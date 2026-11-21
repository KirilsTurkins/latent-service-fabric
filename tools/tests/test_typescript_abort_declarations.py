"""Strict selected AbortSignal declarations; no engine or signed-runtime claim."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.tests.test_typescript_network_boundary import pinned_frontend, require_complete_controls

ROOT = Path(__file__).resolve().parents[2]
DECLARATION = ROOT / 'sdk/typescript-guest/activation/runtime-globals.d.ts'
PROBE = ROOT / 'sdk/typescript-guest/probes/fetch-runtime/main.ts'


def fanout_helpers():
    # Compile the real unchanged graph, ordinary and refusal functions, rather
    # than a handwritten version of the failing calls. They need no WIT mock.
    source = PROBE.read_text(encoding='utf-8')
    start = source.index('function abortFanoutGraph()')
    end = source.index('function reentrantDefaultAbortFanout()', start)
    return source[start:end]


def compile_source(compiler, source, *, declaration=None):
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / 'main.ts').write_text(source, encoding='utf-8')
        (root / 'runtime.d.ts').write_bytes(
            DECLARATION.read_bytes() if declaration is None else declaration)
        # Match the normal compiler: no ambient DOM/Node declarations,
        # no skipLibCheck, no type assertions or expected-error suppression.
        config = {'compilerOptions': {'target': 'ES2022', 'module': 'ESNext',
            'moduleResolution': 'Bundler', 'strict': True, 'noEmit': True,
            'lib': ['ES2022'], 'types': []}, 'files': ['main.ts', 'runtime.d.ts']}
        (root / 'tsconfig.json').write_text(json.dumps(config), encoding='utf-8')
        return subprocess.run([*compiler, '--project', str(root / 'tsconfig.json')],
            capture_output=True, text=True, timeout=30)


def check_declarations(compiler):
    """Execute real compiler controls; only the pinned entry point calls this in CI."""
    self = unittest.TestCase()
    completed = []
    result = compile_source(compiler, '''const controller = new AbortController();
const signal = controller.signal;
declare const eventName: string;
const callback = (event: unknown): void => {};
signal.addEventListener('abort', callback, {once: true});
signal.addEventListener('fanout-fill', callback);
signal.addEventListener(eventName, callback, false);
signal.removeEventListener('abort', callback);
signal.removeEventListener('fanout-fill', callback);
signal.removeEventListener(eventName, callback);
signal.onabort = callback;
const aborted: boolean = signal.aborted;
signal.throwIfAborted();
AbortSignal.any([signal, AbortSignal.abort('reason'), AbortSignal.timeout(1)]);
''')
    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
    completed.append('string_events_keep_existing_abort_and_listener_types')

    source = fanout_helpers()
    self.assertIn("filler.addEventListener('fanout-fill', listener)", source)
    self.assertIn("filler.removeEventListener('fanout-fill', listener)", source)
    result = compile_source(compiler, source)
    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
    old = DECLARATION.read_bytes()
    for method in (b'addEventListener', b'removeEventListener'):
        before = method + b'(type: string,'
        self.assertIn(before, old)
        old = old.replace(before, method + b"(type: 'abort',")
    rejected = compile_source(compiler, source, declaration=old)
    self.assertNotEqual(rejected.returncode, 0)
    self.assertIn('TS2345', rejected.stdout + rejected.stderr)
    self.assertIn('fanout-fill', rejected.stdout + rejected.stderr)
    completed.append('actual_fanout_helpers_compile_and_old_declarations_fail')

    cases = (
        ("signal.addEventListener(42, () => {});", 'TS2345'),
        ("signal.removeEventListener(42, () => {});", 'TS2345'),
        ("signal.addEventListener('custom', 42);", 'TS2345'),
        ("signal.removeEventListener('custom', 42);", 'TS2345'),
        ("signal.addEventListener('custom', () => {}, {once: 'yes'});", 'TS2322'),
        ("signal.aborted = true;", 'TS2540'),
        ("document.createElement('div');", 'TS2584'),
    )
    for source, diagnostic in cases:
        result = compile_source(compiler, 'const signal = new AbortController().signal;\n' + source)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(diagnostic, result.stdout + result.stderr)
    completed.append('invalid_arguments_and_ambient_browser_apis_still_fail')

    return {'status': 'passed', 'scope': 'strict-declarations-only',
            'signedExecution': False, 'controls': completed}


def compiler_controls(frontend):
    tools, node, versions = pinned_frontend(frontend)
    result = check_declarations([node, str(tools / 'node_modules/typescript/bin/tsc')])
    return {**result, 'versions': versions}


class TypeScriptAbortDeclarations(unittest.TestCase):
    def test_runtime_declarations_keep_string_event_names_and_callback_types(self):
        source = DECLARATION.read_text(encoding='utf-8')
        for method in ('addEventListener', 'removeEventListener'):
            self.assertIn(method + '(type: string, listener: (event: any) => void', source)
        self.assertIn('options?: boolean | { once?: boolean }', source)
        self.assertIn('readonly aborted: boolean', source)
        self.assertNotIn('declare var document', source)

    def test_compiler_control_uses_the_actual_same_signal_fanout_helpers(self):
        source = fanout_helpers()
        self.assertIn('const filler = graph.source.signal;', source)
        self.assertIn("filler.addEventListener('fanout-fill', listener)", source)
        self.assertIn("filler.removeEventListener('fanout-fill', listener)", source)
        self.assertIn('function refusedAbortFanout()', source)
        self.assertNotIn('function reentrantDefaultAbortFanout()', source)

    def test_explicit_gate_requires_tools_and_never_treats_absence_as_success(self):
        environment = {key: value for key, value in os.environ.items()
                       if key != 'LSF_TYPESCRIPT_FRONTEND'}
        with patch.dict(os.environ, environment, clear=True), \
                patch(__name__ + '.compiler_controls', side_effect=AssertionError('unexpected compiler')):
            with self.assertRaisesRegex(ValueError, 'abort-declarations-pinned-frontend-required'):
                main()
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(subprocess, 'run', side_effect=AssertionError('unexpected process')):
            with self.assertRaises(FileNotFoundError):
                compiler_controls(Path(temporary) / 'absent')


def main():
    selected = os.environ.get('LSF_TYPESCRIPT_FRONTEND')
    if not selected:
        raise ValueError('abort-declarations-pinned-frontend-required')
    compiler = compiler_controls(Path(selected))
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TypeScriptAbortDeclarations)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    controls = require_complete_controls(result)
    print(json.dumps({**compiler, 'unitControls': controls}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
