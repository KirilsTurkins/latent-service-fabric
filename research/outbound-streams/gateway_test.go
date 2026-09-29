package streams

import (
	"bufio"
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"errors"
	"io"
	"math/big"
	"net"
	"net/netip"
	"strings"
	"sync"
	"testing"
	"time"
)

// This is a bounded real TCP SMTP protocol peer, not a fake SMTP client. It
// records acceptance before optionally losing the final reply. No external mail
// is sent. Channels witness protocol readiness; timers are failure watchdogs.
type peer struct {
	listener             net.Listener
	mode                 string
	tls                  *tls.Config
	mu                   sync.Mutex
	connections          []net.Conn
	accepted, messages   int
	connected, committed chan struct{}
	release, acceptDone  chan struct{}
	workers              sync.WaitGroup
}

func newPeer(t *testing.T, mode string, tlsConfig *tls.Config) *peer {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	p := &peer{listener: listener, mode: mode, tls: tlsConfig, connected: make(chan struct{}, 16),
		committed: make(chan struct{}, 16), release: make(chan struct{}), acceptDone: make(chan struct{})}
	go func() {
		defer close(p.acceptDone)
		for {
			c, err := listener.Accept()
			if err != nil {
				return
			}
			p.mu.Lock()
			if len(p.connections) == 16 {
				p.mu.Unlock()
				_ = c.Close()
				return
			}
			p.connections = append(p.connections, c)
			p.accepted++
			p.mu.Unlock()
			p.connected <- struct{}{}
			p.workers.Add(1)
			go func() { defer p.workers.Done(); p.serve(c) }()
		}
	}()
	t.Cleanup(func() {
		_ = listener.Close()
		<-p.acceptDone
		close(p.release)
		p.mu.Lock()
		for _, c := range p.connections {
			_ = c.Close()
		}
		p.mu.Unlock()
		done := make(chan struct{})
		go func() { p.workers.Wait(); close(done) }()
		await(t, done)
	})
	return p
}
func (p *peer) address() string    { return p.listener.Addr().String() }
func (p *peer) counts() (int, int) { p.mu.Lock(); defer p.mu.Unlock(); return p.accepted, p.messages }
func (p *peer) serve(raw net.Conn) {
	defer raw.Close()
	_ = raw.SetDeadline(time.Now().Add(4 * time.Second))
	var c net.Conn = raw
	if p.tls != nil {
		secured := tls.Server(raw, p.tls)
		if secured.Handshake() != nil {
			return
		}
		c = secured
	}
	if p.mode == "stall-greeting" {
		<-p.release
		return
	}
	if p.mode == "flood-greeting" {
		_, _ = io.WriteString(c, strings.Repeat("x", 20000))
		return
	}
	write := func(s string) bool { _, err := io.WriteString(c, s); return err == nil }
	if !write("220 mail.test fixture\r\n") {
		return
	}
	r := bufio.NewReaderSize(c, 8192)
	for commands := 0; commands < 12; commands++ {
		line, err := r.ReadSlice('\n')
		if err != nil {
			return
		}
		cmd := strings.TrimSpace(string(line))
		switch {
		case strings.HasPrefix(cmd, "EHLO ") || strings.HasPrefix(cmd, "HELO "):
			if !write("250 mail.test\r\n") {
				return
			}
		case strings.HasPrefix(cmd, "MAIL FROM:") || strings.HasPrefix(cmd, "RCPT TO:"):
			if !write("250 ok\r\n") {
				return
			}
		case cmd == "DATA":
			if !write("354 continue\r\n") {
				return
			}
			size := 0
			for {
				line, err = r.ReadSlice('\n')
				if err != nil {
					return
				}
				size += len(line)
				if size > maxBody+1024 {
					return
				}
				if bytes.Equal(line, []byte(".\r\n")) {
					break
				}
			}
			if p.mode == "reject-data" {
				write("550 secret-peer-detail\r\n")
				return
			}
			p.mu.Lock()
			p.messages++
			p.mu.Unlock()
			p.committed <- struct{}{}
			if p.mode == "drop-data" {
				return
			}
			if p.mode == "stall-data" {
				<-p.release
				return
			}
			if !write("250 queued\r\n") {
				return
			}
		default:
			write("500 command\r\n")
			return
		}
	}
}
func await(t *testing.T, ch <-chan struct{}) {
	t.Helper()
	select {
	case <-ch:
	case <-time.After(5 * time.Second):
		t.Fatal("readiness/cleanup watchdog")
	}
}
func provider(t *testing.T, p *peer, edit func(*Config)) *Provider {
	t.Helper()
	cfg := FixtureConfig(p.address())
	if edit != nil {
		edit(&cfg)
	}
	got, err := New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	return got
}
func bind(t *testing.T, p *Provider, tenant string) *Handle {
	t.Helper()
	h, err := p.Bind(FixtureGrant(p.cfg.Address, tenant), time.Now().Add(3*time.Second))
	if err != nil {
		t.Fatal(err)
	}
	return h
}
func message() Message {
	return Message{"sender@example.test", "recipient@example.test", []byte("Subject: fixture\r\n\r\nhello\r\n")}
}
func clean(t *testing.T, p *Provider) {
	t.Helper()
	s := p.Snapshot()
	if s.Handles != 0 || s.Active != 0 || s.Bytes != 0 {
		t.Fatalf("live owners after retirement: %+v", s)
	}
}
func outcome(t *testing.T, o Outcome, code string, may bool) {
	t.Helper()
	if o.Code != code || o.MayHaveApplied != may {
		t.Fatalf("outcome %+v; want %s/%t", o, code, may)
	}
}
func sendAsync(p *Provider, ctx context.Context, h *Handle) <-chan Outcome {
	result := make(chan Outcome, 1)
	go func() { result <- p.Send(ctx, h, message()) }()
	return result
}
func receive(t *testing.T, ch <-chan Outcome) Outcome {
	t.Helper()
	select {
	case out := <-ch:
		return out
	case <-time.After(5 * time.Second):
		t.Fatal("operation watchdog")
		return Outcome{}
	}
}

