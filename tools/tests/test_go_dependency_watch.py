"""Owned original Go module fixtures retain exact source/resource/version scope."""
from pathlib import Path
import tempfile
import unittest

from tools import go_dependency_watch_fixture as fixture


class GoDependencyWatchFixture(unittest.TestCase):
    def test_two_real_modules_preserve_primary_api_and_resource_across_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            application = Path(temporary) / 'application'; application.mkdir()
            observed = fixture.create(application)
            primary, child = Path(observed['primary']), Path(observed['child'])
            v1 = (primary / 'go.mod').read_text()
            self.assertIn('module ' + fixture.PRIMARY, v1)
            self.assertIn('require ' + fixture.CHILD + ' v0.1.0', v1)
            self.assertIn('replace ' + fixture.CHILD + ' => ../child', v1)
            self.assertEqual((primary / 'badge.txt').read_bytes(), fixture.RESOURCE)
            original_api = (primary / 'primary.go').read_bytes()
            self.assertIn(b'value+39', (child / 'child.go').read_bytes())
            fixture.remove_original(observed, 'primary'); fixture.remove_original(observed, 'child')
            self.assertFalse(primary.exists() or child.exists())
            fixture.restore_revision(observed, 2)
            self.assertIn('require ' + fixture.CHILD + ' v0.1.1', (primary / 'go.mod').read_text())
            self.assertEqual((primary / 'primary.go').read_bytes(), original_api)
            self.assertIn(b'value+40', (child / 'child.go').read_bytes())
            self.assertNotEqual(observed['inputDigests']['child-v1'], observed['inputDigests']['child-v2'])
            self.assertFalse((application / 'app').exists())

    def test_cleanup_and_restore_refuse_unknown_roots_without_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            application = Path(temporary) / 'application'; application.mkdir()
            observed = fixture.create(application)
            primary = Path(observed['primary'])
            before = (primary / 'go.mod').read_bytes()
            with self.assertRaisesRegex(ValueError, 'fresh'):
                fixture.restore_revision(observed, 2)
            with self.assertRaisesRegex(ValueError, 'unknown'):
                fixture.remove_original(observed, '../application')
            changed = {**observed, 'ownedRoot': str(application.resolve())}
            with self.assertRaisesRegex(ValueError, 'escaped'):
                fixture.remove_original(changed, 'primary')
            self.assertEqual((primary / 'go.mod').read_bytes(), before)
            self.assertTrue(application.is_dir())

    def test_removal_entry_has_no_library_reference_and_keeps_generated_export_api(self):
        selected = fixture.application_source()
        removed = fixture.application_source(removed=True)
        self.assertIn('primary.Answer()', selected)
        self.assertIn('primary.Resource()', selected)
        self.assertNotIn(fixture.PRIMARY, removed)
        self.assertNotIn('strconv', removed)
        self.assertIn('"removed/"+name', removed)
        for source in (selected, removed):
            self.assertIn('package export_examples_greeting_api', source)
            self.assertIn('go.bytecodealliance.org/pkg/wit/types', source)
            self.assertIn('calls != 0', source)
            self.assertNotIn('unsafe', source)

    def test_uncertain_shutdown_is_never_replayed_and_original_failure_is_preserved(self):
        from tools.qualify_go_dependency_watch import ShutdownOnce
        fence = ShutdownOnce()
        calls = []
        original = RuntimeError('unknown external shutdown result')
        def uncertain():
            calls.append('down')
            self.assertTrue(fence.attempted)
            raise original
        with self.assertRaises(RuntimeError) as observed:
            fence.call(uncertain)
        self.assertIs(observed.exception, original)
        with self.assertRaisesRegex(ValueError, 'already-attempted-no-retry'):
            fence.call(lambda: calls.append('replayed'))
        self.assertEqual(calls, ['down'])

    def test_confirmed_shutdown_receipt_is_preserved_and_same_owner_is_not_replayed(self):
        from tools.qualify_go_dependency_watch import ShutdownOnce
        fence = ShutdownOnce()
        receipt = {'state': 'stopped', 'reaped': True, 'cleanShutdown': True}
        self.assertIs(fence.call(lambda: receipt), receipt)
        with self.assertRaisesRegex(ValueError, 'already-attempted-no-retry'):
            fence.call(lambda: self.fail('replayed confirmed mutation'))

    def test_watch_delegation_operations_exist_in_maintained_frontend(self):
        import argparse
        import ast
        import inspect
        from tools import qualify_go_dependency_watch as programme
        from tools.dev_workflow.cli import parser
        root = parser()
        groups = next(row for row in root._actions if isinstance(row, argparse._SubParsersAction))
        commands = next(row for row in groups.choices['dev']._actions
            if isinstance(row, argparse._SubParsersAction)).choices
        tree = ast.parse(inspect.getsource(programme))
        operations = [row.args[1].value for row in ast.walk(tree)
            if isinstance(row, ast.Call) and isinstance(row.func, ast.Name) and row.func.id == 'front'
            and len(row.args) > 1 and isinstance(row.args[1], ast.Constant)]
        self.assertTrue(operations)
        self.assertLessEqual(set(operations), set(commands))
        self.assertIn('trust', operations)
        codes = {row.value for row in ast.walk(tree) if isinstance(row, ast.Constant)
            and isinstance(row.value, str) and row.value.startswith('workspace-recipe-')}
        self.assertEqual(codes, {'workspace-recipe-trust-required'})

