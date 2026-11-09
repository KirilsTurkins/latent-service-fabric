"""Fail-closed controls for the fired Go one-shot diagnostic campaign."""
import json
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import qualify_go_synchronization as owner
from tools.go_guest import fired_timer_witness as probe

ROOT = Path(__file__).resolve().parents[2]


def output(include_returned_cancel=False):
    cases = [('stop', 0, 'success', 1), ('reset', 1, 'success', 2), ('returned-stop', 2, 'success', 3),
             ('returned-reset', 3, 'success', 4)]
    if include_returned_cancel:
        cases.append(('returned-cancel', 4, 'cancelled', 5))
    cases.append(('fresh', 0, 'success', 6 if include_returned_cancel else 5))
    rows = [dict(case=case, mode=mode, outcome=outcome, storesCreated=count, liveStores=0,
                 liveInstances=0, reservations=0, reservedFuel=0, reservedMemory=0, pendingProviderWaits=0)
            for case, mode, outcome, count in cases]
    lines = [f'test {owner.FIRED_TIMER_CASE} ... ok']
    lines.extend('GO_TIMER_FIRED_CASE ' + json.dumps(row) for row in rows)
    lines.append('test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 53 filtered out;')
    return ('\n'.join(lines) + '\n').encode()


def diagnostic(include_returned_cancel=False):
    ids = ['go-timer-fired-stop', 'go-timer-fired-reset']
    lines = []
    for name in ids:
        lines.append(f'LSF-GO-TIMER-WAIT-DROP-V1|{name}|1')
        lines.append(f'LSF-GO-TIMER-FIRED-V1|{name}|1|0|0|512')
    for name in ['go-timer-returned-stop', 'go-timer-returned-reset']:
        lines.append(f'LSF-GO-TIMER-WAIT-DROP-V1|{name}|1')
        lines.append(f'LSF-GO-TIMER-RETURNED-V1|{name}|1|0|0|512')
    if include_returned_cancel:
        lines.append('LSF-GO-TIMER-WAIT-DROP-V1|go-timer-returned-cancel|1')
        lines.append('LSF-GO-TIMER-RETURNED-CANCEL-V1|go-timer-returned-cancel|1|0|0|512')
    return ('\n'.join(lines) + '\n').encode()


