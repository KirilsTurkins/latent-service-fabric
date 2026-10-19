"""A metadata derivation is separately observed and cannot inherit an AOT pass."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import replay_dotnet_console_closed_io as replay
from tools.rust_capsule_project import digest, inventory


class ClosedConsoleReplay(unittest.TestCase):
    def test_selected_production_helper_is_exact_reviewed_source(self):
        self.assertEqual(digest(Path(replay.closed_io.__file__).read_bytes()), replay.CLOSED_SOURCE)
        self.assertEqual(replay.PRODUCTION, '645f912b0ba01d5064167e773c28089e4cd7b248')

    def test_foreign_original_component_refuses_before_nested_input_selection(self):
        with self.assertRaisesRegex(RuntimeError, 'original-component'):
            replay.recover_components(b'foreign component', {})

    def test_fresh_derivation_observation_never_rebinds_original_compilation_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root/'artifact';artifact.mkdir()
            original = {'componentDigest': 'sha256:'+'1'*64, 'nativeAotCompilation': True}
            original['parameters'] = {'compiler': 'native-aot-llvm', 'bindings': 'wit-bindgen-csharp',
                'language': 'csharp', 'target': 'wasi-wasm', 'runtime': 'native-aot', 'locked': True, 'ambientWasi': False}
            original['materials'] = [{'name': name, 'digest': 'sha256:'+'2'*64, 'size': 1}
                for name in ('toolchain-config', 'wasm-tools', 'dotnet', 'wit-bindgen', 'closed-runtime',
                             'compiler-inputs', 'dependency-lock', 'contracts-tool', 'packager')]
            old = (json.dumps(original)+'\n').encode()
            for name in ('BUILD-COMPLETE.json', 'build-observation.json', 'source-inputs.json',
                         'recipe-inputs.json', 'compatibility-report.json'):
                (artifact/name).write_bytes(old)
            (artifact/'component.wasm').write_bytes(b'original component')
            (artifact/'capsule.json').write_bytes(b'{"component":{"digest":"original"}}')
            (artifact/'deployment.json').write_bytes(b'{"spec":{"release":"original"}}')
            document = {'layers': [{'source': name} for name in ('component.wasm', 'capsule.json', 'compatibility-report.json')]}
            (artifact/'package-source.json').write_bytes(json.dumps(document).encode())
            component = root/'selected.wasm';component.write_bytes(b'selected component')
            marker = replay.publish_build(artifact, component, {'nativeAotCompilation': False},
                                         root/'evidence', None, 'a'*40)
            current = json.loads((artifact/'build-observation.json').read_bytes())
            self.assertEqual(current['parameters'], original['parameters'])
            self.assertEqual(current['source']['revision'], digest((artifact/'source-inputs.json').read_bytes())[7:])
            derivation = json.loads((root/'evidence/derivation.json').read_bytes())
            self.assertFalse(derivation['nativeAotCompilation'])
            self.assertEqual(derivation['operation'], 'component-metadata-derivation')
            self.assertEqual(derivation['metadataRecipeSource'], 'a'*40)
            self.assertEqual(next(row for row in current['materials']
                if row['name'] == 'metadata-only-no-native-aot-compilation')['digest'],
                digest((root/'evidence/derivation.json').read_bytes()))
            self.assertEqual(current['componentDigest'], digest(component.read_bytes()))
            self.assertEqual(current['source']['snapshotDigest'], digest((artifact/'source-inputs.json').read_bytes()))
            self.assertEqual(marker['observationDigest'], digest((artifact/'build-observation.json').read_bytes()))
            self.assertEqual((root/'evidence/original-build-observation.json').read_bytes(), old)
            self.assertEqual(json.loads(old)['nativeAotCompilation'], True)
            material = next(row for row in current['materials'] if row['name'] == 'package-inputs')
            expected = inventory({name: (artifact/name).read_bytes() for name in ('package-source.json',
                'component.wasm', 'capsule.json', 'compatibility-report.json')})
            self.assertEqual(material['digest'], digest(expected))
            compatibility = json.loads((artifact/'compatibility-report.json').read_bytes())
            self.assertEqual(compatibility['componentDigest'], current['componentDigest'])
            self.assertEqual(compatibility['status'], 'incomplete')
            self.assertTrue(all(row['evidence'] == 'not-evaluated' for row in compatibility['findings']))

    def test_bad_source_revision_stops_before_any_output_or_original_input_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'absent'
            for source in ('', 'not-a-revision', 'a'*39, 'A'*40):
                with patch.object(replay.sys, 'platform', 'linux'), self.assertRaisesRegex(RuntimeError, 'recipe-source'):
                    replay.replay(Path('missing'), output, source)
                self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
