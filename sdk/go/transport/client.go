package transport

import (
	"context"
	"errors"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"latent.dev/sdk/go/internal/rpc/controlv1"
	"latent.dev/sdk/go/internal/rpc/invocationv1"
	"latent.dev/sdk/go/profile"
)

type Client struct {
	config     Config
	endpoint   *url.URL
	channel    *http.ClientConn
	owner      *http.Transport
	socket     *ownedSocket
	invocation invocationv1.InvocationServiceClient
	policy     controlv1.PolicyServiceClient
	capability controlv1.CapabilityServiceClient
	lifetime   context.Context
	stop       context.CancelFunc
	mutex      sync.Mutex
	closed     bool
	active     int
	normal     int
	queued     int
	wake       chan struct{}
	fault      chan struct{}
	done       chan struct{}
	watchDone  chan struct{}
	closeOnce  sync.Once
	wait       sync.WaitGroup
	closeError error
}

var _ profile.ClientProfile = (*Client)(nil)

func (*Client) String() string   { return "latent bounded Go client (redacted)" }
func (*Client) GoString() string { return "transport.Client{redacted}" }

func New(ctx context.Context, config Config) (*Client, error) {
	return newClient(ctx, config, nil, false)
}

func AdoptConnection(ctx context.Context, config Config, connection *net.TCPConn) (*Client, error) {
	return newClient(ctx, config, connection, true)
}

func newClient(ctx context.Context, config Config, supplied *net.TCPConn, adopt bool) (*Client, error) {
	success := false
	defer func() {
		if !success && supplied != nil {
			_ = supplied.Close()
		}
	}()
	endpoint, failure := config.validate()
	if failure != nil {
		return nil, failure
	}
	if ctx == nil || http2DebugEnabled() || (adopt && supplied == nil) {
		return nil, invalidConfig()
	}
	startup, cancel := context.WithTimeout(ctx, config.ConnectTimeout)
	defer cancel()
	if failure = startup.Err(); failure != nil {
		return nil, contextFailure(failure)
	}
	var connection net.Conn = supplied
	if !adopt {
		connection, failure = (&net.Dialer{}).DialContext(startup, "tcp", endpoint.Host)
		if failure != nil {
			if startup.Err() != nil {
				return nil, contextFailure(startup.Err())
			}
			return nil, localFailure(profile.FailureCategoryTransport, "loopback connection failed")
		}
	}
	defer func() {
		if !success {
			_ = connection.Close()
		}
	}()
	startupRetired := make(chan struct{})
	stopStartup := context.AfterFunc(startup, func() { _ = connection.Close(); close(startupRetired) })
	var stopOnce sync.Once
	stopStartupWatch := func() {
		stopOnce.Do(func() {
			if !stopStartup() {
				<-startupRetired
			}
		})
	}
	defer stopStartupWatch()
	peer, peerOK := connection.RemoteAddr().(*net.TCPAddr)
	local, localOK := connection.LocalAddr().(*net.TCPAddr)
	if !peerOK || !localOK || !peer.IP.IsLoopback() || !local.IP.IsLoopback() || peer.String() != endpoint.Host {
		return nil, invalidConfig()
	}
	deadline, _ := startup.Deadline()
	if failure = connection.SetDeadline(deadline); failure != nil {
		return nil, localFailure(profile.FailureCategoryTransport, "connection deadline failed")
	}
	lifetime, stop := context.WithCancel(context.Background())
	client := &Client{config: config, endpoint: endpoint, lifetime: lifetime, stop: stop,
		wake: make(chan struct{}), fault: make(chan struct{}, 1), done: make(chan struct{}), watchDone: make(chan struct{})}
	client.socket = &ownedSocket{Conn: connection, fault: client.fault, settings: newPeerSettings()}
	var protocols http.Protocols
	protocols.SetUnencryptedHTTP2(true)
	var handed atomic.Bool
	owner := &http.Transport{
		Protocols: &protocols, DisableCompression: true,
		MaxResponseHeaderBytes: int64(config.MaxHeaderBytes),
		DialContext: func(_ context.Context, network, address string) (net.Conn, error) {
			if network != "tcp" || address != endpoint.Host || !handed.CompareAndSwap(false, true) {
				return nil, errors.New("replacement connections are disabled")
			}
			return client.socket, nil
		},
		HTTP2: &http.HTTP2Config{
			StrictMaxConcurrentRequests: true, MaxReadFrameSize: 16 * 1024,
			MaxDecoderHeaderTableSize: 4096, MaxEncoderHeaderTableSize: 4096,
			MaxReceiveBufferPerConnection: 64 * 1024, MaxReceiveBufferPerStream: 64 * 1024,
			WriteByteTimeout: config.ConnectTimeout,
		},
	}
	client.owner = owner
	client.channel, failure = owner.NewClientConn(startup, endpoint.Scheme, endpoint.Host)
	if failure == nil {
		select {
		case <-client.socket.settings.ready:
			failure = client.channel.Err()
		case <-client.fault:
			failure = net.ErrClosed
		case <-startup.Done():
			failure = startup.Err()
		}
	}
	if failure != nil {
		stop()
		if client.channel != nil {
			_ = client.channel.Close()
		}
		if startup.Err() != nil {
			return nil, contextFailure(startup.Err())
		}
		if !time.Now().Before(deadline) {
			return nil, contextFailure(context.DeadlineExceeded)
		}
		return nil, localFailure(profile.FailureCategoryTransport, "HTTP/2 startup failed")
	}
	if client.socket.settings.maximum.Load() <= uint32(config.ReservedRecovery) {
		stop()
		_ = client.channel.Close()
		return nil, localFailure(profile.FailureCategoryTransport, "peer cannot provide the configured recovery capacity")
	}
	stopStartupWatch()
	if startup.Err() != nil {
		stop()
		_ = client.channel.Close()
		return nil, contextFailure(startup.Err())
	}
	if failure = connection.SetDeadline(time.Time{}); failure != nil {
		stop()
		_ = client.channel.Close()
		return nil, localFailure(profile.FailureCategoryTransport, "connection deadline failed")
	}
	wire := &rpcChannel{client: client}
	client.invocation = invocationv1.NewInvocationServiceClient(wire)
	client.policy = controlv1.NewPolicyServiceClient(wire)
	client.capability = controlv1.NewCapabilityServiceClient(wire)
	success = true
	go func() {
		defer close(client.watchDone)
		select {
		case <-client.fault:
			client.shutdown()
		case <-client.done:
		}
	}()
	return client, nil
}

