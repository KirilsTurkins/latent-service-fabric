"""C CLI uses selected standalone bytes while preserving original uncertain work."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from tools import c_dependency_authoring as authoring, guest_authoring_frontend as frontend
from tools.build_snapshot import digest
from tools.dev_workflow import cli
from tools.tests import test_c_dependency_authoring as fixtures


class CAuthoringFrontend(unittest.TestCase):
    setUp = fixtures.CDependencyAuthoring.setUp
    call = fixtures.CDependencyAuthoring.call
    capture = fixtures.CDependencyAuthoring.capture
    review = fixtures.CDependencyAuthoring.review
    descriptor = fixtures.CDependencyAuthoring.descriptor

    def selected(self):
        self.review(); self.descriptor()
        executable = self.root / 'reviewed-frontend'
        executable.write_bytes(b'explicitly reviewed frontend bytes')
        return executable, digest(executable.read_bytes())

    def test_explicit_c_test_and_watch_preserve_selected_arguments_and_uncertain_result_once(self):
        executable, identity = self.selected()
        seen = []
        raw = b'{"schemaVersion":"latent.dev.result.v1","code":"original-operation-unknown","uncertain":true}\n'
        def run(command, cwd, environment, seconds, maximum):
            seen.append((command, cwd, seconds, maximum))
            return subprocess.CompletedProcess(command, 5, raw, b'')
        with patch.object(frontend, 'run_bounded_result', side_effect=run), \
                patch.object(cli, 'main', side_effect=AssertionError('explicit selection fell back to source')):
            for action in ('test', 'watch'):
                code, out, err = self.call(action, self.project, '--workspace', 'test-c', '--select', 'greeting',
                    '--frontend', executable, '--frontend-sha256', identity, '--frontend-timeout', '315')
                self.assertEqual((code, out.encode(), err), (5, raw, ''))
        self.assertEqual(len(seen), 2)
        for command, cwd, seconds, maximum in seen:
            self.assertEqual(command[0], str(executable))
            self.assertEqual(cwd, self.project)
            self.assertEqual(seconds, 315)
            self.assertEqual(maximum, 1024 * 1024)
            self.assertIn(str(self.project), command)
        self.assertEqual(seen[0][0][1:3], ['dev', 'test'])
        self.assertEqual(seen[1][0][1:3], ['dev', 'up'])
        self.assertIn('--watch', seen[1][0])
        receipts = [json.loads(path.read_bytes()) for path in (self.project / authoring.STATE).glob('receipt-*.json')]
        self.assertEqual(len(receipts), 2)
        self.assertTrue(all(row['exitCode'] == 5 and row['frontendDigest'] == identity
                            and row['automaticReplay'] is False for row in receipts))

    def test_wrong_or_partial_c_frontend_identity_fails_before_any_dispatch_or_fallback(self):
        executable, _identity = self.selected()
        with patch.object(frontend, 'run_bounded_result') as run, patch.object(cli, 'main') as source:
            for options in (('--frontend', executable), ('--frontend-sha256', digest(b'absent')),
                            ('--frontend', executable, '--frontend-sha256', digest(b'changed'))):
                with self.subTest(options=options):
                    code, _out, err = self.call('test', self.project, '--workspace', 'test-c', *options)
                    self.assertEqual(code, 1)
                    self.assertIn('authoring-', err)
            run.assert_not_called(); source.assert_not_called()

    def test_receipt_write_failure_keeps_explicit_frontend_exit_five_and_original_output(self):
        executable, identity = self.selected()
        raw = b'{"schemaVersion":"latent.dev.result.v1","code":"operation-outcome-unknown","uncertain":true}\n'
        with patch.object(frontend, 'run_bounded_result', return_value=subprocess.CompletedProcess([], 5, raw, b'')) as run, \
                patch.object(authoring, 'record', side_effect=OSError('private-receipt-error')):
            code, out, err = self.call('test', self.project, '--workspace', 'test-c',
                '--frontend', executable, '--frontend-sha256', identity)
        self.assertEqual(code, 5)
        self.assertEqual(out.encode(), raw)
        self.assertEqual(run.call_count, 1)
        self.assertNotIn('private-receipt-error', err)

    def test_actual_staged_c_cli_verifies_capture_and_retains_selected_exit_without_controller_import(self):
        from tools.dev_tool_distribution import recipe
        executable, identity = self.selected()
        payload = self.root / 'payload'
        payload.mkdir()
        recipe(payload, 'c')
        staged = payload / 'recipe'
        script = '''import json,pathlib,subprocess,sys
root,project,selected,identity=map(str,sys.argv[1:])
sys.path.insert(0,root)
from tools import c_capsule,guest_authoring_frontend as frontend
called=[]
raw=b'{"schemaVersion":"latent.dev.result.v1","code":"original-operation-unknown","uncertain":true}\\n'
def run(command,cwd,env,seconds,maximum):
 assert command[0]==selected
 assert str(cwd)==project
 assert command[1:3]==['dev','test']
 assert str(project) in command
 called.append(command)
 return subprocess.CompletedProcess(command,5,raw,b'')
frontend.run_bounded_result=run
base=['test',project,'--workspace','test-c']
assert c_capsule.main(base)==1
assert called==[]
assert c_capsule.main([*base,'--frontend',selected,'--frontend-sha256',identity])==5
assert len(called)==1
assert 'tools.dev_workflow.cli' not in sys.modules
for name,module in tuple(sys.modules.items()):
 if name.startswith('tools.') and getattr(module,'__file__',None):
  assert pathlib.Path(module.__file__).resolve().is_relative_to(pathlib.Path(root)),name
rows=[json.loads(path.read_bytes()) for path in (pathlib.Path(project)/'target/c-dependency-authoring').glob('receipt-*.json')]
assert any(row.get('frontendDigest')==identity and row.get('exitCode')==5 and not row['automaticReplay'] for row in rows)
print('staged-c-selected-frontend-original-exit-five')
'''
        result = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(staged), str(self.project), str(executable), identity],
            cwd=payload, stdin=subprocess.DEVNULL, capture_output=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace')[:4096])
        self.assertEqual(result.stdout.splitlines()[-1], b'staged-c-selected-frontend-original-exit-five')
        self.assertIn(b'authoring-staged-recipe-requires-explicit-frontend', result.stderr)


if __name__ == '__main__':
    unittest.main()
