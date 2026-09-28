package streams

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/smtp"
	"strings"
	"testing"
	"time"
)

func TestReplyEnvelopeExactBoundsAndFragmentation(t *testing.T) {
	line := "250 " + strings.Repeat("x", maxReplyLine-6) + "\r\n"
	multi := strings.Repeat("250-"+strings.Repeat("x", maxReplyLine-6)+"\r\n", maxReplyLines-1) + line
	for name, text := range map[string]string{"bare": "220\r\n", "line": line, "multiline": multi, "successive": multi + line} {
		for _, chunk := range []int{1, 2, 7, 512, 4096} {
			t.Run(fmt.Sprintf("%s/%d", name, chunk), func(t *testing.T) {
				var g smtpReplyEnvelope
				for offset := 0; offset < len(text); {
					end := min(offset+chunk, len(text))
					n, err := g.accept([]byte(text[offset:end]))
					if err != nil || n != end-offset {
						t.Fatalf("valid fragmented reply: %d/%d %v", n, end-offset, err)
					}
					offset = end
				}
				if g.lineBytes != 0 || g.replyBytes != 0 || g.continued {
					t.Fatal("reply state did not reset")
				}
			})
		}
	}
}

func TestReplyEnvelopeRejectsOversizeAndNonSMTPContinuations(t *testing.T) {
	for name, text := range map[string]string{
		"long-line":        "220 " + strings.Repeat("x", maxReplyLine-5) + "\r\n",
		"too-many-lines":   strings.Repeat("250-x\r\n", maxReplyLines) + "250 done\r\n",
		"mixed-code":       "250-start\r\n550 end\r\n",
		"ftp-continuation": "250-start\r\nunprefixed text\r\n250 end\r\n",
		"bare-lf":          "220 invalid\n",
		"bad-code":         "xyz greeting\r\n",
	} {
		for _, chunk := range []int{1, 7, 4096} {
			t.Run(fmt.Sprintf("%s/%d", name, chunk), func(t *testing.T) {
				var g smtpReplyEnvelope
				var err error
				for offset := 0; offset < len(text) && err == nil; offset += chunk {
					_, err = g.accept([]byte(text[offset:min(offset+chunk, len(text))]))
				}
				if !errors.Is(err, errReplyEnvelope) {
					t.Fatal("hostile reply accepted")
				}
				if n, err := g.accept([]byte("220 recovery\r\n")); n != 0 || !errors.Is(err, errReplyEnvelope) {
					t.Fatal("terminal envelope failure was reset")
				}
			})
		}
	}
}

// Negative evidence: the real standard library accepts this oversized greeting
// without the envelope. Transport-byte ceilings alone do not enforce SMTP's
// line profile. Closing each pipe and joining the writer bounds every branch.
func TestRealSMTPParserNeedsExplicitReplyEnvelope(t *testing.T) {
	greeting := "220 " + strings.Repeat("x", maxReplyLine-5) + "\r\n"
	for _, guarded := range []bool{false, true} {
		t.Run(fmt.Sprint(guarded), func(t *testing.T) {
			clientSide, peerSide := net.Pipe()
			done := make(chan struct{})
			go func() {
				defer close(done)
				defer peerSide.Close()
				_ = peerSide.SetDeadline(time.Now().Add(time.Second))
				_, _ = io.WriteString(peerSide, greeting)
			}()
			c := &boundedConn{Conn: clientSide, deadline: time.Now().Add(time.Second), idle: time.Second, chunk: 7, limit: 16384}
			var transport net.Conn = c
			if guarded {
				transport = &smtpReplyConn{Conn: c}
			}
			client, err := smtp.NewClient(transport, "mail.test")
			_ = clientSide.Close()
			<-done
			if guarded {
				if err == nil || client != nil || c.attempted {
					t.Fatal("envelope did not fail before any SMTP command")
				}
				if _, err = transport.Write([]byte("HELO capsule.test\r\n")); !errors.Is(err, errReplyEnvelope) || c.attempted {
					t.Fatal("fallback performed I/O after envelope failure")
				}
			} else if err != nil {
				t.Fatalf("negative parser observation changed: %v", err)
			}
		})
	}
}

func TestReplyParserReservationRejectsBeforeConnect(t *testing.T) {
	cfg := FixtureConfig("127.0.0.1:25")
	body := []byte("Subject: probe\r\n\r\nx\r\n")
	cfg.MaxLiveBytes = handleMetadata + operationMetadata + kernelReservation + len(body) - 1
	p, err := New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	h, err := p.Bind(FixtureGrant(cfg.Address, "a"), time.Now().Add(time.Second))
	if err != nil {
		t.Fatal(err)
	}
	out := p.Send(context.Background(), h, Message{"sender@example.test", "recipient@example.test", body})
	if out.Code != "exhausted" || out.MayHaveApplied || p.Snapshot().ConnectAttempts != 0 {
		t.Fatalf("parser storage was not prepaid: %+v", out)
	}
	if err = p.Close(h); err != nil {
		t.Fatal(err)
	}
	if s := p.Snapshot(); s.Handles != 0 || s.Active != 0 || s.Bytes != 0 {
		t.Fatal(s)
	}
}
