"""Fixed historical normal ancestry and unchanged original Rust workflow bodies."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import replay_rust_scratch as gate
from tools.phase3_resource_identity import file_identity
from tools.tests.test_sdk_scratch_qualification import ordinary, replace_json


class RustScratchReplay(unittest.TestCase):
    def test_current_composed_runner_uses_actual_normal_inventory_identity_shape(self):
        observed = gate.current_inputs('rust')['helpers']['run_rust_capsule_workflow.py']
        self.assertEqual(observed, gate.COMPOSED_RUNNER)
        self.assertEqual(set(gate.ORIGINAL_RUNNER), {'sha256', 'bytes'})
        self.assertEqual(set(gate.COMPOSED_RUNNER), {'sha256', 'bytes'})

    def test_composition_accepts_only_exact_reviewed_default_dotnet_runner_pair(self):
        before = {name: {} for name in ('runtime', 'sdk', 'wit', 'schemas', 'guide', 'helpers')}
        before['helpers'] = {'run_rust_capsule_workflow.py': gate.ORIGINAL_RUNNER, 'other.py': {'digest': 'fixed'}}
        after = copy.deepcopy(before)
        after['helpers']['run_rust_capsule_workflow.py'] = gate.COMPOSED_RUNNER
        proof = gate.normal_inputs(before, after)
        self.assertFalse(proof['selectedForRust'])
        self.assertEqual(proof['reviewedDelta'], 'default-false-dotnet-published-tasks-only')
        for changed in ('runner', 'other-helper', 'sdk', 'extra-helper'):
            value = copy.deepcopy(after)
            if changed == 'runner': value['helpers']['run_rust_capsule_workflow.py']['bytes'] += 1
            elif changed == 'other-helper': value['helpers']['other.py']['digest'] = 'foreign'
            elif changed == 'sdk': value['sdk'] = {'foreign': True}
            else: value['helpers']['extra.py'] = {}
            with self.subTest(changed=changed), self.assertRaisesRegex(RuntimeError, 'current-nonnative-normal-inputs'):
                gate.normal_inputs(before, value)

    def test_historical_products_bind_fixed_normal_source_and_all_original_layers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); receipt = ordinary(root)
            original_source = {'runtime': {'original': True}, 'sdk': {}, 'wit': {}, 'schemas': {}, 'guide': {}, 'helpers': {}}
            replace_json(root/'source-inputs.json', original_source)
            receipt['sourceIdentityDigest'] = file_identity(root/'source-inputs.json')['sha256']
            replace_json(root/'qualification.json', receipt)
            pins = {'QUALIFICATION': file_identity(root/'qualification.json')['sha256'],
                'SOURCE_INPUTS': file_identity(root/'source-inputs.json')['sha256'],
                'ORIGINAL_NODE': file_identity(root/'node/workflow.json')['sha256']}
            current_source = {**original_source, 'runtime': {'new native source': True}}
            with patch.multiple(gate, **pins), patch.object(gate, 'current_inputs', return_value=current_source):
                binaries, companions, proof = gate.historical(root)
            self.assertEqual(set(binaries), set(gate.PRODUCTS))
            self.assertEqual(set(companions), set(gate.TEMPLATES)-{'greeting'})
            self.assertEqual(proof['originalCompiledSource'], gate.ORIGINAL_SOURCE)
            self.assertFalse(proof['nativeProductsRebuilt'])
            self.assertFalse(proof['currentNormalReceiptFabricated'])
            for name in ('source-inputs.json', 'node/workflow.json', 'native-binaries/latentd',
                         'builds/word-count/component.wasm', 'builds/word-count/package-source.json'):
                path = root/name; original = path.read_bytes()
                try:
                    path.write_bytes(original+b'\n')
                    with patch.multiple(gate, **pins), patch.object(gate, 'current_inputs', return_value=current_source), self.subTest(name=name), self.assertRaises(RuntimeError):
                        gate.historical(root)
                finally:
                    path.write_bytes(original)
            with patch.multiple(gate, **pins), patch.object(gate, 'current_inputs',
                    return_value={**current_source, 'helpers': {'changed compiler': True}}), self.assertRaisesRegex(RuntimeError, 'current-nonnative-normal-inputs'):
                gate.historical(root)

    def test_replay_is_exact38_passed_bundle_and_never_rebinds_native_source(self):
        self.assertEqual((gate.ORIGINAL_RUN, gate.ORIGINAL_ARTIFACT), (39358494292, 12236803645))
        self.assertEqual(gate.ORIGINAL_SOURCE, '38fedd53bb8fc366a9078a3182d88cc03cf0835b')
        self.assertEqual(gate.QUALIFICATION,
            'sha256:87b5664bcca6db0622e2407bf047f3ed30c1f406008370a4ac2cf7a0655fdb9d')
        self.assertEqual(gate.SOURCE_INPUTS,
            'sha256:3677ec116d9e47ca3b96542f274b995dd202ba5ff959e7d642afc510d52fbab6')

    def test_only_explicit_manual_replay_skips_original_nine_complete_jobs(self):
        from tools.ci_lane_inventory import workflow_model
        model = workflow_model((gate.ROOT/'.github/workflows/rust-capsule-authoring.yml').read_text())
        selector = model['on']['workflow_dispatch']['inputs']['replay-scratch-refusals']
        self.assertEqual(selector['type'], 'boolean'); self.assertIs(selector['default'], False)
        expected = {
            'standard-clocks': '2d4c30f5cc6f4efcce7f1e8c66c3a4d88166765bfb56bb95d52291f36b3f0209',
            'git-components': '8ccfe97e408e6448bd413c4f8232f85cd4802af23e9a5e915345aaf7b2e753c2',
            'standard-stdio': '90aa26f4dd0ee4f511226bb7e273233733cbf0a616268941504fd932a25c647a',
            'standard-entropy': 'f5209489e21bea792ac5875549d78eb6f84fba53d55f900a0c7feb504d5c080d',
            'compatibility': '635328a9dc2bf890134232858a0327aa2d98f826d91564d708f5fee4ef512536',
            'scratch-refusals': '61175fefba9c907a2f4d14e42b6aa7f59ad698a0ae4d2151ad3d9281a240b112',
            'dependency-matrix': 'd1d2a66a2cea7567b015a57ac9f2e34bf462f4f0dd3e6a7890e8a7cc3cd744d2',
            'git-closure': '1ac4407d432f10fef94735fcf6d45982d04d2027783ff59cee58c052a1bbeb55',
            'authoring': '31825e93f2c639608acdb4b7e04e5c285c5bfd1864e20da5dc764e154eacde8e'}
        for name, identity in expected.items():
            job = copy.deepcopy(model['jobs'][name])
            self.assertEqual(job.pop('if'), "${{ github.event_name != 'workflow_dispatch' || !inputs.replay-scratch-refusals }}")
            self.assertEqual(hashlib.sha256(json.dumps(job, sort_keys=True, separators=(',', ':')).encode()).hexdigest(), identity)
        child = model['jobs']['scratch-replay']
        self.assertEqual(child['timeout-minutes'], 20)
        self.assertNotIn('needs', child)
        self.assertEqual(child['if'], "${{ github.event_name == 'workflow_dispatch' && inputs.replay-scratch-refusals }}")
        commands = '\n'.join(row.get('run', '') for row in child['steps'])
        self.assertIn('tools/replay_rust_scratch.py', commands)
        self.assertNotIn('cargo build', commands); self.assertNotIn('cargo test', commands)
