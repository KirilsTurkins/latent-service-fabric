"""Controlled npm lock authoring and declaration fences; native outputs modelled here."""
from contextlib import redirect_stderr, redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from tools import npm_lock_authoring as locking
from tools import typescript_application_dependencies as native, typescript_dependency_authoring as authoring
from tools import typescript_capsule
from tools.application_dependency_store import DependencyError
from tools.build_snapshot import canonical
from tools.tests import test_typescript_dependency_authoring as fixture
from tools.typescript_guest import project


class NpmLockAuthoring(unittest.TestCase):
    copy_application = fixture.NpmDependencyAuthoring.copy_application
    select = fixture.NpmDependencyAuthoring.select
    resolver_command = fixture.NpmDependencyAuthoring.resolver_command

    @classmethod
    def setUpClass(cls):
        fixture.NpmDependencyAuthoring.setUpClass.__func__(cls)

    def setUp(self):
        fixture.NpmDependencyAuthoring.setUp(self)
        self.after = None
        self.unobserved = False
        self.native_commands = []

    def command(self, command, cwd, environment, seconds, maximum):
        self.native_commands.append(list(command))
        self.assertNotIn('NODE_OPTIONS', environment)
        self.assertEqual(environment['NPM_CONFIG_IGNORE_SCRIPTS'], 'true')
        if command[1:] == ['--version']:
            raw = b'v24.19.0\n'
        elif command[-1] == '--version':
            raw = b'11.17.0\n'
        else:
            self.assertEqual(command[2], 'install')
            for flag in ('--package-lock-only', '--ignore-scripts', '--bin-links=false', '--strict-peer-deps'):
                self.assertIn(flag, command)
            work = Path(cwd)
            declaration = json.loads((work / 'package.json').read_bytes())
            packages = {'': {field: declaration[field] for field in native.FIELDS if field in declaration}}
            pending = list(declaration.get('dependencies', {}).items())
            while pending:
                name, spec = pending.pop()
                source = native.local_path(spec, work)
                manifest = json.loads((source / 'package.json').read_bytes())
                row = {'version': manifest['version'], 'resolved': 'file:' + str(source)}
                for field in native.FIELDS:
                    if field in manifest:
                        row[field] = manifest[field]
                packages['node_modules/' + name] = row
                pending.extend(manifest.get('dependencies', {}).items())
            if self.unobserved:
                unknown = work / 'unknown-native-input'
                unknown.mkdir()
                packages['node_modules/outside-module']['resolved'] = 'file:' + str(unknown)
            (work / 'package-lock.json').write_bytes(canonical({'lockfileVersion': 3, 'packages': packages}))
            if self.after:
                self.after(work)
            raw = b''
        return subprocess.CompletedProcess(command, 0, raw, b'')

    def lock(self):
        with patch.object(locking, 'run_bounded', side_effect=self.command):
            return locking.create_lock(self.owner, node=self.node, npm=self.npm)

    def test_add_update_remove_are_exact_edits_without_fetch_and_preserve_accepted_lock(self):
        accepted = self.owner / 'latent.dependencies.lock.json'
        accepted.write_bytes(b'previous reviewed lock')
        with patch.object(locking, 'run_bounded', side_effect=AssertionError('edits must not fetch')):
            authoring.edit(self.app, 'add', identity='ordinary-package', version='1.2.3', section='optionalDependencies')
            authoring.edit(self.app, 'update', identity='ordinary-package', version='2.0.0-beta.1', section='optionalDependencies')
            self.assertEqual(authoring.configuration(self.app)['optionalDependencies']['ordinary-package'], '2.0.0-beta.1')
            authoring.edit(self.app, 'remove', identity='ordinary-package', section='optionalDependencies')
            authoring.edit(self.app, 'add', identity='JSONStream', version='1.3.5')
            self.assertEqual(authoring.configuration(self.app)['dependencies']['JSONStream'], '1.3.5')
            authoring.edit(self.app, 'remove', identity='JSONStream')
        self.assertEqual(accepted.read_bytes(), b'previous reviewed lock')
        self.assertEqual((self.app / 'sdk-lock.json').read_bytes(), self.sdk)

    def test_first_add_creates_only_native_application_declaration(self):
        (self.app / 'package.json').unlink(); (self.app / 'package-lock.json').unlink()
        authoring.edit(self.app, 'add', identity='outside-module', local=self.library)
        value = authoring.configuration(self.app)
        self.assertTrue(value['private']); self.assertEqual(value['type'], 'module')
        self.assertEqual(value['dependencies']['outside-module'], 'file:../outside')
        self.assertFalse((self.app / 'package-lock.json').exists())
        self.assertFalse((self.app / 'latent.dependencies.json').exists())

    def test_nonexact_ambiguous_and_sdk_overlap_edits_fail_before_changes(self):
        before = authoring.source_files(self.app)
        for version in ('*', '^1.0.0', '[1,2)', 'latest', '1.0', '1.0.0\n'):
            with self.subTest(version=version), self.assertRaisesRegex(DependencyError, 'exact-version'):
                authoring.edit(self.app, 'update', identity='outside-module', version=version)
        with self.assertRaisesRegex(DependencyError, 'one-exact-source'):
            authoring.edit(self.app, 'add', identity='new', version='1.0.0', local=self.library)
        with self.assertRaisesRegex(DependencyError, 'overlaps-sdk-or-project'):
            authoring.edit(self.app, 'add', identity='sdk', local=self.app / 'vendor/lsf')
        self.assertEqual(authoring.source_files(self.app), before)

    def test_nested_application_cannot_be_its_own_local_package(self):
        fixture.NpmDependencyAuthoring.nested(self)
        before = authoring.source_files(self.app)
        with self.assertRaisesRegex(DependencyError, 'overlaps-sdk-or-project'):
            authoring.edit(self.app, 'add', identity='self', local=self.app)
        self.assertEqual(authoring.source_files(self.app), before)

    def test_lock_mirrors_transitive_local_inputs_and_retains_native_original_semantics(self):
        old = (self.app / 'package-lock.json').read_bytes()
        result = self.lock()
        value = json.loads((self.app / 'package-lock.json').read_bytes())
        self.assertEqual(value['packages']['']['dependencies'], authoring.configuration(self.app)['dependencies'])
        self.assertEqual(value['packages']['node_modules/outside-module']['resolved'], 'file:../outside')
        self.assertEqual(value['packages']['node_modules/outside-module']['dependencies'], {'transitive-module': 'file:../transitive'})
        self.assertNotEqual((self.app / 'package-lock.json').read_bytes(), old)
        self.assertTrue(result['captureRequired']); self.assertTrue(result['reviewRequired'])
        self.assertFalse((self.app / 'latent.dependencies.lock.json').exists())
        self.assertEqual(len(self.native_commands), 3)

    def test_unsafe_local_archive_is_rejected_before_native_invocation(self):
        import tarfile
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode='w:gz') as archive:
            entry = tarfile.TarInfo('../outside-package.json')
            entry.size = 2
            archive.addfile(entry, io.BytesIO(b'{}'))
        package = self.root / 'unsafe.tgz'
        package.write_bytes(raw.getvalue())
        authoring.edit(self.app, 'update', identity='outside-module', local=package)
        with patch.object(locking, 'run_bounded', side_effect=AssertionError('unsafe archive must not reach native npm')):
            with self.assertRaises(DependencyError):
                locking.create_lock(self.owner, node=self.node, npm=self.npm)
        self.assertEqual(self.native_commands, [])

    def test_native_failure_keeps_previous_lock_manifest_and_accepted_capture(self):
        previous = (self.app / 'package-lock.json').read_bytes()
        (self.owner / 'latent.dependencies.lock.json').write_bytes(b'previous accepted')
        (self.owner / 'latent.dependencies.json').write_bytes(b'previous manifest')
        with patch.object(locking, 'run_bounded', side_effect=RuntimeError('private native failure')):
            with self.assertRaises(RuntimeError):
                locking.create_lock(self.owner, node=self.node, npm=self.npm)
        self.assertEqual((self.app / 'package-lock.json').read_bytes(), previous)
        self.assertEqual((self.owner / 'latent.dependencies.lock.json').read_bytes(), b'previous accepted')
        self.assertEqual((self.owner / 'latent.dependencies.json').read_bytes(), b'previous manifest')

    def test_source_or_local_resource_drift_prevents_native_lock_publication(self):
        previous = (self.app / 'package-lock.json').read_bytes()
        for target in (self.app / 'src/main.ts', self.child / 'greeting.txt'):
            original = target.read_bytes()
            self.after = lambda work: target.write_bytes(original + b'concurrent user edit')
            with self.subTest(target=target.name), self.assertRaisesRegex(DependencyError, 'source-tool-or-policy-mutated'):
                self.lock()
            self.assertEqual((self.app / 'package-lock.json').read_bytes(), previous)
            target.write_bytes(original)

    def test_unobserved_local_native_source_is_rejected_without_publication(self):
        previous = (self.app / 'package-lock.json').read_bytes()
        self.unobserved = True
        with self.assertRaisesRegex(DependencyError, 'unobserved-local-source'):
            self.lock()
        self.assertEqual((self.app / 'package-lock.json').read_bytes(), previous)

    def test_explicit_profile_is_inherited_by_direct_capture_and_mismatch_precedes_native_commands(self):
        from tools.typescript_guest.runtime_profile import ASYNC_PROFILE, SYNC_PROFILE
        self.owner = self.app = project.create(self.root / 'async-app', 'greeting', runtime_profile=ASYNC_PROFILE)
        self.select()
        candidate = self.root / 'profile-candidate.json'
        with patch.object(native, 'run_bounded', side_effect=self.resolver_command):
            result = native.resolve(self.owner, candidate, node=self.node, npm=self.npm)
        self.assertEqual(result['selection']['runtimeProfile'], ASYNC_PROFILE)
        self.calls.clear()
        with patch.object(native, 'run_bounded', side_effect=AssertionError('mismatch must precede native')):
            with self.assertRaisesRegex(ValueError, 'profile-capture-mismatch'):
                native.resolve(self.owner, self.root / 'mismatch.json', node=self.node, npm=self.npm,
                               selected={'runtimeProfile': SYNC_PROFILE})
        self.assertEqual(self.calls, [])

    def test_registry_authorization_slot_and_value_bounds_never_fall_back(self):
        root = self.root / 'invalid-policy'
        for ordinal, variable in enumerate(('', None, 'NODE_OPTIONS', 'LSF_REQUIRED_TOKEN')):
            owned = root / str(ordinal); owned.mkdir(parents=True)
            with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(DependencyError, 'authorization-unavailable'):
                native.fetch_environment(owned, {'registries': [{'url': 'https://example.invalid/npm/', 'authorizationEnv': variable}]})
        for ordinal, token in enumerate(('x\ny', 'x\ty', 'x' * 8193, 'x\x7f')):
            owned = self.root / ('bad-value-' + str(ordinal)); owned.mkdir()
            with patch.dict(os.environ, {'LSF_TOKEN': token}), self.assertRaisesRegex(DependencyError, 'authorization-format'):
                native.fetch_environment(owned, {'registries': [{'url': 'https://example.invalid/npm/', 'authorizationEnv': 'LSF_TOKEN'}]})

    def test_cli_lock_failure_is_redacted_once_and_preserves_accepted_bytes(self):
        stderr = io.StringIO()
        with patch.object(locking, 'create_lock', side_effect=RuntimeError('PRIVATE_TOKEN=secret')) as lock, \
                redirect_stderr(stderr), redirect_stdout(io.StringIO()):
            result = typescript_capsule.main(['lock', str(self.owner), '--node', str(self.node), '--npm', str(self.npm)])
        self.assertEqual(result, 1); self.assertEqual(lock.call_count, 1)
        self.assertNotIn('PRIVATE_TOKEN', stderr.getvalue())
        self.assertFalse(json.loads(stderr.getvalue())['automaticReplay'])
