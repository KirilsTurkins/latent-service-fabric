"""Finite TLS transport for the existing controlled HTTP peer, not a provider."""
from __future__ import annotations

from pathlib import Path
import selectors
import ssl

from .observations import validate
from .peer import Peer, READ_WINDOW
from .protocol import require
from .vectors import BY_ID, PROFILE

TLS_PROFILE = 'latent.controlled-http-tls-peer.v1'
HANDSHAKE_SECONDS = 5


class _Channel:
    """Translate TLS readiness into the original peer's nonblocking operations."""

    def __init__(self, owner, stream):
        self.owner, self.stream, self.pending_write = owner, stream, None

    def fileno(self):
        return self.stream.fileno()

    def close(self):
        self.pending_write = None
        self.stream.close()

    def recv(self, maximum):
        require(type(maximum) is int and 0 < maximum <= READ_WINDOW, 'tls-peer-read-window')
        try:
            return self.stream.recv(maximum)
        except ssl.SSLWantReadError:
            self.owner._need(self, 'read', selectors.EVENT_READ)
            raise BlockingIOError from None
        except ssl.SSLWantWriteError:
            self.owner._need(self, 'read', selectors.EVENT_WRITE)
            raise BlockingIOError from None

    def send(self, value):
        require(isinstance(value, bytes) and 0 < len(value) <= READ_WINDOW, 'tls-peer-write-window')
        # OpenSSL retries retain the exact original buffer until that operation
        # advances. The existing HTTP offset changes only after a positive send.
        if self.pending_write is None:
            self.pending_write = value
        require(value == self.pending_write, 'tls-peer-changed-pending-write')
        try:
            sent = self.stream.send(self.pending_write)
        except ssl.SSLWantReadError:
            self.owner._need(self, 'write', selectors.EVENT_READ)
            raise BlockingIOError from None
        except ssl.SSLWantWriteError:
            self.owner._need(self, 'write', selectors.EVENT_WRITE)
            raise BlockingIOError from None
        self.pending_write = None
        return sent


