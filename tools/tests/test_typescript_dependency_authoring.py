"""Real npm capture/review controls with deliberately modelled Node boundaries."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import importlib
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import application_dependencies as inputs, guest_authoring_frontend as frontend
from tools import typescript_application_dependencies as native, typescript_capsule
from tools import typescript_dependency_authoring as authoring
from tools.application_dependency_store import DependencyError, Store
from tools.build_snapshot import canonical, digest
from tools.dev_workflow import cli, common, project as dev_project
from tools.dev_tool_distribution import recipe
from tools.tests.test_dev_contracts import descriptor
from tools.typescript_guest import project


class Output(io.StringIO):
    @property
    def buffer(self):
        return self

    def write(self, value):
        return super().write(value.decode('utf-8') if isinstance(value, bytes) else value)


class NpmDependencyAuthoring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix='npm-authoring-source-')
        cls.addClassCleanup(temporary.cleanup)
        cls.original = project.snapshot(project.create(Path(temporary.name) / 'app', 'greeting'))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='npm-authoring-control-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.owner = self.root / 'project'
        self.app = self.owner
        self.copy_application(self.app, self.original)
        self.sdk = (self.app / 'sdk-lock.json').read_bytes()
        self.library, self.child = self.root / 'outside', self.root / 'transitive'
        for path, name in ((self.library, 'outside-module'), (self.child, 'transitive-module')):
            path.mkdir()
            value = {'name': name, 'version': '1.0.0', 'license': 'MIT', 'type': 'module',
                     'exports': {'import': './index.mjs', 'require': './index.cjs'}}
            if path == self.library:
                value.update(dependencies={'transitive-module': 'file:../transitive'},
                             scripts={'prepare': 'node forbidden.cjs'})
            (path / 'package.json').write_bytes(canonical(value))
            (path / 'index.mjs').write_bytes(b'export const value = 42;\n')
            (path / 'index.cjs').write_bytes(b'exports.value = 42;\n')
        (self.library / 'forbidden.cjs').write_bytes(b'throw new Error("implicit package hooks are forbidden");\n')
        (self.child / 'greeting.txt').write_bytes(b'original immutable resource')
        self.node, self.npm = self.root / 'node-model-only', self.root / 'npm-model-only.js'
        for path in (self.node, self.npm):
            path.write_bytes(b'not executable: Node/npm process outputs are modelled in source controls')
        self.calls = []
        self.select()

    def copy_application(self, target, files):
        target.mkdir()
        for name, raw in files.items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)

    def select(self, libraries=True):
        value = {'name': 'my-greeting', 'version': '1.0.0', 'private': True, 'type': 'module'}
        packages = {'': {}}
        if libraries:
            value['dependencies'] = {'outside-module': 'file:' + str(self.library)}
            packages = {'': {'dependencies': value['dependencies']},
                'node_modules/outside-module': {'version': '1.0.0', 'resolved': 'file:' + str(self.library),
                    'dependencies': {'transitive-module': 'file:' + str(self.child)}},
                'node_modules/transitive-module': {'version': '1.0.0', 'resolved': 'file:' + str(self.child)}}
        (self.app / 'package.json').write_bytes(canonical(value))
        (self.app / 'package-lock.json').write_bytes(canonical({'lockfileVersion': 3, 'packages': packages}))

    def nested(self):
        current = authoring.source_files(self.app)
        self.owner = self.root / 'nested-project'
        self.owner.mkdir()
        self.app = self.owner / 'app'
        self.copy_application(self.app, current)
        value = descriptor()
        value.update(language='typescript', inputRoots=['app'])
        value['template']['ownerIssue'] = dev_project.LANGUAGES['typescript']
        value['build']['workingDirectory'] = 'app'
        (self.owner / 'latent.project.json').write_bytes(common.encode(value))

    def resolver_command(self, command, cwd, environment, seconds, maximum):
        self.calls.append((list(command), Path(cwd), dict(environment), seconds, maximum))
        if command[1:] == ['--version']:
            raw = b'v24.19.0\n'
        elif command[-1] == '--version':
            raw = b'11.6.0\n'
        elif command[1:] == ['-p', 'process.arch']:
            raw = b'x64\n'
        elif command[2] == 'ci':
            self.assertIn('--ignore-scripts', command)
            self.assertIn('--bin-links=false', command)
            self.assertIn('--strict-peer-deps', command)
            locked = json.loads((Path(cwd) / 'package-lock.json').read_bytes())
            for name, row in locked['packages'].items():
                if not name:
                    continue
                original = Path(row['resolved'].removeprefix('file:'))
                shutil.copytree(original, Path(cwd) / name)
            raw = b''
        else:
            self.fail('unexpected native boundary: ' + repr(command))
        return subprocess.CompletedProcess(command, 0, raw, b'')

    def call(self, *arguments, module=typescript_capsule):
        out, err = Output(), Output()
        with redirect_stdout(out), redirect_stderr(err):
            code = module.main([str(value) for value in arguments])
        return code, out.getvalue(), err.getvalue()

    def capture(self, **kwargs):
        candidate = self.root / ('candidate-' + secrets.token_hex(8) + '.json')
        with patch.object(native, 'run_bounded', side_effect=self.resolver_command):
            locked = native.resolve(self.owner, candidate, node=self.node, npm=self.npm, **kwargs)
        return candidate, locked

    def reviewed(self):
        candidate, lock = self.capture()
        result = authoring.review(self.owner, candidate, digest(candidate.read_bytes()))
        return candidate, lock, result

    def test_exact_capture_review_and_offline_resource_after_originals_are_removed(self):
        _candidate, lock, result = self.reviewed()
        shutil.rmtree(self.library); shutil.rmtree(self.child)
        work, output = self.root / 'work', self.root / 'output'
        work.mkdir(); output.mkdir()
        with patch.object(inputs, 'fetch', side_effect=AssertionError('offline review contacted upstream')):
            status = authoring.status(self.owner)
            closure = inputs.prepare(self.owner, work, output, 'typescript')
            selected = native.bundle_configuration(closure)
            closure.check_unchanged()
        self.assertEqual(status['capturedInputIdentity'], result['capturedInputIdentity'])
        self.assertEqual((work / selected['moduleRoot'] / 'transitive-module/greeting.txt').read_bytes(),
                         b'original immutable resource')
        self.assertEqual(len(lock['artifacts']), 3)
        self.assertFalse(result['compilerExecution'])
        self.assertEqual((self.app / 'sdk-lock.json').read_bytes(), self.sdk)

    def test_cli_emits_a_fresh_candidate_receipt_then_requires_exact_review(self):
        candidate = self.root / 'cli-candidate.json'
        with patch.object(native, 'run_bounded', side_effect=self.resolver_command):
            code, out, err = self.call('resolve', self.owner, '--candidate', candidate, '--node', self.node, '--npm', self.npm)
        self.assertEqual((code, err), (0, ''))
        self.assertTrue(json.loads(out)['reviewRequired'])
        self.assertFalse((self.owner / inputs.LOCK).exists())
        self.assertTrue(candidate.with_name(candidate.name + '.receipt.json').is_file())
        code, _out, err = self.call('review-lock', self.owner, '--candidate', candidate, '--expect', 'sha256:' + '0' * 64)
        self.assertEqual(code, 1); self.assertIn('npm-candidate-review-drift', err)
        code, out, err = self.call('review-lock', self.owner, '--candidate', candidate, '--expect', digest(candidate.read_bytes()))
        self.assertEqual((code, err), (0, '')); self.assertEqual(json.loads(out)['status'], 'reviewed')
        self.assertEqual(self.call('dependencies', self.owner)[0], 0)

    def test_update_and_remove_preserve_old_lock_until_each_exact_review(self):
        self.reviewed()
        old_lock = (self.owner / inputs.LOCK).read_bytes()
        (self.child / 'greeting.txt').write_bytes(b'updated resource')
        candidate, new_lock = self.capture()
        self.assertEqual((self.owner / inputs.LOCK).read_bytes(), old_lock)
        self.assertNotEqual(json.loads(old_lock)['manifestDigest'], new_lock['manifestDigest'])
        with self.assertRaises(DependencyError): authoring.status(self.owner)
        authoring.review(self.owner, candidate, digest(candidate.read_bytes()))
        updated = (self.owner / inputs.LOCK).read_bytes()
        self.select(libraries=False)
        candidate, lock = self.capture()
        self.assertEqual((self.owner / inputs.LOCK).read_bytes(), updated)
        authoring.review(self.owner, candidate, digest(candidate.read_bytes()))
        self.assertEqual(len(lock['artifacts']), 1)
        self.assertEqual(authoring.status(self.owner)['status'], 'verified')
        self.assertEqual((self.app / 'sdk-lock.json').read_bytes(), self.sdk)

    def test_native_inputs_candidate_and_cached_object_tampering_never_replace_reviewed_lock(self):
        candidate, lock, _result = self.reviewed()
        accepted = (self.owner / inputs.LOCK).read_bytes()
        for name in ('package.json', 'package-lock.json', 'npm-resolved.lock.json'):
            path = self.app / name; before = path.read_bytes(); path.write_bytes(before + b' ')
            with self.subTest(name=name), self.assertRaises(DependencyError):
                authoring.review(self.owner, candidate, digest(candidate.read_bytes()))
            path.write_bytes(before)
            self.assertEqual((self.owner / inputs.LOCK).read_bytes(), accepted)
        candidate.write_bytes(candidate.read_bytes() + b' ')
        with self.assertRaisesRegex(DependencyError, 'review-drift'):
            authoring.review(self.owner, candidate, digest(accepted))
        module = next(row for row in lock['artifacts'] if row['metadata'].get('assetType') == 'selected-node-modules')
        data = module['files'][0]
        Store(self.owner / 'dependency-inputs/objects').path(data['digest']).write_bytes(b'tampered')
        with self.assertRaises(DependencyError): authoring.status(self.owner)
        self.assertEqual((self.owner / inputs.LOCK).read_bytes(), accepted)

    def test_sdk_drift_is_rejected_before_any_resolver_operation(self):
        path = self.app / 'vendor/lsf/tools/toolchain.toml'
        path.write_bytes(path.read_bytes() + b'\n# unreviewed drift\n')
        with self.assertRaisesRegex(ValueError, 'vendored SDK changed'):
            self.capture()
        self.assertEqual(self.calls, [])
        self.assertFalse((self.owner / inputs.MANIFEST).exists())

    def test_source_sdk_node_npm_and_registry_drift_during_resolution_fail_before_acceptance(self):
        for path in (self.app / 'src/main.ts', self.app / 'vendor/lsf/tools/toolchain.toml', self.node, self.npm):
            before = path.read_bytes()
            def mutate(*arguments):
                result = self.resolver_command(*arguments)
                if arguments[0][1:] == ['-p', 'process.arch']:
                    path.write_bytes(before + b'changed')
                return result
            candidate = self.root / ('drift-' + secrets.token_hex(8) + '.json')
            with self.subTest(path=path.name), patch.object(native, 'run_bounded', side_effect=mutate), self.assertRaises((DependencyError, ValueError)):
                native.resolve(self.owner, candidate, node=self.node, npm=self.npm)
            path.write_bytes(before)
            self.assertFalse(candidate.exists())
            self.assertFalse((self.owner / inputs.MANIFEST).exists())

    def test_failed_cli_redacts_resolver_secret_and_retains_separate_failed_receipt(self):
        candidate = self.root / 'failed.json'
        with patch.object(native, 'run_bounded', side_effect=RuntimeError('https://token:private-secret@example.invalid')):
            code, out, err = self.call('resolve', self.owner, '--candidate', candidate, '--node', self.node, '--npm', self.npm)
        self.assertEqual(code, 1); self.assertEqual(out, '')
        self.assertNotIn('private-secret', err)
        self.assertEqual(json.loads(err)['reason'], 'npm-authoring-invalid-or-unavailable-input')
        self.assertFalse(candidate.exists())
        self.assertTrue(candidate.with_name(candidate.name + '.failed.json').is_file())
        self.assertNotIn(b'private-secret', candidate.with_name(candidate.name + '.failed.json').read_bytes())

    def test_candidate_reuse_and_source_locations_cannot_overwrite_originals_or_receipts(self):
        candidate, _lock = self.capture()
        before = candidate.read_bytes()
        with self.assertRaisesRegex(DependencyError, 'candidate-exists'):
            native.resolve(self.owner, candidate, node=self.node, npm=self.npm)
        self.assertEqual(candidate.read_bytes(), before)
        for unsafe in (self.app / 'package.json', self.library / 'candidate.json',
                       self.app / 'target/../package.json'):
            with self.subTest(path=unsafe), patch.object(native, 'run_bounded', side_effect=self.resolver_command):
                code, _out, err = self.call('resolve', self.owner, '--candidate', unsafe, '--node', self.node, '--npm', self.npm)
            self.assertEqual(code, 1)
            self.assertFalse(unsafe.with_name(unsafe.name + '.failed.json').exists())
            self.assertIn('candidate-', err)
        receipt = self.root / 'existing-receipt.json.receipt.json'; receipt.write_bytes(b'keep original evidence')
        code, _out, err = self.call('resolve', self.owner, '--candidate', self.root / 'existing-receipt.json',
                                  '--node', self.node, '--npm', self.npm)
        self.assertEqual(code, 1); self.assertIn('fresh-attempt', err)
        self.assertEqual(receipt.read_bytes(), b'keep original evidence')

    def test_private_registry_policy_uses_only_explicit_env_and_keeps_public_outcomes_secret_free(self):
        config = self.root / 'private-registries.json'
        config.write_bytes(canonical({'registries': [{'scope': '@team', 'url': 'https://private.example.invalid/npm/',
            'authorizationEnv': 'APP_REGISTRY_TOKEN'}]}))
        with patch.dict(os.environ, {'APP_REGISTRY_TOKEN': 'resolver-only-secret', 'UNRELATED_PRODUCTION_TOKEN': 'omit-me'}):
            candidate, lock = self.capture(registry_config=config)
        for _command, _cwd, environment, _seconds, _maximum in self.calls:
            self.assertEqual(environment['LSF_NPM_REGISTRY_TOKEN_0'], 'resolver-only-secret')
            self.assertNotIn('APP_REGISTRY_TOKEN', environment)
            self.assertNotIn('UNRELATED_PRODUCTION_TOKEN', environment)
            self.assertEqual(environment['GIT_TERMINAL_PROMPT'], '0')
            self.assertNotIn(str(self.app), environment['HOME'])
        result = authoring.resolved(self.owner, candidate, lock)
        self.assertNotIn(b'resolver-only-secret', canonical(lock))
        self.assertNotIn(b'resolver-only-secret', canonical(result))
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(DependencyError, 'authorization-unavailable'):
            self.capture(registry_config=config)
        inside = self.app / 'registry.json'; inside.write_bytes(config.read_bytes())
        with self.assertRaisesRegex(DependencyError, 'stay-outside-project'):
            self.capture(registry_config=inside)

    def test_private_registry_changed_bytes_and_project_npmrc_fail_closed(self):
        config = self.root / 'registries.json'; config.write_bytes(canonical({'registries': []}))
        def mutate(*arguments):
            result = self.resolver_command(*arguments)
            if arguments[0][1:] == ['-p', 'process.arch']: config.write_bytes(b'{}')
            return result
        candidate = self.root / 'config-drift.json'
        with patch.object(native, 'run_bounded', side_effect=mutate), self.assertRaisesRegex(DependencyError, 'input-mutated'):
            native.resolve(self.owner, candidate, node=self.node, npm=self.npm, registry_config=config)
        self.assertFalse(candidate.exists())
        (self.app / '.npmrc').write_bytes(b'//private.example.invalid/:_authToken=must-not-copy\n')
        with self.assertRaisesRegex(DependencyError, 'explicit-registry-policy'):
            self.capture()
        self.assertFalse((self.owner / inputs.MANIFEST).exists())

    def test_authorization_variable_cannot_restore_node_loader_or_home_overrides(self):
        config = self.root / 'loader-looking-token.json'
        config.write_bytes(canonical({'registries': [{'url': 'https://private.example.invalid/npm/',
            'authorizationEnv': 'NODE_OPTIONS'}]}))
        token = '--require /outside/forbidden-initializer.cjs'
        with patch.dict(os.environ, {'NODE_OPTIONS': token}):
            candidate, lock = self.capture(registry_config=config)
        for _command, _cwd, environment, _seconds, _maximum in self.calls:
            self.assertNotIn('NODE_OPTIONS', environment)
            self.assertEqual(environment['LSF_NPM_REGISTRY_TOKEN_0'], token)
            self.assertNotEqual(environment['HOME'], token)
        self.assertNotIn(token.encode(), canonical(authoring.resolved(self.owner, candidate, lock)))

    def test_selected_conditions_are_reviewed_without_changing_installed_runtime_profile(self):
        candidate, lock = self.capture(selected={'conditions': ['private', 'private']})
        result = authoring.review(self.owner, candidate, digest(candidate.read_bytes()))
        self.assertEqual(lock['selection']['conditions'], ['private'])
        self.assertEqual(result['selection']['runtimeProfile'], 'spidermonkey-public-sync-v1')
        with self.assertRaisesRegex(DependencyError, 'profile-not-installed'):
            self.capture(selected={'runtimeProfile': 'pending-promises'})

    def test_outer_and_application_entries_bind_exact_native_paths_and_descriptor(self):
        self.nested()
        candidate, lock, _result = self.reviewed()
        self.assertEqual([row['path'] for row in lock['nativeLocks']],
            ['app/package.json', 'app/package-lock.json', 'app/npm-resolved.lock.json'])
        self.assertFalse((self.app / inputs.MANIFEST).exists())
        self.assertFalse((self.app / inputs.LOCK).exists())
        self.assertEqual(authoring.status(self.app)['capturedInputIdentity'], authoring.status(self.owner)['capturedInputIdentity'])
        descriptor_bytes = (self.owner / 'latent.project.json').read_bytes()
        old = (self.owner / inputs.LOCK).read_bytes()
        (self.app / 'latent.project.json').write_bytes(descriptor_bytes)
        for selected in (self.owner, self.app):
            with self.subTest(selected=selected), self.assertRaisesRegex(DependencyError, 'ambiguous-project-descriptor'):
                authoring.review(selected, candidate, digest(candidate.read_bytes()))
        self.assertEqual((self.owner / inputs.LOCK).read_bytes(), old)

    def test_nested_dependency_lock_and_test_watch_shadow_are_denied_before_dispatch(self):
        self.nested(); self.reviewed()
        shadow = self.app / inputs.LOCK; shadow.write_bytes(b'{}')
        with self.assertRaisesRegex(DependencyError, 'ambiguous-application-lock'): authoring.status(self.owner)
        shadow.unlink()
        (self.app / 'latent.project.json').write_bytes((self.owner / 'latent.project.json').read_bytes())
        with patch.object(cli, 'main', return_value=0) as dispatched:
            for action in ('test', 'watch'):
                self.assertEqual(self.call(action, self.owner, '--workspace', 'demo')[0], 1)
        dispatched.assert_not_called()

    def test_atomic_review_rejects_a_concurrent_candidate_change_without_partial_lock(self):
        candidate, _lock = self.capture()
        original = authoring.current_application
        def mutate(app, lock):
            original(app, lock)
            candidate.write_bytes(candidate.read_bytes() + b' ')
        with patch.object(authoring, 'current_application', side_effect=mutate), self.assertRaisesRegex(DependencyError, 'concurrent-input-edit'):
            authoring.review(self.owner, candidate, digest(candidate.read_bytes()))
        self.assertFalse((self.owner / inputs.LOCK).exists())

    def test_invalid_graph_inventory_and_missing_native_input_do_not_accept_candidate(self):
        candidate, _lock = self.capture()
        graph = self.app / 'npm-resolved.lock.json'
        original = graph.read_bytes()
        for change in ({'formatVersion': True}, {'filesDigest': 'sha256:' + '0' * 64}):
            value = json.loads(original); value.update(change); graph.write_bytes(canonical(value))
            # Even a fresh capture of those edits cannot claim a matching graph.
            candidate_lock = json.loads(candidate.read_bytes())
            reference = Store(self.owner / 'dependency-inputs/objects').put(graph.read_bytes())
            next(row for row in candidate_lock['nativeLocks'] if row['path'] == 'npm-resolved.lock.json').update(reference)
            checked = self.root / ('modified-' + secrets.token_hex(8) + '.json'); checked.write_bytes(canonical(candidate_lock))
            with self.subTest(change=change), self.assertRaisesRegex(DependencyError, 'native-graph-or-declaration-drift'):
                authoring.review(self.owner, checked, digest(checked.read_bytes()))
        graph.write_bytes(original)
        (self.app / 'package-lock.json').unlink()
        with self.assertRaises((DependencyError, FileNotFoundError)):
            authoring.review(self.owner, candidate, digest(candidate.read_bytes()))
        self.assertFalse((self.owner / inputs.LOCK).exists())

    def test_unreviewed_resolution_cannot_be_rebound_into_a_success_receipt(self):
        candidate, lock = self.capture()
        declaration = self.app / 'package.json'; declaration.write_bytes(declaration.read_bytes() + b' ')
        with self.assertRaisesRegex(DependencyError, 'native-lock-drift'):
            authoring.resolved(self.owner, candidate, lock)

    def test_test_and_watch_use_maintained_parser_and_preserve_uncertain_receipt_failure(self):
        self.nested(); self.reviewed()
        with patch.object(cli, 'main', return_value=5) as dispatched, patch.object(authoring, 'record', side_effect=OSError('receipt unavailable')):
            for action in ('test', 'watch'):
                code, _out, err = self.call(action, self.app, '--workspace', 'demo', '--select', 'greeting')
                self.assertEqual(code, 5); self.assertIn('inspect workspace status', err)
        self.assertEqual(dispatched.call_count, 2)
        for arguments in dispatched.call_args_list:
            argv = arguments.args[0]
            self.assertEqual(cli.parser().parse_args(argv).project, self.owner)
            self.assertEqual(argv.count(str(self.owner)), 1)
        with patch.object(cli, 'main', return_value=130):
            self.assertEqual(self.call('watch', self.owner, '--workspace', 'demo')[0], 130)

    def test_symbolic_local_dependency_is_rejected_before_native_dispatch(self):
        if os.name != 'posix': self.skipTest('POSIX symbolic-link fixture; Windows reparse controls are separate')
        linked = self.root / 'linked-library'; linked.symlink_to(self.library, target_is_directory=True)
        locked = json.loads((self.app / 'package-lock.json').read_bytes())
        locked['packages']['node_modules/outside-module']['resolved'] = 'file:' + str(linked)
        (self.app / 'package-lock.json').write_bytes(canonical(locked))
        with self.assertRaisesRegex(DependencyError, 'link-denied'): self.capture()
        self.assertEqual(self.calls, [])

    @contextmanager
    def staged_tools(self):
        payload = self.root / 'staged'; payload.mkdir(); recipe(payload, 'typescript')
        source = payload / 'recipe'
        saved = {name: value for name, value in sys.modules.items() if name == 'tools' or name.startswith('tools.')}
        for name in saved: sys.modules.pop(name)
        sys.path.insert(0, str(source))
        try:
            yield source
        finally:
            for name in tuple(sys.modules):
                if name == 'tools' or name.startswith('tools.'): sys.modules.pop(name)
            sys.modules.update(saved)
            sys.path.remove(str(source))

    def test_actual_staged_recipe_captures_reviews_verifies_and_requires_explicit_frontend(self):
        self.nested()
        candidate = self.root / 'staged-candidate.json'
        executable = Path(sys.executable).resolve(strict=True)
        with self.staged_tools() as source:
            staged = importlib.import_module('tools.typescript_capsule')
            captured = importlib.import_module('tools.typescript_application_dependencies')
            wrapper = importlib.import_module('tools.guest_authoring_frontend')
            self.assertTrue(Path(staged.__file__).is_relative_to(source))
            with patch.object(captured, 'run_bounded', side_effect=self.resolver_command):
                self.assertEqual(self.call('resolve', self.app, '--candidate', candidate, '--node', self.node, '--npm', self.npm, module=staged)[0], 0)
            self.assertEqual(self.call('review-lock', self.owner, '--candidate', candidate,
                                      '--expect', digest(candidate.read_bytes()), module=staged)[0], 0)
            self.assertEqual(self.call('dependencies', self.app, module=staged)[0], 0)
            code, _out, err = self.call('test', self.owner, '--workspace', 'demo', module=staged)
            self.assertEqual(code, 1); self.assertIn('requires-explicit-frontend', err)
            result = subprocess.CompletedProcess([], 5, common.encode({'schemaVersion': 'latent.dev.result.v1',
                'code': 'operation-unresolved', 'uncertain': True}), b'')
            with patch.object(wrapper, 'run_bounded_result', return_value=result) as dispatched:
                code, _out, _err = self.call('test', self.owner, '--workspace', 'demo', '--frontend', executable,
                    '--frontend-sha256', digest(executable.read_bytes()), module=staged)
            self.assertEqual(code, 5); dispatched.assert_called_once()


if __name__ == '__main__':
    unittest.main()
