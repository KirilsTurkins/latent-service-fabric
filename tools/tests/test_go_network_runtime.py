"""Closed real-harness evidence and preservation of the guarded ordinary source."""
import hashlib
import json
from pathlib import Path
import re
import unittest

from tools import go_network_read_barrier as runtime

ROOT = Path(__file__).resolve().parents[2]


class GoNetworkRuntimeTests(unittest.TestCase):
    def rows(self):
        result = []
        for label, mode, output, contacts in runtime.EXPECTED:
            if label in ('fragmented-read', 'cancel-pending-read'):
                result.append(('GO_NETWORK_READ_EDGE', {'case': label, 'constructedReads': 2,
                    'retiredReadDeliveredBytes': 1, 'deliveredReadBytes': 1, 'pendingReads': 1,
                    'pendingOperations': 1, 'ioCalls': 1, 'streamOwners': 1, 'connections': 1,
                    'retiredGenerations': 0, 'quarantinedConnections': 0,
                    'providerStopped': False, 'currentGenerationRetired': False, 'liveStores': 1, 'activeActivations': 1}))
            if label == 'cancel-pending-read':
                result.append(('GO_NETWORK_CANCEL_EDGE', {'case': label, 'readDropStartsBefore': 1,
                    'readDropStartsAfterAccepted': 1, 'sameConnection': True, 'sameGenerationCurrent': True}))
            result.append(('GO_NETWORK_OWNER', {'case': label, 'stores': 0, 'instances': 0,
                'streamOwners': 0, 'ioOwners': 0, 'kernelRetirementQualified': False}))
            result.append(('GO_NETWORK_CASE', {'case': label, 'mode': mode, 'result': output, 'contacts': contacts}))
        result.append(('GO_NETWORK_COMPLETE', {'cases': 13, 'contacts': 5, 'cleanLogicalProviderStop': True,
            'kernelRetirementQualified': False, 'normalProviderInstalled': False}))
        return result

    def output(self, rows=None):
        rows = self.rows() if rows is None else rows
        return ('\n'.join(name + ' ' + json.dumps(row) for name, row in rows) + '\n' +
            'test ' + runtime.CASE + ' ... ok\n' +
            'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 1.0s\n').encode()

    def test_complete_ordered_go_cases_and_zero_user_owners_do_not_claim_kernel_retirement(self):
        record = runtime.outcomes(self.output())
        expanded = self.output().replace(b"0 filtered out", b"2 filtered out")
        self.assertEqual(runtime.outcomes(expanded, filtered=2), record)
        with self.assertRaises(ValueError):
            runtime.outcomes(expanded, filtered=1)
        self.assertEqual(len(record['cases']), 13)
        self.assertEqual(sum(row['contacts'] for row in record['cases']), 5)
        self.assertEqual(len(record['userSpaceOwners']), 13)
        self.assertEqual([x['constructedReads'] for x in record['readEdges']], [2, 2])
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
                           ('kernelRetirementQualified', True), ('cases', 13.0), ('contacts', 3)):
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

    def test_each_case_requires_a_constructed_read_after_prior_byte_retirement(self):
        for label in ('fragmented-read', 'cancel-pending-read'):
            for mutation in ('missing', 'duplicate', 'reordered', 'first-read-post-byte',
                             'provisional-second', 'guard-retired', 'other-operation',
                             'second-connection', 'retired-generation', 'quarantine', 'stopped', 'retired-current',
                             'two-bytes', 'boolean-counter', 'unknown-field'):
                rows = self.rows()
                index = next(i for i, (name, row) in enumerate(rows)
                             if name == 'GO_NETWORK_READ_EDGE' and row['case'] == label)
                if mutation == 'missing':
                    rows.pop(index)
                elif mutation == 'duplicate':
                    rows.insert(index, rows[index])
                elif mutation == 'reordered':
                    rows[index], rows[index + 1] = rows[index + 1], rows[index]
                elif mutation == 'first-read-post-byte':
                    rows[index][1].update(constructedReads=1, retiredReadDeliveredBytes=0)
                else:
                    key, value = {'provisional-second': ('constructedReads', 1),
                        'guard-retired': ('pendingReads', 0), 'other-operation': ('pendingOperations', 2),
                        'second-connection': ('connections', 2), 'retired-generation': ('retiredGenerations', 1),
                        'quarantine': ('quarantinedConnections', 1), 'stopped': ('providerStopped', True),
                        'retired-current': ('currentGenerationRetired', True), 'two-bytes': ('deliveredReadBytes', 2),
                        'boolean-counter': ('ioCalls', True), 'unknown-field': ('extra', 1)}[mutation]
                    rows[index][1][key] = value
                with self.subTest(case=label, mutation=mutation), self.assertRaises(ValueError):
                    runtime.outcomes(self.output(rows))

    def test_cancellation_requires_the_same_undropped_original_owner(self):
        for field, bad in (('readDropStartsBefore', 2), ('readDropStartsAfterAccepted', 2),
                           ('sameConnection', False), ('sameGenerationCurrent', False),
                           ('readDropStartsAfterAccepted', True)):
            rows = self.rows()
            index = next(i for i, (name, _) in enumerate(rows) if name == 'GO_NETWORK_CANCEL_EDGE')
            rows[index][1][field] = bad
            with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                runtime.outcomes(self.output(rows))
        for mutation in ('missing', 'duplicate', 'reordered'):
            rows = self.rows()
            index = next(i for i, (name, _) in enumerate(rows) if name == 'GO_NETWORK_CANCEL_EDGE')
            if mutation == 'missing':
                rows.pop(index)
            elif mutation == 'duplicate':
                rows.insert(index, rows[index])
            else:
                rows[index], rows[index + 1] = rows[index + 1], rows[index]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                runtime.outcomes(self.output(rows))

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
        self.assertIn("'--features', 'development-go-network-read-witness'", source)
        self.assertNotIn("'--workspace'", source)
        self.assertNotIn('actual-private-owner-reference', source)
        self.assertEqual(source.count('compiler.compile('), 1)
        native = re.sub(r'\s+', ' ', (ROOT / 'crates/latent-wasmtime/tests/go_outbound_streams.rs').read_text())
        for owner in ('usage.delivered_read_bytes == 1', 'usage.pending_operations == 1',
                      'usage.read_admissions != 2', 'usage.retired_read_delivered_bytes != 1',
                      'usage.pending_reads != 1', 'status.retired_generations != 0',
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
