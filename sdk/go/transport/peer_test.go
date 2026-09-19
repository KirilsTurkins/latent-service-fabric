package transport

import (
	"bytes"
	"context"
	"encoding/binary"
	"io"
	"log"
	"math"
	"net"
	"net/http"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"google.golang.org/protobuf/proto"
	"latent.dev/sdk/go/internal/rpc/invocationv1"
	"latent.dev/sdk/go/profile"
)

const fixtureToken = "LSF-GO-CONTROLLED-PEER-TEST-ONLY"

type controlledPeer struct {
	listener net.Listener
	endpoint string
	accepted atomic.Int64
	requests atomic.Int64
	mutex    sync.Mutex
	sockets  []net.Conn
	live     map[net.Conn]bool
	wait     sync.WaitGroup
	closed   chan struct{}
}

type peerListener struct {
	net.Listener
	peer *controlledPeer
}

func (listener *peerListener) Accept() (net.Conn, error) {
	socket, failure := listener.Listener.Accept()
	if failure != nil {
		return nil, failure
	}
	if listener.peer.accepted.Add(1) > 16 {
		_ = socket.Close()
		return nil, net.ErrClosed
	}
	listener.peer.mutex.Lock()
	listener.peer.sockets = append(listener.peer.sockets, socket)
	listener.peer.live[socket] = true
	listener.peer.wait.Add(1)
	listener.peer.mutex.Unlock()
	return socket, nil
}

func newPeer(test *testing.T, handler http.HandlerFunc, configure ...func(*http.HTTP2Config)) *controlledPeer {
	test.Helper()
	listener, failure := net.Listen("tcp", "127.0.0.1:0")
	if failure != nil {
		test.Fatal(failure)
	}
	peer := &controlledPeer{listener: listener, endpoint: "http://" + listener.Addr().String(),
		closed: make(chan struct{}), live: make(map[net.Conn]bool)}
	protocols := &http.Protocols{}
	protocols.SetUnencryptedHTTP2(true)
	http2Config := &http.HTTP2Config{MaxConcurrentStreams: 32, MaxReadFrameSize: 16 * 1024,
		MaxReceiveBufferPerConnection: 64 * 1024, MaxReceiveBufferPerStream: 64 * 1024}
	for _, modify := range configure {
		modify(http2Config)
	}
	server := &http.Server{
		Protocols: protocols, HTTP2: http2Config, MaxHeaderBytes: 32 * 1024,
		ReadHeaderTimeout: 2 * time.Second, ReadTimeout: 5 * time.Second,
		WriteTimeout: 5 * time.Second, IdleTimeout: 5 * time.Second,
		ErrorLog: log.New(io.Discard, "", 0),
		Handler: http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
			peer.requests.Add(1)
			if request.ProtoMajor != 2 {
				test.Error("controlled peer accepted a non-HTTP/2 request")
			}
			handler(writer, request)
		}),
		ConnState: func(socket net.Conn, state http.ConnState) {
			if state != http.StateClosed && state != http.StateHijacked {
				return
			}
			peer.mutex.Lock()
			if peer.live[socket] {
				delete(peer.live, socket)
				peer.wait.Done()
			}
			peer.mutex.Unlock()
		},
	}
	peer.wait.Add(1)
	go func() {
		defer peer.wait.Done()
		_ = server.Serve(&peerListener{Listener: listener, peer: peer})
	}()
	test.Cleanup(func() {
		_ = listener.Close()
		_ = server.Close()
		peer.mutex.Lock()
		for _, socket := range peer.sockets {
			_ = socket.Close()
		}
		peer.mutex.Unlock()
		go func() { peer.wait.Wait(); close(peer.closed) }()
		select {
		case <-peer.closed:
		case <-time.After(3 * time.Second):
			test.Error("controlled peer did not retire")
		}
	})
	return peer
}

