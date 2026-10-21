"""Bound captured diagnostic attribution; these controls do not execute guests."""
import copy
import tempfile
from pathlib import Path
import unittest

from tools import guest_compatibility as report
from tools import guest_compatibility_context as context
from tools import guest_compatibility_context_build as build
from tools.dev_workflow.common import DevError, digest, encode
from tools.rust_capsule_project import inventory


def package(index, **metadata):
    return {'id': f'outside-{index}', 'treeDigest': digest(f'tree-{index}'.encode()),
            'original': {'digest': digest(f'archive-{index}'.encode())}, 'metadata': metadata}


def files(language, packages):
    return {'sdk-lock.json': encode({'language': language}),
            'latent.dependencies.lock.json': encode({'language': language, 'artifacts': packages})}


def observe(language, captured):
    source = inventory(captured)
    value = report.report(language, digest(source), digest(b'component'), 'lsf-host-abi-phase3-v5', [],
        [report.finding('unresolved-behavior', 'initialization', 'not-evaluated')])
    original = encode(value)
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory)
        (output/'compatibility-report.json').write_bytes(original)
        result = build.finish(output, captured, source, b'component', [])
        assert (output/'compatibility-report.json').read_bytes() == original
        return result


class CompatibilityAttribution(unittest.TestCase):
    def test_partial_owner_graph_omits_unknown_attribution_without_becoming_a_build_gate(self):
        captured = {'sdk-lock.json': encode({'language': 'rust'}),
            'latent.dependencies.lock.json': encode({'selection': {'runtimeProfile': 'closed'},
                'artifacts': [{'name': 'unknown-package', 'digest': digest(b'partial')}],
                'privateRepository': 'https://credential:secret@private.invalid/path'})}
        rows, omitted = build.dependency_materials(captured, inventory(captured), 'rust')
        self.assertEqual((rows, omitted), ([], 1))
        selected = observe('rust', captured)
        self.assertEqual(selected['omittedMaterials'], 1)
        self.assertEqual(selected['qualification'], 'unknown')
        self.assertNotIn('private.invalid', context.present(selected))

    def test_all_six_build_contexts_bind_exact_captured_package_version_and_both_identities(self):
        for language in report.LANGUAGES:
            with self.subTest(language=language):
                row = package(1, version='1.2.3-rc.1+local', source='https://private.invalid/path')
                selected = observe(language, files(language, [row]))
                material = next(row for row in selected['materials'] if row['kind'] == 'dependency')
                self.assertEqual(material, {'kind': 'dependency', 'name': 'outside-1',
                    'digest': row['treeDigest'], 'originalDigest': row['original']['digest'],
                    'version': '1.2.3-rc.1+local'})
                text = context.present(selected)
                for expected in (row['treeDigest'], row['original']['digest'], '1.2.3-rc.1+local',
                                 'share capsule authority', 'qualification unknown'):
                    self.assertIn(expected, text)
                self.assertNotIn('private.invalid', text)
                self.assertEqual((selected['authority'], selected['reachability'], selected['workerDrain']),
                                 ('none', 'unknown', 'unproven'))

    def test_unchanged_source_inventory_cannot_borrow_a_different_dependency_graph(self):
        original = files('rust', [package(1, version='1.0.0')])
        mutated = files('rust', [package(1, version='2.0.0')])
        with self.assertRaisesRegex(DevError, 'detached-dependency-inventory'):
            build.dependency_materials(mutated, inventory(original), 'rust')
        with self.assertRaisesRegex(DevError, 'dependency-graph'):
            build.dependency_materials(original, inventory(original), 'java')

    def test_native_replacement_uses_selected_version_and_local_source_keeps_version_unknown(self):
        captured = files('go', [package(1, version='v1.0.0', effectiveVersion='v2.0.0'),
                                package(2, version='v9.0.0', effectiveVersion=None)])
        rows, omitted = build.dependency_materials(captured, inventory(captured), 'go')
        self.assertEqual(omitted, 0)
        self.assertEqual(rows[0]['version'], 'v2.0.0')
        self.assertNotIn('version', rows[1])
        text = context.present(observe('go', captured))
        self.assertNotIn('v1.0.0', text)
        self.assertNotIn('v9.0.0', text)
        self.assertIn('v2.0.0', text)
        self.assertIn('captured version not-observed', text)

    def test_dependency_omissions_preserve_existing_material_floor_and_explicit_count(self):
        selected = observe('c', files('c', [package(i, version='1.0.0') for i in range(70)]))
        self.assertEqual(len(selected['materials']), 64)
        self.assertEqual(selected['materials'][0]['kind'], 'sdk')
        self.assertEqual(selected['omittedMaterials'], 7)
        self.assertIn('Additional materials omitted: 7.', context.present(selected))
        self.assertLessEqual(len(encode(selected)), context.MAX_BYTES)

    def test_private_metadata_and_invalid_labels_are_omitted_without_version_guessing(self):
        first = package(1, version='user:password@registry', token='never-print-this')
        second = package(2, version='https://user:password@private.invalid')
        second['id'] = '../private/source'
        captured = files('dotnet', [first, second, package(3)])
        rows, omitted = build.dependency_materials(captured, inventory(captured), 'dotnet')
        self.assertEqual(omitted, 1)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all('version' not in row for row in rows))
        text = context.present(observe('dotnet', captured))
        self.assertIn('captured version not-observed', text)
        for secret in ('password', 'never-print-this', 'private.invalid', '../private'):
            self.assertNotIn(secret, text)

    def test_version_tokens_cannot_attach_to_an_unrelated_runtime_material(self):
        for version in ('user:password@host', '../file', 'https://host', '1\nsecret', '', True, 'x'*129):
            with self.subTest(version=version), self.assertRaises(DevError):
                context.material('dependency', 'outside', digest(b'pkg'), version=version)
        with self.assertRaisesRegex(DevError, 'version-owner'):
            context.material('runtime', 'runtime', digest(b'pkg'), version='1.2.3')

    def test_selected_runtime_and_patch_present_original_result_and_transform_separately(self):
        value = report.report('go', digest(b'source'), None, 'lsf-host-abi-phase3-v5', [], [])
        material = context.material('patch', 'owned-port', digest(b'result'),
            original=digest(b'original'), transformation=digest(b'recipe-and-configuration'), profile='selected-v1')
        selected = context.create(value, [material], {'state': 'absent'})
        text = context.present(selected)
        for expected in material.values():
            self.assertIn(expected if expected != 'patch' else 'Patch', text)
        self.assertIn('qualification unknown', text)

    def test_actual_generated_transform_material_is_visible_without_changing_the_bound_context(self):
        value = report.report('go', digest(b'source'), None, 'lsf-host-abi-phase3-v5', [], [])
        material = context.material('generated', 'maintained-sdk-binding-generation', digest(b'generated-result'),
            original=digest(b'original-wit'), transformation=digest(b'actual-transform-receipt'))
        selected = context.create(value, [material], {'state': 'absent'})
        before = copy.deepcopy(selected)
        text = context.present(selected)
        self.assertIn('Generated transformation: maintained-sdk-binding-generation', text)
        for key in ('digest', 'originalDigest', 'transformDigest'):
            self.assertIn(material[key], text)
        self.assertEqual(selected, before)
        self.assertIn('qualification unknown', text)
        self.assertIn('worker drain remains unproven', text)

    def test_untransformed_generated_tool_material_does_not_claim_an_original_or_transformation(self):
        value = report.report('c', digest(b'source'), None, 'lsf-host-abi-phase3-v5', [], [])
        for options in ({}, {'original': digest(b'original')}, {'transformation': digest(b'transform')}):
            material = context.material('generated', 'c-generator-inputs', digest(b'generated'), **options)
            selected = context.create(value, [material], {'state': 'absent'})
            text = context.present(selected)
            self.assertNotIn('Generated transformation:', text)
            self.assertNotIn(material['digest'], text)

    def test_text_retains_bounded_package_source_symbol_and_location_without_raw_symbol_leak(self):
        finding = report.finding('target-incompatible', 'compile', 'compiler',
            package_digest=digest(b'package'), source_digest=digest(b'source'),
            symbol='outside::callback', location={'path': 'dependencies/outside/lib.rs', 'line': 17, 'column': 3})
        value = report.report('rust', digest(b'snapshot'), None, 'selected-profile', [], [finding])
        before = copy.deepcopy(value)
        text = report.present(value)
        for expected in (digest(b'package'), digest(b'source'), 'outside::callback',
                         'dependencies/outside/lib.rs:17:3'):
            self.assertIn(expected, text)
        self.assertEqual(value, before)
        for private in ('user:password@host', '/home/private/source', 'C:/private/source'):
            finding['symbol'] = private
            value = report.report('rust', digest(b'snapshot'), None, 'selected-profile', [], [finding])
            text = report.present(value)
            self.assertNotIn(private, text)
            self.assertIn('Symbol: redacted', text)


if __name__ == '__main__':
    unittest.main()
