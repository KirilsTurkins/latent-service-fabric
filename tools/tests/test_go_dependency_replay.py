"""Pure artifact/provenance and actual fixture-boundary controls; no Go execution."""
import ast
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from tools import replay_go_dependencies as replay
from tools import qualify_go_private_dependencies as maintained
from tools.application_dependency_store import DependencyError
from tools.go_dependency_authoring import failure
from tools.rust_capsule_project import canonical, digest


class ReplayBoundaries(unittest.TestCase):
    def test_original_random_wit_layer_is_bound_and_unknown_layers_still_refuse(self):
        from tools.rust_capsule_project import inventory
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for ordinal, member in enumerate(('wit/deps/random/package.wit', 'private.env')):
                layers = [{'source': name, 'path': name} for name in ('component.wasm', member)]
                observed = {'package-source.json': canonical({'layers': layers}),
                            'component.wasm': b'original component', member: b'original WIT'}
                package = inventory(observed)
                observation = canonical({'materials': [{'name': 'package-inputs',
                    'digest': digest(package), 'size': len(package)}]})
                marker = {'componentDigest': digest(observed['component.wasm']),
                          'observationDigest': digest(observation), 'sourceDigest': digest(b'original source')}
                records = dict(observed, **{'BUILD-COMPLETE.json': canonical(marker),
                    'build-observation.json': observation, 'source-inputs.json': b'original source',
                    'recipe-inputs.json': b'{}', 'package-inputs.json': package, 'deployment.json': b'{}'})
                class FixedArtifact:
                    def extract(self, name, output, maximum=None):
                        prefix = 'go-capsule-authoring/builds/greeting/'
                        self_name = name.removeprefix(prefix)
                        self_outer.assertTrue(name.startswith(prefix))
                        output.parent.mkdir(parents=True, exist_ok=True)
                        output.write_bytes(records[self_name])
                self_outer = self
                artifact = FixedArtifact()
                destination = root / str(ordinal)
                if ordinal == 0:
                    replay.retrieve_build(artifact, 'greeting', destination, marker)
                    self.assertEqual((destination / 'builds/greeting' / member).read_bytes(), b'original WIT')
                else:
                    with self.assertRaisesRegex(Exception, 'fixed-package-layer'):
                        replay.retrieve_build(artifact, 'greeting', destination, marker)
                    self.assertFalse((destination / 'builds/greeting' / member).exists())

    def test_actual_six_product_inventory_reuses_only_five_and_refuses_unexpected_products(self):
        rows = {name: {'sha256': digest(name.encode()), 'bytes': 1}
                for name in replay.PRODUCTS + replay.UNUSED_ORIGINAL_PRODUCTS}
        selected = replay.selected_products({'binaries': rows})
        self.assertEqual(set(selected), set(replay.PRODUCTS))
        self.assertNotIn('examples/go_runtime_probe', selected)
        for changed in ({name: row for name, row in rows.items() if name != 'examples/go_runtime_probe'},
                        dict(rows, unexpected={'sha256': digest(b'other'), 'bytes': 1})):
            with self.assertRaisesRegex(Exception, 'exact-original-native-inventory'):
                replay.selected_products({'binaries': changed})

    def test_wrong_or_ambient_tool_refuses_before_authoring_can_execute_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); tools = root / 'tools'; tools.mkdir()
            paths, expected = {}, {}
            for name in ('go', 'componentize-go', 'wasm-tools'):
                path = tools / name; raw = ('fixture-' + name).encode(); path.write_bytes(raw)
                paths[name] = path
                expected[name] = {'name': name, 'digest': digest(raw), 'size': len(raw)}
            with patch('shutil.which', side_effect=lambda name: str(paths[name])):
                self.assertEqual(replay.compiler_tools(root, expected), paths)
                paths['go'].write_bytes(b'different tool bytes')
                with self.assertRaisesRegex(Exception, 'tool-before-execution'):
                    replay.compiler_tools(root, expected)
                paths['go'] = root / 'ambient-go'; paths['go'].write_bytes(b'fixture-go')
                with self.assertRaisesRegex(Exception, 'outside-owned-inputs'):
                    replay.compiler_tools(root, expected)

    def test_immutable_git_blob_proof_catches_native_tool_source_outside_normal_runtime_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'tools/toolchain-smoke/examples/package.rs'
            path.parent.mkdir(parents=True)
            raw = b'original immutable native source\n'; path.write_bytes(raw)
            expected = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
            with patch.object(replay, 'ROOT', root):
                self.assertEqual(replay.production_blob(path, expected)['sha256'], digest(raw))
                path.write_bytes(raw + b'changed after original native compilation')
                with self.assertRaisesRegex(Exception, 'production-git-preimage-drift'):
                    replay.production_blob(path, expected)

    def test_only_exact_reviewed_reader_import_can_explain_old_qualifier_identity(self):
        raw = (replay.ROOT / 'tools/qualify_rust_capsules.py').read_bytes()
        expected = replay.qualifier_delta(raw)
        self.assertEqual(expected['sha256'], replay.ORIGINAL_QUALIFIER_DIGEST)
        for changed in (raw + b'\n# unexplained delta\n', raw.replace(b'fresh, read_file,', b'fresh, read_file, read_file,')):
            with self.assertRaises(Exception):
                replay.qualifier_delta(changed)

    def test_artifact_names_and_link_entries_refuse_before_writing(self):
        for name in ('../escape', '/absolute', 'x/../../escape', 'x\\escape', 'x:escape', './alias'):
            with self.subTest(name=name), self.assertRaises(Exception):
                replay.safe_name(name)
        with tempfile.TemporaryDirectory() as temporary:
            data = io.BytesIO()
            with zipfile.ZipFile(data, 'w') as archive:
                link = zipfile.ZipInfo('fixed.json'); link.create_system = 3
                link.external_attr = 0o120777 << 16
                archive.writestr(link, '../private')
            reader = object.__new__(replay.Artifact)
            reader.archive, reader.selected = zipfile.ZipFile(data), {}
            target = Path(temporary) / 'fixed.json'
            with self.assertRaises(Exception):
                reader.extract('fixed.json', target)
            self.assertFalse(target.exists())

    def test_actual_normal_receipt_cannot_be_replaced_by_coherent_new_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'qualification.json').write_bytes(canonical({'status': 'passed', 'binaries': {}}))
            with patch.object(replay, 'expected_original_inputs') as selected:
                with self.assertRaisesRegex(Exception, 'original-receipt-drift'):
                    replay.frozen(root)
                selected.assert_not_called()

    def test_compiler_material_completeness_and_aliases_are_not_forgiven(self):
        rows = [{'name': name, 'digest': digest(name.encode()), 'size': 1} for name in replay.COMPILER_MATERIALS]
        self.assertEqual(set(replay.compiler_materials({'materials': rows})), replay.COMPILER_MATERIALS)
        for changed in (rows[:-1], rows + [rows[0]]):
            with self.assertRaises(Exception):
                replay.compiler_materials({'materials': changed})