func testClient(test *testing.T, peer *controlledPeer, configure ...func(*Config)) *Client {
	test.Helper()
	config := DefaultConfig(peer.endpoint, fixtureToken)
	for _, change := range configure {
		change(&config)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	client, failure := New(ctx, config)
	if failure != nil {
		test.Fatal(failure)
	}
	test.Cleanup(func() {
		if failure := client.Close(); failure != nil {
			test.Error(failure)
		}
		if !client.Snapshot().Reaped {
			test.Error("client retained actual transport owners after Close")
		}
	})
	return client
}

func decodePeerRequest(test *testing.T, request *http.Request, target proto.Message) {
	test.Helper()
	if request.Method != http.MethodPost || request.Header.Get("authorization") != "Bearer "+fixtureToken ||
		request.Header.Get("content-type") != "application/grpc+proto" || request.Header.Get("grpc-timeout") == "" {
		test.Error("explicit authenticated protobuf request headers missing")
	}
	packet, failure := io.ReadAll(io.LimitReader(request.Body, 4*1024*1024+6))
	if failure != nil {
		test.Error("controlled request read failed")
		return
	}
	payload, present, failure := readUnary(bytes.NewReader(packet), 4*1024*1024)
	if failure != nil || !present || proto.Unmarshal(payload, target) != nil {
		test.Error("controlled request was not one protobuf message")
	}
}

func peerReply(writer http.ResponseWriter, value proto.Message) {
	payload, failure := proto.Marshal(value)
	if failure != nil {
		panic("controlled peer encoding failed")
	}
	peerBytes(writer, frame(payload), "0")
}

func frame(payload []byte) []byte {
	packet := make([]byte, len(payload)+5)
	binary.BigEndian.PutUint32(packet[1:5], uint32(len(payload)))
	copy(packet[5:], payload)
	return packet
}

func peerBytes(writer http.ResponseWriter, packet []byte, status string) {
	writer.Header().Set("content-type", "application/grpc+proto")
	writer.Header().Add("Trailer", "Grpc-Status")
	writer.WriteHeader(http.StatusOK)
	_, _ = writer.Write(packet)
	writer.Header().Set("Grpc-Status", status)
}

func peerFailure(writer http.ResponseWriter, status string) {
	writer.Header().Set("content-type", "application/grpc")
	writer.Header().Set("grpc-status", status)
	writer.WriteHeader(http.StatusOK)
}

func pointer[Value any](value Value) *Value { return &value }

func invokeRequest(identity string) profile.InvokeRequest {
	return profile.InvokeRequest{ActivationId: pointer(identity),
		Target:  &profile.InvocationTarget{Tenant: "tenant-a", Service: "echo", Contract: "test:echo/api@1.0.0", Function: "run"},
		Payload: []byte{0, 255, 1, 128}, MediaType: "application/octet-stream",
		Budget: &profile.ResourceBudget{CpuFuel: math.MaxUint64, WallTimeLimitMillis: pointer(uint64(0))}}
}

func successWire(identity string) *invocationv1.InvokeResponse {
	return &invocationv1.InvokeResponse{ActivationId: identity, RevisionId: "revision-a",
		ReleaseDigest: "sha256:" + strings.Repeat("a", 64), PublicationId: pointer("publication:sha256:" + strings.Repeat("b", 64)),
		RouteGeneration: math.MaxUint64, Consumption: &invocationv1.BudgetConsumption{CpuFuel: math.MaxUint64},
		Result: &invocationv1.InvokeResponse_Success{Success: &invocationv1.Success{Payload: []byte{0, 255, 1, 128}, MediaType: "application/octet-stream", CommittedStateVersion: pointer("")}}}
}

func waitFor(test *testing.T, predicate func() bool) {
	test.Helper()
	deadline := time.NewTimer(2 * time.Second)
	defer deadline.Stop()
	ticker := time.NewTicker(time.Millisecond)
	defer ticker.Stop()
	for !predicate() {
		select {
		case <-deadline.C:
			test.Fatal("bounded fixture condition did not occur")
		case <-ticker.C:
		}
	}
}
