"""Data-only guards for the private replay; no compiler, binary or node runs."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import yaml

from tools import diagnose_typescript_fetch_failure as fetch
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import digest, inventory, read_file


class FetchFailureFrames(unittest.TestCase):
    def material(self, root):
        selected = ('package examples:lsf-typescript-activation@1.0.0;\n\nworld selected {\n'
            '    include examples:typescript-fetch/service@1.0.0;\n'
            '    import latent:runtime/activation@0.1.0;\n'
            '    import latent:clock/monotonic@0.1.0;\n'
            '    import latent:clock/wall@0.1.0;\n}\n').encode()
        materials = {'wit/world.wit': selected,
            **{name: read_file(fetch.ROOT/source) for name, source in fetch.WIT_INPUTS.items()}}
        for name in ('component.wasm', 'capsule.json', 'contracts.json', 'wit-lock.json',
                     'compatibility-report.json', 'typescript-runtime-selection.json', 'package-source.json'):
            materials[name] = name.encode()
            (root/name).write_bytes(materials[name])
        manifest = inventory(materials)
        (root/'package-inputs.json').write_bytes(manifest)
        return materials, digest(manifest), {'sha256': digest(materials['component.wasm']),
                                            'bytes': len(materials['component.wasm'])}

    def test_reconstructed_wit_bytes_match_all_five_original_d412_package_identities(self):
        expected = {
            'wit/world.wit': 'e6f15d4337a87de6374b08e2c05ce6c1613a8c439aed9bb5c10c88cd05f448ef',
            'wit/deps/activation/package.wit': '0855e3524edbe15a5d174a825df6034ef41cd87f1330e2fba884ea6e2c58e946',
            'wit/deps/application/world.wit': 'c47ac93f21282658578663783a845bef511b095f085c73192de4dec025f665ca',
            'wit/deps/clock/package.wit': 'a009ecd4ad23d581523fe97b66327ebe352ac27c9c72d4e09ecc9bb003c466ea',
            'wit/deps/http-v3/package.wit': '6fcae4b3123ec3ce0b32a4e65390630be3bde40ee74b50d7b732150b6bb6147d'}
        with tempfile.TemporaryDirectory() as directory:
            materials, manifest, component = self.material(Path(directory))
            with patch.object(fetch, 'PACKAGE_INPUTS', manifest), patch.object(fetch, 'COMPONENT', component):
                actual = fetch.package_materials(Path(directory))
            self.assertEqual(actual, materials)
            self.assertEqual({name: digest(actual[name]) for name in expected},
                             {name: 'sha256:'+value for name, value in expected.items()})

    def test_changed_component_or_forged_manifest_is_refused_before_restore_or_packager(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _materials, manifest, component = self.material(root)
            with patch.object(fetch, 'PACKAGE_INPUTS', manifest), patch.object(fetch, 'COMPONENT', component), \
                    patch.object(fetch, 'run_bounded_result') as command:
                (root/'component.wasm').write_bytes(b'forged-component')
                with self.assertRaisesRegex(WorkflowError, 'package-bytes-changed'):
                    fetch.package(root, Path('package'), root)
                self.assertFalse((root/'wit').exists())
                command.assert_not_called()
                (root/'package-inputs.json').write_bytes(b'{}')
                with self.assertRaisesRegex(WorkflowError, 'original-package-manifest'):
                    fetch.package_materials(root)

    def test_only_fully_authenticated_materials_are_restored_and_rechecked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            materials, manifest, component = self.material(root)
            with patch.object(fetch, 'PACKAGE_INPUTS', manifest), patch.object(fetch, 'COMPONENT', component), \
                    patch.object(fetch, 'run_bounded_result', return_value=SimpleNamespace(returncode=0)) as command:
                fetch.package(root, Path('package'), root)
                self.assertEqual({name: (root/name).read_bytes() for name in materials}, materials)
                self.assertEqual([row.args[0][1] for row in command.call_args_list], ['build', 'inspect'])
                with self.assertRaisesRegex(WorkflowError, 'already-exists'):
                    fetch.package(root, Path('package'), root)
                self.assertEqual(command.call_count, 2)

    def test_private_replay_keeps_original_failed_json_vector_and_never_exports_stderr(self):
        numeric = {'available': True, 'truncated': False,
                   'frames': [{'functionIndex': 17, 'functionOffset': 23, 'moduleOffset': 101}]}
        service = SimpleNamespace(owner=SimpleNamespace(finished=True), close=Mock(), buffers=[b'',
            b'PRIVATE credential/path/error\n'+fetch.frames.PREFIX+json.dumps(numeric).encode()+b'\n'])
        peer = Mock()
        peer.line.return_value = {'origins': {'primary': {'host': '127.0.0.1', 'port': 12345}}}
        client = Mock()
        client.call.return_value = {'data': {'operation': {'publication': {'id': 'original'}}}}
        row = {'exitCode': 4, 'decoded': None, 'response': {'data': {
            'resolvedRevision': {'releaseDigest': fetch.COMPONENT['sha256']}}}}
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            binaries = {name: Path(name) for name in fetch.fetch.PRODUCTS}
            for name, value in (('RecordingClient', client), ('connect', service), ('configuration', root/'node.json'),
                                ('grants', ([], ['unchanged-grants'])), ('deploy', {'budget': 'original'}), ('call', row)):
                stack.enter_context(patch.object(fetch.fetch, name, return_value=value))
            called = fetch.fetch.call
            stack.enter_context(patch.object(fetch, 'Process', return_value=peer))
            stack.enter_context(patch.object(fetch, 'run_bounded_result', return_value=SimpleNamespace(returncode=0)))
            observed = fetch.replay(root/'artifact', binaries, root/'output')
            self.assertFalse(observed['qualification'])
            self.assertEqual(observed['entry'], row)
            self.assertEqual(observed['numericFrames'], numeric)
            self.assertNotIn('PRIVATE', json.dumps(observed))
            self.assertEqual(called.call_args.args[2:], ('typescript-fetch', 'run',
                [0, 'http://127.0.0.1:12345/conformance/json'], 'fetch-json'))
            service.close.assert_called_once()
            peer.close.assert_called_once()

    def test_manual_observer_has_no_gate_substitution_and_downloads_only_the_authenticated_run(self):
        workflow = yaml.safe_load(read_file(fetch.ROOT/'.github/workflows/typescript-guest.yml'))
        jobs = workflow['jobs']
        self.assertEqual(jobs['fetch-runtime']['needs'], ['boundary', 'source-splicer', 'promise-library', 'fetch-component'])
        self.assertNotIn('continue-on-error', jobs['fetch-runtime'])
        observer = jobs['fetch-failure-frames']
        self.assertIn("github.event_name == 'workflow_dispatch'", observer['if'])
        self.assertEqual(observer['timeout-minutes'], 15)
        steps = observer['steps']
        downloads = [step['with'] for step in steps if step.get('uses', '').startswith('actions/download-artifact@')]
        self.assertEqual(len(downloads), 2)
        self.assertTrue(all(row['run-id'] == 39247171188 and fetch.TESTED in row['name'] for row in downloads))
        selected = [step['with']['ref'] for step in steps if step.get('with', {}).get('ref')]
        self.assertEqual(selected, [fetch.TESTED])
        retained = steps[-1]['with']['path']
        for forbidden in ('private-latentd', 'source-overlays', 'stderr', '**', 'releases'):
            self.assertNotIn(forbidden, retained)


if __name__ == '__main__':
    unittest.main()
