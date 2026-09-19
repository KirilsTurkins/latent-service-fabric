package transport

import (
	"context"
	"errors"
	"math"
	"net"
	"net/http"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"golang.org/x/net/http2"
	"latent.dev/sdk/go/internal/rpc/controlv1"
	"latent.dev/sdk/go/internal/rpc/invocationv1"
	"latent.dev/sdk/go/profile"
)

func TestCancellationQueueAndReservedRecovery(test *testing.T) {
	started := make(chan struct{}, 1)
	retired := make(chan struct{}, 1)
	peer := newPeer(test, func(writer http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case invocationv1.InvocationService_Invoke_FullMethodName:
			wire := &invocationv1.InvokeRequest{}
			decodePeerRequest(test, request, wire)
			started <- struct{}{}
			<-request.Context().Done()
			retired <- struct{}{}
		case invocationv1.InvocationService_Cancel_FullMethodName:
			wire := &invocationv1.CancelRequest{}
			decodePeerRequest(test, request, wire)
			if wire.ActivationId != "held-a" {
				test.Error("recovery changed the original identity")
			}
			peerReply(writer, &invocationv1.CancelResponse{Disposition: invocationv1.CancelDisposition_CANCEL_DISPOSITION_ACCEPTED})
		case invocationv1.InvocationService_GetActivation_FullMethodName:
			wire := &invocationv1.GetActivationRequest{}
			decodePeerRequest(test, request, wire)
			peerReply(writer, &invocationv1.ActivationStatus{ActivationId: wire.ActivationId, Phase: "running"})
		default:
			test.Error("queued or overflowing request escaped admission")
		}
	})
	client := testClient(test, peer, func(config *Config) { config.MaxInFlight = 2; config.ReservedRecovery = 1; config.MaxQueued = 1 })
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	result := make(chan error, 1)
	go func() {
		_, failure := client.Invoke(ctx, invokeRequest("held-a"), profile.CallOptions{})
		result <- failure
	}()
	select {
	case <-started:
	case <-time.After(2 * time.Second):
		test.Fatal("held invocation did not start")
	}
	queuedContext, cancelQueued := context.WithCancel(context.Background())
	defer cancelQueued()
	queued := make(chan error, 1)
	go func() {
		_, failure := client.GetPolicy(queuedContext, profile.GetPolicyRequest{Id: "queued", RecordKind: profile.CapabilityPolicyRecordKindPolicy}, profile.CallOptions{})
		queued <- failure
	}()
	waitFor(test, func() bool { client.mutex.Lock(); defer client.mutex.Unlock(); return client.queued == 1 })
	_, failure := client.GetPolicy(context.Background(), profile.GetPolicyRequest{Id: "overflow", RecordKind: profile.CapabilityPolicyRecordKindPolicy}, profile.CallOptions{})
	assertFailure(test, failure, profile.FailureCategoryLimit, false)
	status, failure := client.GetActivation(context.Background(), profile.GetActivationRequest{ActivationId: "held-a"}, profile.CallOptions{})
	if failure != nil || status.Value.Phase != "running" {
		test.Fatalf("reserved live status failed: %v", failure)
	}
	cancelQueued()
	assertFailure(test, boundedResult(test, queued), profile.FailureCategoryLocalCancelled, false)
	cancel()
	failure = boundedResult(test, result)
	detail := assertFailure(test, failure, profile.FailureCategoryLocalCancelled, true)
	if !errors.Is(failure, context.Canceled) || detail.Identity.ActivationId == nil || *detail.Identity.ActivationId != "held-a" {
		test.Fatal("native cancellation or recovery identity lost")
	}
	cancelled, failure := client.Cancel(context.Background(), profile.CancelRequest{ActivationId: "held-a", Reason: "explicit separate call"}, profile.CallOptions{})
	if failure != nil || cancelled.Value.Disposition != profile.CancelDispositionAccepted {
		test.Fatalf("explicit cancellation unusable after local cancellation: %v", failure)
	}
	select {
	case <-retired:
	case <-time.After(2 * time.Second):
		test.Fatal("cancelled peer stream not retired")
	}
	if peer.requests.Load() != 3 || peer.accepted.Load() != 1 {
		test.Fatal("local cancellation issued a hidden Cancel, retry or connection")
	}
}

