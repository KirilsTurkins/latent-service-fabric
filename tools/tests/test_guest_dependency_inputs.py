"""Actual reviewed outer/app inputs remain attributable and fail closed on drift."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import application_dependencies as dependencies, guest_dependency_inputs as inputs
from tools.application_dependency_store import DependencyError, Store
from tools.build_snapshot import canonical, digest
from tools.dev_workflow import common, project
from tools.rust_capsule_project import snapshot
from tools.tests.test_dev_contracts import descriptor


class FrontendDependencyInputs(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.owner = self.root / 'project'
        self.app = self.owner / 'app'
        self.app.mkdir(parents=True)
        (self.app / 'src').mkdir()
        (self.app / 'src/application.txt').write_bytes(b'unchanged ordinary application')
        (self.app / 'sdk-lock.json').write_bytes(b'{"immutable":"sdk"}')
        (self.app / 'native.lock').write_bytes(b'exact original native declaration')
        self.library = self.root / 'outside-private-local-library'
        self.library.mkdir()
        (self.library / 'library.txt').write_bytes(b'actual selected library bytes')

    def capture(self, language='rust', *, native=('app/native.lock',), role='application'):
        value = descriptor()
        value.update(language=language, inputRoots=['app'])
        value['template']['ownerIssue'] = project.LANGUAGES[language]
        value['build']['workingDirectory'] = 'app'
        (self.owner / inputs.DESCRIPTOR).write_bytes(common.encode(value))
        declaration = {'formatVersion': 1, 'language': language, 'selection': {'profile': 'selected-exact-v1'},
            'nativeLocks': list(native), 'artifacts': [{'id': 'outside/uncatalogued/1.0', 'role': role,
                'format': 'directory', 'mount': 'dependencies/selected', 'source': {'path': str(self.library)},
                'dependencies': [], 'metadata': {'license': 'MIT', 'repository': 'private-alias'}}],
            'transformations': []}
        (self.owner / dependencies.MANIFEST).write_bytes(canonical(declaration))
        lock = dependencies.capture(self.owner)
        (self.owner / dependencies.LOCK).write_bytes(canonical(lock))
        return value, declaration, lock

    def materialize(self, observed):
        work = self.root / 'owned-work'
        work.mkdir()
        for name, raw in observed.files.items():
            path = work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        output = self.root / 'output'; output.mkdir()
        return work, output

    def test_all_five_language_inputs_use_exact_outer_capture_without_sdk_changes(self):
        sdk = (self.app / 'sdk-lock.json').read_bytes()
        for language in ('rust', 'go', 'java', 'typescript', 'dotnet'):
            with self.subTest(language=language):
                self.capture(language)
                observed = inputs.capture_source(self.app, language)
                self.assertEqual(observed.dependency_root, self.owner)
                self.assertEqual(observed.application, self.app)
                self.assertEqual(inputs.application_root(self.owner, language), self.app)
                self.assertEqual(observed.files[dependencies.LOCK], (self.owner / dependencies.LOCK).read_bytes())
                self.assertEqual(observed.files['native.lock'], (self.app / 'native.lock').read_bytes())
                mapping = json.loads(observed.files[inputs.MAPPING])
                self.assertEqual(mapping['nativeInputs'], [{'originalPath': 'app/native.lock', 'buildPath': 'native.lock',
                    'digest': digest(observed.files['native.lock']), 'size': len(observed.files['native.lock'])}])
                self.assertEqual(mapping['sdkLockDigest'], digest(sdk))
                self.assertTrue(all(not name.startswith('dependency-inputs/') for name in observed.files))
                observed.check_unchanged()
        self.assertEqual((self.app / 'sdk-lock.json').read_bytes(), sdk)

    def test_originals_deleted_offline_prepare_and_native_read_use_real_captured_bytes(self):
        self.capture()
        observed = inputs.capture_source(self.app, 'rust')
        work, output = self.materialize(observed)
        shutil.rmtree(self.library)
        with patch.object(dependencies, 'fetch', side_effect=AssertionError('offline prepare contacted a source')):
            closure = dependencies.prepare(observed.dependency_root, work, output, 'rust')
            observed.check_unchanged()
        self.assertEqual((work / 'dependencies/selected/library.txt').read_bytes(), b'actual selected library bytes')
        self.assertEqual(closure.project, self.owner)
        self.assertEqual(inputs.read_native(closure, 'native.lock'), b'exact original native declaration')
        receipt = json.loads((output / 'application-dependencies.json').read_bytes())
        self.assertEqual(receipt['inputIdentity'], closure.identity)
        self.assertEqual(receipt['manifestDigest'], digest(observed.files[dependencies.MANIFEST]))
        self.assertFalse(receipt['networkResolution'])

    def test_standalone_source_inventory_and_native_read_preserve_existing_layout(self):
        before = snapshot(self.app)
        observed = inputs.capture_source(self.app, 'rust')
        self.assertEqual(observed.files, before)
        self.assertEqual(observed.dependency_root, self.app)
        self.assertNotIn(inputs.MAPPING, observed.files)
        closure = type('Selected', (), {'project': self.app, 'work': self.app})()
        self.assertEqual(inputs.read_native(closure, 'native.lock'), before['native.lock'])

    def test_descriptor_without_capture_preserves_original_source_inventory_and_creates_no_store(self):
        self.capture(native=())
        (self.owner / dependencies.MANIFEST).unlink()
        (self.owner / dependencies.LOCK).unlink()
        shutil.rmtree(self.owner / 'dependency-inputs')
        observed = inputs.capture_source(self.app, 'rust')
        self.assertEqual(observed.files, snapshot(self.app))
        observed.check_unchanged()
        self.assertFalse((self.owner / 'dependency-inputs').exists())

    def test_shadow_capture_is_rejected_even_when_outer_capture_is_absent(self):
        self.capture()
        for outer in (True, False):
            with self.subTest(outer=outer):
                (self.app / dependencies.MANIFEST).write_bytes((self.owner / dependencies.MANIFEST).read_bytes())
                if not outer:
                    (self.owner / dependencies.MANIFEST).unlink()
                    (self.owner / dependencies.LOCK).unlink()
                with self.assertRaisesRegex(DependencyError, 'ambiguous-application-lock'):
                    inputs.capture_source(self.app, 'rust')

    def test_missing_reviewed_lock_stale_manifest_and_declared_trust_are_rejected(self):
        value, declaration, _lock = self.capture()
        raw = (self.owner / dependencies.LOCK).read_bytes()
        (self.owner / dependencies.LOCK).unlink()
        with self.assertRaisesRegex(common.DevError, 'lock-missing'):
            inputs.capture_source(self.app, 'rust')
        (self.owner / dependencies.LOCK).write_bytes(raw)
        declaration['selection']['profile'] = 'changed-profile-v2'
        (self.owner / dependencies.MANIFEST).write_bytes(canonical(declaration))
        with self.assertRaisesRegex(common.DevError, 'lock-drift'):
            inputs.capture_source(self.app, 'rust')
        self.capture()
        value, _ = project.load(self.owner)
        value['dependencyInputs']['applicationLock'] = 'sha256:' + '0' * 64
        (self.owner / inputs.DESCRIPTOR).write_bytes(common.encode(value))
        with self.assertRaisesRegex(common.DevError, 'trust-binding-drift'):
            inputs.capture_source(self.app, 'rust')

    def test_native_original_cas_missing_and_tampered_bytes_fail_before_build(self):
        _value, _declaration, lock = self.capture()
        native = (self.app / 'native.lock').read_bytes()
        (self.app / 'native.lock').write_bytes(b'changed original')
        with self.assertRaisesRegex(common.DevError, 'native-lock-drift'):
            inputs.capture_source(self.app, 'rust')
        (self.app / 'native.lock').write_bytes(native)
        row = lock['artifacts'][0]['files'][0]
        path = Store(self.owner / 'dependency-inputs/objects', create=False).path(row['digest'])
        original = path.read_bytes(); path.unlink()
        with self.assertRaisesRegex(common.DevError, 'artifact-missing-resolve-explicitly'):
            inputs.capture_source(self.app, 'rust')
        path.write_bytes(original + b'tampered')
        with self.assertRaisesRegex(common.DevError, 'artifact-integrity'):
            inputs.capture_source(self.app, 'rust')

    def test_changed_descriptor_sdk_and_source_inputs_invalidate_original_observation(self):
        for name, raw in ((inputs.DESCRIPTOR, None), ('app/sdk-lock.json', b'{"changed":"sdk"}'),
                          ('app/src/application.txt', b'edited application')):
            with self.subTest(name=name):
                self.capture()
                observed = inputs.capture_source(self.app, 'rust')
                path = self.owner / name
                before = path.read_bytes()
                if raw is None:
                    value = json.loads(before); value['build']['argv'].append('--changed-recipe')
                    raw = common.encode(value)
                path.write_bytes(raw)
                with self.assertRaisesRegex(DependencyError, 'source-input-mutated'):
                    observed.check_unchanged()
                path.write_bytes(before)

    def test_changed_project_selection_and_sibling_application_cannot_use_outer_capture(self):
        value, _, _ = self.capture()
        value['build']['workingDirectory'] = 'different-app'
        (self.owner / inputs.DESCRIPTOR).write_bytes(common.encode(value))
        with self.assertRaisesRegex(DependencyError, 'application-layout'):
            inputs.capture_source(self.app, 'rust')
        value['build']['workingDirectory'] = 'app'; value['language'] = 'go'
        value['template']['ownerIssue'] = project.LANGUAGES['go']
        (self.owner / inputs.DESCRIPTOR).write_bytes(common.encode(value))
        with self.assertRaisesRegex(DependencyError, 'language-mismatch'):
            inputs.capture_source(self.app, 'rust')

    def test_native_projection_collision_and_duplicate_original_aliases_fail_closed(self):
        (self.owner / 'native.lock').write_bytes(b'different outside bytes')
        self.capture(native=('native.lock',))
        with self.assertRaisesRegex(DependencyError, 'source-input-collision'):
            inputs.capture_source(self.app, 'rust')
        (self.owner / 'native.lock').write_bytes((self.app / 'native.lock').read_bytes())
        self.capture(native=('native.lock', 'app/native.lock'))
        with self.assertRaisesRegex(DependencyError, 'native-input-alias'):
            inputs.capture_source(self.app, 'rust')

    def test_compiler_native_projection_is_checked_against_original_reviewed_lock(self):
        self.capture()
        observed = inputs.capture_source(self.app, 'rust')
        work, output = self.materialize(observed)
        closure = dependencies.prepare(self.owner, work, output, 'rust')
        (work / 'native.lock').write_bytes(b'compiler-side mutation')
        with self.assertRaisesRegex(DependencyError, 'native-input-mutated'):
            inputs.read_native(closure, 'native.lock')
        with self.assertRaisesRegex(DependencyError, 'native-input-not-selected'):
            inputs.read_native(closure, 'unselected-private.lock')

    def test_native_mapping_cannot_change_original_descriptor_or_reviewed_lock_identity(self):
        self.capture()
        observed = inputs.capture_source(self.app, 'rust')
        work, output = self.materialize(observed)
        closure = dependencies.prepare(self.owner, work, output, 'rust')
        original = observed.files[inputs.MAPPING]
        for changed in ('formatVersion', 'descriptorDigest', 'applicationPath', 'applicationLock'):
            with self.subTest(changed=changed):
                value = json.loads(original)
                if changed == 'applicationLock':
                    value['dependencyInputs'][changed] = 'sha256:' + '0' * 64
                else:
                    value[changed] = {'formatVersion': True, 'descriptorDigest': 'sha256:' + '0' * 64,
                                      'applicationPath': 'different-app'}[changed]
                (work / inputs.MAPPING).write_bytes(canonical(value))
                with self.assertRaisesRegex(DependencyError, 'native-mapping-invalid'):
                    inputs.read_native(closure, 'native.lock')
        (work / inputs.MAPPING).write_bytes(original)
        self.assertEqual(inputs.read_native(closure, 'native.lock'), b'exact original native declaration')

    def test_reserved_source_mapping_and_native_paths_cannot_override_owned_inputs(self):
        self.capture()
        (self.app / inputs.MAPPING).write_bytes(b'user-controlled alias')
        with self.assertRaisesRegex(DependencyError, 'source-input-collision'):
            inputs.capture_source(self.app, 'rust')
        (self.app / inputs.MAPPING).unlink()
        for name in ('app/dependencies/not-a-native.lock', 'app/application-vendor/not-a-native.lock'):
            path = self.owner / name; path.parent.mkdir(exist_ok=True)
            path.write_bytes(b'reserved input')
            self.capture(native=(name,))
            with self.assertRaisesRegex(DependencyError, 'native-input-reserved'):
                inputs.capture_source(self.app, 'rust')

    def test_typescript_excludes_captured_module_cache_without_broadening_uncaptured_selection(self):
        modules = self.app / 'node_modules'; modules.mkdir()
        (modules / 'unobserved-module.js').write_bytes(b'ambient javascript')
        before = inputs.capture_source(self.app, 'typescript', exclude_when_captured=('node_modules',))
        self.assertIn('node_modules/unobserved-module.js', before.files)
        self.capture('typescript')
        after = inputs.capture_source(self.app, 'typescript', exclude_when_captured=('node_modules',))
        self.assertNotIn('node_modules/unobserved-module.js', after.files)
        after.check_unchanged()

    def test_private_resolution_configuration_and_environment_do_not_enter_mapping(self):
        self.capture()
        (self.owner / 'private-auth-config.json').write_bytes(b'{"token":"never-retain-this-secret"}')
        with patch.dict(os.environ, {'LSF_PRIVATE_RESOLUTION_TOKEN': 'never-retain-this-secret'}):
            observed = inputs.capture_source(self.app, 'rust')
        self.assertNotIn('private-auth-config.json', observed.files)
        self.assertNotIn(b'never-retain-this-secret', observed.files[inputs.MAPPING])
        self.assertNotIn(str(self.library).encode(), observed.files[inputs.MAPPING])

    def test_reviewed_executable_inputs_are_bound_without_granting_execution(self):
        self.capture(role='build-tool')
        observed = inputs.capture_source(self.app, 'rust')
        mapping = json.loads(observed.files[inputs.MAPPING])
        self.assertEqual(mapping['dependencyInputs']['executableInputs'], ['outside/uncatalogued/1.0'])
        work, output = self.materialize(observed)
        with self.assertRaisesRegex(DependencyError, 'require-isolated-stage'):
            dependencies.prepare(self.owner, work, output, 'rust')
        self.assertFalse((work / 'dependencies').exists())

    def staged_consumer(self, language, *, missing=None):
        from tools.dev_tool_distribution import recipe
        payload = self.root / ('staged-' + language)
        payload.mkdir()
        recipe(payload, language)
        staged = payload / 'recipe'
        if missing:
            (staged / missing).unlink()
        script = """import importlib, pathlib, sys
