"""Fail-closed controls for the bounded signed timer-overlap campaign."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools import qualify_go_activation as activation
from tools import qualify_go_synchronization as reference


def cases():
    return [dict(case=case, mode=mode, outcome='success', storesCreated=count,
                 liveStores=0, liveInstances=0, reservations=0,
                 reservedFuel=0, reservedMemory=0, pendingProviderWaits=0)
            for case, mode, count in [('reset-reset', 0, 1), ('reset-stop', 1, 2),
                                      ('gc-reset-reset', 2, 3), ('gc-reset-stop', 3, 4),
                                      ('fresh', 0, 5)]]


def stdout(rows=None, filtered=53):
    rows = cases() if rows is None else rows
    records = '\n'.join('GO_TIMER_OVERLAP_CASE ' + json.dumps(row) for row in rows)
    return (f'test {reference.TIMER_OVERLAP_CASE} ... ok\n{records}\n'
            f'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; {filtered} filtered out; finished in 1.00s\n').encode()


def stderr():
    return (b'LSF-GO-TIMER-OVERLAP-V1|go-timer-overlap-reset-reset|1|0|0|4|1|1|1|1|1|1|512\n'
            b'LSF-GO-TIMER-OVERLAP-V1|go-timer-overlap-reset-stop|1|0|0|4|1|1|1|1|1|1|512\n'
            b'LSF-GO-TIMER-OVERLAP-V1|go-timer-overlap-gc-reset-reset|1|0|0|4|1|1|1|1|1|1|512\n'
            b'LSF-GO-TIMER-OVERLAP-V1|go-timer-overlap-gc-reset-stop|1|0|0|4|1|1|1|1|1|1|512\n')


class GoTimerOverlap(unittest.TestCase):
    def test_exact_source_bound_signed_retirements_and_four_complete_witnesses(self):
        result = reference.timer_overlap_observations(stdout(), stderr(), 53)
        self.assertEqual(result['cases'], cases())
        self.assertEqual(result['witnesses'], [
            {'activation': 'go-timer-overlap-reset-reset', 'modeledWitnessBytes': 512},
            {'activation': 'go-timer-overlap-reset-stop', 'modeledWitnessBytes': 512},
            {'activation': 'go-timer-overlap-gc-reset-reset', 'modeledWitnessBytes': 512},
            {'activation': 'go-timer-overlap-gc-reset-stop', 'modeledWitnessBytes': 512},
        ])
        for rows in (cases()[:-1], list(reversed(cases())), cases() + cases()[:1]):
            with self.subTest(rows=rows), self.assertRaisesRegex(ValueError, 'signed-retirement'):
                reference.timer_overlap_observations(stdout(rows), stderr(), 53)

    def test_incomplete_wrong_order_and_ambiguous_witnesses_fail_closed(self):
        raw = stderr()
        changes = [raw.splitlines(keepends=True)[0], raw + raw.splitlines(keepends=True)[0],
                   b''.join(reversed(raw.splitlines(keepends=True))),
                   raw.replace(b'go-timer-overlap-gc-reset-stop|1|0|0|4',
                               b'go-timer-overlap-gc-reset-stop|0|0|0|4'),
                   raw.replace(b'|1|0|0|4|1|1|1|1|1|1|512', b'|0|0|0|4|1|1|1|1|1|1|512', 1),
                   raw.replace(b'|1|0|0|4|1|1|1|1|1|1|512', b'|1|0|1|4|1|1|1|1|1|1|512', 1),
                   raw.replace(b'|1|0|0|4|1|1|1|1|1|1|512', b'|1|0|0|5|1|1|1|1|1|1|512', 1),
                   raw.replace(b'|1|0|0|4|1|1|1|1|1|1|512', b'|1|0|0|4|1|0|1|1|1|1|512', 1),
                   raw.replace(b'|512\n', b'|0\n', 1), raw.replace(b'|512\n', b'|513\n', 1)]
        for changed in changes:
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, 'Go-timer-overlap-'):
                reference.timer_overlap_observations(stdout(), changed, 53)
        with self.assertRaisesRegex(ValueError, 'exact-signed-case'):
            reference.timer_overlap_observations(stdout().replace(b'1 passed', b'0 passed'), raw, 53)
        with self.assertRaisesRegex(ValueError, 'duplicate-field'):
            reference.timer_overlap_observations(stdout().replace(b'"mode": 0', b'"mode": 0, "mode": 0', 1), raw, 53)

    def test_only_exact_v5_fixture_source_world_and_native_reference_are_admitted(self):
        fixture = Path('fixture')
        self.assertEqual(reference.campaign('timer-overlap', fixture, None),
                         {'case': reference.TIMER_OVERLAP_CASE, 'fixture': 'timer-overlap',
                          'variable': 'LSF_GO_TIMER_OVERLAP_FIXTURE',
                          'inputs': [(fixture, 'go-component-activation-v5')]})
        with self.assertRaisesRegex(ValueError, 'unreviewed-campaign'):
            reference.campaign('timer-overlap', fixture, Path('other'))
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / 'fixture'
            with self.assertRaisesRegex(ValueError, 'timer-overlap-requires-v5'):
                activation.compile_fixture(folder, runtime_profile='go-component-activation-v1', fixture='timer-overlap')
            self.assertFalse(folder.exists())
            original = reference.ROOT / 'sdk/go-guest/runtime/timer-overlap-conformance'
            source, world = (original / 'main.go').read_bytes(), (original / 'world.wit').read_bytes()
            for child in ('src', 'wit', 'build'):
                (folder / child).mkdir(parents=True, exist_ok=True)
            (folder / 'src/main.go').write_bytes(source)
            (folder / 'wit/world.wit').write_bytes(world)
            component = b'host-control-only-not-an-executed-component'
            (folder / 'build/component.wasm').write_bytes(component)
            record = {'profile': 'go-component-activation-v5', 'fixture': 'timer-overlap',
                      'sourceDigest': 'sha256:' + reference.digest(source), 'sourceUnchanged': True,
                      'ordinarySource': True, 'signedExecution': 'not-run',
                      'componentDigest': 'sha256:' + reference.digest(component), 'bindingDigest': 'sha256:' + 'a' * 64,
                      'tools': [], 'transformations': [], 'nativeReference': {'modes': [0, 1, 2, 3], 'outputs': [42, 42, 42, 42],
                      'freshProcessPerMode': True, 'sourceDigest': 'sha256:' + reference.digest(source)}}
            receipt = folder / 'GO-ACTIVATION-COMPILE.json'
            receipt.write_text(json.dumps(record))
            self.assertEqual(reference.compile_identity(folder, reference.ROOT, record['profile'], record['fixture'])['sourceDigest'], record['sourceDigest'])
            changed = copy.deepcopy(record)
            changed['nativeReference']['outputs'] = [42, 43, 42, 43]
            receipt.write_text(json.dumps(changed))
            reference.compile_identity(folder, reference.ROOT, record['profile'], record['fixture'])
            changed['nativeReference']['outputs'] = [43, 42, 42, 42]
            receipt.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, 'native-reference'):
                reference.compile_identity(folder, reference.ROOT, record['profile'], record['fixture'])
            changed['nativeReference']['outputs'] = [42, 42, 43, 42]
            receipt.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, 'native-reference'):
                reference.compile_identity(folder, reference.ROOT, record['profile'], record['fixture'])
            for field, value in [('sourceUnchanged', False), ('signedExecution', 'passed')]:
                changed = copy.deepcopy(record)
                changed[field] = value
                receipt.write_text(json.dumps(changed))
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'compiler-source-or-profile'):
                    reference.compile_identity(folder, reference.ROOT, record['profile'], record['fixture'])
            receipt.write_text(json.dumps(record))
            (folder / 'wit/world.wit').write_bytes(b'wrong-world')
            with self.assertRaisesRegex(ValueError, 'timer-overlap-compiler-world'):
                reference.compile_identity(folder, reference.ROOT, record['profile'], record['fixture'])


if __name__ == '__main__':
    unittest.main()
