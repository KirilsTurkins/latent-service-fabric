"""Bounded acquisition retries; no application compilation or guest execution credit."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import java_standard_http_library as owner
from tools import qualify_java_dependency_suite as suite
from tools.java_guest import compiler as production, compiler_acquisition as acquisition

COORDINATE = 'org.teavm:teavm-gradle-plugin:0.15.0'
POM = 'https://repo.maven.apache.org/maven2/org/teavm/teavm-gradle-plugin/0.15.0/teavm-gradle-plugin-0.15.0.pom'
LOCK = json.dumps({'artifacts': [{'path': 'org/teavm/teavm-gradle-plugin/0.15.0/teavm-gradle-plugin-0.15.0.jar'}]}).encode()
LOG = f'''FAILURE: Build failed with an exception.

* What went wrong:
A problem occurred configuring root project 'lsf-java-guest-feasibility'.
> Could not resolve all artifacts for configuration 'classpath'.
   > Could not find {COORDINATE}.
     Searched in the following locations:
       - {POM}
     Required by:
         buildscript of root project 'lsf-java-guest-feasibility'

BUILD FAILED in 5s
'''


RATE_LIMIT = LOG.replace(
    f'   > Could not find {COORDINATE}.\n     Searched in the following locations:\n       - {POM}\n',
    f'   > Could not resolve {COORDINATE}.\n'
).replace("         buildscript of root project 'lsf-java-guest-feasibility'\n",
          "         buildscript of root project 'lsf-java-guest-feasibility'\n"
          f"      > Could not resolve {COORDINATE}.\n"
          f"         > Could not get resource '{POM}'.\n"
          f"            > Could not GET '{POM}'. Received status code 429 from server: Too Many Requests\n")


class AcquisitionRetryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.compiler = owner.AcquisitionCompiler.__new__(owner.AcquisitionCompiler)
        self.compiler.directory = root
        self.compiler.paths = {'gradle': Path('/tools/gradle')}
        self.compiler.environment = {}
        self.compiler.offline = False
        self.compiler.deadline = 100.0
        self.compiler.records = []
        self.compiler.retained_bytes = 0
        self.compiler.original_sdk = {'feasibility/dependencies.lock.json': LOCK}
        self.compiler.check_unchanged = Mock()
        self.clock = self.stack.enter_context(patch.object(owner.time, 'monotonic', return_value=10.0))
        self.sleep = self.stack.enter_context(patch.object(owner.time, 'sleep'))
        self.process = self.stack.enter_context(patch.object(production, 'run_bounded_result'))

    def outcomes(self, *logs):
        self.process.side_effect = [SimpleNamespace(returncode=0 if text is None else 1,
            stdout=b'GENERATED' if text is None else text.encode(), stderr=b'') for text in logs]

    def run_compiler(self, *arguments):
        return self.compiler.run('java-to-c', 'gradle', *(arguments or ('--no-daemon', 'generateC')))

    def test_first_success_keeps_the_original_command(self):
        self.outcomes(None)
        self.assertEqual(self.run_compiler(), 'GENERATED\n')
        self.assertEqual(self.process.call_args.args[0], [str(self.compiler.paths['gradle']), '--no-daemon', 'generateC'])
        self.sleep.assert_not_called()
        self.compiler.check_unchanged.assert_not_called()

    def test_retry_refreshes_resolution_and_retains_every_attempt(self):
        self.outcomes(LOG, None)
        self.assertEqual(self.run_compiler(), 'GENERATED\n')
        self.assertEqual([call.args[0] for call in self.process.call_args_list], [
            [str(self.compiler.paths['gradle']), '--no-daemon', 'generateC'],
            [str(self.compiler.paths['gradle']), '--no-daemon', '--refresh-dependencies', 'generateC']])
        self.assertEqual([row['exitCode'] for row in self.compiler.records], [1, 0])
        self.assertEqual(self.compiler.deadline, 100.0)
        self.assertIn('Could not find', (self.compiler.directory / '0-java-to-c.log').read_text())
        self.assertEqual(json.loads((self.compiler.directory / '0-java-to-c.command.json').read_text())['exitCode'], 1)
        self.assertEqual(json.loads((self.compiler.directory / '1-java-to-c.command.json').read_text())['exitCode'], 0)
        self.sleep.assert_called_once_with(2)
        self.compiler.check_unchanged.assert_called_once_with()

    def test_rate_limited_locked_plugin_can_recover_within_the_original_deadline(self):
        self.outcomes(RATE_LIMIT, RATE_LIMIT, None)
        self.assertEqual(self.run_compiler(), 'GENERATED\n')
        self.assertEqual([call.args for call in self.sleep.call_args_list], [(15,), (30,)])
        self.assertEqual([row['exitCode'] for row in self.compiler.records], [1, 1, 0])
        self.assertIn('--refresh-dependencies', self.process.call_args.args[0])

    def test_rate_limit_recognition_requires_the_exact_locked_metadata_request(self):
        variants = (RATE_LIMIT.replace(POM, POM.replace('repo.maven.apache.org', 'other.example')),
            RATE_LIMIT.replace(POM, POM.replace('.pom', '.jar')),
            RATE_LIMIT.replace('Could not GET', 'Could not HEAD'),
            RATE_LIMIT.replace('429', '403'),
            RATE_LIMIT.replace(COORDINATE, 'org.teavm:unreviewed:0.15.0', 1),
            RATE_LIMIT + 'Could not download a transitive dependency\n',
            RATE_LIMIT + 'Dependency verification failed\n')
        for log in variants:
            with self.subTest(log=log):
                self.assertEqual(owner.compiler_metadata_retry_delay(log, LOCK), 0)
        self.compiler.deadline = 24.0
        self.outcomes(RATE_LIMIT, None)
        with self.assertRaises(ValueError):
            self.run_compiler()
        self.sleep.assert_not_called()
        self.assertEqual(self.process.call_count, 1)

    def test_multiple_missing_locked_poms_are_retryable_but_unknowns_are_not(self):
        other = 'teavm-metaprogramming-api'
        coordinate = 'org.teavm:' + other + ':0.15.0'
        pom = 'https://repo.maven.apache.org/maven2/org/teavm/' + other + '/0.15.0/' + other + '-0.15.0.pom'
        log = LOG.replace('BUILD FAILED', '   > Could not find ' + coordinate + '.\n       - ' + pom + '\nBUILD FAILED')
        lock = json.loads(LOCK)
        self.assertFalse(owner.missing_compiler_metadata(log, LOCK))
        lock['artifacts'].append({'path': 'org/teavm/' + other + '/0.15.0/' + other + '-0.15.0.jar'})
        self.compiler.original_sdk['feasibility/dependencies.lock.json'] = json.dumps(lock).encode()
        self.outcomes(log, None)
        self.assertEqual(self.run_compiler(), 'GENERATED\n')
        self.assertEqual(self.process.call_count, 2)

    def test_exhaustion_is_a_failure_after_exactly_three_attempts(self):
        self.outcomes(LOG, LOG, LOG, None)
        with self.assertRaisesRegex(ValueError, 'stage failed: java-to-c'):
            self.run_compiler()
        self.assertEqual(self.process.call_count, 3)
        self.assertEqual([call.args for call in self.sleep.call_args_list], [(2,), (4,)])
        self.assertEqual([row['exitCode'] for row in self.compiler.records], [1, 1, 1])
        self.assertEqual(len(list(self.compiler.directory.glob('*.command.json'))), 3)

    def test_offline_build_never_retries_or_refreshes(self):
        self.compiler.offline = True
        self.outcomes(LOG, None)
        with self.assertRaises(ValueError):
            self.run_compiler('--no-daemon', '--offline', 'generateC')
        self.assertEqual(self.process.call_count, 1)
        self.assertNotIn('--refresh-dependencies', self.process.call_args.args[0])
        self.sleep.assert_not_called()

    def test_task_compiler_verification_and_unknown_dependency_failures_do_not_retry(self):
        variants = (LOG + '> Task :generateC FAILED\n',
            LOG + 'Execution failed for task :generateC\n', LOG + 'Dependency verification failed\n',
            LOG.replace(COORDINATE, 'org.teavm:unreviewed:0.15.0'),
            LOG.replace('0.15.0', '0.16.0'), LOG.replace('classpath', 'runtimeClasspath'),
            LOG.replace('lsf-java-guest-feasibility', 'application'),
            LOG.replace('https://repo.maven.apache.org/maven2', 'https://other.invalid/maven2'),
            LOG + '       - https://other.invalid/extra.pom\n', LOG + '       - file:/tmp/extra.pom\n',
            LOG + 'Could not download another dependency\n',
            'FAILURE: Build failed with an exception.\nVariable used before definition\n')
        for text in variants:
            with self.subTest(log=text):
                self.process.reset_mock()
                self.outcomes(text, None)
                with self.assertRaises(ValueError):
                    self.run_compiler()
                self.assertEqual(self.process.call_count, 1)
        self.sleep.assert_not_called()

    def test_unrelated_commands_keep_failure_semantics(self):
        for stage, tool, arguments in (('java-owned-classes', 'gradle', ('--no-daemon', 'classes')),
                ('c-to-wasm', 'clang', ('-O2',)), ('java-to-c', 'gradle', ('--no-daemon', '--stacktrace', 'generateC'))):
            with self.subTest(stage=stage, arguments=arguments):
                self.process.reset_mock()
                self.outcomes(LOG, None)
                with self.assertRaises(ValueError):
                    self.compiler.run(stage, tool, *arguments)
                self.assertEqual(self.process.call_count, 1)
        self.sleep.assert_not_called()

    def test_missing_malformed_or_unbounded_diagnostics_fail_closed(self):
        for mutation in ('missing', 'malformed-lock', 'overbound', 'bad-encoding'):
            with self.subTest(mutation=mutation):
                self.process.reset_mock()
                self.compiler.original_sdk['feasibility/dependencies.lock.json'] = b'invalid' if mutation == 'malformed-lock' else LOCK
                self.outcomes(LOG, None)
                with ExitStack() as context:
                    if mutation == 'missing':
                        context.enter_context(patch.object(acquisition.paths, 'read', side_effect=OSError('missing')))
                    elif mutation == 'overbound':
                        self.outcomes(LOG + 'x' * (4 * 1024 * 1024), None)
                    elif mutation == 'bad-encoding':
                        context.enter_context(patch.object(acquisition.paths, 'read', return_value=b'\xff'))
                    with self.assertRaises(ValueError):
                        self.run_compiler()
                self.assertEqual(self.process.call_count, 1)
        self.sleep.assert_not_called()

    def test_other_exit_codes_and_process_failures_never_retry(self):
        self.process.return_value = SimpleNamespace(returncode=2, stdout=LOG.encode(), stderr=b'')
        with self.assertRaisesRegex(ValueError, 'stage failed'):
            self.run_compiler()
        self.assertEqual(self.process.call_count, 1)
        self.process.reset_mock()
        failure = production.BuildProcessError('controlled-process-failure')
        self.process.side_effect = failure
        with self.assertRaises(production.BuildProcessError) as caught:
            self.run_compiler()
        self.assertIs(caught.exception, failure)
        self.assertEqual(self.process.call_count, 1)
        self.assertEqual(self.compiler.records[-1]['processFailure'], failure.reason)
        self.sleep.assert_not_called()

    def test_original_retention_limit_is_not_reset(self):
        self.compiler.retained_bytes = 16 * 1024 * 1024
        self.outcomes(LOG, None)
        with self.assertRaisesRegex(ValueError, 'retention exceeded'):
            self.run_compiler()
        self.assertEqual(self.process.call_count, 1)
        self.sleep.assert_not_called()

    def test_original_and_parent_deadlines_prevent_late_retry(self):
        for parent in (False, True):
            with self.subTest(parent=parent):
                self.process.reset_mock()
                self.outcomes(LOG, None)
                self.compiler.deadline = 12.0 if not parent else 100.0
                self.compiler._parent_deadline = 17.0 if parent else None
                with self.assertRaisesRegex(ValueError, 'stage failed'):
                    self.run_compiler()
                self.assertEqual(self.process.call_count, 1)
        self.sleep.assert_not_called()

    def test_distribution_change_aborts_instead_of_retrying(self):
        changed = ValueError('Java compiler distribution changed during build')
        self.compiler.check_unchanged.side_effect = changed
        self.outcomes(LOG, None)
        with self.assertRaises(ValueError) as caught:
            self.run_compiler()
        self.assertIs(caught.exception, changed)
        self.assertEqual(self.process.call_count, 1)
        self.sleep.assert_not_called()

    def test_developer_tool_bundle_acquires_the_maintained_greeting_through_the_shared_compiler(self):
        from tools import dev_managed_distribution as distribution

        root = self.compiler.directory
        capture = root / 'bundle'
        capture.mkdir()
        source = {name: {} for name in ('jdk', 'gradle', 'wasi-sdk')}
        project = root / 'greeting'
        self.stack.enter_context(patch('tools.java_guest.compiler_profile.pin', return_value=None))
        self.stack.enter_context(patch.object(distribution, 'sources', return_value=source))
        self.stack.enter_context(patch.object(distribution, 'extract', side_effect=lambda archive, dest, name: dest))
        creator = self.stack.enter_context(patch('tools.java_capsule_project.create', return_value=project))
        compiler = self.stack.enter_context(patch.object(acquisition, 'AcquisitionCompiler', autospec=True))
        compiler.return_value.compile.side_effect = ValueError('end of acquisition probe')
        with self.assertRaisesRegex(ValueError, 'end of acquisition probe'):
            distribution.prepare(root / 'payload', capture, 'java', Mock())
        creator.assert_called_once_with(capture / 'managed-dependency-project', 'greeting')
        compiler.assert_called_once_with(capture / 'managed-dependencies', capture / 'managed-source/wasi-sdk',
                                         gradle=str(capture / 'managed-source/gradle/bin/gradle'))
        compiler.return_value.compile.assert_called_once_with(project / 'src', project / 'wit',
            'examples:greeting/service@1.0.0', capture / 'managed-dependency-build')

    def test_ordinary_application_compiler_remains_single_attempt(self):
        application = production.Compiler.__new__(production.Compiler)
        application.__dict__.update(self.compiler.__dict__)
        self.outcomes(LOG, None)
        with self.assertRaises(ValueError):
            application.run('java-to-c', 'gradle', '--no-daemon', 'generateC')
        self.assertEqual(self.process.call_count, 1)
        self.assertIs(suite.Compiler, owner.AcquisitionCompiler)
        self.sleep.assert_not_called()

    def delayed_acquisition_setup(self):
        """Use the real constructor/run path, with controlled setup time and tools."""
        java = self.compiler.directory / 'pinned-jdk/bin/java'
        java.parent.mkdir(parents=True)
        java.write_bytes(b'pinned-tool-control')
        self.stack.enter_context(patch.dict('os.environ', {'JAVA_HOME': str(java.parent.parent)}))
        self.stack.enter_context(patch.object(production.shutil, 'which', return_value=str(java)))
        self.stack.enter_context(patch.object(production.Compiler, '_wasi_compiler_version',
                                              return_value='21.1.4-wasi-sdk'))
        self.stack.enter_context(patch.object(production, 'source_module',
                                              return_value=SimpleNamespace(verify_version=Mock())))

        def environment(_directory):
            # Setup crosses the caller's absolute deadline before version probes.
            self.clock.return_value = 110.0
            return {}

        self.stack.enter_context(patch.object(production, 'build_environment', side_effect=environment))
        self.process.side_effect = AssertionError('acquisition subprocess escaped the parent deadline')

    def test_cache_acquisition_does_not_restart_deadline_after_source_setup(self):
        self.delayed_acquisition_setup()
        output = self.compiler.directory / 'cache-owner'

        def create(_directory, _template):
            self.clock.return_value = 70.0
            return self.compiler.directory / 'maintained-greeting'

        with patch.object(owner, 'create', side_effect=create), \
                self.assertRaisesRegex(ValueError, 'Java build deadline exceeded'):
            owner.compiler_cache(SimpleNamespace(deadline=100.0), Path('unused'), output, None)
        self.process.assert_not_called()
        self.sleep.assert_not_called()
        self.assertFalse((output / 'compiler-cache-selection.json').exists())

    def test_dependency_acquisition_keeps_deadline_across_constructor_setup(self):
        self.delayed_acquisition_setup()
        for mode in ('private', 'recovery'):
            with self.subTest(mode=mode):
                self.clock.return_value = 10.0
                commands = SimpleNamespace(deadline=100.0, environment={}, records=[])
                output = self.compiler.directory / ('suite-' + mode)

                def create(_directory, _template):
                    self.clock.return_value = 70.0
                    return self.compiler.directory / 'maintained-greeting'

                with patch.object(suite, 'Commands', return_value=commands), \
                        patch.object(suite, 'source_inputs', return_value={}), \
                        patch.object(suite, 'native', return_value=(Path('products'), Path('receipt'))), \
                        patch.object(suite, 'ordinary_tuple', return_value={}), \
                        patch.object(suite, 'create', side_effect=create), \
                        self.assertRaisesRegex(ValueError, 'Java build deadline exceeded'):
                    suite.main(['--output', str(output), '--wasi-sdk', 'unused', '--mode', mode])
                failure = json.loads((output / 'FAILED.json').read_text())
                self.assertEqual(failure['stage'], 'normal-pinned-compiler-acquisition')
                self.assertEqual(failure['reason'], 'Java build deadline exceeded')
                self.assertFalse((output / 'compiler-acquisition.json').exists())
        self.process.assert_not_called()
        self.sleep.assert_not_called()

    def test_source_setup_expiration_refuses_before_compiler_workspace_creation(self):
        output = self.compiler.directory / 'expired-cache-owner'

        def create(_directory, _template):
            self.clock.return_value = 110.0
            return self.compiler.directory / 'maintained-greeting'

        with patch.object(owner, 'create', side_effect=create), \
                patch.object(production, 'build_environment') as environment, \
                self.assertRaisesRegex(ValueError, 'Java-build-original-owner-deadline'):
            owner.compiler_cache(SimpleNamespace(deadline=100.0), Path('unused'), output, None)
        environment.assert_not_called()
        self.process.assert_not_called()
        self.sleep.assert_not_called()
        self.assertFalse((output / 'compiler-acquisition').exists())

    def test_explicit_cache_never_creates_an_acquisition_compiler(self):
        selected = self.compiler.directory / 'selected'
        with patch.object(owner, 'AcquisitionCompiler') as compiler, patch.object(owner, 'create') as create, \
                patch.object(owner, 'read_only_dependency_cache', return_value=selected), \
                patch.object(owner, 'tool_inventory', return_value=b'checked-cache'):
            actual = owner.compiler_cache(SimpleNamespace(deadline=100.0), Path('unused'), self.compiler.directory, selected)
        self.assertEqual(actual, selected)
        compiler.assert_not_called()
        create.assert_not_called()
        receipt = json.loads((self.compiler.directory / 'compiler-cache-selection.json').read_text())
        self.assertEqual(receipt['mode'], 'explicit-read-only-cache')
        self.assertFalse(receipt['applicationRegistryResolution'])


if __name__ == '__main__':
    unittest.main()
