"""Explicit Java processor approval, capture and actual contained generation."""
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

from tools import java_capsule, java_capsule_build as build, java_dependency_authoring as authoring
from tools import java_generator_authoring as generators
from tools.application_dependency_store import DependencyError
from tools.build_process import BuildProcessError, run_bounded_result
from tools.build_snapshot import canonical, digest
from tools.dev_workflow import common, project as frontend
from tools.java_capsule_project import create, snapshot, validate, validate_sdk_inputs
from tools.java_guest.compiler import tool_inventory
from tools.tests.test_dev_contracts import descriptor


class JavaGeneratorFixture(unittest.TestCase):
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
        self.tool.write_bytes(b'#!/bin/sh\nprintf "package outside; public final class Generated { public static final int VALUE=17; }\\n" > /outputs/Generated.java\n')
        self.tool.chmod(0o700)
        self.candidate = self.project / 'target/request.json'
        self.candidate.parent.mkdir()

    def plan(self, **options):
        return generators.request(self.project, self.candidate, tool=self.tool, arguments=[],
                                  inputs=self.inputs, destination='src/generated', tool_version='fixture-v1', **options)

    def command(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = java_capsule.main(list(map(str, arguments)))
        return result, stdout.getvalue(), stderr.getvalue()


class JavaGeneratorApproval(JavaGeneratorFixture):
    def test_cli_request_binds_tool_inputs_source_sdk_arguments_and_limits_without_execution(self):
        with patch('subprocess.Popen', side_effect=AssertionError('request ran a tool')):
            result, stdout, stderr = self.command('generator-request', self.project,
                '--candidate', self.candidate, '--tool', self.tool, '--tool-version', 'selected-processor-v1',
                '--inputs', self.inputs, '--arg=--processor', '--arg=outside.Processor')
        self.assertEqual((result, stderr), (0, ''))
        receipt = json.loads(stdout)
        plan = json.loads(self.candidate.read_bytes())
        self.assertEqual(receipt['requestDigest'], digest(self.candidate.read_bytes()))
        self.assertEqual(plan['specification']['executableDigest'], digest(self.tool.read_bytes()))
        self.assertEqual(plan['specification']['arguments'], ['--processor', 'outside.Processor'])
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
        for path, reason in ((self.project / 'src/dev/latent/app/Capsule.java', 'source-or-sdk-drift'),
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
        value.update(language='java', inputRoots=['app'])
        value['template']['ownerIssue'] = frontend.LANGUAGES['java']
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
        for destination in ('vendor/lsf/generated', '../outside', 'src/dev', 'src/nested/generated'):
            with self.subTest(destination=destination), self.assertRaises((DependencyError, ValueError)):
                generators.request(self.project, self.candidate, tool=self.tool, arguments=[], inputs=self.inputs,
                                   destination=destination, tool_version='fixture-v1')
        for options in ({'timeout_seconds': 61}, {'timeout_seconds': float('nan')}, {'maximum_output_bytes': 1048577}):
            with self.subTest(options=options), self.assertRaisesRegex(DependencyError, 'finite-limits'):
                self.plan(**options)
        self.assertFalse(self.candidate.exists())

    def test_changed_generated_bytes_fail_normal_build_and_frontend_before_compiler(self):
        output = 'src/generated/Generated.java'
        raw = b'package outside; public final class Generated {}\n'
        rows = [{'path': output, 'digest': digest(raw), 'size': len(raw)}]
        record = {name: 'sha256:' + '1' * 64 for name in ('requestDigest', 'executionIdentity', 'toolDigest',
            'inputsDigest', 'specificationDigest', 'executionReceiptDigest')}
        record.update(toolVersion='fixture-v1', outputs=rows, outputsIdentity=digest(canonical(rows)), cleanup='reaped')
        target = self.project / output
        target.parent.mkdir()
        target.write_bytes(raw)
        (self.project / generators.MANIFEST).write_bytes(canonical({'formatVersion': 1, 'language': 'java', 'records': [record]}) + b'\n')
        validate(snapshot(self.project))
        target.write_bytes(raw + b'// changed\n')
        with self.assertRaisesRegex(DependencyError, 'generated-inputs-drift'):
            authoring.status(self.project)
        with patch.object(build, 'Compiler') as compiler:
            with self.assertRaisesRegex(DependencyError, 'generated-inputs-drift'):
                build.build(self.project, self.root / 'build', self.tool, None,
                            'https://example.invalid/source', self.inputs)
        compiler.assert_not_called()
        self.assertIn('tools/java_generator_authoring.py', build.RECIPE)


def require_containment():
    if sys.platform != 'linux' or not shutil.which('bwrap'):
        if os.environ.get('LSF_REQUIRE_COMPILER_ISOLATION') == '1':
            raise RuntimeError('required Java generator containment host missing')
        raise unittest.SkipTest('actual Java source generation requires Linux Bubblewrap')


class JavaGeneratorNative(JavaGeneratorFixture):
    @classmethod
    def setUpClass(cls):
        require_containment()
        super().setUpClass()

    def test_actual_approved_generator_reuses_captured_java_offline_without_original_tool(self):
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
        self.assertEqual(record['outputs'][0]['digest'], digest(after['src/generated/Generated.java']))

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

    def test_binary_nonportable_linked_and_empty_outputs_never_enter_java_source(self):
        for index, command in enumerate(('printf x > /outputs/Hidden.class',
                                         'printf x > "/outputs/Bad$.java"',
                                         'ln -s /inputs/value.txt /outputs/Linked.java', 'true')):
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
        self.tool.write_bytes(b'#!/bin/sh\ndd if=/dev/zero of=/outputs/Large.java bs=1048576 count=5 2>/dev/null\n')
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
        self.assertTrue((stage / 'outputs/Generated.java').is_file())


class JavaAnnotationProcessorNative(JavaGeneratorFixture):
    @classmethod
    def setUpClass(cls):
        require_containment()
        super().setUpClass()
        selected = os.environ.get('LSF_JAVA_GENERATOR_TEST_JDK')
        if selected is None:
            if os.environ.get('LSF_REQUIRE_JAVA_GENERATOR_PROCESSOR') == '1':
                raise RuntimeError('required pinned public processor JDK fixture missing')
            raise unittest.SkipTest('actual processor needs explicitly selected pinned public JDK')
        cls.jdk = Path(selected)
        if not cls.jdk.is_relative_to('/usr') or cls.jdk.is_symlink():
            raise RuntimeError('processor JDK fixture must be read-only public host sysroot under /usr')
        pins = validate_sdk_inputs(cls.original)[2]
        version = run_bounded_result([str(cls.jdk / 'bin/java'), '-version'], cwd=cls.jdk,
                                     env={'PATH': os.defpath}, timeout_seconds=30, max_output_bytes=65536)
        if version.returncode or pins['sdk']['java'].encode() not in version.stderr:
            raise RuntimeError('processor fixture does not match the pinned Java toolchain')

    def test_actual_selected_annotation_processor_is_contained_and_output_is_captured_once(self):
        source = self.root / 'Generator.java'
        source.write_text('''package fixture;
import java.io.Writer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;
import javax.annotation.processing.*;
import javax.lang.model.SourceVersion;
import javax.lang.model.element.TypeElement;
@SupportedAnnotationTypes("*")
@SupportedSourceVersion(SourceVersion.RELEASE_25)
public final class Generator extends AbstractProcessor {
    private boolean generated;
    public boolean process(Set<? extends TypeElement> annotations, RoundEnvironment round) {
        if (!generated && !round.processingOver()) {
            generated = true;
            if (System.getenv("LSF_GENERATOR_SECRET") != null || Files.exists(Path.of("/etc/passwd")))
                throw new AssertionError("ambient authority exposed");
            try (Writer output = processingEnv.getFiler().createSourceFile("outside.Generated").openWriter()) {
                String value = Files.readString(Path.of("/inputs/value.txt"));
                output.write("package outside; public final class Generated { public static final int VALUE="+value+"; }\\n");
            } catch (Exception error) { throw new AssertionError(error); }
        }
        return false;
    }
}
''', encoding='utf-8')
        classes = self.root / 'processor-classes'
        classes.mkdir()
        for command in ([str(self.jdk / 'bin/javac'), '-proc:none', '--release', '25', '-d', str(classes), str(source)],
                        [str(self.jdk / 'bin/jar'), '--create', '--file', str(self.inputs / 'processor.jar'), '-C', str(classes), '.']):
            built = run_bounded_result(command, cwd=self.root, env={'PATH': os.defpath},
                                       timeout_seconds=60, max_output_bytes=1048576)
            self.assertEqual(built.returncode, 0, built.stderr.decode('utf-8', 'replace'))
        # The selected public JDK's exact inventory joins the reviewed inputs.
        # It is not an application/compiler plugin or a native SDK product.
        (self.inputs / 'jdk-inputs.json').write_bytes(tool_inventory({'jdk': self.jdk}))
        (self.inputs / 'Trigger.java').write_bytes(b'public final class Trigger {}\n')
        self.tool.write_bytes(('#!/bin/sh\nset -eu\n' + str(self.jdk / 'bin/javac') +
            ' --release 25 -proc:only -processorpath /inputs/processor.jar -processor fixture.Generator'
            ' -d /tmp/classes -s /outputs /inputs/Trigger.java\n').encode())
        self.tool.chmod(0o700)
        planned = self.plan()
        with patch.dict(os.environ, {'LSF_GENERATOR_SECRET': 'fixture-not-a-secret'}):
            result = generators.run(self.project, self.candidate, planned['requestDigest'])
        self.assertEqual((result['status'], result['cleanup']), ('succeeded', 'reaped'))
        captured = snapshot(self.project)
        self.assertIn(b'VALUE=17', captured['src/generated/outside/Generated.java'])
        self.assertNotIn('processor.jar', captured)
        self.assertEqual(captured['sdk-lock.json'], self.original['sdk-lock.json'])
        shutil.rmtree(self.inputs)
        self.tool.unlink()
        with patch('subprocess.Popen', side_effect=AssertionError('normal build reran a processor')):
            validate(captured)
            authoring.status(self.project)


if __name__ == '__main__':
    unittest.main()
