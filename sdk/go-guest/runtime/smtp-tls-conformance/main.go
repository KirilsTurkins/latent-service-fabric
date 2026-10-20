package export_examples_go_standard_network_api

import (
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"net/smtp"
)

// Ordinary standard clients, explicit application trust, and no supplied Conn.
// This fixture does not grant authority or select a host TLS provider.
func Run(which uint32, input string) string {
	if which > 5 {
		return "unsupported-fixture-mode"
	}
	var config struct {
		Address    string `json:"address"`
		RootPEM    string `json:"rootPem"`
		ServerName string `json:"serverName"`
	}
	if json.Unmarshal([]byte(input), &config) != nil || config.Address == "" {
		return "fixture-input-error"
	}
	client, err := smtp.Dial(config.Address)
	if err != nil {
		return "smtp-dial-error"
	}
	defer client.Close()
	if which == 0 {
		if client.Noop() != nil || client.Quit() != nil {
			return "smtp-plain-error"
		}
		return "ordinary-smtp-plain"
	}
	roots := x509.NewCertPool()
	if which != 3 && !roots.AppendCertsFromPEM([]byte(config.RootPEM)) {
		return "fixture-root-error"
	}
	version := uint16(tls.VersionTLS13)
	if which == 4 {
		version = tls.VersionTLS12
	}
	name := config.ServerName
	if which == 2 {
		name = "wrong-fixture-name.invalid"
	}
	err = client.StartTLS(&tls.Config{
		RootCAs: roots, ServerName: name,
		MinVersion: version, MaxVersion: version,
	})
	if which == 2 {
		var mismatch x509.HostnameError
		if errors.As(err, &mismatch) {
			return "ordinary-starttls-hostname-refused"
		}
		return "unexpected-hostname-result"
	}
	if which == 3 {
		var unknown x509.UnknownAuthorityError
		if errors.As(err, &unknown) {
			return "ordinary-starttls-trust-refused"
		}
		return "unexpected-trust-result"
	}
	if err != nil {
		return "starttls-error"
	}
	state, ok := client.TLSConnectionState()
	if !ok || !state.HandshakeComplete || state.Version != version || len(state.VerifiedChains) == 0 {
		return "tls-state-error"
	}
	if client.Noop() != nil || client.Quit() != nil {
		return "smtp-tls-error"
	}
	if version == tls.VersionTLS12 {
		return "ordinary-smtp-tls12"
	}
	return "ordinary-smtp-tls13"
}
