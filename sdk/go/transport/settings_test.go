package transport

import (
	"bytes"
	"context"
	"math"
	"testing"

	"latent.dev/sdk/go/profile"
)

func TestSettingsFragmentationAndPeerCapacityUpdates(test *testing.T) {
	var sequence bytes.Buffer
	_ = testFrame(&sequence, 4, 0, 0, []byte{0, 3, 0, 0, 0, 8, 0, 4, 0, 1, 0, 0})
	_ = testFrame(&sequence, 4, 1, 0, nil)
	_ = testFrame(&sequence, 0, 0, 1, []byte{0, 255, 1, 128})
	_ = testFrame(&sequence, 4, 0, 0, []byte{0, 3, 0, 0, 0, 2})
	for fragment := 1; fragment <= sequence.Len(); fragment++ {
		settings := newPeerSettings()
		remaining := sequence.Bytes()
		for len(remaining) != 0 {
			count := min(fragment, len(remaining))
			if failure := settings.observe(remaining[:count]); failure != nil {
				test.Fatal(failure)
			}
			remaining = remaining[count:]
		}
		if settings.maximum.Load() != 2 || settings.headerBytes != 0 || settings.settingBytes != 0 {
			test.Fatal("fragmented settings lost the peer concurrency bound")
		}
		select {
		case <-settings.ready:
		default:
			test.Fatal("settings handshake never completed")
		}
	}
	var empty bytes.Buffer
	_ = testFrame(&empty, 4, 0, 0, nil)
	settings := newPeerSettings()
	if failure := settings.observe(empty.Bytes()); failure != nil || settings.maximum.Load() != math.MaxUint32 {
		test.Fatal("absent peer capacity did not retain HTTP/2 default semantics")
	}
}

func TestInvalidSettingsFailBeforePayloadAllocation(test *testing.T) {
	for _, scenario := range []struct {
		name    string
		kind    byte
		flags   byte
		stream  uint32
		payload []byte
	}{
		{name: "headers-first", kind: 1, stream: 1},
		{name: "ack-first", kind: 4, flags: 1},
		{name: "settings-on-stream", kind: 4, stream: 1},
		{name: "partial-setting", kind: 4, payload: []byte{0}},
	} {
		test.Run(scenario.name, func(test *testing.T) {
			var packet bytes.Buffer
			_ = testFrame(&packet, scenario.kind, scenario.flags, scenario.stream, scenario.payload)
			if failure := newPeerSettings().observe(packet.Bytes()); failure == nil {
				test.Fatal("invalid peer settings accepted")
			}
		})
	}
	if failure := newPeerSettings().observe([]byte{0, 64, 1, 4, 0, 0, 0, 0, 0}); failure == nil {
		test.Fatal("oversized frame prefix entered the receive buffer")
	}
}

func TestAmbientHTTP2LoggingIsRejectedBeforeDial(test *testing.T) {
	test.Setenv("GODEBUG", "http2debug=2")
	_, failure := New(context.Background(), DefaultConfig("http://127.0.0.1:1", fixtureToken))
	assertFailure(test, failure, profile.FailureCategoryInvalidRequest, false)
	test.Setenv("GODEBUG", "http2debug=0")
	if http2DebugEnabled() {
		test.Fatal("explicitly disabled HTTP/2 logging was rejected")
	}
}
