package transport

import (
	"encoding/binary"
	"errors"
	"math"
	"sync/atomic"
)

type peerSettings struct {
	ready        chan struct{}
	maximum      atomic.Uint32
	header       [9]byte
	headerBytes  int
	remaining    int
	settings     bool
	setting      [6]byte
	settingBytes int
	nextMaximum  uint32
	seen         bool
}

func newPeerSettings() *peerSettings {
	settings := &peerSettings{ready: make(chan struct{}), nextMaximum: math.MaxUint32}
	return settings
}

func (settings *peerSettings) observe(input []byte) error {
	for len(input) != 0 {
		if settings.headerBytes < len(settings.header) {
			count := copy(settings.header[settings.headerBytes:], input)
			settings.headerBytes += count
			input = input[count:]
			if settings.headerBytes != len(settings.header) {
				continue
			}
			settings.remaining = int(settings.header[0])<<16 | int(settings.header[1])<<8 | int(settings.header[2])
			settings.settings = settings.header[3] == 4 && settings.header[4]&1 == 0
			if settings.remaining > 16*1024 || (!settings.seen && !settings.settings) ||
				(settings.settings && (settings.remaining%6 != 0 || binary.BigEndian.Uint32(settings.header[5:])&0x7fffffff != 0)) {
				return errors.New("invalid bounded HTTP/2 settings exchange")
			}
		}
		count := min(len(input), settings.remaining)
		if settings.settings {
			payload := input[:count]
			for len(payload) != 0 {
				copied := copy(settings.setting[settings.settingBytes:], payload)
				settings.settingBytes += copied
				payload = payload[copied:]
				if settings.settingBytes == len(settings.setting) {
					if binary.BigEndian.Uint16(settings.setting[:2]) == 3 {
						settings.nextMaximum = binary.BigEndian.Uint32(settings.setting[2:])
					}
					settings.settingBytes = 0
				}
			}
		}
		input = input[count:]
		settings.remaining -= count
		if settings.remaining == 0 {
			if settings.settings {
				settings.maximum.Store(settings.nextMaximum)
				if !settings.seen {
					settings.seen = true
					close(settings.ready)
				}
			}
			settings.headerBytes = 0
		}
	}
	return nil
}
