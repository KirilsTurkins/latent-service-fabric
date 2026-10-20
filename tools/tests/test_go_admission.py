"""Fail-closed evidence controls for real signed shared-cell execution."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools import qualify_go_synchronization as reference


def rows():
    return [{'case': case, 'tenant': tenant, 'outcome': outcome}
            for case, tenant, outcome in reference.ADMISSION_ROWS]


def output(values, filtered=48):
    records = '\n'.join('GO_ADMISSION_CASE ' + json.dumps(row) for row in values)
    return (f'test {reference.ADMISSION_CASE} ... ok\n{records}\n'
            f'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; {filtered} filtered out; finished in 1.00s\n').encode()


class GoAdmission(unittest.TestCase):
    def test_all_twelve_ordered_barriers_include_both_tenants_and_cancel_trap_reuse(self):
        values = rows()
        self.assertEqual(reference.admission_observations(output(values), 48), values)
        self.assertEqual(len(values), 12)
        self.assertEqual([r['outcome'] for r in values if r['case'] == 'original'], ['cancelled', 'guest-trap'])
        self.assertEqual([r['tenant'] for r in values if r['case'] == 'saturated'], ['tenant-b', 'tenant-a'])

    def test_missing_duplicate_reordered_or_wrong_tenant_cannot_substitute_for_retirement(self):
        wrong = rows()
        wrong[2]['tenant'] = 'tenant-a'
        for values in [rows()[:-1], rows() + rows()[:1], list(reversed(rows())), wrong]:
            with self.subTest(values=values[-1]), self.assertRaisesRegex(ValueError, 'missing-or-extra|observation-contract'):
                reference.admission_observations(output(values), 48)

    def test_successful_admission_private_fields_or_foreign_cancel_success_are_rejected(self):
        for index, key, value in [(2, 'outcome', 'success'), (3, 'outcome', 'accepted'),
                                  (0, 'tenant', True), (0, 'private', 'not-exported'),
                                  (0, 'tenant', 'tenant-c'), (0, 'case', 'unknown')]:
            values = rows()
            values[index][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'private-or-unknown|observation-contract'):
                reference.admission_observations(output(values), 48)

    def test_wrapper_success_other_target_ignored_or_incomplete_libtest_is_not_qualification(self):
        raw = output(rows())
        for old, new in [(reference.ADMISSION_CASE.encode(), reference.CASE.encode()),
                         (b'0 ignored', b'1 ignored'), (b'48 filtered', b'47 filtered'),
                         (b'1 passed', b'2 passed'), (b'GO_ADMISSION_CASE', b'GO_SYNCHRONIZATION_CASE')]:
            with self.subTest(new=new), self.assertRaises(ValueError):
                reference.admission_observations(raw.replace(old, new), 48)
        with self.assertRaisesRegex(ValueError, 'output-bound'):
            reference.admission_observations(b'x' * (2 * 1024 * 1024 + 1), 48)

    def test_exact_campaigns_cannot_mix_checkpoint_negative_or_managed_source(self):
        fixture, negative = Path('positive'), Path('negative')
        plan = reference.campaign('admission', fixture, None)
        self.assertEqual(plan['case'], reference.ADMISSION_CASE)
        self.assertEqual(plan['fixture'], 'managed-idle')
        self.assertEqual(plan['inputs'], [(fixture, 'go-component-activation-v5')])
        self.assertEqual(reference.campaign('synchronization', fixture, negative)['inputs'],
                         [(fixture, 'go-component-activation-v5'), (negative, 'go-component-activation-v1')])
        for name, control in [('unknown', None), ('admission', negative), ('synchronization', None)]:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'unreviewed-campaign-or-negative'):
                reference.campaign(name, fixture, control)

    def test_source_identity_includes_actual_synthetic_callee_constructor_and_contract(self):
        snapshot = reference.source_snapshot(reference.ROOT)
        for name in ['crates/latent-wasmtime/tests/local_service/packages.rs',
                     'crates/latent-wasmtime/tests/local_service/component.rs']:
            self.assertEqual(snapshot[name], reference.digest((reference.ROOT / name).read_bytes()))

    def test_existing_managed_fixture_identity_and_native_modes_are_required(self):
        source = (reference.ROOT / 'sdk/go-guest/runtime/managed-idle-conformance/main.go').read_bytes()
        profile = 'go-component-activation-v5'
        record = {'profile': profile, 'fixture': 'managed-idle', 'sourceDigest': 'sha256:' + reference.digest(source),
                  'sourceUnchanged': True, 'ordinarySource': True, 'signedExecution': 'not-run',
                  'componentDigest': 'sha256:' + reference.digest(b'source-control-only'),
                  'bindingDigest': 'sha256:' + 'a' * 64, 'tools': [], 'transformations': [],
                  'nativeReference': {'modes': [0, 1, 2], 'output': 42, 'freshProcessPerMode': True,
                                      'sourceDigest': 'sha256:' + reference.digest(source)}}
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / 'src').mkdir()
            (folder / 'src/main.go').write_bytes(source)
            (folder / 'build').mkdir()
            (folder / 'build/component.wasm').write_bytes(b'source-control-only')
            receipt = folder / 'GO-ACTIVATION-COMPILE.json'
            receipt.write_bytes(json.dumps(record).encode())
            self.assertEqual(reference.compile_identity(folder, reference.ROOT, profile, 'managed-idle')['profile'], profile)
            for key, value in [('fixture', 'synchronization'), ('profile', 'go-component-activation-v4'),
                               ('sourceUnchanged', False), ('signedExecution', 'passed')]:
                changed = copy.deepcopy(record)
                changed[key] = value
                receipt.write_bytes(json.dumps(changed).encode())
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'compiler-source-or-profile'):
                    reference.compile_identity(folder, reference.ROOT, profile, 'managed-idle')
            changed = copy.deepcopy(record)
            changed['nativeReference']['modes'] = [0, 1]
            receipt.write_bytes(json.dumps(changed).encode())
            with self.assertRaisesRegex(ValueError, 'native-reference'):
                reference.compile_identity(folder, reference.ROOT, profile, 'managed-idle')


if __name__ == '__main__':
    unittest.main()
