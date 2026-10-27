"""Reader controls only; these synthetic rows are not canonical/runtime evidence."""
from pathlib import Path
import tempfile
import unittest

from tools import qualify_stream_outers as owner


class StreamOuterOwnerReader(unittest.TestCase):
    def test_exact_case_success_cannot_be_replaced_by_ignored_wrong_or_duplicate_rows(self):
        for case in (*owner.PRIVATE_CASES, *owner.PUBLIC_CASES):
            raw = (f'test {case} ... ok\n\ntest result: ok. 1 passed; 0 failed; '
                '0 ignored; 0 measured; 17 filtered out; finished in 0.01s\n').encode()
            with self.subTest(case=case):
                value = owner.result(raw, case)
                self.assertEqual((value['passed'], value['ignored']), (1, 0))
                self.assertEqual(value['scope'], 'private-canonical-entry-counter-owner'
                    if case in owner.PRIVATE_CASES else 'public-original-ActivationBudget')
                for changed in (raw + raw, raw.replace(b'0 ignored', b'1 ignored'),
                    raw.replace(b'1 passed', b'0 passed'),
                    raw.replace(case.encode(), b'wrong::case')):
                    with self.assertRaises(ValueError):
                        owner.result(changed, case)
        with self.assertRaises(ValueError):
            owner.result(b'', 'unknown::case')
        for case in (*owner.CONSUMER_PRIVATE_CASES, *owner.CONSUMER_PUBLIC_CASES):
            raw = (f'test {case} ... ok\n\ntest result: ok. 1 passed; 0 failed; '
                '0 ignored; 0 measured; 17 filtered out; finished in 0.01s\n').encode()
            with self.subTest(consumer_case=case):
                value = owner.consumer_result(raw, case)
                self.assertEqual((value['passed'], value['ignored']), (1, 0))
                self.assertEqual(value['scope'], 'private-consumer-implementation-counter'
                    if case in owner.CONSUMER_PRIVATE_CASES else 'public-original-ActivationBudget')
                for changed in (raw + raw, raw.replace(b'0 ignored', b'1 ignored'),
                    raw.replace(b'1 passed', b'0 passed'),
                    raw.replace(case.encode(), b'wrong::case')):
                    with self.assertRaises(ValueError):
                        owner.consumer_result(changed, case)
        for case in (*owner.PRIVATE_CASES, 'unknown::case'):
            with self.assertRaises(ValueError):
                owner.consumer_result(b'', case)
        for case in (*owner.PRODUCER_PRIVATE_CASES, *owner.PRODUCER_PUBLIC_CASES):
            raw = (f'test {case} ... ok\n\ntest result: ok. 1 passed; 0 failed; '
                '0 ignored; 0 measured; 17 filtered out; finished in 0.01s\n').encode()
            with self.subTest(producer_case=case):
                value = owner.producer_result(raw, case)
                self.assertEqual((value['passed'], value['ignored']), (1, 0))
                self.assertEqual(value['scope'], 'private-producer-implementation-counter'
                    if case in owner.PRODUCER_PRIVATE_CASES else 'public-original-ActivationBudget')
                for changed in (raw + raw, raw.replace(b'0 ignored', b'1 ignored'),
                    raw.replace(b'1 passed', b'0 passed'),
                    raw.replace(case.encode(), b'wrong::case')):
                    with self.assertRaises(ValueError):
                        owner.producer_result(changed, case)
        for case in (*owner.PRIVATE_CASES, *owner.CONSUMER_PRIVATE_CASES, 'unknown::case'):
            with self.assertRaises(ValueError):
                owner.producer_result(b'', case)
        self.assertEqual((len(owner.FACTORY_PRIVATE_CASES), len(owner.FACTORY_PUBLIC_CASES)), (5, 4))
        self.assertEqual(owner.FACTORY_AFFECTED_PRIVATE_CASES, owner.PRODUCER_PRIVATE_CASES[-1:])
        self.assertEqual(owner.FACTORY_AFFECTED_PUBLIC_CASES, owner.PRODUCER_NEW_PUBLIC_CASES[-2:])
        for case in (*owner.FACTORY_PRIVATE_CASES, *owner.FACTORY_PUBLIC_CASES):
            raw = (f'test {case} ... ok\n\ntest result: ok. 1 passed; 0 failed; '
                '0 ignored; 0 measured; 17 filtered out; finished in 0.01s\n').encode()
            with self.subTest(factory_case=case):
                value = owner.factory_result(raw, case)
                self.assertEqual((value['passed'], value['ignored']), (1, 0))
                self.assertEqual(value['scope'], 'private-producer-factory-implementation-counter'
                    if case in owner.FACTORY_PRIVATE_CASES else 'public-original-ActivationBudget')
                for changed in (raw + raw, raw.replace(b'0 ignored', b'1 ignored'),
                    raw.replace(b'1 passed', b'0 passed'),
                    raw.replace(case.encode(), b'wrong::case')):
                    with self.assertRaises(ValueError):
                        owner.factory_result(changed, case)
        for case in (*owner.PRIVATE_CASES, *owner.CONSUMER_PRIVATE_CASES, 'unknown::case'):
            with self.assertRaises(ValueError):
                owner.factory_result(b'', case)
        self.assertEqual((len(owner.IO_CASES), len(owner.IO_NEW_CASES)), (5, 3))
        for index, case in enumerate(owner.IO_CASES):
            raw = (f'test {case} ... ok\n\ntest result: ok. 1 passed; 0 failed; '
                '0 ignored; 0 measured; 17 filtered out; finished in 0.01s\n').encode()
            with self.subTest(io_case=case):
                value = owner.io_operation_result(raw, case)
                self.assertEqual((value['passed'], value['ignored']), (1, 0))
                self.assertEqual(value['scope'], 'original-Phase3-memory-broker-unit' if index < 3
                    else 'node-compiled-layout-unit' if index == 3 else 'legacy-Phase1-IO-reference')
                for changed in (raw + raw, raw.replace(b'0 ignored', b'1 ignored'),
                    raw.replace(b'1 passed', b'0 passed'),
                    raw.replace(case.encode(), b'wrong::case')):
                    with self.assertRaises(ValueError):
                        owner.io_operation_result(changed, case)
        for case in (*owner.FACTORY_PRIVATE_CASES, *owner.FACTORY_PUBLIC_CASES, 'unknown::case'):
            with self.assertRaises(ValueError):
                owner.io_operation_result(b'', case)
        import json
        self.assertEqual((len(owner.IO_GRAPH_CASES), len(owner.IO_GRAPH_NEW_CASES)), (8, 7))
        self.assertEqual(owner.IO_GRAPH_CASES[-1], owner.IO_CASES[-1])
        self.assertEqual(owner.IO_GRAPH_CHECK_ARGS, (
            'check', '--locked', '--tests', '--all-features',
            '-p', 'latent-http', '-p', 'latent-blobs', '-p', 'latent-streams',
            '-p', 'latent-wasmtime', '-p', 'latentd', '--message-format=json'))
        for index, case in enumerate(owner.IO_GRAPH_CASES):
            raw = (f'test {case} ... ok\n\ntest result: ok. 1 passed; 0 failed; '
                '0 ignored; 0 measured; 17 filtered out; finished in 0.01s\n').encode()
            with self.subTest(io_graph_case=case):
                value = owner.io_graph_result(raw, case)
                self.assertEqual((value['passed'], value['ignored']), (1, 0))
                self.assertEqual(value['scope'], 'exact-layout-provider-future-backing-instrument-control'
                    if index < 2 else 'allocation-free-provider-refusal-control' if index == 2
                    else 'legacy-Phase1-IO-reference' if index == 7
                    else 'original-Phase3-broker-owned-graph-control')
                for changed in (raw + raw, raw.replace(b'0 ignored', b'1 ignored'),
                    raw.replace(b'1 passed', b'0 passed'),
                    raw.replace(case.encode(), b'wrong::case')):
                    with self.assertRaises(ValueError):
                        owner.io_graph_result(changed, case)
        for case in (*owner.IO_NEW_CASES, 'unknown::case'):
            with self.assertRaises(ValueError):
                owner.io_graph_result(b'', case)
        records = []
        for manifest, target, source in owner.IO_GRAPH_CHECK_TARGETS:
            path = (owner.ROOT / manifest).resolve()
            records.append({'reason': 'compiler-artifact', 'manifest_path': str(path),
                'target': {'kind': ['lib'], 'name': target,
                    'src_path': str(path.parent / source)},
                'profile': {'test': True}, 'executable': None, 'features': []})
        finished = {'reason': 'build-finished', 'success': True}
        def raw_inventory(rows):
            return b''.join((json.dumps(row) + '\n').encode() for row in rows)
        observed = owner.io_graph_check_result(raw_inventory([*records, finished]))
        self.assertEqual([row['target'] for row in observed],
            [row[1] for row in owner.IO_GRAPH_CHECK_TARGETS])
        self.assertTrue(all(row['libtestTypechecked'] for row in observed))
        for rows in (records, [*records[:-1], finished], [*records, records[0], finished],
            [*records, {'reason': 'build-finished', 'success': False}],
            [*records, finished, records[0]]):
            with self.assertRaises(ValueError):
                owner.io_graph_check_result(raw_inventory(rows))
        for field, value in (('executable', '/tmp/unowned-test'),
            ('target', {'kind': ['lib'], 'name': 'counterfeit', 'src_path': '/tmp/x'}),
            ('profile', {'test': False})):
            changed = [{**records[0], field: value}, *records[1:], finished]
            with self.assertRaises(ValueError):
                owner.io_graph_check_result(raw_inventory(changed))
        self.assertEqual((len(owner.IO_COPY_CASES), len(owner.IO_COPY_NEW_CASES)), (3, 1))
        self.assertEqual(owner.IO_COPY_CAP_CASES[1], owner.IO_GRAPH_CASES[5])
        self.assertEqual(owner.IO_COPY_MANAGED_CASE,
            'resource_guest_drains_chunks_and_trailers_then_reclaims_all_owners')
        self.assertEqual(owner.IO_COPY_CHECK_ARGS, ('check', '--locked', '--tests',
            '--all-features', '-p', 'latent-streams', '--message-format=json'))
        for index, case in enumerate(owner.IO_COPY_CASES):
            raw = (f'test {case} ... ok\n\ntest result: ok. 1 passed; 0 failed; '
                '0 ignored; 0 measured; 17 filtered out; finished in 0.01s\n').encode()
            value = owner.io_copy_result(raw, case)
            self.assertEqual((value['passed'], value['ignored']), (1, 0))
            self.assertEqual(value['scope'], 'original-Phase3-affine-copy-owner-control'
                if index == 0 else 'affected-original-Phase3-transfer-capacity-control'
                if index == 1 else 'managed-component-streaming-http-lowering')
            for changed in (raw + raw, raw.replace(b'0 ignored', b'1 ignored'),
                raw.replace(b'1 passed', b'0 passed'), raw.replace(case.encode(), b'wrong::case')):
                with self.assertRaises(ValueError):
                    owner.io_copy_result(changed, case)
        for case in (*owner.IO_GRAPH_CASES[:5], 'unknown::case'):
            with self.assertRaises(ValueError):
                owner.io_copy_result(b'', case)
        manifest, target, source = owner.IO_COPY_CHECK_TARGETS[0]
        path = (owner.ROOT / manifest).resolve()
        checked = {'reason': 'compiler-artifact', 'manifest_path': str(path),
            'target': {'kind': ['lib'], 'name': target, 'src_path': str(path.parent / source)},
            'profile': {'test': True}, 'executable': None, 'features': []}
        self.assertEqual(owner.io_copy_check_result(raw_inventory([checked, finished]))[0]['target'],
            'latent_streams')
        for rows in ([checked], [finished], [checked, checked, finished],
            [checked, {'reason': 'build-finished', 'success': False}]):
            with self.assertRaises(ValueError):
                owner.io_copy_check_result(raw_inventory(rows))
        for name in owner.IO_COPY_FORBIDDEN_FIXTURE_ENV:
            with self.assertRaises(ValueError):
                owner.require_io_copy_environment({name: 'external-fixture'})
            environment = {name: 'external-fixture', 'PATH': 'normal-pinned-tools'}
            self.assertIs(owner.io_copy_environment(environment), environment)
            self.assertEqual(environment, {'PATH': 'normal-pinned-tools'})
            owner.require_io_copy_environment(environment)

        self.assertEqual((len(owner.BLOB_COPY_CASES), len(owner.BLOB_COPY_NEW_CASES)), (4, 3))
        self.assertEqual(owner.BLOB_COPY_MANAGED_CASE,
            'guest_writes_seals_and_reads_exact_bounded_chunks')
        self.assertEqual(owner.BLOB_COPY_CHECK_ARGS, ('check', '--locked', '--tests',
            '--all-features', '-p', 'latent-blobs', '-p', 'latent-wasmtime', '--message-format=json'))
        for index, case in enumerate(owner.BLOB_COPY_CASES):
            raw = (f'test {case} ... ok\n\ntest result: ok. 1 passed; 0 failed; '
                '0 ignored; 0 measured; 17 filtered out; finished in 0.01s\n').encode()
            value = owner.blob_copy_result(raw, case)
            self.assertEqual((value['passed'], value['ignored']), (1, 0))
            self.assertEqual(value['scope'], 'original-Phase3-affine-blob-copy-and-pooled-request-control'
                if index < 3 else 'managed-component-local-blob-chunk-lowering')
            for changed in (raw + raw, raw.replace(b'0 ignored', b'1 ignored'),
                raw.replace(b'1 passed', b'0 passed'), raw.replace(case.encode(), b'wrong::case')):
                with self.assertRaises(ValueError):
                    owner.blob_copy_result(changed, case)
        for case in (*owner.IO_COPY_CASES, 'unknown::case'):
            with self.assertRaises(ValueError):
                owner.blob_copy_result(b'', case)
        records = []
        for manifest, target, source in owner.BLOB_COPY_CHECK_TARGETS:
            path = (owner.ROOT / manifest).resolve()
            records.append({'reason': 'compiler-artifact', 'manifest_path': str(path),
                'target': {'kind': ['lib'], 'name': target, 'src_path': str(path.parent / source)},
                'profile': {'test': True}, 'executable': None, 'features': []})
        self.assertEqual([r['target'] for r in owner.blob_copy_check_result(raw_inventory([*records, finished]))],
            ['latent_blobs', 'latent_wasmtime'])
        for rows in (records, [finished], [records[0], finished], [*records, records[0], finished],
            [*records, {'reason': 'build-finished', 'success': False}], [*records, finished, records[0]]):
            with self.assertRaises(ValueError):
                owner.blob_copy_check_result(raw_inventory(rows))
        for field, value in (('executable', '/tmp/unowned-test'),
            ('target', {'kind': ['lib'], 'name': 'counterfeit', 'src_path': '/tmp/x'}),
            ('profile', {'test': False})):
            with self.assertRaises(ValueError):
                owner.blob_copy_check_result(raw_inventory([{**records[0], field: value}, records[1], finished]))

        self.assertEqual((len(owner.BLOB_INPUT_CASES), len(owner.BLOB_INPUT_NEW_CASES)), (4, 3))
        self.assertEqual(owner.BLOB_INPUT_MANAGED_CASE, owner.BLOB_COPY_MANAGED_CASE)
        self.assertEqual(owner.BLOB_INPUT_CHECK_ARGS, owner.BLOB_COPY_CHECK_ARGS)
        for index, case in enumerate(owner.BLOB_INPUT_CASES):
            raw = (f'test {case} ... ok\n\ntest result: ok. 1 passed; 0 failed; '
                '0 ignored; 0 measured; 17 filtered out; finished in 0.01s\n').encode()
            value = owner.blob_input_result(raw, case)
            self.assertEqual((value['passed'], value['ignored']), (1, 0))
            self.assertEqual(value['scope'], 'original-Phase3-prepaid-blob-input-bridge-control'
                if index < 3 else 'managed-component-local-blob-input-and-readback')
            for changed in (raw + raw, raw.replace(b'0 ignored', b'1 ignored'),
                raw.replace(b'1 passed', b'0 passed'), raw.replace(case.encode(), b'wrong::case')):
                with self.assertRaises(ValueError):
                    owner.blob_input_result(changed, case)
        for case in (*owner.BLOB_COPY_CAP_CASES, *owner.IO_COPY_CASES, 'unknown::case'):
            with self.assertRaises(ValueError):
                owner.blob_input_result(b'', case)
        records = []
        for manifest, target, source in owner.BLOB_INPUT_CHECK_TARGETS:
            path = (owner.ROOT / manifest).resolve()
            records.append({'reason': 'compiler-artifact', 'manifest_path': str(path),
                'target': {'kind': ['lib'], 'name': target, 'src_path': str(path.parent / source)},
                'profile': {'test': True}, 'executable': None, 'features': []})
        self.assertEqual([r['target'] for r in owner.blob_input_check_result(raw_inventory([*records, finished]))],
            ['latent_blobs', 'latent_wasmtime'])
        for rows in (records, [finished], [records[0], finished], [*records, records[0], finished],
            [*records, {'reason': 'build-finished', 'success': False}], [*records, finished, records[0]]):
            with self.assertRaises(ValueError):
                owner.blob_input_check_result(raw_inventory(rows))
        for field, value in (('executable', '/tmp/unowned-test'),
            ('target', {'kind': ['lib'], 'name': 'counterfeit', 'src_path': '/tmp/x'}),
            ('profile', {'test': False})):
            with self.assertRaises(ValueError):
                owner.blob_input_check_result(raw_inventory([{**records[0], field: value}, records[1], finished]))

    def test_private_fixture_identity_is_bounded_and_changes_are_observed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'fixture.wasm'
            for raw in (b'', b'not-a-wasm-component', b'\0asm' + b'0' * 65536):
                path.write_bytes(raw)
                with self.assertRaises((ValueError, OSError)):
                    owner.fixture_identity(path)
            # This is a reader identity control, never a parse/runtime claim.
            path.write_bytes(b'\0asm' + b'\x00' * 12)
            first = owner.fixture_identity(path)
            path.write_bytes(b'\0asm' + b'\x01' * 12)
            self.assertNotEqual(owner.fixture_identity(path), first)


if __name__ == '__main__':
    unittest.main()
