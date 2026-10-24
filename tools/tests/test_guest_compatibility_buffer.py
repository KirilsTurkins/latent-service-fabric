"""Actual filesystem provenance readers; no compiler or guest execution."""
import copy
from pathlib import Path
import tempfile
import unittest

from tools import guest_compatibility as compatibility
from tools import guest_compatibility_context as context
from tools import guest_compatibility_context_build as builder
from tools import guest_compatibility_outcomes as outcomes
from tools import guest_runtime_receipts
from tools.dev_workflow.common import DevError, digest, encode
from tools.rust_capsule_project import ROOT, inventory
from tools.typescript_guest import buffer_profile

COMPONENT = b'component identity fixture; not a runtime component'


class CapturedBuffer:
    def __init__(self, root, *, selected=True, declaration=None):
        self.root = root
        self.output = root/'build'
        self.output.mkdir()
        declared = (ROOT/buffer_profile.DECLARATION).read_bytes()
        self.backend = (ROOT/buffer_profile.BACKEND).read_bytes()
        self.files = {'sdk-lock.json': encode({'language': 'typescript'})}
        self.selected = selected
        if selected:
            self.files['vendor/lsf/'+buffer_profile.DECLARATION] = declared if declaration is None else declaration
            self.files['wit/world.wit'] = b'package tests:buffer@1.0.0; world service {}\n'
        self.source = inventory(self.files)
        self.recipe = inventory({buffer_profile.BACKEND: self.backend, buffer_profile.DECLARATION: declared})
        self.materials = []
        self.write_bound('recipe-inputs.json', 'build-recipe', self.recipe)
        self.selection = buffer_profile.check_selection({'standardBufferModules': ['node:buffer'],
            'standardBufferProfile': buffer_profile.PROFILE,
            'standardBufferBackendDigest': digest(self.backend)}, digest(self.backend))
        if selected:
            self.write_bound('typescript-buffer-selection.json', context.BUFFER_MATERIALS[0], encode(self.selection))
        self.report = compatibility.report('typescript', digest(self.source), digest(COMPONENT),
            'lsf-host-abi-phase3-v5', [],
            [compatibility.finding('unresolved-behavior', 'initialization', 'not-evaluated')])
        (self.output/'compatibility-report.json').write_bytes(encode(self.report))
        (self.output/'source-inputs.json').write_bytes(self.source)
        self.descriptor = {'artifacts': {'component': 'build/component.wasm'}}
        self.frontend = {'source': digest(b'frontend snapshot'), 'artifacts': {'component': digest(COMPONENT)}}

    def write_bound(self, filename, name, raw):
        (self.output/filename).write_bytes(raw)
        self.materials = [row for row in self.materials if row['name'] != name]
        self.materials.append({'name': name, 'digest': digest(raw), 'size': len(raw)})

    def finish(self):
        if self.selected and not (self.output/'standard-runtime-selection.json').exists():
            self.materials.append(guest_runtime_receipts.emit(self.output, 'typescript',
                'spidermonkey-public-sync-v1', self.files, self.source, COMPONENT, self.materials,
                graph=None, binding_digest=digest(b'source-binding identity fixture'), configuration={}))
        return builder.finish(self.output, self.files, self.source, COMPONENT, self.materials)

    def read(self):
        return outcomes.from_build(self.root, self.descriptor, self.frontend)