class FreshActivationEvidence(unittest.TestCase):
    @staticmethod
    def report():
        return {'passed': True, 'environment': 'node', 'selection': list(fixture.SCENARIO_IDS),
            'cleanup': 'invocation-results-received-node-retained', 'pendingOperation': None,
            'results': [{'id': identifier, 'required': True, 'status': 'passed', 'category': 'success',
                'outcomeKnown': True, 'targetMatches': True, 'execution': {'grants': list(fixture.RUNTIME_GRANTS)},
                'activationId': 'dev-' + str(index) * 32, 'inputSha256': 'sha256:' + 'a' * 64,
                'payloadSha256': 'sha256:' + 'b' * 64,
                'expectedRevision': {'publicationId': 'publication:sha256:' + 'c' * 64},
                'resolvedRevision': {'publicationId': 'publication:sha256:' + 'c' * 64}}
                for index, identifier in enumerate(fixture.SCENARIO_IDS)]}

    def test_fixture_uses_two_required_calls_and_only_explicit_maintained_go_grants(self):
        from tools.dev_workflow.scenarios import validate
        from tools.guest_runtime_profiles import profiles
        value = fixture.scenarios()
        validate(value, 'node')
        self.assertEqual([row['id'] for row in value['scenarios']], list(fixture.SCENARIO_IDS))
        self.assertEqual(len(value['scenarios']), 2)
        self.assertEqual(set(fixture.RUNTIME_GRANTS), {row[0] for row in profiles('go').values()})
        for row in value['scenarios']:
            self.assertIs(row['required'], True)
            self.assertEqual(row['execution'], {'grants': list(fixture.RUNTIME_GRANTS)})
            self.assertEqual(row['requires'], ['fresh-state', 'clock', 'random'])
            self.assertEqual(row['nodeTimeoutMillis'], 120000)
        first, second = value['scenarios']
        self.assertEqual({k: v for k, v in first.items() if k != 'id'},
                         {k: v for k, v in second.items() if k != 'id'})
        first['execution']['grants'].clear()
        self.assertEqual(second['execution']['grants'], list(fixture.RUNTIME_GRANTS))
        self.assertEqual(fixture.scenarios()['scenarios'][0]['execution']['grants'], list(fixture.RUNTIME_GRANTS))

    def test_same_target_distinct_successful_activations_are_required(self):
        from tools.qualify_go_dependency_watch import stage_tests_passed
        self.assertTrue(stage_tests_passed(self.report(), fixture.SCENARIO_IDS, fixture.RUNTIME_GRANTS))
        for field in ('activationId', 'inputSha256', 'payloadSha256', 'expectedRevision', 'resolvedRevision'):
            with self.subTest(field=field):
                report = self.report()
                report['results'][1][field] = (report['results'][0][field] if field == 'activationId'
                                              else 'sha256:' + 'd' * 64)
                self.assertFalse(stage_tests_passed(report, fixture.SCENARIO_IDS, fixture.RUNTIME_GRANTS))

    def test_missing_duplicate_partial_or_reordered_cases_cannot_qualify(self):
        from tools.qualify_go_dependency_watch import stage_tests_passed
        for selection, indices in (([], ()), (list(fixture.SCENARIO_IDS), (0,)),
                (list(fixture.SCENARIO_IDS), (0, 0)), (list(fixture.SCENARIO_IDS), (1, 0)),
                (list(fixture.SCENARIO_IDS), (0, 1, 1)), (list(reversed(fixture.SCENARIO_IDS)), (0, 1))):
            with self.subTest(selection=selection, indices=indices):
                report = self.report()
                report['selection'] = selection
                report['results'] = [report['results'][index] for index in indices]
                self.assertFalse(stage_tests_passed(report, fixture.SCENARIO_IDS, fixture.RUNTIME_GRANTS))

    def test_platform_failure_skips_unknown_outcome_or_implicit_grants_cannot_qualify(self):
        from tools.qualify_go_dependency_watch import stage_tests_passed
        changes = (('status', 'skipped'), ('category', 'platform-failure'), ('required', False),
            ('outcomeKnown', False), ('targetMatches', False), ('outcomeKnown', 1),
            ('execution', {'grants': []}), ('execution', {'grants': list(fixture.RUNTIME_GRANTS),
                                                         'deniedCapabilities': [fixture.RUNTIME_GRANTS[0]]}))
        for field, value in changes:
            with self.subTest(field=field, value=value):
                report = self.report(); report['results'][1][field] = value
                self.assertFalse(stage_tests_passed(report, fixture.SCENARIO_IDS, fixture.RUNTIME_GRANTS))
        for field in self.report()['results'][0]:
            with self.subTest(missing=field):
                report = self.report(); del report['results'][1][field]
                self.assertFalse(stage_tests_passed(report, fixture.SCENARIO_IDS, fixture.RUNTIME_GRANTS))

    def test_report_failure_ambiguous_cleanup_or_non_node_execution_cannot_qualify(self):
        from tools.qualify_go_dependency_watch import stage_tests_passed
        for field, value in (('passed', False), ('passed', 1), ('environment', 'portable'),
                ('cleanup', 'client-cleanup-unconfirmed-node-retained'), ('pendingOperation', {'kind': 'deploy'})):
            with self.subTest(field=field, value=value):
                report = self.report(); report[field] = value
                self.assertFalse(stage_tests_passed(report, fixture.SCENARIO_IDS, fixture.RUNTIME_GRANTS))
        for report in (None, [], {}, {'passed': True}):
            self.assertFalse(stage_tests_passed(report, fixture.SCENARIO_IDS, fixture.RUNTIME_GRANTS))


