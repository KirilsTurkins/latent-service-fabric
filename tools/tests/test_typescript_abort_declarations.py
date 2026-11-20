"""Strict selected AbortSignal declarations; no engine or signed-runtime claim."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_typescript_network_boundary import pinned_frontend, require_complete_controls

ROOT = Path(__file__).resolve().parents[2]
DECLARATION = ROOT / 'sdk/typescript-guest/activation/runtime-globals.d.ts'
PROBE = ROOT / 'sdk/typescript-guest/probes/fetch-runtime/main.ts'


class TypeScriptAbortDeclarations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        selected = os.environ.get('LSF_TYPESCRIPT_FRONTEND')
        if not selected:
            raise unittest.SkipTest('explicit pinned frontend required; the owning gate refuses skips')
        tools, node, _versions = pinned_frontend(Path(selected))
        cls.compiler = [node, str(tools / 'node_modules/typescript/bin/tsc')]

    def compile(self, source, *, declaration=None):
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
            return subprocess.run([*self.compiler, '--project', str(root / 'tsconfig.json')],
                capture_output=True, text=True, timeout=30)

    def test_string_events_keep_existing_abort_and_listener_types(self):
        result = self.compile('''const controller = new AbortController();
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

    def test_actual_fanout_helpers_compile_and_old_declarations_fail(self):
        source = PROBE.read_text(encoding='utf-8')
        # Compile the unchanged graph, ordinary fan-out and refusal functions,
        # not a handwritten version of the failing calls. No contract mock is
        # needed: these functions have no WIT imports or export wrapper.
        start = source.index('function abortFanoutGraph()')
        end = source.index('function reentrantDefaultAbortFanout()', start)
        source = source[start:end]
        self.assertIn("filler.addEventListener('fanout-fill', listener)", source)
        self.assertIn("filler.removeEventListener('fanout-fill', listener)", source)
        result = self.compile(source)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        old = DECLARATION.read_bytes()
        for method in (b'addEventListener', b'removeEventListener'):
            before = method + b'(type: string,'
            self.assertIn(before, old)
            old = old.replace(before, method + b"(type: 'abort',")
        rejected = self.compile(source, declaration=old)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn('TS2345', rejected.stdout + rejected.stderr)
        self.assertIn('fanout-fill', rejected.stdout + rejected.stderr)

    def test_invalid_arguments_and_ambient_browser_apis_still_fail(self):
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
            with self.subTest(source=source):
                result = self.compile('const signal = new AbortController().signal;\n' + source)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(diagnostic, result.stdout + result.stderr)


def main():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TypeScriptAbortDeclarations)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    require_complete_controls(result)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