class FiredTimerControls(unittest.TestCase):
    def test_exact_fence_derivation_and_source_drift(self):
        source = (ROOT / 'sdk/go-guest/runtime/timer_async.go.in').read_bytes()
        derived = probe.derive(source)
        self.assertEqual(derived.count(b'lsfFiredFenceWitness()'), 2)
        self.assertIn(probe.INSTRUMENTED, derived)
        self.assertIn(probe.INSTRUMENTED_STOPPED, derived)
        self.assertIn(b'wait.token == lsfFiredFirstStopped', derived)
        self.assertIn(probe.INSTRUMENTED_EVENT, derived)
        timer_bridge = (ROOT / 'sdk/go-guest/runtime/timer_bridge.go.in').read_bytes()
        activation_bridge = (ROOT / 'sdk/go-guest/runtime/activation_bridge.go.in').read_bytes()
        self.assertIn(probe.BRIDGE, probe.derive_bridge(timer_bridge))
        self.assertIn(probe.PARK_INSTRUMENTED, probe.derive_activation_bridge(activation_bridge))
        for invalid in (timer_bridge.replace(b'func lsfNextTimer()', b'func other()'), timer_bridge + b'lsfReturnedTickerSelected'):
            with self.assertRaisesRegex(ValueError, 'source-drift'): probe.derive_bridge(invalid)
        for invalid in (activation_bridge.replace(probe.PARK_MATCH, b'changed'), activation_bridge + probe.PARK_MATCH):
            with self.assertRaisesRegex(ValueError, 'source-drift'): probe.derive_activation_bridge(invalid)
        for changed in (source.replace(probe.EVENT, b'changed'), source.replace(probe.MATCH, b'changed'), source.replace(probe.SIGNATURE, b'changed'),
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
        self.assertEqual([row['case'] for row in parsed['cases']], ['stop', 'reset', 'returned-stop', 'returned-reset', 'fresh'])
        self.assertEqual(len(parsed['physicalWaitDrops']), 4)
        self.assertEqual(len(parsed['returnedWitnesses']), 2)
        for out, diag in (
            (output().replace(owner.FIRED_TIMER_CASE.encode(), b'other'), diagnostic()),
            (output().replace(b'"liveStores": 0', b'"liveStores": 1', 1), diagnostic()),
            (output() + output(), diagnostic()),
            (output(), diagnostic().replace(b'|1|0|0|512', b'|1|1|0|512', 1)),
            (output(), diagnostic().replace(b'|1|0|0|512', b'|1|0|1|512', 1)),
            (output(), diagnostic().replace(b'RETURNED-V1|go-timer-returned-stop|1', b'RETURNED-V1|go-timer-returned-stop|0')),
            (output(), diagnostic().replace(b'RETURNED-V1|go-timer-returned-reset', b'RETURNED-V1|foreign')),
            (output(), diagnostic().replace(b'WAIT-DROP-V1|go-timer-returned-stop|1', b'WAIT-DROP-V1|go-timer-returned-stop|0')),
            (output(), diagnostic().replace(b'WAIT-DROP-V1|go-timer-fired-stop|1', b'WAIT-DROP-V1|go-timer-fired-stop|0')),
            (output(), diagnostic() + diagnostic()),
        ):
            with self.subTest(out=out[:100], diag=diag[:100]), self.assertRaises(ValueError):
                owner.fired_timer_observations(out, diag, 53)

    def test_current_cancellation_requires_its_exact_case_witness_and_original_wait_drop(self):
        parsed = owner.fired_timer_observations(output(True), diagnostic(True), 53, include_returned_cancel=True)
        self.assertEqual([row['case'] for row in parsed['cases']],
            ['stop', 'reset', 'returned-stop', 'returned-reset', 'returned-cancel', 'fresh'])
        self.assertEqual(parsed['returnedCancellationWitness']['activation'], 'go-timer-returned-cancel')
        for out, diag in (
            (output(), diagnostic()),
            (output(True).replace(b'"outcome": "cancelled"', b'"outcome": "success"'), diagnostic(True)),
            (output(True), diagnostic(True).replace(b'RETURNED-CANCEL-V1|go-timer-returned-cancel|1',
                                                    b'RETURNED-CANCEL-V1|go-timer-returned-cancel|0')),
            (output(True), diagnostic(True).replace(b'WAIT-DROP-V1|go-timer-returned-cancel|1',
                                                    b'WAIT-DROP-V1|go-timer-returned-cancel|0')),
        ):
            with self.subTest(out=out[:100], diag=diag[-100:]), self.assertRaises(ValueError):
                owner.fired_timer_observations(out, diag, 53, include_returned_cancel=True)
        with self.assertRaises(ValueError):
            owner.fired_timer_observations(output(True), diagnostic(True), 53)


    def test_receipt_retains_all_validated_fired_and_returned_cases(self):
        available = {owner.FIRED_TIMER_CASE, *(f'other_{index}' for index in range(53))}
        suite = {'id': 'latent-wasmtime.test.local-service',
                 'expectedIgnored': [owner.FIRED_TIMER_CASE], 'timeoutSeconds': 900}
        result = SimpleNamespace(returncode=0, output=b'', stderr=b'')

        def owned(command, **_kwargs):
            if command[0] == 'git' or '--list' in command:
                return result
            return SimpleNamespace(returncode=0, output=output(True), stderr=diagnostic(True))

        expected = owner.fired_timer_observations(output(True), diagnostic(True), 53, include_returned_cancel=True)
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(owner.sys, 'platform', 'linux'), \
                patch.object(owner.artifacts, 'require_source'), \
                patch.object(owner, 'source_snapshot', return_value={'digest': 'unchanged'}), \
                patch.object(owner, 'compile_identity', return_value={'digest': 'fixture'}), \
                patch.object(owner.registry, 'load', return_value={'suites': [suite]}), \
                patch.object(owner.discovery, 'listing', side_effect=[available, {owner.FIRED_TIMER_CASE}]), \
                patch.object(owner.discovery, 'validate_cases'), \
                patch.object(owner, 'run_owned', side_effect=owned):
            out = Path(temporary) / 'output'
            receipt = owner.qualify(ROOT, out, Path(temporary) / 'fixture', None,
                                    'test-revision', 'timer-fired-v7')
            self.assertEqual(receipt, json.loads((out / 'receipt.json').read_text(encoding='utf-8')))
            self.assertEqual(receipt['signedCases'], expected['cases'])
            self.assertEqual(receipt['signedInvocations'], 6)
            self.assertEqual(receipt['signedInvocations'], len(receipt['signedCases']))
            self.assertEqual(receipt['originalTimerOverlapWitnesses'], expected['witnesses'])
            self.assertEqual(receipt['returnedTimerWitnesses'], expected['returnedWitnesses'])
            self.assertEqual(receipt['returnedCancellationWitness'], expected['returnedCancellationWitness'])
            self.assertEqual(receipt['physicalTimerWaitDrops'], expected['physicalWaitDrops'])

    def test_compiler_selects_the_diagnostic_sdk_without_editing_the_original(self):
        from tools import qualify_go_activation as activation
        seen = {}
        class SourceOnlyCompiler:
            def __init__(self, _root, sdk, *_args, **_kwargs):
                self.materials = []
                self.goroot = _root / 'fake-goroot'
                directory = self.goroot / 'src/runtime'
                directory.mkdir(parents=True)
                (directory / 'chan.go').write_bytes(b'fake chan\n')
                (directory / 'runtime2.go').write_bytes(b'fake runtime2\n')
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
        native = {'modes': [0, 1, 2, 3], 'output': 42, 'freshProcessPerMode': True,
                  'sourceDigest': 'sha256:' + owner.digest(source)}
        with tempfile.TemporaryDirectory() as temporary, patch.object(activation, 'ROOT', ROOT), \
                patch.object(probe, 'GO_CHAN_SHA256', owner.digest(b'fake chan\n')), \
                patch.object(probe, 'GO_RUNTIME2_SHA256', owner.digest(b'fake runtime2\n')), \
                patch.object(activation, 'Compiler', SourceOnlyCompiler), patch.object(activation, 'stage'), \
                patch.object(activation, 'fixture_reference', return_value=native):
            output = Path(temporary) / 'capture'
            record = activation.compile_fixture(output, runtime_profile='go-component-activation-v7', fixture='timer-fired')
            self.assertEqual(seen['sdk'], output / 'diagnostic-sdk')
            self.assertEqual((seen['sdk'] / 'runtime/timer_async.go.in').read_bytes(), probe.derive(original))
            self.assertEqual(original_path.read_bytes(), original)
            self.assertEqual(record['diagnosticRuntime']['originalTimerAsyncDigest'], 'sha256:' + owner.digest(original))
            # The signed Rust fixture is a separate consumer of this receipt.
            # A mismatched identity otherwise fails only after the guest build.
            rust = (ROOT / 'crates/latent-wasmtime/tests/local_service/runtime/go.rs').read_text(encoding='utf-8')
            expected = re.findall(r'record\["diagnosticRuntime"\]\["kind"\]\s*,\s*"([^"]+)"', rust)
            self.assertEqual(expected, [record['diagnosticRuntime']['kind']])
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
            for folder in ('src', 'wit', 'build', 'diagnostic-sdk/runtime', 'diagnostic-runtime-inputs/runtime'):
                (fixture / folder).mkdir(parents=True)
            (fixture / 'src/main.go').write_bytes(source)
            (fixture / 'wit/world.wit').write_bytes(world)
            (fixture / 'build/component.wasm').write_bytes(b'example-component')
            timer = fixture / 'diagnostic-sdk/runtime/timer_async.go.in'
            timer.write_bytes(derived)
            original_bridge = (ROOT / 'sdk/go-guest/runtime/timer_bridge.go.in').read_bytes()
            original_activation = (ROOT / 'sdk/go-guest/runtime/activation_bridge.go.in').read_bytes()
            (fixture / 'diagnostic-sdk/runtime/timer_bridge.go.in').write_bytes(probe.derive_bridge(original_bridge))
            (fixture / 'diagnostic-sdk/runtime/activation_bridge.go.in').write_bytes(probe.derive_activation_bridge(original_activation))
            (fixture / 'diagnostic-runtime-inputs/runtime/chan.go').write_bytes(b'fake chan\n')
            (fixture / 'diagnostic-runtime-inputs/runtime/runtime2.go').write_bytes(b'fake runtime2\n')
            record = {'profile': 'go-component-activation-v7', 'fixture': 'timer-fired',
                'sourceDigest': 'sha256:' + owner.digest(source), 'sourceUnchanged': True,
                'ordinarySource': True, 'signedExecution': 'not-run',
                'componentDigest': 'sha256:' + owner.digest(b'example-component'),
                'bindingDigest': 'example', 'tools': {}, 'transformations': [],
                'diagnosticRuntime': {'kind': 'selected-returned-ticker-cancel-fence-observe-v4',
                    'originalTimerAsyncDigest': 'sha256:' + owner.digest(original),
                    'derivedTimerAsyncDigest': 'sha256:' + owner.digest(derived),
                    'originalTimerBridgeDigest': 'sha256:' + owner.digest(original_bridge),
                    'derivedTimerBridgeDigest': 'sha256:' + owner.digest(probe.derive_bridge(original_bridge)),
                    'originalActivationBridgeDigest': 'sha256:' + owner.digest(original_activation),
                    'derivedActivationBridgeDigest': 'sha256:' + owner.digest(probe.derive_activation_bridge(original_activation)),
                    'runtimeChanDigest': 'sha256:' + owner.digest(b'fake chan\n'),
                    'runtimeDescriptorDigest': 'sha256:' + owner.digest(b'fake runtime2\n')},
                'nativeReference': {'modes': [0, 1, 2, 3], 'output': 42, 'freshProcessPerMode': True,
                                    'sourceDigest': 'sha256:' + owner.digest(source)}}
            receipt = fixture / 'GO-ACTIVATION-COMPILE.json'
            receipt.write_text(json.dumps(record), encoding='utf-8')
            with patch.object(probe, 'GO_CHAN_SHA256', owner.digest(b'fake chan\n')), \
                    patch.object(probe, 'GO_RUNTIME2_SHA256', owner.digest(b'fake runtime2\n')):
                owner.compile_identity(fixture, ROOT, 'go-component-activation-v7', 'timer-fired')
                timer.write_bytes(derived + b'// tampered')
                with self.assertRaisesRegex(ValueError, 'diagnostic-runtime-drift'):
                    owner.compile_identity(fixture, ROOT, 'go-component-activation-v7', 'timer-fired')
                timer.write_bytes(derived)
                (fixture / 'diagnostic-runtime-inputs/runtime/chan.go').write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'diagnostic-runtime-drift'):
                    owner.compile_identity(fixture, ROOT, 'go-component-activation-v7', 'timer-fired')
                (fixture / 'diagnostic-runtime-inputs/runtime/chan.go').write_bytes(b'fake chan\n')
                for relative in ('diagnostic-runtime-inputs/runtime/runtime2.go',
                                 'diagnostic-sdk/runtime/timer_bridge.go.in',
                                 'diagnostic-sdk/runtime/activation_bridge.go.in'):
                    protected = fixture / relative
                    previous = protected.read_bytes()
                    protected.write_bytes(previous + b'changed')
                    with self.assertRaisesRegex(ValueError, 'diagnostic-runtime-drift'):
                        owner.compile_identity(fixture, ROOT, 'go-component-activation-v7', 'timer-fired')
                    protected.write_bytes(previous)
                record['diagnosticRuntime']['originalTimerAsyncDigest'] = 'sha256:' + '0' * 64
                receipt.write_text(json.dumps(record), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'diagnostic-runtime-drift'):
                    owner.compile_identity(fixture, ROOT, 'go-component-activation-v7', 'timer-fired')

    def test_branch_owner_and_inventory_bind_the_new_campaign(self):
        from tools import ci_lane_inventory as lanes
        workflow = lanes.workflow_model((ROOT / '.github/workflows/go-synchronization-reference.yml').read_text())
        branch = 'feat/go-fired-timer-fence-v7-20261108'
        self.assertIn(branch, workflow['on']['push']['branches'])
        returned_branch = 'feat/go-returned-timer-fence-20261109'
        self.assertIn(returned_branch, workflow['on']['push']['branches'])
        self.assertIn("github.ref_name == '" + returned_branch + "' && 'timer-fired-v7'", workflow['env']['LSF_GO_REFERENCE_CAMPAIGN'])
        cancel_branch = 'feat/go-returned-cancel-20261109'
        self.assertIn(cancel_branch, workflow['on']['push']['branches'])
        self.assertIn("github.ref_name == '" + cancel_branch + "' && 'timer-fired-v7'", workflow['env']['LSF_GO_REFERENCE_CAMPAIGN'])
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
        for suffix in ('src/', 'wit/', 'diagnostic-sdk/runtime/timer_async.go.in',
                       'diagnostic-sdk/runtime/timer_bridge.go.in', 'diagnostic-sdk/runtime/activation_bridge.go.in',
                       'diagnostic-runtime-inputs/', 'build/component.wasm', 'logs/'):
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
