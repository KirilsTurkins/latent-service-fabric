"""Tiny encoded MVP mechanisms, distinct from real ordinary Rust execution."""
from __future__ import annotations

from pathlib import Path
import json
import subprocess
import tempfile
import unittest

from tools import rust_thread_callback_paths as paths, rust_thread_object_graph as graph


def string(value):
    raw = value.encode()
    return paths.unsigned(len(raw)) + raw


def fixture(*, bypass=None):
    u, sec = paths.unsigned, paths.section
    types = sec(1, b'\x03\x60\x01\x7f\x01\x7f\x60\0\x01\x7f'
                   b'\x60\x02\x7f\x7f\x01\x7f')
    functions = sec(3, b'\x05\0\0\x01\x02\x01')
    table = sec(4, b'\x01\x70\x01\x03\x03')
    memory = sec(5, b'\x01\0\x01')
    exports = [(name, index) for name, index in (('owner', 2), ('ordinary', 3), ('source', 4))]
    if bypass == 'export':
        exports.append(('leak', 0))
    exported = sec(7, u(len(exports)) + b''.join(string(name) + b'\0' + u(index)
                                               for name, index in exports))
    elements = sec(9, b'\x01\0\x41\x01\x0b\x02\0' +
                   (b'\0' if bypass == 'table-alias' else b'\x01'))
    ordinary = b'\0\x20\0\x20\x01\x11\0\0\x0b'
    if bypass == 'direct':
        ordinary = b'\0\x20\0\x10\0\x0b'
    elif bypass == 'ref.func':
        ordinary = b'\0\xd2\0\x1a\x41\0\x0b'
    bodies = [b'\0\x20\0\x28\x02\0\x0b', b'\0\x20\0\x41\x01\x6a\x0b',
              b'\0\x41\x20\x41\x01\x11\0\0\x0b', ordinary,
              b'\0\x41\x20\x41\x02\x11\0\0\x0b']
    code = sec(10, u(len(bodies)) + b''.join(u(len(body)) + body for body in bodies))
    data = sec(11, b'\x02\0\x41\x20\x0b\x04\x37\0\0\0'
                   b'\0\x41\xc0\0\x0b\x04\x4d\0\0\0')
    core = b'\0asm\1\0\0\0' + types + functions + table + memory + exported + elements + code + data
    targets = (paths.Target(1, 0),)
    sites = (paths.Site(2, 5, 1), paths.Site(4, 5, 1, source_fallback=True))
    return core, targets, sites


class CallbackPaths(unittest.TestCase):
    def test_owner_and_source_fallback_execute_while_arbitrary_pointer_table_call_traps(self):
        original, targets, sites = fixture()
        derived, receipt = paths.seal_callback_paths(original, graph.digest(original), targets, sites)
        # This is an isolated MVP engine mechanism with no imports, signing,
        # runtime or upstream Rust. The original adversarial call reads77;
        # after isolation it traps while owner55 and genuine Source33 survive.
        script = r"""
const fs = require('fs');
const raw = fs.readFileSync(process.argv[1]);
const x = new WebAssembly.Instance(new WebAssembly.Module(raw)).exports;
let trapped = false;
try { x.ordinary(64,1); } catch (e) { if (!(e instanceof WebAssembly.RuntimeError)) throw e; trapped = true; }
console.log(JSON.stringify({owner:x.owner(), source:x.source(), ordinary:x.ordinary(64,2), trapped}));
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'control.wasm'
            results = []
            for raw in (original, derived):
                path.write_bytes(raw)
                process = subprocess.run(['node', '-e', script, str(path)],
                                         capture_output=True, text=True, timeout=5, check=True)
                results.append(json.loads(process.stdout))
        self.assertEqual(results, [
            {'owner': 55, 'source': 33, 'ordinary': 65, 'trapped': False},
            {'owner': 55, 'source': 33, 'ordinary': 65, 'trapped': True}])
        self.assertEqual(receipt['ordinaryTableMinimum'], 3)
        self.assertEqual(receipt['ordinaryTableMaximum'], 3)

    def test_original_direct_ref_export_or_aliased_table_bypass_refuses_before_transform(self):
        for bypass, reason in (('direct', 'private-direct-or-ref-bypass'),
                               ('ref.func', 'private-direct-or-ref-bypass'),
                               ('export', 'private-export-bypass'),
                               ('table-alias', 'unexpected-private-table-alias')):
            with self.subTest(bypass=bypass):
                core, targets, sites = fixture(bypass=bypass)
                with self.assertRaisesRegex(ValueError, reason):
                    paths.seal_callback_paths(core, graph.digest(core), targets, sites)


if __name__ == '__main__':
    unittest.main()
