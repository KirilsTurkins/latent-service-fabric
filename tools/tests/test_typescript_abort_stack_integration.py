"""Cross-branch probe routing; Node reference execution is not engine evidence."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from tools import qualify_typescript_fetch_runtime as fetch


class AbortStackIntegrationTests(unittest.TestCase):
    def test_probe_families_have_distinct_dispatch_modes_and_all_are_scheduled(self):
        families = (fetch.ABORT_FANOUT_VECTORS, fetch.COMBINATOR_VECTORS,
                    fetch.COMPLETED_CAPTURE_VECTORS)
        modes = [set(row[1] for row in family) for family in families]
        for index, selected in enumerate(modes):
            for other in modes[index + 1:]:
                self.assertFalse(selected & other, 'unrelated probes must not share a dispatch mode')
        source = (fetch.ROOT / fetch.FIXTURE / 'main.ts').read_text()
        dispatch = re.findall(r'if \(mode === (\d+)\)', source)
        self.assertEqual(len(dispatch), len(set(dispatch)), 'a later duplicate mode is unreachable')
        self.assertTrue(set.union(*modes) <= set(map(int, dispatch)))
        normal = {row[0] for row in fetch.execution_vectors(False)}
        diagnostic = {row[0] for row in fetch.execution_vectors(True)}
        self.assertTrue({row[0] for row in fetch.ABORT_FANOUT_VECTORS} <= normal)
        self.assertTrue({row[0] for row in fetch.COMBINATOR_VECTORS} <= normal)
        self.assertEqual({row[0] for row in fetch.COMPLETED_CAPTURE_VECTORS}, diagnostic)
        self.assertFalse(normal & diagnostic)

    def test_actual_guest_dispatch_keeps_combinator_and_abort_results_separate(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node is required for the dispatch reference control')
        selected = [fetch.COMBINATOR_VECTORS[0], fetch.ABORT_FANOUT_VECTORS[0]]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(fetch.ROOT / fetch.FIXTURE / 'main.ts', root / 'main.ts')
            (root / 'package.json').write_text('{"type":"module"}\n')
            (root / 'default-client.js').write_text(
                'export const initialized = true;\n'
                'export function request() { throw new Error("unexpected-network"); }\n'
                'export {request as requestReady, request as promiseReady, request as requestCopyReady};\n')
            script = ("import assert from 'node:assert/strict';\n"
                      "import {api} from './main.ts';\n"
                      f"for (const [name, mode, expected] of {json.dumps(selected)}) {{\n"
                      "  assert.equal(await api.run(mode, ''), expected, name);\n}\n")
            result = subprocess.run([node, '--experimental-strip-types', '--input-type=module', '-e', script],
                                    cwd=root, capture_output=True, timeout=15, check=False)
            self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[:65536])
            self.assertLessEqual(len(result.stdout) + len(result.stderr), 65536)


if __name__ == '__main__':
    unittest.main()
