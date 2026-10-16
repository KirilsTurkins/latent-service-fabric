"""Owned original TypeScript package fixtures retain exact source/resource/version scope."""
from pathlib import Path
import tempfile
import json
import unittest

from tools import typescript_dependency_watch_fixture as fixture


class TypescriptDependencyWatchFixture(unittest.TestCase):
    def test_two_real_packages_preserve_primary_api_and_resource_across_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            application = Path(temporary) / 'application'; application.mkdir()
            observed = fixture.create(application)
            primary, child = Path(observed['primary']), Path(observed['child'])
            v1 = json.loads((primary / 'package.json').read_text())
            self.assertEqual(v1['name'], fixture.PRIMARY)
            self.assertEqual(v1['dependencies'][fixture.CHILD], 'file:../child-v1')
            self.assertEqual((primary / 'badge.txt').read_bytes(), fixture.RESOURCE)
            original_api = (primary / 'index.mjs').read_bytes()
            self.assertIn(b'value + 39', (child / 'index.mjs').read_bytes())
            fixture.remove_original(observed, 'primary'); fixture.remove_original(observed, 'child')
            self.assertFalse(primary.exists() or child.exists())
            fixture.restore_revision(observed, 2)
            primary, child = Path(observed['primary']), Path(observed['child'])
            self.assertEqual(json.loads((primary / 'package.json').read_text())['version'], '1.0.1')
            self.assertEqual((primary / 'index.mjs').read_bytes(), original_api)
            self.assertIn(b'value + 40', (child / 'index.mjs').read_bytes())
            self.assertNotEqual(observed['inputDigests']['child-v1'], observed['inputDigests']['child-v2'])
            self.assertFalse((application / 'app').exists())

    def test_cleanup_and_restore_refuse_unknown_roots_without_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            application = Path(temporary) / 'application'; application.mkdir()
            observed = fixture.create(application)
            primary = Path(observed['primary'])
            before = (primary / 'package.json').read_bytes()
            with self.assertRaisesRegex(ValueError, 'fresh'):
                fixture.restore_revision(observed, 2)
            with self.assertRaisesRegex(ValueError, 'unknown'):
                fixture.remove_original(observed, '../application')
            changed = {**observed, 'ownedRoot': str(application.resolve())}
            with self.assertRaisesRegex(ValueError, 'escaped'):
                fixture.remove_original(changed, 'primary')
            self.assertEqual((primary / 'package.json').read_bytes(), before)
            self.assertTrue(application.is_dir())

    def test_removal_entry_has_no_library_reference_and_keeps_normal_wit(self):
        selected = fixture.application_source()
        removed = fixture.application_source(removed=True)
        self.assertIn('answer()', selected)
        self.assertNotIn('outside-watch-primary', removed)
        self.assertIn('removed/${clean}', removed)
        for source in (selected, removed):
            self.assertIn('export const api: typeof Contract', source)
            self.assertIn('calls++ !== 0', source)
            self.assertNotIn('unsafe', source)

    def test_uncertain_shutdown_is_never_replayed_and_original_failure_is_preserved(self):
        from tools.qualify_typescript_dependency_watch import ShutdownOnce
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
        from tools.qualify_typescript_dependency_watch import ShutdownOnce
        fence = ShutdownOnce()
        receipt = {'state': 'stopped', 'reaped': True, 'cleanShutdown': True}
        self.assertIs(fence.call(lambda: receipt), receipt)
        with self.assertRaisesRegex(ValueError, 'already-attempted-no-retry'):
            fence.call(lambda: self.fail('replayed confirmed mutation'))

    def test_watch_delegation_operations_exist_in_maintained_frontend(self):
        import argparse
        import ast
        import inspect
        from tools import qualify_typescript_dependency_watch as programme
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