func TestRealSMTPPartialIOAndFreshInvocation(t *testing.T) {
	peer := newPeer(t, "normal", nil)
	p := provider(t, peer, nil)
	for i := 0; i < 2; i++ {
		h := bind(t, p, "a")
		outcome(t, p.Send(context.Background(), h, message()), "peer-accepted", true)
		clean(t, p)
		outcome(t, p.Send(context.Background(), h, message()), "invalid-handle", false)
	}
	a, m := peer.counts()
	if a != 2 || m != 2 {
		t.Fatalf("no socket reuse: connections=%d messages=%d", a, m)
	}
	if p.Snapshot().ConnectAttempts != 2 {
		t.Fatal("unexpected replay")
	}
}

func TestDeniedAuthorityNeverConnects(t *testing.T) {
	peer := newPeer(t, "normal", nil)
	p := provider(t, peer, nil)
	for _, change := range []func(*Grant){
		func(g *Grant) { g.Destination = "127.0.0.1:1" },
		func(g *Grant) { g.Provider = "http" },
		func(g *Grant) { g.Operation = "POST /mail" },
		func(g *Grant) { g.Epoch = 2 }, func(g *Grant) { g.Tenant = "" },
	} {
		g := FixtureGrant(p.cfg.Address, "a")
		change(&g)
		if _, err := p.Bind(g, time.Now().Add(time.Second)); err == nil {
			t.Fatal("grant accepted")
		}
	}
	if p.Snapshot().ConnectAttempts != 0 {
		t.Fatal("denied work dispatched")
	}
	clean(t, p)
	if a, _ := peer.counts(); a != 0 {
		t.Fatal("denied destination contacted")
	}
}

func TestLiteralAndSpecialAddressPolicy(t *testing.T) {
	for _, text := range []string{"localhost:25", "127.0.0.1:0", "smtp://127.0.0.1:25", "user@127.0.0.1:25", "127.0.0.1:*"} {
		if ValidateEndpointText(text) {
			t.Fatal(text)
		}
	}
	for _, ip := range []string{"8.8.8.8", "0.0.0.0", "10.0.0.1", "169.254.169.254", "192.0.2.1", "100.64.0.1", "224.0.0.1", "::", "::1", "::ffff:127.0.0.1", "2001:db8::1", "2002::1"} {
		if addressAllowed(netip.MustParseAddr(ip), false) {
			t.Fatal(ip)
		}
	}
	if !addressAllowed(netip.MustParseAddr("::ffff:127.0.0.1"), true) {
		t.Fatal("mapped address identity")
	}
	cfg := FixtureConfig("127.0.0.1:25")
	cfg.LoopbackFixture = false
	if _, err := New(cfg); err == nil {
		t.Fatal("missing special-address exception")
	}
}