class BufferCompatibility(unittest.TestCase):
    def test_bound_module_renders_both_aliases_and_stays_unqualified(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = CapturedBuffer(Path(temporary))
            value = fixture.finish()
            rows = context.buffer_module(value)
            self.assertEqual(rows[context.BUFFER_MATERIALS[0]]['digest'],
                digest((fixture.output/'typescript-buffer-selection.json').read_bytes()))
            self.assertEqual(rows[context.BUFFER_MATERIALS[1]]['digest'], digest(fixture.backend))
            self.assertEqual(rows[context.BUFFER_MATERIALS[2]]['digest'],
                digest(fixture.files['vendor/lsf/'+buffer_profile.DECLARATION]))
            text = context.present(value)
            self.assertIn('SELECTED runtime module: buffer, node:buffer; profile lsf-node-buffer-v1', text)
            self.assertIn('qualification unknown; authority none', text)
            self.assertEqual((value['qualification'], value['authority'], value['workerDrain']),
                             ('unknown', 'none', 'unproven'))
            self.assertEqual((fixture.output/'compatibility-report.json').read_bytes(), encode(fixture.report))
            self.assertEqual(fixture.read().context_state, 'observed')

    def test_bound_receipt_and_strict_json_types_cannot_drift(self):
        for field, changed in (('backendDigest', 'sha256:'+'0'*64), ('qualification', 'passed'),
                               ('globalBufferInstalled', 0), ('nativeStorage', 0.0),
                               ('maximumBufferBytes', 1048576.0)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                fixture = CapturedBuffer(Path(temporary))
                fixture.write_bound('typescript-buffer-selection.json', context.BUFFER_MATERIALS[0],
                    encode(dict(fixture.selection, **{field: changed})))
                with self.assertRaisesRegex(ValueError, 'retained-selection-drift'):
                    fixture.finish()
        with tempfile.TemporaryDirectory() as temporary:
            fixture = CapturedBuffer(Path(temporary))
            (fixture.output/'typescript-buffer-selection.json').write_bytes(b'changed after material capture')
            with self.assertRaisesRegex(DevError, 'stale-or-unbound-receipt'):
                fixture.finish()

    def test_recipe_backend_and_captured_declaration_must_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = CapturedBuffer(Path(temporary), declaration=b'different captured declaration')
            with self.assertRaisesRegex(DevError, 'buffer-declaration-drift'):
                fixture.finish()
        for change in ('backend', 'missing-declaration', 'float-size'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                fixture = CapturedBuffer(Path(temporary))
                from tools.dev_workflow.common import decode
                recipe = decode(fixture.recipe)
                if change == 'backend':
                    recipe[buffer_profile.BACKEND]['digest'] = 'sha256:'+'0'*64
                elif change == 'missing-declaration':
                    del recipe[buffer_profile.DECLARATION]
                else:
                    recipe[buffer_profile.DECLARATION]['size'] = float(recipe[buffer_profile.DECLARATION]['size'])
                fixture.write_bound('recipe-inputs.json', 'build-recipe', encode(recipe))
                with self.assertRaises(ValueError):
                    fixture.finish()

    def test_outcome_reader_rechecks_files_and_freshly_rehashed_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = CapturedBuffer(Path(temporary))
            value = fixture.finish()
            for name in ('typescript-buffer-selection.json', 'recipe-inputs.json', 'source-inputs.json'):
                path = fixture.output/name
                original = path.read_bytes()
                path.write_bytes(b'changed after context capture')
                self.assertEqual(fixture.read().context_state, 'invalid-present', name)
                path.write_bytes(original)
            receipt = fixture.output/'typescript-buffer-selection.json'
            original = receipt.read_bytes(); receipt.unlink()
            self.assertEqual(fixture.read().context_state, 'invalid-present')
            receipt.write_bytes(original)
            changed = copy.deepcopy(value)
            next(row for row in changed['materials'] if row['name'] == context.BUFFER_MATERIALS[1])['digest'] = 'sha256:'+'0'*64
            changed['identity'] = digest(encode({key: item for key, item in changed.items() if key != 'identity'}))
            (fixture.output/'compatibility-context.json').write_bytes(encode(changed))
            self.assertEqual(fixture.read().context_state, 'invalid-present')
            (fixture.output/'compatibility-context.json').write_bytes(encode(value))
            self.assertEqual(fixture.read().context_state, 'observed')
            # Rewriting both sidecar and recipe, with a fresh context hash,
            # still cannot borrow the original owner input identities.
            from tools.dev_workflow.common import decode
            recipe = decode(fixture.recipe)
            recipe[buffer_profile.BACKEND]['digest'] = 'sha256:'+'0'*64
            recipe_raw = encode(recipe)
            selected_raw = encode(dict(fixture.selection, backendDigest='sha256:'+'0'*64))
            (fixture.output/'recipe-inputs.json').write_bytes(recipe_raw)
            receipt.write_bytes(selected_raw)
            changed = copy.deepcopy(value)
            replacements = {'build-recipe': digest(recipe_raw), context.BUFFER_MATERIALS[0]: digest(selected_raw),
                            context.BUFFER_MATERIALS[1]: 'sha256:'+'0'*64}
            for row in changed['materials']:
                if row['name'] in replacements:
                    row['digest'] = replacements[row['name']]
            changed['identity'] = digest(encode({key: item for key, item in changed.items() if key != 'identity'}))
            (fixture.output/'compatibility-context.json').write_bytes(encode(changed))
            self.assertEqual(fixture.read().context_state, 'invalid-present')

    def test_unselected_legacy_capture_keeps_generic_output_without_declarations(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = CapturedBuffer(Path(temporary), selected=False)
            value = fixture.finish()
            self.assertIsNone(context.buffer_module(value))
            self.assertEqual(value['standardRuntime'], {'state': 'absent'})
            self.assertEqual(value['materials'], [
                context.material('compiler', 'build-recipe', digest(fixture.recipe)),
                context.material('sdk', 'sdk-lock', digest(fixture.files['sdk-lock.json']))])
            self.assertNotIn('SELECTED runtime module', context.present(value))
            self.assertEqual(fixture.read().context_state, 'observed')

    def test_complete_module_and_recipe_survive_existing_material_cap(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = CapturedBuffer(Path(temporary))
            fixture.materials += [{'name': 'a-tool-'+str(index), 'digest': digest(str(index).encode()), 'size': 1}
                                  for index in range(61)]
            value = fixture.finish()
            self.assertEqual(len(value['materials']), 64)
            self.assertEqual(value['omittedMaterials'], 6)
            self.assertEqual(set(context.buffer_module(value)), {*context.BUFFER_MATERIALS, 'build-recipe'})
            self.assertLessEqual(len(encode(value)), 65536)
            changed = copy.deepcopy(value)
            changed['materials'] = [row for row in changed['materials'] if row['name'] != context.BUFFER_MATERIALS[2]]
            changed['identity'] = digest(encode({key: item for key, item in changed.items() if key != 'identity'}))
            with self.assertRaisesRegex(DevError, 'buffer-module-group'):
                context.validate(changed)
            changed = copy.deepcopy(value)
            del changed['standardRuntime']['receiptName']; del changed['standardRuntime']['ownerIssue']
            changed['identity'] = digest(encode({key: item for key, item in changed.items() if key != 'identity'}))
            with self.assertRaisesRegex(DevError, 'buffer-module-owner'):
                context.validate(changed)


if __name__ == '__main__':
    unittest.main()
