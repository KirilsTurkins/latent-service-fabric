"""Pure conformance-oracle controls, not guest/backend execution evidence."""
import base64
import copy
import hashlib
import json
import unittest

from tools.standard_http import values
from tools.standard_http.protocol import FixtureError


class StandardHttpValues(unittest.TestCase):
    def test_public_cases_cover_all_methods_binary_utf8_and_optional_metadata(self):
        cases = values.load()
        self.assertEqual({case['method'] for case in cases}, {'GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'})
        self.assertEqual(base64.b64decode(cases[0]['bodyBase64']), b'\x00\xffcaf\xc3\xa9')
        self.assertEqual(cases[0]['header'], 'caf\u00e9')
        self.assertEqual(values.echo(cases[-2]), {'method': 'POST', 'bodyBase64': '',
            'contentLengthPresent': True, 'contentTypePresent': False, 'customHeaderBase64': ''})
        self.assertEqual(values.echo(cases[-1]), {'method': 'POST', 'bodyBase64': '',
            'contentLengthPresent': False, 'contentTypePresent': False, 'customHeaderBase64': None})

    def test_result_oracle_rejects_wrong_bytes_missing_empty_metadata_and_boolean_integers(self):
        case = values.load()[-2]
        expected = {'method': 'POST', 'bodyBase64': '', 'contentLengthPresent': True,
            'contentTypePresent': False, 'customHeaderBase64': ''}
        values.require_result(case, 'values:' + json.dumps(expected))
        for key, changed in (('bodyBase64', 'AA=='), ('customHeaderBase64', None),
                             ('contentTypePresent', True), ('contentLengthPresent', 1), ('extra', 'invented')):
            with self.subTest(key=key), self.assertRaises(FixtureError):
                values.require_result(case, 'values:' + json.dumps(dict(expected, **{key: changed})))
        with self.assertRaises(FixtureError):
            values.require_result(case, '200:domain-success')
        with self.assertRaisesRegex(FixtureError, 'duplicate-field'):
            values.require_result(case, 'values:{"method":"PUT",' + json.dumps(expected)[1:])

    def test_head_requires_status_exact_declared_length_and_no_response_bytes(self):
        case = values.load()[1]
        expected = values.echo(case)
        length = len(json.dumps(expected, sort_keys=True, separators=(',', ':')).encode('utf-8'))
        values.require_result(case, 'values-head:200:' + str(length) + ':0')
        for returned in ('values-head:404:' + str(length) + ':0', 'values-head:200:0:0',
                         'values-head:200:' + str(length) + ':1', 'values:' + json.dumps(expected)):
            with self.subTest(returned=returned), self.assertRaises(FixtureError):
                values.require_result(case, returned)

    def test_peer_oracle_rejects_forged_success_replay_wrong_order_and_changed_transfer(self):
        cases = values.load()
        rows = [{'role': 'primary', 'vector': 'method-bytes', 'method': case['method'], 'state': 'closed',
            'bodyBytes': len(base64.b64decode(case['bodyBase64'])),
            'bodySha256': 'sha256:' + hashlib.sha256(base64.b64decode(case['bodyBase64'])).hexdigest(),
            'requestFraming': 'length' if case['length'] == 'known' else 'chunked'} for case in cases]
        values.require_peer(cases, rows)
        for key, changed in (('method', 'CONNECT'), ('bodyBytes', 0), ('bodySha256', 'sha256:'+'0'*64),
                             ('role', 'secondary'), ('state', 'held-upload'), ('requestFraming', 'chunked')):
            forged = copy.deepcopy(rows)
            forged[0][key] = changed
            with self.subTest(key=key), self.assertRaises(FixtureError):
                values.require_peer(cases, forged)
        for changed in (rows[:-1], rows + rows[:1], list(reversed(rows))):
            with self.assertRaises(FixtureError):
                values.require_peer(cases, changed)


if __name__ == '__main__':
    unittest.main()
