"""Owned original Rust crate fixtures retain exact source/resource/version scope."""
from pathlib import Path
import tempfile
import tomllib
import unittest

from tools import rust_dependency_watch_fixture as fixture


class RustDependencyWatchFixture(unittest.TestCase):
    def test_two_real_crates_preserve_primary_api_and_resource_across_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            application = Path(temporary) / 'application'; application.mkdir()
            observed = fixture.create(application)
            primary, child = Path(observed['primary']), Path(observed['child'])
            v1 = tomllib.loads((primary / 'Cargo.toml').read_text())
            self.assertEqual(v1['package']['name'], fixture.PRIMARY)
            self.assertEqual(v1['dependencies'][fixture.CHILD], {'path': '../child', 'version': '=0.1.0'})
            self.assertEqual((primary / 'src/badge.txt').read_bytes(), fixture.RESOURCE)
            original_api = (primary / 'src/lib.rs').read_bytes()
            self.assertIn(b'value+39', (child / 'src/lib.rs').read_bytes())
            fixture.remove_original(observed, 'primary'); fixture.remove_original(observed, 'child')
            self.assertFalse(primary.exists() or child.exists())
            fixture.restore_revision(observed, 2)
            self.assertEqual(tomllib.loads((primary / 'Cargo.toml').read_text())['package']['version'], '0.1.1')
            self.assertEqual((primary / 'src/lib.rs').read_bytes(), original_api)
            self.assertIn(b'value+40', (child / 'src/lib.rs').read_bytes())
            self.assertNotEqual(observed['inputDigests']['child-v1'], observed['inputDigests']['child-v2'])
            self.assertFalse((application / 'app').exists())

    def test_cleanup_and_restore_refuse_unknown_roots_without_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            application = Path(temporary) / 'application'; application.mkdir()
            observed = fixture.create(application)
            primary = Path(observed['primary'])
            before = (primary / 'Cargo.toml').read_bytes()
            with self.assertRaisesRegex(ValueError, 'fresh'):
                fixture.restore_revision(observed, 2)
            with self.assertRaisesRegex(ValueError, 'unknown'):
                fixture.remove_original(observed, '../application')
            changed = {**observed, 'ownedRoot': str(application.resolve())}
            with self.assertRaisesRegex(ValueError, 'escaped'):
                fixture.remove_original(changed, 'primary')
            self.assertEqual((primary / 'Cargo.toml').read_bytes(), before)
            self.assertTrue(application.is_dir())

    def test_removal_entry_has_no_library_reference_and_keeps_normal_wit(self):
        selected = fixture.application_source()
        removed = fixture.application_source(removed=True)
        self.assertIn('outside_watch_primary::answer()', selected)
        self.assertNotIn('outside_watch_primary', removed)
        self.assertIn('removed/{name}', removed)
        for source in (selected, removed):
            self.assertIn('path:"wit",world:"service"', source)
            self.assertIn('CALLS.fetch_add', source)
            self.assertNotIn('unsafe', source)

    def test_uncertain_shutdown_is_never_replayed_and_original_failure_is_preserved(self):
        from tools.qualify_rust_dependency_watch import ShutdownOnce
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
        from tools.qualify_rust_dependency_watch import ShutdownOnce
        fence = ShutdownOnce()
        receipt = {'state': 'stopped', 'reaped': True, 'cleanShutdown': True}
        self.assertIs(fence.call(lambda: receipt), receipt)
        with self.assertRaisesRegex(ValueError, 'already-attempted-no-retry'):
            fence.call(lambda: self.fail('replayed confirmed mutation'))

