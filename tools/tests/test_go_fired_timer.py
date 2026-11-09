"""Fail-closed controls for the fired Go one-shot diagnostic campaign."""
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import qualify_go_synchronization as owner
from tools.go_guest import fired_timer_witness as probe

ROOT = Path(__file__).resolve().parents[2]


def output():
    rows = [dict(case=case, mode=mode, outcome='success', storesCreated=count, liveStores=0,
                 liveInstances=0, reservations=0, reservedFuel=0, reservedMemory=0, pendingProviderWaits=0)
            for case, mode, count in [('stop', 0, 1), ('reset', 1, 2), ('fresh', 0, 3)]]
    lines = [f'test {owner.FIRED_TIMER_CASE} ... ok']
    lines.extend('GO_TIMER_FIRED_CASE ' + json.dumps(row) for row in rows)
    lines.append('test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 53 filtered out;')
    return ('\n'.join(lines) + '\n').encode()


def diagnostic():
    ids = ['go-timer-fired-stop', 'go-timer-fired-reset']
    lines = []
    for name in ids:
        lines.append(f'LSF-GO-TIMER-WAIT-DROP-V1|{name}|1')
        lines.append(f'LSF-GO-TIMER-FIRED-V1|{name}|1|0|0|1024')
    return ('\n'.join(lines) + '\n').encode()


