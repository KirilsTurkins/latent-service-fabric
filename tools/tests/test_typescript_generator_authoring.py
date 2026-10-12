"""Explicit TypeScript script approval, capture and actual contained generation."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from tools import typescript_capsule, typescript_dependency_authoring as authoring
from tools.typescript_guest import build
from tools import typescript_generator_authoring as generators
from tools.application_dependency_store import DependencyError
from tools.build_process import BuildProcessError, run_bounded_result
from tools.build_snapshot import canonical, digest
from tools.dev_workflow import common, project as frontend
from tools.typescript_guest.project import create, snapshot, validate
from tools.tests.test_dev_contracts import descriptor


class TypeScriptGeneratorFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        cls.original = snapshot(create(Path(temporary.name) / 'app', 'greeting'))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        for name, raw in self.original.items():
            target = self.project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        self.inputs = self.root / 'inputs'
        self.inputs.mkdir()
        (self.inputs / 'value.txt').write_bytes(b'17')
        self.tool = self.root / 'generator'
        self.tool.write_bytes(b'#!/bin/sh\nprintf "export const generated: number = 17;\\n" > /outputs/value.ts\n')
        self.tool.chmod(0o700)
        self.candidate = self.project / 'target/request.json'
        self.candidate.parent.mkdir()

    def plan(self, **options):
        return generators.request(self.project, self.candidate, tool=self.tool, arguments=[],
                                  inputs=self.inputs, destination='src/generated', tool_version='selected-script-v1', **options)

    def command(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = typescript_capsule.main(list(map(str, arguments)))
        return result, stdout.getvalue(), stderr.getvalue()


class TypeScriptGeneratorApproval(TypeScriptGeneratorFixture):
    def test_cli_request_binds_tool_inputs_source_sdk_arguments_and_limits_without_execution(self):
        with patch('subprocess.Popen', side_effect=AssertionError('request ran a tool')):
            result, stdout, stderr = self.command('generator-request', self.project,
                '--candidate', self.candidate, '--tool', self.tool, '--tool-version', 'selected-script-v1',
                '--inputs', self.inputs, '--arg=--mode', '--arg=generate')
        self.assertEqual((result, stderr), (0, ''))
        receipt = json.loads(stdout)
        plan = json.loads(self.candidate.read_bytes())
        self.assertEqual(receipt['requestDigest'], digest(self.candidate.read_bytes()))
        self.assertEqual(plan['specification']['executableDigest'], digest(self.tool.read_bytes()))
        self.assertEqual(plan['specification']['arguments'], ['--mode', 'generate'])
        self.assertEqual(plan['limits'], {'timeoutSeconds': 60, 'maximumOutputBytes': 1048576})
        self.assertEqual(plan['sdkIdentity']['lock'], digest(self.original['sdk-lock.json']))
        self.assertEqual(plan['specification']['network'], 'denied')
        self.assertFalse(receipt['generatorExecution'])
        self.assertTrue(receipt['approvalRequired'])

    def test_missing_wrong_or_tampered_request_approval_never_executes(self):
        planned = self.plan()
        before = snapshot(self.project)
        with patch.object(generators.generators, 'execute', side_effect=AssertionError('unapproved tool executed')):
            for expected in ('', 'sha256:' + '0' * 64):
                with self.subTest(expected=expected), self.assertRaisesRegex(DependencyError, 'approval-mismatch'):
                    generators.run(self.project, self.candidate, expected)
            self.candidate.write_bytes(self.candidate.read_bytes() + b' ')
            with self.assertRaisesRegex(DependencyError, 'approval-mismatch'):
                generators.run(self.project, self.candidate, planned['requestDigest'])
        self.assertEqual(snapshot(self.project), before)

    def test_changed_source_tool_and_input_reject_previous_approval_before_dispatch(self):
        planned = self.plan()
        for path, reason in ((self.project / 'src/main.ts', 'source-or-sdk-drift'),
                             (self.tool, 'tool-or-input-drift'), (self.inputs / 'value.txt', 'tool-or-input-drift')):
            original = path.read_bytes()
            path.write_bytes(original + b'\n')
            try:
                with self.subTest(path=path.name), patch.object(generators.generators, 'execute') as execute:
                    with self.assertRaisesRegex(DependencyError, reason):
                        generators.run(self.project, self.candidate, planned['requestDigest'])
                    execute.assert_not_called()
            finally:
                path.write_bytes(original)

    def test_outer_descriptor_change_invalidates_exact_nested_application_approval(self):
        app = self.project / 'app'
        app.mkdir()
        for path in list(self.project.iterdir()):
            if path.name not in {'app', 'target'}:
                path.rename(app / path.name)
        value = descriptor()
        value.update(language='typescript', inputRoots=['app'])
        value['template']['ownerIssue'] = frontend.LANGUAGES['typescript']
        value['build']['workingDirectory'] = 'app'
        (self.project / 'latent.project.json').write_bytes(common.encode(value))
        planned = self.plan()
        value['name'] = 'changed-project'
        (self.project / 'latent.project.json').write_bytes(common.encode(value))
        with patch.object(generators.generators, 'execute') as execute:
            with self.assertRaisesRegex(DependencyError, 'source-or-sdk-drift'):
                generators.run(self.project, self.candidate, planned['requestDigest'])
        execute.assert_not_called()

    def test_requests_cannot_replace_source_sdk_or_existing_directory_or_widen_limits(self):
        for destination in ('vendor/lsf/generated', '../outside', 'src/main.ts', 'src/nested/generated'):
            with self.subTest(destination=destination), self.assertRaises((DependencyError, ValueError)):
                generators.request(self.project, self.candidate, tool=self.tool, arguments=[], inputs=self.inputs,
                                   destination=destination, tool_version='selected-script-v1')
        for options in ({'timeout_seconds': 61}, {'timeout_seconds': float('nan')}, {'maximum_output_bytes': 1048577}):
            with self.subTest(options=options), self.assertRaisesRegex(DependencyError, 'finite-limits'):
                self.plan(**options)
        self.assertFalse(self.candidate.exists())

    def test_changed_generated_bytes_fail_normal_build_and_frontend_before_compiler(self):
        output = 'src/generated/value.ts'
        raw = b'export const generated = 17;\n'
        rows = [{'path': output, 'digest': digest(raw), 'size': len(raw)}]
        record = {name: 'sha256:' + '1' * 64 for name in ('requestDigest', 'executionIdentity', 'toolDigest',
            'inputsDigest', 'specificationDigest', 'executionReceiptDigest')}
        record.update(toolVersion='selected-script-v1', outputs=rows, outputsIdentity=digest(canonical(rows)), cleanup='reaped')
        target = self.project / output
        target.parent.mkdir()
        target.write_bytes(raw)
        (self.project / generators.MANIFEST).write_bytes(canonical({'formatVersion': 1, 'language': 'typescript', 'records': [record]}) + b'\n')
        validate(snapshot(self.project))
        target.write_bytes(raw + b'// changed\n')
        with self.assertRaisesRegex(DependencyError, 'generated-inputs-drift'):
            authoring.status(self.project)
        with patch.object(build, 'Compiler') as compiler:
            with self.assertRaisesRegex(DependencyError, 'generated-inputs-drift'):
                build.build(self.project, self.root / 'build', self.tool, None,
                            'https://example.invalid/source', tools=self.inputs)
        compiler.assert_not_called()
        self.assertIn('tools/typescript_generator_authoring.py', build.RECIPE)


def require_containment():
    if sys.platform != 'linux' or not shutil.which('bwrap'):
        if os.environ.get('LSF_REQUIRE_COMPILER_ISOLATION') == '1':
            raise RuntimeError('required TypeScript generator containment host missing')
        raise unittest.SkipTest('actual TypeScript source generation requires Linux Bubblewrap')


class TypeScriptGeneratorNative(TypeScriptGeneratorFixture):
    @classmethod
    def setUpClass(cls):
        require_containment()
        super().setUpClass()

    def test_actual_approved_generator_reuses_captured_typescript_offline_without_original_tool(self):
        before = snapshot(self.project)
        planned = self.plan()
        code, stdout, stderr = self.command('generate', self.project, '--candidate', self.candidate,
                                          '--expect', planned['requestDigest'])
        self.assertEqual((code, stderr), (0, ''))
        result = json.loads(stdout)
        self.assertEqual((result['status'], result['cleanup']), ('succeeded', 'reaped'))
        after = snapshot(self.project)
        for name, raw in before.items():
            self.assertEqual(after[name], raw)
        self.tool.unlink()
        (self.inputs / 'value.txt').unlink()
        with patch('subprocess.Popen', side_effect=AssertionError('offline validation reran a processor')):
            validate(snapshot(self.project))
            authoring.status(self.project)
        record = generators.validate_generated_inputs(after)['records'][0]
        self.assertEqual(record['executionIdentity'], planned['executionIdentity'])
        self.assertEqual(record['outputs'][0]['digest'], digest(after['src/generated/value.ts']))

    def test_actual_script_has_no_ambient_home_credentials_or_network(self):
        (self.inputs / 'network-namespace.txt').write_text(os.readlink('/proc/self/ns/net'), encoding='ascii')
        self.tool.write_bytes(b'#!/usr/bin/python3\n'
            b'import os,pathlib,socket\n'
            b'assert not pathlib.Path("/etc/passwd").exists()\n'
            b'assert not os.environ.get("LSF_GENERATOR_SECRET")\n'
            b'assert os.readlink("/proc/self/ns/net") != pathlib.Path("/inputs/network-namespace.txt").read_text()\n'
            b'try:\n socket.create_connection(("127.0.0.1", 9), timeout=.2)\n'
            b'except OSError: pass\nelse: raise AssertionError("network exposed")\n'
            b'value=pathlib.Path("/inputs/value.txt").read_text()\n'
            b'pathlib.Path("/outputs/value.ts").write_text("export const generated: number = "+value+";\\n")\n')
        self.tool.chmod(0o700)
        planned = self.plan()
        with patch.dict(os.environ, {'LSF_GENERATOR_SECRET': 'fixture-not-a-secret'}):
            result = generators.run(self.project, self.candidate, planned['requestDigest'])
        self.assertEqual((result['status'], result['cleanup']), ('succeeded', 'reaped'))
        self.assertIn(b'generated: number = 17', (self.project / 'src/generated/value.ts').read_bytes())
        self.assertEqual((self.project / 'sdk-lock.json').read_bytes(), self.original['sdk-lock.json'])

    def test_nested_captured_npm_selection_and_disabled_scripts_survive_source_generation(self):
        from tools import application_dependencies as dependencies, guest_dependency_inputs
        from tools.application_dependency_store import directory_files
        from tools.typescript_application_dependencies import selection
        app = self.project / 'app'
        app.mkdir()
        for path in list(self.project.iterdir()):
            if path.name not in {'app', 'target'}:
                path.rename(app / path.name)
        value = descriptor()
        value.update(language='typescript', inputRoots=['app'])
        value['template']['ownerIssue'] = frontend.LANGUAGES['typescript']
        value['build']['workingDirectory'] = 'app'
        (self.project / 'latent.project.json').write_bytes(common.encode(value))
        declaration = canonical({'name': 'outside-app', 'version': '1.0.0', 'type': 'module',
                                 'scripts': {'prepare': 'node forbidden.cjs'}})
        native_lock = canonical({'lockfileVersion': 3, 'packages': {'': {'name': 'outside-app', 'version': '1.0.0'}}})
        (app / 'package.json').write_bytes(declaration)
        (app / 'package-lock.json').write_bytes(native_lock)
        modules = self.root / 'selected-public-modules'
        modules.mkdir()
        (modules / 'empty.txt').write_bytes(b'synthetic native graph boundary; no Node resolver qualification')
        rows = [{'path': name, 'digest': digest(raw), 'size': len(raw)} for name, raw in directory_files(modules).items()]
        graph = {'formatVersion': 1, 'selection': selection(), 'originalManifestDigest': digest(declaration),
                 'nativeLockDigest': digest(native_lock), 'filesDigest': digest(canonical(rows)),
                 'lifecycleScripts': 'disabled'}
        (app / 'npm-resolved.lock.json').write_bytes(canonical(graph))
        manifest = {'formatVersion': 1, 'language': 'typescript', 'selection': selection(),
            'nativeLocks': ['app/package.json', 'app/package-lock.json', 'app/npm-resolved.lock.json'],
            'artifacts': [{'id': 'synthetic/selected-modules', 'role': 'application', 'format': 'directory',
                'mount': 'application-vendor/node_modules', 'source': {'path': str(modules)}, 'dependencies': [],
                'metadata': {'assetType': 'selected-node-modules', 'license': 'MIT'}}], 'transformations': []}
        (self.project / dependencies.MANIFEST).write_bytes(canonical(manifest))
        lock = dependencies.capture(self.project)
        (self.project / dependencies.LOCK).write_bytes(canonical(lock))
        authoring.status(self.project)
        closure_before = {name: (self.project / name).read_bytes() for name in (dependencies.MANIFEST, dependencies.LOCK)}
        planned = self.plan()
        result = generators.run(self.project, self.candidate, planned['requestDigest'])
        self.assertEqual((result['status'], result['cleanup']), ('succeeded', 'reaped'))
        self.assertEqual({name: (self.project / name).read_bytes() for name in closure_before}, closure_before)
        self.assertEqual(json.loads((app / 'npm-resolved.lock.json').read_bytes())['lifecycleScripts'], 'disabled')
        self.tool.unlink()
        shutil.rmtree(modules)
        with patch('subprocess.Popen', side_effect=AssertionError('offline validation executed package hooks')):
            observed = guest_dependency_inputs.capture_source(self.project, 'typescript', exclude_when_captured=('node_modules',))
            validate(observed.files)
            authoring.status(self.project)
        self.assertIn('latent.dependencies.json', observed.files)
        self.assertIn('src/generated/value.ts', observed.files)

    def test_actual_deadline_reaps_descendants_retains_failure_and_preserves_source(self):
        self.tool.write_bytes(b'#!/bin/sh\nprintf x > /outputs/progress\n'
                             b'while :; do printf x >> /outputs/progress; done &\nwait\n')
        self.tool.chmod(0o700)
        before = snapshot(self.project)
        planned = self.plan(timeout_seconds=.25)
        with self.assertRaisesRegex(BuildProcessError, 'command-deadline'):
            generators.run(self.project, self.candidate, planned['requestDigest'])
        self.assertEqual(snapshot(self.project), before)
        self.assertFalse((self.project / 'src/generated').exists())
        stage = next((self.project / authoring.STATE).glob('generator-*'))
        outcome = json.loads((stage / 'outcome.json').read_bytes())
        self.assertEqual((outcome['status'], outcome['cleanup']), ('failed', 'reaped'))
        self.assertFalse(outcome['sourceChanged'])
        self.assertFalse(outcome['automaticReplay'])
        progress = stage / 'outputs/progress'
        size = progress.stat().st_size
        time.sleep(.1)
        self.assertEqual(progress.stat().st_size, size)

    def test_binary_nonportable_linked_and_empty_outputs_never_enter_typescript_source(self):
        for index, command in enumerate(('printf x > /outputs/Hidden.node',
                                         'printf x > "/outputs/Bad$.ts"',
                                         'ln -s /inputs/value.txt /outputs/Linked.ts', 'true')):
            self.tool.write_bytes(('#!/bin/sh\n' + command + '\n').encode())
            self.tool.chmod(0o700)
            self.candidate = self.project / ('target/request-' + str(index) + '.json')
            planned = self.plan()
            before = snapshot(self.project)
            with self.subTest(command=command), self.assertRaises(DependencyError):
                generators.run(self.project, self.candidate, planned['requestDigest'])
            self.assertEqual(snapshot(self.project), before)
            self.assertFalse((self.project / 'src/generated').exists())

    def test_oversized_generated_source_is_rejected_at_original_project_file_bound(self):
        self.tool.write_bytes(b'#!/bin/sh\ndd if=/dev/zero of=/outputs/Large.ts bs=1048576 count=5 2>/dev/null\n')
        self.tool.chmod(0o700)
        planned = self.plan()
        before = snapshot(self.project)
        with self.assertRaisesRegex(DependencyError, 'project-source-limit'):
            generators.run(self.project, self.candidate, planned['requestDigest'])
        self.assertEqual(snapshot(self.project), before)
        self.assertFalse((self.project / 'src/generated').exists())

    def test_failed_manifest_write_rolls_back_only_the_fresh_adopted_subtree(self):
        planned = self.plan()
        before = snapshot(self.project)
        write = generators.paths.write_new
        def fail_pending(path, raw):
            if path.name == 'generated-inputs.json':
                raise OSError('controlled manifest write failure')
            return write(path, raw)
        with patch.object(generators.paths, 'write_new', side_effect=fail_pending):
            with self.assertRaisesRegex(OSError, 'controlled manifest write failure'):
                generators.run(self.project, self.candidate, planned['requestDigest'])
        self.assertEqual(snapshot(self.project), before)
        self.assertFalse((self.project / 'src/generated').exists())
        stage = next((self.project / authoring.STATE).glob('generator-*'))
        outcome = json.loads((stage / 'outcome.json').read_bytes())
        self.assertEqual((outcome['status'], outcome['cleanup']), ('failed', 'reaped'))
        self.assertFalse(outcome['sourceChanged'])
        self.assertTrue((stage / 'outputs/value.ts').is_file())


if __name__ == '__main__':
    unittest.main()