class FrontendRuntime(unittest.TestCase):
    def test_exact_frontend_ignores_ambient_python_inputs_and_never_writes_bytecode(self):
        import json
        import hashlib
        import os
        import subprocess
        import sys
        from types import SimpleNamespace
        import zipfile
        from tools import qualify_rust_dependency_watch as qualifier

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
        from tools.qualify_rust_dependency_watch import public_events
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
        from tools.qualify_rust_dependency_watch import public_events
        values = [{'code': 'success'} for _ in range(8)] + [
            {'code': 'workspace-recipe-trust-required'} for _ in range(32)]
        self.assertEqual(public_events(values), values[-32:])

    def test_public_event_phase_and_code_vocabulary_has_only_real_producer_literals(self):
        import ast
        import inspect
        from tools.qualify_rust_dependency_watch import public_events
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
        from tools.qualify_rust_dependency_watch import public_build_failure
        secret = '/private/source/token-secret/signing-key'
        observed = public_build_failure({'stage': 'compile', 'reason': secret,
            'commands': [{'stage': 'component', 'exitCode': 1, 'argv': [secret], 'stderr': secret}],
            'path': secret, 'details': {'secret': secret}})
        self.assertEqual(observed, {'stage': 'compile',
            'reasonSha256': 'sha256:' + hashlib.sha256(secret.encode()).hexdigest(),
            'commands': [{'stage': 'component', 'exitCode': 1}]})
        self.assertNotIn(secret, str(observed))
        self.assertEqual(public_build_failure({'stage': [], 'reason': 'x' * 4097, 'commands': secret}), {})
        self.assertEqual(public_build_failure([]), {})
        self.assertEqual(public_build_failure({'reason': 'FileNotFoundError'})['exceptionKind'], 'FileNotFoundError')
        self.assertEqual(public_build_failure({'reason': 'standalone build deadline exceeded'})['reasonCode'], 'build-deadline')
        self.assertEqual(public_build_failure({'reason': 'wit-bindgen CLI does not match the project pin'})['reasonCode'],
                         'bindgen-profile-mismatch')
        self.assertNotIn('reasonCode', public_build_failure({'reason': 'token-secret'}))

    def test_command_projection_retains_last_eight_and_rejects_invalid_types_or_private_paths(self):
        from tools.qualify_rust_dependency_watch import public_build_failure
        commands = [{'stage': 'rust-sysroot', 'exitCode': index} for index in range(12)]
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
        from tools.qualify_rust_dependency_watch import collect_build_failures
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
        from tools.qualify_rust_dependency_watch import collect_build_failures
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
        from tools.qualify_rust_dependency_watch import collect_build_failures
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
        from tools.qualify_rust_dependency_watch import optional_failure_file
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
        from tools import qualify_rust_dependency_watch as qualifier
        tree = ast.parse(inspect.getsource(qualifier.public_build_failure))
        reasons, commands, stages = set(), set(), set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'reasons'
                    for target in node.targets)):
                reasons.update(key.value for key in node.value.keys)
            if isinstance(node, ast.Compare) and isinstance(node.left, ast.Subscript):
                for comparison in node.comparators:
                    if isinstance(comparison, ast.Set):
                        selected = {item.value for item in comparison.elts}
                        (commands if isinstance(node.left.value, ast.Name) and node.left.value.id == 'command'
                         else stages).update(selected)
        root = Path(__file__).resolve().parents[2]
        actual = set()
        for name in ('tools/rust_capsule_build.py', 'tools/guest_compatibility_build.py'):
            actual.update(node.value for node in ast.walk(ast.parse((root / name).read_text()))
                          if isinstance(node, ast.Constant) and isinstance(node.value, str))
        self.assertEqual((len(reasons), len(commands), len(stages)), (7, 11, 10))
        self.assertLessEqual(reasons | commands | stages, actual)

    def test_observer_and_metadata_errors_preserve_original_qualification_failure(self):
        from tools.qualify_rust_dependency_watch import add_public_diagnostics
        original = RuntimeError('original-qualification-failure')
        public = {'passed': False, 'failure': 'initial-build-failed'}
        def broken_events():
            raise ValueError('unsafe-observer')
        def broken_descriptor():
            raise KeyError('missing-output-root')
        with self.assertRaises(RuntimeError) as observed:
            try:
                raise original
            finally:
                add_public_diagnostics(public, broken_events, Path('owned-workspace'), broken_descriptor)
        self.assertIs(observed.exception, original)
        self.assertEqual(public, {'passed': False, 'failure': 'initial-build-failed'})

    def test_successful_receipt_does_not_collect_failure_metadata(self):
        from tools.qualify_rust_dependency_watch import add_public_diagnostics
        public = {'passed': True}
        add_public_diagnostics(public, lambda: [{'code': 'success', 'private': '/private'}],
            Path('owned-workspace'), lambda: self.fail('successful receipt collected failure metadata'))
        self.assertEqual(public, {'passed': True, 'watchEvents': [{'code': 'success'}]})

    def test_parser_and_runtime_observer_errors_preserve_original_exception_identity(self):
        from tools.qualify_rust_dependency_watch import add_public_diagnostics
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
        from tools.qualify_rust_dependency_watch import add_public_diagnostics
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / 'builds' / ('a' * 32) / 'source'
            source.parent.mkdir(parents=True, mode=0o700)
            source.mkdir(mode=0o700)
            output = source / 'output'; output.mkdir(mode=0o700)
            owner = {'id': 'a' * 32, 'key': 'sha256:' + '0' * 64, 'source': 'sha256:' + '1' * 64,
                     'recipe': 'sha256:' + '2' * 64, 'state': 'failed'}
            (source.parent / 'attempt.json').write_text(json.dumps(owner))
            raw = b'[' * 16384 + b'0' + b']' * 16384
            self.assertLess(len(raw), 65536)
            with self.assertRaises(RecursionError):
                json.loads(raw)
            (output / 'BUILD-FAILED.json').write_bytes(raw)
            original = RuntimeError('original-build-failure')
            public = {'passed': False, 'failure': 'initial-build-failed'}
            with self.assertRaises(RuntimeError) as observed:
                try:
                    raise original
                finally:
                    add_public_diagnostics(public, lambda: [], root, lambda: 'output')
            self.assertIs(observed.exception, original)
            self.assertEqual(public, {'passed': False, 'failure': 'initial-build-failed', 'watchEvents': []})