root, owner = map(pathlib.Path, sys.argv[1:3])
language = sys.argv[3]
sys.path.insert(0, str(root))
from tools import application_dependencies as dependencies, guest_dependency_inputs as inputs
from tools.dev_workflow import project, state
importlib.import_module('tools.dev_guest_recipe')
observed = inputs.capture_source(owner / 'app', language)
work, output = owner / 'target/staged-work', owner / 'target/staged-output'
work.mkdir(parents=True); output.mkdir()
for name, raw in observed.files.items():
    path = work / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
closure = dependencies.prepare(observed.dependency_root, work, output, language)
assert closure.project == owner
assert inputs.read_native(closure, 'native.lock') == b'exact original native declaration'
assert (work / 'dependencies/selected/library.txt').read_bytes() == b'actual selected library bytes'
assert not any(name.startswith('dependency-inputs/') for name in observed.files)
assert project.load(owner)[0]['dependencyInputs'] == __import__('json').loads(observed.files[inputs.MAPPING])['dependencyInputs']
private = owner / 'target/private-state'; private.mkdir(mode=0o700)
with state.lock(private, 'staged-authoring.lock'):
    closure.check_unchanged()
    observed.check_unchanged()
for name, loaded in tuple(sys.modules.items()):
    if name.startswith('tools.') and getattr(loaded, '__file__', None):
        assert pathlib.Path(loaded.__file__).resolve().is_relative_to(root), name
