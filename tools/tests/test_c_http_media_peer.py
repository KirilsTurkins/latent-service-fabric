"""Exact, non-disclosing observation of the ordinary C POST's media type."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.c_http_media_peer import EXPECTED, MediaPeer
from tools.phase2_operator_process import WorkflowError
from tools.standard_http.peer import Peer
from tools.standard_http.protocol import FixtureError, Request


class MediaPeerObservation(unittest.TestCase):
    def run_request(self, value):
        peer = object.__new__(MediaPeer)
        peer._media_checked = peer._media_matches = False
        headers = {} if value is None else {b'content-type': value}
        record = SimpleNamespace(vector=SimpleNamespace(identity='method-bytes'),
                                 parser=SimpleNamespace(method=b'POST', headers=headers))
        with patch.object(Peer, '_complete_request', return_value='original-response') as original:
            self.assertEqual(peer._complete_request('stream', record), 'original-response')
            original.assert_called_once_with('stream', record)
            with self.assertRaises(WorkflowError):
                peer._complete_request('stream', record)
        return peer.media_observation()

    def test_only_the_exact_type_matches_without_retaining_the_received_value(self):
        for value, matched in ((EXPECTED, True), (None, False),
                               (b'text/plain', False), (EXPECTED + b'X', False)):
            with self.subTest(value=value):
                result = self.run_request(value)
                self.assertIs(result['exactMatch'], matched)
                self.assertFalse(result['arbitraryHeaderValueRetained'])
                self.assertEqual(set(result), {'expected', 'exactMatch', 'arbitraryHeaderValueRetained'})

    def test_unobserved_peer_cannot_report_a_match(self):
        peer = object.__new__(MediaPeer)
        peer._media_checked = peer._media_matches = False
        with self.assertRaises(WorkflowError):
            peer.media_observation()

    def test_observation_consumes_the_real_peer_parser_and_rejects_duplicate_headers(self):
        request = Request()
        request.feed(b'POST /conformance/echo HTTP/1.1\r\nHost: localhost\r\n'
                     b'Content-Type: text/plain; charset=utf-8\r\nContent-Length: 0\r\n\r\n')
        self.assertTrue(request.complete)
        peer = object.__new__(MediaPeer)
        peer._media_checked = peer._media_matches = False
        row = SimpleNamespace(vector=SimpleNamespace(identity='method-bytes'), parser=request)
        with patch.object(Peer, '_complete_request'):
            peer._complete_request('stream', row)
        self.assertTrue(peer.media_observation()['exactMatch'])
        duplicate = Request()
        with self.assertRaises(FixtureError):
            duplicate.feed(b'POST /conformance/echo HTTP/1.1\r\nHost: localhost\r\n'
                           b'Content-Type: text/plain; charset=utf-8\r\n'
                           b'content-type: different\r\nContent-Length: 0\r\n\r\n')
