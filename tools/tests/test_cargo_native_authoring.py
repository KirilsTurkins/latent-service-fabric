"""Controlled Cargo authoring boundaries; native command outputs are modelled."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib
import unittest
from unittest.mock import patch

from tools import cargo_native_authoring as locking, rust_dependency_authoring as authoring, rust_capsule
from tools.application_dependency_store import DependencyError
from tools.tests import test_rust_dependency_authoring as fixture


class CargoNativeAuthoring(unittest.TestCase):
    select = fixture.RustDependencyAuthoring.select

    @classmethod
    def setUpClass(cls):
        fixture.RustDependencyAuthoring.setUpClass.__func__(cls)

    def setUp(self):
        fixture.RustDependencyAuthoring.setUp(self)
        self.select(libraries=False)
        self.cargo = self.tool
        (self.cargo.parent / ('rustc.exe' if os.name == 'nt' else 'rustc')).write_bytes(b'model compiler identity; never executed')
        self.commands = []
        self.after = None
        self.fail_lock = False
        self.wrong_selection = False

    def command(self, command, cwd, environment, seconds, maximum):
        owned = Path(cwd)
        self.commands.append((list(command), owned, dict(environment)))
        self.assertEqual(Path(environment['CARGO_HOME']).parent, owned)
        self.assertEqual(environment['RUSTUP_AUTO_INSTALL'], '0')
        self.assertEqual(environment['RUSTUP_TOOLCHAIN'], '1.97.1')
        self.assertEqual(Path(environment['GIT_CONFIG_GLOBAL']).read_bytes(), b'')
        self.assertNotIn('RUSTFLAGS', environment)
        self.assertNotIn('CARGO_BUILD_RUSTC_WRAPPER', environment)
        if command[1:] == ['--version']:
            return subprocess.CompletedProcess(command, 0, b'cargo 1.97.1 (model-only)\n', b'')
        manifest = Path(command[command.index('--manifest-path') + 1])
        self.assertTrue(manifest.is_relative_to(owned / 'mirror'))
        self.assertFalse(owned.is_relative_to(manifest.parent))
        if command[1] in {'add', 'remove'}:
            selection = command[2]
            identity, _, version = selection.partition('@')
            text = manifest.read_text()
            pattern = re.compile('^' + re.escape(identity) + r'\s*=.*(?:\n|$)', re.MULTILINE)
            text = pattern.sub('', text)
            if command[1] == 'add':
                if '--path' in command:
                    path = Path(command[command.index('--path') + 1])
                    self.assertTrue(path.is_relative_to(owned / 'mirror'))
                    package = tomllib.loads((path / 'Cargo.toml').read_text())['package']
                    value = '{version=' + json.dumps(package['version']) + ', path=' + json.dumps(str(path)) + '}'
                else:
                    value = json.dumps('=9.9.9' if self.wrong_selection else version)
                if '[dependencies]' not in text:
                    text += '\n[dependencies]\n'
                text += identity + '=' + value + '\n'
            manifest.write_text(text, encoding='utf-8')
        elif command[1] == 'generate-lockfile':
            if self.fail_lock:
                raise RuntimeError('private native failure')
            if self.after:
                self.after(manifest.parent)
            with (manifest.parent / 'Cargo.lock').open('ab') as output:
                output.write(b'\n[[package]]\nname="native-selected-control"\nversion="1.0.0"\n')
        else:
            self.fail('unexpected Cargo operation ' + str(command))
        return subprocess.CompletedProcess(command, 0, b'', b'')

    def author(self, operation, **values):
        with patch.object(locking, 'run_bounded', side_effect=self.command):
            return locking.author(self.owner, operation, cargo=self.cargo, **values)

    def test_native_add_update_remove_preserve_sdk_and_accepted_capture(self):
        accepted = self.owner / 'latent.dependencies.lock.json'
        accepted.write_bytes(b'previous reviewed capture')
        before = locking.sdk_configuration(tomllib.loads((self.app / 'Cargo.toml').read_text()))
        self.author('add', identity='outside', version='1.0.0', local=self.library)
        row = tomllib.loads((self.app / 'Cargo.toml').read_text())['dependencies']['outside']
        self.assertEqual(row['path'], '../independent-outside')
        self.author('update', identity='outside', version='2.0.0')
        self.assertEqual(tomllib.loads((self.app / 'Cargo.toml').read_text())['dependencies']['outside'], '=2.0.0')
        self.author('remove', identity='outside')
        self.assertNotIn('outside', tomllib.loads((self.app / 'Cargo.toml').read_text())['dependencies'])
        self.assertEqual(locking.sdk_configuration(tomllib.loads((self.app / 'Cargo.toml').read_text())), before)
        self.assertEqual(accepted.read_bytes(), b'previous reviewed capture')
        self.assertEqual((self.app / 'sdk-lock.json').read_bytes(), self.sdk)
        self.assertTrue(all(command[1] in {'--version', 'add', 'remove', 'generate-lockfile'} for command, _cwd, _env in self.commands))

    def test_nonexact_and_sdk_edits_are_rejected_before_native_commands(self):
        before = fixture.project.snapshot(self.app)
        for version in ('latest', '^1.0.0', '1.0', '1.0.0\n', '*'):
            with self.subTest(version=version), self.assertRaisesRegex(DependencyError, 'exact-version'):
                self.author('add', identity='unknown', version=version)
        with self.assertRaisesRegex(DependencyError, 'immutable-sdk'):
            self.author('remove', identity='wit-bindgen', target='cfg(target_arch = "wasm32")')
        self.assertEqual(self.commands, [])
        self.assertEqual(fixture.project.snapshot(self.app), before)

    def test_local_identity_sdk_overlap_and_external_workspace_pointer_fail_closed(self):
        with self.assertRaisesRegex(DependencyError, 'identity-mismatch'):
            self.author('add', identity='different-coordinate', version='1.0.0', local=self.library)
        with self.assertRaisesRegex(DependencyError, 'overlaps-project'):
            self.author('add', identity='sdk', version='1.0.0', local=self.app / 'vendor/lsf')
        manifest = self.library / 'Cargo.toml'
        manifest.write_text(manifest.read_text().replace('[package]', '[package]\nworkspace="/unobserved/workspace"'), encoding='utf-8')
        with self.assertRaisesRegex(DependencyError, 'workspace-pointer-not-captured'):
            self.author('add', identity='outside', version='1.0.0', local=self.library)
        self.assertEqual(self.commands, [])

    def test_quoted_paths_are_mirrored_and_original_transitive_resources_observed(self):
        path = self.library / 'Cargo.toml'
        path.write_text(path.read_text().replace('resource={path=', 'resource={"path"='), encoding='utf-8')
        result = self.author('add', identity='outside', version='1.0.0', local=self.library)
        self.assertTrue(result['captureRequired']); self.assertTrue(result['reviewRequired'])
        self.assertFalse(result['compilerExecution'])
        self.assertNotIn(str(self.library), json.dumps(result))
        self.assertEqual((self.child / 'src/greeting.txt').read_bytes(), b'original captured resource')

    def test_source_local_resource_and_tool_drift_reject_publication(self):
        original = {name: (self.app / name).read_bytes() for name in ('Cargo.toml', 'Cargo.lock')}
        for target in (self.app / 'src/lib.rs', self.child / 'src/greeting.txt', self.cargo):
            raw = target.read_bytes()
            self.after = lambda work: target.write_bytes(raw + b'concurrent edit')
            with self.subTest(target=target.name), self.assertRaisesRegex(DependencyError, 'mutated'):
                self.author('add', identity='outside', version='1.0.0', local=self.library)
            self.assertEqual({name: (self.app / name).read_bytes() for name in original}, original)
            target.write_bytes(raw)

    def test_native_failure_keeps_both_original_metadata_files(self):
        before = fixture.project.snapshot(self.app)
        self.fail_lock = True
        with self.assertRaises(RuntimeError):
            self.author('add', identity='outside', version='1.0.0', local=self.library)
        self.assertEqual(fixture.project.snapshot(self.app), before)

    def test_wrong_native_selection_and_mirror_source_mutation_are_denied(self):
        before = fixture.project.snapshot(self.app)
        self.wrong_selection = True
        with self.assertRaisesRegex(DependencyError, 'selection-mismatch'):
            self.author('add', identity='unknown', version='1.0.0')
        self.wrong_selection = False
        self.after = lambda work: (work / 'src/lib.rs').write_bytes(b'mutated native source')
        with self.assertRaisesRegex(DependencyError, 'nondeclaration-input'):
            self.author('lock')
        self.assertEqual(fixture.project.snapshot(self.app), before)

    def test_partial_publication_preserves_concurrent_user_edit(self):
        before = (self.app / 'Cargo.toml').read_bytes()
        original = authoring.replace
        for user_edit in (False, True):
            (self.app / 'Cargo.toml').write_bytes(before)
            def fail_lock(owner, private, name, raw, previous, sdk):
                if name == 'Cargo.lock':
                    if user_edit:
                        (self.app / 'Cargo.toml').write_bytes(b'concurrent user edit')
                    raise OSError('model publication failure')
                return original(owner, private, name, raw, previous, sdk)
            with patch.object(authoring, 'replace', side_effect=fail_lock), self.assertRaises(OSError):
                self.author('add', identity='outside', version='1.0.0', local=self.library)
            self.assertEqual((self.app / 'Cargo.toml').read_bytes(), b'concurrent user edit' if user_edit else before)

    def test_project_config_and_unselected_registry_have_no_implicit_authority(self):
        configuration = self.app / '.cargo/config.toml'
        configuration.parent.mkdir()
        configuration.write_bytes(b'[registry]\nglobal-credential-providers=["unapproved"]\n')
        with self.assertRaisesRegex(DependencyError, 'project-config-not-supported'):
            self.author('lock')
        configuration.unlink()
        with self.assertRaisesRegex(DependencyError, 'registry-not-explicit'):
            self.author('add', identity='unknown', version='1.0.0', registry='ambient-private')
        self.assertEqual(self.commands, [])

    def test_cli_failure_redacts_native_output_and_does_not_retry(self):
        stderr = io.StringIO()
        with patch.object(locking, 'author', side_effect=RuntimeError('PRIVATE_TOKEN=secret')) as invoked, \
                redirect_stderr(stderr), redirect_stdout(io.StringIO()):
            result = rust_capsule.main(['lock', str(self.owner), '--cargo', str(self.cargo)])
        self.assertEqual(result, 1); self.assertEqual(invoked.call_count, 1)
        self.assertNotIn('PRIVATE_TOKEN', stderr.getvalue())
        self.assertFalse(json.loads(stderr.getvalue())['automaticReplay'])

    def test_relative_private_policy_cannot_hide_inside_project(self):
        (self.app / 'private-policy.json').write_bytes(b'{"registries":{}}')
        previous = Path.cwd()
        try:
            os.chdir(self.app)
            with self.assertRaisesRegex(DependencyError, 'must-stay-outside-project'):
                locking.native.registry_policy(self.owner, self.app, Path('private-policy.json'))
        finally:
            os.chdir(previous)
        self.assertEqual(self.commands, [])


class WorkspaceRecipePreservation(unittest.TestCase):
    original = b'''[package]
name="app"
version="1.0.0"
[workspace]
[workspace.package]
license="Apache-2.0"
[workspace.dependencies]
serde={version="=1.0.229",features=["derive"]}
[workspace.dependencies."wit-bindgen"]
version="=0.62.0"
[profile.release]
panic="abort"
[dependencies]
outside={path="../outside",version="0.1.0"}
'''
    removed = b'''[package]
name="app"
version="1.0.0"
[workspace]
[workspace.package]
license="Apache-2.0"
[profile.release]
panic="abort"
[dependencies]
'''

    def test_only_pruned_workspace_entries_are_restored_and_native_removal_is_preserved(self):
        restored = locking.preserve_workspace_recipe(self.original, self.removed)
        value = tomllib.loads(restored.decode())
        self.assertEqual(value['workspace'], tomllib.loads(self.original.decode())['workspace'])
        self.assertEqual(locking.sdk_configuration(value), locking.sdk_configuration(tomllib.loads(self.original.decode())))
        self.assertNotIn('outside', value['dependencies'])
        self.assertIn(b'[workspace.dependencies."wit-bindgen"]\nversion="=0.62.0"', restored)
        package_profiles = b'\n[profile.dev.package.cranelift-codegen]\nopt-level=3\n[profile.dev.package.wasmparser]\nopt-level=3\n'
        for original, selected in ((self.original + package_profiles, self.removed),
                                   (self.original + package_profiles, self.original)):
            with self.subTest(workspace_changed=original != self.original):
                repaired = tomllib.loads(locking.preserve_workspace_recipe(original, selected).decode())
                expected = tomllib.loads(selected.decode())
                expected['workspace'] = tomllib.loads(original.decode())['workspace']
                expected['profile'] = tomllib.loads(original.decode())['profile']
                self.assertEqual(repaired, expected)
                self.assertEqual(locking.sdk_configuration(repaired),
                                 locking.sdk_configuration(tomllib.loads(original.decode())))

    def test_unchanged_workspace_never_rewrites_native_manifest(self):
        self.assertIs(locking.preserve_workspace_recipe(self.original, self.original), self.original)

    def test_new_or_modified_workspace_and_sdk_changes_are_not_repaired(self):
        candidates = [
            self.removed.replace(b'[workspace.package]', b'[workspace.dependencies]\nunapproved="1.0.0"\n[workspace.package]'),
            self.removed.replace(b'[workspace.package]', b'[workspace.dependencies]\nserde="=9.9.9"\n[workspace.package]'),
            self.removed.replace(b'Apache-2.0', b'changed'),
            self.removed.replace(b'panic="abort"', b'panic="unwind"'),
            self.removed.replace(b'name="app"', b'name="changed"'),
            self.removed + b'\n[profile.dev.package.changed]\nopt-level=3\n',
        ]
        for selected in candidates:
            with self.subTest(selected=selected), self.assertRaisesRegex(DependencyError, 'mutated-sdk-recipe'):
                locking.preserve_workspace_recipe(self.original, selected)
        original = self.original + b'\n[profile.dev.package.compiler]\nopt-level=3\n'
        for selected in (self.removed + b'\n[profile.dev.package.compiler]\nopt-level=1\n',
                         self.removed + b'\n[profile.dev]\nopt-level=3\n',
                         self.removed.replace(b'panic="abort"', b'panic="unwind"')):
            with self.subTest(selected=selected), self.assertRaisesRegex(DependencyError, 'mutated-sdk-recipe'):
                locking.preserve_workspace_recipe(original, selected)

    def test_inline_layout_and_header_like_string_content_cannot_change_unrelated_semantics(self):
        original = b'workspace={dependencies={serde="=1.0.229"}}\n[package]\nname="app"\n'
        selected = b'workspace={}\n[package]\nname="app"\n'
        with self.assertRaisesRegex(DependencyError, 'workspace-preservation'):
            locking.preserve_workspace_recipe(original, selected)
        original = self.original.replace(b'license="Apache-2.0"', b'license="Apache-2.0"\n[workspace.metadata]\ntext="""\n[dependencies]\n"""')
        selected = self.removed.replace(b'license="Apache-2.0"', b'license="Apache-2.0"\n[workspace.metadata]\ntext="""\n[dependencies]\n"""')
        with self.assertRaisesRegex(DependencyError, 'workspace-preservation'):
            locking.preserve_workspace_recipe(original, selected)
