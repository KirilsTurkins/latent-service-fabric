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
	}
	return "unexpected-result"
}
