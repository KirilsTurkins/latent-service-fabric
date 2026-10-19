"""Actual type encoding preserves closed implementation bytes and synchronous callers."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest

from tools.dotnet_guest import closed_io, internal_io
from tools.rust_capsule_project import ROOT


@unittest.skipUnless(shutil.which('wasm-tools'), 'pinned wasm-tools is required for real component encoding')
class ClosedIO(unittest.TestCase):
    def setUp(self):
        self.owned = tempfile.TemporaryDirectory()
        self.addCleanup(self.owned.cleanup)
        self.directory = Path(self.owned.name)
        self.wasm = shutil.which('wasm-tools')
        version = subprocess.check_output([self.wasm, '--version'], timeout=10).decode().strip()
        self.assertEqual(version, 'wasm-tools 1.254.0')

    def run_tool(self, stage, executable, *arguments):
        return subprocess.run([str(executable), *map(str, arguments)], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=True, timeout=15).stdout

    def adapter(self, profile='closed-logging'):
        source = ROOT/'sdk/dotnet-guest/runtime/wit'
        core, adapter = self.directory/'core.wasm', self.directory/'adapter.wasm'
        self.run_tool('embed', self.wasm, 'component', 'embed', source, '--world', profile,
                      '--dummy', '-o', core)
        self.run_tool('component', self.wasm, 'component', 'new', core, '-o', adapter)
        original = adapter.read_bytes()
        graph = json.loads(self.run_tool('wit', self.wasm, 'component', 'wit', adapter, '--json'))
        reference = copy.deepcopy(graph)
        return adapter, original, graph, reference

    def test_actual_closed_graph_changes_only_four_async_kinds_and_preserves_every_core_byte(self):
        for profile in ('closed', 'closed-logging'):
            with self.subTest(profile=profile):
                adapter, original, graph, reference = self.adapter(profile)
                evidence = self.directory/profile
                evidence.mkdir()
                compiler = SimpleNamespace(wasm=self.wasm, run=self.run_tool,
                    commands=SimpleNamespace(output=evidence, deadline=time.monotonic()+90))
                selected, record = closed_io.prepare(compiler, adapter, evidence/'selected', profile)
                actual = json.loads(self.run_tool('final', self.wasm, 'component', 'wit', selected, '--json'))
                self.assertEqual(actual, closed_io.projected_graph(graph, reference, profile))
                self.assertEqual(internal_io.core_modules(original), internal_io.core_modules(selected.read_bytes()))
                self.assertEqual(adapter.read_bytes(), original)
                self.assertTrue(record['coreBytesUnchanged'])
                self.assertTrue(record['applicationImportsUnchanged'])
                self.assertNotEqual(record['originalDigest'], record['selectedDigest'])
                self.assertEqual(sum(map(len, record['functions'].values())), 4)
                self.assertEqual(record['signedExecution'], 'not-run')

    def test_closed_async_type_preimage_and_public_signature_changes_fail_closed(self):
        _adapter, _raw, graph, reference = self.adapter()
        for kind in ('synchronous-preimage', 'parameter-width', 'extra-function'):
            with self.subTest(kind=kind):
                changed = copy.deepcopy(graph)
                functions = internal_io.functions(changed, 'exports')['wasi:io/streams@0.2.6']
                function = functions['[method]output-stream.blocking-flush']
                if kind == 'synchronous-preimage':
                    function['kind'] = {'method': function['kind']['async-method']}
                elif kind == 'parameter-width':
                    function['params'].append({'name': 'unexpected', 'type': 'u64'})
                else:
                    functions['foreign'] = copy.deepcopy(function)
                with self.assertRaisesRegex(ValueError, 'original-function'):
                    closed_io.projected_graph(changed, reference, 'closed-logging')

    def test_nonclosed_profiles_refuse_before_inspection_or_component_rewrite(self):
        for profile in ('runtime', 'runtime-logging', 'http', 'http-logging', 'unknown', None):
            with self.subTest(profile=profile), self.assertRaisesRegex(ValueError, 'closed-io-profile'):
                closed_io.prepare(None, self.directory/'absent', self.directory/'untouched', profile)
            self.assertFalse((self.directory/'untouched').exists())

    def test_unknown_unreferenced_and_shared_foreign_async_types_are_refused(self):
        for text in (
            '(component (type $t (func async)) (func $foreign (type $t) (canon lift (core func 0))))',
            '(component (type $t (func async)))',
            '(component (type $t (func async)) (func $poll (type $t)) (func $foreign (type $t)))'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'unknown-async-type-use'):
                closed_io.selected_text(text)

    def test_metadata_rewrite_preserves_canonical_options_and_unselected_spans(self):
        rows = []
        for i, name in enumerate(sorted(closed_io.NAMES)):
            rows.append(f'(type $t{i} (func async (param "x" u32)))\n'
                f'(func ${json.dumps(name)} (type $t{i}) (canon lift (core func {i}) (memory 0)))')
        original = '(component\n;; untouched metadata\n'+'\n'.join(rows)+'\n)'
        selected = closed_io.selected_text(original)
        self.assertEqual(selected, original.replace('(func async', '(func'))
        self.assertIn(';; untouched metadata', selected)
        self.assertEqual(selected.count('(canon lift'), 4)


if __name__ == '__main__':
    unittest.main()
