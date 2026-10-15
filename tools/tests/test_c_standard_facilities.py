"""Profile authority, derived contracts and retained original input identities."""
import json
from pathlib import Path
import tempfile
import unittest

from tools import c_capsule_project as project, guest_runtime_receipts as receipts
from tools.c_guest import standard_facilities as facilities
from tools.dev_workflow.common import DevError, digest
from tools.rust_capsule_project import ROOT, inventory


class StandardFacilities(unittest.TestCase):
    def setUp(self):
        owned = tempfile.TemporaryDirectory(); self.addCleanup(owned.cleanup)
        self.root = Path(owned.name)

    def test_profile_is_explicit_closed_and_part_of_original_source(self):
        root = project.create(self.root / 'project', 'greeting')
        files = project.snapshot(root)
        value, _, _ = project.validate(files)
        self.assertEqual(facilities.selected_profile(value), facilities.DEFAULT)
        for invalid in (None, True, [], 'ambient-wasi', ''):
            changed = dict(files)
            changed['capsule-project.json'] = json.dumps({**value, 'runtimeProfile': invalid}).encode()
            with self.subTest(profile=invalid), self.assertRaisesRegex(ValueError, 'unsupported-c-standard-runtime-profile'):
                project.validate(changed)
        changed = dict(files)
        changed['capsule-project.json'] = json.dumps({**value, 'runtimeProfile': facilities.PROFILE}).encode()
        selected, _, _ = project.validate(changed)
        self.assertEqual(facilities.selected_profile(selected), facilities.PROFILE)
        self.assertNotEqual(inventory(files), inventory(changed))
        changed['vendor/lsf/sdk/c-guest/src/standard-clock-entropy.c'] += b'\n'
        with self.assertRaisesRegex(ValueError, 'vendored SDK changed'):
            project.validate(changed)

    def test_derived_world_retains_originals_and_exact_typed_dependency_closure(self):
        root = project.create(self.root / 'project', 'greeting')
        source = root / 'wit'
        original = project.snapshot(source)
        destination = self.root / 'derived'
        facilities.stage(source, 'examples:greeting/service@1.0.0', destination, ROOT / 'wit/platform')
        self.assertEqual(project.snapshot(source), original)
        text = '\n'.join(path.read_text() for path in destination.glob('*.wit'))
        for name in facilities.IMPORTS:
            self.assertEqual(text.count('import ' + name + ';'), 1)
        self.assertEqual({path.name for path in (destination / 'deps').iterdir()}, {'clock', 'random'})
        self.assertIn('export api;', text)
        with self.assertRaisesRegex(ValueError, 'fresh-derived-wit'):
            facilities.stage(source, 'service', destination, ROOT / 'wit/platform')

    def test_ambiguous_world_and_explicit_profile_import_cannot_gain_duplicate_contracts(self):
        source = self.root / 'wit'; source.mkdir()
        path = source / 'app.wit'
        for text in ('package test:app; world other {}',
                     'package test:app; world service {} world service {}',
                     'package test:app; world service { import latent:clock/wall@0.1.0; }'):
            path.write_text(text)
            destination = self.root / 'derived'
            with self.subTest(text=text), self.assertRaises(ValueError):
                facilities.stage(source, 'service', destination, ROOT / 'wit/platform')
            self.assertFalse(destination.exists())

    def test_dependency_graph_must_select_same_runtime_as_captured_application(self):
        from tools.application_dependency_store import DependencyError
        from tools.c_dependency_authoring import manifest
        selected = {'runtimeProfile': facilities.PROFILE}
        self.assertEqual(facilities.selected_profile(selected, {'selection': selected}), facilities.PROFILE)
        for graph in ({'selection': {'runtimeProfile': facilities.DEFAULT}},
                      {'selection': {'runtimeProfile': 'unknown'}}):
            with self.subTest(graph=graph), self.assertRaisesRegex(ValueError, 'selection-mismatch'):
                facilities.selected_profile(selected, graph)
        declaration = {'formatVersion': 1, 'language': 'c', 'selection': selected,
                       'nativeLocks': [], 'artifacts': [], 'transformations': []}
        self.assertEqual(manifest(declaration)['selection'], selected)
        for invalid in (None, True, [], {}, 'unknown'):
            with self.subTest(profile=invalid), self.assertRaisesRegex(DependencyError, 'runtime-profile-not-installed'):
                manifest({**declaration, 'selection': {'runtimeProfile': invalid}})

    def test_derived_contracts_cannot_modify_captured_source_or_platform_inputs(self):
        root = project.create(self.root / 'project', 'greeting')
        before = project.snapshot(root)
        source, platform = root / 'wit', root / 'vendor/lsf/wit/platform'
        for destination in (source, source / 'derived', platform / 'derived', root):
            with self.subTest(destination=destination), self.assertRaisesRegex(ValueError, 'must-not-overlap'):
                facilities.stage(source, 'service', destination, platform)
            self.assertEqual(project.snapshot(root), before)

    def test_external_standard_library_probe_compiles_only_captured_closure_and_explicit_profile(self):
        from tools import application_dependencies as dependencies
        from tools.c_standard_facilities_probe import prepare
        from tools.c_application_dependencies import selected
        from tools.guest_runtime_profiles import profiles
        root = project.create(self.root / 'project', 'greeting')
        proof = prepare(root)
        self.assertTrue(proof['originalLibraryRemoved'])
        files = project.snapshot(root)
        value, _, _ = project.validate(files)
        self.assertEqual(value['runtimeProfile'], facilities.PROFILE)
        output, work = self.root / 'output', self.root / 'work'
        output.mkdir(); work.mkdir()
        closure = dependencies.prepare(root, work, output, 'c')
        observed = selected(closure, compiler_digest=digest(b'compiler'), runtime_digest=digest(b'runtime'),
                            runtime_profile=facilities.PROFILE)
        self.assertEqual(observed.receipt['runtimeProfile'], facilities.PROFILE)
        self.assertEqual(observed.sources[0].name, 'clock_probe.c')
        self.assertIn(b'getentropy(bytes, 256)', observed.sources[0].read_bytes())
        self.assertNotIn(b'latent_', observed.sources[0].read_bytes())
        self.assertEqual(profiles('c')['random'][2], 'bytes')
        self.assertEqual(profiles('go')['random'][2], 'u64-value')
        self.assertEqual(profiles('dotnet'), {'clockMonotonic': profiles('c')['clockMonotonic']})
        closure.check_unchanged()

    def test_c_execution_profile_cannot_be_selected_for_another_language_or_with_implicit_consent(self):
        from tools.run_rust_capsule_workflow import run
        for language, selected in (('java', True), ('c', 1), ('c', 'yes')):
            destination = self.root / 'must-not-exist'
            with self.subTest(language=language, selected=selected), self.assertRaisesRegex(RuntimeError, 'c-standard-facilities-language'):
                run(Path('missing'), Path('missing'), Path('missing'), destination,
                    language=language, c_standard_facilities=selected)
            self.assertFalse(destination.exists())

    def test_receipt_cannot_borrow_profile_or_original_runtime_after_rehash(self):
        root = project.create(self.root / 'project', 'greeting')
        files = project.snapshot(root)
        value = json.loads(files['capsule-project.json'])
        files['capsule-project.json'] = json.dumps({**value, 'runtimeProfile': facilities.PROFILE}).encode()
        component = b'controlled component identity, not runtime qualification'
        materials = [{'name': 'build-recipe', 'digest': digest(b'actual recipe'), 'size': 13}]
        receipts.emit(self.root, 'c', facilities.PROFILE, files, inventory(files), component, materials,
                      graph=None, binding_digest=digest(b'actual derived bindings'), configuration={})
        receipt = receipts.read((self.root / 'standard-runtime-selection.json').read_bytes())
        receipts.verify_build(receipt, 'c', files, inventory(files), component, materials)
        self.assertEqual((receipt['qualification'], receipt['apiSupport'], receipt['authority']),
                         ('unknown', 'not-evaluated', 'none'))
        changed = dict(files)
        changed['capsule-project.json'] = json.dumps({**value, 'runtimeProfile': facilities.DEFAULT}).encode()
        receipt['sourceDigest'] = digest(inventory(changed))
        receipt['identity'] = digest(receipts.encode({k: v for k, v in receipt.items() if k != 'identity'}))
        with self.assertRaisesRegex(DevError, 'stale-profile'):
            receipts.verify_build(receipt, 'c', changed, inventory(changed), component, materials)


if __name__ == '__main__':
    unittest.main()
