"""One short-lived loopback-only DNS fixture; no ambient names or forwarding."""
from __future__ import annotations

import socket
import struct
import threading


def response(packet: bytes) -> bytes:
    if not 12 <= len(packet) <= 512:
        raise ValueError('DNS fixture packet size')
    identifier, flags, questions, answers, authority, additional = struct.unpack('!6H', packet[:12])
    if flags & 0xF800 or (questions, answers, authority, additional) != (1, 0, 0, 0):
        raise ValueError('DNS fixture query header')
    cursor = 12
    labels = []
    while cursor < len(packet):
        length = packet[cursor]
        cursor += 1
        if length == 0:
            break
        if length > 63 or cursor + length > len(packet) or len(labels) >= 8:
            raise ValueError('DNS fixture question bound')
        labels.append(packet[cursor:cursor + length].decode('ascii'))
        cursor += length
    if cursor + 4 != len(packet) or '.'.join(labels).lower() != 'harbor.test':
        raise ValueError('DNS fixture question outside approved name')
    kind, query_class = struct.unpack('!HH', packet[cursor:])
    if kind not in (1, 28) or query_class != 1:
        raise ValueError('DNS fixture query type')
    answer = b''
    if kind == 1:
        answer = b'\xc0\x0c' + struct.pack('!HHIH', 1, 1, 1, 4) + socket.inet_aton('127.0.0.1')
    return struct.pack('!6H', identifier, 0x8180, 1, int(kind == 1), 0, 0) + packet[12:] + answer


class Fixture:
    def __init__(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(('127.0.0.1', 0))
        self.socket.settimeout(0.2)
        self.address = '{}:{}'.format(*self.socket.getsockname())
        self.stopping = threading.Event()
        self.count = 0
        self.failed = False
        self.worker = threading.Thread(target=self._run, name='owned-harbor-dns')
        self.worker.start()

    def _run(self):
        while not self.stopping.is_set():
            try:
                packet, peer = self.socket.recvfrom(513)
                if peer[0] != '127.0.0.1' or self.count >= 1024:
                    raise ValueError('DNS fixture work bound')
                result = response(packet)
                self.count += 1
                self.socket.sendto(result, peer)
            except socket.timeout:
                continue
            except (OSError, ValueError, UnicodeError):
                if not self.stopping.is_set():
                    self.failed = True
                break

    def close(self):
        self.stopping.set()
        self.socket.close()
        self.worker.join(timeout=2)
        if self.worker.is_alive() or self.failed:
            raise RuntimeError('DNS fixture did not retire cleanly')
