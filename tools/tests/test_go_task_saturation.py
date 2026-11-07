"""Fail-closed controls for the finite Task16 signed reference."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools import qualify_go_activation as activation
from tools import qualify_go_synchronization as reference


def cases():
    return [dict(case=case, outcome=outcome, storesCreated=count, liveStores=0, liveInstances=0,
                 reservations=0, reservedFuel=0, reservedMemory=0)
            for case, outcome, count in [('seven-live', 'success', 1),
                ('eighth-refused', 'guest-trap', 2), ('fresh-after-refusal', 'success', 3)]]


def refusal():
    return dict(tenant='tenant-a', activation='go-task16-saturation', stage='execution',
                reason='runtime-task-limit', configuredBound=16, requestedOwners=17,
                terminalCauseEstablished=False)


def output(rows=None, observation=None, filtered=52):
    rows = cases() if rows is None else rows
    observation = refusal() if observation is None else observation
    records = ['GO_TASK_SATURATION_CASE ' + json.dumps(rows[0]),
               'GO_TASK_SATURATION_REFUSAL ' + json.dumps(observation)]
    records.extend('GO_TASK_SATURATION_CASE ' + json.dumps(row) for row in rows[1:])
    return (f'test {reference.TASK_SATURATION_CASE} ... ok\n' + '\n'.join(records) + '\n'
            f'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; {filtered} filtered out; finished in 1.00s\n').encode()


class GoTaskSaturation(unittest.TestCase):
    def test_exact_three_signed_results_and_original_refusal_are_required(self):
        result = reference.task_saturation_observations(output(), 52)
        self.assertEqual(result, {'cases': cases(), 'refusal': refusal()})
        for changed in (cases()[:-1], cases() + cases()[:1], list(reversed(cases()))):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, 'original-refusal-or-retirement'):
                reference.task_saturation_observations(output(changed), 52)

    def test_wrong_activation_or_unobserved_original_capacity_cannot_qualify(self):
        for key, value in [('tenant', 'tenant-b'), ('activation', 'other'), ('reason', 'runtime-queue-limit'),
                           ('configuredBound', 10), ('configuredBound', True), ('requestedOwners', 16),
                           ('terminalCauseEstablished', True), ('private', 'not-exported')]:
            changed = refusal() | {key: value}
            with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, 'original-refusal-or-retirement'):
                reference.task_saturation_observations(output(observation=changed), 52)

    def test_missing_duplicate_reordered_or_nonterminal_results_cannot_qualify(self):
        raw = output()
        lines = raw.splitlines()
        for changed in (b'\n'.join(lines[:2] + lines[3:]) + b'\n',
                        b'\n'.join(lines[:3] + [lines[2]] + lines[3:]) + b'\n',
                        b'\n'.join([lines[0], lines[2], lines[1], *lines[3:]]) + b'\n',
                        raw.replace(b'"liveStores": 0', b'"liveStores": 1', 1)):
            with self.subTest(changed=changed[:120]), self.assertRaisesRegex(ValueError, 'original-refusal-or-retirement'):
                reference.task_saturation_observations(changed, 52)
        for old, new in ((b'1 passed', b'0 passed'), (b'0 ignored', b'1 ignored'),
                         (reference.TASK_SATURATION_CASE.encode(), b'other::case')):
            with self.subTest(old=old), self.assertRaisesRegex(ValueError, 'exact-signed-case'):
                reference.task_saturation_observations(raw.replace(old, new), 52)
        with self.assertRaisesRegex(ValueError, 'duplicate-field'):
            reference.task_saturation_observations(raw.replace(
                b'"configuredBound": 16', b'"configuredBound": 16, "configuredBound": 16'), 52)

    def test_campaign_selects_only_the_exact_v5_fixture_without_a_negative(self):
        path = Path('component')
        plan = reference.campaign('task-saturation', path, None)
        self.assertEqual(plan, {'case': reference.TASK_SATURATION_CASE, 'fixture': 'task-saturation',
                                'variable': 'LSF_GO_TASK_SATURATION_FIXTURE',
                                'inputs': [(path, 'go-component-activation-v5')]})
        with self.assertRaisesRegex(ValueError, 'unreviewed-campaign-or-negative'):
            reference.campaign('task-saturation', path, Path('extra'))

    def test_only_v5_and_the_exact_source_world_component_and_native_control_are_admitted(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'fixture'
            with self.assertRaisesRegex(ValueError, 'task-saturation-requires-v5'):
                activation.compile_fixture(path, runtime_profile='go-component-activation-v1', fixture='task-saturation')
            self.assertFalse(path.exists())
            source = (reference.ROOT / 'sdk/go-guest/runtime/task-saturation-conformance/main.go').read_bytes()
            world = (reference.ROOT / 'sdk/go-guest/runtime/task-saturation-conformance/world.wit').read_bytes()
            (path / 'src').mkdir(parents=True)
            (path / 'wit').mkdir()
            (path / 'build').mkdir()
            (path / 'src/main.go').write_bytes(source)
            (path / 'wit/world.wit').write_bytes(world)
            component = b'host-control-only-not-an-executed-component'
            (path / 'build/component.wasm').write_bytes(component)
            record = {'profile': 'go-component-activation-v5', 'fixture': 'task-saturation',
                      'sourceDigest': 'sha256:' + reference.digest(source), 'sourceUnchanged': True,
                      'ordinarySource': True, 'signedExecution': 'not-run',
                      'componentDigest': 'sha256:' + reference.digest(component), 'bindingDigest': 'sha256:' + 'a' * 64,
                      'tools': [], 'transformations': [], 'nativeReference': {'modes': [0], 'output': 42,
                      'freshProcessPerMode': True, 'sourceDigest': 'sha256:' + reference.digest(source)}}
            receipt = path / 'GO-ACTIVATION-COMPILE.json'
            receipt.write_text(json.dumps(record))
            result = reference.compile_identity(path, reference.ROOT, record['profile'], record['fixture'])
            self.assertEqual(result['sourceDigest'], record['sourceDigest'])
            for field, value in [('sourceUnchanged', False), ('signedExecution', 'passed')]:
                changed = copy.deepcopy(record)
                changed[field] = value
                receipt.write_text(json.dumps(changed))
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'compiler-source-or-profile'):
                    reference.compile_identity(path, reference.ROOT, record['profile'], record['fixture'])
            receipt.write_text(json.dumps(record))
            (path / 'wit/world.wit').write_bytes(b'wrong-world')
            with self.assertRaisesRegex(ValueError, 'compiler-world'):
                reference.compile_identity(path, reference.ROOT, record['profile'], record['fixture'])


if __name__ == '__main__':
    unittest.main()
