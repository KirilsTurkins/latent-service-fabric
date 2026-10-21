"""Authenticated installed profile inputs and exact source-world selection."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import dev_rust_http_runtime as runtime, dev_tool_distribution as distribution
from tools.rust_capsule_project import read_file
from tools.dev_workflow import tool_inventory
from tools.dev_workflow.common import HOST_ABI
from tools.rust_wasi_http_inputs import consumer_files, source_files


def graph(imports):
    return {'packages': [{'name': 'other:package@1.0.0'}, {'name': 'outside:client@2.0.0'},
        *({'name': name.split('/')[0] + '@' + name.split('@')[1]} for name in imports)],
        'interfaces': [{'name': name.split('/')[1].split('@')[0], 'package': i + 2}
            for i, name in enumerate(imports)], 'worlds': [
            {'name': 'service', 'package': 0, 'imports': {}},
            {'name': 'service', 'package': 1, 'imports': {
                str(i): {'interface': {'id': i}} for i in range(len(imports))}}]}


class InstalledRustHttpRuntime(unittest.TestCase):
    def setUp(self):
        owned = tempfile.TemporaryDirectory()
        self.addCleanup(owned.cleanup)
        self.root = Path(owned.name)
        self.payload = self.root / 'installed'
        (self.payload / 'sdk').mkdir(parents=True)
        self.source = self.root / 'prepared'
        self.source.mkdir()
        for name in runtime.MEMBERS:
            p = self.source / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(('original:' + name).encode())
        (self.source / 'private-signing-key').write_bytes(b'never staged')
        self.project = self.root / 'outside-app'
        (self.project / 'wit').mkdir(parents=True)
        (self.project / 'wit/world.wit').write_bytes(b'original whole WIT')
        (self.project / 'capsule-project.json').write_text(
            json.dumps({'world': 'outside:client/service@2.0.0'}), encoding='utf-8')

    def prepared(self, directory, rustc, wasm_tools):
        self.assertEqual(rustc, self.payload / 'sdk/rust/bin/rustc')
        self.assertEqual(wasm_tools, self.payload / 'sdk/bin/wasm-tools')
        return SimpleNamespace(path=directory, check=lambda: None,
            material=lambda: read_file(directory / 'INSTALL-COMPLETE.json'))

    def test_only_seven_public_inputs_are_copied_with_original_receipts_and_staged_tool_checks(self):
        with patch.object(runtime, 'Prepared', side_effect=self.prepared) as prepared:
            executables = runtime.prepare(self.payload, self.source)
        retained = self.payload / runtime.DIRECTORY
        self.assertEqual({p.relative_to(retained).as_posix() for p in retained.rglob('*') if p.is_file()},
            set(runtime.MEMBERS))
        self.assertEqual(executables, {'sdk/rust-http-runtime/component-composer/wac'})
        self.assertEqual(prepared.call_count, 2)
        for name in runtime.MEMBERS:
            self.assertEqual(read_file(retained / name), read_file(self.source / name))

    def test_prepared_tool_or_source_refusal_happens_before_any_copy(self):
        with patch.object(runtime, 'Prepared', side_effect=ValueError('prepared-tool-drift:rustc')):
            with self.assertRaisesRegex(ValueError, 'prepared-tool-drift'):
                runtime.prepare(self.payload, self.source)
        self.assertFalse((self.payload / runtime.DIRECTORY).exists())

    def test_changed_original_receipt_cannot_publish_the_prepared_copy(self):
        count = [0]
        def prepared(directory, rustc, wasm_tools):
            result = self.prepared(directory, rustc, wasm_tools)
            if directory == self.source:
                def recheck():
                    count[0] += 1
                    if count[0] == 2:
                        (directory / 'INSTALL-COMPLETE.json').write_bytes(b'changed')
                result.check = recheck
            return result
        with patch.object(runtime, 'Prepared', side_effect=prepared):
            with self.assertRaisesRegex(ValueError, 'inputs-changed'):
                runtime.prepare(self.payload, self.source)

    def test_selected_recipe_contains_the_exact_consumer_closure_without_checkout_imports(self):
        distribution.recipe(self.payload, 'rust', rust_http_runtime=True)
        for name, raw in consumer_files().items():
            self.assertEqual(read_file(self.payload / 'recipe' / name), raw)
        command = [sys.executable, '-I', '-B', '-c',
            'import sys;sys.path.insert(0,sys.argv[1]);'
            'from tools.rust_wasi_http_inputs import source_files,consumer_files;'
            'assert len(source_files())==110 and len(consumer_files())==113',
            str(self.payload / 'recipe')]
        result = subprocess.run(command, cwd=self.root, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_default_and_other_language_recipes_do_not_acquire_the_runtime(self):
        distribution.recipe(self.payload, 'rust')
        self.assertFalse((self.payload / 'recipe/tools/dev_rust_http_runtime.py').exists())
        self.assertFalse((self.payload / 'recipe/sdk/wasi-http-runtime').exists())
        for language in ('c', 'java', 'dotnet', 'go', 'typescript'):
            with self.subTest(language=language), self.assertRaisesRegex(Exception, 'requires-rust-builder'):
                distribution.recipe(self.root / language, language, rust_http_runtime=True)
            self.assertFalse((self.root / language).exists())

    def test_world_selection_uses_the_exact_package_version_and_explicit_world(self):
        value = graph(sorted(runtime.profile.AUTHORITY))
        self.assertEqual(set(runtime.declared_world(value, 'outside:client/service@2.0.0')),
            runtime.profile.AUTHORITY)
        self.assertEqual(runtime.declared_world(value, 'other:package/service@1.0.0'), [])
        for world in ('service', 'outside:client/service@1.0.0', 'outside:client/absent@2.0.0'):
            with self.subTest(world=world), self.assertRaisesRegex(ValueError, 'world'):
                runtime.declared_world(value, world)
        duplicate = copy.deepcopy(value)
        duplicate['worlds'].append(duplicate['worlds'][1])
        with self.assertRaisesRegex(ValueError, 'exact-selected-world'):
            runtime.declared_world(duplicate, 'outside:client/service@2.0.0')

    def test_complete_declarations_select_and_partial_declarations_preserve_normal_builder_refusals(self):
        (self.payload / runtime.DIRECTORY).mkdir()
        for imports in ([], sorted(runtime.profile.AUTHORITY)[:2], sorted(runtime.profile.AUTHORITY)):
            value = graph(imports)
            with self.subTest(imports=imports), patch.object(runtime, 'Prepared', side_effect=self.prepared), \
                    patch.object(runtime, 'run_bounded', return_value=SimpleNamespace(
                        returncode=0, stdout=json.dumps(value).encode())) as reader:
                selected = runtime.compiler_options(self.payload, self.project, lambda: None)
            expected = {'http_runtime': self.payload / runtime.DIRECTORY} if len(imports) == 3 else {}
            self.assertEqual(selected, expected)
            self.assertEqual(reader.call_args.args[0], [str(self.payload / 'sdk/bin/wasm-tools'),
                'component', 'wit', str(self.project / 'wit'), '--json'])
            self.assertEqual(reader.call_args.kwargs['timeout_seconds'], 30)
            self.assertEqual(reader.call_args.kwargs['max_output_bytes'], 16 * 1024 * 1024)

    def test_source_change_during_the_reader_is_refused_without_selecting_an_adapter(self):
        (self.payload / runtime.DIRECTORY).mkdir()
        def changed(*args, **kwargs):
            (self.project / 'wit/world.wit').write_bytes(b'changed')
            return SimpleNamespace(returncode=0, stdout=json.dumps(graph(sorted(runtime.profile.AUTHORITY))).encode())
        with patch.object(runtime, 'Prepared', side_effect=self.prepared), \
                patch.object(runtime, 'run_bounded', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'source-changed-during-selection'):
                runtime.compiler_options(self.payload, self.project, lambda: None)

    def test_complete_tool_inventory_binds_the_runtime_and_every_selected_recipe_file(self):
        with patch.object(runtime, 'Prepared', side_effect=self.prepared):
            runtime.prepare(self.payload, self.source)
        distribution.recipe(self.payload, 'rust', rust_http_runtime=True)
        value = distribution.compiler_inventory(self.payload, 'a' * 40, 'rust')
        rows = {row['path'] for row in value['files']}
        self.assertTrue({runtime.DIRECTORY + '/' + name for name in runtime.MEMBERS} <= rows)
        self.assertTrue({'recipe/' + name for name in consumer_files()} <= rows)
        descriptor = {'language': 'rust', 'hostAbi': HOST_ABI,
            'template': {'ownerIssue': 544, 'revision': 'a' * 40},
            'build': {'inventory': {'path': 'guest-tools.json',
                'sha256': distribution.file_digest(self.payload / 'guest-tools.json')[0]}, 'tools': []}}
        self.assertEqual(tool_inventory.check(self.payload, descriptor, 'linux-x86_64'), value['identity'])
        (self.payload / runtime.DIRECTORY / 'raw-runtime.wasm').write_bytes(b'changed')
        with self.assertRaisesRegex(Exception, 'guest-tool-companion-modified'):
            tool_inventory.check(self.payload, descriptor, 'linux-x86_64')


if __name__ == '__main__':
    unittest.main()
