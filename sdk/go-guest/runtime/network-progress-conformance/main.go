package export_examples_go_standard_network_api

import (
	"bytes"
	"errors"
	"io"
	"net"
	"strconv"
	"time"
)

// Ordinary Go APIs over the maintained compiler port. This diagnostic never
// supplies a Conn, transport, goroutine executor or application polling loop.
var entries uint32

const writeSize = 48*1024 + 37
const copySize = 40*1024 + 13
const quotaSize = 1024*1024 + 16*1024

type partialEffect interface {
	error
	AcceptedPrefixBytes() uint32
	MayHaveApplied() bool
}

func payload(size int) []byte {
	value := make([]byte, size)
	for index := range value {
		value[index] = byte((uint32(index) * 2654435761) >> 24)
	}
	return value
}

func Run(which uint32, address string) string {
	entries++
	if entries != 1 || which > 2 { panic("write-progress:one-shot-mode") }
	connection, err := net.DialTimeout("tcp", address, time.Second)
	if err != nil { panic("write-progress:connect") }
	// Read/write operations retain the provider's original 2s idle/10s
	// absolute bounds and the original activation deadline; no rearming.
	var n int64
	var result string
	switch which {
	case 0:
		count, failure := connection.Write(payload(writeSize))
		if failure != nil || count != writeSize { panic("write-progress:write") }
		n, result = int64(count), "write"
	case 1:
		value := payload(copySize)
		// LimitedReader has no WriterTo; the real io.Copy buffer drives the
		// ordinary public Conn.Write path across its 16KiB host fragments.
		count, failure := io.Copy(connection, io.LimitReader(bytes.NewReader(value), int64(len(value))))
		if failure != nil || count != copySize { panic("write-progress:copy") }
		n, result = count, "copy"
	case 2:
		count, failure := connection.Write(payload(quotaSize))
		var operation *net.OpError
		var partial partialEffect
		if failure == nil || !errors.As(failure, &operation) || operation.Op != "write" ||
			!errors.As(failure, &partial) || partial.Error() != "lsf-stream-exhausted" ||
			count < 64 || count > 1024*1024 || uint32(count) != partial.AcceptedPrefixBytes() {
			panic("write-progress:typed-quota-prefix")
		}
		// Input exhaustion does not consume output credit or this connection.
		// A real pending ordinary read witnesses this reached error path while
		// the host samples original transfer credit/owners. The peer receives
		// exactly count bytes before sending this permit; no write after error.
		var permit [1]byte
		if got, failure := io.ReadFull(connection, permit[:]); failure != nil || got != 1 || permit[0] != 112 {
			panic("write-progress:quota-permit")
		}
		n = int64(count)
		result = "quota|accepted=" + strconv.FormatUint(uint64(partial.AcceptedPrefixBytes()), 10) +
			"|may-have-applied=" + strconv.FormatBool(partial.MayHaveApplied())
	}
	closeResult := "closed"
	if failure := connection.Close(); failure != nil {
		var partial partialEffect
		if !errors.As(failure, &partial) || partial.Error() != "lsf-stream-exhausted" { panic("write-progress:close") }
		// Preserve an actual typed close refusal; retirement must still be
		// observed by the owning host. Never call this successful close.
		closeResult = "exhausted"
	}
	return result + "|n=" + strconv.FormatInt(n, 10) + "|close=" + closeResult + "|fresh=1"
}
