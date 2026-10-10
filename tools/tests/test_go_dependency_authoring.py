"""Actual capture/review/staged controls with deliberately modelled Go commands."""
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
from tools import go_application_dependencies as native, go_capsule, go_capsule_project as project
from tools import go_dependency_authoring as authoring
from tools.application_dependency_store import DependencyError, Store
from tools.build_snapshot import canonical, digest
from tools.dev_tool_distribution import recipe
from tools.dev_workflow import cli, common, project as dev_project
from tools.tests.test_dev_contracts import descriptor


class Output(io.StringIO):
    @property
    def buffer(self):
        return self

    def write(self, value):
        return super().write(value.decode('utf-8') if isinstance(value, bytes) else value)


class GoDependencyAuthoring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix='go-authoring-source-')
        cls.addClassCleanup(temporary.cleanup)
        cls.original = project.snapshot(project.create(Path(temporary.name) / 'app', 'greeting'))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='go-authoring-control-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.owner = self.app = self.root / 'project'
        self.copy_application(self.app, self.original)
        self.sdk = (self.app / 'sdk-lock.json').read_bytes()
        self.library, self.child = self.root / 'outside', self.root / 'transitive'
        self.identities = ['outside.example.test/developer-module', 'outside.example.test/child']
        for path, identity in zip((self.library, self.child), self.identities):
            path.mkdir()
            (path / 'go.mod').write_text('module ' + identity + '\n\ngo 1.27.2\n', encoding='ascii')
            (path / 'value.go').write_bytes(b'package library\nfunc Value() int { return 42 }\n')
        (self.child / 'message.txt').write_bytes(b'captured immutable embedded resource')
        (self.library / 'generate.go').write_bytes(b'//go:generate forbidden-generator\npackage library\n')
        self.go = self.root / 'go-command-model-only'
        self.go.write_bytes(b'Not executable: source tests model Go command output')
        self.calls = []
        self.select()

    def copy_application(self, target, files):
        target.mkdir()
        for name, raw in files.items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)

    def select(self, libraries=True):
        self.main = 'application.example.test/source'
        self.declaration = {'Module': {'Path': self.main}, 'Go': '1.27.2', 'Require': [], 'Replace': [], 'Exclude': []}
        text = 'module ' + self.main + '\n\ngo 1.27.2\n'
        if libraries:
            for identity, location in zip(self.identities, (self.library, self.child)):
                self.declaration['Require'].append({'Path': identity, 'Version': 'v0.0.0'})
                self.declaration['Replace'].append({'Old': {'Path': identity}, 'New': {'Path': str(location)}})
                text += '\nrequire ' + identity + ' v0.0.0\nreplace ' + identity + ' => ' + str(location) + '\n'
        (self.app / 'go.mod').write_text(text, encoding='utf-8')
        (self.app / 'go.sum').write_bytes(b'')

    def nested(self):
        self.owner = self.root / 'nested-project'
        self.owner.mkdir()
        self.app = self.owner / 'app'
        self.copy_application(self.app, authoring.source_files(self.root / 'project'))
        value = descriptor()
        value.update(language='go', inputRoots=['app'])
        value['template']['ownerIssue'] = dev_project.LANGUAGES['go']
        value['build']['workingDirectory'] = 'app'
        (self.owner / 'latent.project.json').write_bytes(common.encode(value))

    def resolver_command(self, command, cwd, environment, seconds, maximum):
        self.calls.append((list(command), Path(cwd), dict(environment), seconds, maximum))
        self.assertEqual(environment['GOTOOLCHAIN'], 'local')
        self.assertEqual(environment['GOWORK'], 'off')
        self.assertEqual(environment['GOENV'], 'off')
        self.assertEqual(environment['CGO_ENABLED'], '0')
        self.assertEqual(environment['GOFLAGS'], '-mod=readonly')
        self.assertEqual(environment['GIT_TERMINAL_PROMPT'], '0')
        self.assertEqual(Path(environment['GIT_CONFIG_GLOBAL']).read_bytes(), b'')
        arguments = command[1:]
        if arguments == ['version']:
            raw = b'go version go1.27.2 linux/amd64\n'
        elif arguments == ['mod', 'edit', '-json']:
            raw = canonical(self.declaration)
        elif arguments[:2] == ['mod', 'edit'] and arguments[2].startswith('-replace='):
            name, destination = arguments[2].removeprefix('-replace=').split('=', 1)
            identity = name.partition('@')[0]
            original = next(row['New']['Path'] for row in self.declaration['Replace'] if row['Old']['Path'] == identity)
            path = Path(cwd) / 'go.mod'
            path.write_text(path.read_text().replace('=> ' + original, '=> ' + destination), encoding='utf-8')
            raw = b''
        elif arguments == ['list', '-m', '-json', 'all']:
            rows = [{'Path': self.main, 'Main': True, 'GoVersion': '1.27.2'}]
            text = (Path(cwd) / 'go.mod').read_text()
            for row in self.declaration['Replace']:
                identity = row['Old']['Path']
                location = next(line.partition(' => ')[2] for line in text.splitlines() if line.startswith('replace ' + identity + ' => '))
                rows.append({'Path': identity, 'Version': 'v0.0.0', 'GoVersion': '1.27.2',
                             'Replace': {'Path': location, 'Dir': location}})
            raw = b'\n'.join(canonical(row) for row in rows)
        elif arguments == ['mod', 'download', '-json', 'all']:
            raw = b''
        elif arguments == ['mod', 'graph']:
            edges = [self.main + ' ' + row['Path'] + '@' + row['Version'] for row in self.declaration['Require']]
            if len(self.declaration['Require']) == 2:
                edges.append(self.identities[0] + '@v0.0.0 ' + self.identities[1] + '@v0.0.0')
            raw = ('\n'.join(edges) + ('\n' if edges else '')).encode()
        else:
            self.fail('unexpected native process boundary: ' + repr(command))
        return subprocess.CompletedProcess(command, 0, raw, b'')

    def capture(self, **kwargs):
        candidate = self.root / ('candidate-' + secrets.token_hex(8) + '.json')
        with patch.object(native, 'run_bounded', side_effect=self.resolver_command):
            lock = native.resolve(self.owner, candidate, go=self.go, **kwargs)
        return candidate, lock

    def reviewed(self):
        candidate, lock = self.capture()
        result = authoring.review(self.owner, candidate, digest(candidate.read_bytes()))
        return candidate, lock, result

    def call(self, *arguments, module=go_capsule):
        out, err = Output(), Output()
        with redirect_stdout(out), redirect_stderr(err):
            code = module.main([str(value) for value in arguments])
        return code, out.getvalue(), err.getvalue()

    def test_exact_local_graph_and_resource_review_work_after_originals_are_removed(self):
        _candidate, lock, result = self.reviewed()
        shutil.rmtree(self.library); shutil.rmtree(self.child)
        work, output, generated = self.root / 'work', self.root / 'output', self.root / 'generated'
        for directory in (work, output, generated): directory.mkdir()
        for name in ('go.sum', 'go-resolved.lock.json'):
            (work / name).write_bytes((self.app / name).read_bytes())
        with patch.object(inputs, 'fetch', side_effect=AssertionError('offline review contacted upstream')):
            status = authoring.status(self.owner)
            closure = inputs.prepare(self.owner, work, output, 'go')
            selected = native.configure(closure, generated)
            closure.check_unchanged()
        child = next(row for row in lock['artifacts'] if row['metadata'].get('module') == self.identities[1])
        self.assertEqual((generated / child['mount'] / 'message.txt').read_bytes(), b'captured immutable embedded resource')
        self.assertEqual(status['capturedInputIdentity'], result['capturedInputIdentity'])
        self.assertEqual(selected['runtimeProfile'], 'go-component-async-v1')
        self.assertEqual(selected['generators'], 'never-executed')
        self.assertEqual((self.app / 'sdk-lock.json').read_bytes(), self.sdk)

    def test_resolve_preserves_each_accepted_lock_until_exact_update_and_remove_review(self):
        _candidate, _lock, _result = self.reviewed()
        previous = (self.owner / inputs.LOCK).read_bytes()
        (self.child / 'message.txt').write_bytes(b'updated captured bytes')
        candidate, _lock = self.capture()
        self.assertEqual((self.owner / inputs.LOCK).read_bytes(), previous)
        authoring.review(self.owner, candidate, digest(candidate.read_bytes()))
        updated = (self.owner / inputs.LOCK).read_bytes()
        self.assertNotEqual(updated, previous)
        self.select(False)
        candidate, lock = self.capture()
        self.assertEqual((self.owner / inputs.LOCK).read_bytes(), updated)
        authoring.review(self.owner, candidate, digest(candidate.read_bytes()))
        self.assertFalse(any(row['metadata'].get('assetType') == 'local-module' for row in lock['artifacts']))

    def test_candidate_expected_digest_and_native_input_tampering_preserve_accepted_lock(self):
        self.reviewed()
        previous = (self.owner / inputs.LOCK).read_bytes()
        candidate, _lock = self.capture()
        with self.assertRaisesRegex(DependencyError, 'candidate-review-drift'):
            authoring.review(self.owner, candidate, 'sha256:' + '0' * 64)
        original = (self.app / 'go.mod').read_bytes()
        (self.app / 'go.mod').write_bytes(original + b'\n')
        with self.assertRaisesRegex(DependencyError, 'native-lock-drift'):
            authoring.review(self.owner, candidate, digest(candidate.read_bytes()))
        self.assertEqual((self.owner / inputs.LOCK).read_bytes(), previous)

    def test_changed_cached_original_bytes_fail_read_only_review(self):
        candidate, lock = self.capture()
        store = Store(self.owner / 'dependency-inputs/objects')
        item = next(row for row in lock['artifacts'] if row['metadata'].get('assetType') == 'local-module')
        store.path(item['files'][0]['digest']).write_bytes(b'changed captured object')
        with self.assertRaises(DependencyError): authoring.review(self.owner, candidate, digest(candidate.read_bytes()))
        self.assertFalse((self.owner / inputs.LOCK).exists())

    def test_sdk_drift_stops_before_any_go_command(self):
        (self.app / 'vendor/lsf/sdk/go-guest/toolchain.lock.json').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'vendored SDK changed'): self.capture()
        self.assertEqual(self.calls, [])

    def test_go_source_sdk_proxy_and_resolver_drift_stop_before_candidate_acceptance(self):
        config = self.root / 'private-proxy.json'
        config.write_bytes(canonical({'proxy': 'https://private.example.test', 'sumdb': 'off'}))
        for target in (self.app / 'src/main.go', self.app / 'vendor/lsf/NOTICE', self.go, config):
            before = target.read_bytes()
            def changed(command, cwd, environment, seconds, maximum):
                result = self.resolver_command(command, cwd, environment, seconds, maximum)
                if command[1:] == ['mod', 'graph']: target.write_bytes(before + b' ')
                return result
            with self.subTest(target=target), patch.object(native, 'run_bounded', side_effect=changed), self.assertRaises(ValueError):
                native.resolve(self.owner, self.root / ('changed-' + secrets.token_hex(8)), go=self.go, proxy_config=config)
            target.write_bytes(before)
        self.assertFalse((self.owner / inputs.LOCK).exists())

    def test_candidate_cannot_overwrite_sources_prior_receipts_or_local_modules(self):
        for target in (self.app / 'go.mod', self.library / 'new-lock.json'):
            with self.subTest(target=target), patch.object(native, 'run_bounded', side_effect=self.resolver_command), self.assertRaises(DependencyError):
                native.resolve(self.owner, target, go=self.go)
        candidate = self.root / 'used.json'
        candidate.with_name(candidate.name + '.failed.json').write_bytes(b'prior failed receipt')
        code, _out, err = self.call('resolve', self.owner, '--candidate', candidate, '--go', self.go)
        self.assertEqual(code, 1); self.assertIn('use-fresh-attempt', err)
        self.assertEqual(candidate.with_name(candidate.name + '.failed.json').read_bytes(), b'prior failed receipt')

    def test_cli_capture_requires_exact_review_and_emits_separate_receipts(self):
        candidate = self.owner / 'target/candidate.json'
        with patch.object(native, 'run_bounded', side_effect=self.resolver_command):
            code, out, _err = self.call('resolve', self.owner, '--candidate', candidate, '--go', self.go)
        self.assertEqual(code, 0); self.assertTrue(json.loads(out)['reviewRequired'])
        self.assertTrue(candidate.with_name(candidate.name + '.receipt.json').is_file())
        self.assertFalse((self.owner / inputs.LOCK).exists())
        self.assertEqual(self.call('review-lock', self.owner, '--candidate', candidate, '--expect', digest(candidate.read_bytes()))[0], 0)
        self.assertEqual(self.call('dependencies', self.owner)[0], 0)

    def test_public_failed_receipts_never_echo_resolver_credentials(self):
        secret = 'private-token-value-never-public'
        candidate = self.owner / 'target/failure.json'; candidate.parent.mkdir()
        with patch.object(native, 'run_bounded', side_effect=RuntimeError(secret)):
            code, out, err = self.call('resolve', self.owner, '--candidate', candidate, '--go', self.go)
        self.assertEqual(code, 1)
        self.assertNotIn(secret, out + err)
        self.assertNotIn(secret.encode(), candidate.with_name(candidate.name + '.failed.json').read_bytes())
        self.assertFalse((self.owner / inputs.LOCK).exists())

    def test_private_proxy_tokens_are_opaque_and_do_not_replace_go_control_environment(self):
        config = self.root / 'private-proxy.json'
        config.write_bytes(canonical({'proxy': 'https://private.example.test', 'sumdb': 'off',
                                     'private': ['outside.example.test/*'], 'authorizationEnv': 'GOTOOLCHAIN'}))
        token = 'untrusted-compiler-selection-token'
        with patch.dict(os.environ, {'GOTOOLCHAIN': token, 'GOFLAGS': '-toolexec=forbidden', 'NETRC': '/foreign/secret'}):
            candidate, lock = self.capture(proxy_config=config)
        for _command, _cwd, environment, _seconds, _maximum in self.calls:
            self.assertEqual(environment['GOTOOLCHAIN'], 'local')
            self.assertEqual(environment['GOFLAGS'], '-mod=readonly')
            self.assertNotEqual(environment['NETRC'], '/foreign/secret')
            self.assertEqual(environment['GONOPROXY'], 'none')
        self.assertNotIn(token.encode(), canonical(authoring.resolved(self.owner, candidate, lock)))

    def test_proxy_config_must_stay_outside_project_and_never_embed_url_credentials(self):
        for location, policy in ((self.app / 'proxy.json', {'proxy': 'https://proxy.example.test', 'sumdb': 'off'}),
                (self.root / 'proxy.json', {'proxy': 'https://name:secret@private.example.test', 'sumdb': 'off'})):
            location.write_bytes(canonical(policy))
            with self.subTest(policy=policy), self.assertRaises(DependencyError): self.capture(proxy_config=location)
        self.assertEqual(self.calls, [])

    def test_tool_declarations_and_wrong_runtime_profile_require_separate_qualified_stage(self):
        self.declaration['Tool'] = [{'Path': 'private.example.test/generator'}]
        with self.assertRaisesRegex(DependencyError, 'executable-tool-declarations'): self.capture()
        self.assertFalse(any(command[1:3] in (['mod', 'download'], ['generate']) for command, *_rest in self.calls))
        with self.assertRaisesRegex(DependencyError, 'profile-not-installed'): self.capture(selected={'runtimeProfile': 'native-go'})

    def test_tags_remain_exact_without_installing_new_runtime_authority(self):
        candidate, lock = self.capture(selected={'tags': ['private', 'private']})
        result = authoring.review(self.owner, candidate, digest(candidate.read_bytes()))
        self.assertEqual(result['selection']['tags'], ['private'])
        self.assertEqual(lock['selection']['runtimeProfile'], 'go-component-async-v1')
        self.assertFalse(result['compilerExecution'])

    def test_outer_and_app_entries_bind_exact_original_and_transformed_module_paths(self):
        self.nested()
        _candidate, lock, _result = self.reviewed()
        self.assertEqual([row['path'] for row in lock['nativeLocks']], ['app/go.mod', 'app/go.sum', 'app/go-resolved.lock.json'])
        self.assertFalse((self.app / inputs.LOCK).exists())
        self.assertEqual(authoring.status(self.owner)['capturedInputIdentity'], authoring.status(self.app)['capturedInputIdentity'])
        self.assertTrue(lock['transformations'])

    def test_inner_descriptor_or_capture_cannot_redirect_test_watch_before_dispatch(self):
        self.nested(); self.reviewed()
        shadow = self.app / inputs.LOCK; shadow.write_bytes(b'{}')
        with self.assertRaisesRegex(DependencyError, 'ambiguous-application-lock'): authoring.status(self.owner)
        shadow.unlink()
        (self.app / 'latent.project.json').write_bytes((self.owner / 'latent.project.json').read_bytes())
        with patch.object(cli, 'main', return_value=0) as dispatched:
            for action in ('test', 'watch'): self.assertEqual(self.call(action, self.app, '--workspace', 'demo')[0], 1)
        dispatched.assert_not_called()

    def test_concurrent_candidate_change_never_replaces_an_accepted_lock(self):
        candidate, _lock = self.capture()
        original = authoring.current_application
        def mutate(app, lock):
            original(app, lock)
            candidate.write_bytes(candidate.read_bytes() + b' ')
        with patch.object(authoring, 'current_application', side_effect=mutate), self.assertRaisesRegex(DependencyError, 'concurrent-input-edit'):
            authoring.review(self.owner, candidate, digest(candidate.read_bytes()))
        self.assertFalse((self.owner / inputs.LOCK).exists())

    def test_consistently_recaptured_invalid_native_graph_never_claims_review_success(self):
        candidate, _lock = self.capture()
        graph = self.app / 'go-resolved.lock.json'; original = graph.read_bytes()
        for change in ({'formatVersion': True}, {'selectedManifestDigest': 'sha256:' + '0' * 64}, {'nodes': []}):
            value = json.loads(original); value.update(change); graph.write_bytes(canonical(value))
            lock = json.loads(candidate.read_bytes())
            next(row for row in lock['nativeLocks'] if row['path'] == 'go-resolved.lock.json').update(Store(self.owner / 'dependency-inputs/objects').put(graph.read_bytes()))
            changed = self.root / ('changed-graph-' + secrets.token_hex(8)); changed.write_bytes(canonical(lock))
            with self.subTest(change=change), self.assertRaises(DependencyError): authoring.review(self.owner, changed, digest(changed.read_bytes()))
        self.assertFalse((self.owner / inputs.LOCK).exists())

    def test_changed_resolution_cannot_be_rebound_as_successful_public_receipt(self):
        candidate, lock = self.capture()
        original = (self.app / 'go.mod').read_bytes()
        (self.app / 'go.mod').write_bytes(original + b'\n')
        with self.assertRaisesRegex(DependencyError, 'native-lock-drift'): authoring.resolved(self.owner, candidate, lock)

    def test_maintained_test_watch_parser_preserves_unknown_and_interrupted_results(self):
        self.nested(); self.reviewed()
        with patch.object(cli, 'main', return_value=5) as dispatched, patch.object(authoring, 'record', side_effect=OSError('unavailable')):
            for action in ('test', 'watch'):
                code, _out, err = self.call(action, self.app, '--workspace', 'demo', '--select', 'greeting')
                self.assertEqual(code, 5); self.assertIn('inspect workspace status', err)
        self.assertEqual(dispatched.call_count, 2)
        for arguments in dispatched.call_args_list: self.assertEqual(cli.parser().parse_args(arguments.args[0]).project, self.owner)
        with patch.object(cli, 'main', return_value=130): self.assertEqual(self.call('watch', self.owner, '--workspace', 'demo')[0], 130)

    def test_symbolic_local_replace_is_denied_before_module_fetch(self):
        if os.name != 'posix': self.skipTest('POSIX symbolic-link fixture; Windows reparse controls are separate')
        linked = self.root / 'linked-module'; linked.symlink_to(self.library, target_is_directory=True)
        self.declaration['Replace'][0]['New']['Path'] = str(linked)
        with self.assertRaisesRegex(DependencyError, 'link-denied'): self.capture()
        self.assertFalse(any(command[1:3] == ['mod', 'download'] for command, *_rest in self.calls))

    @contextmanager
    def staged_tools(self):
        payload = self.root / 'staged'; payload.mkdir(); recipe(payload, 'go')
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

    def test_actual_staged_recipe_resolves_reviews_and_requires_selected_frontend(self):
        self.nested(); candidate = self.root / 'staged-candidate.json'
        executable = Path(sys.executable).resolve(strict=True)
        with self.staged_tools() as source:
            staged = importlib.import_module('tools.go_capsule')
            captured = importlib.import_module('tools.go_application_dependencies')
            wrapper = importlib.import_module('tools.guest_authoring_frontend')
            self.assertTrue(Path(staged.__file__).is_relative_to(source))
            with patch.object(captured, 'run_bounded', side_effect=self.resolver_command):
                self.assertEqual(self.call('resolve', self.app, '--candidate', candidate, '--go', self.go, module=staged)[0], 0)
            self.assertEqual(self.call('review-lock', self.owner, '--candidate', candidate, '--expect', digest(candidate.read_bytes()), module=staged)[0], 0)
            self.assertEqual(self.call('dependencies', self.app, module=staged)[0], 0)
            code, _out, err = self.call('test', self.owner, '--workspace', 'demo', module=staged)
            self.assertEqual(code, 1); self.assertIn('requires-explicit-frontend', err)
            result = subprocess.CompletedProcess([], 5, common.encode({'schemaVersion': 'latent.dev.result.v1', 'code': 'operation-unresolved', 'uncertain': True}), b'')
            with patch.object(wrapper, 'run_bounded_result', return_value=result) as dispatched:
                code, _out, _err = self.call('test', self.owner, '--workspace', 'demo', '--frontend', executable,
                    '--frontend-sha256', digest(executable.read_bytes()), module=staged)
            self.assertEqual(code, 5); dispatched.assert_called_once()


if __name__ == '__main__':
    unittest.main()