func TestAbsoluteDeadlineAndInvalidTimeoutNeverDispatch(test *testing.T) {
	peer := newPeer(test, func(writer http.ResponseWriter, request *http.Request) { <-request.Context().Done() })
	client := testClient(test, peer)
	for _, timeout := range []uint64{0, math.MaxUint64} {
		_, failure := client.Invoke(context.Background(), invokeRequest("deadline-a"), profile.CallOptions{TimeoutMillis: &timeout})
		category := profile.FailureCategoryDeadline
		if timeout != 0 {
			category = profile.FailureCategoryInvalidRequest
		}
		assertFailure(test, failure, category, false)
	}
	if peer.requests.Load() != 0 {
		test.Fatal("expired or overflowing deadline dispatched")
	}
	started := time.Now()
	_, failure := client.Invoke(context.Background(), invokeRequest("deadline-a"), profile.CallOptions{TimeoutMillis: pointer(uint64(50))})
	assertFailure(test, failure, profile.FailureCategoryDeadline, true)
	if !errors.Is(failure, context.DeadlineExceeded) || time.Since(started) > time.Second {
		test.Fatal("absolute local deadline was extended")
	}
}

func TestRecoveryCapacityTracksPeerStreamLimit(test *testing.T) {
	started := make(chan struct{}, 1)
	peer := newPeer(test, func(writer http.ResponseWriter, request *http.Request) {
		if request.URL.Path == invocationv1.InvocationService_Invoke_FullMethodName {
			started <- struct{}{}
			<-request.Context().Done()
			return
		}
		peerReply(writer, &invocationv1.ActivationStatus{ActivationId: "held-a", Phase: "running"})
	}, func(server *http2.Server) { server.MaxConcurrentStreams = 2 })
	client := testClient(test, peer, func(config *Config) { config.MaxInFlight = 4; config.ReservedRecovery = 1 })
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	result := make(chan error, 2)
	go func() {
		_, failure := client.Invoke(ctx, invokeRequest("held-a"), profile.CallOptions{})
		result <- failure
	}()
	select {
	case <-started:
	case <-time.After(2 * time.Second):
		test.Fatal("lower-capacity peer did not admit the first call")
	}
	go func() {
		_, failure := client.Invoke(ctx, invokeRequest("queued-a"), profile.CallOptions{})
		result <- failure
	}()
	waitFor(test, func() bool { return client.Snapshot().Queued == 1 })
	status, failure := client.GetActivation(context.Background(), profile.GetActivationRequest{ActivationId: "held-a"}, profile.CallOptions{})
	if failure != nil || status.Value.Phase != "running" || peer.requests.Load() != 2 {
		test.Fatalf("normal calls consumed the peer's recovery slot: %v", failure)
	}
	cancel()
	for index := 0; index < 2; index++ {
		if !errors.Is(boundedResult(test, result), context.Canceled) {
			test.Fatal("lower-capacity call owner did not retire")
		}
	}
	config := DefaultConfig(peer.endpoint, fixtureToken)
	_, failure = New(context.Background(), config)
	assertFailure(test, failure, profile.FailureCategoryTransport, false)
}