class ClosedNativeFailure(unittest.TestCase):
    def test_actual_authoring_producer_reason_survives_but_credential_shaped_values_do_not(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'logs').mkdir()
            commands = SimpleNamespace(output=root, records=[{'stage': 'initial-candidate-lock', 'exitCode': 1}])
            path = root / 'logs/00-initial-candidate-lock.stderr.txt'
            for code in ('go-proxy-public-trust-mutated', 'token-secret', 'a' * 64):
                path.write_bytes(canonical(failure('lock', DependencyError(code))))
                result = replay.native_failure(commands)
                if code in replay.NATIVE_FAILURE_REASONS:
                    self.assertEqual(result['reason'], code)
                else:
                    self.assertNotIn('reason', result)
                    self.assertNotIn(code, json.dumps(result))
            self.assertEqual(set(result), {'available', 'phase', 'exitCode'})

    def test_foreign_shape_duplicate_keys_and_hardlinks_cannot_supply_public_reason(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'logs').mkdir()
            commands = SimpleNamespace(output=root, records=[{'stage': 'initial-candidate-lock', 'exitCode': 1}])
            path = root / 'logs/00-initial-candidate-lock.stderr.txt'
            for raw in (b'{"reason":"go-proxy-public-trust-mutated"}', b'{"stage":1,"stage":2}', b'{"v":NaN}'):
                path.write_bytes(raw)
                with self.assertRaises(Exception):
                    replay.native_failure(commands)
            path.write_bytes(canonical(failure('lock', DependencyError('go-proxy-public-trust-mutated'))))
            import os
            os.link(path, root / 'hardlink')
            with self.assertRaisesRegex(Exception, 'diagnostic-bound'):
                replay.native_failure(commands)

    def test_actual_private_wrapper_preserves_exception_identity_when_nested_metadata_and_observer_fail(self):
        original = RuntimeError('private original must not be replaced')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); output = root / 'output'
            commands = SimpleNamespace(output=output, records=[{'stage': 'initial-candidate-lock', 'exitCode': 1}])
            def captured(*args):
                (output / 'logs').mkdir()
                (output / 'logs/00-initial-candidate-lock.stderr.txt').write_bytes(b'[' * 16384 + b'0' + b']' * 16384)
                raise original
            fake_go = root / 'never-executed-go'; fake_go.write_bytes(b'owned fixture tool')
            with patch('tools.rust_capsule_build.Commands', return_value=commands), \
                 patch.object(replay, 'check_baseline', return_value={}), \
                 patch.object(replay, 'frozen', return_value=({}, {}, {})), \
                 patch.object(replay, 'compiler_tools', return_value={'go': fake_go}), \
                 patch.object(replay, 'inputs', return_value={}), \
                 patch('shutil.which', return_value=str(fake_go)), \
                 patch.object(maintained, 'capture', side_effect=captured), \
                 patch.object(replay, 'write_json', side_effect=RecursionError('observer failed')):
                with self.assertRaises(RuntimeError) as caught:
                    replay.private(root / 'prepared', root / 'baseline', output)
                self.assertIs(caught.exception, original)