func TestForgedForeignAndClosedHandles(t *testing.T) {
	peer := newPeer(t, "normal", nil)
	p := provider(t, peer, nil)
	other := provider(t, peer, nil)
	h := bind(t, p, "a")
	copy := *h
	outcome(t, p.Send(context.Background(), &copy, message()), "invalid-handle", false)
	outcome(t, other.Send(context.Background(), h, message()), "invalid-handle", false)
	if err := p.Close(h); err != nil {
		t.Fatal(err)
	}
	if err := p.Close(h); err == nil {
		t.Fatal("double close")
	}
	outcome(t, p.Send(context.Background(), h, message()), "invalid-handle", false)
	clean(t, p)
	clean(t, other)
}

func TestHandleAndTenantLimits(t *testing.T) {
	peer := newPeer(t, "normal", nil)
	p := provider(t, peer, nil)
	a := bind(t, p, "a")
	if _, err := p.Bind(FixtureGrant(p.cfg.Address, "a"), time.Now().Add(time.Second)); err == nil {
		t.Fatal("tenant cap")
	}
	b := bind(t, p, "b")
	if _, err := p.Bind(FixtureGrant(p.cfg.Address, "c"), time.Now().Add(time.Second)); err == nil {
		t.Fatal("provider cap")
	}
	_ = p.Close(a)
	_ = p.Close(b)
	clean(t, p)
	outcome(t, p.Send(context.Background(), bind(t, p, "a"), message()), "peer-accepted", true)
	clean(t, p)
}

func TestByteAndAuditExhaustionBeforeConnect(t *testing.T) {
	peer := newPeer(t, "normal", nil)
	p := provider(t, peer, func(c *Config) { c.MaxLiveBytes = handleMetadata })
	h := bind(t, p, "a")
	outcome(t, p.Send(context.Background(), h, message()), "exhausted", false)
	if p.Snapshot().ConnectAttempts != 0 {
		t.Fatal("byte denial dispatched")
	}
	_ = p.Close(h)
	clean(t, p)
	p = provider(t, peer, func(c *Config) { c.MaxAudit = 1 })
	outcome(t, p.Send(context.Background(), bind(t, p, "a"), message()), "peer-accepted", true)
	h = bind(t, p, "a")
	outcome(t, p.Send(context.Background(), h, message()), "exhausted", false)
	if p.Snapshot().ConnectAttempts != 1 {
		t.Fatal("audit denial dispatched")
	}
	_ = p.Close(h)
	clean(t, p)
}

func TestInvalidInputAndCancelledBeforeDispatch(t *testing.T) {
	peer := newPeer(t, "normal", nil)
	p := provider(t, peer, nil)
	h := bind(t, p, "a")
	m := message()
	m.From = "sender@example.test\r\nRCPT TO:bad"
	outcome(t, p.Send(context.Background(), h, m), "invalid-input", false)
	m = message()
	m.Body = make([]byte, maxBody+1)
	outcome(t, p.Send(context.Background(), h, m), "invalid-input", false)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	outcome(t, p.Send(ctx, h, message()), "cancelled-before-dispatch", false)
	if p.Snapshot().ConnectAttempts != 0 {
		t.Fatal("pre-dispatch connect")
	}
	_ = p.Close(h)
	clean(t, p)
}

func TestRevocationBeforeStart(t *testing.T) {
	peer := newPeer(t, "normal", nil)
	p := provider(t, peer, nil)
	h := bind(t, p, "a")
	p.Revoke()
	outcome(t, p.Send(context.Background(), h, message()), "denied", false)
	if p.Snapshot().ConnectAttempts != 0 {
		t.Fatal("revoked connect")
	}
	_ = p.Close(h)
	clean(t, p)
}

func TestLostResponseDoesNotUndoPeerEffect(t *testing.T) {
	peer := newPeer(t, "drop-data", nil)
	p := provider(t, peer, nil)
	outcome(t, p.Send(context.Background(), bind(t, p, "a"), message()), "uncertain", true)
	a, m := peer.counts()
	if a != 1 || m != 1 {
		t.Fatalf("peer effect %d/%d", a, m)
	}
	clean(t, p)
	if p.Audit()[0].Code != "uncertain" {
		t.Fatal("audit lost uncertainty")
	}
}

