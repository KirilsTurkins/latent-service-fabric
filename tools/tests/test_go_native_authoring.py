"""Go native metadata authoring controls; subprocess output is explicitly modelled."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from tools import go_native_authoring as locking, go_dependency_authoring as authoring, go_capsule
from tools.application_dependency_store import DependencyError
from tools.build_snapshot import canonical
from tools.tests import test_go_dependency_authoring as fixture


class GoNativeAuthoring(unittest.TestCase):
    copy_application = fixture.GoDependencyAuthoring.copy_application
    select = fixture.GoDependencyAuthoring.select

    @classmethod
    def setUpClass(cls):
        fixture.GoDependencyAuthoring.setUpClass.__func__(cls)

    def setUp(self):
        fixture.GoDependencyAuthoring.setUp(self)
        self.commands = []
        self.after = None
        self.fail_download = False
        self.tidy_unused_runtime = False
        self.selected_runtime_version = 'v0.2.3'
        self.runtime_sum = self.original['vendor/lsf/sdk/go-guest/runtime-deps/go.sum']

    def parse(self, path):
        value = {'Require': [], 'Replace': [], 'Exclude': []}
        for line in path.read_text().splitlines():
            if line.startswith('module '):
                value['Module'] = {'Path': line.split()[1]}
            elif line.startswith('go '):
                value['Go'] = line.split()[1]
            elif line.startswith('require '):
                _, name, version = line.split()
                value['Require'].append({'Path': name, 'Version': version})
            elif line.startswith('replace '):
                _, name, _, destination = line.split()
                name, _, version = name.partition('@')
                value['Replace'].append({'Old': {'Path': name, **({'Version': version} if version else {})},
                                         'New': {'Path': destination}})
            elif line.startswith('exclude '):
                _, name, version = line.split()
                value['Exclude'].append({'Path': name, 'Version': version})
        return value

    def render(self, path, value):
        text = 'module ' + value['Module']['Path'] + '\n\ngo ' + value['Go'] + '\n'
        for row in value['Require']:
            text += '\nrequire ' + row['Path'] + ' ' + row['Version'] + '\n'
        for row in value['Replace']:
            text += '\nreplace ' + locking.module_key(row['Old']) + ' => ' + row['New']['Path'] + '\n'
        for row in value['Exclude']:
            text += '\nexclude ' + row['Path'] + ' ' + row['Version'] + '\n'
        path.write_text(text, encoding='utf-8')

    def command(self, command, cwd, environment, seconds, maximum):
        work = Path(cwd)
        self.commands.append((list(command), work, dict(environment)))
        self.assertEqual(environment['GOTOOLCHAIN'], 'local')
        self.assertEqual(environment['GOWORK'], 'off')
        self.assertEqual(environment['GOENV'], 'off')
        self.assertEqual(environment['CGO_ENABLED'], '0')
        self.assertNotIn('GOPATH', environment)
        self.assertNotIn('GODEBUG', environment)
        self.assertEqual(Path(environment['GIT_CONFIG_GLOBAL']).read_bytes(), b'')
        arguments = command[1:]
        if arguments == ['version']:
            raw = b'go version go1.27.2 linux/amd64\n'
        elif arguments == ['mod', 'edit', '-json']:
            raw = canonical(self.parse(work / 'go.mod'))
        elif arguments[:2] == ['mod', 'edit']:
            value = self.parse(work / 'go.mod')
            for argument in arguments[2:]:
                flag, payload = argument.split('=', 1)
                if flag in {'-require', '-droprequire'}:
                    name, _, version = payload.partition('@')
                    value['Require'] = [row for row in value['Require'] if row['Path'] != name]
                    if flag == '-require':
                        value['Require'].append({'Path': name, 'Version': version})
                elif flag in {'-replace', '-dropreplace'}:
                    key, _, destination = payload.partition('=')
                    value['Replace'] = [row for row in value['Replace'] if locking.module_key(row['Old']) != key]
                    if flag == '-replace':
                        name, _, version = key.partition('@')
                        value['Replace'].append({'Old': {'Path': name, **({'Version': version} if version else {})},
                                                 'New': {'Path': destination}})
                else:
                    self.fail('unexpected native metadata operation ' + flag)
            self.render(work / 'go.mod', value)
            raw = b''
        elif arguments in (['mod', 'tidy'], ['mod', 'download', 'all']):
            self.assertEqual(environment['GOOS'], 'wasip1')
            self.assertEqual(environment['GOARCH'], 'wasm')
            self.assertEqual(environment['GOPROXY'], 'https://proxy.golang.org')
            value = self.parse(work / 'go.mod')
            for row in value['Replace']:
                source = Path(row['New']['Path'])
                self.assertTrue(source.is_relative_to(Path(environment['HOME']).parent / 'mirror'))
                self.assertTrue((source / 'go.mod').is_file())
            if self.fail_download and arguments[1] == 'download':
                raise RuntimeError('private download failure')
            if arguments[1] == 'tidy' and self.tidy_unused_runtime:
                value['Require'] = [row for row in value['Require'] if row['Path'] != 'go.bytecodealliance.org/pkg']
                self.render(work / 'go.mod', value)
            if self.after:
                self.after(work)
            (work / 'go.sum').write_bytes(b'example.test/public v1.2.3 h1:' + b'A' * 43 + b'=\n'
                                         + (self.runtime_sum if arguments[1] == 'download' else b''))
            raw = b''
        elif arguments == ['list', '-m', '-json', 'all']:
            value = self.parse(work / 'go.mod')
            rows = [{'Path': value['Module']['Path'], 'Main': True}]
            rows += [{'Path': row['Path'], 'Version': self.selected_runtime_version
                      if row['Path'] == 'go.bytecodealliance.org/pkg' else row['Version']}
                     for row in value['Require']]
            raw = b'\n'.join(canonical(row) for row in rows)
        else:
            self.fail('unexpected native invocation ' + repr(arguments))
        return subprocess.CompletedProcess(command, 0, raw, b'')

    def edit(self, operation, **values):
        with patch.object(locking, 'run_bounded', side_effect=self.command):
            return locking.edit(self.owner, operation, go=self.go, **values)

    def lock(self, **values):
        with patch.object(locking, 'run_bounded', side_effect=self.command):
            return locking.create_lock(self.owner, go=self.go, **values)

    def test_add_update_remove_are_native_offline_edits_preserving_accepted_capture(self):
        accepted = self.owner / 'latent.dependencies.lock.json'
        accepted.write_bytes(b'previous accepted capture')
        original_sum = (self.app / 'go.sum').read_bytes()
        identity = 'unknown.example.test/developer-module/v2'
        self.edit('add', identity=identity, version='v2.0.0', local=self.library)
        value = self.parse(self.app / 'go.mod')
        self.assertIn({'Path': identity, 'Version': 'v2.0.0'}, value['Require'])
        self.assertEqual(value['Replace'][-1]['New']['Path'], '../outside')
        self.edit('update', identity=identity, version='v2.1.0')
        self.assertFalse(any(row['Old']['Path'] == identity for row in self.parse(self.app / 'go.mod')['Replace']))
        self.edit('remove', identity=identity)
        self.assertFalse(any(row['Path'] == identity for row in self.parse(self.app / 'go.mod')['Require']))
        self.assertEqual(accepted.read_bytes(), b'previous accepted capture')
        self.assertEqual((self.app / 'go.sum').read_bytes(), original_sum)
        self.assertEqual((self.app / 'sdk-lock.json').read_bytes(), self.sdk)
        self.assertTrue(all(environment['GOPROXY'] == 'off' and environment['GOSUMDB'] == 'off'
                            for _command, _work, environment in self.commands))
        self.assertTrue(all(command[1] in {'version', 'mod'} for command, _work, _environment in self.commands))

    def test_invalid_versions_and_immutable_sdk_edits_fail_without_native_execution(self):
        before = authoring.source_files(self.app)
        for version in ('latest', 'v1.2', '^v1.2.3', 'v1.2.3\n', '*'):
            with self.subTest(version=version), self.assertRaisesRegex(DependencyError, 'exact-version'):
                self.edit('add', identity='example.test/module', version=version)
        with self.assertRaisesRegex(DependencyError, 'immutable-sdk'):
            self.edit('update', identity='go.bytecodealliance.org/pkg', version='v9.9.9')
        self.assertEqual(self.commands, [])
        self.assertEqual(authoring.source_files(self.app), before)

    def test_native_lock_restores_portable_local_replacements_and_preserves_prior_capture(self):
        (self.app / 'latent.dependencies.lock.json').write_bytes(b'previous accepted')
        declaration = self.parse(self.app / 'go.mod')
        result = self.lock(tags=['selected', 'selected'])
        declaration['Require'].append({'Path': 'go.bytecodealliance.org/pkg', 'Version': 'v0.2.3'})
        self.assertEqual(self.parse(self.app / 'go.mod'), declaration)
        self.assertEqual((self.app / 'latent.dependencies.lock.json').read_bytes(), b'previous accepted')
        self.assertTrue(result['captureRequired']); self.assertTrue(result['reviewRequired'])
        self.assertEqual(result['tags'], ['selected'])
        self.assertFalse(result['compilerExecution'])
        self.assertEqual(result['generators'], 'never-executed')
        self.assertNotIn(str(self.library), json.dumps(result))

    def test_native_lock_retains_reviewable_sdk_build_input_for_source_without_wit_imports(self):
        source = b'package developer\nimport ("net/http"; "outside.example.test/developer-module")\n'
        (self.app / 'src/main.go').write_bytes(source)
        self.tidy_unused_runtime = True
        accepted = self.app / 'latent.dependencies.lock.json'
        accepted.write_bytes(b'old reviewed capture')
        result = self.lock()
        requirements = self.parse(self.app / 'go.mod')['Require']
        self.assertEqual([row for row in requirements if row['Path'] == 'go.bytecodealliance.org/pkg'],
                         [{'Path': 'go.bytecodealliance.org/pkg', 'Version': 'v0.2.3'}])
        self.assertEqual((self.app / 'src/main.go').read_bytes(), source)
        self.assertTrue((self.app / 'go.sum').read_bytes().endswith(self.runtime_sum))
        self.assertEqual(result['sdkRuntimeBuildDependencies'], locking.runtime_build_dependencies(self.original))
        self.assertTrue(result['captureRequired']); self.assertTrue(result['reviewRequired'])
        self.assertEqual(accepted.read_bytes(), b'old reviewed capture')
        operations = [row[0][1:] for row in self.commands]
        self.assertLess(operations.index(['mod', 'tidy']),
                        operations.index(['mod', 'edit', '-require=go.bytecodealliance.org/pkg@v0.2.3']))
        self.assertLess(operations.index(['mod', 'edit', '-require=go.bytecodealliance.org/pkg@v0.2.3']),
                        operations.index(['mod', 'download', 'all']))

    def test_sdk_build_requirement_cannot_hide_an_override_replacement_or_exclusion(self):
        original = (self.app / 'go.mod').read_bytes()
        for field, row in (
                ('Require', {'Path': 'go.bytecodealliance.org/pkg', 'Version': 'v0.2.4'}),
                ('Replace', {'Old': {'Path': 'go.bytecodealliance.org/pkg'}, 'New': {'Path': '../outside'}}),
                ('Exclude', {'Path': 'go.bytecodealliance.org/pkg', 'Version': 'v0.2.3'})):
            (self.app / 'go.mod').write_bytes(original)
            value = self.parse(self.app / 'go.mod'); value[field].append(row)
            self.render(self.app / 'go.mod', value)
            before = authoring.source_files(self.app)
            self.commands.clear()
            with self.subTest(field=field), self.assertRaisesRegex(DependencyError, 'overrides-immutable-sdk'):
                self.lock()
            self.assertEqual(authoring.source_files(self.app), before)
            self.assertFalse(any(command[1:3] == ['mod', 'tidy'] for command, _work, _env in self.commands))

    def test_sdk_selected_version_and_both_checksums_are_verified_before_native_publication(self):
        (self.app / 'latent.dependencies.json').write_bytes(b'old capture manifest')
        (self.app / 'latent.dependencies.lock.json').write_bytes(b'old accepted capture')
        original = authoring.source_files(self.app)
        bad_sums = [b'', self.runtime_sum.replace(b'So9z', b'To9z'),
                    self.runtime_sum.replace(b'OjA+', b'PjA+')]
        for version, raw in [('v0.2.4', self.runtime_sum), *[('v0.2.3', raw) for raw in bad_sums]]:
            self.selected_runtime_version, self.runtime_sum = version, raw
            with self.subTest(version=version, sums=raw), self.assertRaisesRegex(DependencyError, 'selection-or-checksum-drift'):
                self.lock()
            self.assertEqual(authoring.source_files(self.app), original)

    def test_sdk_runtime_override_introduced_during_tidy_is_not_silently_replaced(self):
        before = authoring.source_files(self.app)
        def introduce_override(work):
            value = self.parse(work / 'go.mod')
            value['Replace'].append({'Old': {'Path': 'go.bytecodealliance.org/pkg'},
                                     'New': {'Path': '../outside'}})
            self.render(work / 'go.mod', value)
        self.after = introduce_override
        with self.assertRaisesRegex(DependencyError, 'overrides-immutable-sdk'):
            self.lock()
        self.assertEqual(authoring.source_files(self.app), before)
        self.assertFalse(any(command[1:3] == ['mod', 'download'] for command, _work, _env in self.commands))

    def test_sdk_runtime_selection_requires_one_unreplaced_module(self):
        modules = locking.runtime_build_dependencies(self.original)
        selected = [{'Path': row['path'], 'Version': row['version']} for row in modules]
        locking.runtime_selection(selected, self.runtime_sum, modules)
        for rows in ([], selected + selected, [{**selected[0], 'Replace': {'Path': 'outside.test/other'}}]):
            with self.subTest(rows=rows), self.assertRaisesRegex(DependencyError, 'selection-or-checksum-drift'):
                locking.runtime_selection(rows,self.runtime_sum,modules)

    def test_sdk_runtime_lock_binds_manifest_and_original_checksum_bytes(self):
        for name in ('go.mod', 'go.sum'):
            files = dict(self.original)
            files['vendor/lsf/sdk/go-guest/runtime-deps/' + name] += b'changed'
            with self.subTest(name=name), self.assertRaisesRegex(DependencyError, 'runtime-lock-identity'):
                locking.runtime_build_dependencies(files)

    def test_native_failure_preserves_both_native_files_and_accepted_capture(self):
        before = authoring.source_files(self.app)
        self.fail_download = True
        with self.assertRaises(RuntimeError):
            self.lock()
        self.assertEqual(authoring.source_files(self.app), before)

    def test_aggregate_local_file_count_is_bounded_before_mirror_publication(self):
        before = authoring.source_files(self.app)
        too_many = {'entry-' + str(index): b'' for index in range(32769)}
        with patch.object(locking, 'directory_files', return_value=too_many):
            with self.assertRaisesRegex(DependencyError, 'local-byte-or-count-limit'):
                self.lock()
        self.assertFalse(any(command[1:3] == ['mod', 'tidy'] for command, _work, _environment in self.commands))
        self.assertEqual(authoring.source_files(self.app), before)

    def test_source_local_resource_and_tool_drift_deny_publication(self):
        before = {name: (self.app / name).read_bytes() for name in ('go.mod', 'go.sum')}
        for target in (self.app / 'src/main.go', self.child / 'message.txt', self.go):
            original = target.read_bytes()
            self.after = lambda work: target.write_bytes(original + b'concurrent edit')
            with self.subTest(target=target.name), self.assertRaisesRegex(DependencyError, 'mutated'):
                self.lock()
            self.assertEqual({name: (self.app / name).read_bytes() for name in before}, before)
            target.write_bytes(original)

    def test_partial_native_publication_rolls_back_only_our_bytes(self):
        old = (self.app / 'go.mod').read_bytes()
        original = authoring.replace
        for user_edit in (False, True):
            (self.app / 'go.mod').write_bytes(old)
            def fail_sum(owner, private, name, raw, previous, sdk):
                if name == 'go.sum':
                    if user_edit:
                        (self.app / 'go.mod').write_bytes(b'user concurrent edit')
                    raise OSError('model publication failure')
                return original(owner, private, name, raw, previous, sdk)
            with patch.object(authoring, 'replace', side_effect=fail_sum), self.assertRaises(OSError):
                self.lock()
            self.assertEqual((self.app / 'go.mod').read_bytes(), b'user concurrent edit' if user_edit else old)

    def test_sdk_overlap_and_shadow_targets_are_denied(self):
        with self.assertRaisesRegex(DependencyError, 'overlaps-sdk-or-project'):
            self.edit('add', identity='outside.test/sdk', version='v0.0.0', local=self.app / 'vendor/lsf')
        with authoring.transaction(self.owner) as (owner, app, private, sdk):
            with self.assertRaisesRegex(DependencyError, 'edit-target'):
                authoring.replace(owner, private, 'vendor/lsf/go.mod', b'x', None, sdk)

    def test_explicit_empty_credential_slot_has_no_anonymous_fallback(self):
        policy = self.root / 'proxy-policy.json'
        policy.write_bytes(canonical({'proxy': 'https://example.invalid/modules', 'sumdb': 'off', 'authorizationEnv': ''}))
        with self.assertRaisesRegex(DependencyError, 'authorization-unavailable'):
            self.lock(proxy_config=policy)
        self.assertEqual(self.commands, [])

    def test_cli_lock_failure_is_redacted_without_retry(self):
        stderr = io.StringIO()
        with patch.object(locking, 'create_lock', side_effect=RuntimeError('SECRET=private')) as invoked, \
                redirect_stderr(stderr), redirect_stdout(io.StringIO()):
            result = go_capsule.main(['lock', str(self.owner), '--go', str(self.go)])
        self.assertEqual(result, 1); self.assertEqual(invoked.call_count, 1)
        self.assertNotIn('SECRET', stderr.getvalue())
        self.assertFalse(json.loads(stderr.getvalue())['automaticReplay'])
