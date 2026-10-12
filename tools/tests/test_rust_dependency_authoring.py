"""Cargo authoring capture/review controls; native compiler/node proof is separate."""
from contextlib import redirect_stderr, redirect_stdout
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
from tools import rust_application_dependencies as native, rust_capsule, rust_capsule_project as project
from tools import rust_dependency_authoring as authoring
from tools.application_dependency_store import DependencyError, Store
from tools.build_snapshot import canonical, digest
from tools.dev_workflow import cli, common, project as dev_project
from tools.tests.test_dev_contracts import descriptor


class Output(io.StringIO):
    @property
    def buffer(self):
        return self

    def write(self, value):
        return super().write(value.decode('utf-8') if isinstance(value, bytes) else value)


class RustDependencyAuthoring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix='rust-authoring-source-')
        cls.addClassCleanup(temporary.cleanup)
        cls.original = project.snapshot(project.create(Path(temporary.name) / 'app', 'greeting'))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='rust-authoring-control-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.owner = self.root / 'project'
        self.app = self.owner
        self.app.mkdir()
        for name, raw in self.original.items():
            path = self.app / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        self.sdk = (self.app / 'sdk-lock.json').read_bytes()
        self.library = self.root / 'independent-outside'
        self.child = self.root / 'independent-resource'
        for path, name in ((self.library, 'outside'), (self.child, 'resource')):
            path.mkdir()
            (path / 'src').mkdir()
            manifest = '[package]\nname="' + name + '"\nversion="1.0.0"\nlicense="MIT"\nedition="2024"\n'
            if path == self.library:
                manifest += '[dependencies]\nresource={path="../independent-resource"}\n'
            (path / 'Cargo.toml').write_text(manifest, encoding='utf-8')
            (path / 'src/lib.rs').write_bytes(b'pub fn value() -> u32 { 42 }\n')
        (self.child / 'src/greeting.txt').write_bytes(b'original captured resource')
        self.tool = self.root / 'cargo-boundary-only'
        self.tool.write_bytes(b'not an executable: native Cargo command outputs are modelled in these controls')
        self.calls = []
        self.select()

    def select(self, libraries=True):
        declaration = self.original['Cargo.toml']
        if libraries:
            declaration += ('\n[dependencies]\noutside={path=' + json.dumps(str(self.library)) + '}\n').encode()
        (self.app / 'Cargo.toml').write_bytes(declaration)
        # These cases model Cargo's native outputs and test the real capture,
        # transformation and offline review code. They do not run Cargo itself.
        lock = self.original['Cargo.lock']
        if libraries:
            lock += b'\n[[package]]\nname="outside"\nversion="1.0.0"\n\n[[package]]\nname="resource"\nversion="1.0.0"\n'
        (self.app / 'Cargo.lock').write_bytes(lock)
        self.libraries = libraries

    def nested(self):
        original = project.snapshot(self.app)
        self.owner = self.root / 'nested-project'
        self.owner.mkdir()
        self.app = self.owner / 'app'
        self.app.mkdir()
        for name, raw in original.items():
            path = self.app / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        value = descriptor()
        value.update(language='rust', inputRoots=['app'])
        value['template']['ownerIssue'] = dev_project.LANGUAGES['rust']
        value['build']['workingDirectory'] = 'app'
        (self.owner / 'latent.project.json').write_bytes(common.encode(value))

    def metadata(self):
        def package(path, name, identity):
            return {'id': identity, 'name': name, 'version': '1.0.0', 'source': None,
                    'manifest_path': str(path / 'Cargo.toml'), 'license': 'MIT', 'license_file': None,
                    'targets': [{'kind': ['lib'], 'src_path': str(path / 'src/lib.rs')}]}
        packages = [package(self.app, 'my-greeting', 'root')]
        nodes = [{'id': 'root', 'features': [], 'deps': []}]
        if self.libraries:
            packages += [package(self.library, 'outside', 'outside'), package(self.child, 'resource', 'resource')]
            nodes[0]['deps'] = [{'pkg': 'outside'}]
            nodes += [{'id': 'outside', 'features': ['pure'], 'deps': [{'pkg': 'resource'}]},
                      {'id': 'resource', 'features': [], 'deps': []}]
        if (self.app / 'build.rs').exists():
            packages[0]['targets'].append({'kind': ['custom-build'], 'src_path': str(self.app / 'build.rs')})
        return {'version': 1, 'packages': packages, 'resolve': {'root': 'root', 'nodes': nodes}}

    def resolver_command(self, command, cwd, environment, seconds, maximum):
        self.calls.append((list(command), Path(cwd), dict(environment), seconds, maximum))
        if command[1] == '--version':
            raw = b'cargo 1.97.1 (source-boundary-model)\n'
        elif command[1] == 'metadata':
            raw = canonical(self.metadata())
        elif command[1] == 'vendor':
            Path(command[-1]).mkdir()
            raw = b''
        else:
            self.fail('unexpected resolver command: ' + repr(command))
        return subprocess.CompletedProcess(command, 0, raw, b'')

    def call(self, *arguments):
        out, err = Output(), Output()
        with redirect_stdout(out), redirect_stderr(err):
            code = rust_capsule.main([str(value) for value in arguments])
        return code, out.getvalue(), err.getvalue()

    def capture(self, **kwargs):
        candidate = self.root / ('candidate-' + secrets.token_hex(8) + '.json')
        with patch.object(native, 'run_bounded', side_effect=self.resolver_command):
            locked = native.resolve(self.owner, candidate, cargo=self.tool, **kwargs)
        return candidate, locked

    def reviewed(self):
        candidate, lock = self.capture()
        result = authoring.review(self.owner, candidate, digest(candidate.read_bytes()))
        return candidate, lock, result

    def test_capture_and_exact_review_preserve_sdk_and_materialize_removed_outside_sources(self):
        candidate, lock, result = self.reviewed()
        shutil.rmtree(self.library); shutil.rmtree(self.child)
        with patch.object(inputs, 'fetch', side_effect=AssertionError('offline review contacted upstream')):
            status = authoring.status(self.owner)
            work, output = self.root / 'work', self.root / 'output'
            work.mkdir(); output.mkdir()
            (work / 'Cargo.toml').write_bytes((self.app / 'Cargo.toml').read_bytes())
            closure = inputs.prepare(self.owner, work, output, 'rust')
            adapted, receipt = native.configure(closure, work, self.root / 'cargo-home')
            closure.check_unchanged()
        resource = next(row for row in lock['artifacts'] if row['metadata'].get('package') == 'resource')
        self.assertEqual((work / resource['mount'] / 'src/greeting.txt').read_bytes(), b'original captured resource')
        self.assertNotIn(str(self.library).encode(), adapted)
        self.assertFalse(receipt['networkResolution'])
        self.assertEqual(status['capturedInputIdentity'], result['capturedInputIdentity'])
        self.assertEqual((self.owner / inputs.LOCK).read_bytes(), candidate.read_bytes())
        self.assertEqual((self.app / 'sdk-lock.json').read_bytes(), self.sdk)

    def test_add_update_remove_require_fresh_resolution_and_review_keep_accepted_lock(self):
        first, _lock, _result = self.reviewed()
        accepted = first.read_bytes()
        self.select(False)
        with self.assertRaisesRegex(DependencyError, 'native-lock-drift'):
            authoring.status(self.owner)
        second, _lock = self.capture()
        self.assertEqual((self.owner / inputs.LOCK).read_bytes(), accepted)
        with self.assertRaisesRegex(DependencyError, 'lock-drift'):
            authoring.status(self.owner)
        authoring.review(self.owner, second, digest(second.read_bytes()))
        self.assertEqual(len(authoring.status(self.owner)['artifacts']), 1)
        self.select(True)
        third, _lock = self.capture()
        authoring.review(self.owner, third, digest(third.read_bytes()))
        self.assertEqual(len(authoring.status(self.owner)['artifacts']), 3)
        self.assertEqual((self.app / 'sdk-lock.json').read_bytes(), self.sdk)

    def test_nested_outer_and_app_review_share_original_native_paths_and_offline_trust(self):
        self.nested()
        candidate, lock, result = self.reviewed()
        self.assertEqual([row['path'] for row in lock['nativeLocks']], ['app/Cargo.lock', 'app/cargo-resolved.lock.json'])
        self.assertFalse((self.app / inputs.MANIFEST).exists())
        self.assertEqual(authoring.status(self.app)['capturedInputIdentity'], result['capturedInputIdentity'])
        loaded, _identity = dev_project.load(self.owner)
        self.assertEqual(loaded['dependencyInputs']['applicationLock'], digest(candidate.read_bytes()))

    def test_candidate_tamper_or_wrong_review_digest_never_replaces_accepted_lock(self):
        first, _lock, _result = self.reviewed()
        accepted = first.read_bytes()
        second, _lock = self.capture()
        expected = digest(second.read_bytes())
        second.write_bytes(second.read_bytes() + b' ')
        with self.assertRaisesRegex(DependencyError, 'candidate-review-drift'):
            authoring.review(self.owner, second, expected)
        self.assertEqual((self.owner / inputs.LOCK).read_bytes(), accepted)

    def test_native_lock_drift_never_accepts_or_approves_stale_resolution(self):
        candidate, _lock = self.capture()
        (self.app / 'Cargo.lock').write_bytes(b'changed native lock')
        with self.assertRaisesRegex(DependencyError, 'native-lock-drift'):
            authoring.review(self.owner, candidate, digest(candidate.read_bytes()))
        self.assertFalse((self.owner / inputs.LOCK).exists())

    def test_root_manifest_drift_and_new_default_build_script_fail_before_review(self):
        candidate, _lock = self.capture()
        original = (self.app / 'Cargo.toml').read_bytes()
        (self.app / 'Cargo.toml').write_bytes(original + b'\n# changed manifest\n')
        with self.assertRaisesRegex(DependencyError, 'root-manifest-drift'):
            authoring.review(self.owner, candidate, digest(candidate.read_bytes()))
        (self.app / 'Cargo.toml').write_bytes(original)
        (self.app / 'build.rs').write_bytes(b'fn main() {}\n')
        with self.assertRaisesRegex(DependencyError, 'build-script-drift'):
            authoring.review(self.owner, candidate, digest(candidate.read_bytes()))
        self.assertFalse((self.owner / inputs.LOCK).exists())

    def test_captured_build_script_is_reviewable_but_never_authorized_by_review(self):
        (self.app / 'build.rs').write_bytes(b'fn main() {}\n')
        candidate, _lock, result = self.reviewed()
        self.assertEqual(len(result['executableInputs']), 1)
        self.assertFalse(result['compilerExecution'])
        work, output = self.root / 'work', self.root / 'output'
        work.mkdir(); output.mkdir()
        with self.assertRaisesRegex(DependencyError, 'require-isolated-stage'):
            inputs.prepare(self.owner, work, output, 'rust')
        (self.app / 'build.rs').write_bytes(b'fn main() { panic!(); }\n')
        with self.assertRaisesRegex(DependencyError, 'build-script-drift'):
            authoring.status(self.owner)
        self.assertEqual((self.owner / inputs.LOCK).read_bytes(), candidate.read_bytes())

    def test_tampered_or_missing_cas_fails_closed_without_using_original_sources(self):
        candidate, lock, _result = self.reviewed()
        row = next(item for item in lock['artifacts'] if item['metadata'].get('package') == 'resource')['files'][0]
        path = Store(self.owner / 'dependency-inputs/objects', create=False).path(row['digest'])
        raw = path.read_bytes()
        path.write_bytes(b'tampered')
        with self.assertRaisesRegex(DependencyError, 'artifact-integrity'):
            authoring.status(self.owner)
        path.write_bytes(raw); path.unlink()
        with self.assertRaisesRegex(DependencyError, 'artifact-missing-resolve-explicitly'):
            authoring.status(self.owner)
        self.assertEqual((self.owner / inputs.LOCK).read_bytes(), candidate.read_bytes())

    def test_sdk_vendor_drift_stops_resolver_before_any_command(self):
        target = next(path for path in (self.app / 'vendor/lsf').rglob('*.rs'))
        target.write_bytes(target.read_bytes() + b'\n// mutated\n')
        with patch.object(native, 'run_bounded') as run:
            with self.assertRaisesRegex(ValueError, 'vendored SDK changed'):
                native.resolve(self.owner, self.root / 'candidate', cargo=self.tool)
        run.assert_not_called()

    def test_inner_descriptor_and_shadow_capture_fail_before_resolution_or_frontend(self):
        self.nested()
        inner = self.app / 'latent.project.json'
        inner.write_bytes((self.owner / 'latent.project.json').read_bytes())
        with patch.object(native, 'run_bounded') as run, patch.object(frontend, 'run_bounded_result') as selected:
            for entry in (self.owner, self.app):
                code, _out, err = self.call('resolve', entry, '--candidate', self.root / 'candidate', '--cargo', self.tool)
                self.assertEqual(code, 1); self.assertIn('ambiguous-project-descriptor', err)
                code, _out, err = self.call('test', entry, '--workspace', 'rust-owned')
                self.assertEqual(code, 1); self.assertIn('ambiguous-project-descriptor', err)
            run.assert_not_called(); selected.assert_not_called()
        inner.unlink()
        (self.app / inputs.MANIFEST).write_bytes(b'{}')
        with self.assertRaisesRegex(DependencyError, 'ambiguous-application-lock'):
            authoring.seal(self.owner)

    def test_private_resolver_environment_is_explicit_and_not_reflected_in_receipts(self):
        registries = self.root / 'private-registry.json'
        registries.write_bytes(canonical({'registries': {'team': {'index': 'sparse+https://registry.example.invalid/index/'}}}))
        with patch.dict(os.environ, {'CARGO_REGISTRIES_TEAM_TOKEN': 'private-team-token',
                'CARGO_REGISTRIES_UNSELECTED_TOKEN': 'unselected-private-token', 'RUSTC_WRAPPER': 'private-wrapper',
                'GIT_CONFIG_GLOBAL': 'ambient-private-git-config'}, clear=False):
            candidate, lock = self.capture(registry_config=registries)
        for _command, cwd, environment, seconds, _maximum in self.calls:
            self.assertEqual(environment['CARGO_REGISTRIES_TEAM_TOKEN'], 'private-team-token')
            self.assertNotIn('CARGO_REGISTRIES_UNSELECTED_TOKEN', environment)
            self.assertNotIn('RUSTC_WRAPPER', environment)
            self.assertEqual(environment['GIT_CONFIG_NOSYSTEM'], '1')
            self.assertEqual(environment['GIT_TERMINAL_PROMPT'], '0')
            self.assertNotEqual(environment['GIT_CONFIG_GLOBAL'], 'ambient-private-git-config')
            self.assertLessEqual(seconds, 600)
            if _command[1] != '--version':
                self.assertFalse(cwd.is_relative_to(self.owner))
        raw = canonical(authoring.resolved(self.owner, candidate, lock)) + candidate.read_bytes()
        self.assertNotIn(b'private-team-token', raw)
        self.assertNotIn(b'unselected-private-token', raw)
        self.assertNotIn(b'ambient-private-git-config', raw)

    def test_private_configuration_inside_owner_or_credential_url_is_rejected(self):
        for index in ('https://user:password@example.invalid/index', 'https://example.invalid/index?token=private'):
            config = self.root / ('registry-' + secrets.token_hex(8))
            config.write_bytes(canonical({'registries': {'team': {'index': index}}}))
            with patch.object(native, 'run_bounded') as run:
                with self.assertRaisesRegex(DependencyError, 'credentials-or-endpoint-denied'):
                    native.resolve(self.owner, self.root / 'candidate', cargo=self.tool, registry_config=config)
                run.assert_not_called()
        inside = self.owner / 'private.json'
        inside.write_bytes(canonical({'registries': {}}))
        with self.assertRaisesRegex(DependencyError, 'outside-project'):
            native.resolve(self.owner, self.root / 'candidate', cargo=self.tool, registry_config=inside)

    def test_outside_path_matching_sdk_coordinates_cannot_bypass_executable_approval(self):
        import tomllib
        baseline = tomllib.loads((project.ROOT / 'tools/rust_capsule.lock').read_text())['package']
        selected = next(row for row in baseline if 'source' not in row and 'checksum' not in row
                        and row['name'] != 'my-greeting')
        metadata = self.metadata()
        package = next(row for row in metadata['packages'] if row['id'] == 'outside')
        package.update(name=selected['name'], version=selected['version'],
                       targets=[{'kind': ['proc-macro'], 'src_path': str(self.library / 'src/lib.rs')}])
        vendor = self.root / 'vendor'; vendor.mkdir()
        artifacts, _graph = native.analyze(metadata, self.app, vendor, {})
        captured = next(row for row in artifacts if row['metadata']['package'] == selected['name'])
        self.assertEqual(captured['role'], 'build-tool')
        self.assertFalse(captured['metadata']['sdkCompilerInput'])
        self.assertEqual(captured['metadata']['executableKinds'], [['proc-macro']])

    def test_features_and_pinned_target_are_bound_and_unsupported_selection_never_runs(self):
        candidate, lock = self.capture(selection={'features': ['pure', 'pure'], 'noDefaultFeatures': True})
        self.assertEqual(lock['selection']['features'], ['pure'])
        selected = next(command for command, *_rest in self.calls if '--filter-platform' in command)
        self.assertIn('--locked', selected); self.assertIn('--no-default-features', selected)
        self.assertEqual(selected[selected.index('--filter-platform') + 1], 'wasm32-unknown-unknown')
        self.assertEqual(candidate.read_bytes(), canonical(lock) + b'\n')
        for selection in ({'target': 'x86_64-linux'}, {'runtimeProfile': 'tokio-unqualified'}, {'features': ['--exec']}):
            with patch.object(native, 'run_bounded') as run:
                with self.assertRaises(DependencyError):
                    native.resolve(self.owner, self.root / 'unsupported-candidate', cargo=self.tool, selection=selection)
                run.assert_not_called()

    def test_cli_resolution_success_and_failure_keep_immutable_separate_redacted_receipts(self):
        candidate = self.root / 'candidate.json'
        with patch.object(native, 'run_bounded', side_effect=self.resolver_command):
            code, out, err = self.call('resolve', self.owner, '--candidate', candidate, '--cargo', self.tool)
        self.assertEqual((code, err), (0, ''))
        result = json.loads(out)
        self.assertTrue(result['reviewRequired']); self.assertFalse(result['compilerExecution'])
        receipt = candidate.with_name(candidate.name + '.receipt.json')
        first = receipt.read_bytes()
        with patch.object(native, 'run_bounded') as run:
            code, _out, err = self.call('resolve', self.owner, '--candidate', candidate, '--cargo', self.tool)
        self.assertEqual(code, 1); self.assertIn('use-fresh-attempt', err); run.assert_not_called()
        self.assertEqual(receipt.read_bytes(), first)
        failed = self.root / 'failed-candidate.json'
        with patch.object(native, 'run_bounded', side_effect=ValueError('private-team-token')):
            code, _out, err = self.call('resolve', self.owner, '--candidate', failed, '--cargo', self.tool)
        self.assertEqual(code, 1); self.assertNotIn('private-team-token', err)
        failure = failed.with_name(failed.name + '.failed.json').read_bytes()
        self.assertNotIn(b'private-team-token', failure)
        self.assertFalse(json.loads(failure)['automaticReplay'])

    def test_source_mutation_during_resolution_preserves_prior_reviewed_inputs(self):
        candidate, _lock, _result = self.reviewed()
        previous = {name: (self.owner / name).read_bytes() for name in (inputs.MANIFEST, inputs.LOCK, 'cargo-resolved.lock.json')}
        def changed(command, *arguments):
            result = self.resolver_command(command, *arguments)
            if command[1] == 'vendor':
                path = self.app / 'src/lib.rs'
                path.write_bytes(path.read_bytes() + b'\n// concurrent source change\n')
            return result
        with patch.object(native, 'run_bounded', side_effect=changed):
            with self.assertRaisesRegex(DependencyError, 'resolution-input-mutated'):
                native.resolve(self.owner, self.root / 'changed-candidate', cargo=self.tool)
        self.assertEqual({name: (self.owner / name).read_bytes() for name in previous}, previous)
        self.assertEqual((self.owner / inputs.LOCK).read_bytes(), candidate.read_bytes())

    def test_candidate_cannot_overwrite_source_or_reviewed_lock(self):
        for candidate in (self.owner / 'new-input.json', self.app / 'src/new.rs', self.owner / inputs.LOCK,
                          self.owner / 'target/../src/escaped-candidate.json'):
            with patch.object(native, 'run_bounded') as run:
                with self.assertRaisesRegex(DependencyError, 'cannot-overwrite-reviewed-input'):
                    native.resolve(self.owner, candidate, cargo=self.tool)
                run.assert_not_called()

    def test_rejected_candidate_location_cannot_write_a_failure_sibling_in_source(self):
        candidate = self.owner / 'target/../src/escaped-candidate.json'
        with patch.object(native, 'run_bounded') as run:
            code, _out, err = self.call('resolve', self.owner, '--candidate', candidate, '--cargo', self.tool)
        self.assertEqual(code, 1); self.assertIn('cannot-overwrite-reviewed-input', err)
        run.assert_not_called()
        self.assertFalse((self.app / 'src/escaped-candidate.json').exists())
        self.assertFalse((self.app / 'src/escaped-candidate.json.failed.json').exists())

    def test_candidate_inside_original_library_cannot_write_success_or_failure_source_bytes(self):
        candidate = self.library / 'capture-attempt.json'
        original = project.snapshot(self.library)
        with patch.object(native, 'run_bounded', side_effect=self.resolver_command):
            code, _out, err = self.call('resolve', self.owner, '--candidate', candidate, '--cargo', self.tool)
        self.assertEqual(code, 1); self.assertIn('candidate-inside-captured-source', err)
        self.assertEqual(project.snapshot(self.library), original)
        self.assertFalse(candidate.exists())
        self.assertFalse(candidate.with_name(candidate.name + '.failed.json').exists())

    def test_success_receipt_cannot_rebind_a_candidate_to_concurrently_changed_native_inputs(self):
        candidate, lock = self.capture()
        (self.app / 'Cargo.lock').write_bytes(b'changed after resolution')
        with self.assertRaisesRegex(DependencyError, 'native-lock-drift'):
            authoring.resolved(self.owner, candidate, lock)
        (self.app / 'Cargo.lock').write_bytes(self.original['Cargo.lock'])
        declaration = self.owner / inputs.MANIFEST
        declaration.write_bytes(declaration.read_bytes() + b' ')
        with self.assertRaisesRegex(DependencyError, 'candidate-resolution-drift'):
            authoring.resolved(self.owner, candidate, lock)

    def test_selected_frontend_test_watch_keep_outer_identity_and_uncertain_exit_once(self):
        self.nested(); self.reviewed()
        selected = self.root / 'reviewed-frontend'
        selected.write_bytes(b'reviewed executable identity; dispatch boundary is mocked')
        identity = digest(selected.read_bytes())
        raw = b'{"schemaVersion":"latent.dev.result.v1","code":"original-operation-unknown","uncertain":true}\n'
        seen = []
        def invoke(command, cwd, environment, seconds, maximum):
            seen.append((command, cwd, seconds, maximum))
            return subprocess.CompletedProcess(command, 5, raw, b'')
        with patch.object(frontend, 'run_bounded_result', side_effect=invoke), \
                patch.object(cli, 'main', side_effect=AssertionError('selected frontend fell back to source')):
            for action in ('test', 'watch'):
                code, out, err = self.call(action, self.app, '--workspace', 'rust-owned', '--select', 'greeting',
                    '--frontend', selected, '--frontend-sha256', identity, '--frontend-timeout', '315')
                self.assertEqual((code, out.encode(), err), (5, raw, ''))
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0][0][1:3], ['dev', 'test'])
        self.assertEqual(seen[1][0][1:3], ['dev', 'up']); self.assertIn('--watch', seen[1][0])
        for command, cwd, seconds, maximum in seen:
            self.assertEqual((command[0], cwd, seconds, maximum), (str(selected), self.owner, 315, 1024 * 1024))
            self.assertEqual(command[command.index('--project') + 1], str(self.owner))
        receipts = [json.loads(path.read_bytes()) for path in (self.owner / authoring.STATE).glob('receipt-*.json')]
        self.assertEqual(len(receipts), 2)
        self.assertTrue(all(row['exitCode'] == 5 and not row['automaticReplay'] for row in receipts))

    def test_source_frontend_actual_parser_receives_selection_without_replaying_unknown_work(self):
        self.nested(); self.reviewed()
        seen = []
        def invoke(args):
            seen.append(args)
            self.assertEqual((args.group, args.command, args.project), ('dev', 'test', self.owner))
            self.assertEqual(args.select, ['greeting'])
            raise common.DevError('original-operation-unknown', uncertain=True)
        with patch.object(cli, 'dispatch', side_effect=invoke):
            code, out, err = self.call('test', self.owner, '--workspace', 'rust-owned', '--select', 'greeting')
        self.assertEqual((code, err), (5, ''))
        self.assertEqual(json.loads(out)['code'], 'original-operation-unknown')
        self.assertEqual(len(seen), 1)

    def test_wrong_or_partial_frontend_identity_never_dispatches_or_falls_back(self):
        self.nested(); self.reviewed()
        selected = self.root / 'selected-frontend'
        selected.write_bytes(b'reviewed executable identity')
        with patch.object(frontend, 'run_bounded_result') as run, patch.object(cli, 'main') as source:
            for options in (('--frontend', selected), ('--frontend-sha256', digest(b'absent')),
                            ('--frontend', selected, '--frontend-sha256', digest(b'changed'))):
                code, _out, err = self.call('test', self.owner, '--workspace', 'rust-owned', *options)
                self.assertEqual(code, 1); self.assertIn('authoring-', err)
            run.assert_not_called(); source.assert_not_called()

    def test_receipt_io_failure_preserves_selected_exit_five_and_original_result(self):
        self.nested(); self.reviewed()
        selected = self.root / 'selected-frontend'
        selected.write_bytes(b'reviewed executable identity')
        raw = b'{"schemaVersion":"latent.dev.result.v1","code":"original-operation-unknown","uncertain":true}\n'
        with patch.object(frontend, 'run_bounded_result', return_value=subprocess.CompletedProcess([], 5, raw, b'')) as run, \
                patch.object(authoring, 'record', side_effect=OSError('private-io-details')):
            code, out, err = self.call('test', self.owner, '--workspace', 'rust-owned',
                '--frontend', selected, '--frontend-sha256', digest(selected.read_bytes()))
        self.assertEqual((code, out.encode(), run.call_count), (5, raw, 1))
        self.assertNotIn('private-io-details', err)

    def test_staged_recipe_import_and_consumer_need_explicit_selected_frontend(self):
        from tools.dev_tool_distribution import recipe
        self.nested(); self.reviewed()
        selected = self.root / 'selected-frontend'
        selected.write_bytes(b'explicit reviewed executable identity; process boundary is mocked')
        identity = digest(selected.read_bytes())
        payload = self.root / 'payload'; payload.mkdir()
        recipe(payload, 'rust')
        staged = payload / 'recipe'
        metadata = self.root / 'native-metadata.json'
        metadata.write_bytes(canonical(self.metadata()))
        script = '''import json,pathlib,subprocess,sys
root,project,selected,identity,cargo,metadata=map(str,sys.argv[1:])
sys.path.insert(0,root)
from tools import rust_capsule,rust_application_dependencies as native,guest_authoring_frontend as frontend
from tools.build_snapshot import digest
called=[]
raw=b'{"schemaVersion":"latent.dev.result.v1","code":"original-operation-unknown","uncertain":true}\\n'
def resolve(command,cwd,env,seconds,maximum):
 if command[1]=='--version':
  output=b'cargo 1.97.1 (staged-source-boundary-model)'
 elif command[1]=='metadata':
  output=pathlib.Path(metadata).read_bytes()
 elif command[1]=='vendor':
  pathlib.Path(command[-1]).mkdir()
  output=b''
 else:
  raise AssertionError('unexpected staged resolver command')
 return subprocess.CompletedProcess(command,0,output,b'')
native.run_bounded=resolve
candidate=pathlib.Path(metadata).with_name('staged-candidate.json')
assert rust_capsule.main(['resolve',project,'--candidate',str(candidate),'--cargo',cargo])==0
assert rust_capsule.main(['review-lock',project,'--candidate',str(candidate),'--expect',digest(candidate.read_bytes())])==0
assert rust_capsule.main(['dependencies',project])==0
def run(command,cwd,env,seconds,maximum):
 assert command[0]==selected and str(cwd)==project and command[1:3]==['dev','test']
 called.append(command)
 return subprocess.CompletedProcess(command,5,raw,b'')
frontend.run_bounded_result=run
base=['test',project,'--workspace','rust-owned']
assert rust_capsule.main(base)==1 and called==[]
assert rust_capsule.main([*base,'--frontend',selected,'--frontend-sha256',identity])==5
assert len(called)==1 and 'tools.dev_workflow.cli' not in sys.modules
for name,module in tuple(sys.modules.items()):
 if name.startswith('tools.') and getattr(module,'__file__',None):
  assert pathlib.Path(module.__file__).resolve().is_relative_to(pathlib.Path(root)),name
print('staged-rust-selected-frontend-original-exit-five')
'''
        result = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(staged), str(self.owner), str(selected), identity,
                                 str(self.tool), str(metadata)],
            cwd=payload, stdin=subprocess.DEVNULL, capture_output=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace')[:4096])
        self.assertEqual(result.stdout.splitlines()[-1], b'staged-rust-selected-frontend-original-exit-five')
        self.assertIn(b'authoring-staged-recipe-requires-explicit-frontend', result.stderr)


if __name__ == '__main__':
    unittest.main()
