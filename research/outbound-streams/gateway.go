// Package streams is a research-only typed SMTP gateway experiment for #696.
// It is not an LSF provider, guest transport, or production authorization boundary.
package streams

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"io"
	"net"
	"net/netip"
	"net/smtp"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	maxBody           = 4096
	handleMetadata    = 256
	operationMetadata = 32 * 1024 // Reply envelope plus parser/copy allowance; logical, not RSS.
	kernelReservation = 96 * 1024 // Conservative logical charge, not kernel measurement.
	tlsReservation    = 64 * 1024 // Not a verified bound on Go's TLS implementation.
	maxAbsolute       = 5 * time.Second
)

// Config is trusted operator configuration, never supplied in a guest request.
// Only one literal destination is supported: no ambient DNS, proxy, or redirect.
type Config struct {
	Address         string
	Hostname        string
	LoopbackFixture bool
	TLS             bool
	Roots           *x509.CertPool
	MaxHandles      int
	MaxPerTenant    int
	MaxLiveBytes    int
	MaxAudit        int
	Idle            time.Duration
	Chunk           int
	WireLimit       int
}

// Grant models a precompiled exact authority tuple. A caller-created value is
// NOT a substitute for LSF's sealed CapabilitySession in a production provider.
type Grant struct {
	Tenant, Provider, Destination, Operation string
	Epoch                                    uint64
}

type Message struct {
	From, To string
	Body     []byte
}
type Outcome struct {
	Code           string
	MayHaveApplied bool
}
type Snapshot struct{ Handles, Active, Bytes, ConnectAttempts, AuditEntries int }
type Audit struct {
	Code           string
	MayHaveApplied bool
}

type Provider struct {
	mu                      sync.Mutex
	cfg                     Config
	endpoint                netip.AddrPort
	epoch                   uint64
	retired                 bool
	next                    uint64
	handles                 map[uint64]*Handle
	tenants                 map[string]int
	active, bytes, connects int
	audit                   []Audit
	// Test-only fault injection. Zero disables it; never exposed by a request.
	faultAfter   int
	beforeRetire func() // Test-only physical-owner barrier.
}

// Handle is affine by lookup: a copied, stale or foreign Go value cannot match
// the stored pointer. Closing active work requests stop; Send owns reclamation.
type Handle struct {
	provider     *Provider
	id           uint64
	grant        Grant
	deadline     time.Time
	closed, busy bool
	cancel       context.CancelFunc
}

func New(cfg Config) (*Provider, error) {
	endpoint, err := netip.ParseAddrPort(cfg.Address)
	if err != nil || endpoint.Port() == 0 || !addressAllowed(endpoint.Addr(), cfg.LoopbackFixture) {
		return nil, errors.New("destination-policy")
	}
	if cfg.Hostname != "mail.test" || cfg.MaxHandles < 1 || cfg.MaxHandles > 8 ||
		cfg.MaxPerTenant < 1 || cfg.MaxPerTenant > cfg.MaxHandles ||
		cfg.MaxLiveBytes < handleMetadata || cfg.MaxLiveBytes > 4*1024*1024 ||
		cfg.MaxAudit < 1 || cfg.MaxAudit > 128 || cfg.Idle <= 0 || cfg.Idle > maxAbsolute ||
		cfg.Chunk < 1 || cfg.Chunk > 4096 || cfg.WireLimit < 1 || cfg.WireLimit > 128*1024 {
		return nil, errors.New("invalid-config")
	}
	if cfg.TLS {
		if cfg.Roots == nil {
			return nil, errors.New("explicit-roots-required")
		}
		cfg.Roots = cfg.Roots.Clone()
	}
	return &Provider{cfg: cfg, endpoint: endpoint, epoch: 1,
		handles: make(map[uint64]*Handle), tenants: make(map[string]int)}, nil
}