class TLSPeer(Peer):
    """The original socket/contact/HTTP/gate limits also cover handshakes.

    Certificates are disposable fixture inputs. Their private keys never enter
    observations, packages or guest snapshots. A peer socket close establishes
    no host-provider or kernel accounting result.
    """

    def __init__(self, authorization, certificate, private_key, **options):
        for path in (certificate, private_key):
            require(isinstance(path, Path) and path.is_absolute() and path.is_file()
                    and 0 < path.stat().st_size <= 65536, 'tls-peer-certificate-file')
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.options |= ssl.OP_NO_TICKET | ssl.OP_NO_RENEGOTIATION
        context.set_alpn_protocols(['http/1.1'])
        context.load_cert_chain(str(certificate), str(private_key))
        self._context = context
        self._pending, self._logical, self._http_deadlines = {}, {}, {}
        super().__init__(authorization, **options)

    def origin(self, role='primary'):
        return {**super().origin(role), 'scheme': 'https'}

    def url(self, identity):
        require(identity in BY_ID, 'fixture-vector')
        vector = BY_ID[identity]
        return f'https://127.0.0.1:{self.ports[vector.role]}' + vector.path.decode('ascii')

    def _accept(self, listener):
        existing = set(self.clients)
        super()._accept(listener)
        for plain in set(self.clients) - existing:
            record = self.clients.pop(plain)
            self.selector.unregister(plain)
            record.registered = False
            try:
                secure = self._context.wrap_socket(plain, server_side=True, do_handshake_on_connect=False)
            except (OSError, ValueError):
                plain.close()
                record.observation.update(state='closed', closeReason='tls-peer-setup-failed')
                self._event('peer-connection-closed', record, reason='tls-peer-setup-failed')
                self.failure = 'tls-peer-setup-failed'
                self.close()
                return
            stream = _Channel(self, secure)
            self.clients[stream] = record
            self._http_deadlines[stream] = record.deadline
            record.deadline = min(record.deadline, self.clock() + HANDSHAKE_SECONDS)
            record.observation['tls'] = {'state': 'handshake', 'version': None, 'alpn': None}
            self._logical[stream] = selectors.EVENT_READ
            self._need(stream, 'handshake', selectors.EVENT_READ)

    def _need(self, stream, operation, events):
        require(operation in {'handshake', 'read', 'write'}
                and type(events) is int and events in {selectors.EVENT_READ, selectors.EVENT_WRITE},
                'tls-peer-readiness')
        self._pending[stream] = (operation, events)
        super()._set_events(stream, self.clients[stream], events)

    def _set_events(self, stream, record, events):
        self._logical[stream] = events
        super()._set_events(stream, record, self._pending.get(stream, (None, events))[1])

    def event(self, key, mask):
        require(self.owns(key), 'fixture-foreign-selector-event')
        stream = key.fileobj
        if self.closed or stream in self.listeners:
            return super().event(key, mask)
        record = self.clients.get(stream)
        if record is None:
            return
        pending = self._pending.get(stream)
        if pending:
            operation, needed = pending
            if not mask & needed:
                return
            del self._pending[stream]
            if operation == 'handshake':
                try:
                    stream.stream.do_handshake()
                    version, alpn = stream.stream.version(), stream.stream.selected_alpn_protocol()
                    require(version in {'TLSv1.2', 'TLSv1.3'} and alpn == 'http/1.1', 'tls-peer-protocol')
                    record.observation['tls'].update(state='established', version=version, alpn=alpn)
                    record.deadline = self._http_deadlines.pop(stream)
                    self._set_events(stream, record, selectors.EVENT_READ)
                    super().event(self.selector.get_key(stream), selectors.EVENT_READ)
                except ssl.SSLWantReadError:
                    self._need(stream, operation, selectors.EVENT_READ)
                except ssl.SSLWantWriteError:
                    self._need(stream, operation, selectors.EVENT_WRITE)
                except (OSError, ValueError):
                    self._close_client(stream, record, 'tls-handshake-failed')
                return
            # A TLS write can need readable transport, and vice versa. Resume
            # that original operation rather than dispatching an unrelated one.
            mask = selectors.EVENT_READ if operation == 'read' else selectors.EVENT_WRITE
        super().event(key, mask)
        if stream in self.clients and stream not in self._pending and record.registered:
            super()._set_events(stream, record, self._logical[stream])

    def tick(self):
        super().tick()
        # OpenSSL may already own decrypted bytes after the transport fd stops
        # reporting readiness. Bound this work to one window per live channel;
        # an explicitly held/unregistered HTTP gate stays held.
        for stream, record in list(self.clients.items()):
            if not record.registered or self._pending.get(stream, (None,))[0] == 'handshake':
                continue
            try:
                buffered = stream.stream.pending()
            except OSError:
                self._close_client(stream, record, 'connection-lost')
                continue
            if buffered and self._logical[stream] & selectors.EVENT_READ:
                self.event(self.selector.get_key(stream), selectors.EVENT_READ)

    def _close_client(self, stream, record, reason):
        self._pending.pop(stream, None)
        self._logical.pop(stream, None)
        self._http_deadlines.pop(stream, None)
        if 'tls' in record.observation:
            record.observation['tls']['state'] = ('closed' if record.observation['tls']['version']
                                                  else 'handshake-failed')
        super()._close_client(stream, record, reason)

    def _start_request(self, stream, record):
        # Redirect vectors contain a plain HTTP Location; they are not TLS
        # redirect evidence. Keep this fixture's advertised finite scope exact.
        require(record.parser.path in {BY_ID[name].path for name in
            ('domain-json', 'http-404', 'http-500', 'pending-headers', 'partial-body')},
            'tls-peer-vector-unavailable')
        super()._start_request(stream, record)

    def observation(self):
        value = super().observation()
        value['schemaVersion'] = TLS_PROFILE
        value['tlsProfile'] = {'minimum': 'TLSv1.2', 'maximum': 'TLSv1.3', 'alpn': 'http/1.1',
            'handshakeSeconds': HANDSHAKE_SECONDS, 'providerAccountingQualified': False}
        return value


def validate_tls(value):
    profile = value.get('tlsProfile') if type(value) is dict else None
    require(type(value) is dict and value.get('schemaVersion') == TLS_PROFILE
            and type(profile) is dict and profile == {'minimum': 'TLSv1.2', 'maximum': 'TLSv1.3', 'alpn': 'http/1.1',
                'handshakeSeconds': HANDSHAKE_SECONDS, 'providerAccountingQualified': False}, 'tls-peer-profile')
    require(type(profile['handshakeSeconds']) is int and profile['providerAccountingQualified'] is False,
            'tls-peer-profile-types')
    origins = value.get('origins')
    require(type(origins) is dict and set(origins) == {'primary', 'secondary'}
            and all(type(origin) is dict and origin.get('scheme') == 'https' for origin in origins.values()),
            'tls-peer-origins')
    # Reuse only the original HTTP framing/counter/owner predicates. The public
    # record remains explicitly TLS and is never accepted as a plain-HTTP receipt.
    framing = {**value, 'schemaVersion': PROFILE,
        'origins': {role: {**origin, 'scheme': 'http'} for role, origin in origins.items()}}
    validate(framing)
    for row in value['requests']:
        tls = row.get('tls')
        if row.get('closeReason') == 'fixture-connection-bound':
            require(tls is None, 'tls-peer-refused-before-handshake')
            continue
        require(type(tls) is dict and set(tls) == {'state', 'version', 'alpn'}
                and tls['state'] in {'handshake', 'established', 'closed', 'handshake-failed'}, 'tls-peer-observation')
        established = tls['state'] in {'established', 'closed'}
        require((tls['version'] in {'TLSv1.2', 'TLSv1.3'} and tls['alpn'] == 'http/1.1') if established
                else tls['version'] is tls['alpn'] is None, 'tls-peer-observed-protocol')
        require(('vector' not in row or established)
                and ((row['state'] == 'closed') == (tls['state'] in {'closed', 'handshake-failed'})),
                'tls-peer-before-http-or-after-close')
