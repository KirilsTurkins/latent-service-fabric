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