class FrontendRuntime(unittest.TestCase):
    def test_exact_frontend_ignores_ambient_python_inputs_and_never_writes_bytecode(self):
        import ast
        import json
        import hashlib
        import os
        import subprocess
        import sys
        from types import SimpleNamespace
        import zipfile
        from tools import qualify_go_dependency_watch as qualifier

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            helper = root / 'helper.pyz'
            with zipfile.ZipFile(helper, 'w') as archive:
                archive.writestr('tools/__init__.py', '')
                archive.writestr('tools/dev_workflow/__init__.py', '')
                archive.writestr('tools/dev_workflow/cli.py',
                    'import json,sys\n'
                    'def main():\n'
                    ' print(json.dumps({"isolated":sys.flags.isolated,'
                    '"ignoreEnvironment":sys.flags.ignore_environment,'
                    '"noBytecode":sys.dont_write_bytecode,"cachePrefix":sys.pycache_prefix}))\n'
                    ' return 0\n')
            frontend, events = root / 'frontend.py', root / 'events.jsonl'
            python = Path(sys.executable)
            args = SimpleNamespace(helper=helper,
                helper_sha256='sha256:' + hashlib.sha256(helper.read_bytes()).hexdigest())
            qualifier.write_frontend(frontend, python, args, events)
            header = frontend.read_text().splitlines()[0]
            self.assertTrue(header.startswith('#!' + str(python)))
            argument = header[len('#!' + str(python)):].strip()
            environment = {'PATH': os.defpath, 'HOME': temporary, 'TEMP': temporary, 'TMP': temporary,
                'PYTHONPATH': str(root / 'ambient-imports'),
                'PYTHONPYCACHEPREFIX': str(root / 'ambient-bytecode')}
            if sys.platform == 'win32':
                environment['SystemRoot'] = os.environ['SystemRoot']
            result = subprocess.run([str(python), *([argument] if argument else []), str(frontend)],
                cwd=root, env=environment, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
            self.assertEqual(json.loads(result.stdout), {'isolated': 1, 'ignoreEnvironment': 1,
                'noBytecode': True, 'cachePrefix': None})
            self.assertEqual(events.read_bytes(), result.stdout)
            self.assertFalse((root / 'ambient-bytecode').exists())


class PublicWatchEvents(unittest.TestCase):
    def test_projection_rejects_private_fields_invalid_codes_and_non_bool_uncertainty(self):
        from tools.qualify_go_dependency_watch import public_events
        secret = '/private/source/token-secret/signing-key'
        observed = public_events([
            None, [], secret, 1,
            {'event': 'edit-failed', 'phase': 'build', 'code': 'guest-build-failed-last-deployment-retained',
             'uncertain': False, 'path': secret, 'details': {'privateKey': secret},
             'stdout': secret, 'result': {'secret': secret}},
            {'event': 'UPPERCASE', 'phase': secret, 'code': 'code\nsecret', 'uncertain': 1},
            {'event': 'x' * 129, 'phase': [], 'code': '', 'uncertain': 'false'},
            {'event': 'token-secret', 'phase': 'a' * 64, 'code': 'token-secret'},
            {'event': 'a' * 64, 'phase': 'token-secret', 'code': 'a' * 64},
            {'code': 'x' * 128, 'uncertain': True},
        ])
        self.assertEqual(observed, [
            {'event': 'edit-failed', 'phase': 'build', 'code': 'guest-build-failed-last-deployment-retained',
             'uncertain': False},
            {'uncertain': True},
        ])
        self.assertNotIn(secret, str(observed))
        self.assertNotIn('token-secret', str(observed))
        self.assertNotIn('a' * 64, str(observed))

    def test_projection_retains_only_the_last_32_observations(self):
        from tools.qualify_go_dependency_watch import public_events
        values = [{'code': 'success'} for _ in range(8)] + [
            {'code': 'workspace-recipe-trust-required'} for _ in range(32)]
        self.assertEqual(public_events(values), values[-32:])

    def test_public_event_phase_and_code_vocabulary_has_only_real_producer_literals(self):
        import ast
        import inspect
        from tools.qualify_go_dependency_watch import public_events
        tree = ast.parse(inspect.getsource(public_events))
        assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == 'allowed' for target in node.targets)]
        self.assertEqual(len(assignments), 1)
        allowed = ast.literal_eval(assignments[0].value)
        self.assertEqual(set(allowed), {'event', 'phase', 'code'})
        self.assertEqual(tuple(len(allowed[key]) for key in ('event', 'phase', 'code')), (5, 4, 23))
        root = Path(__file__).resolve().parents[2]
        actual = set()
        for name in ('tools/dev_workflow/cli.py', 'tools/dev_workflow/watch.py',
                     'tools/dev_workflow/build.py', 'tools/dev_workflow/build_client.py',
                     'tools/dev_workflow/node_test_signing.py', 'tools/dev_workflow/tool_inventory.py',
                     'tools/dev_workflow/paths.py', 'tools/dev_guest_recipe.py'):
            actual.update(node.value for node in ast.walk(ast.parse((root / name).read_text()))
                          if isinstance(node, ast.Constant) and isinstance(node.value, str))
        self.assertLessEqual(set().union(*allowed.values()), actual)