func addressAllowed(addr netip.Addr, fixture bool) bool {
	// Deliberately local-only. Do not ship a hand-maintained partial special-
	// address blacklist as production policy; that was a negative result of
	// this experiment. DNS and public destinations are design-only below.
	return fixture && addr.Unmap() == netip.MustParseAddr("127.0.0.1")
}

func (p *Provider) authorized(g Grant) bool {
	return !p.retired && g.Tenant != "" && len(g.Tenant) <= 32 &&
		g.Provider == "smtp-fixture" && g.Destination == p.cfg.Address &&
		g.Operation == "mail.submit-v1" && g.Epoch == p.epoch
}

func (p *Provider) Bind(g Grant, deadline time.Time) (*Handle, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	if !p.authorized(g) {
		return nil, errors.New("denied")
	}
	remaining := time.Until(deadline)
	if remaining <= 0 || remaining > maxAbsolute {
		return nil, errors.New("deadline")
	}
	if len(p.handles) >= p.cfg.MaxHandles || p.tenants[g.Tenant] >= p.cfg.MaxPerTenant ||
		p.bytes+handleMetadata > p.cfg.MaxLiveBytes || p.next == ^uint64(0) {
		return nil, errors.New("exhausted")
	}
	p.next++
	h := &Handle{provider: p, id: p.next, grant: g, deadline: deadline}
	p.handles[h.id] = h
	p.tenants[g.Tenant]++
	p.bytes += handleMetadata
	return h, nil
}

func (p *Provider) valid(h *Handle) bool {
	return h != nil && h.provider == p && p.handles[h.id] == h && !h.closed
}

func (p *Provider) release(h *Handle) {
	delete(p.handles, h.id)
	p.tenants[h.grant.Tenant]--
	if p.tenants[h.grant.Tenant] == 0 {
		delete(p.tenants, h.grant.Tenant)
	}
	p.bytes -= handleMetadata
}

func (p *Provider) Close(h *Handle) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	if !p.valid(h) {
		return errors.New("invalid-handle")
	}
	h.closed = true
	if h.busy {
		h.cancel()
	} else {
		p.release(h)
	}
	return nil
}

// Revoke fences future dispatch, not a claim of rollback of accepted work.
func (p *Provider) Revoke() { p.mu.Lock(); p.retired = true; p.mu.Unlock() }
func (p *Provider) Snapshot() Snapshot {
	p.mu.Lock()
	defer p.mu.Unlock()
	return Snapshot{len(p.handles), p.active, p.bytes, p.connects, len(p.audit)}
}
func (p *Provider) Audit() []Audit {
	p.mu.Lock()
	defer p.mu.Unlock()
	return append([]Audit(nil), p.audit...)
}