func (client *Client) Close() error {
	client.shutdown()
	<-client.done
	<-client.watchDone
	return client.closeError
}

func (client *Client) shutdown() {
	client.closeOnce.Do(func() {
		client.mutex.Lock()
		client.closed = true
		client.stop()
		close(client.wake)
		client.mutex.Unlock()
		_ = client.channel.Close()
		_ = client.socket.Close()
		client.wait.Wait()
		deadline := time.NewTimer(client.config.ConnectTimeout)
		poll := time.NewTicker(time.Millisecond)
		defer deadline.Stop()
		defer poll.Stop()
	retirement:
		for client.socket.inFlight() != 0 {
			select {
			case <-poll.C:
			case <-deadline.C:
				client.closeError = localFailure(profile.FailureCategoryTransport, "HTTP/2 retirement exceeded the close bound")
				break retirement
			}
		}
		close(client.done)
	})
}

func (client *Client) acquire(ctx context.Context, recovery bool) (func(), error) {
	var poll <-chan time.Time
	var ticker *time.Ticker
	defer func() {
		if ticker != nil {
			ticker.Stop()
		}
	}()
	client.mutex.Lock()
	if client.closed {
		client.mutex.Unlock()
		return nil, localFailure(profile.FailureCategoryTransport, "client is closed")
	}
	client.wait.Add(1)
	waiting := false
	for {
		if ctx.Err() != nil || client.closed {
			if waiting {
				client.queued--
			}
			client.wait.Done()
			client.mutex.Unlock()
			if ctx.Err() != nil {
				return nil, contextFailure(ctx.Err())
			}
			return nil, localFailure(profile.FailureCategoryTransport, "client is closed")
		}
		wireOwners := client.channel.InFlight()
		limit := int(min(uint32(client.config.MaxInFlight), client.socket.settings.maximum.Load()))
		if client.active < limit && wireOwners < limit &&
			(recovery || client.normal < limit-client.config.ReservedRecovery) {
			if waiting {
				client.queued--
			}
			client.active++
			if !recovery {
				client.normal++
			}
			client.mutex.Unlock()
			return func() {
				client.mutex.Lock()
				client.active--
				if !recovery {
					client.normal--
				}
				if !client.closed {
					close(client.wake)
					client.wake = make(chan struct{})
				}
				client.mutex.Unlock()
				client.wait.Done()
			}, nil
		}
		if !waiting {
			if client.queued == client.config.MaxQueued {
				client.wait.Done()
				client.mutex.Unlock()
				return nil, localFailure(profile.FailureCategoryLimit, "client admission queue is full")
			}
			client.queued++
			waiting = true
			ticker = time.NewTicker(5 * time.Millisecond)
			poll = ticker.C
		}
		wake := client.wake
		client.mutex.Unlock()
		select {
		case <-wake:
		case <-ctx.Done():
		case <-poll:
		}
		client.mutex.Lock()
	}
}

