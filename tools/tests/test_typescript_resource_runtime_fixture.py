"""Native reference/source controls; these are not signed component evidence."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools import typescript_resource_runtime_fixture as fixture
from tools.rust_capsule_project import snapshot
from tools.typescript_guest.project import validate

LOADER = '''import {registerHooks} from 'node:module';
import {readFileSync} from 'node:fs';
registerHooks({load(url, context, next) {
  if (url.startsWith('file:') && (url.endsWith('.txt') || url.endsWith('.bin'))) {
    const raw = readFileSync(new URL(url));
    const value = url.endsWith('.txt') ? JSON.stringify(raw.toString('utf8')) : 'Uint8Array.from(' + JSON.stringify([...raw]) + ')';
    return {format: 'module', shortCircuit: true, source: 'export default ' + value + ';'};
  }
  return next(url, context);
}});
'''


class ResourceRuntimeFixture(unittest.TestCase):
    def test_project_keeps_sdk_and_explicit_runtime_log_authority_with_transitive_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app, proof = fixture.project(root/'project', root/'outside')
            descriptor, sdk, _tools = validate(snapshot(app))
            self.assertEqual(descriptor['runtimeProfile'], fixture.IMPORT_PROFILE)
            self.assertEqual(descriptor['world'], 'examples:resource-runtime/service@1.0.0')
            self.assertEqual(descriptor['limits']['logBytes'], 16384)
            self.assertNotIn('grants', descriptor)
            self.assertEqual((app/'wit/world.wit').read_bytes(), fixture.WORLD)
            self.assertEqual((app/'src/main.ts').read_bytes(), fixture.MAIN)
            self.assertEqual(proof['sdkLock'], fixture.digest((app/'sdk-lock.json').read_bytes()))
            self.assertEqual(sdk['template']['witDigest'], fixture.digest(fixture.WORLD))
            library = json.loads((root/'outside/library/package.json').read_bytes())
            self.assertEqual(library['dependencies'], {fixture.PACKAGES[1]: 'file:'+str((root/'outside/data').resolve())})
            self.assertEqual((root/'outside/library/index.mjs').read_bytes(), fixture.LIBRARY)
            self.assertEqual((root/'outside/data/index.mjs').read_bytes(), fixture.RESOURCE)
            for name, raw in fixture.DATA.items():self.assertEqual((root/'outside/data'/name).read_bytes(), raw)
            self.assertFalse(proof['nativeThreadsQualified'])
            self.assertFalse(proof['pendingFlushQualified'])
            self.assertEqual(proof['signedExecution'], 'pending')

    def test_reject_foreign_outside_source_before_creating_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);other = root/'other';other.mkdir()
            with self.assertRaisesRegex(RuntimeError, 'independent-outside-project'):
                fixture.project(root/'project', other/'outside')
            self.assertFalse((root/'project').exists())

    @unittest.skipUnless(shutil.which('node'), 'native Node reference is unavailable')
    def test_unchanged_library_reference_has_real_callbacks_independent_copies_and_stale_state_refusal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            modules = root/'node_modules';modules.mkdir()
            library, data = (modules/name for name in fixture.PACKAGES)
            for directory in (library, data):
                directory.mkdir()
                (directory/'package.json').write_bytes(b'{"type":"module","exports":"./index.mjs"}\n')
            (library/'index.mjs').write_bytes(fixture.LIBRARY)
            (data/'index.mjs').write_bytes(fixture.RESOURCE)
            for name, raw in fixture.DATA.items():(data/name).write_bytes(raw)
            loader = root/'reference-loader.mjs';loader.write_bytes(LOADER.encode())
            entry = root/'reference.mjs'
            for mode, expected in fixture.EXPECTED.items():
                with self.subTest(mode=mode):
                    source = "import {resourceRuntime} from 'outside-resource-runtime-library';\n"
                    source += 'const value = await resourceRuntime('+json.dumps(mode)+');\n'
                    source += "console.log('RESULT ' + JSON.stringify(value));\n"
                    source += "try { await resourceRuntime('fresh'); throw new Error('stale-call-accepted'); }\n"
                    source += "catch (error) { if (error.message !== 'resource-runtime-state-survived-retirement') throw error; }\n"
                    entry.write_bytes(source.encode())
                    result = subprocess.run([shutil.which('node'), '--import', loader.as_uri(), str(entry)],
                                            cwd=root, capture_output=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8'))
                    lines = result.stdout.decode().splitlines()
                    self.assertEqual(json.loads(lines[-1].removeprefix('RESULT ')), expected)
                    self.assertEqual(lines[:-1], ['resource-callback:first', 'resource-callback:second']
                                     if mode == 'parallel' else ['resource-fresh:ordinary'])
                    self.assertEqual(result.stderr, b'')


if __name__ == '__main__':unittest.main()
