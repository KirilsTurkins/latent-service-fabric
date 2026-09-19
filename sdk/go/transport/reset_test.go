package transport

import (
	"context"
	"io"
	"net"
	"sync/atomic"
	"testing"
	"time"

	"golang.org/x/net/http2"
	"latent.dev/sdk/go/profile"
)

func TestRefusedStreamIsNeverResubmitted(test *testing.T) {
	listener, failure := net.Listen("tcp", "127.0.0.1:0")
	if failure != nil {
		test.Fatal(failure)
	}
	defer listener.Close()
	var headers atomic.Int64
	finished := make(chan struct{})
	go func() {
		defer close(finished)
		socket, failure := listener.Accept()
		if failure != nil {
			return
		}
		defer socket.Close()
		_ = socket.SetDeadline(time.Now().Add(3 * time.Second))
		preface := make([]byte, len(http2.ClientPreface))
		if _, failure := io.ReadFull(socket, preface); failure != nil || string(preface) != http2.ClientPreface {
			return
		}
		framer := http2.NewFramer(socket, socket)
		framer.SetMaxReadFrameSize(16 * 1024)
		if framer.WriteSettings(http2.Setting{ID: http2.SettingMaxConcurrentStreams, Val: 8}) != nil {
			return
		}
		for {
			value, failure := framer.ReadFrame()
			if failure != nil {
				return
			}
			switch value := value.(type) {
			case *http2.SettingsFrame:
				if !value.IsAck() {
					_ = framer.WriteSettingsAck()
				}
			case *http2.PingFrame:
				if !value.IsAck() {
					_ = framer.WritePing(true, value.Data)
				}
			case *http2.HeadersFrame:
				headers.Add(1)
				_ = framer.WriteRSTStream(value.StreamID, http2.ErrCodeRefusedStream)
			}
		}
	}()
	client, failure := New(context.Background(), DefaultConfig("http://"+listener.Addr().String(), fixtureToken))
	if failure != nil {
		test.Fatal(failure)
	}
	_, failure = client.ApplyPolicy(context.Background(), policyRequest(), profile.CallOptions{})
	assertFailure(test, failure, profile.FailureCategoryTransport, true)
	if failure := client.Close(); failure != nil {
		test.Fatal(failure)
	}
	select {
	case <-finished:
	case <-time.After(3 * time.Second):
		test.Fatal("controlled reset peer did not retire")
	}
	if headers.Load() != 1 {
		test.Fatal("REFUSED_STREAM caused an automatic RPC resubmission")
	}
}