func TestConcurrentCloseReapsPendingAndQueuedCalls(test *testing.T) {
	var entered atomic.Int64
	peer := newPeer(test, func(writer http.ResponseWriter, request *http.Request) {
		entered.Add(1)
		<-request.Context().Done()
	})
	client := testClient(test, peer, func(config *Config) { config.MaxInFlight = 4; config.ReservedRecovery = 1; config.MaxQueued = 4 })
	results := make(chan error, 7)
	for index := 0; index < 7; index++ {
		go func() {
			_, failure := client.Invoke(context.Background(), invokeRequest("close-a"), profile.CallOptions{})
			results <- failure
		}()
	}
	waitFor(test, func() bool {
		client.mutex.Lock()
		defer client.mutex.Unlock()
		return client.active == 3 && client.queued == 4 && entered.Load() == 3
	})
	var closers sync.WaitGroup
	for index := 0; index < 8; index++ {
		closers.Add(1)
		go func() { defer closers.Done(); _ = client.Close() }()
	}
	for index := 0; index < 7; index++ {
		failure := boundedResult(test, results)
		var detail *profile.ClientFailure
		if !errors.As(failure, &detail) || detail.Category != profile.FailureCategoryTransport {
			test.Fatalf("close hid an outstanding failure: %v", failure)
		}
	}
	closers.Wait()
	client.mutex.Lock()
	if !client.closed || client.active != 0 || client.queued != 0 {
		test.Error("close refunded unfinished call owners")
	}
	client.mutex.Unlock()
	if !client.channel.State().Closed {
		test.Fatal("Close left a usable connection")
	}
	_, failure := client.Cancel(context.Background(), profile.CancelRequest{ActivationId: "close-a"}, profile.CallOptions{})
	assertFailure(test, failure, profile.FailureCategoryTransport, false)
}

func TestFailedStartupAndAdoptedConnectionOwnership(test *testing.T) {
	listener, failure := net.Listen("tcp", "127.0.0.1:0")
	if failure != nil {
		test.Fatal(failure)
	}
	defer listener.Close()
	retired := make(chan error, 1)
	go func() {
		socket, failure := listener.Accept()
		if failure != nil {
			retired <- failure
			return
		}
		defer socket.Close()
		_ = socket.SetReadDeadline(time.Now().Add(2 * time.Second))
		buffer := make([]byte, 1024)
		for {
			if _, failure := socket.Read(buffer); failure != nil {
				retired <- failure
				return
			}
		}
	}()
	config := DefaultConfig("http://"+listener.Addr().String(), fixtureToken)
	config.ConnectTimeout = 40 * time.Millisecond
	_, failure = New(context.Background(), config)
	assertFailure(test, failure, profile.FailureCategoryDeadline, false)
	if failure = boundedResult(test, retired); failure == nil {
		test.Fatal("failed handshake did not close its socket")
	}
	peer := newPeer(test, func(writer http.ResponseWriter, request *http.Request) {
		peerReply(writer, &controlv1.GetPolicyResponse{})
	})
	socket, failure := net.Dial("tcp", peer.listener.Addr().String())
	if failure != nil {
		test.Fatal(failure)
	}
	config = DefaultConfig(peer.endpoint, fixtureToken)
	config.BearerToken = "invalid\ncredential"
	_, failure = AdoptConnection(context.Background(), config, socket.(*net.TCPConn))
	assertFailure(test, failure, profile.FailureCategoryInvalidRequest, false)
	if _, failure = socket.Write([]byte{0}); failure == nil {
		test.Fatal("rejected adopted socket remained caller-owned")
	}
	socket, failure = net.Dial("tcp", peer.listener.Addr().String())
	if failure != nil {
		test.Fatal(failure)
	}
	adopted, failure := AdoptConnection(context.Background(), DefaultConfig(peer.endpoint, fixtureToken), socket.(*net.TCPConn))
	if failure != nil {
		test.Fatal(failure)
	}
	_ = adopted.Close()
	if _, failure = socket.Write([]byte{0}); failure == nil {
		test.Fatal("Close did not retire the adopted socket")
	}
}

func boundedResult(test *testing.T, result <-chan error) error {
	test.Helper()
	select {
	case failure := <-result:
		return failure
	case <-time.After(3 * time.Second):
		test.Fatal("bounded asynchronous call did not retire")
		return nil
	}
}

func assertFailure(test *testing.T, failure error, category profile.FailureCategory, dispatched bool) *profile.ClientFailure {
	test.Helper()
	var detail *profile.ClientFailure
	if !errors.As(failure, &detail) || detail.Category != category || detail.Dispatched != dispatched ||
		(dispatched && detail.Outcome != profile.OutcomeKnowledgeUnknown) || (!dispatched && detail.Outcome != profile.OutcomeKnowledgeNotDispatched) {
		test.Fatalf("wrong bounded failure: category=%v dispatched=%v: %#v", category, dispatched, detail)
	}
	return detail
}
