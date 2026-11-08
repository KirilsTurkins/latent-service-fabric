"""Fail-closed controls for the bounded signed timer-overlap campaign."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import qualify_go_activation as activation
from tools import qualify_go_synchronization as reference
from tools import ci_lane_inventory as lanes


def cases():
    return [dict(case=case, mode=mode, outcome=outcome, storesCreated=count,
                 liveStores=0, liveInstances=0, reservations=0,
                 reservedFuel=0, reservedMemory=0, pendingProviderWaits=0)
            for case, mode, outcome, count in [('reset-reset', 0, 'success', 1),
                ('reset-stop', 1, 'success', 2), ('gc-reset-reset', 2, 'success', 3),
                ('gc-reset-stop', 3, 'success', 4), ('cancel-reset-reset', 0, 'cancelled', 5),
                ('deadline-reset-stop', 1, 'deadline-exceeded', 6), ('fresh', 0, 'success', 7)]]


def stdout(rows=None, filtered=53):
    rows = cases() if rows is None else rows
    records = '\n'.join('GO_TIMER_OVERLAP_CASE ' + json.dumps(row) for row in rows)
    return (f'test {reference.TIMER_OVERLAP_CASE} ... ok\n{records}\n'
            f'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; {filtered} filtered out; finished in 1.00s\n').encode()


def stderr():
    names = ('reset-reset', 'reset-stop', 'gc-reset-reset', 'gc-reset-stop',
             'cancel-reset-reset', 'deadline-reset-stop')
    lines = []
    for index, name in enumerate(names):
        gc, stop = int(index in (2, 3)), int(index in (4, 5))
        lines.append(f'LSF-GO-TIMER-OVERLAP-V4|go-timer-overlap-{name}|1|0|0|4|1|1|1|1|{gc}|{gc}|1|{stop}|{1-stop}|512')
        lines.append(f'LSF-GO-TIMER-WAIT-DROP-V1|go-timer-overlap-{name}|{1-stop}')
    return ('\n'.join(lines) + '\n').encode()


class GoTimerOverlap(unittest.TestCase):
    def test_v7_overlap_campaign_requires_its_own_signed_case_and_complete_witness(self):
        fixture = Path('owned-v7-overlap')
        self.assertEqual(reference.campaign('timer-overlap-v7', fixture, None),
            {'case': reference.V7_TIMER_OVERLAP_CASE, 'fixture': 'timer-overlap',
             'variable': 'LSF_GO_V7_TIMER_OVERLAP_FIXTURE', 'inputs': [(fixture, 'go-component-activation-v7')]})
        raw = stdout().replace(reference.TIMER_OVERLAP_CASE.encode(), reference.V7_TIMER_OVERLAP_CASE.encode())
        self.assertEqual(reference.timer_overlap_observations(raw, stderr(), 53, reference.V7_TIMER_OVERLAP_CASE)['cases'], cases())
        for wrong, case in ((stdout(), reference.V7_TIMER_OVERLAP_CASE), (raw, reference.TIMER_OVERLAP_CASE)):
            with self.assertRaisesRegex(ValueError, 'exact-signed-case'):
                reference.timer_overlap_observations(wrong, stderr(), 53, case)
        with self.assertRaisesRegex(ValueError, 'causal-witness'):
            reference.timer_overlap_observations(raw, stderr().replace(b'|1|0|0|4', b'|0|0|0|4', 1), 53,
                                                 reference.V7_TIMER_OVERLAP_CASE)
        with self.assertRaisesRegex(ValueError, 'unreviewed-campaign'):
            reference.campaign('timer-overlap-v7', fixture, Path('v5-receipt'))

    def test_v7_overlap_requires_its_own_profile_source_and_native_reference(self):
        class SourceOnlyCompiler:
            def __init__(self, *_args, **_kwargs): self.materials = []
            def compile(self, _source, _wit, _world, output, **_kwargs):
                (output / 'runtime-overlay').mkdir(parents=True)
                (output / 'runtime-overlay/overlay.json').write_bytes(b'{"Replace":{}}')
                component = output / 'component.wasm'
                component.write_bytes(b'unit-test-only')
                return component, {}
        original = reference.ROOT / 'sdk/go-guest/runtime/timer-overlap-conformance'
        source, world = (original / 'main.go').read_bytes(), (original / 'world.wit').read_bytes()
        native = {'modes': [0, 1, 2, 3], 'outputs': [42, 43, 42, 43], 'freshProcessPerMode': True,
                  'sourceDigest': 'sha256:' + reference.digest(source)}
        with tempfile.TemporaryDirectory() as temporary, patch.object(activation, 'ROOT', reference.ROOT), \
                patch.object(activation, 'Compiler', SourceOnlyCompiler), patch.object(activation, 'stage'), \
                patch.object(activation, 'fixture_reference', return_value=native) as observe:
            folder = Path(temporary) / 'capture'
            record = activation.compile_fixture(folder, runtime_profile='go-component-activation-v7', fixture='timer-overlap')
            self.assertEqual(record['profile'], 'go-component-activation-v7')
            self.assertEqual(record['nativeReference'], native)
            self.assertEqual(record['signedExecution'], 'not-run')
            observe.assert_called_once()
            (folder / 'wit').mkdir(exist_ok=True)
            (folder / 'wit/world.wit').write_bytes(world)
            self.assertEqual(reference.compile_identity(folder, reference.ROOT, record['profile'], 'timer-overlap')['profile'], record['profile'])
            with self.assertRaisesRegex(ValueError, 'source-or-profile'):
                reference.compile_identity(folder, reference.ROOT, 'go-component-activation-v5', 'timer-overlap')
            (folder / 'wit/world.wit').write_bytes(world + b'\n')
            with self.assertRaisesRegex(ValueError, 'compiler-world'):
                reference.compile_identity(folder, reference.ROOT, record['profile'], 'timer-overlap')

    def test_v7_overlap_is_an_additional_exact_ignored_inventory_case(self):
        suite, = [s for s in json.loads((reference.ROOT / 'tools/ci/suites.json').read_bytes())['suites']
                  if s['id'] == 'latent-wasmtime.test.local-service']
        self.assertEqual(suite['expectedIgnored'].count(reference.TIMER_OVERLAP_CASE), 1)
        self.assertEqual(suite['expectedIgnored'].count(reference.V7_TIMER_OVERLAP_CASE), 1)
        self.assertEqual(suite['ignoredLeaves'].count(reference.V7_TIMER_OVERLAP_CASE.rsplit('::', 1)[-1]), 1)

    def test_workflow_binds_each_overlap_profile_to_its_own_fixture_and_receipts(self):
        path = reference.ROOT / '.github/workflows/go-synchronization-reference.yml'
        model = lanes.structural_workflow(lanes.workflow_model(path.read_text(encoding='utf8')))
        choices = model['on']['workflow_dispatch']['inputs']['campaign']['options']
        self.assertTrue({'synchronization', 'admission', 'queued', 'managed-timers', 'task-saturation',
                         'timer-overlap', 'timer-overlap-v7'} <= set(choices))
        branch = 'feat/go-v7-timer-overlap-20261108'
        self.assertIn(branch, model['on']['push']['branches'])
        self.assertIn("github.ref_name == '" + branch + "' && 'timer-overlap-v7'", model['env']['LSF_GO_REFERENCE_CAMPAIGN'])
        job = model['jobs']['synchronization']
        steps = {step['name']: step for step in job['steps'] if 'name' in step}
        for version in ('v5', 'v7'):
            campaign = 'timer-overlap' if version == 'v5' else 'timer-overlap-v7'
            condition = "env.LSF_GO_REFERENCE_CAMPAIGN == '" + campaign + "'"
            compile_step = steps['Compile unchanged Go timer overlap fixture under ' + version]
            signed_step = steps['Require original ' + version + ' timer overlap and retirement witnesses']
            fixture = '$RUNNER_TEMP/go-timer-overlap-' + version
            self.assertEqual(compile_step['if'], condition)
            self.assertEqual(signed_step['if'], condition)
            self.assertIn('--runtime-profile go-component-activation-' + version + ' --fixture timer-overlap', compile_step['run'])
            self.assertIn('--output "' + fixture + '"', compile_step['run'])
            self.assertIn('--campaign ' + campaign + ' --source-commit "${{ github.sha }}"', signed_step['run'])
            self.assertIn('--fixture "' + fixture + '"', signed_step['run'])
            retained = steps['Retain bounded actual results and compiler source identities']['with']['path']
            for suffix in ('/src/', '/wit/', '/build/component.wasm', '/GO-ACTIVATION-COMPILE.json', '-result/'):
                self.assertIn('go-timer-overlap-' + version + suffix, retained)
        contract = reference.ROOT / 'tools/ci/contracts/workflows/go-synchronization-reference.yml'
        policy = json.loads((contract / 'workflow.json').read_bytes())
        definition = json.loads((contract / 'jobs/synchronization.json').read_bytes())
        self.assertEqual(policy['policy'], {key: value for key, value in model.items() if key != 'jobs'})
        self.assertEqual(definition['definition'], job)

    def test_exact_source_bound_signed_retirements_and_six_complete_witnesses(self):
        result = reference.timer_overlap_observations(stdout(), stderr(), 53)
        self.assertEqual(result['cases'], cases())
        self.assertEqual(len(result['witnesses']), 6)
        self.assertEqual([w['bothParkedBeforeRootStop'] for w in result['witnesses']],
                         [False, False, False, False, True, True])
        self.assertEqual([w['handshakeParkObserved'] for w in result['witnesses']],
                         [False, False, True, True, False, False])
        self.assertEqual([w['returned'] for w in result['physicalWaitDrops']],
                         [True, True, True, True, False, False])
        for rows in (cases()[:-1], list(reversed(cases())), cases() + cases()[:1]):
            with self.subTest(rows=rows), self.assertRaisesRegex(ValueError, 'signed-retirement'):
                reference.timer_overlap_observations(stdout(rows), stderr(), 53)

    def test_incomplete_wrong_order_and_ambiguous_witnesses_fail_closed(self):
        raw = stderr()
        plain = b'|1|0|0|4|1|1|1|1|0|0|1|0|1|512'
        changes = [raw.splitlines(keepends=True)[0], raw + raw.splitlines(keepends=True)[0],
                   b''.join(reversed(raw.splitlines(keepends=True))),
                   raw.replace(b'go-timer-overlap-gc-reset-stop|1|0|0|4',
                               b'go-timer-overlap-gc-reset-stop|0|0|0|4'),
                   raw.replace(b'go-timer-overlap-gc-reset-stop|1|0|0|4|1|1|1|1|1|1|1|0|1|512',
                               b'go-timer-overlap-gc-reset-stop|1|0|0|4|1|1|1|1|0|1|1|0|1|512'),
                   raw.replace(b'go-timer-overlap-cancel-reset-reset|1|0|0|4|1|1|1|1|0|0|1|1|0|512',
                               b'go-timer-overlap-cancel-reset-reset|1|0|0|4|1|1|1|1|0|0|1|0|0|512'),
                   raw.replace(b'LSF-GO-TIMER-WAIT-DROP-V1|go-timer-overlap-cancel-reset-reset|0\n', b''),
                   raw.replace(b'LSF-GO-TIMER-WAIT-DROP-V1|go-timer-overlap-reset-reset|1',
                               b'LSF-GO-TIMER-WAIT-DROP-V1|go-timer-overlap-reset-reset|0'),
                   raw.replace(plain, b'|0|0|0|4|1|1|1|1|0|0|1|0|1|512', 1),
                   raw.replace(plain, b'|1|0|1|4|1|1|1|1|0|0|1|0|1|512', 1),
                   raw.replace(plain, b'|1|0|0|5|1|1|1|1|0|0|1|0|1|512', 1),
                   raw.replace(plain, b'|1|0|0|4|1|0|1|1|0|0|1|0|1|512', 1),
                   raw.replace(b'OVERLAP-V4', b'OVERLAP-V3'),
                   raw.replace(b'|512\n', b'|0\n', 1), raw.replace(b'|512\n', b'|513\n', 1)]
        for changed in changes:
            self.assertNotEqual(changed, raw)
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, 'Go-timer-overlap-'):
                reference.timer_overlap_observations(stdout(), changed, 53)
        with self.assertRaisesRegex(ValueError, 'exact-signed-case'):
            reference.timer_overlap_observations(stdout().replace(b'1 passed', b'0 passed'), raw, 53)
        with self.assertRaisesRegex(ValueError, 'duplicate-field'):
            reference.timer_overlap_observations(stdout().replace(b'"mode": 0', b'"mode": 0, "mode": 0', 1), raw, 53)

    def test_v5_fixture_source_world_and_native_reference_are_admitted(self):
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
