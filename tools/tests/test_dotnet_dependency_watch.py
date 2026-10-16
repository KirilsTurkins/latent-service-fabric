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
            tree = ast.parse(Path(qualifier.__file__).read_text())
            expressions = [node for node in ast.walk(tree)
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and isinstance(node.value.func.value, ast.Name)
                and node.value.func.value.id == 'frontend' and node.value.func.attr == 'write_text']
            self.assertEqual(len(expressions), 1)
            exec(compile(ast.Module(body=expressions, type_ignores=[]), '<actual-frontend>', 'exec'),
                {'frontend': frontend, 'python': python, 'args': args, 'events': events})
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
