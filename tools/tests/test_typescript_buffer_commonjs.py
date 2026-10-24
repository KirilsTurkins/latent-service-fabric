"""Real project/filesystem boundaries; no compiler, npm or guest execution."""
import copy
import inspect
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import qualify_typescript_buffer as runner
from tools import qualify_typescript_buffer_commonjs as qualifier
from tools import typescript_buffer_commonjs_fixture as fixture
from tools import typescript_buffer_fixture as old_fixture
from tools.rust_capsule_project import ROOT, digest, inventory, read_file, read_json, snapshot, write_json
from tools.typescript_guest.project import validate
from tools.phase2_operator_process import WorkflowError


class PublishedCommonJsBufferControls(unittest.TestCase):
    def test_normal_project_captures_unchanged_lock_and_keeps_original_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = fixture.project(Path(temporary)/'application')
            files = snapshot(app)
            with self.assertRaisesRegex(ValueError, 'reviewed dependency capture'):
                validate(files)
            selected = read_json(app/'capsule-project.json')
            lock = read_json(app/'sdk-lock.json')
            self.assertEqual(selected['limits']['cpuFuel'], 1000000000)
            self.assertEqual(selected['limits']['memoryBytes'], 134217728)
            self.assertEqual(selected['limits']['outboundRequests'], 0)
            self.assertEqual(selected['limits']['effectCount'], 0)
            self.assertEqual(selected['world'], fixture.WORLD)
            self.assertEqual(files['src/main.ts'], read_file(ROOT/fixture.FIXTURE/'main.ts'))
            self.assertEqual(files['package-lock.json'], read_file(ROOT/fixture.FIXTURE/'package-lock.json'))
            self.assertEqual(lock['template']['sourceDigest'], digest(files['src/main.ts']))
            declaration = read_json(app/'package.json')
            self.assertEqual(declaration['devDependencies'], {'@types/buffer-xor': '2.0.2'})
            self.assertEqual(declaration['dependencies'], {'buffer-xor': '2.0.2', 'safe-buffer': '5.2.1'})
            fixture.verify_probe(files)
            for index, name in enumerate(('src/main.ts', 'wit/world.wit')):
                original = read_file(app/name)
                (app/name).write_bytes(original+b'\n// altered probe')
                with self.subTest(name=name), self.assertRaisesRegex(WorkflowError, 'closed-probe-source'):
                    qualifier.qualify(app, Path(temporary)/('refused-'+str(index)),
                        Path(temporary)/'tools', Path(temporary)/'engine',
                        Path(temporary)/'splicer', Path(temporary)/'native')
                (app/name).write_bytes(original)
            original = read_file(app/'capsule-project.json')
            changes = [('world', 'examples:other/service@1.0.0'), ('runtimeProfile', 'other'),
                       *((name, value+1) for name, value in selected['limits'].items()),
                       ('effectCount', False), ('memoryBytes', 134217728.0)]
            for index, (field, value) in enumerate(changes):
                changed = copy.deepcopy(selected)
                if field in ('world', 'runtimeProfile'): changed[field] = value
                else: changed['limits'][field] = value
                (app/'capsule-project.json').write_text(json.dumps(changed))
                with self.subTest(field=field, value=value), self.assertRaisesRegex(WorkflowError, 'closed-probe-'):
                    qualifier.qualify(app, Path(temporary)/('config-refused-'+str(index)),
                        Path(temporary)/'tools', Path(temporary)/'engine',
                        Path(temporary)/'splicer', Path(temporary)/'native')
                (app/'capsule-project.json').write_bytes(original)
            fixture.verify_probe(snapshot(app))

    def test_real_normal_capture_projection_binds_versions_integrity_edges_and_profile(self):
        native = read_json(ROOT/fixture.FIXTURE/'package-lock.json')
        observed = read_json(ROOT/fixture.FIXTURE/'capture-reference.json')
        fixture.validate_graph(native, observed)
        mutations = (
            lambda value: value['nodes'][1].update(version='2.0.3'),
            lambda value: value['nodes'][1].update(integrity='sha512-forged'),
            lambda value: value['nodes'][1].update(selected=False),
            lambda value: value['nodes'][1].update(link=True),
            lambda value: value['nodes'][3]['dependencies'][0].update(selected='node_modules/other-safe-buffer'),
            lambda value: value['selection'].update(conditions=['browser']),
            lambda value: value.update(installScripts='executed'),
        )
        for change in mutations:
            changed = copy.deepcopy(observed); change(changed)
            with self.subTest(change=change), self.assertRaises(WorkflowError):
                fixture.validate_graph(native, changed)

    def evidence(self, root):
        original = {'inputIdentity': 'sha256:'+'1'*64, 'manifestDigest': 'sha256:'+'2'*64,
                    'acceptedLock': 'sha256:'+'3'*64}
        source = b'{"real-source.ts":{"digest":"sha256:control","size":7}}'
        (root/'source-inputs.json').write_bytes(source)
        write_json(root/'application-dependencies.json', {**original, 'lockDigest': original['acceptedLock'],
            'transformations': [], 'networkResolution': False})
        write_json(root/'npm-inputs.json', {'inputIdentity': original['inputIdentity']})
        write_json(root/'bundle-selected-inputs.json', {'capturedInputs': [
            {'path': 'dependencies/npm/node_modules/'+name, 'digest': fixture.SOURCE_FILES[name], 'size': 1}
            for name in ('buffer-xor/index.js', 'safe-buffer/index.js')],
            'inputs': {'lsf-owned-node-buffer:node:buffer': {}},
            'selection': {'inputIdentity': original['inputIdentity'], 'conditions': [], 'commonJs': 'static-require-only'}})
        materials = []
        for name in ('application-dependencies.json', 'npm-inputs.json', 'bundle-selected-inputs.json'):
            data = read_file(root/name)
            materials.append({'name': name.removesuffix('.json'), 'digest': digest(data), 'size': len(data)})
        write_json(root/'build-observation.json', {'materials': materials})
        return original, source

    def test_retained_build_documents_reject_changed_closure_source_and_bundle_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original, source = self.evidence(root)
            result = qualifier.dependency_build_evidence(root, original, source)
            self.assertEqual(len(result), 3)
            for name in ('source-inputs.json', 'application-dependencies.json', 'bundle-selected-inputs.json',
                         'build-observation.json'):
                raw = read_file(root/name)
                if name == 'source-inputs.json':
                    (root/name).write_bytes(raw+b' ')
                else:
                    value = json.loads(raw)
                    if name == 'application-dependencies.json': value['lockDigest'] = 'sha256:'+'0'*64
                    elif name == 'bundle-selected-inputs.json': value['capturedInputs'][0]['digest'] = 'sha256:'+'0'*64
                    else: value['materials'][0]['digest'] = 'sha256:'+'0'*64
                    (root/name).write_text(json.dumps(value))
                with self.subTest(name=name), self.assertRaises(WorkflowError):
                    qualifier.dependency_build_evidence(root, original, source)
                (root/name).write_bytes(raw)
            self.assertEqual(qualifier.dependency_build_evidence(root, original, source), result)

    def test_executor_preserves_eight_case_default_and_refuses_unknown_programmes_before_io(self):
        parameters = inspect.signature(runner.execute).parameters
        self.assertIs(parameters['cases'].default, old_fixture.CASES)
        self.assertIsNone(parameters['scope'].default)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'must-not-exist'
            for cases, scope in ((old_fixture.CASES[:7], None), (fixture.CASES, None),
                                 (old_fixture.CASES, fixture.SCOPE), (fixture.CASES, 'unknown')):
                with self.subTest(cases=cases, scope=scope), self.assertRaisesRegex(WorkflowError, 'closed-qualification'):
                    runner.execute(None, None, output, cases=cases, scope=scope)
                self.assertFalse(output.exists())

    def test_normal_build_failure_cannot_reach_signing_or_invocation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = fixture.project(root/'application')
            originals = {}
            for name in runner.PRODUCTS:
                path = root/('original-'+name); path.write_bytes(b'control binary, never executed')
                originals[name] = path
            with patch.object(qualifier.fixture, 'provenance', return_value={'control': 'source-only'}), \
                    patch.object(qualifier.host, 'verify_prepared', return_value={'control': True}), \
                    patch.object(qualifier.host, 'native_products', return_value=originals), \
                    patch.object(qualifier, 'build', side_effect=ValueError('normal-typecheck-control-failure')), \
                    patch.object(qualifier, 'execute') as execute:
                with self.assertRaisesRegex(ValueError, 'normal-typecheck-control-failure'):
                    qualifier.qualify(app, root/'output', root/'tools', root/'engine', root/'splicer', root/'native')
                execute.assert_not_called()
            self.assertEqual(read_json(root/'output/FAILED.json')['stage'], 'normal-strict-typecheck-bundle-component-package')
            self.assertFalse((root/'output/node').exists())


if __name__ == '__main__':
    unittest.main()