class PublicExecutableApproval(unittest.TestCase):
    def request(self):
        from types import SimpleNamespace
        from tools.application_dependency_approval import request
        from tools.build_snapshot import canonical, digest
        private = 'token-secret/' + 'a' * 64
        artifact = {'id': private, 'role': 'build-tool', 'format': 'directory',
            'source': {'path': '/private/' + private}, 'metadata': {'package': private,
            'version': private, 'nativeSourceDigest': digest(b'source'), 'sdkCompilerInput': False,
            'executableKinds': [['proc-macro', private], ['custom-build']]}}
        verified = SimpleNamespace(identity=digest(b'inputs'),
            lock={'selection': {'private': private}, 'artifacts': [artifact]})
        isolation = SimpleNamespace(receipt={'profile': 'linux-captured-compiler-namespaces-v1'})
        specification = request(verified, isolation, digest(b'recipe'))
        return {'formatVersion': 1, 'identity': digest(canonical(specification)),
            'specification': specification}, private

    def test_actual_request_producer_binds_exact_selection_without_private_text_or_authorization(self):
        from tools.qualify_rust_dependency_watch import public_executable_approval_request
        from tools.build_snapshot import canonical, digest
        request, private = self.request()
        observed = public_executable_approval_request(request)
        self.assertIs(observed['qualification'], False)
        self.assertEqual(observed['requestIdentity'], request['identity'])
        self.assertEqual(observed['executableInputsSha256'], digest(canonical(request['specification']['executableInputs'])))
        self.assertEqual(observed['executableInputCount'], 1)
        row = observed['inputs'][0]
        self.assertEqual(row['ordinal'], 0)
        self.assertEqual(row['executableKinds'], ['custom-build', 'proc-macro'])
        self.assertIs(row['sdkCompilerInput'], False)
        self.assertEqual(row['packageSha256'], digest(canonical(private)))
        self.assertNotIn(private, str(observed))
        self.assertNotIn('/private/', str(observed))
        self.assertNotIn('approvalIdentity', observed)

    def test_changed_request_identity_foreign_profile_and_invalid_scalars_are_not_projected(self):
        import copy
        from tools.qualify_rust_dependency_watch import public_executable_approval_request
        from tools.build_snapshot import canonical, digest
        request, _private = self.request()
        for field, invalid in (('network', 'allowed'), ('hermetic', 0),
                ('isolationProfile', 'foreign-profile'), ('inputIdentity', 'token-secret')):
            changed = copy.deepcopy(request)
            changed['specification'][field] = invalid
            changed['identity'] = digest(canonical(changed['specification']))
            self.assertEqual(public_executable_approval_request(changed), {})
        request['specification']['selection'] = {'changed': True}
        self.assertEqual(public_executable_approval_request(request), {})

    def test_projection_bounds_rows_uses_strict_booleans_and_omits_unknown_kinds(self):
        from tools.qualify_rust_dependency_watch import public_executable_approval_request
        from tools.build_snapshot import canonical, digest
        request, private = self.request()
        artifact = request['specification']['executableInputs'][0]
        artifact['metadata']['sdkCompilerInput'] = 1
        artifact['metadata']['executableKinds'] = [[private, 'proc-macro']]
        request['specification']['executableInputs'] = [artifact] * 9
        request['identity'] = digest(canonical(request['specification']))
        observed = public_executable_approval_request(request)
        self.assertEqual(observed['executableInputCount'], 9)
        self.assertEqual(len(observed['inputs']), 8)
        self.assertEqual([row['ordinal'] for row in observed['inputs']], list(range(8)))
        self.assertNotIn('sdkCompilerInput', observed['inputs'][0])
        self.assertEqual(observed['inputs'][0]['executableKinds'], ['proc-macro'])
        self.assertNotIn(private, str(observed))

    def test_projection_does_not_authorize_absent_or_wrong_approval_or_change_captured_inputs(self):
        from tools.tests.test_application_dependency_approval import ExecutionApproval
        from tools.application_dependencies import prepare
        from tools.application_dependency_approval import approve, request
        from tools.application_dependency_store import DependencyError
        from tools.build_snapshot import canonical, digest
        from tools.qualify_rust_dependency_watch import public_executable_approval_request
        fixture = ExecutionApproval()
        try:
            project, work, output, verified, isolation = fixture.fixture()
            before = {path.relative_to(project).as_posix(): path.read_bytes()
                      for path in project.rglob('*') if path.is_file()}
            sdk_lock = Path(__file__).resolve().parents[2] / 'tools/rust_capsule.lock'
            sdk_before = sdk_lock.read_bytes()
            specification = request(verified, isolation, digest(b'recipe'))
            observed = public_executable_approval_request({'formatVersion': 1,
                'identity': digest(canonical(specification)), 'specification': specification})
            self.assertIs(observed['qualification'], False)
            with self.assertRaisesRegex(DependencyError, '^dependency-executable-tools-require-isolated-stage$'):
                prepare(project, work, output, 'rust')
            with self.assertRaisesRegex(DependencyError, 'approval-mismatch'):
                approve(verified, isolation, digest(b'recipe'), digest(b'wrong-approval'))
            self.assertEqual(before, {path.relative_to(project).as_posix(): path.read_bytes()
                for path in project.rglob('*') if path.is_file()})
            self.assertEqual(sdk_lock.read_bytes(), sdk_before)
            self.assertEqual(list(work.iterdir()), [])
            self.assertEqual(list(output.iterdir()), [])
        finally:
            fixture.doCleanups()

    def test_owned_fixed_request_reader_preserves_original_approval_denial_and_missing_is_optional(self):
        import json
        from tools.qualify_rust_dependency_watch import add_public_diagnostics, collect_build_failures
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / 'builds' / ('a' * 32) / 'source'
            source.parent.mkdir(parents=True, mode=0o700)
            source.mkdir(mode=0o700)
            output = source / 'output'; output.mkdir(mode=0o700)
            owner = {'id': 'a' * 32, 'key': 'sha256:' + '0' * 64, 'source': 'sha256:' + '1' * 64,
                     'recipe': 'sha256:' + '2' * 64, 'state': 'failed'}
            (source.parent / 'attempt.json').write_text(json.dumps(owner))
            failure = {'stage': 'executable-input-approval',
                'reason': 'captured Cargo build scripts/macros require the exact retained executable-input approval identity'}
            (output / 'BUILD-FAILED.json').write_text(json.dumps(failure))
            self.assertNotIn('executableApprovalRequest', collect_build_failures(root, 'output')[0])
            request, private = self.request()
            target = output / 'executable-input-approval-request.json'
            target.write_text(json.dumps(request))
            original = RuntimeError('initial-build-failed')
            public = {'passed': False}
            with self.assertRaises(RuntimeError) as observed:
                try:
                    raise original
                finally:
                    add_public_diagnostics(public, lambda: [], root, lambda: 'output')
            self.assertIs(observed.exception, original)
            failure = public['buildFailures'][0]
            self.assertEqual(failure['reasonCode'], 'executable-input-approval-required')
            self.assertIs(failure['executableApprovalRequest']['qualification'], False)
            self.assertNotIn(private, str(public))
            target.unlink(); target.mkdir(mode=0o700)
            with self.assertRaisesRegex(ValueError, 'single-link-regular-file'):
                collect_build_failures(root, 'output')