type Snapshot struct {
	Closed               bool
	InFlight             int
	Queued               int
	WireConcurrencySlots int
	Reaped               bool
}

func (client *Client) Snapshot() Snapshot {
	client.mutex.Lock()
	defer client.mutex.Unlock()
	result := Snapshot{Closed: client.closed, InFlight: client.active, Queued: client.queued,
		WireConcurrencySlots: client.channel.InFlight()}
	select {
	case <-client.watchDone:
		result.Reaped = client.channel.Err() != nil && result.InFlight == 0 && result.Queued == 0 && client.socket.inFlight() == 0
	default:
	}
	return result
}

type ownedSocket struct {
	net.Conn
	fault    chan struct{}
	mutex    sync.Mutex
	active   int
	closed   bool
	settings *peerSettings
}

func (socket *ownedSocket) Read(buffer []byte) (int, error) {
	if !socket.begin() {
		return 0, net.ErrClosed
	}
	defer socket.end()
	count, failure := socket.Conn.Read(buffer)
	if count != 0 && socket.settings != nil {
		if invalid := socket.settings.observe(buffer[:count]); invalid != nil {
			count = 0
			failure = invalid
		}
	}
	if failure != nil {
		select {
		case socket.fault <- struct{}{}:
		default:
		}
	}
	return count, failure
}

func (socket *ownedSocket) Write(buffer []byte) (int, error) {
	if !socket.begin() {
		return 0, net.ErrClosed
	}
	defer socket.end()
	return socket.Conn.Write(buffer)
}

func (socket *ownedSocket) Close() error {
	socket.mutex.Lock()
	socket.closed = true
	socket.mutex.Unlock()
	return socket.Conn.Close()
}

func (socket *ownedSocket) begin() bool {
	socket.mutex.Lock()
	defer socket.mutex.Unlock()
	if socket.closed {
		return false
	}
	socket.active++
	return true
}

func (socket *ownedSocket) end() {
	socket.mutex.Lock()
	socket.active--
	socket.mutex.Unlock()
}

func (socket *ownedSocket) inFlight() int {
	socket.mutex.Lock()
	defer socket.mutex.Unlock()
	return socket.active
}

func (client *Client) roundTrip(request *http.Request) (*http.Response, error) {
	state, valid := request.Context().Value(callKey{}).(*callState)
	if !valid || request.URL.Host != client.endpoint.Host || !state.attempted.CompareAndSwap(false, true) {
		return nil, errors.New("automatic RPC resubmission is disabled")
	}
	poll := time.NewTicker(5 * time.Millisecond)
	defer poll.Stop()
	for {
		client.mutex.Lock()
		if request.Context().Err() != nil {
			client.mutex.Unlock()
			return nil, request.Context().Err()
		}
		available := client.channel.InFlight() < client.config.MaxInFlight && client.channel.Available() > 0
		if client.closed || client.channel.Err() != nil {
			client.mutex.Unlock()
			return nil, errors.New("single connection is closed")
		}
		if available && client.channel.Reserve() == nil {
			setTimeoutHeader(request)
			state.dispatched = true
			client.mutex.Unlock()
			return client.channel.RoundTrip(request)
		}
		client.mutex.Unlock()
		select {
		case <-request.Context().Done():
			return nil, request.Context().Err()
		case <-client.lifetime.Done():
			return nil, errors.New("single connection is closed")
		case <-poll.C:
		}
	}
}

func http2DebugEnabled() bool {
	for _, setting := range strings.Split(os.Getenv("GODEBUG"), ",") {
		name, value, present := strings.Cut(setting, "=")
		if present && name == "http2debug" && value != "0" {
			return true
		}
	}
	return false
}

func contextFailure(failure error) *profile.ClientFailure {
	if errors.Is(failure, context.DeadlineExceeded) {
		return localFailure(profile.FailureCategoryDeadline, "local deadline expired")
	}
	return localFailure(profile.FailureCategoryLocalCancelled, "local wait cancelled")
}
