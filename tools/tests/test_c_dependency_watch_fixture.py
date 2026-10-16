"""Actual capture/review operations for the finite installed C watch inputs."""
import json
from pathlib import Path
import tempfile
import unittest

from tools import c_capsule_project, c_dependency_authoring as author
from tools import c_dependency_watch_fixture as fixture
from tools import application_dependencies as dependencies
from tools.application_dependency_store import DependencyError
from tools.build_snapshot import digest
from tools.c_application_dependencies import selected


class WatchInputs(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = c_capsule_project.create(self.root / 'application', 'greeting')
        self.inputs = fixture.create(self.project)
        self.sdk = (self.project / 'sdk-lock.json').read_bytes()

    def add(self):
        declarations = self.inputs['declarations']
        author.edit(self.project, 'add', [json.loads(declarations[name].read_bytes())
                                        for name in ('child-v1', 'primary')], [])

    def review(self, label):
        candidate = self.root / (label + '.json')
        author.resolve(self.project, candidate)
        author.review(self.project, candidate, digest(candidate.read_bytes()))
        self.assertEqual((self.project / 'sdk-lock.json').read_bytes(), self.sdk)
        return candidate.read_bytes()

    def test_both_revisions_capture_offline_without_changing_sdk_or_adding_catalogue_entries(self):
        self.add(); initial = self.review('initial')
        fixture.remove_original(self.inputs, 'primary'); fixture.remove_original(self.inputs, 'child-v1')
        self.assertEqual(author.status(self.project)['status'], 'verified')
        changed = json.loads(self.inputs['declarations']['child-v2'].read_bytes())
        author.edit(self.project, 'update', [changed], [fixture.CHILD])
        with self.assertRaisesRegex(DependencyError, 'lock-drift'):
            author.status(self.project)
        self.assertEqual((self.project / dependencies.LOCK).read_bytes(), initial)
        fixture.restore_primary(self.inputs)
        updated = self.review('updated')
        self.assertNotEqual(updated, initial)
        fixture.remove_original(self.inputs, 'primary'); fixture.remove_original(self.inputs, 'child-v2')
        work, output = self.root / 'work', self.root / 'output'
        work.mkdir(); output.mkdir()
        closure = dependencies.prepare(self.project, work, output, 'c')
        choice = selected(closure, compiler_digest=digest(b'compiler'), runtime_digest=digest(b'runtime'))
        self.assertEqual(len(choice.sources), 1)
        headers = [path / 'child.h' for path in choice.includes if (path / 'child.h').exists()]
        self.assertEqual(len(headers), 1)
        self.assertIn(b'value + 40', headers[0].read_bytes())
        self.assertNotIn(b'latent_', choice.sources[0].read_bytes())
        closure.check_unchanged()

    def test_closed_remove_requires_new_review_and_retains_sdk_bytes(self):
        self.add(); initial = self.review('initial')
        author.edit(self.project, 'remove', [], [fixture.PRIMARY, fixture.CHILD])
        with self.assertRaisesRegex(DependencyError, 'lock-drift'):
            author.status(self.project)
        self.assertEqual((self.project / dependencies.LOCK).read_bytes(), initial)
        removed = self.review('removed')
        self.assertEqual(json.loads(removed)['artifacts'], [])
        self.assertEqual(author.status(self.project)['status'], 'verified')
        source = fixture.application_source(removed=True)
        self.assertNotIn('owned_api.h', source)
        self.assertIn('"removed/"', source)
        self.assertNotIn('stdio.h', source)
        self.assertNotIn('snprintf', source)

    def test_unexpected_original_input_is_preserved_instead_of_removed(self):
        path = self.inputs['root'] / 'primary/owned.c'
        path.write_bytes(b'changed outside library')
        with self.assertRaisesRegex(ValueError, 'input-bytes-changed'):
            fixture.remove_original(self.inputs, 'primary')
        self.assertEqual(path.read_bytes(), b'changed outside library')
        self.assertTrue((path.parent / 'owned_api.h').exists())


class ShutdownFence(unittest.TestCase):
    def test_uncertain_shutdown_preserves_original_error_and_never_replays_dispatch(self):
        from tools.qualify_c_dependency_watch import shutdown_once
        attempts, calls = set(), []
        original = RuntimeError('original-uncertain-down')
        def dispatch():
            calls.append('down')
            raise original
        with self.assertRaises(RuntimeError) as observed:
            shutdown_once(attempts, 'initial', dispatch)
        self.assertIs(observed.exception, original)
        with self.assertRaisesRegex(ValueError, 'normal-down-already-attempted'):
            shutdown_once(attempts, 'initial', dispatch)
        self.assertEqual(calls, ['down'])
        self.assertEqual(attempts, {'initial'})

    def test_confirmed_shutdown_is_once_per_distinct_workspace_and_keeps_original_receipt(self):
        from tools.qualify_c_dependency_watch import shutdown_once
        attempts, calls = set(), []
        receipt = {'state': 'stopped', 'reaped': True, 'cleanShutdown': True}
        def dispatch():
            calls.append('down')
            return receipt
        for workspace in ('initial', 'updated', 'removed'):
            self.assertIs(shutdown_once(attempts, workspace, dispatch), receipt)
            with self.assertRaisesRegex(ValueError, 'normal-down-already-attempted'):
                shutdown_once(attempts, workspace, dispatch)
        self.assertEqual(calls, ['down'] * 3)


class FrontendRuntime(unittest.TestCase):
    def test_exact_frontend_ignores_ambient_python_inputs_and_never_writes_bytecode(self):
        import ast
        import hashlib
        import os
        import subprocess
        import sys
        from types import SimpleNamespace
        import zipfile
        from tools import qualify_c_dependency_watch as qualifier

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


if __name__ == '__main__':
    unittest.main()