// Send uses the real net/smtp client with one socket and one active owner.
// Success means the peer returned SMTP 250 for DATA, NOT recipient delivery.
// All error strings and payloads from net/smtp remain out of the public outcome.
func (p *Provider) Send(parent context.Context, h *Handle, m Message) (out Outcome) {
	if m.From != "sender@example.test" || m.To != "recipient@example.test" || len(m.Body) == 0 || len(m.Body) > maxBody {
		return Outcome{Code: "invalid-input"}
	}
	p.mu.Lock()
	if !p.valid(h) || h.busy {
		p.mu.Unlock()
		return Outcome{Code: "invalid-handle"}
	}
	if !p.authorized(h.grant) {
		p.mu.Unlock()
		return Outcome{Code: "denied"}
	}
	if parent.Err() != nil {
		p.mu.Unlock()
		return Outcome{Code: "cancelled-before-dispatch"}
	}
	if time.Until(h.deadline) <= 0 {
		p.mu.Unlock()
		return Outcome{Code: "deadline-before-dispatch"}
	}
	charge := operationMetadata + kernelReservation + len(m.Body)
	if p.cfg.TLS {
		charge += tlsReservation
	}
	// Each accepted operation reserves its final audit slot before dispatch.
	if p.bytes+charge > p.cfg.MaxLiveBytes || len(p.audit) >= p.cfg.MaxAudit {
		p.mu.Unlock()
		return Outcome{Code: "exhausted"}
	}
	ctx, cancel := context.WithDeadline(parent, h.deadline)
	h.busy = true
	h.cancel = cancel
	p.active++
	p.bytes += charge
	index := len(p.audit)
	p.audit = append(p.audit, Audit{Code: "accepted"})
	p.connects++
	p.mu.Unlock()
	// Reserve before copying. Only this private slice is zeroized on retirement.
	body := make([]byte, len(m.Body))
	copy(body, m.Body)
	defer func() {
		cancel()
		for i := range body {
			body[i] = 0
		}
		if p.beforeRetire != nil {
			p.beforeRetire()
		}
		p.mu.Lock()
		defer p.mu.Unlock()
		h.closed = true
		h.busy = false
		h.cancel = nil
		p.active--
		p.bytes -= charge
		p.audit[index] = Audit{out.Code, out.MayHaveApplied}
		p.release(h)
	}()
	dialer := net.Dialer{}
	raw, err := dialer.DialContext(ctx, "tcp", p.endpoint.String())
	if err != nil {
		return Outcome{Code: classify(ctx, err, false, false)}
	}
	// This defer runs before the owner refund above. No detached cleanup job.
	defer raw.Close()
	tcp := raw.(*net.TCPConn)
	if err = tcp.SetReadBuffer(32 * 1024); err != nil {
		return Outcome{Code: "buffer-config"}
	}
	if err = tcp.SetWriteBuffer(16 * 1024); err != nil {
		return Outcome{Code: "buffer-config"}
	}
	peer, err := netip.ParseAddrPort(raw.RemoteAddr().String())
	if err != nil || peer.Addr().Unmap() != p.endpoint.Addr().Unmap() || peer.Port() != p.endpoint.Port() {
		return Outcome{Code: "peer-denied"}
	}
	// Cancellation interrupts the actual syscall. Join any running callback
	// before closing/refunding the physical owner; stop alone is not a join.
	stopped := make(chan struct{})
	stop := context.AfterFunc(ctx, func() { _ = raw.Close(); close(stopped) })
	defer func() {
		if !stop() {
			<-stopped
		}
	}()
	wire := &boundedConn{Conn: raw, deadline: h.deadline, idle: p.cfg.Idle,
		chunk: p.cfg.Chunk, limit: p.cfg.WireLimit}
	var conn net.Conn = wire
	if p.cfg.TLS {
		secured := tls.Client(wire, &tls.Config{ServerName: p.cfg.Hostname, RootCAs: p.cfg.Roots,
			MinVersion: tls.VersionTLS12, SessionTicketsDisabled: true})
		if err = secured.HandshakeContext(ctx); err != nil {
			return Outcome{Code: classify(ctx, err, false, true)}
		}
		conn = secured
	}
	// Mark application write uncertainty outside TLS: a failed handshake has
	// not submitted an SMTP command, although the TCP/TLS peer was contacted.
	app := &boundedConn{Conn: conn, deadline: h.deadline, idle: p.cfg.Idle,
		chunk: p.cfg.Chunk, limit: 16 * 1024, faultAfter: p.faultAfter}
	framed := &smtpReplyConn{Conn: app}
	defer framed.clear()
	client, err := smtp.NewClient(framed, p.cfg.Hostname)
	if err == nil {
		// Frozen net/smtp may try HELO after EHLO fails. boundedConn's sticky
		// transport error prevents any additional I/O after an I/O failure.
		err = client.Hello("capsule.test")
		if err == nil {
			err = client.Mail(m.From)
		}
		if err == nil {
			err = client.Rcpt(m.To)
		}
		if err == nil {
			var data io.WriteCloser
			data, err = client.Data()
			if err == nil {
				_, err = data.Write(body)
				if err == nil {
					err = data.Close()
				}
			}
		}
		// Deliberately no QUIT, transparent retry, reconnect or pooling.
	}
	if err != nil {
		return Outcome{Code: classify(ctx, err, app.attempted, false), MayHaveApplied: app.attempted}
	}
	if ctx.Err() != nil {
		return Outcome{Code: "uncertain", MayHaveApplied: app.attempted}
	}
	return Outcome{Code: "peer-accepted", MayHaveApplied: true}
}

