"""Default shared-owner I/O and presentation controls, not guest qualification."""
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import guest_api_analysis as api
from tools import guest_compatibility as compatibility
from tools import guest_compatibility_context_build as build
from tools.dev_workflow.common import digest, encode
from tools.rust_capsule_project import inventory


def fixture(output, language='c', package='uncatalogued-outside', materials=()):
    component = b'\0asm\x01\0\0\0'
    files = {'sdk-lock.json': encode({'language': language}), 'src/source.txt': b'captured source',
             'package-name.txt': package.encode()}
    source, recipe = inventory(files), encode({'observed-helper': 'current'})
    report = compatibility.report(language, digest(source), digest(component), 'lsf-host-abi-phase3-v4', [], [])
    raw = encode(report)
    for name, body in (('component.wasm', component), ('source-inputs.json', source),
                       ('recipe-inputs.json', recipe), ('compatibility-report.json', raw)):
        (output / name).write_bytes(body)
    refs = [{'name': 'build-recipe', 'digest': digest(recipe), 'size': len(recipe)}, *materials]
    (output / 'build-observation.json').write_bytes(encode({'formatVersion': 1,
        'source': {'snapshotDigest': digest(source)}, 'componentDigest': digest(component), 'materials': refs}))
    selected = build.finish(output, files, source, component, refs)
    observed = api.read((output / api.NAME).read_bytes(), output, report, selected)
    return report, selected, observed, raw


class DefaultApiAnalysis(unittest.TestCase):
    def test_rehashing_context_and_api_cannot_replace_original_owner_selected_materials(self):
        names = ('c-closed-filesystem-libc-0', 'c-closed-filesystem-libc-1', 'c-closed-filesystem-stdio-v1')
        refs = [{'name': name, 'digest': digest(name.encode()), 'size': 16} for name in names]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            report, selected, value, _ = fixture(output, materials=refs)
            original_owner = (output / 'build-observation.json').read_bytes()
            selected = copy.deepcopy(selected)
            selected_ref = next(row for row in selected['materials'] if row['name'] == names[0])
            selected_ref['digest'] = digest(b'foreign implementation')
            selected['identity'] = digest(encode({key: item for key, item in selected.items() if key != 'identity'}))
            forged = copy.deepcopy(value); forged['contextIdentity'] = selected['identity']
            for row in forged['apis']:
                for ref in row['implementationMaterials']:
                    if ref['name'] == names[0]: ref['digest'] = selected_ref['digest']
            for ref in forged['standardImplementationMaterials']:
                if ref['name'] == names[0]: ref['digest'] = selected_ref['digest']
            forged['identity'] = digest(encode({key: item for key, item in forged.items() if key != 'identity'}))
            (output / 'compatibility-context.json').write_bytes(encode(selected))
            (output / api.NAME).write_bytes(encode(forged))
            with self.assertRaisesRegex(ValueError, 'detached-original-material'):
                api.read(encode(forged), output, report, selected)
            self.assertEqual((output / 'build-observation.json').read_bytes(), original_owner)

    def test_shared_normal_finish_emits_all_six_without_changing_original_report_or_package_eligibility(self):
        for language in compatibility.LANGUAGES:
            with self.subTest(language=language), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                report, selected, observed, original = fixture(output, language)
                self.assertEqual((output / 'compatibility-report.json').read_bytes(), original)
                self.assertEqual(observed['language'], language)
                self.assertEqual(observed['state'], 'observed')
                self.assertEqual(observed['libraryEligibility'], 'not-evaluated')
                self.assertEqual(observed['uncataloguedApis'], 'unknown')
                self.assertEqual(observed['contextIdentity'], selected['identity'])
                expected_owner = {'c': 744, 'rust': 743, 'go': 742, 'java': 741, 'dotnet': 746, 'typescript': 745}[language]
                self.assertTrue(all(row['apiReachability'] == 'unknown' and row['apiBehavior'] == 'unqualified'
                                    and row['ownerIssue'] == expected_owner for row in observed['apis']))
                self.assertNotIn('uncatalogued-outside', encode(observed).decode())

    def test_unknown_package_rename_changes_source_binding_without_changing_api_verdict(self):
        for language in compatibility.LANGUAGES:
            with self.subTest(language=language), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); first = root / 'first'; first.mkdir(); second = root / 'second'; second.mkdir()
                left = fixture(first, language, 'unknown-original')[2]
                right = fixture(second, language, 'unknown-renamed')[2]
                self.assertNotEqual(left['sourceDigest'], right['sourceDigest'])
                self.assertEqual([(row['api'], row['state'], row['ownerIssue'], row['apiBehavior']) for row in left['apis']],
                                 [(row['api'], row['state'], row['ownerIssue'], row['apiBehavior']) for row in right['apis']])

    def test_identified_materials_are_still_unqualified_and_rehashed_behavior_upgrade_refuses(self):
        names = ('c-closed-filesystem-libc-0', 'c-closed-filesystem-libc-1', 'c-closed-filesystem-stdio-v1')
        refs = [{'name': name, 'digest': digest(name.encode()), 'size': 16} for name in names]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            report, selected, value, _ = fixture(output, materials=refs)
            self.assertEqual(value['apis'][0]['state'], 'selected-implementation-unqualified')
            self.assertEqual([row['name'] for row in value['apis'][0]['implementationMaterials']], list(names))
            forged = copy.deepcopy(value); forged['apis'][0]['apiBehavior'] = 'supported'
            forged['identity'] = digest(encode({key: item for key, item in forged.items() if key != 'identity'}))
            with self.assertRaisesRegex(ValueError, 'cannot-certify-behavior'): api.read(encode(forged), output, report, selected)
            with self.assertRaisesRegex(ValueError, 'cannot-certify-behavior'): api.present(forged)

    def test_actual_source_component_recipe_and_root_file_mutations_cannot_reuse_old_api_report(self):
        for filename in ('component.wasm', 'source-inputs.json', 'recipe-inputs.json', 'compatibility-reachability.json'):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                report, selected, value, _ = fixture(output)
                (output / filename).write_bytes(b'changed input')
                with self.assertRaises(ValueError): api.read(encode(value), output, report, selected)

    def test_default_existing_presentation_loads_fixed_sidecar_and_json_report_stays_v1(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            report, _, _, _ = fixture(output)
            stdout = io.StringIO()
            with patch('sys.argv', ['compatibility', str(output / 'compatibility-report.json')]), contextlib.redirect_stdout(stdout):
                self.assertEqual(compatibility.main(), 0)
            self.assertIn('API implementation observations', stdout.getvalue())
            self.assertIn('owner #744', stdout.getvalue())
            stdout = io.StringIO()
            with patch('sys.argv', ['compatibility', str(output / 'compatibility-report.json'), '--json']), contextlib.redirect_stdout(stdout):
                self.assertEqual(compatibility.main(), 0)
            self.assertEqual(json.loads(stdout.getvalue()), report)
            # Exercise the REAL file entrypoint under the same sanitized
            # environment as the compiler owner, outside the checkout. An
            # in-process main() call cannot detect a missing tools bootstrap.
            from tools.build_observation import build_environment
            from tools.rust_capsule_project import ROOT
            environment = build_environment(output)
            self.assertNotIn('PYTHONPATH', environment)
            for options in ([], ['--json']):
                completed = subprocess.run([sys.executable, '-B', ROOT / 'tools/guest_compatibility.py',
                    output / 'compatibility-report.json', *options], cwd=output,
                    env=environment, capture_output=True, timeout=15)
                self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors='replace'))
                self.assertEqual(completed.stderr, b'')
                if options: self.assertEqual(json.loads(completed.stdout), report)
                else: self.assertIn(b'API implementation observations;', completed.stdout)

    def test_missing_passive_input_has_closed_unavailable_result_without_new_build_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            report, selected, _, original = fixture(output)
            (output / api.NAME).unlink()
            (output / 'compatibility-reachability.json').unlink()
            value = api.emit(output, report, selected)
            self.assertEqual(value['state'], 'unavailable')
            self.assertEqual(api.read((output / api.NAME).read_bytes(), output, report, selected), value)
            self.assertEqual((output / 'compatibility-report.json').read_bytes(), original)
            self.assertNotIn('private', encode(value).decode())




