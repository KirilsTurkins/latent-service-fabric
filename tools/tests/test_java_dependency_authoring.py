"""Real Java capture/review/CLI controls; JAR headers do not qualify emitted code."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import application_dependencies as inputs, guest_dependency_inputs, java_capsule
from tools import java_capsule_project as project, java_dependency_authoring as authoring
from tools import java_dependency_resolution as native
from tools.application_dependency_store import DependencyError
from tools.build_snapshot import canonical, digest
from tools.dev_tool_distribution import recipe
from tools.dev_workflow import cli, common, project as dev_project
from tools.java_application_dependencies import classpath, deterministic_jar, selected_entries
from tools.rust_capsule_project import snapshot
from tools.tests.test_dev_contracts import descriptor


class Output(io.StringIO):
    @property
    def buffer(self):
        return self

    def write(self, value):
        return super().write(value.decode('utf-8') if isinstance(value, bytes) else value)


class JavaDependencyAuthoring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix='java-authoring-source-')
        cls.addClassCleanup(temporary.cleanup)
        cls.original = snapshot(project.create(Path(temporary.name) / 'app', 'greeting'))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='java-authoring-control-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.owner = self.app = self.root / 'project'
        self.copy_application(self.app, self.original)
        self.sdk = (self.app / 'sdk-lock.json').read_bytes()
        self.primary = self.root / 'developer-primary.jar'
        self.child = self.root / 'developer-child.jar'
        self.primary.write_bytes(deterministic_jar({'outside/Primary.class': self.header(), 'data/message.txt': b'captured snowman \xe2\x98\x83'}))
        self.child.write_bytes(deterministic_jar({'outside/Child.class': self.header()}))

    def header(self):
        return b'\xca\xfe\xba\xbe' + struct.pack('>HH', 0, 69) + b'source-control-only'

    def copy_application(self, destination, files):
        destination.mkdir()
        for name, raw in files.items():
            path = destination / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)

    def command(self, *arguments):
        stdout, stderr = Output(), Output()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = java_capsule.main(list(map(str, arguments)))
        return code, stdout.getvalue(), stderr.getvalue()

    def selected(self):
        authoring.edit(self.owner, 'add-local', local_id='unknown/private-child/1', jar=self.child)
        authoring.edit(self.owner, 'add-local', local_id='unknown/private-primary/1', jar=self.primary,
                       dependencies=('unknown/private-child/1',))

    def capture(self, name='candidate.json'):
        candidate = self.root / name
        with patch.object(native, 'run_bounded_result', side_effect=AssertionError('local capture executed a host tool')):
            lock = native.resolve(self.owner, candidate)
        return candidate, lock

    def accept(self, name='candidate.json'):
        candidate, lock = self.capture(name)
        authoring.review(self.owner, candidate, digest(candidate.read_bytes()))
        return candidate, lock

    def nested(self):
        self.owner = self.root / 'nested'
        self.owner.mkdir()
        self.app = self.owner / 'app'
        self.copy_application(self.app, self.original)
        value = descriptor()
        value.update(language='java', inputRoots=['app'])
        value['template']['ownerIssue'] = dev_project.LANGUAGES['java']
        value['build']['workingDirectory'] = 'app'
        (self.owner / 'latent.project.json').write_bytes(common.encode(value))

    def test_actual_cli_captures_reviews_and_rebuilds_local_transitives_without_a_host_jvm(self):
        for identity, jar, extra in (('unknown/private-child/1', self.child, []),
                                     ('unknown/private-primary/1', self.primary, ['--depends', 'unknown/private-child/1'])):
            code, stdout, stderr = self.command('add-local', self.owner, '--id', identity, '--jar', jar, *extra)
            self.assertEqual((code, stderr), (0, ''))
            self.assertTrue(json.loads(stdout)['reviewRequired'])
        candidate = self.root / 'cli-candidate.json'
        with patch.object(native, 'run_bounded_result', side_effect=AssertionError('local JAR executed on host')):
            code, stdout, stderr = self.command('resolve', self.owner, '--candidate', candidate)
        self.assertEqual((code, stderr), (0, ''))
        self.assertFalse((self.owner / inputs.LOCK).exists())
        receipt = json.loads(stdout)
        self.assertEqual(receipt['candidateDigest'], digest(candidate.read_bytes()))
        self.assertTrue(receipt['previousLockPreserved'])
        self.assertEqual(self.command('review-lock', self.owner, '--candidate', candidate, '--expect', receipt['candidateDigest'])[0], 0)
        self.primary.unlink(); self.child.unlink()
        self.assertEqual(json.loads(self.command('dependencies', self.owner)[1])['status'], 'verified')
        work, output = self.root / 'work', self.root / 'output'; work.mkdir(); output.mkdir()
        with patch.object(inputs, 'fetch', side_effect=AssertionError('offline closure contacted a repository')):
            closure = inputs.prepare(self.owner, work, output, 'java')
            jars, selection = classpath(closure, self.root / 'classpath')
        self.assertEqual(len(jars), 2)
        self.assertEqual(selected_entries(jars[1].read_bytes(), 25)['data/message.txt'], b'captured snowman \xe2\x98\x83')
        self.assertEqual(selection['resources'][0]['owner'], 'unknown/private-primary/1')
        self.assertEqual((self.app / 'sdk-lock.json').read_bytes(), self.sdk)
        closure.check_unchanged()

    def test_maven_add_exclusion_update_and_remove_keep_sdk_and_reviewed_lock_immutable(self):
        self.selected(); self.accept()
        reviewed = (self.owner / inputs.LOCK).read_bytes()
        code, _stdout, stderr = self.command('add', self.owner, 'outside.example:pure:1.2.3', '--scope', 'compile', '--exclude', 'unwanted:plugin')
        self.assertEqual((code, stderr), (0, ''))
        value = native.declarations(inputs.document(self.app / native.DECLARATIONS))
        self.assertEqual(value['dependencies'][0]['exclusions'], [{'group': 'unwanted', 'name': 'plugin'}])
        self.assertEqual(self.command('update', self.owner, 'outside.example:pure', '--version', '1.2.4')[0], 0)
        self.assertEqual(self.command('remove', self.owner, 'outside.example:pure')[0], 0)
        self.assertEqual((self.owner / inputs.LOCK).read_bytes(), reviewed)
        self.assertEqual((self.app / 'sdk-lock.json').read_bytes(), self.sdk)

    def test_exact_candidate_review_rejects_tamper_and_preserves_prior_lock(self):
        self.selected(); self.accept()
        reviewed = (self.owner / inputs.LOCK).read_bytes()
        candidate, _lock = self.capture('next.json')
        identity = digest(candidate.read_bytes()); candidate.write_bytes(candidate.read_bytes() + b' ')
        with self.assertRaisesRegex(DependencyError, 'review-drift'):
            authoring.review(self.owner, candidate, identity)
        self.assertEqual((self.owner / inputs.LOCK).read_bytes(), reviewed)

    def test_cas_tamper_is_rejected_before_review_or_materialization(self):
        self.selected(); candidate, lock = self.capture()
        selected = next(row for row in lock['artifacts'] if row['id'] == 'unknown/private-child/1')
        from tools.application_dependency_store import Store
        Store(self.owner / 'dependency-inputs/objects').path(selected['original']['digest']).write_bytes(b'changed')
        with self.assertRaises(DependencyError):
            authoring.review(self.owner, candidate, digest(candidate.read_bytes()))
        self.assertFalse((self.owner / inputs.LOCK).exists())

    def test_missing_transitive_never_publishes_resolution_or_candidate(self):
        authoring.edit(self.owner, 'add-local', local_id='unknown/private-primary/1', jar=self.primary, dependencies=('missing/child',))
        with self.assertRaisesRegex(DependencyError, 'graph-not-closed'):
            self.capture()
        self.assertFalse((self.owner / inputs.MANIFEST).exists())
        self.assertFalse((self.app / native.RESOLUTION).exists())
        self.assertFalse((self.owner / inputs.LOCK).exists())

    def test_original_jar_mutation_during_capture_keeps_all_previous_reviewed_inputs(self):
        self.selected(); self.accept()
        original = {name: (self.owner / name).read_bytes() for name in (inputs.MANIFEST, inputs.LOCK, native.RESOLUTION)}
        real = native.capture_resources
        def mutate(*args, **kwargs):
            result = real(*args, **kwargs)
            self.primary.write_bytes(deterministic_jar({'outside/Changed.class': self.header()}))
            return result
        with patch.object(native, 'capture_resources', side_effect=mutate):
            with self.assertRaisesRegex(DependencyError, 'input-mutated'):
                self.capture('mutated.json')
        self.assertEqual({name: (self.owner / name).read_bytes() for name in original}, original)
        self.assertFalse((self.root / 'mutated.json').exists())

    def test_inside_project_jar_is_accepted_only_with_exact_declaration_and_reviewed_bytes(self):
        jar = self.app / 'lib' / 'private.jar'; jar.parent.mkdir(); jar.write_bytes(self.child.read_bytes())
        authoring.edit(self.owner, 'add-local', local_id='developer/inside/1', jar=jar)
        self.accept()
        project.validate(snapshot(self.app))
        jar.write_bytes(deterministic_jar({'outside/Changed.class': self.header()}))
        with self.assertRaisesRegex(ValueError, 'uncaptured'):
            project.validate(snapshot(self.app))
        with self.assertRaisesRegex(DependencyError, 'jar-drift'):
            authoring.status(self.owner)

    def test_undeclared_inside_project_jar_and_build_plugins_remain_denied(self):
        for name in ('undeclared.jar', 'build.gradle', 'pom.xml'):
            with self.subTest(name=name):
                target = self.app / name; target.write_bytes(self.child.read_bytes())
                with self.assertRaisesRegex(ValueError, 'uncaptured'):
                    project.validate(snapshot(self.app))
                target.unlink()

    def test_teavm_application_host_provider_is_denied_before_declaration_write(self):
        jar = self.root / 'plugin.jar'
        jar.write_bytes(deterministic_jar({'META-INF/services/org.teavm.vm.spi.TeaVMPlugin': b'private.RunOnHost\n'}))
        code, stdout, stderr = self.command('add-local', self.owner, '--id', 'developer/plugin', '--jar', jar)
        self.assertEqual(code, 1); self.assertEqual(stdout, '')
        self.assertEqual(json.loads(stderr)['reason'], 'java-executable-compiler-provider-requires-isolation')
        self.assertFalse((self.app / native.DECLARATIONS).exists())

    def test_candidates_cannot_overwrite_any_source_sdk_or_reviewed_lock(self):
        self.selected(); self.accept()
        before = snapshot(self.app)
        for name in ('sdk-lock.json', inputs.LOCK, 'src/dev/latent/app/Capsule.java'):
            with self.subTest(name=name), self.assertRaisesRegex(DependencyError, 'cannot-overwrite'):
                native.resolve(self.owner, self.owner / name)
        self.assertEqual(snapshot(self.app), before)

    def test_sdk_drift_is_rejected_before_any_dependency_edit_or_resolver_execution(self):
        target = self.app / 'vendor/lsf/NOTICE'; target.write_bytes(target.read_bytes() + b'changed')
        code, stdout, stderr = self.command('add', self.owner, 'outside.example:pure:1.2.3')
        self.assertEqual((code, stdout), (1, ''))
        self.assertEqual(json.loads(stderr)['reason'], 'java-authoring-invalid-or-unavailable-input')
        self.assertFalse((self.app / native.DECLARATIONS).exists())

    def test_duplicate_coordinate_repository_credential_slot_and_dynamic_versions_fail_without_edits(self):
        authoring.edit(self.owner, 'add', coordinate='outside.example:pure:1.2.3')
        before = (self.app / native.DECLARATIONS).read_bytes()
        for coordinate in ('outside.example:pure:1.2.4', 'outside.example:other:1.0-SNAPSHOT', 'outside.example:other:1.+'):
            with self.subTest(coordinate=coordinate), self.assertRaises(DependencyError):
                authoring.edit(self.owner, 'add', coordinate=coordinate)
            self.assertEqual((self.app / native.DECLARATIONS).read_bytes(), before)
        value = json.loads(before)
        value['repositories'] += [{'id': 'private-feed', 'url': 'https://example.test/maven'},
                                  {'id': 'private_feed', 'url': 'https://example.test/other'}]
        with self.assertRaisesRegex(DependencyError, 'credential-slot'):
            native.declarations(value)

    def test_private_urls_and_failure_receipts_never_echo_credentials(self):
        secret = 'not-public-private-password'
        code, stdout, stderr = self.command('add', self.owner, 'outside.example:pure:1.2.3',
            '--repository-id', 'private', '--repository-url', 'https://user:' + secret + '@example.test/maven')
        self.assertEqual((code, stdout), (1, ''))
        self.assertNotIn(secret, stderr)
        for receipt in (self.owner / authoring.STATE).glob('receipt-*.json'):
            self.assertNotIn(secret.encode(), receipt.read_bytes())
        self.assertFalse((self.app / native.DECLARATIONS).exists())

    def test_native_graph_identity_and_local_declaration_edits_require_fresh_resolution(self):
        self.selected(); self.accept()
        value = inputs.document(self.app / native.DECLARATIONS)
        value['localJars'][0]['path'] = '../other.jar'
        (self.app / native.DECLARATIONS).write_bytes(canonical(value))
        with self.assertRaises(DependencyError):
            authoring.status(self.owner)

    def test_nested_capture_binds_outer_lock_native_inputs_and_both_entrypoints(self):
        self.nested(); self.selected(); candidate, lock = self.accept()
        self.assertTrue(all(row['path'].startswith('app/') for row in lock['nativeLocks']))
        self.assertFalse((self.app / inputs.LOCK).exists())
        self.assertEqual(authoring.status(self.owner)['capturedInputIdentity'], authoring.status(self.app)['capturedInputIdentity'])
        captured = guest_dependency_inputs.capture_source(self.app, 'java')
        self.assertEqual(captured.dependency_root, self.owner)
        project.validate(captured.files)
        self.assertEqual(captured.files[inputs.LOCK], candidate.read_bytes())
        captured.check_unchanged()

    def test_inner_descriptor_shadow_denies_every_edit_test_and_watch_before_dispatch(self):
        self.nested()
        (self.app / 'latent.project.json').write_bytes((self.owner / 'latent.project.json').read_bytes())
        with patch.object(cli, 'main', side_effect=AssertionError('ambiguous layout reached controller')):
            for entry in (self.owner, self.app):
                for action in ('test', 'watch'):
                    code, _stdout, stderr = self.command(action, entry, '--workspace', 'sdk-java')
                    self.assertEqual(code, 1)
                    self.assertEqual(json.loads(stderr)['reason'], 'dependency-frontend-ambiguous-project-descriptor')

    def test_actual_source_frontend_preserves_uncertain_return_and_one_dispatch(self):
        self.nested(); self.selected(); self.accept()
        for action in ('test', 'watch'):
            for original, expected in ((5, 5), (130, 130), (37, 5)):
                with self.subTest(action=action, original=original), patch.object(cli, 'main', return_value=original) as controller, \
                        patch.object(authoring, 'record', wraps=authoring.record) as recorded:
                    code, stdout, stderr = self.command(action, self.owner, '--workspace', 'sdk-java', '--select', 'greeting')
                    self.assertEqual(code, expected); self.assertEqual((stdout, stderr), ('', ''))
                    self.assertEqual(controller.call_count, 1)
                    delegated = cli.parser().parse_args(controller.call_args[0][0])
                    self.assertEqual(delegated.project, self.owner)
                    if action == 'test':
                        self.assertEqual(delegated.select, ['greeting'])
                    else:
                        self.assertEqual(delegated.test_select, ['greeting'])
                    recorded.assert_called_once()
                    evidence = recorded.call_args.args[1]
                    self.assertEqual(evidence['stage'], 'java-dependency-' + action)
                    self.assertEqual(evidence['automaticReplay'], False)
                    if original == 37:
                        self.assertEqual(evidence['originalFrontendExitCode'], 37)
                        self.assertEqual(evidence['reason'], 'authoring-frontend-exit-unrecognized-inspect-workspace-status')

    def test_staged_recipe_runs_local_capture_and_review_without_checkout_imports(self):
        payload = self.root / 'payload'; recipe(payload, 'java')
        candidate = self.root / 'staged-candidate.json'
        program = """import json, pathlib, sys
