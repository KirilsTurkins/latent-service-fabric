"""Actual C declaration/capture/review lifecycle and existing frontend trust boundaries."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import copy
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import ssl
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import HTTPSHandler, build_opener

from tools import application_dependencies as inputs, c_capsule, c_dependency_authoring as authoring
from tools.application_dependency_store import DependencyError, Store
from tools.build_snapshot import canonical, digest
from tools.c_application_dependencies import selected
from tools.dev_workflow import build_client, cli, common, dependencies, project, snapshot, state
from tools.tests.test_dev_contracts import descriptor


class CDependencyAuthoring(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='lsf-c-dependency-lifecycle-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        (self.project / 'src').mkdir()
        (self.project / 'src/main.c').write_bytes(b'int main(void) { return 0; }\n')
        self.sdk = canonical({'formatVersion': 1, 'language': 'c', 'reviewedCompiler': 'zig-0.16.0'})
        (self.project / 'sdk-lock.json').write_bytes(self.sdk)
        self.library = self.root / 'outside-private-library'
        self.library.mkdir()
        (self.library / 'pure.c').write_bytes(b'#include "transitive.h"\nint pure(int x) { return helper(x); }\n')
        (self.library / 'transitive.h').write_bytes(b'static int helper(int x) { return x * 7; }\n')
        self.artifact = {'id': 'developer/unregistered-pure/1', 'role': 'application', 'format': 'directory',
            'mount': 'dependencies/unknown', 'source': {'path': '../outside-private-library'}, 'dependencies': [],
            'metadata': {'cSources': ['pure.c'], 'includeDirectories': ['.'], 'license': 'MIT'}}

    def declaration(self, artifact=None):
        path = self.root / ('artifact-' + secrets.token_hex(8) + '.json')
        path.write_bytes(canonical(artifact or self.artifact))
        return str(path)

    def call(self, *arguments):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = c_capsule.main([str(value) for value in arguments])
        return code, out.getvalue(), err.getvalue()

    def capture(self):
        if not (self.project / inputs.MANIFEST).exists():
            authoring.edit(self.project, 'add', [self.artifact], [])
        candidate = self.root / ('candidate-' + secrets.token_hex(8) + '.json')
        authoring.resolve(self.project, candidate)
        return candidate

    def review(self):
        candidate = self.capture()
        authoring.review(self.project, candidate, digest(candidate.read_bytes()))
        return candidate

    def descriptor(self):
        value = descriptor()
        value.update(language='c')
        value['template']['ownerIssue'] = project.LANGUAGES['c']
        value['inputRoots'] = ['app']
        value['build']['workingDirectory'] = 'app'
        app = self.project / 'app'
        (app / 'src').mkdir(parents=True, exist_ok=True)
        if not (app / 'sdk-lock.json').exists():
            (app / 'sdk-lock.json').write_bytes(self.sdk)
        if not (app / 'src/main.c').exists():
            (app / 'src/main.c').write_bytes((self.project / 'src/main.c').read_bytes())
        (self.project / 'latent.project.json').write_bytes(common.encode(value))
        return value

    def test_actual_new_add_resolve_review_offline_selected_sources_preserve_sdk(self):
        real = self.root / 'real-c'
        code, _, _ = self.call('new', real)
        self.assertEqual(code, 0)
        sdk = (real / 'sdk-lock.json').read_bytes()
        code, out, err = self.call('add', real, '--artifact', self.declaration())
        self.assertEqual((code, err), (0, ''))
        added = json.loads(out)
        self.assertTrue(added['reviewRequired'])
        self.assertFalse(added['compilerExecution'])
        self.assertFalse((real / inputs.LOCK).exists())
        candidate = self.root / 'real-candidate.json'
        code, out, _ = self.call('resolve', real, '--candidate', candidate)
        self.assertEqual(code, 0)
        lock = json.loads(candidate.read_bytes())
        self.assertEqual(lock['artifacts'][0]['metadata']['license'], 'MIT')
        original = lock['artifacts'][0]['original']
        self.assertIn('digest', original)
        self.assertNotIn('outside-private-library', out + candidate.read_text())
        shutil.rmtree(self.library)
        expected = digest(candidate.read_bytes())
        with patch.object(inputs, 'fetch', side_effect=AssertionError('offline review contacted a feed')):
            code, out, err = self.call('review-lock', real, '--candidate', candidate, '--expect', expected)
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(json.loads(out)['candidateDigest'], expected)
        work, output = self.root / 'work', self.root / 'output'
        work.mkdir(); output.mkdir()
        closure = inputs.prepare(real, work, output, 'c')
        picked = selected(closure, compiler_digest=digest(b'compiler'), runtime_digest=digest(b'runtime'))
        self.assertEqual(picked.sources[0].read_bytes(), b'#include "transitive.h"\nint pure(int x) { return helper(x); }\n')
        self.assertTrue((picked.includes[0] / 'transitive.h').is_file())
        closure.check_unchanged()
        self.assertEqual((real / 'sdk-lock.json').read_bytes(), sdk)
        self.assertEqual((real / inputs.LOCK).read_bytes(), candidate.read_bytes())
        receipts = list((real / authoring.STATE).glob('receipt-*.json'))
        self.assertEqual(len(receipts), 3)
        self.assertTrue(all(json.loads(path.read_bytes())['status'] != 'failed' for path in receipts))

    def test_update_remove_each_require_new_review_and_keep_original_lock(self):
        self.review()
        old = (self.project / inputs.LOCK).read_bytes()
        previous = digest((self.project / inputs.MANIFEST).read_bytes())
        updated = copy.deepcopy(self.artifact)
        updated['metadata']['defines'] = {'PURE_FEATURE': '2'}
        result = authoring.edit(self.project, 'update', [updated], [updated['id']], expected=previous)
        self.assertTrue(result['previousLockPreserved'])
        self.assertEqual((self.project / inputs.LOCK).read_bytes(), old)
        with self.assertRaisesRegex(DependencyError, 'lock-drift'):
            authoring.status(self.project)
        self.review()
        new_lock = (self.project / inputs.LOCK).read_bytes()
        self.assertNotEqual(new_lock, old)
        authoring.edit(self.project, 'remove', [], [updated['id']])
        self.assertEqual((self.project / inputs.LOCK).read_bytes(), new_lock)
        with self.assertRaisesRegex(DependencyError, 'lock-drift'):
            authoring.status(self.project)
        self.review()
        self.assertEqual(authoring.status(self.project)['artifacts'], [])
        self.assertEqual((self.project / 'sdk-lock.json').read_bytes(), self.sdk)

    def test_closed_transitive_add_and_remove_are_atomic(self):
        child = copy.deepcopy(self.artifact)
        child.update(id='developer/public-headers/1', role='resource', mount='dependencies/public-headers')
        child['metadata'] = {'license': 'MIT'}
        parent = copy.deepcopy(self.artifact)
        parent['dependencies'] = [child['id']]
        with self.assertRaisesRegex(DependencyError, 'graph-not-closed'):
            authoring.edit(self.project, 'add', [parent], [])
        self.assertFalse((self.project / inputs.MANIFEST).exists())
        authoring.edit(self.project, 'add', [parent, child], [])
        before = (self.project / inputs.MANIFEST).read_bytes()
        with self.assertRaisesRegex(DependencyError, 'graph-not-closed'):
            authoring.edit(self.project, 'remove', [], [child['id']])
        self.assertEqual((self.project / inputs.MANIFEST).read_bytes(), before)
        authoring.edit(self.project, 'remove', [], [parent['id'], child['id']])
        self.assertEqual(json.loads((self.project / inputs.MANIFEST).read_bytes())['artifacts'], [])

    def test_duplicate_identity_mount_and_unapproved_configuration_keep_inputs(self):
        authoring.edit(self.project, 'add', [self.artifact], [])
        before = (self.project / inputs.MANIFEST).read_bytes()
        for change in ({}, {'id': 'different/1'}, {'metadata': {'configure': './configure'}},
                       {'metadata': {'generator': 'unreviewed executable'}}):
            row = copy.deepcopy(self.artifact); row.update(change)
            with self.subTest(change=change), self.assertRaises(DependencyError):
                authoring.edit(self.project, 'add', [row], [])
            self.assertEqual((self.project / inputs.MANIFEST).read_bytes(), before)
        changed = copy.deepcopy(self.artifact); changed['id'] = 'different/1'
        with self.assertRaisesRegex(DependencyError, 'explicit-add-remove'):
            authoring.edit(self.project, 'update', [changed], [self.artifact['id']])
        self.assertEqual((self.project / 'sdk-lock.json').read_bytes(), self.sdk)

    def test_review_requires_exact_digest_and_preserves_previous_lock_on_failure(self):
        self.review()
        old = (self.project / inputs.LOCK).read_bytes()
        candidate = self.capture()
        expected = digest(candidate.read_bytes())
        for wrong in ('not-a-digest', digest(b'changed review')):
            with self.subTest(wrong=wrong), self.assertRaisesRegex(DependencyError, 'candidate-review'):
                authoring.review(self.project, candidate, wrong)
        candidate.write_bytes(candidate.read_bytes() + b'\n')
        with self.assertRaisesRegex(DependencyError, 'candidate-review-drift'):
            authoring.review(self.project, candidate, expected)
        self.assertEqual((self.project / inputs.LOCK).read_bytes(), old)

    def test_stale_manifest_and_tampered_or_missing_cas_never_accept_candidate(self):
        self.review()
        old = (self.project / inputs.LOCK).read_bytes()
        candidate = self.capture()
        lock = json.loads(candidate.read_bytes())
        item = lock['artifacts'][0]['files'][0]
        cached = Store(self.project / 'dependency-inputs/objects', create=False).path(item['digest'])
        original = cached.read_bytes()
        cached.write_bytes(b'tampered')
        with self.assertRaisesRegex(DependencyError, 'integrity'):
            authoring.review(self.project, candidate, digest(candidate.read_bytes()))
        cached.unlink()
        with self.assertRaisesRegex(DependencyError, 'missing-resolve-explicitly'):
            authoring.review(self.project, candidate, digest(candidate.read_bytes()))
        cached.write_bytes(original)
        changed = copy.deepcopy(self.artifact); changed['metadata']['license'] = 'BSD-2-Clause'
        authoring.edit(self.project, 'update', [changed], [changed['id']])
        with self.assertRaisesRegex(DependencyError, 'lock-drift'):
            authoring.review(self.project, candidate, digest(candidate.read_bytes()))
        self.assertEqual((self.project / inputs.LOCK).read_bytes(), old)

    def test_native_lock_drift_and_atomic_replace_failure_preserve_reviewed_bytes(self):
        authoring.edit(self.project, 'add', [self.artifact], [])
        declaration = json.loads((self.project / inputs.MANIFEST).read_bytes())
        declaration['nativeLocks'] = ['native.lock']
        (self.project / inputs.MANIFEST).write_bytes(canonical(declaration))
        (self.project / 'native.lock').write_bytes(b'original selected configuration\n')
        candidate = self.capture()
        (self.project / 'native.lock').write_bytes(b'changed configuration\n')
        with self.assertRaisesRegex(DependencyError, 'native-lock-drift'):
            authoring.review(self.project, candidate, digest(candidate.read_bytes()))
        self.assertFalse((self.project / inputs.LOCK).exists())
        before = (self.project / inputs.MANIFEST).read_bytes()
        with patch.object(authoring.os, 'replace', side_effect=OSError('private-path-must-not-leak')):
            code, _, err = self.call('update', self.project, '--id', self.artifact['id'], '--artifact', self.declaration())
        self.assertEqual(code, 1)
        self.assertNotIn('private-path-must-not-leak', err)
        self.assertEqual((self.project / inputs.MANIFEST).read_bytes(), before)
        self.assertEqual(list((self.project / authoring.STATE).glob('pending-*')), [])

    def test_expected_manifest_and_simultaneous_sdk_change_fail_before_replace(self):
        authoring.edit(self.project, 'add', [self.artifact], [])
        before = (self.project / inputs.MANIFEST).read_bytes()
        with self.assertRaisesRegex(DependencyError, 'manifest-review-drift'):
            authoring.edit(self.project, 'update', [self.artifact], [self.artifact['id']], expected=digest(b'wrong'))
        real_write = authoring.paths.write_new
        def change_sdk(path, raw):
            real_write(path, raw)
            if path.name.startswith('pending-'):
                (self.project / 'sdk-lock.json').write_bytes(self.sdk + b'\n')
        with patch.object(authoring.paths, 'write_new', side_effect=change_sdk), self.assertRaisesRegex(DependencyError, 'concurrent-edit'):
            authoring.edit(self.project, 'remove', [], [self.artifact['id']])
        self.assertEqual((self.project / inputs.MANIFEST).read_bytes(), before)
        self.assertEqual(list((self.project / authoring.STATE).glob('pending-*')), [])

    def test_resolution_never_overwrites_project_inputs_or_prior_attempts(self):
        authoring.edit(self.project, 'add', [self.artifact], [])
        before = (self.project / inputs.MANIFEST).read_bytes()
        for path in (self.project / inputs.MANIFEST, self.project / inputs.LOCK,
                     self.project / 'new-source.c', self.project / 'sdk-lock.json'):
            with self.subTest(path=path), self.assertRaises(DependencyError):
                authoring.resolve(self.project, path)
        candidate = self.capture()
        original = candidate.read_bytes()
        code, _, _ = self.call('resolve', self.project, '--candidate', candidate)
        self.assertEqual(code, 1)
        self.assertEqual(candidate.read_bytes(), original)
        self.assertEqual((self.project / inputs.MANIFEST).read_bytes(), before)
        self.assertEqual((self.project / 'sdk-lock.json').read_bytes(), self.sdk)

    def test_reviewed_update_changes_actual_watch_snapshot_and_requires_fresh_trust(self):
        self.review(); self.descriptor()
        old_descriptor, _ = project.load(self.project)
        old_selection = build_client.selection(self.project)
        workspace = self.root / 'workspace'; workspace.mkdir(mode=0o700)
        state.atomic(workspace, 'trust.json', {'project': str(self.project), 'recipe': project.trust_identity(old_descriptor)})
        updated = copy.deepcopy(self.artifact); updated['metadata']['defines'] = {'FEATURE': '1'}
        authoring.edit(self.project, 'update', [updated], [updated['id']])
        with self.assertRaisesRegex(common.DevError, 'lock-drift'):
            build_client.selection(self.project)
        self.review()
        new_descriptor, _ = project.load(self.project)
        new_selection = build_client.selection(self.project)
        self.assertNotEqual(new_selection[0], old_selection[0])
        self.assertNotEqual(new_selection[1], old_selection[1])
        dependencies.verify(self.project, new_descriptor)
        record, content = snapshot.observe(self.project, new_descriptor['inputRoots'])
        self.assertIn(inputs.LOCK, content)
        self.assertTrue(any(name.startswith('dependency-inputs/objects/') for name in content))
        self.assertEqual(record['identity'], new_selection[1])
        class NoDispatch:
            def call(self, *_args, **_kwargs):
                raise AssertionError('stale trust reached a build or provider')
        with self.assertRaisesRegex(common.DevError, 'recipe-trust-required'):
            build_client.run(workspace, NoDispatch(), self.project, '/tools')
        calls = []
        class ObserveCancellation:
            def call(self, *args, **_kwargs):
                calls.append(args)
                return {'accepted': True}
        observer = build_client.Observer(self.project, old_selection, ObserveCancellation(), 'original-build')
        observer.check()
        self.assertTrue(observer.superseded)
        self.assertEqual(calls, [('cancel-build', {'buildId': 'original-build', 'reason': 'superseded'})])
        self.assertEqual((self.project / 'sdk-lock.json').read_bytes(), self.sdk)

    def test_test_and_watch_use_actual_frontend_parser_and_preserve_uncertain_outcome(self):
        self.review(); self.descriptor()
        for action in ('test', 'watch'):
            observed = []
            def dispatch(args):
                observed.append(args)
                raise common.DevError('operation-outcome-unknown-inspect-status', uncertain=True)
            with patch.object(cli, 'dispatch', side_effect=dispatch), patch.object(cli, 'emit') as emit:
                code, _, err = self.call(action, self.project, '--workspace', 'test-c', '--select', 'greeting')
            self.assertEqual((code, err), (5, ''))
            self.assertEqual(len(observed), 1)
            self.assertEqual(observed[0].command, 'test' if action == 'test' else 'up')
            self.assertEqual(emit.call_args[0][0]['uncertain'], True)
            if action == 'watch':
                self.assertTrue(observed[0].watch)
                self.assertEqual(observed[0].test_select, ['greeting'])
            else:
                self.assertEqual(observed[0].select, ['greeting'])
        receipts = [json.loads(path.read_bytes()) for path in (self.project / authoring.STATE).glob('receipt-*.json')]
        self.assertTrue(all(row['exitCode'] == 5 and row['automaticReplay'] is False for row in receipts))

    def test_frontend_rejects_wrong_language_missing_descriptor_and_corrupt_capture_before_dispatch(self):
        self.review()
        with patch.object(cli, 'main', side_effect=AssertionError('invalid capture reached frontend')):
            self.assertEqual(self.call('watch', self.project, '--workspace', 'test-c')[0], 1)
            value = self.descriptor(); value.update(language='rust')
            value['template']['ownerIssue'] = project.LANGUAGES['rust']
            (self.project / 'latent.project.json').write_bytes(common.encode(value))
            self.assertEqual(self.call('test', self.project, '--workspace', 'test-c')[0], 1)
            self.descriptor()
            captured = inputs.verify_inputs(self.project, 'c').lock['artifacts'][0]['files'][0]
            Store(self.project / 'dependency-inputs/objects', create=False).path(captured['digest']).write_bytes(b'tampered')
            self.assertEqual(self.call('test', self.project, '--workspace', 'test-c')[0], 1)

    def test_maintained_app_layout_build_and_archive_consume_outer_reviewed_closure(self):
        from tools import c_capsule_build, c_capsule_project, c_static_archive_build
        app = c_capsule_project.create(self.project / 'app', 'greeting')
        self.descriptor()
        sdk = (app / 'sdk-lock.json').read_bytes()
        self.review()
        files, owner = authoring.build_inputs(app)
        self.assertEqual(owner, self.project)
        self.assertEqual(files[inputs.MANIFEST], (self.project / inputs.MANIFEST).read_bytes())
        self.assertEqual(files[inputs.LOCK], (self.project / inputs.LOCK).read_bytes())
        self.assertIn('latent.project.json', files)
        self.assertEqual(authoring.application_root(self.project), app)
        shutil.rmtree(self.library)
        for kind in ('build', 'archive'):
            output = self.root / ('nested-' + kind)
            compiler = c_capsule_build if kind == 'build' else c_static_archive_build
            with patch.object(compiler, 'Compiler', side_effect=RuntimeError('actual-compiler-qualification-remains-pending')):
                args = [kind, str(self.project), '--output', str(output), '--repository', 'https://example.invalid/public-application']
                if kind == 'build':
                    args += ['--package-inputs-only']
                self.assertEqual(self.call(*args)[0], 1)
            captured = json.loads((output / 'application-dependencies.json').read_bytes())
            self.assertEqual(captured['manifestDigest'], digest(files[inputs.MANIFEST]))
            self.assertEqual(captured['lockDigest'], digest(files[inputs.LOCK]))
            self.assertEqual(captured['artifacts'][0]['id'], self.artifact['id'])
            failed = 'BUILD-FAILED.json' if kind == 'build' else 'STATIC-ARCHIVE-FAILED.json'
            self.assertTrue((output / failed).exists())
            self.assertFalse((output / 'BUILD-COMPLETE.json').exists())
            self.assertFalse((output / 'STATIC-ARCHIVE-COMPLETE.json').exists())
        self.assertEqual((app / 'sdk-lock.json').read_bytes(), sdk)

    def test_nested_layout_rejects_shadow_lock_and_descriptor_drift(self):
        self.descriptor(); self.review()
        app = self.project / 'app'
        (app / inputs.MANIFEST).write_bytes((self.project / inputs.MANIFEST).read_bytes())
        with self.assertRaisesRegex(DependencyError, 'ambiguous-application-lock'):
            authoring.build_inputs(app)
        (app / inputs.MANIFEST).unlink()
        sdk = authoring.sdk_identity(self.project)
        value = json.loads((self.project / 'latent.project.json').read_bytes())
        value['build']['argv'].append('--changed-reviewed-recipe')
        (self.project / 'latent.project.json').write_bytes(common.encode(value))
        with self.assertRaisesRegex(DependencyError, 'concurrent-edit'):
            authoring.check_authority(self.project, sdk)

    def test_inner_descriptor_cannot_redirect_cli_component_or_archive_inputs(self):
        from tools import c_capsule_build, c_static_archive_build
        value = self.descriptor()
        self.review()
        app = self.project / 'app'
        sdk = (app / 'sdk-lock.json').read_bytes()
        native_before = {name: (self.project / name).read_bytes() for name in (inputs.MANIFEST, inputs.LOCK)}
        value['build']['workingDirectory'] = 'nested-unapproved-application'
        (app / value['build']['workingDirectory']).mkdir()
        (app / 'latent.project.json').write_bytes(common.encode(value))
        for ordinal, entry in enumerate((self.project, app)):
            with self.subTest(entry=entry):
                with self.assertRaisesRegex(DependencyError, 'ambiguous-project-descriptor'):
                    authoring.layout(entry)
                with self.assertRaisesRegex(DependencyError, 'ambiguous-project-descriptor'):
                    authoring.application_root(entry)
                with self.assertRaisesRegex(DependencyError, 'ambiguous-project-descriptor'):
                    authoring.build_inputs(entry)
                code, _out, err = self.call('dependencies', entry)
                self.assertEqual(code, 1)
                self.assertIn('ambiguous-project-descriptor', err)
                for label, builder in (('component', c_capsule_build), ('archive', c_static_archive_build)):
                    output = self.root / ('shadow-' + label + '-' + str(ordinal))
                    with patch.object(builder, 'Compiler') as compiler:
                        with self.assertRaisesRegex(DependencyError, 'ambiguous-project-descriptor'):
                            if label == 'component':
                                builder.build(entry, output, self.root / 'never-executed-contracts', None,
                                              'https://example.invalid/repository')
                            else:
                                builder.build(entry, output, 'https://example.invalid/repository')
                    compiler.assert_not_called()
                    self.assertFalse((output / 'BUILD-COMPLETE.json').exists())
                    self.assertFalse((output / 'STATIC-ARCHIVE-COMPLETE.json').exists())
        self.assertEqual((app / 'sdk-lock.json').read_bytes(), sdk)
        self.assertEqual({name: (self.project / name).read_bytes() for name in native_before}, native_before)

    def test_receipt_io_failure_cannot_reclassify_uncertain_frontend_result(self):
        self.review(); self.descriptor()
        with patch.object(cli, 'dispatch', side_effect=common.DevError('operation-outcome-unknown', uncertain=True)), \
                patch.object(cli, 'emit') as emitted, patch.object(authoring, 'record', side_effect=OSError('private-io-error')):
            code, _, err = self.call('test', self.project, '--workspace', 'test-c')
        self.assertEqual(code, 5)
        self.assertTrue(emitted.call_args[0][0]['uncertain'])
        self.assertNotIn('private-io-error', err)

    def test_reviewed_executable_input_is_not_execution_approval(self):
        tool = copy.deepcopy(self.artifact); tool.update(role='build-tool')
        authoring.edit(self.project, 'add', [tool], [])
        candidate = self.capture()
        reviewed = authoring.review(self.project, candidate, digest(candidate.read_bytes()))
        self.assertEqual(reviewed['executableInputs'], [tool['id']])
        work, output = self.root / 'work', self.root / 'output'
        work.mkdir(); output.mkdir()
        with self.assertRaisesRegex(DependencyError, 'require-isolated-stage'):
            inputs.prepare(self.project, work, output, 'c')
        self.assertEqual(list(work.iterdir()), [])

    def test_private_auth_missing_and_secret_metadata_fail_with_redacted_immutable_receipts(self):
        artifact = copy.deepcopy(self.artifact)
        artifact.update(format='file', mount='dependencies/library.c')
        artifact['source'] = {'repository': 'private-alias', 'path': 'library.c', 'digest': digest(b'private library')}
        authoring.edit(self.project, 'add', [artifact], [])
        repositories = self.root / 'private-repositories.json'
        repositories.write_bytes(canonical({'private-alias': {'url': 'https://private.invalid', 'authorizationEnv': 'LSF_C_TEST_AUTH'}}))
        with patch.dict(os.environ, {}, clear=True):
            code, out, err = self.call('resolve', self.project, '--candidate', self.root / 'failed.json', '--repositories', repositories)
        self.assertEqual(code, 1)
        self.assertIn('dependency-repository-auth-unavailable', err)
        self.assertNotIn('private.invalid', out + err)
        self.assertFalse((self.project / inputs.LOCK).exists())
        bad = copy.deepcopy(artifact); bad['metadata'] = {'authorization': 'Bearer never-retain-this'}
        code, _, err = self.call('add', self.project, '--artifact', self.declaration(bad))
        self.assertEqual(code, 1)
        self.assertNotIn('never-retain-this', err)
        receipts = [path.read_text() for path in (self.project / authoring.STATE).glob('receipt-*.json')]
        self.assertEqual(len(receipts), 2)
        self.assertTrue(all('Bearer' not in raw and 'private.invalid' not in raw for raw in receipts))

    def test_private_configuration_inside_captured_project_is_rejected_before_feed_contact(self):
        authoring.edit(self.project, 'add', [self.artifact], [])
        private = self.project / 'private-repositories.json'
        private.write_bytes(canonical({'private-alias': {'url': 'https://private-registry.invalid', 'authorizationEnv': 'LSF_C_TEST_AUTH'}}))
        with patch.object(inputs, 'fetch', side_effect=AssertionError('invalid private configuration contacted feed')):
            code, out, err = self.call('resolve', self.project, '--candidate', self.root / 'private-candidate.json', '--repositories', private)
        self.assertEqual(code, 1)
        self.assertIn('config-must-stay-outside-project', err)
        self.assertNotIn('private-registry.invalid', out + err)
        self.assertFalse((self.root / 'private-candidate.json').exists())

    def test_actual_private_https_capture_redacts_credentials_and_reviews_offline(self):
        from tools.run_oci_registry_tests import certificates
        tls = self.root / 'tls'; tls.mkdir()
        certificates(tls)
        payload = b'int private_value(void) { return 42; }\n'
        token = 'Bearer ' + secrets.token_hex(32)
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                authorized = self.headers.get('Authorization') == token
                requests.append({'authorized': authorized, 'path': self.path})
                body = payload if authorized else b'private-registry-secret-error'
                self.send_response(200 if authorized else 401)
                self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
            def log_message(self, *_args):
                pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls_context.load_cert_chain(tls / 'server.pem', tls / 'server.key')
        server.socket = tls_context.wrap_socket(server.socket, server_side=True)
        worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.02}, name='c-private-capture-fixture')
        worker.start()
        def close():
            server.shutdown(); server.server_close(); worker.join(2)
            self.assertFalse(worker.is_alive())
        self.addCleanup(close)
        row = copy.deepcopy(self.artifact)
        row.update(format='file', mount='dependencies/private.c')
        row['metadata'].update(cSources=['private.c'], includeDirectories=[])
        row['source'] = {'repository': 'private-alias', 'path': 'private.c', 'digest': digest(payload)}
        authoring.edit(self.project, 'add', [row], [])
        config = {'private-alias': {'url': 'https://127.0.0.1:' + str(server.server_port), 'authorizationEnv': 'LSF_C_TEST_AUTH'}}
        trusted = ssl.create_default_context(cafile=str(tls / 'ca.pem'))
        def opener(*handlers):
            return build_opener(*handlers, HTTPSHandler(context=trusted))
        candidate = self.root / 'https-candidate.json'
        with patch.object(inputs, 'build_opener', side_effect=opener), patch.dict(os.environ, {'LSF_C_TEST_AUTH': 'Bearer rejected-secret', 'NO_PROXY': '127.0.0.1'}):
            with self.assertRaisesRegex(DependencyError, 'fetch-failed'):
                authoring.resolve(self.project, self.root / 'rejected-candidate.json', repositories=config)
        self.assertFalse((self.root / 'rejected-candidate.json').exists())
        with patch.object(inputs, 'build_opener', side_effect=opener), patch.dict(os.environ, {'LSF_C_TEST_AUTH': token, 'NO_PROXY': '127.0.0.1'}):
            result = authoring.resolve(self.project, candidate, repositories=config)
        self.assertEqual(requests, [{'authorized': False, 'path': '/private.c'}, {'authorized': True, 'path': '/private.c'}])
        receipt = authoring.record(self.project, result)
        self.assertNotIn(token, candidate.read_text() + receipt.read_text())
        self.assertNotIn(config['private-alias']['url'], candidate.read_text() + receipt.read_text())
        with patch.object(inputs, 'fetch', side_effect=AssertionError('review contacted private HTTPS feed')):
            reviewed = authoring.review(self.project, candidate, digest(candidate.read_bytes()))
        self.assertEqual(reviewed['candidateDigest'], digest(candidate.read_bytes()))
        self.assertEqual(len(requests), 2)
        self.assertEqual(authoring.status(self.project)['status'], 'verified')


if __name__ == '__main__':
    unittest.main()