class FiniteImplementationFixtureMapping(unittest.TestCase):
    def test_exact_standard_materials_profiles_and_owners_only_select_finite_fixture(self):
        for known in api.FINITE_IMPLEMENTATION_FIXTURES:
            with self.subTest(cell=known['cell']):
                refs = sorted(copy.deepcopy(known['materials']), key=lambda row: row['name'])
                def selected(materials=refs, runtime=known['runtimeProfile'], host=known['hostAbiProfile'],
                             owners=known['ownerObservations'], language=known['language']):
                    return api.finite_implementation_fixtures(language, materials, runtime, host, owners)
                self.assertEqual(selected(), [known])
                for index in range(len(refs)):
                    changed = copy.deepcopy(refs); changed[index]['digest'] = digest(b'different-standard-bytes')
                    # Java identity is original JARs + selected CFileSystem
                    # source, not the per-app runtime/profile JSON digest.
                    self.assertEqual(selected(materials=changed), [known] if known['cell'] == 'java' else [])
                self.assertEqual(selected(materials=[]), [])
                self.assertEqual(selected(runtime='foreign-profile'), [])
                self.assertEqual(selected(host='foreign-host'), [])
                self.assertEqual(selected(language='foreign-language'), [])
                self.assertEqual(selected(owners={'java-closed-filesystem': digest(b'foreign-owner')}), [])
                selected()[0]['origin']['run'] = 0
                self.assertNotEqual(selected()[0]['origin']['run'], 0)
        self.assertEqual(api.missing_implementation_issues('node.net.Socket', 'typescript'), [738, 739, 745])
        self.assertFalse(any(row['cell'] in {'go', 'dotnet'} for row in api.FINITE_IMPLEMENTATION_FIXTURES))

    def test_rehashed_fixture_claim_and_legacy_downgrade_cannot_replace_current_owner_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            report, selected, value, _ = fixture(output)
            self.assertEqual(value['finiteImplementationFixtures'], [])
            self.assertTrue(all(row['apiBehavior'] == 'unqualified' for row in value['apis']))
            forged = copy.deepcopy(value)
            forged['finiteImplementationFixtures'] = [copy.deepcopy(api.FINITE_IMPLEMENTATION_FIXTURES[0])]
            forged['identity'] = digest(encode({key: item for key, item in forged.items() if key != 'identity'}))
            with self.assertRaisesRegex(ValueError, 'rehashed-qualification'):
                api.present(forged)
            legacy = copy.deepcopy(value)
            del legacy['standardImplementationMaterials']; del legacy['finiteImplementationFixtures']
            for row in legacy['apis']: del row['missingImplementationIssues']
            legacy['identity'] = digest(encode({key: item for key, item in legacy.items() if key != 'identity'}))
            self.assertEqual(api.validate(legacy), legacy)
            self.assertNotIn('finite fixture', api.present(legacy))
            with self.assertRaisesRegex(ValueError, 'stale-or-rehashed-evidence'):
                api.read(encode(legacy), output, report, selected)


if __name__ == '__main__': unittest.main()
