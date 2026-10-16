"""Real NuGet capture/review transactions with explicitly modelled native restore."""
import base64
from contextlib import redirect_stderr, redirect_stdout
import copy
import io
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from tools import application_dependencies as inputs, dotnet_capsule
from tools import dotnet_application_dependencies as native, dotnet_dependency_authoring as authoring
from tools.application_dependency_store import DependencyError, Store
from tools.build_snapshot import canonical, digest
from tools.dotnet_guest import project
from tools.dev_workflow import common, project as dev_project
from tools.guest_authoring_frontend import Outcome
from tools.tests.test_dev_contracts import descriptor


class DotnetDependencyAuthoring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix='nuget-authoring-source-')
        cls.addClassCleanup(temporary.cleanup)
        cls.original = project.snapshot(project.create(Path(temporary.name) / 'app', 'greeting'))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='nuget-authoring-model-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.owner = self.app = self.root / 'app'
        self.copy(self.app, self.original)
        self.sdk = (self.app / 'sdk-lock.json').read_bytes()
        self.dotnet = self.root / 'dotnet-model-only'
        self.dotnet.write_bytes(b'not executable: native restore output is modelled explicitly')
        self.tools = self.root / 'compiler-tools'
        self.copy(self.tools / 'package-hash-source', project.snapshot(self.app / 'vendor/lsf/sdk/dotnet-guest/tools/package-hash'))
        helper = self.tools / 'package-hash/PackageHash.dll'
        helper.parent.mkdir(); helper.write_bytes(b'modelled SDK helper binary')
        self.candidate = self.root / 'attempt/candidate.json'
        self.calls = []
        self.after_restore = self.after_hash = None
        authoring.edit(self.app, 'add', identity='Outside.Library', version='1.0.0')

    def copy(self, root, files):
        root.mkdir(parents=True)
        for name, raw in files.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)

    def nested(self):
        outer = self.root / 'owner'
        outer.mkdir()
        shutil.move(self.app, outer / 'app')
        self.owner, self.app = outer, outer / 'app'
        value = descriptor()
        value.update(language='dotnet', inputRoots=['app'])
        value['template']['ownerIssue'] = dev_project.LANGUAGES['dotnet']
        value['build']['workingDirectory'] = 'app'
        (outer / 'latent.project.json').write_bytes(common.encode(value))

    def command(self, command, cwd, environment, seconds, maximum):
        self.calls.append(list(command))
        self.assertEqual(environment['DOTNET_ROLL_FORWARD'], 'Disable')
        self.assertEqual(environment['MSBUILDDISABLENODEREUSE'], '1')
        self.assertTrue(Path(environment['NUGET_PACKAGES']).is_relative_to(cwd))
        if command[1:] == ['--version']:
            return SimpleNamespace(stdout=b'10.0.100\n')
        if command[1] == 'restore':
            self.assertIn('--disable-parallel', command)
            self.assertIn('-p:ImportDirectoryBuildTargets=false', command)
            root = Path(cwd)
            baseline = json.loads(self.original['vendor/lsf/sdk/dotnet-guest/probes/smoke/packages.lock.json'])
            lock = copy.deepcopy(baseline)
            libraries, targets = {}, {}
            for group in baseline['dependencies'].values():
                for name, row in group.items():
                    identity = name + '/' + row['resolved']
                    libraries[identity] = {'type': 'package', 'path': identity.lower(), 'sha512': row['contentHash'], 'files': []}
                    targets[identity] = {}
            for name, version in [('Outside.Library', '1.0.0'), ('Outside.Child', '2.0.0')]:
                identity = name.lower() + '/' + version
                folder = root / 'packages' / identity
                folder.mkdir(parents=True)
                package = folder / (name.lower() + '.' + version + '.nupkg')
                with zipfile.ZipFile(package, 'w') as archive:
                    archive.writestr(name + '.nuspec', b'<package />')
                    archive.writestr('resources/greeting.txt', b'original owned immutable resource')
                content_hash = base64.b64encode(__import__('hashlib').sha512(package.read_bytes()).digest()).decode()
                lock['dependencies']['net10.0'][name] = {'type': 'Direct' if name.endswith('Library') else 'Transitive',
                    'resolved': version, 'contentHash': content_hash}
                libraries[name + '/' + version] = {'type': 'package', 'path': identity, 'sha512': content_hash,
                    'files': [name + '.nuspec', 'resources/greeting.txt']}
                targets[name + '/' + version] = {'dependencies': {'Outside.Child': '[2.0.0]'}} if name.endswith('Library') else {}
            assets = {'version': 3, 'targets': {'net10.0': targets, 'net10.0/wasi-wasm': targets}, 'libraries': libraries}
            (root / native.LOCK).write_bytes(canonical(lock))
            (root / 'obj').mkdir()
            (root / 'obj/project.assets.json').write_bytes(canonical(assets))
            if self.after_restore:
                self.after_restore()
            return SimpleNamespace(stdout=b'')
        if command[1].endswith('PackageHash.dll'):
            content_hash = base64.b64encode(__import__('hashlib').sha512(Path(command[2]).read_bytes()).digest())
            if self.after_hash:
                self.after_hash()
            return SimpleNamespace(stdout=content_hash + b'\n')
        self.fail('unexpected modelled command')

    def resolve(self):
        with patch.object(native, 'run_bounded', side_effect=self.command):
            return native.resolve(self.owner, self.candidate, dotnet=self.dotnet, tools=self.tools)

    def accept(self):
        lock = self.resolve()
        result = authoring.review(self.owner, self.candidate, digest(self.candidate.read_bytes()))
        self.assertEqual(result['status'], 'reviewed')
        return lock

    def test_exact_edits_preserve_sdk_and_accepted_lock_without_native_execution(self):
        (self.owner / inputs.LOCK).write_bytes(b'prior accepted bytes remain a drift fence')
        with patch.object(native, 'run_bounded', side_effect=AssertionError('editing must not restore')):
            authoring.edit(self.owner, 'update', identity='outside.library', version='2.3.4-beta.1')
            self.assertIn(b'[2.3.4-beta.1]', (self.app / native.PROJECT).read_bytes())
            authoring.edit(self.owner, 'remove', identity='Outside.Library')
        self.assertNotIn(b'Outside.Library', (self.app / native.PROJECT).read_bytes())
        self.assertEqual((self.owner / inputs.LOCK).read_bytes(), b'prior accepted bytes remain a drift fence')
        self.assertEqual((self.app / 'sdk-lock.json').read_bytes(), self.sdk)

    def test_sdk_package_and_nonexact_version_edits_fail_before_writes(self):
        before = authoring.source_files(self.app)
        for version in ('*', '[1,2)', '1.0', '$UNREVIEWED', '1.0.0\n'):
            with self.assertRaisesRegex(DependencyError, 'exact-version'):
                authoring.edit(self.owner, 'update', identity='Outside.Library', version=version)
        with self.assertRaisesRegex(DependencyError, 'sdk-package-edit-denied'):
            authoring.edit(self.owner, 'remove', identity='BytecodeAlliance.Componentize.DotNet.Wasm.SDK')
        self.assertEqual(authoring.source_files(self.app), before)

    def test_resolve_capture_requires_exact_review_then_verifies_offline_originals(self):
        lock = self.resolve()
        self.assertFalse((self.owner / inputs.LOCK).exists())
        self.assertEqual({row['id'] for row in lock['artifacts']}, {'outside.library/1.0.0', 'outside.child/2.0.0'})
        self.assertEqual(lock['artifacts'][1]['dependencies'], ['outside.child/2.0.0'])
        self.assertNotIn(str(self.root), (self.owner / inputs.MANIFEST).read_text())
        with self.assertRaisesRegex(DependencyError, 'review-drift'):
            authoring.review(self.owner, self.candidate, 'sha256:' + '0' * 64)
        self.assertFalse((self.owner / inputs.LOCK).exists())
        with patch.object(native, 'run_bounded', side_effect=AssertionError('offline review/status must not resolve')):
            authoring.review(self.owner, self.candidate, digest(self.candidate.read_bytes()))
            result = authoring.status(self.owner)
        self.assertEqual(result['status'], 'verified')
        self.assertFalse(result['compilerExecution'])
        self.assertEqual((self.app / 'sdk-lock.json').read_bytes(), self.sdk)

    def test_nested_owner_captures_rebased_native_locks_without_inner_shadow(self):
        self.nested()
        lock = self.accept()
        self.assertEqual({row['path'] for row in lock['nativeLocks']},
            {'app/' + name for name in (native.PROJECT, 'global.json', native.LOCK, native.ASSETS)})
        self.assertFalse((self.app / inputs.MANIFEST).exists())
        self.assertFalse((self.app / inputs.LOCK).exists())
        self.assertEqual(authoring.status(self.app)['status'], 'verified')
        (self.app / inputs.MANIFEST).write_bytes((self.owner / inputs.MANIFEST).read_bytes())
        with self.assertRaisesRegex(DependencyError, 'ambiguous-application-lock'):
            authoring.status(self.owner)

    def test_failed_restore_does_not_mutate_accepted_manifest_or_native_graph(self):
        self.accept()
        before = authoring.source_files(self.app)
        accepted = (self.owner / inputs.LOCK).read_bytes()
        self.candidate = self.root / 'failed/candidate.json'
        with patch.object(native, 'run_bounded', side_effect=RuntimeError('private external diagnostic')):
            with self.assertRaises(RuntimeError):
                native.resolve(self.owner, self.candidate, dotnet=self.dotnet, tools=self.tools)
        self.assertEqual(authoring.source_files(self.app), before)
        self.assertEqual((self.owner / inputs.LOCK).read_bytes(), accepted)
        self.assertFalse(self.candidate.exists())

    def test_source_drift_during_restore_prevents_all_publication(self):
        self.after_restore = lambda: (self.app / 'src/Main.cs').write_bytes(b'concurrent user source')
        with self.assertRaisesRegex(DependencyError, 'source-lock-resolver-or-helper-mutated'):
            self.resolve()
        for name in (native.LOCK, native.ASSETS, inputs.MANIFEST, inputs.LOCK):
            self.assertFalse((self.owner / name).exists())
        self.assertEqual((self.app / 'src/Main.cs').read_bytes(), b'concurrent user source')
        self.assertFalse(self.candidate.exists())

    def test_helper_drift_during_restore_prevents_all_publication(self):
        self.after_hash = lambda: (self.tools / 'package-hash/PackageHash.dll').write_bytes(b'mutated helper')
        with self.assertRaisesRegex(DependencyError, 'source-lock-resolver-or-helper-mutated'):
            self.resolve()
        self.assertFalse((self.owner / inputs.MANIFEST).exists())
        self.assertFalse((self.app / native.LOCK).exists())

    def test_candidate_write_failure_rolls_back_new_native_state(self):
        original = authoring.paths.write_new
        def fail(path, raw):
            if path == self.candidate:
                raise OSError('modelled disk publication failure')
            return original(path, raw)
        with patch.object(authoring.paths, 'write_new', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'publication failure'):
                self.resolve()
        for name in (native.LOCK, native.ASSETS, inputs.MANIFEST, inputs.LOCK):
            self.assertFalse((self.owner / name).exists())

    def test_candidate_write_failure_restores_previous_accepted_state(self):
        self.accept()
        before = authoring.source_files(self.app)
        accepted = (self.owner / inputs.LOCK).read_bytes()
        self.candidate = self.root / 'next/candidate.json'
        original = authoring.paths.write_new
        def fail(path, raw):
            if path == self.candidate:
                raise OSError('modelled disk publication failure')
            return original(path, raw)
        with patch.object(authoring.paths, 'write_new', side_effect=fail):
            with self.assertRaises(OSError):
                self.resolve()
        self.assertEqual(authoring.source_files(self.app), before)
        self.assertEqual((self.owner / inputs.LOCK).read_bytes(), accepted)
        self.assertEqual(authoring.status(self.owner)['status'], 'verified')

    def test_rollback_preserves_concurrent_user_native_edit(self):
        original = authoring.paths.write_new
        def fail(path, raw):
            if path == self.candidate:
                (self.app / native.LOCK).write_bytes(b'concurrent user lock edit')
                raise OSError('modelled failure after user edit')
            return original(path, raw)
        with patch.object(authoring.paths, 'write_new', side_effect=fail):
            with self.assertRaises(OSError):
                self.resolve()
        self.assertEqual((self.app / native.LOCK).read_bytes(), b'concurrent user lock edit')
        self.assertFalse((self.app / native.ASSETS).exists())
        self.assertFalse((self.owner / inputs.MANIFEST).exists())

    def test_sdk_drift_between_publications_rolls_back_owned_graph_bytes(self):
        original = authoring.replace
        def replace(owner, private, name, raw, previous, sdk):
            original(owner, private, name, raw, previous, sdk)
            if name == native.LOCK:
                (self.app / 'vendor/lsf/sdk/dotnet-guest/global.json').write_bytes(b'concurrent SDK edit')
        with patch.object(authoring, 'replace', side_effect=replace):
            with self.assertRaisesRegex(ValueError, 'vendored SDK changed'):
                self.resolve()
        for name in (native.LOCK, native.ASSETS, inputs.MANIFEST, inputs.LOCK):
            self.assertFalse((self.owner / name).exists())
        self.assertEqual((self.app / 'vendor/lsf/sdk/dotnet-guest/global.json').read_bytes(), b'concurrent SDK edit')

    def test_delivered_recipe_includes_dependency_owner_and_frontend_input_closure(self):
        from tools.dev_tool_distribution import recipe
        payload = self.root / 'payload'
        recipe(payload, 'dotnet')
        for name in ('dotnet_dependency_authoring.py', 'dotnet_application_dependencies.py',
                     'guest_authoring_frontend.py', 'dev_workflow/state.py'):
            self.assertTrue((payload / 'recipe/tools' / name).is_file(), name)

    def test_candidate_cannot_overwrite_any_source_or_existing_attempt(self):
        for target in (self.app / native.PROJECT, self.app / 'src/new.cs', self.owner / inputs.LOCK):
            with self.assertRaisesRegex(DependencyError, 'cannot-overwrite-reviewed-input'):
                native.resolve(self.owner, target, dotnet=self.dotnet, tools=self.tools)
        self.candidate.parent.mkdir(); self.candidate.write_bytes(b'previous candidate')
        with self.assertRaisesRegex(DependencyError, 'candidate-exists'):
            self.resolve()
        self.assertEqual(self.candidate.read_bytes(), b'previous candidate')
        self.assertEqual(self.calls, [])

    def test_missing_or_tampered_transitive_original_blocks_review(self):
        lock = self.resolve()
        child = next(row for row in lock['artifacts'] if row['id'].startswith('outside.child/'))
        store = Store(self.owner / 'dependency-inputs/objects')
        store.path(child['original']['digest']).write_bytes(b'tampered original archive')
        with self.assertRaisesRegex(DependencyError, 'artifact-integrity'):
            authoring.review(self.owner, self.candidate, digest(self.candidate.read_bytes()))
        self.assertFalse((self.owner / inputs.LOCK).exists())

    def test_native_review_checks_actual_original_format_mount_size_and_edges(self):
        lock = self.resolve()
        files = authoring.source_files(self.app)
        native_lock = json.loads(files[native.LOCK])
        graph = json.loads(files[native.ASSETS])
        for field, value in [('format', 'directory'), ('mount', 'dependencies/other'),
                             ('original', {'digest': lock['artifacts'][1]['original']['digest'], 'size': 1}),
                             ('dependencies', [])]:
            artifacts = copy.deepcopy(lock['artifacts'])
            artifacts[1][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(DependencyError, 'not-native-original'):
                native.validate_selection(files, lock['selection'], native_lock, graph, artifacts)

    def test_declaration_change_invalidates_accepted_graph_until_new_resolution_review(self):
        self.accept()
        accepted = (self.owner / inputs.LOCK).read_bytes()
        authoring.edit(self.owner, 'update', identity='Outside.Library', version='2.0.0')
        with self.assertRaisesRegex(DependencyError, 'native-lock-drift'):
            authoring.status(self.owner)
        self.assertEqual((self.owner / inputs.LOCK).read_bytes(), accepted)

    def test_sdk_or_descriptor_drift_blocks_transaction(self):
        sdk_source = self.app / 'vendor/lsf/sdk/dotnet-guest/global.json'
        sdk_source.write_bytes(b'mutated compiler version')
        with self.assertRaisesRegex(ValueError, 'vendored SDK changed'):
            authoring.edit(self.owner, 'remove', identity='Outside.Library')
        self.assertEqual((self.app / 'sdk-lock.json').read_bytes(), self.sdk)

    def test_cli_failure_receipt_redacts_untrusted_native_error_and_does_not_retry(self):
        stderr = io.StringIO()
        with patch.object(native, 'resolve', side_effect=RuntimeError('PRIVATE_TOKEN=external diagnostic')) as resolve, \
                redirect_stderr(stderr), redirect_stdout(io.StringIO()):
            code = dotnet_capsule.main(['resolve', str(self.owner), '--candidate', str(self.candidate),
                '--dotnet', str(self.dotnet), '--tools', str(self.tools)])
        self.assertEqual(code, 1); self.assertEqual(resolve.call_count, 1)
        evidence = json.loads(stderr.getvalue())
        self.assertFalse(evidence['automaticReplay'])
        self.assertNotIn('PRIVATE_TOKEN', stderr.getvalue())
        self.assertTrue(self.candidate.with_name(self.candidate.name + '.failed.json').exists())

    def test_normal_frontend_test_watch_arguments_preserve_selections_and_uncertain_exit(self):
        self.nested(); self.accept()
        test = authoring.frontend(self.app, 'test', workspace='owned-workspace', selections=('greeting',), environment='portable')
        self.assertEqual(test[-4:], ['--environment', 'portable', '--select', 'greeting'])
        watch = authoring.frontend(self.app, 'watch', workspace='owned-workspace', tool_root='frozen', selections=('greeting',))
        self.assertIn('--watch', watch); self.assertEqual(watch[-2:], ['--test-select', 'greeting'])
        from tools import guest_authoring_frontend
        outcome = Outcome(5, {'status': 'frontend-uncertain', 'uncertain': True, 'automaticReplay': False})
        with patch.object(guest_authoring_frontend, 'execute', return_value=outcome) as execute, \
                patch.object(guest_authoring_frontend, 'emit'):
            self.assertEqual(dotnet_capsule.main(['watch', str(self.app), '--workspace', 'owned-workspace']), 5)
        self.assertEqual(execute.call_count, 1)
