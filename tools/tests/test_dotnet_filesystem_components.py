"""Exact retained package restoration fails before signing on any identity drift."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import replay_dotnet_filesystem_components as replay
from tools.ci_lane_inventory import workflow_model
from tools.rust_capsule_project import digest, inventory, snapshot


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'))+'\n').encode()


class FilesystemComponentReplay(unittest.TestCase):
    def fixture(self, root):
        original, _ = replay.project(root/'original', joined=False)
        source = inventory(snapshot(original))
        component = b'authenticated-component-control'
        wit = (original/'wit/world.wit').read_bytes()
        package = encoded({'layers': [{'source': 'component.wasm'}, {'source': 'wit/world.wit'}]})
        package_inputs = inventory({'package-source.json': package, 'component.wasm': component, 'wit/world.wit': wit})
        observation = encoded({'materials': [{'name': 'package-inputs', 'digest': digest(package_inputs), 'size': len(package_inputs)}]})
        files = {'component.wasm': component, 'source-inputs.json': source,
            'package-source.json': package, 'package-inputs.json': package_inputs, 'build-observation.json': observation,
            'BUILD-COMPLETE.json': encoded({'componentDigest': digest(component), 'sourceDigest': digest(source),
                'observationDigest': digest(observation)})}
        return {'pure/'+name: raw for name, raw in files.items()}

    def test_restored_wit_and_component_equal_the_original_observed_signer_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); selected = self.fixture(root); location = root/'new'; location.mkdir()
            app, build, files, proof = replay.restore(location, 'pure', selected)
            self.assertEqual((build/'component.wasm').read_bytes(), selected['pure/component.wasm'])
            self.assertEqual((build/'wit/world.wit').read_bytes(), files['wit/world.wit'])
            self.assertTrue(proof['sourceInventoryEqual'])
            self.assertFalse(proof['nativeAotRecompiled']); self.assertFalse(proof['coreLibRewritten'])
            self.assertEqual((build/'BUILD-COMPLETE.json').read_bytes(), selected['pure/BUILD-COMPLETE.json'])

    def test_source_component_package_layer_or_build_observation_drift_fails_before_signing(self):
        for key in ('source-inputs.json', 'component.wasm', 'package-source.json', 'build-observation.json'):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); selected = self.fixture(root)
                selected['pure/'+key] += b' '
                location = root/'new'; location.mkdir()
                with self.assertRaises(RuntimeError): replay.restore(location, 'pure', selected)

    def test_missing_non_wit_payload_cannot_be_invented_from_current_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); selected = self.fixture(root)
            required = json.loads(selected['pure/package-inputs.json'])
            required['invented.json'] = {'digest': digest(b'{}'), 'size': 2}
            selected['pure/package-inputs.json'] = encoded(required)
            location = root/'new'; location.mkdir()
            with self.assertRaisesRegex(RuntimeError, 'unavailable-package-layer'):
                replay.restore(location, 'pure', selected)

    def test_archive_origin_and_original_failure_are_required_before_download(self):
        artifact = {'id': replay.ARTIFACT, 'expired': False, 'size_in_bytes': replay.ARCHIVE_BYTES,
            'digest': replay.ARCHIVE_DIGEST, 'workflow_run': {'id': replay.RUN, 'head_sha': replay.COMPILED}}
        job = {'run_id': replay.RUN, 'head_sha': replay.COMPILED, 'status': 'completed', 'conclusion': 'failure'}
        for mutation in ('expired', 'digest', 'wrong-source', 'wrong-result'):
            a, j = copy.deepcopy(artifact), copy.deepcopy(job)
            if mutation == 'expired': a['expired'] = True
            elif mutation == 'digest': a['digest'] = 'sha256:'+'0'*64
            elif mutation == 'wrong-source': a['workflow_run']['head_sha'] = '0'*40
            else: j['conclusion'] = 'success'
            with self.subTest(mutation=mutation), patch.object(replay.products.acquisition.historical, 'api', side_effect=[a,j]), \
                    patch.object(replay.subprocess, 'check_output') as download, self.assertRaises(RuntimeError):
                replay.authenticated_components()
            download.assert_not_called()

    def test_manual_lane_keeps_original20_minute_bound_and_needs_no_compiler_or_host_build(self):
        model = workflow_model((replay.ROOT/'.github/workflows/dotnet-filesystem-component-replay.yml').read_text())
        self.assertEqual(set(model['on']), {'workflow_dispatch'})
        job = model['jobs']['replay']; self.assertEqual(job['timeout-minutes'], 20)
        self.assertNotIn('needs', job)
        commands = '\n'.join(s.get('run','') for s in job['steps'])
        for denied in ('cargo build','cargo test','install-tools','setup-dotnet','wasi-sdk','NativeAOT'):
            self.assertNotIn(denied, commands)
        fetched = next(i for i,s in enumerate(job['steps']) if s.get('run','').startswith('git fetch'))
        controls = next(i for i,s in enumerate(job['steps']) if 'unittest' in s.get('run',''))
        self.assertLess(fetched, controls)
        self.assertIn(replay.products.PRODUCTION, commands)


if __name__ == '__main__':
    unittest.main()
