package export_examples_go_standard_network_api

import (
	"context"
	"errors"
	"io"
	"net"
	"time"
)

// Ordinary public constructors and Conn calls; no injected Conn, resolver,
// transport or application executor. Compilation alone does not run these cases.
func Run(which uint32, address string) string {
	ctx := context.Background()
	switch which {
	case 0:
		connection, err := net.Dial("udp", address)
		if connection == nil && errors.Is(err, errors.ErrUnsupported) {
			return "unsupported-network"
		}
	case 1:
		values, err := net.LookupHost("no-authority.invalid")
		if values == nil && errors.Is(err, errors.ErrUnsupported) {
			return "unsupported-standalone-dns"
		}
	case 2:
		cancelled, cancel := context.WithCancel(ctx)
		cancel()
		connection, err := (&net.Dialer{}).DialContext(cancelled, "tcp", address)
		if connection == nil && errors.Is(err, context.Canceled) {
			return "cancelled-before-connect"
		}
	case 3:
		connection, err := (&net.Dialer{Deadline: time.Now().Add(-time.Second)}).DialContext(ctx, "tcp", address)
		if connection == nil && errors.Is(err, context.DeadlineExceeded) {
			return "expired-before-connect"
		}
		if timeout, ok := err.(net.Error); connection == nil && ok && timeout.Timeout() {
			return "expired-before-connect"
		}
	case 4:
		connection, err := net.DialTimeout("tcp", address, time.Second)
		if err != nil {
			if errors.Is(err, errors.ErrUnsupported) {
				return "provider-unavailable"
			}
			return "connect-error"
		}
		defer connection.Close()
		if connection.SetDeadline(time.Now().Add(time.Second)) != nil {
			return "deadline-error"
		}
		if n, err := connection.Write([]byte("ping")); n != 4 || err != nil {
			return "write-error"
		}
		var reply [4]byte
		if n, err := io.ReadFull(connection, reply[:]); n != 4 || err != nil {
			return "read-error"
		}
		if string(reply[:]) != "pong" {
			return "payload-error"
		}
		return "ordinary-tcp-exchange"
	case 5, 6, 7, 8:
		original := net.DefaultResolver
		preferGo, strictErrors, dial := original.PreferGo, original.StrictErrors, original.Dial
		defer func() {
			net.DefaultResolver = original
			original.PreferGo, original.StrictErrors, original.Dial = preferGo, strictErrors, dial
		}()
		switch which {
		case 5:
			net.DefaultResolver = &net.Resolver{}
		case 6:
			net.DefaultResolver.PreferGo = true
		case 7:
			net.DefaultResolver.StrictErrors = true
		case 8:
			net.DefaultResolver.Dial = func(context.Context, string, string) (net.Conn, error) {
				panic("custom default resolver must never run")
			}
		}
		connection, err := net.Dial("tcp", address)
		if connection == nil && errors.Is(err, errors.ErrUnsupported) {
			return "unsupported-custom-default-resolver"
		}
	case 9:
		connection, err := net.DialTimeout("tcp", address, time.Second)
		if err != nil {
			return "connect-error"
		}
		defer connection.Close()
		if n, err := connection.Write([]byte("ping")); n != 4 || err != nil {
			return "write-error"
		}
		writer, ok := connection.(interface{ CloseWrite() error })
		if !ok || writer.CloseWrite() != nil {
			return "half-close-error"
		}
		reply, err := io.ReadAll(connection)
		if err != nil || string(reply) != "pong" {
			return "eof-error"
		}
		return "ordinary-half-close-eof"
	}
	return "unexpected-result"
}
