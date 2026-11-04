"""Historical ancestry is fixed; synthetic controls cannot establish signed execution."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import qualify_c_closed_filesystem as gate
from tools.phase3_resource_identity import file_identity
from tools.tests.test_sdk_scratch_qualification import ordinary, replace_json


from tools.tests.test_sdk_scratch_qualification import historical_security_actions


class ClosedFilesystemQualification(unittest.TestCase):
    def test_actual_c_standard_error_projection_uses_closed_attribution_tokens(self):
        from tools import guest_compatibility as compatibility
        from tools.qualify_sdk_scratch import execution_report
        from tools.sdk_scratch_probe import refusal
        from tools.rust_capsule_project import digest, write_json
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = compatibility.report('c', digest(b'source'), digest(b'component'),
                'lsf-host-abi-phase3-v4', [], [compatibility.finding('lifecycle-unproven',
                    'retirement', 'not-evaluated', owner_issue=736)])
            write_json(root/'compatibility-report.json', original)
            decoded = [{'ok': 'scratch|c|errno=notsup|fresh=1'}]
            rows = [{'mode': mode, 'observation': refusal('c', decoded), 'invocation': {
                'processReaped': True, 'exitCode': 0, 'response': {'outcomeKnown': True}, 'decoded': decoded}}
                for mode in ('open', 'create', 'temp')]
            node = {'releaseSet': {'releases': [{'name': 'my-greeting', 'componentDigest': original['componentDigest']}]},
                    'standardScratchRefusal': {'status': 'passed', 'language': 'c', 'cases': rows}}
            report = execution_report('c', root, node)
            observed = report['findings'][1:4]
            self.assertEqual([x['operation'] for x in observed], ['fopen/read', 'fopen/create', 'tmpfile'])
            self.assertEqual([x['classification'] for x in observed], ['unsupported-reached']*3)
            self.assertEqual(report['findings'][-1]['classification'], 'unresolved-behavior')

    def setUp(self):
        owned = tempfile.TemporaryDirectory(); self.addCleanup(owned.cleanup)
        self.root = Path(owned.name)
        record = ordinary(self.root)
        node_path = self.root/'node/workflow.json'
        node = json.loads(node_path.read_bytes()); node['language'] = 'c'; replace_json(node_path, node)
        record['schemaVersion'] = 'latent.c-capsule.qualification.v1'
        record['node']['receiptDigest'] = file_identity(node_path)['sha256']
        replace_json(self.root/'qualification.json', record)
        self.constants = {'QUALIFICATION': file_identity(self.root/'qualification.json')['sha256'],
            'SOURCE_INPUTS': file_identity(self.root/'source-inputs.json')['sha256'],
            'ORIGINAL_NODE': file_identity(node_path)['sha256']}

    def test_historical_native_five_and_four_companions_keep_original_identity(self):
        with patch.multiple(gate, **self.constants):
            binaries, companions, proof = gate.historical(self.root)
        self.assertEqual(set(binaries), set(gate.PRODUCTS))
        self.assertEqual(set(companions), set(gate.TEMPLATES)-{'greeting'})
        self.assertEqual(proof['normalInvocations'], 27)
        self.assertFalse(proof['currentNormalReceiptFabricated'])
        self.assertFalse(proof['nativeProductsRebuilt'])
        self.assertEqual(proof['source'], gate.ORIGINAL_SOURCE)

    def test_rehashed_receipt_cannot_authenticate_foreign_source_or_node(self):
        for name in ('qualification.json', 'source-inputs.json', 'node/workflow.json'):
            path = self.root/name; original = path.read_bytes()
            try:
                path.write_bytes(original+b'\n')
                with patch.multiple(gate, **self.constants), self.subTest(name=name), self.assertRaisesRegex(RuntimeError, 'original-preimages'):
                    gate.historical(self.root)
            finally:
                path.write_bytes(original)

    def test_native_and_signer_layer_mutations_fail_before_current_compilation(self):
        for name in ('native-binaries/latentd', 'builds/word-count/component.wasm',
                     'builds/word-count/package-source.json', 'builds/word-count/BUILD-COMPLETE.json'):
            path = self.root/name; original = path.read_bytes()
            try:
                if path.name == 'BUILD-COMPLETE.json':
                    replace_json(path, {**json.loads(original), 'foreign': True})
                else:
                    path.write_bytes(original+b'\n')
                with patch.multiple(gate, **self.constants), self.subTest(name=name), self.assertRaises(RuntimeError):
                    gate.historical(self.root)
            finally:
                path.write_bytes(original)

    def test_historical_pin_and_generic_current_verifier_are_not_interchangeable(self):
        self.assertEqual(gate.ORIGINAL_ARTIFACT, 12235113319)
        self.assertEqual(gate.ORIGINAL_RUN, 39354843145)
        self.assertEqual(gate.QUALIFICATION,
            'sha256:1fdaf907bd90543d2e98307e032e635dbaefb18f4b15de37cdb58d04ba168d01')
        self.assertEqual(gate.SOURCE_INPUTS,
            'sha256:10d1c94122a045f32d9a01a2dd51a3827f8ce01a084a4bc4b4a17f90ab00415b')
        from tools import qualify_sdk_scratch as current
        with patch.object(current, 'current_inputs', return_value={'changed current SDK': True}), self.assertRaisesRegex(RuntimeError, 'source-mismatch'):
            current.prepared(self.root, 'c')

    def test_default_off_replay_preserves_all_original_job_bodies_and_bounds(self):
        from tools.tests.test_sdk_scratch_qualification import SECURITY_ACTION_PIN_INVERSES
        for action, current_sha, previous_sha in SECURITY_ACTION_PIN_INVERSES:
            current = action + '@' + current_sha
            previous = action + '@' + previous_sha
            for encode in (str, str.encode):
                self.assertEqual(historical_security_actions(encode(current)), encode(previous))
                for invalid in (previous, current + '\n' + previous, action + '@' + '0' * 40,
                        action + '@unreviewed', current + '0', current + 'suffix'):
                    with self.subTest(action=action, invalid=invalid), self.assertRaisesRegex(
                            AssertionError, '^historical-workflow-exact-current-security-actions-required$'):
                        historical_security_actions(encode(invalid))
        from tools.ci_lane_inventory import workflow_model
        current = (gate.ROOT/'.github/workflows/c-guest-authoring.yml').read_text()
        selected = workflow_model(current)
        outside = selected['on']['workflow_dispatch']['inputs']['outside-capture']
        self.assertEqual(outside['type'], 'boolean'); self.assertIs(outside['default'], False)
        steps = selected['jobs']['standard-facilities']['steps']
        route = next(row for row in steps if row.get('name') == 'Execute two normal outside-source capture identity variants')
        self.assertEqual(route['if'], "github.event_name == 'workflow_dispatch' && inputs.outside-capture && github.ref == 'refs/heads/feat/sdk-690-c-outside-capture-20261031'")
        self.assertIn('--outside-capture --build-native', route['run'])
        dedicated = 'refs/heads/feat/sdk-690-c-outside-capture-20261031'
        self.assertIn("github.ref != '" + dedicated + "'", selected['jobs']['runtime']['if'])
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.outside-capture",
                      selected['jobs']['standard-facilities']['if'])
        self.assertIn("github.ref != '" + dedicated + "'", selected['jobs']['closed-filesystem']['if'])
        defaults = [row for row in steps if row.get('name') in (
            'Execute the actual captured standard library on current default native products',
            'Execute ordinary bounded stdio through the same frozen default products',
            'Execute combined ordinary libc facilities with four explicit grants',
            'Execute captured C23 raw resources and physical trap retirement')]
        self.assertEqual(len(defaults), 4)
        self.assertTrue(all("github.ref != '" + dedicated + "'" in row['if'] for row in defaults))
        # This frozen, derived historical source is checked independently of
        # the current workflow spelling. It is evidence of an earlier review,
        # never execution evidence for the current source.
        archived = (gate.ROOT / 'tools/ci/history/c-guest-closed-filesystem.yml').read_bytes()
        self.assertEqual(hashlib.sha256(archived).hexdigest(),
                         '8fffe0b896cc4709043da9679cb76dc522d7aeb204bccf48e7720c95be2ef3be')
        model = workflow_model(archived.decode('utf-8'))
        selector = model['on']['workflow_dispatch']['inputs']['replay-closed-filesystem']
        self.assertEqual(selector['type'], 'boolean'); self.assertIs(selector['default'], False)
        jobs = copy.deepcopy(model['jobs'])
        self.assertEqual(jobs['runtime'].pop('if'),
            "${{ github.event_name != 'workflow_dispatch' || !inputs.replay-closed-filesystem }}")
        self.assertEqual(jobs['standard-facilities']['if'],
            "${{ github.event_name != 'workflow_dispatch' || (!inputs.qualify-scratch-refusals && !inputs.replay-closed-filesystem) }}")
        jobs['standard-facilities']['if'] = "${{ github.event_name != 'workflow_dispatch' || !inputs.qualify-scratch-refusals }}"
        original = {'runtime': 'bc0a352e086d7408ac98776baa775efefa9a666367ff1d7036256152cbf3680d',
            'standard-facilities': 'd5ce9143431e6a34300c7731be60d45d8d74331e68149929b2af9db4ff7a0196',
            'scratch-refusals': 'b0acceb6c84052bf65335cca2caacaba7a27724b922f7b2ca91a8041d5565602'}
        for name, expected in original.items():
            self.assertEqual(hashlib.sha256(json.dumps(jobs[name], sort_keys=True, separators=(',', ':')).encode()).hexdigest(), expected)
        replay = jobs['closed-filesystem']
        self.assertEqual(replay['timeout-minutes'], 20)
        self.assertEqual(replay['if'], "${{ github.event_name == 'workflow_dispatch' && inputs.replay-closed-filesystem }}")
        commands = '\n'.join(row.get('run', '') for row in replay['steps'])
        self.assertIn('tools/qualify_c_closed_filesystem.py', commands)
        self.assertNotIn('cargo ', commands)
        downloads = [row['with'] for row in replay['steps'] if 'download-artifact@' in row.get('uses', '')]
        self.assertEqual(len(downloads), 1)
        self.assertEqual(downloads[0]['artifact-ids'], '12235113319')
        self.assertEqual(downloads[0]['run-id'], 39354843145)
