"""Closed real-harness evidence and preservation of the guarded ordinary source."""
import hashlib
import json
from pathlib import Path
import re
import unittest

from tools import qualify_go_network_runtime as runtime

ROOT = Path(__file__).resolve().parents[2]


class GoNetworkRuntimeTests(unittest.TestCase):
    def rows(self):
        result = []
        for label, mode, output, contacts in runtime.EXPECTED:
            result.append(('GO_NETWORK_OWNER', {'case': label, 'stores': 0, 'instances': 0,
                'streamOwners': 0, 'ioOwners': 0, 'kernelRetirementQualified': False}))
            result.append(('GO_NETWORK_CASE', {'case': label, 'mode': mode, 'result': output, 'contacts': contacts}))
        result.append(('GO_NETWORK_COMPLETE', {'cases': 12, 'contacts': 4, 'cleanLogicalProviderStop': True,
            'kernelRetirementQualified': False, 'normalProviderInstalled': False}))
        return result

    def output(self, rows=None):
        rows = self.rows() if rows is None else rows
        return ('\n'.join(name + ' ' + json.dumps(row) for name, row in rows) + '\n' +
            'test ' + runtime.CASE + ' ... ok\n' +
            'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 1.0s\n').encode()

    def test_complete_ordered_go_cases_and_zero_user_owners_do_not_claim_kernel_retirement(self):
        record = runtime.outcomes(self.output())
        self.assertEqual(len(record['cases']), 12)
        self.assertEqual(sum(row['contacts'] for row in record['cases']), 4)
        self.assertEqual(len(record['userSpaceOwners']), 12)
        self.assertIs(record['completion']['kernelRetirementQualified'], False)
        self.assertIs(record['completion']['normalProviderInstalled'], False)

    def test_missing_duplicate_reordered_or_failed_ordinary_cases_cannot_pass(self):
        for mutation in ('missing', 'duplicate', 'reorder', 'failed'):
            rows = self.rows()
            if mutation == 'missing':
                rows.pop(1)
            elif mutation == 'duplicate':
                rows.insert(2, rows[1])
            elif mutation == 'reorder':
                rows[1], rows[3] = rows[3], rows[1]
            else:
                rows[1][1]['result'] = 'connect-error'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                runtime.outcomes(self.output(rows))

    def test_extra_private_unknown_and_boolean_numeric_case_fields_fail_closed(self):
        for key, value in (('url', 'private.invalid'), ('unknown', True), ('mode', False), ('contacts', 0.0)):
            rows = self.rows()
            rows[1][1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                runtime.outcomes(self.output(rows))
        duplicate = self.output().replace(b'"contacts": 0}', b'"contacts": 1, "contacts": 0}', 1)
        with self.assertRaisesRegex(ValueError, 'duplicate-observation-field'):
            runtime.outcomes(duplicate)

    def test_retained_owner_incomplete_stop_or_kernel_promotion_is_not_completion(self):
        for key, value in (('stores', 1), ('streamOwners', 1), ('ioOwners', False), ('kernelRetirementQualified', True)):
            rows = self.rows()
            rows[0][1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                runtime.outcomes(self.output(rows))
        for key, value in (('cleanLogicalProviderStop', False), ('normalProviderInstalled', True),
                           ('kernelRetirementQualified', True), ('cases', 12.0), ('contacts', 3)):
            rows = self.rows()
            rows[-1][1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                runtime.outcomes(self.output(rows))

    def test_wrong_native_case_ignored_case_or_oversized_output_is_not_actual_execution(self):
        for raw in (self.output().replace(runtime.CASE.encode(), b'other_case'),
                    self.output().replace(b'1 passed; 0 failed; 0 ignored', b'0 passed; 0 failed; 1 ignored'),
                    self.output() + b'x' * 1024 * 1024):
            with self.assertRaises(ValueError):
                runtime.outcomes(raw)

    def test_original_guarded_modes_are_unchanged_and_new_mode_uses_ordinary_half_close_eof(self):
        source = (ROOT / 'sdk/go-guest/runtime/network-conformance/main.go').read_bytes()
        self.assertIn(b'\tcase 9:\n', source)
        begin = source.index(b'\tcase 9:\n')
        end = source.index(b'\n\t}\n\treturn "unexpected-result"', begin)
        original = source[:begin] + source[end + 1:]
        # Exact guarded main.go at the merged source before adding only mode9.
        self.assertEqual(hashlib.sha256(original).hexdigest(), '4e8428e4adcddd1e192e734b27985446a889862bc575a222b230f713513c019f')
        added = source[begin:end]
        self.assertIn(b'net.DialTimeout("tcp", address, time.Second)', added)
        self.assertIn(b'interface{ CloseWrite() error }', added)
        self.assertIn(b'io.ReadAll(connection)', added)
        self.assertNotIn(b'lsf/', source)
        self.assertNotIn(b'net.Pipe', source)

    def test_targeted_native_builder_and_pending_barrier_preserve_real_owners_and_caps(self):
        source = (ROOT / 'tools/qualify_go_network_runtime.py').read_text()
        self.assertIn("['cargo', 'test', '--locked', '-p', 'latent-wasmtime', '--test', 'go_outbound_streams'", source)
        self.assertNotIn("'--workspace'", source)
        self.assertNotIn('actual-private-owner-reference', source)
        self.assertEqual(source.count('compiler.compile('), 1)
        native = re.sub(r'\s+', ' ', (ROOT / 'crates/latent-wasmtime/tests/go_outbound_streams.rs').read_text())
        for owner in ('usage.delivered_read_bytes == 1', 'usage.pending_operations == 1',
                      'CancelDisposition::Accepted', 'active_activations, 1',
                      'tasks: 16', 'waits: 4', 'timers: 2', 'native_owners: 2'):
            self.assertIn(owner, native)
        self.assertNotIn('install_for_qualification', native)  # retained shared fixture owns installation
        fixture = (ROOT / 'crates/latent-wasmtime/tests/local_service/fixture.rs').read_text()
        self.assertIn('consumer.grants.extend(streams::grants());', fixture)
        self.assertIn('consumer.grants = streams::grants();', fixture)
        self.assertRegex(fixture, r'if activation_runtime\.is_some\(\) \{\s*consumer\.grants\.extend')


if __name__ == '__main__':
    unittest.main()