func classify(ctx context.Context, err error, attempted, tlsPhase bool) string {
	if attempted {
		return "uncertain"
	}
	if ctx.Err() != nil {
		return "cancelled-or-deadline"
	}
	if tlsPhase {
		return "tls-failed"
	}
	var timeout net.Error
	if errors.As(err, &timeout) && timeout.Timeout() {
		return "deadline"
	}
	return "transport-failed"
}

// boundedConn preserves io.Writer's contract: successful internal short writes
// are completed within this call; a true failure returns the actual partial n.
// It is single-operation-owned, not a concurrent general-purpose net.Conn.
type boundedConn struct {
	net.Conn
	deadline                                time.Time
	idle                                    time.Duration
	chunk, limit, read, written, faultAfter int
	attempted                               bool
	terminal                                error
}

var errBound = errors.New("transport-bound")

func (c *boundedConn) until() time.Time {
	idle := time.Now().Add(c.idle)
	if idle.Before(c.deadline) {
		return idle
	}
	return c.deadline
}
func (c *boundedConn) Read(b []byte) (int, error) {
	if c.terminal != nil {
		return 0, c.terminal
	}
	if len(b) == 0 {
		return 0, nil
	}
	left := c.limit - c.read
	if left <= 0 {
		c.terminal = errBound
		return 0, errBound
	}
	nmax := min(len(b), c.chunk, left)
	if err := c.Conn.SetReadDeadline(c.until()); err != nil {
		c.terminal = err
		return 0, err
	}
	n, err := c.Conn.Read(b[:nmax])
	c.read += n

	if err != nil {
		c.terminal = err
	}
	return n, err
}
func (c *boundedConn) Write(b []byte) (int, error) {
	if c.terminal != nil {
		return 0, c.terminal
	}
	total := 0
	for len(b) > 0 {
		left := c.limit - c.written
		if c.faultAfter > 0 {
			left = min(left, c.faultAfter-c.written)
		}
		if left <= 0 {
			c.terminal = errBound
			return total, errBound
		}
		nmax := min(len(b), c.chunk, left)
		if err := c.Conn.SetWriteDeadline(c.until()); err != nil {
			c.terminal = err
			return total, err
		}
		c.attempted = true
		n, err := c.Conn.Write(b[:nmax])
		c.written += n
		total += n
		b = b[n:]
		if err != nil {
			c.terminal = err
			return total, err
		}
		if n == 0 {
			c.terminal = io.ErrNoProgress
			return total, c.terminal
		}
	}
	return total, nil
}

// FixtureGrant is explicit trusted test setup, not an SDK authority constructor.
func FixtureGrant(address, tenant string) Grant {
	return Grant{tenant, "smtp-fixture", address, "mail.submit-v1", 1}
}
func FixtureConfig(address string) Config {
	return Config{Address: address, Hostname: "mail.test", LoopbackFixture: true,
		MaxHandles: 2, MaxPerTenant: 1, MaxLiveBytes: 512 * 1024, MaxAudit: 32,
		Idle: time.Second, Chunk: 7, WireLimit: 64 * 1024}
}

// ValidateEndpointText prevents a future operator parser treating URI/userinfo,
// wildcard ports, or a hostname as a literal endpoint in this narrow experiment.
func ValidateEndpointText(text string) bool {
	host, port, err := net.SplitHostPort(text)
	if err != nil || strings.ContainsAny(host, "/@") {
		return false
	}
	_, err = netip.ParseAddr(host)
	n, portErr := strconv.ParseUint(port, 10, 16)
	return err == nil && portErr == nil && n != 0
}
