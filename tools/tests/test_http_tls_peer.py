"""Portable readiness/receipt controls; TLS handshakes have a separate real lane."""
import copy
import os
from pathlib import Path
import selectors
import socket
import ssl
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools.standard_http.peer import Connection, Peer, READ_WINDOW
from tools.standard_http.protocol import FixtureError
from tools.standard_http.tls_peer import _Channel, TLSPeer, validate_tls


class HttpTlsPeerTests(unittest.TestCase):
    def test_tls_process_refuses_missing_or_unbounded_inputs_before_acquiring_peer(self):
        from tools.standard_http.process_peer import run
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            certificate, key = root/'certificate.pem', root/'key.pem'
            certificate.write_bytes(b'certificate')
            key.write_bytes(b'x'*65537)
            with patch('tools.standard_http.process_peer.Peer') as plain:
                for parameters in ({'certificate':certificate}, {'private_key':key},
                        {'certificate':certificate,'private_key':key},
                        {'certificate':Path('relative.pem'),'private_key':key}):
                    with self.subTest(parameters=tuple(parameters)), self.assertRaisesRegex(ValueError,'standard-http-tls-'):
                        run(root/'absent-credential', **parameters)
                plain.assert_not_called()

    def test_reference_cli_help_bootstraps_outside_checkout_without_network_or_artifacts(self):
        from tools.rust_capsule_project import ROOT
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, '-B', str(ROOT/'tools/qualify_http_tls_peer.py'), '--help'],
                cwd=temporary, env={**os.environ, 'PYTHONPATH':''}, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertIn(b'--output', result.stdout)
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def peer(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for name in ('certificate.pem', 'private.pem'):
            (root/name).write_text('unit-test-placeholder')
        context = Mock()
        context.options = 0
        with patch('tools.standard_http.tls_peer.ssl.SSLContext', return_value=context):
            peer = TLSPeer(b'Bearer '+b'a'*64, root/'certificate.pem', root/'private.pem')
        self.addCleanup(peer.close)
        return peer, context

    def channel(self, peer, operation='read'):
        raw, remote = socket.socketpair()
        self.addCleanup(raw.close)
        self.addCleanup(remote.close)
        secure = Mock()
        secure.fileno.return_value = raw.fileno()
        secure.pending.return_value = 0
        channel = _Channel(peer, secure)
        record = Connection(1, 'primary', peer.clock()+20)
        record.observation = {'request':1, 'role':'primary', 'state':'accepted', 'responseBytesWritten':0,
            'tls':{'state':'handshake' if operation == 'handshake' else 'established',
                   'version':None if operation == 'handshake' else 'TLSv1.3',
                   'alpn':None if operation == 'handshake' else 'http/1.1'}}
        peer.clients[channel] = record
        peer.rows.append(record.observation)
        peer.accepted = 1
        peer._logical[channel] = selectors.EVENT_READ
        peer.selector.register(channel, selectors.EVENT_READ, (peer, 'connection'))
        return channel, record

    def test_public_origins_are_tls_and_keys_or_credentials_never_enter_receipts(self):
        peer, context = self.peer()
        self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertEqual(context.maximum_version, ssl.TLSVersion.TLSv1_3)
        context.set_alpn_protocols.assert_called_once_with(['http/1.1'])
        self.assertTrue(peer.url('domain-json').startswith('https://127.0.0.1:'))
        self.assertEqual(peer.provider_destinations()[0]['origin']['scheme'], 'https')
        value = peer.observation()
        validate_tls(value)
        self.assertNotIn('a'*64, repr(value))
        self.assertNotIn('private.pem', repr(value))

    def test_tls_read_can_require_write_readiness_without_losing_the_read(self):
        owner, secure = Mock(), Mock()
        secure.recv.side_effect = [ssl.SSLWantWriteError(), b'parsed']
        channel = _Channel(owner, secure)
        with self.assertRaises(BlockingIOError):
            channel.recv(READ_WINDOW)
        owner._need.assert_called_once_with(channel, 'read', selectors.EVENT_WRITE)
        self.assertEqual(channel.recv(READ_WINDOW), b'parsed')

    def test_tls_write_retries_retain_exact_buffer_and_require_original_operation(self):
        owner, secure = Mock(), Mock()
        secure.send.side_effect = [ssl.SSLWantReadError(), 3]
        channel = _Channel(owner, secure)
        first = b'original'
        with self.assertRaises(BlockingIOError):
            channel.send(first)
        owner._need.assert_called_once_with(channel, 'write', selectors.EVENT_READ)
        with self.assertRaisesRegex(FixtureError, 'changed-pending-write'):
            channel.send(b'changed')
        self.assertEqual(channel.send((b'x'+first)[1:]), 3)
        self.assertIs(secure.send.call_args_list[0].args[0], secure.send.call_args_list[1].args[0])
        self.assertIsNone(channel.pending_write)

    def test_channel_windows_refuse_before_any_tls_call(self):
        secure, owner = Mock(), Mock()
        channel = _Channel(owner, secure)
        for maximum in (0, -1, True, READ_WINDOW+1):
            with self.assertRaisesRegex(FixtureError, 'read-window'):
                channel.recv(maximum)
        for value in (b'', b'x'*(READ_WINDOW+1), bytearray(b'x')):
            with self.assertRaisesRegex(FixtureError, 'write-window'):
                channel.send(value)
        secure.recv.assert_not_called()
        secure.send.assert_not_called()

    def test_pending_write_resumes_write_on_readable_socket(self):
        peer, _ = self.peer()
        channel, record = self.channel(peer)
        peer._logical[channel] = selectors.EVENT_WRITE
        peer._need(channel, 'write', selectors.EVENT_READ)
        with patch.object(Peer, 'event') as inherited:
            peer.event(peer.selector.get_key(channel), selectors.EVENT_READ)
        self.assertEqual(inherited.call_args.args[1], selectors.EVENT_WRITE)
        self.assertNotIn(channel, peer._pending)
        self.assertEqual(peer.selector.get_key(channel).events, selectors.EVENT_WRITE)

    def test_handshake_requires_matching_readiness_and_exact_alpn_before_http(self):
        peer, _ = self.peer()
        channel, record = self.channel(peer, 'handshake')
        original = record.deadline
        peer._http_deadlines[channel] = original
        peer._need(channel, 'handshake', selectors.EVENT_READ)
        channel.stream.do_handshake.side_effect = [ssl.SSLWantWriteError(), None]
        channel.stream.version.return_value = 'TLSv1.3'
        channel.stream.selected_alpn_protocol.return_value = 'http/1.1'
        with patch.object(Peer, 'event') as inherited:
            peer.event(peer.selector.get_key(channel), selectors.EVENT_READ)
            inherited.assert_not_called()
            peer.event(peer.selector.get_key(channel), selectors.EVENT_READ)
            self.assertEqual(channel.stream.do_handshake.call_count, 1)
            peer.event(peer.selector.get_key(channel), selectors.EVENT_WRITE)
        self.assertEqual(inherited.call_args.args[1], selectors.EVENT_READ)
        self.assertEqual(record.observation['tls'], {'state':'established','version':'TLSv1.3','alpn':'http/1.1'})
        self.assertEqual(record.deadline, original)

    def test_unqualified_alpn_closes_before_request_parsing(self):
        peer, _ = self.peer()
        channel, record = self.channel(peer, 'handshake')
        peer._http_deadlines[channel] = record.deadline
        peer._need(channel, 'handshake', selectors.EVENT_READ)
        channel.stream.version.return_value = 'TLSv1.3'
        channel.stream.selected_alpn_protocol.return_value = None
        with patch.object(Peer, 'event') as inherited:
            peer.event(peer.selector.get_key(channel), selectors.EVENT_READ)
        inherited.assert_not_called()
        self.assertNotIn(channel, peer.clients)
        self.assertEqual(record.observation['tls']['state'], 'handshake-failed')
        self.assertEqual(peer.started, 0)

    def test_decrypted_buffered_readiness_is_driven_but_explicit_gate_stays_held(self):
        peer, _ = self.peer()
        channel, record = self.channel(peer)
        channel.stream.pending.return_value = 4
        with patch.object(peer, 'event') as event:
            peer.tick()
            event.assert_called_once()
            event.reset_mock()
            peer.selector.unregister(channel)
            record.registered = False
            peer.tick()
            event.assert_not_called()

    def test_tls_receipt_does_not_accept_plain_transport_or_provider_qualification(self):
        peer, _ = self.peer()
        value = peer.observation()
        for change in ('plain', 'provider', 'version', 'boolean-integer', 'float-deadline'):
            changed = copy.deepcopy(value)
            if change == 'plain':
                changed['origins']['primary']['scheme'] = 'http'
            elif change == 'provider':
                changed['tlsProfile']['providerAccountingQualified'] = True
            elif change == 'boolean-integer':
                changed['tlsProfile']['providerAccountingQualified'] = 0
            elif change == 'float-deadline':
                changed['tlsProfile']['handshakeSeconds'] = 5.0
            else:
                changed['tlsProfile']['maximum'] = 'TLSv1.4'
            with self.assertRaises(FixtureError):
                validate_tls(changed)