class FiredTimerControls(unittest.TestCase):
    def test_exact_fence_derivation_and_source_drift(self):
        source = (ROOT / 'sdk/go-guest/runtime/timer_async.go.in').read_bytes()
        derived = probe.derive(source)
        self.assertEqual(derived.count(b'lsfFiredFenceWitness()'), 2)
        self.assertIn(probe.INSTRUMENTED, derived)
        self.assertIn(probe.INSTRUMENTED_STOPPED, derived)
        self.assertIn(b'wait.token == lsfFiredFirstStopped', derived)
        for changed in (source.replace(probe.MATCH, b'changed'), source.replace(probe.SIGNATURE, b'changed'),
                        source.replace(probe.STOPPED, b'changed'), source + probe.MATCH, source + probe.STOPPED,
                        source + b'lsfFiredFenceWitness', source + b'lsfFiredFirstStopped'):
            with self.subTest(changed=changed[-40:]), self.assertRaisesRegex(ValueError, 'source-drift'):
                probe.derive(changed)

    def test_exact_campaign_selects_only_v7_and_no_negative(self):
        path = Path('fired-fixture')
        self.assertEqual(owner.campaign('timer-fired-v7', path, None),
            {'case': owner.FIRED_TIMER_CASE, 'fixture': 'timer-fired', 'variable': 'LSF_GO_V7_TIMER_FIRED_FIXTURE',
             'inputs': [(path, 'go-component-activation-v7')]})
        with self.assertRaisesRegex(ValueError, 'unreviewed-campaign'):
            owner.campaign('timer-fired-v7', path, Path('unexpected'))

    def test_strict_signed_case_and_physical_drop_evidence(self):
        parsed = owner.fired_timer_observations(output(), diagnostic(), 53)
        self.assertEqual([row['case'] for row in parsed['cases']], ['stop', 'reset', 'fresh'])
        self.assertEqual(len(parsed['physicalWaitDrops']), 2)
        for out, diag in (
            (output().replace(owner.FIRED_TIMER_CASE.encode(), b'other'), diagnostic()),
            (output().replace(b'"liveStores": 0', b'"liveStores": 1', 1), diagnostic()),
            (output() + output(), diagnostic()),
            (output(), diagnostic().replace(b'|1|0|0|1024', b'|1|1|0|1024', 1)),
            (output(), diagnostic().replace(b'|1|0|0|1024', b'|1|0|1|1024', 1)),
            (output(), diagnostic().replace(b'WAIT-DROP-V1|go-timer-fired-stop|1', b'WAIT-DROP-V1|go-timer-fired-stop|0')),
            (output(), diagnostic() + diagnostic()),
        ):
            with self.subTest(out=out[:100], diag=diag[:100]), self.assertRaises(ValueError):
                owner.fired_timer_observations(out, diag, 53)


    def test_compiler_selects_the_diagnostic_sdk_without_editing_the_original(self):
        from tools import qualify_go_activation as activation
        seen = {}
        class SourceOnlyCompiler:
            def __init__(self, _root, sdk, *_args, **_kwargs):
                self.materials = []
                seen['sdk'] = sdk
            def compile(self, _source, _wit, _world, output, **_kwargs):
                (output / 'runtime-overlay').mkdir(parents=True)
                (output / 'runtime-overlay/overlay.json').write_bytes(b'{"Replace":{}}')
                component = output / 'component.wasm'
                component.write_bytes(b'unit-test-only')
                return component, {}
        source = (ROOT / 'sdk/go-guest/runtime/timer-fired-conformance/main.go').read_bytes()
        original_path = ROOT / 'sdk/go-guest/runtime/timer_async.go.in'
        original = original_path.read_bytes()
        native = {'modes': [0, 1], 'output': 42, 'freshProcessPerMode': True,
                  'sourceDigest': 'sha256:' + owner.digest(source)}
        with tempfile.TemporaryDirectory() as temporary, patch.object(activation, 'ROOT', ROOT), \
                patch.object(activation, 'Compiler', SourceOnlyCompiler), patch.object(activation, 'stage'), \
                patch.object(activation, 'fixture_reference', return_value=native):
            output = Path(temporary) / 'capture'
            record = activation.compile_fixture(output, runtime_profile='go-component-activation-v7', fixture='timer-fired')
            self.assertEqual(seen['sdk'], output / 'diagnostic-sdk')
            self.assertEqual((seen['sdk'] / 'runtime/timer_async.go.in').read_bytes(), probe.derive(original))
            self.assertEqual(original_path.read_bytes(), original)
            self.assertEqual(record['diagnosticRuntime']['originalTimerAsyncDigest'], 'sha256:' + owner.digest(original))
            (output / 'wit').mkdir(exist_ok=True)
            (output / 'wit/world.wit').write_bytes((ROOT / 'sdk/go-guest/runtime/timer-fired-conformance/world.wit').read_bytes())
            owner.compile_identity(output, ROOT, 'go-component-activation-v7', 'timer-fired')
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, 'requires-v7'):
                activation.compile_fixture(Path(temporary) / 'wrong', runtime_profile='go-component-activation-v5', fixture='timer-fired')

    def test_compiler_identity_requires_exact_original_and_derived_sources(self):
        source = (ROOT / 'sdk/go-guest/runtime/timer-fired-conformance/main.go').read_bytes()
        world = (ROOT / 'sdk/go-guest/runtime/timer-fired-conformance/world.wit').read_bytes()
        original = (ROOT / 'sdk/go-guest/runtime/timer_async.go.in').read_bytes()
        derived = probe.derive(original)
        with tempfile.TemporaryDirectory() as name:
            fixture = Path(name)
            for folder in ('src', 'wit', 'build', 'diagnostic-sdk/runtime'):
                (fixture / folder).mkdir(parents=True)
            (fixture / 'src/main.go').write_bytes(source)
            (fixture / 'wit/world.wit').write_bytes(world)
            (fixture / 'build/component.wasm').write_bytes(b'example-component')
            timer = fixture / 'diagnostic-sdk/runtime/timer_async.go.in'
            timer.write_bytes(derived)
            record = {'profile': 'go-component-activation-v7', 'fixture': 'timer-fired',
                'sourceDigest': 'sha256:' + owner.digest(source), 'sourceUnchanged': True,
                'ordinarySource': True, 'signedExecution': 'not-run',
                'componentDigest': 'sha256:' + owner.digest(b'example-component'),
                'bindingDigest': 'example', 'tools': {}, 'transformations': [],
                'diagnosticRuntime': {'kind': 'selected-stop-token-fence-observe-v2',
                    'originalTimerAsyncDigest': 'sha256:' + owner.digest(original),
                    'derivedTimerAsyncDigest': 'sha256:' + owner.digest(derived)},
                'nativeReference': {'modes': [0, 1], 'output': 42, 'freshProcessPerMode': True,
                                    'sourceDigest': 'sha256:' + owner.digest(source)}}
            receipt = fixture / 'GO-ACTIVATION-COMPILE.json'
            receipt.write_text(json.dumps(record), encoding='utf-8')
            owner.compile_identity(fixture, ROOT, 'go-component-activation-v7', 'timer-fired')
            timer.write_bytes(derived + b'// tampered')
            with self.assertRaisesRegex(ValueError, 'diagnostic-runtime-drift'):
                owner.compile_identity(fixture, ROOT, 'go-component-activation-v7', 'timer-fired')
            timer.write_bytes(derived)
            record['diagnosticRuntime']['originalTimerAsyncDigest'] = 'sha256:' + '0' * 64
            receipt.write_text(json.dumps(record), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'diagnostic-runtime-drift'):
                owner.compile_identity(fixture, ROOT, 'go-component-activation-v7', 'timer-fired')

    def test_branch_owner_and_inventory_bind_the_new_campaign(self):
        from tools import ci_lane_inventory as lanes
        workflow = lanes.workflow_model((ROOT / '.github/workflows/go-synchronization-reference.yml').read_text())
        branch = 'feat/go-fired-timer-fence-v7-20261108'
        self.assertIn(branch, workflow['on']['push']['branches'])
        self.assertNotIn('release', workflow['on']['push']['branches'])
        self.assertIn("github.ref_name == '" + branch + "' && 'timer-fired-v7'", workflow['env']['LSF_GO_REFERENCE_CAMPAIGN'])
        self.assertIn('timer-fired-v7', workflow['on']['workflow_dispatch']['inputs']['campaign']['options'])
        steps = workflow['jobs']['synchronization']['steps']
        negative, = [s for s in steps if s.get('name') == 'Reject foreign fired-timer fence probes using pinned Go']
        self.assertEqual(negative['if'], "env.LSF_GO_REFERENCE_CAMPAIGN == 'timer-fired-v7'")
        self.assertEqual(negative['run'], 'python3 tools/tests/go_fired_fence_controls.py')
        build, = [s for s in steps if s.get('name') == 'Compile the selected v7 fired timer diagnostic']
        signed, = [s for s in steps if s.get('name') == 'Require original fired timer wait retirement on the signed node']
        self.assertEqual(build['if'], "env.LSF_GO_REFERENCE_CAMPAIGN == 'timer-fired-v7'")
        self.assertEqual(signed['if'], build['if'])
        self.assertIn('--runtime-profile go-component-activation-v7 --fixture timer-fired', build['run'])
        self.assertIn('--campaign timer-fired-v7 --source-commit "${{ github.sha }}"', signed['run'])
        retained = next(s for s in steps if s.get('name') == 'Retain bounded actual results and compiler source identities')['with']['path']
        for suffix in ('src/', 'wit/', 'diagnostic-sdk/runtime/timer_async.go.in', 'build/component.wasm', 'logs/'):
            self.assertIn('go-timer-fired-v7/' + suffix, retained)
        self.assertIn('go-timer-fired-v7-result/', retained)
        suites = json.loads((ROOT / 'tools/ci/suites.json').read_text())['suites']
        suite, = [row for row in suites if row['id'] == 'latent-wasmtime.test.local-service']
        self.assertEqual(suite['expectedIgnored'].count(owner.FIRED_TIMER_CASE), 1)
        self.assertEqual(suite['ignoredLeaves'].count(owner.FIRED_TIMER_CASE.rsplit('::', 1)[1]), 1)
        structural = lanes.structural_workflow(workflow)
        policy = json.loads((ROOT / 'tools/ci/contracts/workflows/go-synchronization-reference.yml/workflow.json').read_text())
        job = json.loads((ROOT / 'tools/ci/contracts/workflows/go-synchronization-reference.yml/jobs/synchronization.json').read_text())
        self.assertEqual(policy['policy'], {key: value for key, value in structural.items() if key != 'jobs'})
        self.assertEqual(job['definition'], structural['jobs']['synchronization'])


if __name__ == '__main__':
    unittest.main()