class ActualPrivateProbeFilename(unittest.TestCase):
    def test_actual_qualifier_publishes_the_exact_case_sensitive_consumer_name(self):
        tree = ast.parse((replay.ROOT / 'tools/run_rust_capsule_workflow.py').read_text())
        names = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                 and n.value.startswith('private-') and n.value.endswith('-probe.json')}
        self.assertEqual(len(names), 1)
        consumer = names.pop()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); go = root / 'never-executed-go'; go.write_bytes(b'fixture only')
            def sign(stage, _tool, command, signed, *args):
                self.assertEqual(command, 'demo-sign'); signed.mkdir()
            commands = SimpleNamespace(run=sign, deadline=float('inf'))
            def build(project, output, *args, **kwargs):
                output.mkdir(); (output / 'BUILD-COMPLETE.json').write_bytes(canonical({'componentDigest': digest(b'component')}))
                (output / 'application-dependencies.json').write_bytes(canonical({'networkResolution': False}))
                return output
            observed = []
            def node(_cli, _node, signed, output, **kwargs):
                # Enumeration is deliberately case sensitive even on Windows.
                self.assertIn(consumer, {p.name for p in signed.iterdir()})
                value = json.loads((signed / consumer).read_bytes()); observed.append(value)
                output.mkdir(); (output / 'workflow.json').write_bytes(canonical({'status': 'passed'}))
                return {'status': 'passed', 'capturedGoPrivate': {'status': 'passed', 'cases': [0, 1, 2]}}
            products = {name: root / name for name in ('capsule_contracts', 'package', 'capsule_authoring', 'latent', 'latentd')}
            receipt = {'sourceIdentityDigest': digest(b'{}'), 'binaries': {}}
            phases = [(root / 'app', {}, version, removed) for version, removed in
                      (('v1.0.0', False), ('v2.0.0', False), ('v2.0.0', True))]
            with patch.object(maintained, 'Commands', return_value=commands), \
                 patch.object(maintained, 'frozen', return_value=(receipt, products, [])), \
                 patch.object(maintained, 'capture', return_value=(phases, {'nonce': 'a' * 24})), \
                 patch.object(maintained, 'source_files', return_value={}), \
                 patch.object(maintained.dependencies, 'verify_inputs', return_value=SimpleNamespace(lock={})), \
                 patch.object(maintained, 'build', side_effect=build), \
                 patch.object(maintained, 'node_workflow', side_effect=node), \
                 patch.object(maintained, 'inputs', return_value={}), patch('shutil.which', return_value=str(go)):
                result = maintained.qualify(root / 'prepared', root / 'output')
            self.assertEqual(result['status'], 'passed')
            self.assertEqual([row['removed'] for row in observed], [False, False, True])
            self.assertEqual(len(observed), 3)


if __name__ == '__main__':
    unittest.main()
