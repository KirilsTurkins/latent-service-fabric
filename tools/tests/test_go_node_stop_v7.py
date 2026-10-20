"""Current Go/source selection cannot turn old or incomplete products into proof."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import qualify_go_node_stop_v7 as reference
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import inventory, snapshot


class GoNodeStopV7(unittest.TestCase):
    def test_unfrozen_actual_producer_pins_refuse_without_network_or_component_build(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(reference.products, 'ARTIFACT', None), \
                patch.object(reference.products, 'api') as network, \
                self.assertRaisesRegex(WorkflowError, 'completed-producer-pins-required'):
            reference.selected(Path(directory))
        network.assert_not_called()

    def test_selection_requires_current_native_and_full_compile_trees_but_not_producer_recipe_equality(self):
        native = {'latent': Path('latent'), 'latentd': Path('latentd'), 'package': Path('package'),
                  'capsule_contracts': Path('contracts'), 'capsule_authoring': Path('authoring')}
        trees = {'wit/owned.wit': {'sha256': 'wit', 'bytes': 3}}
        source = {'native': {'sha256': 'native'}, 'materials': {**trees,
            '.github/workflows/sdk-native-products.yml': {'sha256': 'distinct-producer-recipe', 'bytes': 10}}}
        current = {'runtime': source['native'], 'sdk': {'sha256': 'current-go'}}
        with patch.object(reference.products, 'verify_prepared', return_value={'producer': 'verified'}), \
                patch.object(reference, 'read_json', return_value=source), \
                patch.object(reference, 'current_inputs', return_value=current), \
                patch.object(reference, 'compile_trees', return_value=trees), \
                patch.object(reference.products, 'native_products', return_value=native):
            selected, origin, observed = reference.selected(Path('prepared'))
        self.assertEqual(set(selected), {'latent', 'latentd', 'examples/package',
            'examples/capsule_contracts', 'examples/capsule_authoring'})
        self.assertEqual(selected['examples/package'], native['package'])
        self.assertEqual(origin, {'producer': 'verified'})
        self.assertEqual(observed, {**current, 'nativeCompileTrees': {
            'sha256': reference.digest(trees), 'files': 1, 'bytes': 3}})

    def test_production_or_test_native_drift_and_auxiliary_drift_are_not_silently_aliased(self):
        source = {'native': {'sha256': 'native'}, 'materials': {'wit/owned.wit': {'sha256': 'wit', 'bytes': 3}}}
        for field in ('native', 'material'):
            with self.subTest(field=field), \
                    patch.object(reference.products, 'verify_prepared', return_value={}), \
                    patch.object(reference, 'read_json', return_value=source), \
                    patch.object(reference, 'current_inputs', return_value={'runtime': {'sha256': 'changed' if field == 'native' else 'native'}}), \
                    patch.object(reference, 'compile_trees', return_value={'wit/owned.wit': {'sha256': 'changed', 'bytes': 3}}), \
                    patch.object(reference.products, 'native_products') as execute, \
                    self.assertRaisesRegex(WorkflowError, 'current-native-'):
                reference.selected(Path('prepared'))
            execute.assert_not_called()

    def test_failed_producer_integrity_cannot_reach_compiler_signer_or_node(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(reference.sys, 'platform', 'linux'), \
                    patch.object(reference.os, 'geteuid', return_value=1000, create=True), \
                    patch.object(reference.artifacts, 'require_source'), \
                    patch.object(reference, 'selected', side_effect=WorkflowError('controlled-product-drift')), \
                    patch.object(reference, 'build_component') as compiler, \
                    patch.object(reference, 'Commands') as signer, \
                    patch.object(reference.stop, 'programme') as node, \
                    self.assertRaisesRegex(WorkflowError, 'controlled-product-drift'):
                reference.qualify(root / 'output', root / 'prepared', 'controlled-source')
            compiler.assert_not_called();signer.assert_not_called();node.assert_not_called()
            failed = json.loads((root / 'output/FAILED.json').read_bytes())
            self.assertEqual(failed['stage'], 'authenticated-v7-native-products')
            self.assertFalse(failed['historicalNormalProgrammeRecreated'])
            self.assertFalse(failed['newNativeBuild'])
            self.assertFalse((root / 'output/qualification.json').exists())

    def test_actual_programme_is_only_selected_after_fresh_build_and_explicit_positive_flag(self):
        self.exercise(False)

    def test_post_execution_source_drift_retains_failure_instead_of_successful_qualification(self):
        self.exercise(True)

    def exercise(self, drift):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binaries = {}
            for name in ('latent', 'latentd', 'examples/package', 'examples/capsule_contracts', 'examples/capsule_authoring'):
                path = root / name.replace('/', '-')
                path.write_bytes(b'controlled-test-not-executable')
                binaries[name] = path
            origin, inputs = {'source': 'verified-v7'}, {'runtime': {'sha256': 'before'}}
            after = copy.deepcopy(inputs)
            if drift:
                after['runtime']['sha256'] = 'changed'
            selections = [(binaries, origin, inputs), (binaries, origin, after)]
            def build(language, app, destination, selected):
                self.assertEqual(language, 'go');self.assertEqual(selected, binaries)
                destination.mkdir()
                (destination / 'source-inputs.json').write_bytes(inventory(snapshot(app)))
                (destination / 'BUILD-COMPLETE.json').write_bytes(b'{}')
                (destination / 'component.wasm').write_bytes(b'controlled-test-not-component')
                return destination
            signer = SimpleNamespace(run=Mock(), records=[])
            with patch.object(reference.sys, 'platform', 'linux'), \
                    patch.object(reference.os, 'geteuid', return_value=1000, create=True), \
                    patch.object(reference.artifacts, 'require_source'), \
                    patch.object(reference, 'selected', side_effect=selections), \
                    patch.object(reference, 'build_component', side_effect=build) as compiler, \
                    patch.object(reference, 'package_identity', return_value={'controlled': True}), \
                    patch.object(reference, 'Commands', return_value=signer), \
                    patch.object(reference.stop, 'programme', return_value={'controlled': True}) as programme:
                if drift:
                    with self.assertRaisesRegex(WorkflowError, 'observed-inputs-changed'):
                        reference.qualify(root / 'output', root / 'prepared', 'controlled-source')
                else:
                    result = reference.qualify(root / 'output', root / 'prepared', 'controlled-source')
                    self.assertEqual(result['status'], 'passed')
                    self.assertFalse(result['historicalNormalProgrammeRecreated'])
                    self.assertEqual(result['nativeProducer'], origin)
                    self.assertEqual(result['currentSourceInputs'], inputs)
            compiler.assert_called_once()
            signer.run.assert_called_once()
            programme.assert_called_once_with({'latent': binaries['latent'], 'latentd': binaries['latentd']},
                root / 'output/signed', root / 'output', positive_timers=True)
            if drift:
                self.assertEqual(json.loads((root / 'output/FAILED.json').read_bytes())['stage'], 'final-integrity')
                self.assertFalse((root / 'output/qualification.json').exists())


if __name__ == '__main__':
    unittest.main()