class PublicBuildFailures(unittest.TestCase):
    def test_projection_retains_only_bounded_taxonomy_and_hashes_private_reason(self):
        import hashlib
        from tools.qualify_go_dependency_watch import public_build_failure
        secret = '/private/source/token-secret/signing-key'
        observed = public_build_failure({'stage': 'compile', 'reason': secret,
            'commands': [{'stage': 'component-build', 'exitCode': 1, 'argv': [secret], 'stderr': secret}],
            'path': secret, 'details': {'secret': secret}})
        self.assertEqual(observed, {'stage': 'compile',
            'reasonSha256': 'sha256:' + hashlib.sha256(secret.encode()).hexdigest(),
            'commands': [{'stage': 'component-build', 'exitCode': 1}]})
        self.assertNotIn(secret, str(observed))
        self.assertEqual(public_build_failure({'stage': [], 'reason': 'x' * 4097, 'commands': secret}), {})
        self.assertEqual(public_build_failure([]), {})
        self.assertEqual(public_build_failure({'reason': 'FileNotFoundError'})['exceptionKind'], 'FileNotFoundError')
        self.assertEqual(public_build_failure({'reason': 'unreviewed-go-toolchain'})['reasonCode'], 'unreviewed-go-toolchain')
        self.assertEqual(public_build_failure({'reason': 'captured-Go-build-cannot-use-an-additional-cache'})['reasonCode'],
                         'captured-Go-build-cannot-use-an-additional-cache')
        self.assertNotIn('reasonCode', public_build_failure({'reason': 'token-secret'}))

    def test_command_projection_retains_last_eight_and_rejects_invalid_types_or_private_paths(self):
        from tools.qualify_go_dependency_watch import public_build_failure
        commands = [{'stage': 'go-version', 'exitCode': index} for index in range(12)]
        self.assertEqual(public_build_failure({'commands': commands})['commands'], commands[-8:])
        values = [None, {'stage': [], 'exitCode': 1}, {'stage': 'x', 'exitCode': True},
                  {'stage': 'x' * 4097, 'exitCode': 0}, {'stage': 'valid', 'exitCode': 256}]
        self.assertEqual(public_build_failure({'commands': values}), {'commands': []})
        unknown = public_build_failure({'commands': [{'stage': 'token-secret', 'exitCode': 1}]})
        self.assertNotIn('token-secret', str(unknown))
        self.assertIn('stageSha256', unknown['commands'][0])

    def test_collector_reads_fixed_metadata_from_failed_owned_attempt_only(self):
        import hashlib
        import json
        from tools.qualify_go_dependency_watch import collect_build_failures
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / 'builds' / ('a' * 32) / 'source'
            source.parent.mkdir(parents=True, mode=0o700)
            source.mkdir(mode=0o700)
            output = source / 'output'; output.mkdir(mode=0o700)
            cache = source / 'build-cache'; cache.mkdir(mode=0o700)
            owner = {'id': 'a' * 32, 'key': 'sha256:' + '0' * 64, 'source': 'sha256:' + '1' * 64,
                     'recipe': 'sha256:' + '2' * 64, 'state': 'failed'}
            (source.parent / 'attempt.json').write_text(json.dumps(owner))
            (output / 'BUILD-FAILED.json').write_text(json.dumps({'stage': 'compile', 'reason': 'captured-input-missing'}))
            stdout = b'{"code":"compiler-input-or-build-failed"}'
            (cache / 'compiler-stdout.log').write_bytes(stdout)
            secret = b'/private/source/token-secret/signing-key'
            (cache / 'compiler-stderr.log').write_bytes(secret)
            observed = collect_build_failures(root, 'output')
            self.assertEqual(len(observed), 1)
            self.assertEqual(observed[0]['stage'], 'compile')
            self.assertEqual(observed[0]['adapterCode'], 'compiler-input-or-build-failed')
            self.assertEqual(observed[0]['compilerStderrSha256'], 'sha256:' + hashlib.sha256(secret).hexdigest())
            self.assertNotIn(secret.decode(), str(observed))
            owner['state'] = 'complete'; (source.parent / 'attempt.json').write_text(json.dumps(owner))
            self.assertEqual(collect_build_failures(root, 'output'), [])
            with self.assertRaisesRegex(ValueError, 'path-traversal'):
                collect_build_failures(root, '../private')

    def test_collector_refuses_unowned_or_excess_attempts_before_reading_metadata(self):
        from tools.qualify_go_dependency_watch import collect_build_failures
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); builds = root / 'builds'; builds.mkdir(mode=0o700)
            bad = builds / 'unknown'; bad.mkdir(mode=0o700)
            with self.assertRaisesRegex(ValueError, 'owned-attempt-required'):
                collect_build_failures(root, 'output')
            bad.rmdir()
            for index in range(5):
                (builds / (str(index) * 32)).mkdir(mode=0o700)
            with self.assertRaisesRegex(ValueError, 'attempt-limit'):
                collect_build_failures(root, 'output')

    def test_missing_receipt_and_each_stream_preserve_other_actual_read_metadata(self):
        import json
        from tools.dev_workflow import paths
        from tools.qualify_go_dependency_watch import collect_build_failures
        with tempfile.TemporaryDirectory() as temporary:
            for missing in ('receipt', 'stdout', 'stderr'):
                with self.subTest(missing=missing):
                    root = Path(temporary).resolve() / missing
                    source = root / 'builds' / ('a' * 32) / 'source'
                    source.parent.mkdir(parents=True, mode=0o700)
                    source.mkdir(mode=0o700)
                    cache = source / 'build-cache'; cache.mkdir(mode=0o700)
                    owner = {'id': 'a' * 32, 'key': 'sha256:' + '0' * 64, 'source': 'sha256:' + '1' * 64,
                             'recipe': 'sha256:' + '2' * 64, 'state': 'failed'}
                    (source.parent / 'attempt.json').write_text(json.dumps(owner))
                    if missing != 'receipt':
                        output = source / 'output'; output.mkdir(mode=0o700)
                        (output / 'BUILD-FAILED.json').write_text('{"stage":"compile"}')
                    for stream in ('stdout', 'stderr'):
                        if stream != missing:
                            (cache / ('compiler-' + stream + '.log')).write_bytes(
                                b'{"code":"compiler-input-or-build-failed"}' if stream == 'stdout' else b'private-stderr')
                    absent = 'output/BUILD-FAILED.json' if missing == 'receipt' else 'build-cache/compiler-' + missing + '.log'
                    with self.assertRaises(ValueError):
                        paths.read(source, absent, 1024 * 1024)
                    observed = collect_build_failures(root, 'output')[0]
                    self.assertEqual(observed['state'], 'failed')
                    self.assertEqual('stage' in observed, missing != 'receipt')
                    self.assertEqual('adapterCode' in observed, missing != 'stdout')
                    self.assertEqual('compilerStdoutSha256' in observed, missing != 'stdout')
                    self.assertEqual('compilerStderrSha256' in observed, missing != 'stderr')
                    self.assertNotIn('private-stderr', str(observed))

    def test_optional_file_does_not_swallow_unsafe_existing_entries_or_oversized_reads(self):
        import os
        from tools.qualify_go_dependency_watch import optional_failure_file
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / 'not-file').mkdir(mode=0o700)
            with self.assertRaisesRegex(ValueError, 'single-link-regular-file'):
                optional_failure_file(root, 'not-file', 16)
            target = root / 'metadata'; target.write_bytes(b'x' * 17)
            with self.assertRaisesRegex(ValueError, 'file-byte-limit'):
                optional_failure_file(root, 'metadata', 16)
            target.write_bytes(b'{}'); os.link(target, root / 'alias')
            with self.assertRaisesRegex(ValueError, 'single-link-regular-file'):
                optional_failure_file(root, 'metadata', 16)

    def test_public_codes_and_command_labels_are_closed_real_builder_literals(self):
        import ast
        import inspect
        from tools import qualify_go_dependency_watch as qualifier
        tree = ast.parse(inspect.getsource(qualifier.public_build_failure))
        public = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == 'reason':
                for comparison in node.comparators:
                    if isinstance(comparison, ast.Set):
                        values = {item.value for item in comparison.elts}
                        if 'unreviewed-go-toolchain' in values:
                            public.update(values)
            if (isinstance(node, ast.Compare) and isinstance(node.left, ast.Subscript)
                    and isinstance(node.left.value, ast.Name) and node.left.value.id == 'command'):
                for comparison in node.comparators:
                    if isinstance(comparison, ast.Set):
                        public.update(item.value for item in comparison.elts)
        root = Path(__file__).resolve().parents[2]
        actual = set()
        for name in ('tools/go_guest/compiler.py', 'tools/go_guest/checkpoints.py',
                     'tools/go_capsule_build.py', 'tools/guest_compatibility_build.py'):
            actual.update(node.value for node in ast.walk(ast.parse((root / name).read_text()))
                          if isinstance(node, ast.Constant) and isinstance(node.value, str))
        self.assertEqual(len(public), 29)
        self.assertLessEqual(public, actual)

    def test_parser_and_runtime_observer_errors_preserve_original_exception_identity(self):
        from tools.qualify_go_dependency_watch import add_public_diagnostics
        for observer_error, descriptor_error in ((RecursionError, RuntimeError), (RuntimeError, RecursionError)):
            with self.subTest(observer=observer_error.__name__, descriptor=descriptor_error.__name__):
                original = ValueError('initial-build-failed')
                public = {'passed': False, 'failure': str(original)}
                def broken_events():
                    raise observer_error('private-observer-details')
                def broken_descriptor():
                    raise descriptor_error('private-metadata-details')
                with self.assertRaises(ValueError) as observed:
                    try:
                        raise original
                    finally:
                        add_public_diagnostics(public, broken_events, Path('owned-workspace'), broken_descriptor)
                self.assertIs(observed.exception, original)
                self.assertEqual(public, {'passed': False, 'failure': 'initial-build-failed'})

    def test_bounded_deeply_nested_actual_metadata_cannot_replace_original_failure(self):
        import json
        from unittest.mock import patch
        from tools import qualify_go_dependency_watch as qualifier
        native_loads = json.loads
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / 'builds' / ('a' * 32) / 'source'
            source.parent.mkdir(parents=True, mode=0o700)
            source.mkdir(mode=0o700)
            output = source / 'output'; output.mkdir(mode=0o700)
            owner = {'id': 'a' * 32, 'key': 'sha256:' + '0' * 64, 'source': 'sha256:' + '1' * 64,
                     'recipe': 'sha256:' + '2' * 64, 'state': 'failed'}
            (source.parent / 'attempt.json').write_text(json.dumps(owner))
            raw = b'[' * 3000 + b'0' + b']' * 3000
            self.assertLess(len(raw), 65536)
            (output / 'BUILD-FAILED.json').write_bytes(raw)
            # C JSON decoder recursion limits differ between supported Python
            # versions. Exercise native parsing and inject failure only at the
            # actual bounded receipt parser, never at the collector boundary.
            for force_failure in (False, True):
                with self.subTest(parser='fault' if force_failure else 'native'):
                    attempted, failed = [], []
                    def parse(value, *args, **kwargs):
                        if value == raw:
                            attempted.append(True)
                            if force_failure:
                                failed.append(True)
                                raise RecursionError('private parser details')
                        try:
                            return native_loads(value, *args, **kwargs)
                        except RecursionError:
                            failed.append(True)
                            raise
                    original = RuntimeError('original-build-failure')
                    public = {'passed': False, 'failure': 'initial-build-failed'}
                    with patch.object(qualifier.json, 'loads', side_effect=parse):
                        with self.assertRaises(RuntimeError) as observed:
                            try:
                                raise original
                            finally:
                                qualifier.add_public_diagnostics(public, lambda: [], root, lambda: 'output')
                    self.assertIs(observed.exception, original)
                    self.assertEqual(attempted, [True])
                    expected = {'passed': False, 'failure': 'initial-build-failed', 'watchEvents': []}
                    if not failed:
                        expected['buildFailures'] = [{'state': 'failed'}]
                    self.assertEqual(public, expected)


