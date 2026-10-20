"""Owned NuGet watch fixtures; native library compilation is not modelled as execution."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools import dotnet_dependency_watch_fixture as fixture


class DotnetDependencyWatchFixture(unittest.TestCase):
    def prepared(self, parent):
        root = parent / 'library-preparation'; root.mkdir()
        rows = []
        for number in (1, 2):
            # These archive bytes test ownership/revision protocols only. Actual
            # PE images must come from the required hosted pinned compiler.
            raw = fixture.package(number, b'model-only-managed-image-' + str(number).encode())
            path = root / ('v' + str(number) + '.nupkg'); path.write_bytes(raw)
            rows.append({'revision': number, 'path': str(path), 'digest': fixture.digest(raw)})
        return {'root': str(root), 'packages': rows}

    def test_prepared_archive_identity_and_revision_are_preserved_after_original_removal(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary) / 'application'; app.mkdir()
            prepared = self.prepared(app.parent)
            inputs = fixture.create(app, prepared)
            self.assertFalse(Path(prepared['root']).exists())
            feed = Path(inputs['feed'])
            first = list(feed.iterdir())
            self.assertEqual(len(first), 1)
            with zipfile.ZipFile(first[0]) as archive:
                self.assertIn(b'<version>1.0.0</version>', archive.read(fixture.PRIMARY + '.nuspec'))
            fixture.remove_original(inputs)
            self.assertFalse(feed.exists())
            fixture.restore_revision(inputs, 2)
            with zipfile.ZipFile(next(feed.iterdir())) as archive:
                self.assertIn(b'<version>1.0.1</version>', archive.read(fixture.PRIMARY + '.nuspec'))
            self.assertNotEqual(inputs['inputDigests']['library-v1'], inputs['inputDigests']['library-v2'])

    def test_tampered_preparation_never_deletes_original_or_creates_capture_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary) / 'application'; app.mkdir()
            prepared = self.prepared(app.parent)
            Path(prepared['packages'][0]['path']).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                fixture.create(app, prepared)
            self.assertTrue(Path(prepared['root']).is_dir())
            self.assertFalse((app.parent / 'outside-watch-inputs').exists())

    def test_revision_and_cleanup_refuse_unknown_or_changed_owners(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary) / 'application'; app.mkdir()
            inputs = fixture.create(app, self.prepared(app.parent))
            feed = Path(inputs['feed']); before = next(feed.iterdir()).read_bytes()
            for number in (0, 3):
                with self.assertRaisesRegex(ValueError, 'unknown'):
                    fixture.restore_revision(inputs, number)
            with self.assertRaisesRegex(ValueError, 'fresh'):
                fixture.restore_revision(inputs, 2)
            changed = {**inputs, 'ownedRoot': str(app.resolve())}
            with self.assertRaisesRegex(ValueError, 'root changed'):
                fixture.remove_original(changed)
            self.assertEqual(next(feed.iterdir()).read_bytes(), before)

    def test_removal_entry_keeps_normal_export_and_fresh_state_without_library_reference(self):
        selected, removed = fixture.application_source(), fixture.application_source(removed=True)
        self.assertIn('DeveloperInput.LibraryPrefix.Read()', selected)
        self.assertIn('DeveloperInput.LibraryPrefix.Badge()', selected)
        self.assertNotIn('DeveloperInput', removed)
        self.assertIn('"removed/" + clean', removed)
        for source in (selected, removed):
            self.assertIn('namespace ServiceWorld.wit.Exports.examples.greeting', source)
            self.assertIn('Result<string,string>', source)
            self.assertIn('calls++ != 0', source)
            self.assertNotIn('unsafe', source)
        from tools.dotnet_guest import project
        from tools.dotnet_guest.runtime import RANDOM
        from tools.rust_capsule_project import snapshot
        with tempfile.TemporaryDirectory() as temporary:
            app = project.create(Path(temporary) / 'application', 'greeting')
            before = snapshot(app / 'vendor')
            fixture.declare_entropy(app)
            self.assertIn('import ' + RANDOM + ';', (app / 'wit/world.wit').read_text())
            self.assertEqual(snapshot(app / 'wit/deps/random'),
                             snapshot(app / 'vendor/lsf/wit/platform/random'))
            self.assertEqual(snapshot(app / 'vendor'), before)
            with self.assertRaisesRegex(ValueError, 'fixture-world'):
                fixture.declare_entropy(app)
            world = (app / 'wit/world.wit').read_bytes()
            next((app / 'vendor/lsf/wit/platform/random').rglob('*.wit')).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'vendored SDK changed'):
                fixture.declare_entropy(app)
            self.assertEqual((app / 'wit/world.wit').read_bytes(), world)

    def test_uncertain_shutdown_is_never_replayed_and_original_failure_is_preserved(self):
        from tools.qualify_dotnet_dependency_watch import ShutdownOnce
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
        from tools.qualify_dotnet_dependency_watch import ShutdownOnce
        fence = ShutdownOnce()
        receipt = {'state': 'stopped', 'reaped': True, 'cleanShutdown': True}
        self.assertIs(fence.call(lambda: receipt), receipt)
        with self.assertRaisesRegex(ValueError, 'already-attempted-no-retry'):
            fence.call(lambda: self.fail('replayed confirmed mutation'))

    def test_watch_delegation_operations_exist_in_maintained_frontend(self):
        import argparse
        import ast
        import inspect
        from tools import qualify_dotnet_dependency_watch as programme
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

class CapturedCompilerIdentity(unittest.TestCase):
    def test_relocated_exact_compiler_copy_is_accepted(self):
        from tools.build_observation import file_identity
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original, captured = root / 'original', root / 'captured'
            original.write_bytes(b'compiler identity control; never executed')
            captured.write_bytes(original.read_bytes())
            self.assertNotEqual(original.resolve(), captured.resolve())
            fixture.verify_compiler_copy(original, captured, file_identity(original, 'delivered-dotnet'))

    def test_changed_original_or_captured_compiler_is_rejected(self):
        from tools.build_observation import file_identity
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original, captured = root / 'original', root / 'captured'
            raw = b'compiler identity control; never executed'
            for changed in (original, captured):
                original.write_bytes(raw)
                captured.write_bytes(raw)
                expected = file_identity(original, 'delivered-dotnet')
                changed.write_bytes(raw + b'mutated')
                with self.subTest(changed=changed.name), self.assertRaisesRegex(ValueError, 'compiler identity changed'):
                    fixture.verify_compiler_copy(original, captured, expected)


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
        from tools import qualify_dotnet_dependency_watch as qualifier

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


class DeliveredCompilerHostPath(unittest.TestCase):
    def setUp(self):
        from contextlib import ExitStack
        from types import SimpleNamespace
        from unittest.mock import patch
        from tools import dotnet_compiler_isolation as isolation
        from tools import captured_compiler_isolation as captured
        from tools.dotnet_guest.runtime import ADAPTERS
        self.isolation = isolation
        self.captured = captured
        temporary = tempfile.TemporaryDirectory(prefix='dotnet-host-path-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = self.root / 'workspace'; self.workspace.mkdir()
        self.host_path = str(self.root / 'selected host tools')
        self.selected = {}
        for name in ('sh', 'bwrap', 'ldd', 'dotnet', 'wasm-tools', 'wit-bindgen', 'python'):
            path = self.root / name; path.write_bytes(('selected-' + name).encode())
            self.selected[name] = path
        roots = {}
        for name in ('dotnet-sdk', 'dotnet-runtime', 'dotnet-ref', 'dotnet-ref-aspnet', 'dotnet-hostfxr',
                     'component-composer', 'wasi-sdk'):
            path = self.root / name; path.mkdir(); (path / 'input').write_bytes(name.encode()); roots[name] = path
        (roots['component-composer'] / 'wac').write_bytes(b'selected-composer')
        runtimes = {}
        for name in ADAPTERS:
            path = self.root / ('runtime-' + name); path.write_bytes(('adapter-' + name).encode()); runtimes[name] = path
        stdlib = self.root / 'stdlib'; stdlib.mkdir(); (stdlib / 'selected.py').write_bytes(b'# selected stdlib')
        self.compiler = SimpleNamespace(roots=roots, dotnet=self.selected['dotnet'], runtimes=runtimes,
            wasi_sdk=roots['wasi-sdk'], wasm=self.selected['wasm-tools'], bindgen=self.selected['wit-bindgen'],
            compiler_patches=[], commands=SimpleNamespace(environment={'PATH': self.host_path}))
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(isolation.sys, 'platform', 'linux'))
        self.stack.enter_context(patch.object(isolation.sys, 'executable', str(self.selected['python'])))
        self.stack.enter_context(patch.object(isolation.sysconfig, 'get_path', return_value=str(stdlib)))
        self.stack.enter_context(patch.object(isolation.sysconfig, 'get_config_var', return_value=0))
        self.stack.enter_context(patch.object(isolation.os, 'getuid', return_value=1001, create=True))
        self.stack.enter_context(patch.object(isolation.os, 'getgid', return_value=1001, create=True))
        self.stack.enter_context(patch.dict(isolation.os.environ, {'PATH': '/nonexistent'}))
        self.loader = self.stack.enter_context(patch.object(captured, 'run_bounded_result',
            return_value=SimpleNamespace(returncode=0, stdout=b'statically linked', stderr=b'')))

    def lookup(self, name, *, path=None):
        if path is None:
            return None
        self.assertEqual(path, self.host_path)
        return str(self.selected[name])

    def capture_stage(self):
        from unittest.mock import patch, call
        captured = {}
        class NamespaceBoundary(Exception):
            pass
        def capture(workspace, tools, distributions, **arguments):
            captured.update(workspace=workspace, tools=tools, distributions=distributions, arguments=arguments)
            raise NamespaceBoundary()
        # Stop before the maintained Linux loader-directory boundary. Windows
        # drive paths cannot represent that namespace's colon-separated paths.
        with patch.object(self.isolation.shutil, 'which', side_effect=self.lookup) as lookup, \
                patch.object(self.isolation, 'DotnetIsolation', side_effect=capture) as constructor, \
                self.assertRaises(NamespaceBoundary):
            self.isolation.stage(self.compiler, self.workspace)
        constructor.assert_called_once()
        self.assertEqual(lookup.call_args_list, [call('sh', path=self.host_path)])
        self.loader.assert_not_called()
        return captured

    def selected_boundary(self, captured):
        from unittest.mock import patch
        # Exercise the real base constructor with the actual selected shell and
        # transported search path; loader probes are mocked before execution.
        with patch.object(self.isolation.shutil, 'which', side_effect=self.lookup):
            return self.captured.Isolation(captured['workspace'], {'shell': captured['tools']['shell']}, {},
                host_tool_path=captured['arguments']['host_tool_path'])

    def test_actual_stage_transports_explicit_path_to_shell_and_namespace_tool_capture(self):
        from tools.build_observation import file_identity
        captured = self.capture_stage()
        self.assertEqual(captured['tools']['shell'], self.selected['sh'].resolve())
        self.assertEqual(captured['arguments'], {'host_tool_path': self.host_path,
            'loader_directories': (self.workspace / 'captured-dotnet-tools/python/lib',)})
        self.assertEqual(captured['distributions']['compiler-python-stdlib'],
                         self.workspace / 'captured-dotnet-tools/python')
        boundary = self.selected_boundary(captured)
        self.assertEqual(boundary.tool_before['shell'], file_identity(self.selected['sh'], 'shell'))
        self.assertEqual(boundary.sandbox, self.selected['bwrap'].resolve())
        self.assertEqual(boundary.receipt['loaderObserver'],
                         file_identity(self.selected['ldd'], 'loader-dependency-observer'))
        self.assertEqual(self.compiler.commands.environment['PATH'], self.host_path)
        self.assertEqual(self.isolation.os.environ['PATH'], '/nonexistent')
        self.assertTrue(self.loader.called)
        boundary.check_unchanged()

    def test_absent_selected_shell_refuses_before_staging_without_ambient_fallback(self):
        from unittest.mock import patch, call
        def missing(name, *, path=None):
            return str(self.selected[name]) if path is None else None
        with patch.object(self.isolation.shutil, 'which', side_effect=missing) as lookup, \
                self.assertRaisesRegex(self.isolation.DependencyError, 'compiler-shell-unavailable'):
            self.isolation.stage(self.compiler, self.workspace)
        self.assertEqual(lookup.call_args_list, [call('sh', path=self.host_path)])
        self.assertFalse((self.workspace / 'captured-dotnet-tools').exists())
        self.loader.assert_not_called()

    def test_absent_or_invalid_commands_path_never_inherits_parent_path(self):
        from unittest.mock import patch
        for path in (None, '', 'bad\0path', 1, []):
            if path is None:
                self.compiler.commands.environment.pop('PATH', None)
            else:
                self.compiler.commands.environment['PATH'] = path
            with self.subTest(path=path), patch.object(self.isolation.shutil, 'which') as lookup, \
                    self.assertRaisesRegex(self.isolation.DependencyError, 'host-tool-path-invalid'):
                self.isolation.stage(self.compiler, self.workspace)
            lookup.assert_not_called()
        self.assertFalse((self.workspace / 'captured-dotnet-tools').exists())
        self.loader.assert_not_called()

    def test_selected_shell_mutation_is_rejected_by_original_identity_guard(self):
        boundary = self.selected_boundary(self.capture_stage())
        self.selected['sh'].write_bytes(b'changed-selected-shell')
        with self.assertRaisesRegex(self.isolation.DependencyError, 'compiler-executable-mutated'):
            boundary.check_unchanged()


class PublicBuildFailureMetadata(unittest.TestCase):
    def owned(self, parent):
        from types import SimpleNamespace
        from unittest.mock import patch
        from tools.dev_workflow import paths, state, build_cache, build_control
        from tools.dev_workflow.common import DevError
        private = parent / 'private'; paths.new_directory(private)
        workspace = state.workspace(private, 'test-dotnet-diagnostic', create=True)
        paths.new_directory(workspace / 'builds')
        attempt = workspace / 'builds' / ('a' * 32); paths.new_directory(attempt)
        source = attempt / 'source'; paths.new_directory(source)
        paths.new_directory(source / 'output'); paths.new_directory(source / 'build-cache')
        source_id, recipe_id = 'sha256:' + '1' * 64, 'sha256:' + '2' * 64
        state.atomic(workspace, 'project.json', {'snapshot': source_id, 'trust': recipe_id,
            'descriptor': {'build': {'outputRoot': 'output'}}})
        state.atomic(attempt, 'attempt.json', {'id': attempt.name, 'state': 'running',
            'source': source_id, 'recipe': recipe_id, 'key': 'sha256:' + '3' * 64})
        # Exercise the real control/session and cache-state writers, mocking only
        # the Linux boot observation; no child process or compiler is executed.
        instance = SimpleNamespace(guest_instance=lambda: {'bootId': 'test-instance'})
        with patch.dict('sys.modules', {'tools.dev_workflow.service': instance}):
            with self.assertRaises(DevError), build_control.session(workspace, 'b' * 32) as control:
                control.attach(attempt)
                build_cache.transition(attempt, 'uncertain')
                raise DevError('guest-build-cleanup-unconfirmed', uncertain=True)
        failure = source / 'output/BUILD-FAILED.json'
        failure.write_text(json.dumps({'formatVersion': 1, 'stage': 'compile',
            'reason': 'private compiler text', 'commands': [{'stage': 'native-aot',
                'command': ['private application path'], 'exitCode': 1, 'seconds': 0.25}]}))
        adapter = source / 'build-cache/compiler-stdout.log'
        adapter.write_text(json.dumps({'schemaVersion': 'latent.dev.compiler-result.v1',
            'language': 'dotnet', 'ownerIssue': 549, 'cleanup': 'uncertain',
            'code': 'compiler-cleanup-unconfirmed'}))
        return workspace, attempt, failure, adapter

    def test_actual_owned_failure_producers_retain_closed_cause_and_bind_selection(self):
        from tools.qualify_dotnet_dependency_watch import collect_build_failure_metadata
        from tools.dev_workflow import state
        with tempfile.TemporaryDirectory() as temporary:
            workspace, attempt, failure, adapter = self.owned(Path(temporary).resolve())
            result = collect_build_failure_metadata(workspace)
            self.assertEqual(result['state'], 'uncertain')
            self.assertEqual(result['reasonCode'], 'guest-build-cleanup-unconfirmed')
            self.assertIs(result['qualification'], False)
            self.assertEqual(len(result['attempts']), 1)
            self.assertEqual(result['attempts'][0], {'state': 'uncertain',
                'source': 'sha256:' + '1' * 64, 'recipe': 'sha256:' + '2' * 64,
                'buildKey': 'sha256:' + '3' * 64, 'stage': 'compile',
                'commands': [{'stage': 'native-aot', 'exitCode': 1}],
                'failureDocument': 'observed', 'adapterResult': 'observed',
                'adapterCode': 'compiler-cleanup-unconfirmed', 'adapterCleanup': 'uncertain'})
            rendered = json.dumps(result)
            for private in ('private compiler text', 'private application path', str(workspace), attempt.name):
                self.assertNotIn(private, rendered)
            saved = state.load(workspace, 'project.json'); saved['snapshot'] = 'sha256:' + '4' * 64
            state.atomic(workspace, 'project.json', saved)
            self.assertEqual(collect_build_failure_metadata(workspace)['attempts'], [])

    def test_public_projection_rejects_unknown_fields_bools_and_unbounded_commands(self):
        from tools.qualify_dotnet_dependency_watch import _public_build_failure
        value = {'formatVersion': 1, 'stage': 'compile', 'reason': 'private unknown reason',
            'commands': [{'stage': 'native-aot', 'exitCode': False},
                         {'stage': 'private command', 'exitCode': 1}]}
        self.assertEqual(_public_build_failure(value), {'stage': 'compile', 'commands': []})
        self.assertEqual(_public_build_failure({**value, 'formatVersion': True}), {})
        self.assertEqual(_public_build_failure({**value, 'commands': value['commands'] * 257}), {'stage': 'compile'})
        self.assertEqual(_public_build_failure({**value, 'stage': 'private source path',
            'reason': 'process-ownership', 'commands': []}), {'reasonCode': 'process-ownership', 'commands': []})

    def test_running_complete_or_wrong_producer_never_claim_a_failure_cause(self):
        from tools.qualify_dotnet_dependency_watch import collect_build_failure_metadata
        from tools.dev_workflow import state, build_cache
        with tempfile.TemporaryDirectory() as temporary:
            workspace, attempt, failure, adapter = self.owned(Path(temporary).resolve())
            active = state.load(workspace, 'active-build.json'); active['state'] = 'running'
            state.atomic(workspace, 'active-build.json', active)
            self.assertEqual(collect_build_failure_metadata(workspace)['attempts'], [])
            active['state'] = 'uncertain'; state.atomic(workspace, 'active-build.json', active)
            build_cache.transition(attempt, 'complete')
            self.assertEqual(collect_build_failure_metadata(workspace)['attempts'], [])
            build_cache.transition(attempt, 'uncertain')
            original = json.loads(adapter.read_text())
            for changed in ({'language': 'rust'}, {'ownerIssue': True}, {'ownerIssue': 544},
                            {'schemaVersion': 'different-producer'}, {'cleanup': 'reaped'},
                            {'code': 'private error'}, {'message': 'private message'}):
                with self.subTest(changed=changed):
                    adapter.write_text(json.dumps({**original, **changed}))
                    self.assertNotIn('adapterCode', collect_build_failure_metadata(workspace)['attempts'][0])

    def test_duplicate_nonfinite_oversize_and_hardlinked_metadata_refuse_safely(self):
        import os
        from tools.qualify_dotnet_dependency_watch import add_public_build_failure
        with tempfile.TemporaryDirectory() as temporary:
            workspace, attempt, failure, adapter = self.owned(Path(temporary).resolve())
            original = failure.read_bytes()
            for raw, refusal in ((b'{"formatVersion":1,"stage":"compile","stage":"private"}', 'schema'),
                        (b'{"formatVersion":1,"seconds":NaN}', 'schema'), (b' ' * 65537, 'bound')):
                with self.subTest(rawBytes=len(raw)):
                    failure.write_bytes(raw); public = {'passed': False, 'failure': 'initial-build-failed'}
                    add_public_build_failure(public, workspace)
                    self.assertEqual(public['buildFailureMetadata'], {'qualification': False, 'status': 'unavailable',
                        'readerPhase': 'failure-document', 'refusal': refusal})
                    self.assertEqual(public['failure'], 'initial-build-failed')
            failure.write_bytes(original)
            os.link(failure, failure.parent / 'same-file')
            public = {'passed': False}; add_public_build_failure(public, workspace)
            self.assertEqual(public['buildFailureMetadata'], {'qualification': False, 'status': 'unavailable',
                'readerPhase': 'failure-document', 'refusal': 'owner'})

    def test_attempt_bound_and_symlink_escape_never_read_foreign_metadata(self):
        import os
        from tools.qualify_dotnet_dependency_watch import add_public_build_failure
        from tools.dev_workflow import paths
        with tempfile.TemporaryDirectory() as temporary:
            workspace, attempt, failure, adapter = self.owned(Path(temporary).resolve())
            for number in range(4):
                paths.new_directory(workspace / 'builds' / (str(number) * 32))
            public = {'passed': False}; add_public_build_failure(public, workspace)
            self.assertEqual(public['buildFailureMetadata'], {'qualification': False, 'status': 'unavailable',
                'readerPhase': 'attempt-inventory', 'refusal': 'bound'})
            for number in range(4):
                (workspace / 'builds' / (str(number) * 32)).rmdir()
            foreign = failure.parent.parent / 'foreign'; foreign.mkdir()
            failure.unlink(); failure.parent.rmdir()
            try:
                os.symlink(foreign, failure.parent, target_is_directory=True)
            except OSError:
                # Windows developer-mode symlink privilege is optional locally;
                # the same mandatory test exercises this branch on Linux CI.
                if os.name != 'nt':
                    raise
            else:
                (foreign / 'BUILD-FAILED.json').write_text('{"private":"must never read"}')
                public = {'passed': False}; add_public_build_failure(public, workspace)
                self.assertEqual(public['buildFailureMetadata'], {'qualification': False, 'status': 'unavailable',
                    'readerPhase': 'failure-document', 'refusal': 'owner'})

    def test_observer_exception_cannot_replace_original_error_or_touch_success(self):
        from unittest.mock import patch
        from tools import qualify_dotnet_dependency_watch as programme
        original = RuntimeError('original uncertain build failure')
        public = {'passed': False, 'uncertain': True, 'failure': 'initial-build-failed'}
        with patch.object(programme, 'collect_build_failure_metadata', side_effect=RuntimeError('private observer text')):
            with self.assertRaises(RuntimeError) as seen:
                try:
                    raise original
                finally:
                    programme.add_public_build_failure(public, Path('private'))
            self.assertIs(seen.exception, original)
        self.assertIs(public['uncertain'], True)
        self.assertNotIn('private observer text', json.dumps(public))
        with patch.object(programme, 'collect_build_failure_metadata') as reader:
            passed = {'passed': True}; programme.add_public_build_failure(passed, Path('private'))
            programme.add_public_build_failure(public, None)
            reader.assert_not_called(); self.assertEqual(passed, {'passed': True})

    def test_missing_optional_files_are_distinct_from_invalid_actual_producer(self):
        from tools.qualify_dotnet_dependency_watch import collect_build_failure_metadata
        with tempfile.TemporaryDirectory() as temporary:
            workspace, attempt, failure, adapter = self.owned(Path(temporary).resolve())
            failure.unlink(); adapter.unlink()
            row = collect_build_failure_metadata(workspace)['attempts'][0]
            self.assertEqual(row['failureDocument'], 'missing')
            self.assertEqual(row['adapterResult'], 'missing')
            self.assertNotIn('stage', row); self.assertNotIn('adapterCode', row)
            failure.write_text('{"formatVersion":true,"private":"never publish"}')
            adapter.write_text('{"schemaVersion":"private unrecognized producer"}')
            row = collect_build_failure_metadata(workspace)['attempts'][0]
            self.assertEqual(row['failureDocument'], 'invalid')
            self.assertEqual(row['adapterResult'], 'invalid')
            self.assertNotIn('private', json.dumps(row))
            self.assertNotIn('stage', row); self.assertNotIn('adapterCode', row)

    def test_real_schema_and_owner_refusals_preserve_closed_reader_stage(self):
        from tools.qualify_dotnet_dependency_watch import add_public_build_failure
        from tools.dev_workflow import state
        with tempfile.TemporaryDirectory() as temporary:
            workspace, attempt, failure, adapter = self.owned(Path(temporary).resolve())
            original = state.load(workspace, 'active-build.json')
            state.atomic(workspace, 'active-build.json', {**original, 'state': 'private invalid state'})
            public = {'passed': False, 'uncertain': True, 'failure': 'initial-build-failed'}
            add_public_build_failure(public, workspace)
            self.assertEqual(public['buildFailureMetadata'], {'qualification': False, 'status': 'unavailable',
                'readerPhase': 'control-state', 'refusal': 'schema'})
            state.atomic(workspace, 'active-build.json', original)
            owner = state.load(workspace, 'owner.json')
            state.atomic(workspace, 'owner.json', {**owner, 'id': 'private wrong owner'})
            add_public_build_failure(public, workspace)
            self.assertEqual(public['buildFailureMetadata'], {'qualification': False, 'status': 'unavailable',
                'readerPhase': 'workspace-owner', 'refusal': 'owner'})
            self.assertIs(public['uncertain'], True)
            self.assertEqual(public['failure'], 'initial-build-failed')
            self.assertNotIn('private', json.dumps(public))

    def test_busy_actual_control_lock_preserves_original_uncertain_failure_without_retry(self):
        from unittest.mock import patch
        from tools.qualify_dotnet_dependency_watch import add_public_build_failure
        with tempfile.TemporaryDirectory() as temporary:
            workspace, attempt, failure, adapter = self.owned(Path(temporary).resolve())
            public = {'passed': False, 'uncertain': True, 'failure': 'initial-build-failed'}
            original = RuntimeError('original failure')
            with patch('tools.dev_workflow.state.lock', side_effect=BlockingIOError('private lock pathname')) as lock:
                with self.assertRaises(RuntimeError) as caught:
                    try:
                        raise original
                    finally:
                        add_public_build_failure(public, workspace)
            self.assertIs(caught.exception, original)
            lock.assert_called_once()
            self.assertEqual(public['buildFailureMetadata'], {'qualification': False, 'status': 'unavailable',
                'readerPhase': 'control-lock', 'refusal': 'busy'})
            self.assertIs(public['uncertain'], True)
            self.assertNotIn('private', json.dumps(public))

    def test_public_refusal_projection_rejects_unknown_or_malformed_exception_fields(self):
        from unittest.mock import patch
        from tools import qualify_dotnet_dependency_watch as programme
        for phase, refusal in (('private path', 'schema'), ('failure-document', 'private reason'),
                               (True, 'bound'), ('control-state', None)):
            with self.subTest(phase=phase, refusal=refusal), \
                    patch.object(programme, 'collect_build_failure_metadata',
                                 side_effect=programme._ProjectionRefusal(phase, refusal)):
                public = {'passed': False};programme.add_public_build_failure(public, Path('not-read'))
                self.assertEqual(public['buildFailureMetadata'], {'qualification': False, 'status': 'unavailable'})


class OptionalAdapterFailureIsolation(unittest.TestCase):
    def test_empty_malformed_and_bounded_invalid_adapter_keep_authenticated_failure(self):
        from tools.qualify_dotnet_dependency_watch import collect_build_failure_metadata
        from tools.dev_workflow.common import encode
        for raw, refusal in ((b'', 'bound'), (b'{', 'schema'),
                (b'{"code":1,"code":2}', 'schema'), (b'{"seconds":NaN}', 'schema'),
                (b' ' * 262145, 'bound'),
                (encode([None] * 32769), 'bound')):
            with self.subTest(bytes=len(raw)), tempfile.TemporaryDirectory() as temporary:
                workspace, attempt, failure, adapter = PublicBuildFailureMetadata().owned(Path(temporary).resolve())
                adapter.write_bytes(raw)
                value = collect_build_failure_metadata(workspace)
                self.assertEqual(value['state'], 'uncertain')
                self.assertEqual(value['reasonCode'], 'guest-build-cleanup-unconfirmed')
                row = value['attempts'][0]
                self.assertEqual(row['stage'], 'compile')
                self.assertEqual(row['commands'], [{'stage': 'native-aot', 'exitCode': 1}])
                self.assertEqual(row['failureDocument'], 'observed')
                self.assertEqual(row['adapterResult'], 'invalid')
                self.assertEqual(row['adapterRefusal'], refusal)
                self.assertNotIn('adapterCode', row)
                self.assertNotIn('private', json.dumps(value))

    def test_invalid_adapter_does_not_relax_owner_or_final_identity_checks(self):
        import os
        from unittest.mock import patch
        from tools import qualify_dotnet_dependency_watch as programme
        from tools.dev_workflow import build_cache, state
        for kind in ('hardlink', 'changed'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                workspace, attempt, failure, adapter = PublicBuildFailureMetadata().owned(Path(temporary).resolve())
                adapter.write_bytes(b'')
                public = {'passed': False, 'uncertain': True, 'failure': 'initial-build-failed'}
                if kind == 'hardlink':
                    os.link(adapter, adapter.parent / 'alias')
                    programme.add_public_build_failure(public, workspace)
                    self.assertEqual(public['buildFailureMetadata']['refusal'], 'owner')
                else:
                    actual = programme._failure_file
                    def mutate(root, relative, maximum):
                        raw = actual(root, relative, maximum)
                        if relative.endswith('compiler-stdout.log'):
                            value = build_cache.owner(attempt)
                            state.atomic(attempt, 'attempt.json', {**value, 'key': 'sha256:' + '9' * 64})
                        return raw
                    with patch.object(programme, '_failure_file', side_effect=mutate):
                        programme.add_public_build_failure(public, workspace)
                    self.assertEqual(public['buildFailureMetadata']['readerPhase'], 'final-state')
                    self.assertEqual(public['buildFailureMetadata']['refusal'], 'changed')
                self.assertNotIn('attempts', public['buildFailureMetadata'])
                self.assertIs(public['uncertain'], True)
                self.assertEqual(public['failure'], 'initial-build-failed')


class BoundCompilerReasonProjection(unittest.TestCase):
    def owned(self, parent):
        from tools.dev_workflow import state
        from tools.dev_workflow.common import HOST_ABI, digest, encode
        from tools.rust_capsule_project import ROOT
        workspace, attempt, failure, adapter = PublicBuildFailureMetadata().owned(parent)
        names = ('tools/dotnet_guest/build.py', 'tools/dotnet_guest/compiler.py', 'tools/dotnet_guest/sdk.py')
        recipe = {name: {'digest': digest((ROOT / name).read_bytes()), 'size': (ROOT / name).stat().st_size}
                  for name in names}
        value = {'schemaVersion': 'latent.dev.guest-tools.v1', 'language': 'dotnet', 'ownerIssue': 549,
            'sourceCommit': 'b' * 40, 'hostAbi': HOST_ABI, 'host': 'linux-x86_64',
            'files': [{'path': 'recipe/' + name, 'sha256': row['digest'], 'size': row['size']}
                      for name, row in sorted(recipe.items())]}
        value['identity'] = digest(encode(value))
        inventory = attempt / 'tool-inventory.json'; inventory.write_bytes(encode(value))
        selected = state.load(workspace, 'project.json')
        selected['descriptor'].update(language='dotnet', hostAbi=HOST_ABI,
            template={'ownerIssue': 549, 'revision': 'b' * 40})
        selected['descriptor']['build']['inventory'] = {'path': 'guest-tools.json', 'sha256': digest(inventory.read_bytes())}
        state.atomic(workspace, 'project.json', selected)
        recipe_path = failure.parent / 'recipe-inputs.json'; recipe_path.write_bytes(encode(recipe))
        generated = parent / 'generated'; generated.mkdir()
        from tools.dotnet_guest.sdk import install
        with self.assertRaises(ValueError) as raised:
            install(parent / 'unused-sdk', generated, parent / 'unused-output')
        failure.write_bytes(encode({'formatVersion': 1, 'stage': 'compile', 'reason': str(raised.exception),
            'commands': [{'stage': 'canonical-wit', 'exitCode': 0}]}))
        adapter.write_bytes(b'')
        return workspace, attempt, failure, adapter, inventory, recipe_path

    def test_actual_static_producer_error_is_projected_after_owned_recipe_binding(self):
        from tools.qualify_dotnet_dependency_watch import collect_build_failure_metadata
        from tools.dev_workflow.common import digest
        from tools.rust_capsule_project import ROOT
        with tempfile.TemporaryDirectory() as temporary:
            workspace, attempt, failure, adapter, inventory, recipe = self.owned(Path(temporary).resolve())
            result = collect_build_failure_metadata(workspace)
            row = result['attempts'][0]
            self.assertEqual(row['reasonCode'], 'dotnet-generated-world-namespace-ambiguous')
            self.assertEqual(row['reasonProducer'], {'helper': 'dotnet-sdk-facades',
                'digest': digest((ROOT / 'tools/dotnet_guest/sdk.py').read_bytes())})
            self.assertEqual(row['commands'], [{'stage': 'canonical-wit', 'exitCode': 0}])
            self.assertEqual(row['adapterResult'], 'invalid')
            self.assertEqual(result['state'], 'uncertain')
            self.assertIs(result['qualification'], False)
            self.assertNotIn(str(workspace), json.dumps(result))
            self.assertNotIn('ambiguous generated C# world namespace', json.dumps(result))

    def test_every_allowed_reason_is_an_exact_static_raise_in_its_bound_helper(self):
        import ast
        from tools import qualify_dotnet_dependency_watch as programme
        from tools.rust_capsule_project import ROOT
        seen = set()
        for name, producer in programme._COMPILE_REASON_PRODUCERS.items():
            tree = ast.parse((ROOT / name).read_bytes())
            actual = {node.exc.args[0].value for node in ast.walk(tree)
                if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)
                and isinstance(node.exc.func, ast.Name) and node.exc.func.id in {'ValueError', 'DependencyError'}
                and node.exc.args and isinstance(node.exc.args[0], ast.Constant)
                and isinstance(node.exc.args[0].value, str)}
            self.assertLessEqual(set(producer['codes']), actual)
            self.assertTrue(producer['codes'])
            for raw, code in producer['codes'].items():
                self.assertRegex(code, r'^[a-z][a-z0-9-]{0,127}$')
                self.assertNotIn(raw, seen); seen.add(raw)
        self.assertEqual(len(seen), 57)

    def test_private_prefix_suffix_unknown_and_nonliteral_reasons_remain_omitted(self):
        from tools import qualify_dotnet_dependency_watch as programme
        for reason in ('ambiguous generated C# world namespace:private',
                'private ambiguous generated C# world namespace', 'private/token/path',
                'x' * 65537, True, ['ambiguous generated C# world namespace']):
            with self.subTest(kind=type(reason).__name__), tempfile.TemporaryDirectory() as temporary:
                workspace, attempt, failure, adapter, inventory, recipe = self.owned(Path(temporary).resolve())
                value = json.loads(failure.read_bytes()); value['reason'] = reason
                failure.write_text(json.dumps(value))
                public = {'passed': False, 'uncertain': True, 'failure': 'initial-build-failed'}
                programme.add_public_build_failure(public, workspace)
                self.assertNotIn('reasonProducer', json.dumps(public))
                if 'attempts' in public['buildFailureMetadata']:
                    self.assertNotIn('reasonCode', public['buildFailureMetadata']['attempts'][0])
                self.assertEqual(public['failure'], 'initial-build-failed')
                self.assertIs(public['uncertain'], True)

    def test_missing_unpinned_malformed_and_oversize_evidence_never_claim_reason(self):
        from tools import qualify_dotnet_dependency_watch as programme
        from tools.dev_workflow import state
        for kind in ('missing', 'unpinned', 'duplicate', 'oversize', 'wrong-helper', 'wrong-stage', 'wrong-format'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                workspace, attempt, failure, adapter, inventory, recipe = self.owned(Path(temporary).resolve())
                if kind == 'missing':
                    recipe.unlink()
                elif kind == 'unpinned':
                    selected = state.load(workspace, 'project.json')
                    selected['descriptor']['build']['inventory']['sha256'] = 'sha256:' + '9' * 64
                    state.atomic(workspace, 'project.json', selected)
                elif kind == 'duplicate':
                    recipe.write_bytes(b'{"x":1,"x":2}')
                elif kind == 'oversize':
                    recipe.write_bytes(b' ' * (2 * 1024 * 1024 + 1))
                elif kind == 'wrong-helper':
                    value = json.loads(recipe.read_bytes()); value['tools/dotnet_guest/sdk.py']['digest'] = 'sha256:' + '8' * 64
                    recipe.write_text(json.dumps(value))
                else:
                    value = json.loads(failure.read_bytes())
                    value.update({'stage': 'package'} if kind == 'wrong-stage' else {'formatVersion': True})
                    failure.write_text(json.dumps(value))
                public = {'passed': False, 'uncertain': True, 'failure': 'initial-build-failed'}
                programme.add_public_build_failure(public, workspace)
                self.assertNotIn('reasonProducer', json.dumps(public))
                if 'attempts' in public['buildFailureMetadata']:
                    self.assertNotIn('reasonCode', public['buildFailureMetadata']['attempts'][0])
                self.assertEqual(public['failure'], 'initial-build-failed')
                self.assertIs(public['uncertain'], True)

    def test_hardlinked_evidence_or_selection_mutation_refuses_complete_observation(self):
        import os
        from unittest.mock import patch
        from tools import qualify_dotnet_dependency_watch as programme
        from tools.dev_workflow import state
        for kind in ('hardlink', 'selection', 'recipe'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                workspace, attempt, failure, adapter, inventory, recipe = self.owned(Path(temporary).resolve())
                if kind == 'hardlink':
                    os.link(recipe, recipe.parent / 'recipe-alias')
                actual = programme._failure_file
                def mutate(root, relative, maximum):
                    raw = actual(root, relative, maximum)
                    if relative.endswith('compiler-stdout.log'):
                        if kind == 'selection':
                            selected = state.load(workspace, 'project.json'); selected['trust'] = 'sha256:' + '7' * 64
                            state.atomic(workspace, 'project.json', selected)
                        elif kind == 'recipe':
                            recipe.write_bytes(recipe.read_bytes() + b' ')
                    return raw
                with patch.object(programme, '_failure_file', side_effect=mutate):
                    public = {'passed': False}; programme.add_public_build_failure(public, workspace)
                self.assertEqual(public['buildFailureMetadata']['status'], 'unavailable')
                self.assertNotIn('attempts', public['buildFailureMetadata'])

    def test_projection_failure_preserves_original_exception_identity(self):
        from unittest.mock import patch
        from tools import qualify_dotnet_dependency_watch as programme
        with tempfile.TemporaryDirectory() as temporary:
            workspace, attempt, failure, adapter, inventory, recipe = self.owned(Path(temporary).resolve())
            original = RuntimeError('original uncertain error')
            with patch.object(programme, '_bound_compile_reason', side_effect=RuntimeError('private input')):
                with self.assertRaises(RuntimeError) as caught:
                    try:
                        raise original
                    finally:
                        public = {'passed': False, 'uncertain': True}; programme.add_public_build_failure(public, workspace)
            self.assertIs(caught.exception, original)
            self.assertNotIn('private input', json.dumps(public))
            self.assertIs(public['uncertain'], True)


class CompileSetupFailureBreadcrumbs(unittest.TestCase):
    def test_real_setup_boundary_preserves_exception_and_projects_only_closed_context(self):
        from types import SimpleNamespace
        from tools.dotnet_guest.compiler import Compiler, compile_failure_context
        from tools import qualify_dotnet_dependency_watch as programme
        for original in (NameError('private/key/path'), FileExistsError('private/key/path')):
            with self.subTest(kind=type(original).__name__), tempfile.TemporaryDirectory() as temporary:
                holder=SimpleNamespace()
                def fail(): raise original
                with self.assertRaises(type(original)) as caught:
                    Compiler._setup(holder,'sdk-facades',fail)
                self.assertIs(caught.exception,original)
                context=compile_failure_context(holder,RuntimeError('later uncertain cleanup'))
                self.assertEqual(context,{'schemaVersion':'latent.dotnet.compile-setup-failure.v1',
                    'phase':'sdk-facades','exceptionKind':type(original).__name__,'exceptionBoundary':'setup-call'})
                workspace, attempt, failure, adapter, inventory, recipe=BoundCompilerReasonProjection().owned(Path(temporary).resolve())
                value=json.loads(failure.read_bytes()); value['reason']='private/key/path'; value['compileSetup']=context
                failure.write_text(json.dumps(value))
                public=programme.collect_build_failure_metadata(workspace)
                row=public['attempts'][0]
                self.assertEqual(row['compileSetup'],context)
                self.assertEqual(row['reasonProducer']['helper'],'dotnet-compile-setup')
                self.assertNotIn('reasonCode',row)
                self.assertNotIn('private/key/path',json.dumps(public))
                self.assertEqual(public['state'],'uncertain')
                self.assertIs(public['qualification'],False)

    def test_unknown_context_does_not_publish_user_classes_or_arbitrary_phase(self):
        from types import SimpleNamespace
        from tools.dotnet_guest.compiler import Compiler, compile_failure_context
        class PrivateException(NameError): pass
        holder=SimpleNamespace()
        def fail(): raise PrivateException('credential')
        with self.assertRaises(PrivateException): Compiler._setup(holder,'resource-installation',fail)
        self.assertEqual(compile_failure_context(holder,PrivateException())['exceptionKind'],'other')
        for phase in ('private/path',[],None):
            holder.compile_failure_phase=phase
            self.assertIsNone(compile_failure_context(holder,ValueError('private')))

    def test_malformed_context_or_changed_compiler_recipe_never_claims_breadcrumb(self):
        from tools import qualify_dotnet_dependency_watch as programme
        good={'schemaVersion':'latent.dotnet.compile-setup-failure.v1','phase':'sdk-facades','exceptionKind':'NameError','exceptionBoundary':'setup-call'}
        for changes in ({'phase':'private/path'},{'phase':[]},{'exceptionKind':'PrivateException'},
                {'exceptionKind':True},{'exceptionBoundary':'private'},{'exceptionBoundary':[]},
                {'schemaVersion':'unknown'},{'extra':'private'},None):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as temporary:
                workspace, attempt, failure, adapter, inventory, recipe=BoundCompilerReasonProjection().owned(Path(temporary).resolve())
                value=json.loads(failure.read_bytes());value['reason']='private'
                value['compileSetup']={**good,**changes} if changes is not None else good
                failure.write_text(json.dumps(value))
                if changes is None:
                    data=json.loads(recipe.read_bytes());data['tools/dotnet_guest/compiler.py']['digest']='sha256:'+'8'*64
                    recipe.write_text(json.dumps(data))
                public={'passed':False,'uncertain':True};programme.add_public_build_failure(public,workspace)
                self.assertNotIn('compileSetup',json.dumps(public))
                self.assertNotIn('PrivateException',json.dumps(public))
                self.assertIs(public['uncertain'],True)

    def test_setup_success_returns_original_result_and_cleared_context_is_absent(self):
        from types import SimpleNamespace
        from tools.dotnet_guest.compiler import Compiler,compile_failure_context
        holder=SimpleNamespace();sentinel=object()
        self.assertIs(Compiler._setup(holder,'sdk-facades',lambda:sentinel),sentinel)
        holder.compile_failure_phase=None
        self.assertIsNone(compile_failure_context(holder,ValueError('secret')))

    def test_actual_compile_prefix_marks_sdk_failure_before_original_call(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from tools.dotnet_guest import compiler as module
        from tools.dotnet_guest import retirement
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);work=root/'work';work.mkdir();sdk=root/'sdk';sdk.mkdir()
            (work/'wit').mkdir();(work/'wit/world.wit').write_text('package sample:app; world guest {}')
            (work/'src').mkdir();(work/'src/Main.cs').write_text('class Main {}')
            (work/'Capsule.csproj').write_text('<Project />')
            (sdk/'global.json').write_text('{}');(sdk/'nuget.config').write_text('<configuration />')
            (sdk/'probes/smoke').mkdir(parents=True);(sdk/'probes/smoke/packages.lock.json').write_text('{}')
            instance=object.__new__(module.Compiler)
            instance.isolation=None;instance.sdk=sdk;instance.commands=SimpleNamespace(output=root)
            instance.wasm=root/'wasm';instance.python=root/'python';instance.application_closure=None
            original=FileExistsError('private owned path')
            calls=[]
            def run(stage,*args):
                calls.append(stage)
                if stage=='declared-runtime-wit': return b'{}'
                if stage=='bindings':
                    generated=Path(args[args.index('--out-dir')+1]);generated.mkdir()
                    (generated/'bindings.json').write_text('{}')
                if stage=='canonical-wit': return b'package sample:app; world guest {}'
                return b''
            instance.run=run
            with (patch.object(module,'interface_names',return_value={'imports':[]}),
                    patch.object(module.runtime,'select'),
                    patch.object(retirement,'prepare',return_value=(work/'wit',None)),
                    patch.object(module,'install_sdk',side_effect=original) as install):
                with self.assertRaises(FileExistsError) as caught:
                    instance.compile(work,'guest',root/'output')
            self.assertIs(caught.exception,original)
            install.assert_called_once_with(sdk,root/'output/generated',root/'output/project/lsf')
            self.assertEqual(calls,['declared-runtime-wit','bindings','bindings-drift','canonical-wit'])
            self.assertEqual(module.compile_failure_context(instance,caught.exception)['phase'],'sdk-facades')


class FailureProducerReaderRefusal(unittest.TestCase):
    def test_reader_import_failure_is_closed_without_losing_original_uncertain_exception(self):
        from unittest.mock import patch
        from tools import qualify_dotnet_dependency_watch as programme
        for error in (NameError('private/path/token'), ModuleNotFoundError('private/module')):
            with self.subTest(kind=type(error).__name__), tempfile.TemporaryDirectory() as temporary:
                workspace, *_ = BoundCompilerReasonProjection().owned(Path(temporary).resolve())
                original=RuntimeError('original cleanup uncertainty')
                with patch.object(programme,'_bound_compile_reason',side_effect=error):
                    with self.assertRaises(RuntimeError) as caught:
                        try: raise original
                        finally:
                            public={'passed':False,'uncertain':True,'failure':'initial-build-failed'}
                            programme.add_public_build_failure(public,workspace)
                self.assertIs(caught.exception,original)
                self.assertEqual(public['buildFailureMetadata'],{'qualification':False,'status':'unavailable',
                    'readerPhase':'failure-producer','refusal':'unavailable','producerReaderStep':'imports',
                    'readerExceptionKind':type(error).__name__})
                self.assertIs(public['uncertain'],True)
                self.assertNotIn('private',json.dumps(public))
                self.assertNotIn('attempts',public['buildFailureMetadata'])

    def test_actual_inventory_failure_has_fixed_reader_step_and_rejects_private_subclass_name(self):
        from unittest.mock import patch
        from tools import qualify_dotnet_dependency_watch as programme
        class PrivateReaderError(RuntimeError): pass
        with tempfile.TemporaryDirectory() as temporary:
            workspace, *_ = BoundCompilerReasonProjection().owned(Path(temporary).resolve())
            with patch('tools.dev_workflow.tool_inventory.validate',side_effect=PrivateReaderError('private/token')):
                public={'passed':False};programme.add_public_build_failure(public,workspace)
            self.assertEqual(public['buildFailureMetadata'],{'qualification':False,'status':'unavailable',
                'readerPhase':'failure-producer','refusal':'unavailable','producerReaderStep':'tool-inventory',
                'readerExceptionKind':'other'})
            self.assertNotIn('PrivateReaderError',json.dumps(public))
            self.assertNotIn('private/token',json.dumps(public))
            self.assertNotIn('attempts',public['buildFailureMetadata'])


class DeliveredFailureProducerBinding(unittest.TestCase):
    def test_closed_enums_match_real_producer_and_delivered_helper_omits_compiler(self):
        from tools import qualify_dotnet_dependency_watch as programme
        from tools.dotnet_guest import compiler
        from tools.build_dev_frontend import helper
        self.assertEqual(programme._COMPILE_SETUP_PHASES, compiler.COMPILE_SETUP_PHASES)
        self.assertEqual(programme._COMPILE_EXCEPTION_KINDS, compiler.COMPILE_EXCEPTION_KINDS)
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'helper.pyz';helper(path,resource_snapshot=())
            with zipfile.ZipFile(path) as archive:
                names=archive.namelist()
            self.assertIn('tools/dev_workflow/tool_inventory.py',names)
            self.assertFalse(any(name.startswith('tools/dotnet_guest/') for name in names))

    def test_flat_delivered_fixture_reads_explicit_pinned_recipe_without_compiler_import(self):
        from unittest.mock import patch
        from tools import qualify_dotnet_dependency_watch as programme
        from tools.rust_capsule_project import ROOT
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve()
            workspace,attempt,failure,adapter,inventory,recipe=BoundCompilerReasonProjection().owned(root)
            selected=root/'payload/recipe'
            for name in ('build.py','compiler.py','sdk.py'):
                target=selected/'tools/dotnet_guest'/name;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((ROOT/'tools/dotnet_guest'/name).read_bytes())
            # The real wrapper copies this script flat and supplies only helper.pyz.
            # The compiler package is deliberately unavailable in that Python realm.
            with patch.object(programme,'__file__',str(root/'flat/qualifier.py')), \
                    patch.dict('sys.modules',{'tools.dotnet_guest':None,'tools.dotnet_guest.compiler':None}):
                public={'passed':False,'uncertain':True,'failure':'initial-build-failed'}
                programme.add_public_build_failure(public,workspace,producer_root=selected)
            value=public['buildFailureMetadata']
            self.assertEqual(value['attempts'][0]['reasonCode'],'dotnet-generated-world-namespace-ambiguous')
            self.assertEqual(value['attempts'][0]['reasonProducer']['helper'],'dotnet-sdk-facades')
            self.assertEqual(value['state'],'uncertain')
            self.assertIs(value['qualification'],False)
            self.assertIs(public['uncertain'],True)
            self.assertEqual(public['failure'],'initial-build-failed')
            self.assertNotIn(str(root),json.dumps(public))

    def test_selected_recipe_missing_changed_linked_or_mutated_never_falls_back_to_checkout(self):
        import os
        from unittest.mock import patch
        from tools import qualify_dotnet_dependency_watch as programme
        from tools.rust_capsule_project import ROOT
        for kind in ('missing','changed','hardlink','mutation'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary).resolve()
                workspace,attempt,failure,adapter,inventory,recipe=BoundCompilerReasonProjection().owned(root)
                selected=root/'payload/recipe'
                for name in ('build.py','compiler.py','sdk.py'):
                    target=selected/'tools/dotnet_guest'/name;target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes((ROOT/'tools/dotnet_guest'/name).read_bytes())
                sdk=selected/'tools/dotnet_guest/sdk.py'
                if kind=='missing':sdk.unlink()
                if kind=='changed':sdk.write_bytes(sdk.read_bytes()+b'\n')
                if kind=='hardlink':os.link(sdk,sdk.parent/'sdk-alias.py')
                actual=programme._failure_file
                def read(owner,relative,maximum):
                    data=actual(owner,relative,maximum)
                    if kind=='mutation' and relative.endswith('compiler-stdout.log'):
                        sdk.write_bytes(sdk.read_bytes()+b'\n')
                    return data
                original=RuntimeError('original uncertain cleanup')
                with patch.object(programme,'_failure_file',side_effect=read):
                    with self.assertRaises(RuntimeError) as caught:
                        try:raise original
                        finally:
                            public={'passed':False,'uncertain':True,'failure':'initial-build-failed'}
                            programme.add_public_build_failure(public,workspace,producer_root=selected)
                self.assertIs(caught.exception,original)
                self.assertEqual(public['buildFailureMetadata']['status'],'unavailable')
                self.assertNotIn('attempts',public['buildFailureMetadata'])
                self.assertNotIn('reasonProducer',json.dumps(public))
                self.assertNotIn(str(root),json.dumps(public))
                self.assertIs(public['uncertain'],True)