class PublicFailureObservation(unittest.TestCase):
    def failed_attempt(self, root):
        from tools.dev_workflow import state
        builds = root / 'builds'; builds.mkdir(mode=0o700)
        attempt = builds / ('a' * 32); attempt.mkdir(mode=0o700)
        source = attempt / 'source'; source.mkdir(mode=0o700)
        output = source / 'output'; output.mkdir(mode=0o700)
        cache = source / 'build-cache'; cache.mkdir(mode=0o700)
        owner = {'id': attempt.name, 'key': 'sha256:' + '0' * 64,
                 'source': 'sha256:' + '1' * 64, 'recipe': 'sha256:' + '2' * 64, 'state': 'failed'}
        state.atomic(attempt, 'attempt.json', owner)
        return attempt, output, cache, owner

    def preserve_original(self, workspace, output_root):
        from tools.qualify_rust_dependency_watch import add_public_diagnostics
        original = RuntimeError('original-qualification-failure')
        public = {'passed': False, 'failure': 'initial-build-failed'}
        with self.assertRaises(RuntimeError) as observed:
            try:
                raise original
            finally:
                add_public_diagnostics(public, lambda: [], workspace, output_root)
        self.assertIs(observed.exception, original)
        return public

    def assert_closed_observation(self, public, phase, code):
        self.assertEqual(public, {'passed': False, 'failure': 'initial-build-failed', 'watchEvents': [],
            'buildFailureObservation': {'qualification': False, 'status': 'unavailable',
                                        'phase': phase, 'code': code}})

    def test_actual_descriptor_byte_refusal_retains_closed_observation_without_replacing_failure(self):
        from tools.dev_workflow import project
        from tools.dev_workflow.common import MAX_DOCUMENT
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            self.assertLessEqual(MAX_DOCUMENT, 4 * 1024 * 1024)
            (root / 'latent.project.json').write_bytes(b'x' * (MAX_DOCUMENT + 1))
            public = self.preserve_original(root, lambda: project.load(root)[0]['build']['outputRoot'])
            self.assert_closed_observation(public, 'output-root', 'file-byte-limit')

    def test_actual_oversized_metadata_still_refuses_and_retains_closed_observation(self):
        from tools.qualify_rust_dependency_watch import collect_build_failures
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            _attempt, output, _cache, _owner = self.failed_attempt(root)
            (output / 'BUILD-FAILED.json').write_bytes(b'x' * 65537)
            with self.assertRaisesRegex(ValueError, 'file-byte-limit'):
                collect_build_failures(root, 'output')
            public = self.preserve_original(root, lambda: 'output')
            self.assert_closed_observation(public, 'owned-attempt-metadata', 'file-byte-limit')

    def test_actual_link_and_owner_refusals_remain_closed_metadata_observations(self):
        import os
        from tools.dev_workflow import state
        from tools.qualify_rust_dependency_watch import collect_build_failures
        with tempfile.TemporaryDirectory() as temporary:
            for selected in ('link', 'owner'):
                with self.subTest(selected=selected):
                    root = Path(temporary).resolve() / selected; root.mkdir(mode=0o700)
                    attempt, output, _cache, owner = self.failed_attempt(root)
                    if selected == 'link':
                        target = output / 'BUILD-FAILED.json'; target.write_bytes(b'{}')
                        os.link(target, output / 'alias')
                        code = 'single-link-regular-file-required'
                    else:
                        state.atomic(attempt, 'attempt.json', {**owner, 'id': 'b' * 32})
                        code = 'unowned-build-attempt'
                    with self.assertRaisesRegex(ValueError, code):
                        collect_build_failures(root, 'output')
                    public = self.preserve_original(root, lambda: 'output')
                    self.assert_closed_observation(public, 'owned-attempt-metadata', code)

    def test_unknown_credentials_long_or_multiple_arguments_are_not_published(self):
        values = [ValueError('token-secret'), ValueError('a' * 64),
                  RuntimeError('/private/token-secret'), ValueError('x' * 129),
                  ValueError('source-file-unavailable-or-unsafe', 'token-secret')]
        for error in values:
            with self.subTest(arguments=len(error.args)):
                def unavailable():
                    raise error
                public = self.preserve_original(Path('owned-workspace'), unavailable)
                self.assertEqual(public, {'passed': False, 'failure': 'initial-build-failed', 'watchEvents': []})
                self.assertNotIn('token-secret', str(public))
                self.assertNotIn('a' * 64, str(public))
                self.assertNotIn('/private/', str(public))

    def test_unreadable_exception_arguments_cannot_replace_original_failure(self):
        class UnreadableArguments(Exception):
            def __getattribute__(self, name):
                if name == 'args':
                    raise RuntimeError('private-observer-details')
                return super().__getattribute__(name)
        def unavailable():
            raise UnreadableArguments()
        public = self.preserve_original(Path('owned-workspace'), unavailable)
        self.assertEqual(public, {'passed': False, 'failure': 'initial-build-failed', 'watchEvents': []})

    def test_existing_valid_metadata_and_success_output_remain_unchanged(self):
        import json
        from tools.qualify_rust_dependency_watch import add_public_diagnostics, collect_build_failures
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            _attempt, output, cache, _owner = self.failed_attempt(root)
            (output / 'BUILD-FAILED.json').write_text(json.dumps({'stage': 'compile', 'reason': 'captured-input-missing'}))
            (cache / 'compiler-stdout.log').write_bytes(b'{"code":"compiler-input-or-build-failed"}')
            expected = collect_build_failures(root, 'output')
            public = self.preserve_original(root, lambda: 'output')
            self.assertEqual(public, {'passed': False, 'failure': 'initial-build-failed',
                                     'watchEvents': [], 'buildFailures': expected})
            passed = {'passed': True}
            add_public_diagnostics(passed, lambda: [], root,
                                   lambda: self.fail('passing report observed failure metadata'))
            self.assertEqual(passed, {'passed': True, 'watchEvents': []})