func TestPeerStallIsBounded(t *testing.T) {
	peer := newPeer(t, "stall-data", nil)
	p := provider(t, peer, func(c *Config) { c.Idle = 80 * time.Millisecond })
	outcome(t, p.Send(context.Background(), bind(t, p, "a"), message()), "uncertain", true)
	if _, m := peer.counts(); m != 1 {
		t.Fatal("expected peer effect")
	}
	clean(t, p)
}

func TestCancelActiveHandleRetainsPhysicalOwnerUntilReturn(t *testing.T) {
	peer := newPeer(t, "stall-data", nil)
	p := provider(t, peer, nil)
	retiring, finish := make(chan struct{}), make(chan struct{})
	p.beforeRetire = func() { close(retiring); <-finish }
	defer func() {
		select {
		case <-finish:
		default:
			close(finish)
		}
	}()
	h := bind(t, p, "a")
	ch := sendAsync(p, context.Background(), h)
	await(t, peer.committed)
	s := p.Snapshot()
	if s.Active != 1 || s.Handles != 1 || s.Bytes <= handleMetadata {
		t.Fatalf("lost live owner %+v", s)
	}
	outcome(t, p.Send(context.Background(), h, message()), "invalid-handle", false)
	if err := p.Close(h); err != nil {
		t.Fatal(err)
	}
	await(t, retiring)
	s = p.Snapshot()
	if s.Active != 1 || s.Handles != 1 || s.Bytes <= handleMetadata {
		t.Fatalf("premature refund: %+v", s)
	}
	t.Logf("MEASUREMENT cancelled-before-retirement handles=%d active=%d logicalBytes=%d", s.Handles, s.Active, s.Bytes)
	close(finish)
	outcome(t, receive(t, ch), "uncertain", true)
	clean(t, p)
	if err := p.Close(h); err == nil {
		t.Fatal("stale handle accepted")
	}
}

func TestContextCancellationAndFreshNextInvocation(t *testing.T) {
	peer := newPeer(t, "stall-greeting", nil)
	p := provider(t, peer, nil)
	ctx, cancel := context.WithCancel(context.Background())
	ch := sendAsync(p, ctx, bind(t, p, "a"))
	await(t, peer.connected)
	cancel()
	outcome(t, receive(t, ch), "cancelled-or-deadline", false)
	clean(t, p)
	// A fresh activation reaches the peer with its own connection and can also
	// be reclaimed. Successful post-failure recovery is tested separately below.
	ctx, cancel = context.WithCancel(context.Background())
	ch = sendAsync(p, ctx, bind(t, p, "a"))
	await(t, peer.connected)
	cancel()
	_ = receive(t, ch)
	clean(t, p)
	if a, _ := peer.counts(); a != 2 {
		t.Fatal("fresh socket required")
	}
}

func TestPartialWriteFailureAndSuccessfulFreshInvocation(t *testing.T) {
	peer := newPeer(t, "normal", nil)
	p := provider(t, peer, nil)
	p.faultAfter = 5
	outcome(t, p.Send(context.Background(), bind(t, p, "a"), message()), "uncertain", true)
	clean(t, p)
	if p.Snapshot().ConnectAttempts != 1 {
		t.Fatal("hidden retry")
	}
	p.faultAfter = 0
	outcome(t, p.Send(context.Background(), bind(t, p, "a"), message()), "peer-accepted", true)
	clean(t, p)
	if a, m := peer.counts(); a != 2 || m != 1 {
		t.Fatalf("partial/fresh %d/%d", a, m)
	}
}

func TestBoundedPeerBytesAndRedaction(t *testing.T) {
	peer := newPeer(t, "flood-greeting", nil)
	p := provider(t, peer, func(c *Config) { c.WireLimit = 64 })
	outcome(t, p.Send(context.Background(), bind(t, p, "a"), message()), "transport-failed", false)
	clean(t, p)
	peer2 := newPeer(t, "reject-data", nil)
	p2 := provider(t, peer2, nil)
	out := p2.Send(context.Background(), bind(t, p2, "a"), message())
	outcome(t, out, "uncertain", true)
	for _, entry := range p2.Audit() {
		if strings.Contains(entry.Code, "secret") {
			t.Fatal("peer data leaked")
		}
	}
	clean(t, p2)
}

