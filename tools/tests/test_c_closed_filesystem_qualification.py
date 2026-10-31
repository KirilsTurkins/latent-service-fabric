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


def original_libfetch_workflow(value):
    """Remove only the authenticated closed libfetch route before legacy hashes."""
    value = historical_checkout(value)
    edits = (('  push:\n    branches: [development, feat/sdk-690-c-libfetch-http-20261029]\n    paths:\n', '  push:\n    branches: [development]\n    paths:\n'), ("  runtime:\n    if: ${{ github.ref != 'refs/heads/feat/sdk-690-c-libfetch-http-20261029' && (github.event_name != 'workflow_dispatch' || !inputs.replay-closed-filesystem ) }}\n    name: Admitted C capability ownership\n", "  runtime:\n    if: ${{ github.event_name != 'workflow_dispatch' || !inputs.replay-closed-filesystem }}\n    name: Admitted C capability ownership\n"), ('    steps:\n      - name: Start the finite libfetch qualification clock\n        if: github.ref == \'refs/heads/feat/sdk-690-c-libfetch-http-20261029\'\n        run: echo "LSF_C_LIBFETCH_STARTED_NS=$(date +%s%N)" >> "$GITHUB_ENV"\n      - uses: KirilsTurkins/lsf-checkout@c3024dfac542bb46ebccc7829ddf1f95e0be8da9 # v7.0.1 + upstream changes + LSF security fixes\n', '    steps:\n      - uses: KirilsTurkins/lsf-checkout@c3024dfac542bb46ebccc7829ddf1f95e0be8da9 # v7.0.1 + upstream changes + LSF security fixes\n'), ("      - name: Execute the actual captured standard library on current default native products\n        if: github.ref != 'refs/heads/feat/sdk-690-c-libfetch-http-20261029'\n        run: |\n", '      - name: Execute the actual captured standard library on current default native products\n        run: |\n'), ("      - name: Execute ordinary bounded stdio through the same frozen default products\n        if: github.ref != 'refs/heads/feat/sdk-690-c-libfetch-http-20261029'\n        run: |\n", '      - name: Execute ordinary bounded stdio through the same frozen default products\n        run: |\n'), ("      - name: Execute combined ordinary libc facilities with four explicit grants\n        if: github.ref != 'refs/heads/feat/sdk-690-c-libfetch-http-20261029'\n        run: |\n", '      - name: Execute combined ordinary libc facilities with four explicit grants\n        run: |\n'), ("      - name: Execute captured C23 raw resources and physical trap retirement\n        if: github.ref != 'refs/heads/feat/sdk-690-c-libfetch-http-20261029'\n        run: |\n", '      - name: Execute captured C23 raw resources and physical trap retirement\n        run: |\n'), ('          python3 tools/qualify_c_standard_facilities.py --compiled-resources --native-directory "$RUNNER_TEMP/c-standard-facilities/native-build/native" --native-tuple "$RUNNER_TEMP/c-standard-facilities/native-build/native/native-tuple.json" --zig "$(command -v zig)" --wit-bindgen "$(command -v wit-bindgen)" --wasm-tools "$(command -v wasm-tools)" --output "$RUNNER_TEMP/c-compiled-resources"\n      - name: Execute one authentic libfetch client with the current signed typed HTTP backend\n        if: github.ref == \'refs/heads/feat/sdk-690-c-libfetch-http-20261029\'\n        run: >-\n          python3 tools/qualify_c_standard_facilities.py --libfetch-http --build-native\n          --zig "$(command -v zig)" --wit-bindgen "$(command -v wit-bindgen)"\n          --wasm-tools "$(command -v wasm-tools)" --output "$RUNNER_TEMP/c-libfetch-http"\n      - name: Retain bounded C standard runtime proof including failures\n', '          python3 tools/qualify_c_standard_facilities.py --compiled-resources --native-directory "$RUNNER_TEMP/c-standard-facilities/native-build/native" --native-tuple "$RUNNER_TEMP/c-standard-facilities/native-build/native/native-tuple.json" --zig "$(command -v zig)" --wit-bindgen "$(command -v wit-bindgen)" --wasm-tools "$(command -v wasm-tools)" --output "$RUNNER_TEMP/c-compiled-resources"\n      - name: Retain bounded C standard runtime proof including failures\n'), ('          path: |\n            ${{ runner.temp }}/c-libfetch-http/qualified.json\n            ${{ runner.temp }}/c-libfetch-http/FAILED.json\n            ${{ runner.temp }}/c-libfetch-http/logs/**\n            ${{ runner.temp }}/c-libfetch-http/owner-inputs/**\n            ${{ runner.temp }}/c-libfetch-http/project/**\n            ${{ runner.temp }}/c-libfetch-http/native-build/native/native-tuple.json\n            ${{ runner.temp }}/c-libfetch-http/build/**\n            ${{ runner.temp }}/c-libfetch-http/node/signed/release-set.json\n            ${{ runner.temp }}/c-libfetch-http/node/signed/c-thread-runtime/package/**\n            ${{ runner.temp }}/c-libfetch-http/node/signed/c-thread-runtime/evidence/**\n            ${{ runner.temp }}/c-libfetch-http/node/signed/c-thread-runtime/deployment.json\n            ${{ runner.temp }}/c-libfetch-http/node/qualified.json\n            ${{ runner.temp }}/c-libfetch-http/node/FAILED.json\n            ${{ runner.temp }}/c-libfetch-http/node/controls/**\n            ${{ runner.temp }}/c-libfetch-http/node/commands/logs/**\n            ${{ runner.temp }}/c-libfetch-http/node/invocation-*.json\n            ${{ runner.temp }}/c-libfetch-http/node/peer-*.json\n            ${{ runner.temp }}/c-libfetch-http/node/barrier-*.json\n            ${{ runner.temp }}/c-libfetch-http/node/retirement-*.json\n            ${{ runner.temp }}/c-libfetch-http/node/*.stdout\n            ${{ runner.temp }}/c-libfetch-http/node/*.stderr\n            ${{ runner.temp }}/c-standard-facilities/qualified.json\n', '          path: |\n            ${{ runner.temp }}/c-standard-facilities/qualified.json\n'))
    for current, previous in edits:
        if value.count(current) != 1:
            raise AssertionError('historical-workflow-exact-libfetch-route-required')
        value = value.replace(current, previous, 1)
    return value


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
        from tools.ci_lane_inventory import workflow_model
        model = workflow_model(original_libfetch_workflow((gate.ROOT/'.github/workflows/c-guest-authoring.yml').read_text()))
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
