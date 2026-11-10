package export_examples_go_standard_network_api

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"sync/atomic"
	"time"

	"github.com/cenkalti/backoff/v4"
	smtp "github.com/emersion/go-smtp"
	"github.com/reactivex/rxgo/v2"
)

// This independent, effect-free stage exercises RxGo's transitive backoff
// timer before the SMTP client is constructed. It never retries a network call.
func workerTimerStage() bool {
	var attempts atomic.Uint32
	retry := errors.New("local retry fixture")
	source := rxgo.Defer([]rxgo.Producer{func(ctx context.Context, next chan<- rxgo.Item) {
		if attempts.Add(1) == 1 {
			rxgo.Error(retry).SendContext(ctx, next)
			return
		}
		rxgo.Of(uint32(42)).SendContext(ctx, next)
	}})
	policy := backoff.WithMaxRetries(backoff.NewConstantBackOff(5*time.Millisecond), 1)
	values, failures := 0, 0
	for item := range source.BackOffRetry(policy).Observe() {
		if item.Error() {
			failures++
		} else if item.V == uint32(42) {
			values++
		} else {
			return false
		}
	}
	return attempts.Load() == 2 && values == 1 && failures == 0
}

// The published client uses its ordinary factories, without an injected Conn,
// transport, executor or application-level retry around SMTP.
func Run(which uint32, input string) string {
	if which > 5 {
		return "unsupported-fixture-mode"
	}
	var config struct {
		Address    string
		RootPEM    string
		ServerName string
	}
	if json.Unmarshal([]byte(input), &config) != nil || config.Address == "" {
		return "fixture-input-error"
	}
	if !workerTimerStage() {
		return "published-worker-timer-error"
	}
	var client *smtp.Client
	var err error
	version := uint16(tls.VersionTLS13)
	if which == 0 {
		client, err = smtp.Dial(config.Address)
	} else {
		roots := x509.NewCertPool()
		if which != 3 && !roots.AppendCertsFromPEM([]byte(config.RootPEM)) {
			return "fixture-root-error"
		}
		if which == 4 {
			version = tls.VersionTLS12
		}
		name := config.ServerName
		if which == 2 {
			name = "wrong-fixture-name.invalid"
		}
		client, err = smtp.DialStartTLS(config.Address, &tls.Config{
			RootCAs: roots, ServerName: name,
			MinVersion: version, MaxVersion: version,
		})
	}
	if client != nil {
		defer client.Close()
		if err == nil {
			// DialStartTLS constructs the TLS connection; the published
			// client's next protocol command drives its handshake.
			err = client.Noop()
		}
	}
	if which == 2 {
		var mismatch x509.HostnameError
		if errors.As(err, &mismatch) {
			return "published-starttls-hostname-refused"
		}
		return "unexpected-hostname-result"
	}
	if which == 3 {
		var unknown x509.UnknownAuthorityError
		if errors.As(err, &unknown) {
			return "published-starttls-trust-refused"
		}
		return "unexpected-trust-result"
	}
	if err != nil || client == nil {
		return "published-smtp-error"
	}
	if which != 0 {
		state, ok := client.TLSConnectionState()
		if !ok || !state.HandshakeComplete || state.Version != version || len(state.VerifiedChains) == 0 {
			return "tls-state-error"
		}
	}
	if client.Quit() != nil {
		return "published-smtp-quit-error"
	}
	if which == 0 {
		return "published-smtp-plain"
	}
	if version == tls.VersionTLS12 {
		return "published-smtp-tls12"
	}
	return "published-smtp-tls13"
}