func certificates(t *testing.T, name string) (*tls.Config, *x509.CertPool) {
	t.Helper()
	pub, key, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	cert := &x509.Certificate{SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: name}, DNSNames: []string{name},
		NotBefore: time.Now().Add(-time.Minute), NotAfter: time.Now().Add(time.Hour),
		KeyUsage:    x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign,
		ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}, IsCA: true, BasicConstraintsValid: true}
	der, err := x509.CreateCertificate(rand.Reader, cert, cert, pub, key)
	if err != nil {
		t.Fatal(err)
	}
	parsed, err := x509.ParseCertificate(der)
	if err != nil {
		t.Fatal(err)
	}
	roots := x509.NewCertPool()
	roots.AddCert(parsed)
	return &tls.Config{Certificates: []tls.Certificate{{Certificate: [][]byte{der}, PrivateKey: key}},
		MinVersion: tls.VersionTLS12, SessionTicketsDisabled: true}, roots
}
func TestTLSExplicitTrustAndHostname(t *testing.T) {
	for _, which := range []string{"trusted", "untrusted", "wrong-name"} {
		t.Run(which, func(t *testing.T) {
			name := "mail.test"
			if which == "wrong-name" {
				name = "other.test"
			}
			server, roots := certificates(t, name)
			peer := newPeer(t, "normal", server)
			if which == "untrusted" {
				roots = x509.NewCertPool()
			}
			p := provider(t, peer, func(c *Config) { c.TLS = true; c.Roots = roots })
			got := p.Send(context.Background(), bind(t, p, "a"), message())
			if which == "trusted" {
				outcome(t, got, "peer-accepted", true)
			} else {
				outcome(t, got, "tls-failed", false)
				if _, m := peer.counts(); m != 0 {
					t.Fatal("SMTP bytes before trust")
				}
			}
			clean(t, p)
		})
	}
}

// A tiny injected connection proves actual short syscall results, zero-progress,
// sticky terminal errors and absolute deadline narrowing, without scheduling races.
type shortConn struct {
	written []byte
	calls   int
	zero    bool
	last    time.Time
}

func (c *shortConn) Read(b []byte) (int, error) { return 0, io.EOF }
func (c *shortConn) Write(b []byte) (int, error) {
	c.calls++
	if c.zero {
		return 0, nil
	}
	n := min(2, len(b))
	c.written = append(c.written, b[:n]...)
	return n, nil
}
func (*shortConn) Close() error                         { return nil }
func (*shortConn) LocalAddr() net.Addr                  { return &net.TCPAddr{} }
func (*shortConn) RemoteAddr() net.Addr                 { return &net.TCPAddr{} }
func (c *shortConn) SetDeadline(t time.Time) error      { c.last = t; return nil }
func (c *shortConn) SetReadDeadline(t time.Time) error  { c.last = t; return nil }
func (c *shortConn) SetWriteDeadline(t time.Time) error { c.last = t; return nil }
func TestShortWriteContractStickyFailureAndAbsoluteDeadline(t *testing.T) {
	raw := &shortConn{}
	absolute := time.Now().Add(time.Second)
	c := &boundedConn{Conn: raw, deadline: absolute, idle: time.Hour, chunk: 3, limit: 100}
	n, err := c.Write([]byte("abcdefg"))
	if n != 7 || err != nil || raw.calls != 4 {
		t.Fatalf("%d %v %d", n, err, raw.calls)
	}
	if !raw.last.Equal(absolute) {
		t.Fatal("deadline extended")
	}
	c.faultAfter = 9
	n, err = c.Write([]byte("12345"))
	if n != 2 || !errors.Is(err, errBound) {
		t.Fatalf("%d %v", n, err)
	}
	calls := raw.calls
	_, _ = c.Write([]byte("again"))
	if raw.calls != calls {
		t.Fatal("sticky failure performed I/O")
	}
	raw = &shortConn{zero: true}
	c = &boundedConn{Conn: raw, deadline: absolute, idle: time.Hour, chunk: 3, limit: 100}
	if _, err = c.Write([]byte("x")); !errors.Is(err, io.ErrNoProgress) {
		t.Fatal(err)
	}
}
