"""Source and fail-closed execution controls; actual guest behavior runs on Linux."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools import qualify_go_activation as activation
from tools import qualify_go_synchronization as reference


def results():
    rows = [{'case': 'ordinary', 'iteration': iteration, 'mode': mode, 'outcome': 'success'}
            for iteration in range(3) for mode in reference.ORDINARY_MODES]
    return rows + [{'case': case, 'iteration': 0, 'mode': mode, 'outcome': outcome}
                   for case, mode, outcome in reference.EXTRA]


def output(rows, *, filtered=47):
    records = '\n'.join('GO_SYNCHRONIZATION_CASE ' + json.dumps(row) for row in rows)
    return (f'test {reference.CASE} ... ok\n{records}\n'
            f'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; {filtered} filtered out; finished in 1.00s\n').encode()


class GoSynchronization(unittest.TestCase):
    def test_exact_named_signed_target_requires_all_33_original_owner_barriers(self):
        rows = results()
        self.assertEqual(len(rows), 33)
        self.assertEqual(reference.observations(output(rows), 47), rows)
        self.assertEqual({row['mode'] for row in rows if row['case'] == 'ordinary'}, {0, 1, 2, 3, 4, 5, 6, 9})

    def test_missing_duplicated_reordered_or_wrong_outcome_is_not_signed_qualification(self):
        rows = results()
        wrong = copy.deepcopy(rows)
        wrong[-2]['outcome'] = 'success'
        for changed in (rows[:-1], rows + rows[:1], list(reversed(rows)), wrong):
            with self.subTest(changed=changed[-1]), self.assertRaisesRegex(ValueError, 'missing-or-extra|invocation-contract'):
                reference.observations(output(changed), 47)

    def test_unknown_private_fields_bool_and_unbounded_indices_are_rejected(self):
        for field, value in [('private', 'not-exported'), ('mode', True), ('iteration', False),
                             ('iteration', 2**64), ('outcome', 'invented'), ('case', 'unknown')]:
            rows = results()
            rows[0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'private-or-unknown|invocation-contract'):
                reference.observations(output(rows), 47)

    def test_partial_libtest_ignored_or_other_executable_cannot_substitute_for_the_target(self):
        raw = output(results())
        for old, new in ((b'0 ignored', b'1 ignored'), (b'47 filtered', b'46 filtered'),
                         (reference.CASE.encode(), b'other::signed_case'), (b'1 passed', b'2 passed')):
            with self.subTest(new=new), self.assertRaisesRegex(ValueError, 'exact-signed-case-required'):
                reference.observations(raw.replace(old, new), 47)
        with self.assertRaisesRegex(ValueError, 'output-bound'):
            reference.observations(b'x' * (2 * 1024 * 1024 + 1), 47)

    def test_only_current_v5_or_the_exact_v1_negative_is_admitted_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_path = Path(temporary) / 'not-created'
            for profile in ['go-component-activation-v2', 'go-component-activation-v3', 'go-component-activation-v4']:
                with self.subTest(profile=profile), self.assertRaisesRegex(ValueError, 'requires-v5-or-exact-no-checkpoint'):
                    activation.compile_fixture(output_path, runtime_profile=profile, fixture='synchronization')
                self.assertFalse(output_path.exists())

    def test_compiler_binding_requires_original_source_native_modes_and_component_bytes(self):
        source = (reference.ROOT / 'sdk/go-guest/runtime/synchronization-conformance/main.go').read_bytes()
        profile = 'go-component-activation-v5'
        record = {'profile': profile, 'fixture': 'synchronization', 'sourceDigest': 'sha256:' + reference.digest(source),
                  'sourceUnchanged': True, 'ordinarySource': True, 'signedExecution': 'not-run',
                  'componentDigest': 'sha256:' + reference.digest(b'only a source-control fixture'),
                  'bindingDigest': 'sha256:' + 'a' * 64, 'tools': [], 'transformations': [],
                  'nativeReference': {'modes': reference.NATIVE_MODES, 'output': 42, 'freshProcessPerMode': True,
                                      'sourceDigest': 'sha256:' + reference.digest(source)}}
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            (fixture / 'src').mkdir()
            (fixture / 'src/main.go').write_bytes(source)
            (fixture / 'build').mkdir()
            (fixture / 'build/component.wasm').write_bytes(b'only a source-control fixture')
            receipt = fixture / 'GO-ACTIVATION-COMPILE.json'
            receipt.write_bytes(json.dumps(record).encode())
            result = reference.compile_identity(fixture, reference.ROOT, profile)
            self.assertEqual(result['profile'], profile)
            self.assertNotIn('component', result)
            for key, value in [('profile', 'go-component-activation-v4'), ('sourceUnchanged', False),
                               ('sourceDigest', 'sha256:' + 'b' * 64), ('signedExecution', 'passed')]:
                changed = copy.deepcopy(record)
                changed[key] = value
                receipt.write_bytes(json.dumps(changed).encode())
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'compiler-source-or-profile'):
                    reference.compile_identity(fixture, reference.ROOT, profile)
            changed = copy.deepcopy(record)
            changed['nativeReference']['modes'] = [0, 1]
            receipt.write_bytes(json.dumps(changed).encode())
            with self.assertRaisesRegex(ValueError, 'native-reference'):
                reference.compile_identity(fixture, reference.ROOT, profile)
            receipt.write_bytes(json.dumps(record).encode())
            (fixture / 'build/component.wasm').write_bytes(b'changed component')
            with self.assertRaisesRegex(ValueError, 'component-identity'):
                reference.compile_identity(fixture, reference.ROOT, profile)


if __name__ == '__main__':
    unittest.main()
