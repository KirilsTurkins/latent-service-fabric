"""Real source/standalone frontend ownership, uncertain outcomes and staged denial."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch

from tools import guest_authoring_frontend as frontend
from tools.build_snapshot import digest
from tools.dev_workflow import cli
from tools.dev_workflow.common import DevError


class AuthoringFrontend(unittest.TestCase):
    def setUp(self):
        owned = tempfile.TemporaryDirectory(prefix='lsf-authoring-frontend-control-')
        self.addCleanup(owned.cleanup)
        self.root = Path(owned.name)
        self.project = self.root / 'application'
        self.project.mkdir()
        self.executable = Path(sys.executable).absolute()
        self.identity = digest(self.executable.read_bytes())

    def standalone(self, source, action='test', timeout=30):
        return frontend.execute(self.project, action, ['-I', '-c', source],
                                frontend=self.executable, expected=self.identity, timeout_seconds=timeout)

    def test_actual_same_tree_source_parser_preserves_uncertainty_and_never_replays(self):
        args = ['dev', 'test', '--workspace', 'test-owned', '--environment', 'node']
        with patch.object(cli, 'dispatch', side_effect=DevError('original-operation-unknown', uncertain=True)) as dispatch, \
                patch.object(cli, 'emit') as emit:
            outcome = frontend.execute(self.project, 'test', args)
        self.assertEqual(outcome.exit_code, 5)
        self.assertTrue(outcome.evidence['uncertain'])
        self.assertFalse(outcome.evidence['automaticReplay'])
        self.assertFalse(outcome.evidence['remoteCleanupConfirmed'])
        self.assertEqual(outcome.evidence['frontendMode'], 'owned-source')
        self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(emit.call_args.args[0]['code'], 'original-operation-unknown')

    def test_explicit_missing_or_changed_identity_cannot_execute_any_frontend(self):
        with patch.object(frontend, 'run_bounded_result') as run:
            for executable, identity in ((self.executable, None), (None, self.identity),
                                         (self.executable, digest(b'changed'))):
                with self.subTest(executable=executable, identity=identity):
                    with self.assertRaises(DevError):
                        frontend.execute(self.project, 'test', ['dev', 'test'], frontend=executable, expected=identity)
            run.assert_not_called()

    def test_frontend_inside_project_is_denied_before_process_or_source_fallback(self):
        selected = self.project / 'frontend'
        selected.write_bytes(b'not a frontend')
        with patch.object(frontend, 'run_bounded_result') as run, patch.object(cli, 'main') as source:
            with self.assertRaisesRegex(DevError, 'outside-project'):
                frontend.execute(self.project, 'watch', ['dev', 'up', '--watch'],
                                 frontend=selected, expected=digest(selected.read_bytes()))
        run.assert_not_called(); source.assert_not_called()

    def test_selected_executable_is_held_immutable_or_changed_dispatch_remains_uncertain(self):
        selected = self.root / 'selected-frontend'
        selected.write_bytes(b'original reviewed executable')
        protocol = b'{"schemaVersion":"latent.dev.result.v1","code":"success"}\n'
        rejected = []
        def changed(*args, **kwargs):
            try:
                selected.write_bytes(b'different executable after original dispatch')
            except PermissionError:
                rejected.append(True)  # Windows holds a non-write-sharing file handle.
            return subprocess.CompletedProcess(args[0], 0, protocol, b'')
        with patch.object(frontend, 'run_bounded_result', side_effect=changed) as run:
            outcome = frontend.execute(self.project, 'watch', ['dev', 'up', '--watch'],
                frontend=selected, expected=digest(b'original reviewed executable'))
        self.assertEqual(run.call_count, 1)
        if rejected:
            self.assertEqual(outcome.exit_code, 0)
            self.assertEqual(selected.read_bytes(), b'original reviewed executable')
        else:
            self.assertEqual(outcome.exit_code, 5)
            self.assertEqual(outcome.evidence['originalFrontendExitCode'], 0)
            self.assertIn('mutated', outcome.evidence['reason'])
        self.assertFalse(outcome.evidence['automaticReplay'])

    def test_already_imported_foreign_controller_module_cannot_be_a_source_fallback(self):
        foreign = ModuleType('tools.unowned_frontend_module')
        foreign.__file__ = str(self.root / 'foreign-controller.py')
        with patch.dict(sys.modules, {'tools.unowned_frontend_module': foreign}), patch.object(cli, 'main') as source:
            with self.assertRaisesRegex(DevError, 'outside-owned-tree'):
                frontend.execute(self.project, 'test', ['dev', 'test'])
        source.assert_not_called()

    def test_replaced_frontend_path_is_blocked_or_keeps_original_dispatch_uncertain(self):
        selected = self.root / 'selected-frontend'
        selected.write_bytes(b'original executable')
        protocol = b'{"schemaVersion":"latent.dev.result.v1","code":"success"}\n'
        rejected = []
        def replaced(*args, **kwargs):
            try:
                selected.rename(self.root / 'retained-original-frontend')
            except PermissionError:
                rejected.append(True)
            else:
                selected.write_bytes(b'original executable')  # Same bytes, different inode/owner.
            return subprocess.CompletedProcess(args[0], 0, protocol, b'')
        with patch.object(frontend, 'run_bounded_result', side_effect=replaced) as run:
            outcome = frontend.execute(self.project, 'test', ['dev', 'test'],
                frontend=selected, expected=digest(b'original executable'))
        self.assertEqual(run.call_count, 1)
        self.assertEqual(outcome.exit_code, 0 if rejected else 5)
        if not rejected:
            self.assertIn('mutated', outcome.evidence['reason'])
            self.assertFalse(outcome.evidence['remoteCleanupConfirmed'])
        self.assertFalse(outcome.evidence['automaticReplay'])

    def test_actual_standalone_exit_five_and_interruption_remain_original_uncertain_outcomes(self):
        for code in (5, 130):
            source = 'import json,sys;print(json.dumps({"schemaVersion":"latent.dev.result.v1","code":"original-operation-unknown","uncertain":True}));sys.exit(' + str(code) + ')'
            with self.subTest(code=code):
                outcome = self.standalone(source)
                self.assertEqual(outcome.exit_code, code)
                self.assertTrue(outcome.evidence['uncertain'])
                self.assertFalse(outcome.evidence['automaticReplay'])
                self.assertEqual(outcome.evidence['cleanup'], 'reaped')
                self.assertEqual(json.loads(outcome.stdout)['code'], 'original-operation-unknown')

    def test_actual_standalone_uses_selected_bytes_and_omits_ambient_production_credentials(self):
        source = 'import json,os;print(json.dumps({"schemaVersion":"latent.dev.result.v1","code":"success","credentialInherited":"LSF_PRIVATE_FRONTEND_TOKEN" in os.environ}))'
        with patch.dict(os.environ, {'LSF_PRIVATE_FRONTEND_TOKEN': 'private-not-for-child'}):
            outcome = self.standalone(source)
        self.assertEqual(outcome.exit_code, 0)
        self.assertFalse(json.loads(outcome.stdout)['credentialInherited'])
        self.assertEqual(outcome.evidence['frontendDigest'], self.identity)
        self.assertEqual(outcome.evidence['stdoutDigest'], digest(outcome.stdout))
        self.assertNotIn('private-not-for-child', json.dumps(outcome.evidence))
        output = io.StringIO()
        with redirect_stdout(output): frontend.emit(outcome)
        self.assertEqual(output.getvalue().encode(), outcome.stdout)

    def test_zero_exit_with_missing_malformed_or_false_protocol_is_uncertain(self):
        for source in ('pass', 'print("not-json")', 'print("[]")',
                       'print(\'{"schemaVersion":"latent.dev.result.v1","code":"failed"}\')'):
            with self.subTest(source=source):
                outcome = self.standalone(source)
                self.assertEqual(outcome.exit_code, 5)
                self.assertEqual(outcome.evidence['originalFrontendExitCode'], 0)
                self.assertIn('protocol-invalid', outcome.evidence['reason'])
                self.assertFalse(outcome.evidence['automaticReplay'])

    def test_original_bounded_frontend_deadline_preserves_one_effect_and_uncertain_status(self):
        effect = self.root / 'original-effect'
        source = 'from pathlib import Path;Path(' + repr(str(effect)) + ').write_bytes(b"one-original-operation")\nwhile True: pass\n'
        outcome = self.standalone(source, action='watch', timeout=1)
        self.assertEqual(outcome.exit_code, 5)
        self.assertEqual(outcome.evidence['cleanup'], 'reaped')
        self.assertFalse(outcome.evidence['remoteCleanupConfirmed'])
        self.assertFalse(outcome.evidence['automaticReplay'])
        self.assertEqual(effect.read_bytes(), b'one-original-operation')

    def test_all_six_staged_recipes_require_explicit_frontend_without_checkout_or_path_fallback(self):
        from tools.dev_tool_distribution import recipe
        script = '''import pathlib,sys
root=pathlib.Path(sys.argv[1]);sys.path.insert(0,str(root))
from tools.guest_authoring_frontend import execute
from tools.dev_workflow.common import DevError
try:execute(root.parent,'test',['dev','test'])
except DevError as error:
 assert error.code=='authoring-staged-recipe-requires-explicit-frontend',error.code
 print(error.code)
else:raise AssertionError('unowned source or PATH fallback executed')
'''
        for language in ('rust', 'c', 'go', 'typescript', 'java', 'dotnet'):
            with self.subTest(language=language):
                payload = self.root / language
                payload.mkdir()
                recipe(payload, language)
                staged = payload / 'recipe'
                result = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(staged)],
                    cwd=payload, stdin=subprocess.DEVNULL, capture_output=True, timeout=30, check=False)
                self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace')[:4096])
                self.assertEqual(result.stdout.strip(), b'authoring-staged-recipe-requires-explicit-frontend')
                self.assertEqual(result.stderr, b'')


if __name__ == '__main__':
    unittest.main()
