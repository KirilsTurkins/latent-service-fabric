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


def historical_checkout(value):
    """Authenticate the current action before the exact historical pin inverse."""
    prefix = 'KirilsTurkins/lsf-checkout@'
    current = prefix + '842365d0a25bf5a868311e4cb89c908bdcab4bb8'
    previous = prefix + 'c3024dfac542bb46ebccc7829ddf1f95e0be8da9'
    if type(value) is bytes:
        prefix, current, previous = (item.encode('ascii') for item in (prefix, current, previous))
    if type(value) not in (str, bytes) or not value.count(current) or value.count(prefix) != value.count(current):
        raise AssertionError('historical-workflow-exact-current-checkout-required')
    return value.replace(current, previous)


class RustScratchReplay(unittest.TestCase):
    def test_current_composed_runner_uses_actual_normal_inventory_identity_shape(self):
        observed = gate.current_inputs('rust')['helpers']['run_rust_capsule_workflow.py']
        if observed != gate.COMPOSED_RUNNER:
            # Later selectors must not silently repin the frozen historical replay.
            before = {name: {} for name in ('runtime', 'sdk', 'wit', 'schemas', 'guide', 'helpers')}
            before['helpers'] = {'run_rust_capsule_workflow.py': gate.ORIGINAL_RUNNER}
            current = copy.deepcopy(before)
            current['helpers']['run_rust_capsule_workflow.py'] = observed
            with self.assertRaisesRegex(RuntimeError, 'current-nonnative-normal-inputs'):
                gate.normal_inputs(before, current)
        else:
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
        model = workflow_model(historical_checkout((gate.ROOT/'.github/workflows/rust-capsule-authoring.yml').read_text()))
        selector = model['on']['workflow_dispatch']['inputs']['replay-scratch-refusals']
        self.assertEqual(selector['type'], 'boolean'); self.assertIs(selector['default'], False)
        expected = {
            'standard-clocks': '2f85e02551ffae315f79253363eef9ec668065f66db950421a3d4653a9909131',
            'git-components': '781e1e3016a53b1a230519f97cc97faa4669753aa736e1801087f2718c465d8b',
            'standard-stdio': 'e872419c902e741c14a33cbeadc5c8a93a644673f49bda6bc3e6d394b7dca98c',
            'standard-entropy': '8f6a1fee6b660cf42e9fe48dd79dfb20033a844e3cc33acd051879a0c91edf43',
            'compatibility': 'f35befe01bdb525024e4c3b122bcf64894bb029eadfaf832e4f75e4c8e3a15b5',
            'scratch-refusals': 'fdd5d99f8f7c4e9605c346ee6836f439519ba6e0b5e1890e5f134d4e67a84a25',
            'dependency-matrix': '104d0c7b43056b5359d63d67afffbe3d90cf33af37766cc1741d7800cadcb9a0',
            'git-closure': 'dec8580d8a4a81287f45e88db187a2719602e20b8554c36d7a68ce360d9f1386',
            'authoring': '0dad646ab277e9f9b39cfa21c9d09b3a12495793fe3070ebe5e897412552bc57'}
        for name, identity in expected.items():
            job = copy.deepcopy(model['jobs'][name])
            self.assertEqual(job.pop('if'), "${{ github.event_name != 'workflow_dispatch' || !inputs.replay-scratch-refusals }}")
            if name == 'standard-entropy':
                # #1377 selects the already installed exact toolchain for this
                # source control. All original commands and nine job bodies
                # remain pinned after removing only that reviewed environment.
                steps = [step for step in job['steps'] if step.get('name') ==
                    'Test exact entropy source, ordinary transitive capture and retirement controls']
                self.assertEqual(len(steps), 1)
                self.assertEqual(steps[0].pop('env'), {'RUSTUP_TOOLCHAIN': '1.97.1'})
            self.assertEqual(hashlib.sha256(json.dumps(job, sort_keys=True, separators=(',', ':')).encode()).hexdigest(), identity)
        child = model['jobs']['scratch-replay']
        self.assertEqual(child['timeout-minutes'], 20)
        self.assertNotIn('needs', child)
        self.assertEqual(child['if'], "${{ github.event_name == 'workflow_dispatch' && inputs.replay-scratch-refusals }}")
        commands = '\n'.join(row.get('run', '') for row in child['steps'])
        self.assertIn('tools/replay_rust_scratch.py', commands)
        self.assertNotIn('cargo build', commands); self.assertNotIn('cargo test', commands)
