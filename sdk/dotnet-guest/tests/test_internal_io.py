"""Finite metadata/source controls; not NativeAOT application execution."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.dotnet_guest import internal_io as port


class InternalIoTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((Path(__file__).parent/'fixtures/internal-io.json').read_text())

    def test_complete_graph_changes_only_four_matched_internal_function_kinds(self):
        original = self.fixture['original']
        before = copy.deepcopy(original)
        expected, selected = port.projection(original, self.fixture['adapter'])
        self.assertEqual(original, before)
        self.assertEqual(sum(map(len, selected.values())), 4)
        for rows in port.functions(expected, 'imports').values():
            for function in rows.values():
                kind = function['kind']
                if kind == 'async-freestanding': function['kind'] = 'freestanding'
                elif isinstance(kind, dict) and set(kind) == {'async-method'}:
                    function['kind'] = {'method': kind['async-method']}
        self.assertEqual(expected, original)

    def test_changed_parameter_or_unpaired_adapter_kind_is_rejected_before_encoding(self):
        for change in ('params', 'kind'):
            with self.subTest(change=change):
                adapter = copy.deepcopy(self.fixture['adapter'])
                function = port.functions(adapter, 'exports')['wasi:io/poll@0.2.6']['poll']
                function[change] = [] if change == 'params' else 'freestanding'
                with self.assertRaisesRegex(ValueError, 'function-shape|adapter-type-must-match'):
                    port.projection(self.fixture['original'], adapter)

    def test_already_async_native_preimage_and_missing_supplier_fail_closed(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                original, adapter = copy.deepcopy(self.fixture['original']), copy.deepcopy(self.fixture['adapter'])
                if missing:
                    del port.functions(adapter, 'exports')['wasi:io/poll@0.2.6']['poll']
                else:
                    port.functions(original, 'imports')['wasi:io/poll@0.2.6']['poll']['kind'] = 'async-freestanding'
                with self.assertRaises(ValueError): port.projection(original, adapter)

    def test_type_clone_retains_sync_read_and_original_type_while_blocking_read_is_async(self):
        normalized = port.named_export_syntax(self.fixture['wat'])
        _, selected = port.projection(self.fixture['original'], self.fixture['adapter'])
        adapted = port.adapted_text(normalized, selected)
        self.assertEqual(adapted.count('(func async'), 4)
        self.assertEqual(adapted.count('(type $lsf-private-async-io-'), 8)
        # The cloned function bodies are added; no original type declaration is removed.
        original_types = []
        read_exports = []
        def collect(node):
            if node.head('type') and len(node.items) >= 3: original_types.append(normalized[node.start:node.end])
            if node.head('export') and '"[method]input-stream.read"' in node.items:
                read_exports.append(normalized[node.start:node.end])
            for child in node.items:
                if isinstance(child, port.Node): collect(child)
        collect(port.tree(normalized))
        for text in original_types:
            if '(instance' not in text and text.startswith('(type $#type'):
                self.assertIn(text, adapted)
        self.assertEqual(len(read_exports), 2)
        for text in read_exports: self.assertIn(text, adapted)

    def test_rebundle_retains_all_original_core_payloads_and_consumes_every_import_once(self):
        modules = {name: bytes.fromhex(value) for name, value in self.fixture['modules'].items()}
        binary = bytes.fromhex(self.fixture['unbundled'])
        selected = port.rebundle(binary, modules)
        self.assertEqual(sorted(port.core_modules(selected)), sorted(modules.values()))
        with self.assertRaisesRegex(ValueError, 'unconsumed-core-module'):
            port.rebundle(binary, dict(modules, unused=b'\0asm\x01\0\0\0'))
        first = next(iter(modules))
        changed = binary.replace(first.encode(), b'x'*len(first), 1)
        with self.assertRaisesRegex(ValueError, 'unconsumed-core-module|unbundle-import-type'):
            port.rebundle(changed, modules)

    def test_malformed_metadata_and_binary_lengths_are_bounded_and_rejected(self):
        for text in ('(component', '(component (; comment)', '(component "unterminated)',
                     '(component '+'('*130+'x'+')'*130+')'):
            with self.subTest(text=text[:20]), self.assertRaises(ValueError): port.tree(text)
        for raw in (b'', b'\0asm\x0d\0\x01\0\x01\x80', b'\0asm\x0d\0\x01\0\x01\x7f'):
            with self.subTest(raw=raw), self.assertRaises(ValueError): port.core_modules(raw)

    def test_real_component_export_alias_is_preserved_while_type_export_identifier_is_repaired(self):
        original = ('(component (type $api (instance (export $owned "owned" (type (sub resource))))) '
            '(import "api" (instance $original (type $api))) '
            '(export $api-export "api" (instance $original)))')
        selected = port.named_export_syntax(original)
        self.assertIn('(export "owned" (type $owned (sub resource)))', selected)
        self.assertIn('(export $api-export "api" (instance $original))', selected)


if __name__ == '__main__': unittest.main()
