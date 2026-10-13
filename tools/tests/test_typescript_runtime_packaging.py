"""Selected runtime WIT sources stay byte-bound without rewriting the original capture."""
import copy
import unittest

from tools.typescript_guest.build import runtime_package_sources
from tools.typescript_guest.runtime_profile import SELECTED_WORLD, scoped_selected_world, original_world_sources


class TypeScriptRuntimePackagingTests(unittest.TestCase):
    def selection(self):
        return {'world': SELECTED_WORLD, 'sources': [
            {'path': 'wit/world.wit', 'content': 'actual selected world'},
            {'path': 'wit/deps/application/package.wit', 'content': 'original public contract'},
        ]}

    def test_selected_lock_sources_replace_only_package_wit_and_keep_original_capture(self):
        original = {'wit/world.wit': b'original world', 'wit/obsolete.wit': b'old dependency',
                    'src/main.ts': b'unchanged application', 'vendor/lsf/Cargo.toml': b'original SDK'}
        before = copy.deepcopy(original)
        sources = runtime_package_sources(original, self.selection())
        self.assertEqual(original, before)
        self.assertEqual(sources, {'wit/world.wit': b'actual selected world',
            'wit/deps/application/package.wit': b'original public contract',
            'src/main.ts': b'unchanged application', 'vendor/lsf/Cargo.toml': b'original SDK'})

    def test_paths_duplicates_and_unknown_world_fail_before_package_materialization(self):
        for name in ('../world.wit', 'wit/../world.wit', 'wit//world.wit', 'wit/world.json',
                     'wit/C:/world.wit', 'wit/./world.wit', 'wit/deps\\world.wit'):
            value = self.selection()
            value['sources'][0]['path'] = name
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'source-path'):
                runtime_package_sources({}, value)
        value = self.selection()
        value['sources'].append(value['sources'][0])
        with self.assertRaisesRegex(ValueError, 'source-path'):
            runtime_package_sources({}, value)
        value['world'] = 'unknown'
        with self.assertRaisesRegex(ValueError, 'source-envelope'):
            runtime_package_sources({}, value)

    def test_source_bytes_and_envelopes_retain_existing_parser_limits(self):
        for content in ('', 'x' * (256 * 1024 + 1)):
            value = self.selection()
            value['sources'][0]['content'] = content
            with self.assertRaisesRegex(ValueError, 'source-limit'):
                runtime_package_sources({}, value)
        value = self.selection()
        value['sources'] *= 129
        with self.assertRaisesRegex(ValueError, 'source-envelope'):
            runtime_package_sources({}, value)
        value = self.selection()
        value['sources'][0]['authority'] = True
        with self.assertRaisesRegex(ValueError, 'source-entry'):
            runtime_package_sources({}, value)

    def test_selected_world_retains_original_tenant_namespace_without_changing_exports(self):
        self.assertEqual(scoped_selected_world('examples:app/service@2.3.4'),
                         'examples:lsf-typescript-activation/selected@1.0.0')
        self.assertEqual(scoped_selected_world('private-tenant:outside/capsule@1.0.0'),
                         'private-tenant:lsf-typescript-activation/selected@1.0.0')
        selected = scoped_selected_world('examples:app/service@2.3.4')
        value = self.selection()
        value['world'] = selected
        self.assertEqual(runtime_package_sources({}, value, selected_world=selected)['wit/world.wit'],
                         b'actual selected world')
        with self.assertRaisesRegex(ValueError, 'source-envelope'):
            runtime_package_sources({}, value)
        for original in ('not-a-world', 'examples:lsf-typescript-activation/selected@1.0.0'):
            with self.assertRaisesRegex(ValueError, 'world-identity'):
                scoped_selected_world(original)

    def test_runtime_receipt_verifies_explicit_source_selection_without_promoting_it(self):
        import tempfile
        from pathlib import Path
        from tools import guest_runtime_receipts as receipts
        from tools.dev_workflow.common import encode, digest
        from tools.rust_capsule_project import inventory
        from tools.typescript_guest.runtime_profile import IMPORT_PROFILE
        files = {'capsule-project.json': encode({'runtimeProfile': IMPORT_PROFILE}),
                 'vendor/lsf/sdk/typescript-guest/runtime/source': b'captured runtime',
                 'wit/world.wit': b'captured contract'}
        original = inventory(files)
        materials = [{'name': 'build-recipe', 'digest': digest(b'actual recipe'), 'size': 13}]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            receipts.emit(output, 'typescript', IMPORT_PROFILE, files, original, b'controlled component',
                          materials, graph=None, binding_digest=digest(b'actual bindings'),
                          configuration={'profile': IMPORT_PROFILE})
            value = receipts.read((output / 'standard-runtime-selection.json').read_bytes())
            verified = receipts.verify_build(value, 'typescript', files, original,
                                             b'controlled component', materials)
            self.assertEqual((verified['profile'], verified['qualification'], verified['apiSupport']),
                             (IMPORT_PROFILE, 'unknown', 'not-evaluated'))

    def test_original_foreign_packages_remain_separate_exact_lock_sources(self):
        derived = {'world.wit': b'derived world',
                   'deps/application/package.wit': b'nested canonical decoder printout',
                   'deps/activation/package.wit': b'original native runtime'}
        original = {'world.wit': b'original app', 'deps/invocation/package.wit': b'original host package'}
        self.assertEqual(original_world_sources(derived, original), {
            'world.wit': b'derived world', 'deps/application/world.wit': b'original app',
            'deps/invocation/package.wit': b'original host package',
            'deps/activation/package.wit': b'original native runtime'})
        self.assertEqual(derived['deps/application/package.wit'], b'nested canonical decoder printout')
        with self.assertRaisesRegex(ValueError, 'source-conflict'):
            original_world_sources(derived, {'deps/activation/package.wit': b'changed native runtime'})
