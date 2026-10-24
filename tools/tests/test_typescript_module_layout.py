"""Real captured input and argv controls; Linux case alone executes bwrap."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from tools.application_dependencies import capture, prepare
from tools.application_dependency_store import DependencyError
from tools.build_process import run_bounded_result
from tools.build_snapshot import canonical, digest
from tools.captured_compiler_isolation import Isolation
from tools.typescript_guest.compiler import Compiler
from tools.typescript_guest.runtime_profile import IMPORT_PROFILE
from tools.qualify_typescript_buffer_commonjs import typecheck_layout_evidence
from tools.phase2_operator_process import WorkflowError


def closure(root, empty=False):
    owner = root/'owner'; owner.mkdir()
    source = root/'original-modules'; source.mkdir()
    if not empty:
        (source/'ordinary').mkdir()
        (source/'ordinary/index.d.ts').write_bytes(b'export const value: number;\n')
        (source/'ordinary/index.js').write_bytes(b'exports.value=7;\n')
    (owner/'package.json').write_bytes(b'{}')
    manifest = {'formatVersion': 1, 'language': 'typescript',
        'selection': {'target': 'wasm32-component', 'runtimeProfile': IMPORT_PROFILE, 'conditions': []},
        'nativeLocks': ['package.json'], 'transformations': [], 'artifacts': [{
            'id': 'npm-selected/control', 'role': 'application', 'format': 'directory',
            'mount': 'dependencies/npm/node_modules', 'source': {'path': str(source)},
            'dependencies': [], 'metadata': {'ecosystem': 'npm', 'assetType': 'selected-node-modules'}}]}
    (owner/'latent.dependencies.json').write_bytes(canonical(manifest)+b'\n')
    selected = capture(owner)
    (owner/'latent.dependencies.lock.json').write_bytes(canonical(selected)+b'\n')
    workspace = root/'workspace'; workspace.mkdir()
    project = workspace/'project'; project.mkdir()
    output = root/'receipt'; output.mkdir()
    return workspace, prepare(owner, project, output, 'typescript')


def boundary(root, workspace):
    value = Isolation.__new__(Isolation)
    value.workspace, value._typecheck_modules, value.read_only_inputs = workspace, None, []
    value.receipt, value.distributions, value.shared = {'formatVersion': 1}, {}, {}
    value.loader_directories, value.child_path = (), None
    value.sandbox = root/'not-executed-bwrap'
    tool = root/'not-executed-tool'; tool.write_bytes(b'argv control only')
    value.tools = {'control': tool}
    return value, tool


class TypecheckModuleAlias(unittest.TestCase):
    def test_actual_capture_registers_one_exact_phase_only_readonly_view(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); workspace, selected = closure(root)
            isolated, tool = boundary(root, workspace)
            plain = isolated.wrap(tool, [], selected.work, {})
            self.assertNotIn('typeScriptNodeModulesAlias', isolated.receipt)
            isolated.select_typecheck_node_modules(selected)
            receipt = isolated.receipt['typeScriptNodeModulesAlias']
            self.assertEqual(receipt['inputIdentity'], selected.identity)
            self.assertEqual(receipt['source'], 'project/dependencies/npm/node_modules')
            self.assertEqual(receipt['destination'], 'project/node_modules')
            self.assertEqual(receipt['files'], 2)
            self.assertEqual(receipt['access'], 'read-only')
            tree = selected.lock['artifacts'][0]
            original = {'inputIdentity': selected.identity, 'moduleTree': {
                'mount': tree['mount'], 'digest': tree['treeDigest'],
                'files': len(tree['files']), 'bytes': sum(row['size'] for row in tree['files'])}}
            artifact = root/'artifact'; artifact.mkdir()
            document = artifact/'compiler-containment.json'
            raw = canonical(isolated.receipt); document.write_bytes(raw)
            (artifact/'build-observation.json').write_bytes(canonical({'materials': [{
                'name': 'compiler-containment', 'digest': digest(raw), 'size': len(raw)}]}))
            typecheck_layout_evidence(artifact, original)
            for field, value in (('phase', 'bundle'), ('access', 'read-write'),
                    ('inputIdentity', 'sha256:'+'0'*64), ('treeDigest', 'sha256:'+'0'*64),
                    ('destination', 'project/other'), ('files', 2.0)):
                changed = dict(isolated.receipt, typeScriptNodeModulesAlias=dict(receipt, **{field: value}))
                document.write_bytes(canonical(changed))
                with self.subTest(field=field), self.assertRaisesRegex(WorkflowError, 'readonly-typecheck-layout'):
                    typecheck_layout_evidence(artifact, original)
            document.write_bytes(raw)
            (artifact/'build-observation.json').write_bytes(canonical({'materials': []}))
            with self.assertRaisesRegex(WorkflowError, 'material-binding'):
                typecheck_layout_evidence(artifact, original)
            after = isolated.wrap(tool, [], selected.work, {})
            active = isolated.wrap(tool, [], selected.work, {}, typecheck_node_modules=True)
            pair = ['--ro-bind', str(selected.work/'dependencies/npm/node_modules'), str(selected.work/'node_modules')]
            self.assertNotIn(str(selected.work/'node_modules'), plain)
            self.assertNotIn(str(selected.work/'node_modules'), after)
            self.assertEqual(sum(active[i:i+3] == pair for i in range(len(active))), 1)
            self.assertEqual(list((selected.work/'node_modules').iterdir()), [])
            with self.assertRaisesRegex(DependencyError, 'already-selected'):
                isolated.select_typecheck_node_modules(selected)
            isolated._check_typecheck_modules()

    def test_real_closure_mutation_destination_collision_and_escape_are_refused(self):
        for mode in ('source-changed', 'destination-collision', 'outside-workspace', 'after-register', 'empty-tree'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); workspace, selected = closure(root, empty=mode=='empty-tree')
                isolated, tool = boundary(root, workspace)
                if mode == 'source-changed':
                    (selected.work/'dependencies/npm/node_modules/ordinary/index.js').write_bytes(b'changed')
                elif mode == 'destination-collision':
                    (selected.work/'node_modules').mkdir(); (selected.work/'node_modules/unobserved').write_bytes(b'x')
                elif mode == 'outside-workspace':
                    isolated.workspace = root/'other'; isolated.workspace.mkdir()
                if mode in ('after-register', 'empty-tree'):
                    isolated.select_typecheck_node_modules(selected)
                    if mode == 'empty-tree':
                        self.assertEqual(isolated.receipt['typeScriptNodeModulesAlias']['files'], 0)
                        isolated._check_typecheck_modules()
                        continue
                    source = selected.work/'dependencies/npm/node_modules/ordinary/index.js'
                    original = source.read_bytes(); source.write_bytes(b'changed')
                    with self.assertRaisesRegex(DependencyError, 'input-mutated'):
                        isolated.wrap(tool, [], selected.work, {}, typecheck_node_modules=True)
                    source.write_bytes(original)
                    (selected.work/'node_modules/forged').write_bytes(b'x')
                    with self.assertRaisesRegex(DependencyError, 'input-mutated'):
                        isolated._check_typecheck_modules()
                else:
                    with self.assertRaises(DependencyError): isolated.select_typecheck_node_modules(selected)

    def test_compiler_opts_in_only_for_typecheck_and_requires_normal_preparation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); workspace, selected = closure(root)
            isolated, tool = boundary(root, workspace)
            compiler = Compiler.__new__(Compiler)
            compiler.application_modules, compiler.isolation = None, isolated
            compiler.commands = SimpleNamespace(root=selected.work, environment={}, run=lambda stage, *args: (stage, args))
            compiler.prepare_application_modules(selected)
            stage, args = compiler.run('typecheck', tool, '--project', selected.work/'tsconfig.json')
            self.assertEqual(stage, 'typecheck'); self.assertIn(str(selected.work/'node_modules'), args)
            for stage in ('bundle', 'componentize', 'node-version'):
                _stage, args = compiler.run(stage, tool)
                self.assertNotIn(str(selected.work/'node_modules'), args)
            with self.assertRaisesRegex(ValueError, 'fresh-isolation'):
                compiler.prepare_application_modules(selected)

    def test_unselected_command_default_is_exact_and_unregistered_alias_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); workspace, selected = closure(root)
            isolated, tool = boundary(root, workspace)
            original = isolated.wrap(tool, ['--control'], selected.work, {})
            self.assertEqual(original, isolated.wrap(tool, ['--control'], selected.work, {},
                typecheck_node_modules=False))
            self.assertNotIn('typeScriptNodeModulesAlias', isolated.receipt)
            with self.assertRaisesRegex(DependencyError, 'not-selected'):
                isolated.wrap(tool, [], selected.work, {}, typecheck_node_modules=True)
            with self.assertRaisesRegex(DependencyError, 'selection-invalid'):
                isolated.wrap(tool, [], selected.work, {}, typecheck_node_modules=0)


class TypecheckModuleNamespace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.platform != 'linux' or not shutil.which('bwrap') or not shutil.which('ldd'):
            if os.environ.get('LSF_REQUIRE_COMPILER_ISOLATION') == '1':
                raise RuntimeError('required actual compiler namespace unavailable')
            raise unittest.SkipTest('actual read-only namespace requires Linux bubblewrap')

    def test_real_namespace_exposes_original_bytes_only_during_readonly_typecheck(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); workspace, selected = closure(root)
            shell = Path(shutil.which('sh')).resolve(strict=True)
            isolated = Isolation(workspace, {'shell': shell}, {})
            isolated.select_typecheck_node_modules(selected)
            environment = {'PATH': os.defpath}
            # The shell has no ambient PATH. Use its builtins for the content
            # read rather than grant an additional executable to the fixture.
            script = 'IFS= read -r line < node_modules/ordinary/index.js; printf "%s\n" "$line"; ! printf forbidden > node_modules/ordinary/index.js'
            result = run_bounded_result(isolated.wrap(shell, ['-c', script], selected.work, environment,
                typecheck_node_modules=True), selected.work, environment, 5, 16384)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b'exports.value=7;\n')
            outside = run_bounded_result(isolated.wrap(shell, ['-c', 'test ! -f node_modules/ordinary/index.js'],
                selected.work, environment), selected.work, environment, 5, 16384)
            self.assertEqual(outside.returncode, 0)
            selected.check_unchanged(); isolated.check_unchanged()
            original = selected.work/'dependencies/npm/node_modules/ordinary/index.js'
            saved = original.with_name('saved.js'); original.rename(saved)
            original.symlink_to(saved)
            with self.assertRaisesRegex(DependencyError, 'link-denied'):
                isolated._check_typecheck_modules()
            original.unlink(); saved.rename(original)
            destination = selected.work/'node_modules'; destination.rmdir()
            destination.symlink_to(selected.work/'dependencies/npm/node_modules', target_is_directory=True)
            with self.assertRaisesRegex(DependencyError, 'link-denied'):
                isolated._check_typecheck_modules()


if __name__ == '__main__': unittest.main()
