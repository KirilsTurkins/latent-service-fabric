"""Reject fabricated or incomplete native reference output, never grant readiness."""
import json
import unittest

from tools.qualify_go_network_compile import OWNER_CASES, owner_result


class GoNetworkReferenceTests(unittest.TestCase):
    def rows(self):
        rows = [{'Action': 'start', 'Package': 'example.invalid/stream-owner'}]
        for case in OWNER_CASES:
            rows.extend([{'Action': 'run', 'Test': case, 'Package': 'example.invalid/stream-owner'},
                         {'Action': 'pass', 'Test': case, 'Package': 'example.invalid/stream-owner'}])
        rows.append({'Action': 'pass', 'Package': 'example.invalid/stream-owner'})
        return rows

    def encoded(self, rows):
        return b'\n'.join(json.dumps(row).encode() for row in rows) + b'\n'

    def test_all_six_exact_real_owner_case_successes_and_package_success_are_required(self):
        self.assertEqual(owner_result(self.encoded(self.rows())), list(OWNER_CASES))
        for rows in (self.rows()[:-1], self.rows()[1:3], [], self.rows()[:-3] + self.rows()[-1:]):
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                owner_result(self.encoded(rows))

    def test_failed_skipped_unknown_duplicate_or_foreign_native_results_are_rejected(self):
        for change in ('fail', 'skip', 'unknown'):
            rows = self.rows()
            rows[2]['Action'] = change
            with self.subTest(change=change), self.assertRaises(ValueError):
                owner_result(self.encoded(rows))
        for addition in ({'Action': 'pass', 'Test': 'ForeignCase', 'Package': 'example.invalid/stream-owner'},
                         {'Action': 'pass', 'Test': OWNER_CASES[0], 'Package': 'example.invalid/stream-owner'},
                         {'Action': 'pass', 'Package': 'example.invalid/stream-owner'},
                         {'Action': 'pass', 'Test': OWNER_CASES[0], 'Package': 'foreign/private'}):
            with self.assertRaises(ValueError):
                owner_result(self.encoded(self.rows() + [addition]))

    def test_reference_output_bound_is_not_lifted_for_compiler_or_protocol_errors(self):
        with self.assertRaisesRegex(ValueError, 'output-bound'):
            owner_result(b' ' * 262145)
        with self.assertRaises(ValueError):
            owner_result(b'not a native Go test event')


if __name__ == '__main__':
    unittest.main()