class DeliveredGoCacheSelection(unittest.TestCase):
    def setUp(self):
        from contextlib import ExitStack
        from unittest.mock import patch
        from tools import dev_guest_recipe as adapter, dev_managed_tools
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.owner = self.root / 'attempt'
        self.application = self.owner / 'app'; self.application.mkdir(parents=True)
        (self.owner / 'build-cache').mkdir()
        self.output = self.owner / 'output'
        self.payload = self.root / 'payload'; (self.payload / 'sdk').mkdir(parents=True)
        self.staged = self.root / 'staged'; (self.staged / 'go-cache').mkdir(parents=True)
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(adapter.os.environ, {}, clear=True))
        self.stack.enter_context(patch.object(adapter.sys, 'platform', 'linux'))
        self.stack.enter_context(patch.object(adapter.platform, 'machine', return_value='x86_64'))
        self.stack.enter_context(patch.object(dev_managed_tools, 'unpack', return_value=self.staged))

    def frontend(self):
        import json
        from tools.tests.test_dev_contracts import descriptor
        value = descriptor(); value.update(language='go', inputRoots=['app'])
        value['template']['ownerIssue'] = 547
        value['build']['workingDirectory'] = 'app'
        (self.owner / 'latent.project.json').write_text(json.dumps(value))

    def invoke(self):
        from tools.dev_guest_recipe import compile_managed
        return compile_managed(self.payload, self.application, self.output, lambda: None, 'go')

    def test_base_project_preserves_exact_original_sdk_module_cache(self):
        from unittest.mock import patch
        from tools import go_capsule_build
        with patch.object(go_capsule_build, 'build') as build:
            self.invoke()
        self.assertEqual(build.call_args.kwargs, {'offline_cache': self.staged / 'go-cache'})
        self.assertEqual(build.call_args.args[0], self.application)

    def test_either_outer_manifest_or_lock_selects_captured_closure_without_sdk_cache(self):
        from unittest.mock import patch
        from tools import application_dependencies, go_capsule_build
        self.frontend()
        for marker in (application_dependencies.MANIFEST, application_dependencies.LOCK):
            with self.subTest(marker=marker):
                selected = self.owner / marker; selected.write_bytes(b'{}')
                with patch.object(go_capsule_build, 'build') as build:
                    self.invoke()
                self.assertIsNone(build.call_args.kwargs['offline_cache'])
                selected.unlink()

    def test_partial_invalid_capture_still_fails_actual_builder_before_compiler(self):
        from unittest.mock import patch
        from tools import application_dependencies
        from tools.go_guest.compiler import Compiler
        self.frontend()
        (self.owner / application_dependencies.MANIFEST).write_bytes(b'{}')
        with patch.object(Compiler, '__init__', side_effect=AssertionError('invalid capture reached compiler')) as compiler:
            with self.assertRaises(ValueError):
                self.invoke()
        compiler.assert_not_called()

    def test_actual_adapter_builder_and_compiler_reach_only_mocked_version_boundary(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from tools import application_dependencies, go_capsule_build as build, rust_capsule_build
        from tools.go_guest import compiler
        self.frontend()
        (self.owner / application_dependencies.MANIFEST).write_bytes(b'{}')
        repository = Path(__file__).resolve().parents[2]
        pins = (repository / 'sdk/go-guest/toolchain.lock.json').read_bytes()
        observed = SimpleNamespace(files={'vendor/lsf/sdk/go-guest/toolchain.lock.json': pins},
                                   dependency_root=self.owner)
        downloads = self.root / 'closure/module-downloads'; downloads.mkdir(parents=True)
        closure = SimpleNamespace(work=downloads.parent, lock={
            'selection': {'runtimeProfile': 'go-component-async-v1'},
            'artifacts': [{'metadata': {'assetType': 'selected-module-downloads'}, 'mount': downloads.name}]})
        executable = self.root / 'mock-compiler-input'; executable.write_bytes(b'never execute this fixture')
        class VersionBoundary(Exception):
            pass
        with patch.object(build.guest_dependency_inputs, 'capture_source', return_value=observed), \
                patch.object(build, 'validate', return_value=({'name': 'fixture', 'world': 'greeting'}, {}, {})), \
                patch.object(build, 'prepare', return_value=closure), \
                patch.object(compiler.shutil, 'which', return_value=str(executable)), \
                patch.object(compiler.Compiler, 'run', side_effect=VersionBoundary) as version, \
                patch.object(rust_capsule_build.Commands, 'run', side_effect=AssertionError('native tool execution')) as process:
            with self.assertRaisesRegex(ValueError, 'captured-Go-build-cannot-use-an-additional-cache'):
                compiler.Compiler(self.root / 'rejected-compiler', repository / 'sdk/go-guest',
                    SimpleNamespace(environment={'PATH': ''}), offline_cache=self.staged / 'go-cache',
                    application_closure=closure)
            version.assert_not_called()
            with self.assertRaises(VersionBoundary):
                self.invoke()
            version.assert_called_once_with('go-version', 'go', 'version')
            process.assert_not_called()

class PublicPostDeployFailures(unittest.TestCase):
    def test_projection_keeps_actual_failure_tokens_booleans_and_digests_without_private_data(self):
        from tools.qualify_go_dependency_watch import public_test_failure
        secret = 'token-secret'
        observed = public_test_failure([{'event': 'post-deploy-tests', 'report': {
            'passed': False, 'identity': {'secret': secret}, 'selection': [secret],
            'results': [{'id': secret, 'status': 'failed', 'category': 'platform-failure',
                'platformCode': 'permission-denied', 'reason': 'ValueError', 'outcomeKnown': True,
                'targetMatches': False, 'inputSha256': 'sha256:' + '1' * 64,
                'payloadSha256': 'sha256:' + '2' * 64, 'payload': secret, 'error': secret,
                'expectedRevision': secret, 'resolvedRevision': secret},
                {'status': secret, 'category': 'a' * 64, 'platformCode': secret, 'reason': '/private/path',
                 'outcomeKnown': 1, 'targetMatches': 'true', 'inputSha256': secret, 'payloadSha256': secret}]}}])
        self.assertFalse(observed['passed'])
        self.assertIs(observed['qualification'], False)
        self.assertEqual(observed['results'][0], {'ordinal': 1, 'status': 'failed',
            'category': 'platform-failure', 'platformCode': 'permission-denied', 'reason': 'ValueError',
            'outcomeKnown': True, 'targetMatches': False, 'inputSha256': 'sha256:' + '1' * 64,
            'payloadSha256': 'sha256:' + '2' * 64})
        self.assertEqual(set(observed['results'][1]), {'ordinal', 'statusSha256', 'categorySha256',
            'platformCodeSha256', 'reasonSha256'})
        for value in (secret, 'a' * 64, '/private/path', 'expectedRevision', 'resolvedRevision'):
            self.assertNotIn(value, str(observed))
        for row in observed['results']:
            for key in ('id', 'payload', 'error', 'expectedRevision', 'resolvedRevision'):
                self.assertNotIn(key, row)

    def test_projection_retains_last_failing_report_eight_ordinals_and_ignores_success_or_malformed(self):
        from tools.qualify_go_dependency_watch import public_test_failure
        failed = {'event': 'post-deploy-tests', 'report': {'passed': False,
            'results': [{'status': 'failed'} for _ in range(10)]}}
        values = [failed, {'event': 'post-deploy-tests', 'report': {'passed': True,
            'results': [{'status': 'passed'}]}}]
        observed = public_test_failure(values)
        self.assertEqual([row['ordinal'] for row in observed['results']], list(range(3, 11)))
        self.assertEqual(len(observed['results']), 8)
        self.assertEqual(public_test_failure([failed] + [{} for _ in range(32)]), {})
        self.assertEqual(public_test_failure([None, [], {'event': 'post-deploy-tests', 'report': []},
            {'event': 'post-deploy-tests', 'report': {'passed': 0}}]), {})
        self.assertEqual(public_test_failure([{'event': 'post-deploy-tests',
            'report': {'passed': False, 'results': 'private'}}]),
            {'qualification': False, 'passed': False, 'results': []})

    def test_failed_test_projection_errors_preserve_original_exception_and_success_never_collects(self):
        from unittest.mock import patch
        from tools import qualify_go_dependency_watch as qualifier
        original = ValueError('initial-actual-node-test-failed')
        public = {'passed': False, 'failure': str(original)}
        with patch.object(qualifier, 'public_test_failure', side_effect=RuntimeError('private')):
            with self.assertRaises(ValueError) as observed:
                try:
                    raise original
                finally:
                    qualifier.add_public_diagnostics(public, lambda: [], None, lambda: None)
        self.assertIs(observed.exception, original)
        self.assertEqual(public, {'passed': False, 'failure': 'initial-actual-node-test-failed', 'watchEvents': []})
        with patch.object(qualifier, 'public_test_failure', side_effect=AssertionError('successful receipt observed failure')):
            qualifier.add_public_diagnostics({'passed': True}, lambda: [], None, lambda: None)

    def test_projected_vocabulary_matches_actual_report_and_cli_producers(self):
        import ast
        import inspect
        import re
        from tools import qualify_go_dependency_watch as qualifier
        from tools.dev_workflow.node_diagnostics import TRAP_CODES
        tree = ast.parse(inspect.getsource(qualifier.public_test_failure))
        table = next(node.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == 'vocabulary' for target in node.targets))
        vocabulary = ast.literal_eval(table)
        root = Path(__file__).resolve().parents[2]
        producer = ast.parse((root / 'tools/dev_workflow/scenarios.py').read_text())
        actual = {node.value for node in ast.walk(producer) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        actual.update(node.id for node in ast.walk(producer) if isinstance(node, ast.Name))
        self.assertLessEqual(vocabulary['status'] | vocabulary['category'] | vocabulary['reason'], actual)
        cli_codes = set(re.findall(r'Code::[A-Za-z]+\s*=>\s*"([a-z-]+)"',
            (root / 'apps/latent/src/error.rs').read_text()))
        self.assertEqual(len(vocabulary['platformCode']), 22)
        self.assertLessEqual(vocabulary['platformCode'], cli_codes | TRAP_CODES)
