package transport

import (
	"context"
	"encoding/binary"
	"io"
	"net"
	"sync/atomic"
	"testing"
	"time"

	"latent.dev/sdk/go/profile"
)

const http2Preface = "PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"

func testFrame(writer io.Writer, kind, flags byte, stream uint32, payload []byte) error {
	packet := make([]byte, 9+len(payload))
	packet[0] = byte(len(payload) >> 16)
	packet[1] = byte(len(payload) >> 8)
	packet[2] = byte(len(payload))
	packet[3] = kind
	packet[4] = flags
	binary.BigEndian.PutUint32(packet[5:9], stream)
	copy(packet[9:], payload)
	_, failure := writer.Write(packet)
	return failure
}

func TestRefusedStreamIsNeverResubmitted(test *testing.T) {
	for _, scenario := range []string{"refused-stream", "goaway-unprocessed"} {
		test.Run(scenario, func(test *testing.T) {
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
				preface := make([]byte, len(http2Preface))
				if _, failure := io.ReadFull(socket, preface); failure != nil || string(preface) != http2Preface {
					return
				}
				if testFrame(socket, 4, 0, 0, []byte{0, 3, 0, 0, 0, 8}) != nil {
					return
				}
				for {
					var header [9]byte
					if _, failure := io.ReadFull(socket, header[:]); failure != nil {
						return
					}
					length := int(header[0])<<16 | int(header[1])<<8 | int(header[2])
					if length > 16*1024 {
						return
					}
					payload := make([]byte, length)
					if _, failure := io.ReadFull(socket, payload); failure != nil {
						return
					}
					switch header[3] {
					case 4:
						if header[4]&1 == 0 {
							_ = testFrame(socket, 4, 1, 0, nil)
						}
					case 6:
						if header[4]&1 == 0 {
							_ = testFrame(socket, 6, 1, 0, payload)
						}
					case 1:
						headers.Add(1)
						if scenario == "refused-stream" {
							_ = testFrame(socket, 3, 0, binary.BigEndian.Uint32(header[5:])&0x7fffffff, []byte{0, 0, 0, 7})
						} else {
							_ = testFrame(socket, 7, 0, 0, make([]byte, 8))
						}
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
				test.Fatal("peer refusal caused an automatic RPC resubmission")
			}
		})
	}
}
