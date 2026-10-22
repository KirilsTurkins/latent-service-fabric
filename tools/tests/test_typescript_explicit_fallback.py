"""Source/reader controls; these models do not qualify an actual component."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.phase2_operator_process import WorkflowError
from tools import typescript_explicit_fallback_fixture as fixture
from tools import typescript_explicit_fallback_node as node
from tools.rust_capsule_project import ROOT


def result(seed=7, alternate=42, *, trap=False):
    return {'processReaped': True, 'exitCode': 4 if trap else 0,
        'decoded': None if trap else fixture.expected(seed, alternate),
        'response': {'schemaVersion': 'latent.cli.result.v1', 'command': 'invoke',
            'outcomeKnown': True, 'requestDispatched': True,
            'category': 'platform-failure' if trap else 'success',
            'error': {'code': 'guest-trap'} if trap else None,
            'data': {'terminalState': 'guest_trap'} if trap else {}}}


class TypeScriptExplicitFallback(unittest.TestCase):
    def test_success_requires_exact_alternate_native_marker_and_fresh_state(self):
        for seed, alternate in ((7, 42), (11, 62), (19, 102)):
            row = result(seed, alternate)
            self.assertEqual(node.outcome('typescript', row, seed, alternate)['alternate'], alternate)
            for bad in (result(0, 7), {**row, 'processReaped': False}, {**row, 'exitCode': 4},
                    {**row, 'decoded': [{'ok': 'fallback|typescript|unexpected-success'}]}):
                with self.assertRaises(WorkflowError): node.outcome('typescript', bad, seed, alternate)
        with self.assertRaises(WorkflowError): fixture.expected(True, 12)

    def test_uncaught_error_is_terminal_and_never_timeout_or_cancellation(self):
        self.assertFalse(node.outcome('typescript', result(trap=True), 13, None)['preciseInstructionCauseProved'])
        for section, field, wrong in ((None, 'processReaped', False), ('response', 'requestDispatched', False),
                ('response', 'outcomeKnown', False), ('error', 'code', 'deadline-exceeded'),
                ('data', 'terminalState', 'cancelled')):
            changed = result(trap=True)
            target = changed if section is None else changed['response'] if section == 'response' else changed['response'][section]
            target[field] = wrong
            with self.assertRaises(WorkflowError): node.outcome('typescript', changed, 13, None)

    def test_transitive_default_constructor_and_callback_preserve_the_native_refusal(self):
        self.assertIn("from 'outside-fallback-callback'", fixture.LIBRARY)
        self.assertIn('const clock = new DefaultClock()', fixture.LIBRARY)
        self.assertIn('read() { return Date.now(); }', fixture.CALLBACK)
        self.assertIn('alternate(seed) { return seed * 5 + 7; }', fixture.CALLBACK)
        self.assertLess(fixture.LIBRARY.index('error.message !=='), fixture.LIBRARY.index('const alternate ='))
        self.assertEqual(fixture.CASES, (('catch', 7, 42), ('catch', 11, 62), ('uncaught', 13, None), ('catch', 19, 102)))

    def test_actual_application_clock_guard_and_library_control_flow_in_native_reference(self):
        executable = shutil.which('node')
        if executable is None: self.skipTest('Node is required for the separately labelled native reference')
        with tempfile.TemporaryDirectory(prefix='lsf-ts-fallback-reference-') as temporary:
            directory = Path(temporary)
            (directory / 'callback.mjs').write_text(fixture.CALLBACK, encoding='utf-8')
            selected = fixture.LIBRARY.replace("'outside-fallback-callback'", "'./callback.mjs'")
            (directory / 'library.mjs').write_text(selected, encoding='utf-8')
            guard = (ROOT / 'tools/typescript_guest/clock_app.mjs').as_uri()
            script = '''import assert from 'node:assert/strict';
import {installApplicationClocks} from GUARD;
installApplicationClocks(false, () => false);
const url = new URL('./library.mjs', import.meta.url);
for (const [index, [mode, seed, alternate]] of CASES.entries()) {
  const {fallbackCase} = await import(url.href + '?fresh=' + index);
  if (alternate === null) assert.throws(() => fallbackCase(`${mode}:${seed}`), error => error instanceof Error && error.message === REFUSAL);
  else assert.equal(fallbackCase(`${mode}:${seed}`), `fallback|typescript|unsupported|seed=${seed}|alternate=${alternate}|fresh=1`);
}
'''.replace('GUARD', json.dumps(guard)).replace('CASES', json.dumps(fixture.CASES)).replace('REFUSAL', json.dumps(fixture.REFUSAL))
            (directory / 'reference.mjs').write_text(script, encoding='utf-8')
            completed = subprocess.run([executable, directory / 'reference.mjs'], capture_output=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors='replace'))

    def test_material_closure_is_finite_and_keeps_existing_helpers(self):
        from tools.qualify_typescript_explicit_fallback import MATERIALS, materials
        from tools.qualify_sdk_explicit_fallback import MATERIALS as shared
        self.assertTrue(set(shared) <= set(MATERIALS))
        self.assertEqual(len(MATERIALS), len(set(MATERIALS)))
        self.assertLessEqual(len(materials()), 256)


if __name__ == '__main__': unittest.main()