print('staged-selected-closure-owned-offline')
"""
        return subprocess.run([sys.executable, '-I', '-B', '-c', script,
                               str(staged), str(self.owner), language], cwd=payload,
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=30, check=False)

    def test_all_six_staged_recipes_consume_reviewed_outer_capture_without_checkout_imports(self):
        for language in ('rust', 'c', 'java', 'dotnet', 'go', 'typescript'):
            with self.subTest(language=language):
                self.capture(language)
                shutil.rmtree(self.library)
                result = self.staged_consumer(language)
                self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace')[:4096])
                self.assertEqual(result.stdout.splitlines(), [b'staged-selected-closure-owned-offline'])
                self.assertEqual(result.stderr, b'')
                shutil.rmtree(self.owner / 'target')
                self.library.mkdir()
                (self.library / 'library.txt').write_bytes(b'actual selected library bytes')

    def test_staged_missing_descriptor_dependency_module_cannot_fall_back_to_checkout(self):
        self.capture('go')
        result = self.staged_consumer('go', missing='tools/dev_workflow/project.py')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'project', result.stderr)
        self.assertNotIn(b'staged-selected-closure-owned-offline', result.stdout)
        self.assertFalse((self.owner / 'target/staged-work/dependencies').exists())

    def test_staged_tampered_cas_fails_before_dependency_materialization(self):
        _, _, lock = self.capture('java')
        row = lock['artifacts'][0]['files'][0]
        Store(self.owner / 'dependency-inputs/objects', create=False).path(row['digest']).write_bytes(b'changed bytes')
        result = self.staged_consumer('java')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'dependency-artifact-integrity', result.stderr)
        self.assertNotIn(b'staged-selected-closure-owned-offline', result.stdout)
        self.assertFalse((self.owner / 'target/staged-work/dependencies').exists())


if __name__ == '__main__':
    unittest.main()