sys.path[:] = [sys.argv[1]] + [p for p in sys.path if 'site-packages' not in p]
from tools import java_capsule
project, jar, candidate = sys.argv[2:]
assert java_capsule.main(['add-local', project, '--id', 'developer/staged/1', '--jar', jar]) == 0
assert java_capsule.main(['resolve', project, '--candidate', candidate]) == 0
from tools.build_snapshot import digest
assert java_capsule.main(['review-lock', project, '--candidate', candidate, '--expect', digest(pathlib.Path(candidate).read_bytes())]) == 0
pathlib.Path(jar).unlink()
assert java_capsule.main(['dependencies', project]) == 0
root = pathlib.Path(sys.argv[1]).resolve()
for name, module in sys.modules.items():
    if name == 'tools' or name.startswith('tools.'):
        location = getattr(module, '__file__', None)
        assert location is None or pathlib.Path(location).resolve().is_relative_to(root), name
"""
        completed = subprocess.run([str(Path(sys.executable).resolve(strict=True)), '-I', '-B', '-c', program,
                                   str(payload / 'recipe'), str(self.owner), str(self.child), str(candidate)],
                                  cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        self.assertEqual((self.app / 'sdk-lock.json').read_bytes(), self.sdk)
        self.assertIn(b'"status":"verified"', completed.stdout)


if __name__ == '__main__':
    unittest.main()
