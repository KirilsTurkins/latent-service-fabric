"""Pure source/consumer controls; no NativeAOT operation is executed here."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import dotnet_reflection_fixture as fixture
from tools.dotnet_guest.project import create
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import digest, snapshot


class BoundarySelection(unittest.TestCase):
    def test_real_project_selects_explicit_jit_and_byref_like_roots_without_sdk_or_wit_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = create(Path(temporary) / 'project', 'greeting')
            before = {name: (project / name).read_bytes() for name in ('sdk-lock.json', 'global.json', 'wit/world.wit')}
            fixture.select(project, boundaries=True)
            self.assertEqual((project / fixture.DESCRIPTOR).read_bytes(), fixture.BOUNDARY_ROOTS)
            for name, raw in before.items():
                self.assertEqual((project / name).read_bytes(), raw)
            from tools.dotnet_application_dependencies import declarations
            selected = declarations(snapshot(project))
            self.assertEqual(selected['trimmingDescriptors'][0]['digest'], digest(fixture.BOUNDARY_ROOTS))
            self.assertIn(b'<method name="ByRefLikeValue"', fixture.BOUNDARY_ROOTS)
            self.assertIn('new System.Reflection.Emit.DynamicMethod', fixture.BOUNDARY_LIBRARY)
            self.assertIn('catch (PlatformNotSupportedException)', fixture.BOUNDARY_LIBRARY)
            self.assertIn('catch (System.NotSupportedException)', fixture.BOUNDARY_LIBRARY)
            self.assertIn('method.ReturnType.IsByRefLike', fixture.BOUNDARY_LIBRARY)
            self.assertIn('BoundaryBodyCalls != 0', fixture.BOUNDARY_LIBRARY)

    def test_original_source_and_four_case_prefix_are_preserved(self):
        self.assertTrue(fixture.BOUNDARY_LIBRARY.startswith(fixture.LIBRARY))
        self.assertEqual(fixture.BOUNDARY_CASES[:4], fixture.CASES)
        self.assertEqual(len(fixture.BOUNDARY_CASES), 7)
        self.assertNotIn('DynamicMethod', fixture.LIBRARY)
        self.assertNotIn('ByRefLike', fixture.LIBRARY)

    def test_new_selection_is_strict_boolean_before_project_effects(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = create(Path(temporary) / 'project', 'greeting')
            before = snapshot(project)
            for value in (1, 'true', None):
                with self.subTest(value=value), self.assertRaisesRegex(WorkflowError, 'reflection-boundaries-boolean'):
                    fixture.select(project, boundaries=value)
                self.assertEqual(snapshot(project), before)


class BoundarySignedConsumer(unittest.TestCase):
    def test_all_seven_actual_probe_results_bind_the_selected_revision_and_reap(self):
        from tools import rust_capsule_node as node
        revision = {'publicationId': 'selected', 'routeGeneration': '18', 'releaseDigest': digest(b'actual'), 'revisionId': 'revision'}
        calls, values = [], []
        target = {'budget': {'memoryBytes': 134217728}}
        def call(_client, selected, template, function, arguments, activation):
            self.assertIs(selected, target)
            self.assertEqual((template, function), ('greeting', 'greet'))
            index = len(calls)
            calls.append(arguments)
            failed = fixture.BOUNDARY_CASES[index][1] is None
            return {'exitCode': 4 if failed else 0, 'processReaped': True, 'activation': activation,
                'response': {'outcomeKnown': True, 'category': 'platform-failure' if failed else 'success',
                    'error': {'code': 'guest-trap'} if failed else None,
                    'data': {'terminalState': 'guest_trap' if failed else 'succeeded',
                        'consumption': {'peakMemoryBytes': '4096', 'outboundRequests': '0'}, 'resolvedRevision': revision}}}
        result = {'invocations': [], 'samples': [], 'providerIdle': []}
        with patch.object(node, 'selected_revision', return_value=revision), patch.object(node, 'call', side_effect=call), \
                patch.object(node, 'assert_value', side_effect=lambda client, row, expected: values.append(expected)), \
                patch.object(node, 'sample', return_value={'idle': True}), patch.object(node, 'provider_idle', return_value=True):
            fixture.probe(object(), target, object(), result, 5, boundaries=True)
        self.assertEqual(calls, [['reflection:' + mode] for mode, _ in fixture.BOUNDARY_CASES])
        self.assertEqual(values[-3:], [[{'ok': 'dynamic-code-unsupported'}], [{'ok': 'byref-like-invoke-unsupported'}],
                                      [{'ok': 'descriptor-reflected:after-boundaries'}]])
        self.assertEqual(len(result['samples']), 7)
        self.assertEqual(len(result['dotnetReflectionBoundaries']['cases']), 7)
        self.assertFalse(result['dotnetReflectionBoundaries']['fullTicketQualification'])

    def test_selector_refuses_wrong_language_nonboolean_and_conflicting_modes_before_effect(self):
        from tools import run_rust_capsule_workflow as workflow
        for options in ({'language': 'rust', 'dotnet_reflection_boundaries': True},
                        {'language': 'dotnet', 'dotnet_reflection_boundaries': 1},
                        {'language': 'dotnet', 'dotnet_reflection_boundaries': True, 'dotnet_reflection': True},
                        {'language': 'dotnet', 'dotnet_reflection_boundaries': True, 'captured_dotnet_private': True},
                        {'language': 'dotnet', 'dotnet_reflection_boundaries': True, 'captured_dependency_recovery': True}):
            with self.subTest(options=options), patch.object(workflow, 'fresh') as fresh, \
                    self.assertRaisesRegex(WorkflowError, 'authoring-dotnet-reflection-boundaries-language'):
                workflow.run(None, None, None, None, **options)
            fresh.assert_not_called()


class CatalogueFreeSource(unittest.TestCase):
    def test_actual_staged_build_entry_imports_in_isolated_python_with_only_recipe_and_support(self):
        import subprocess
        import sys
        from tools import dotnet_catalogue_free_build as staging
        from tools.rust_capsule_project import ROOT
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'staged'
            receipt = staging.stage(ROOT, root)
            self.assertEqual(staging.verify(root), receipt)
            self.assertLessEqual(receipt['fileCount'], staging.MAX_FILES)
            self.assertEqual({name for name in receipt['files'] if not name.endswith('.py')}, staging.DATA)
            self.assertFalse(any(part in {'docs', 'reference', 'catalogue', 'catalog', '.git', 'target'}
                                 for name in receipt['files'] for part in Path(name).parts))
            self.assertTrue(set(staging.RECIPE) <= receipt['files'].keys())
            # --help parses/imports the actual staged entry without starting a build.
            completed = subprocess.run([sys.executable, '-I', '-S', '-B', str(root / staging.SELF), '--help'],
                cwd=temporary, capture_output=True, timeout=15, check=True)
            self.assertIn(b'--expect-source-digest', completed.stdout)
            self.assertEqual(staging.verify(root), receipt)
            self.assertFalse(receipt['actualComponentQualified'])

    def test_staged_source_substitution_missing_recipe_and_extra_data_all_refuse(self):
        from tools import dotnet_catalogue_free_build as staging
        from tools.rust_capsule_project import ROOT
        for mode in ('source-mutated', 'missing-recipe', 'extra-reference-data'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / 'staged'
                staging.stage(ROOT, root)
                if mode == 'source-mutated':
                    path = root / 'tools/dotnet_guest/build.py'
                    path.write_bytes(path.read_bytes() + b'\n# changed source\n')
                elif mode == 'missing-recipe':
                    (root / 'wit/host-abi-phase3-v4.json').unlink()
                else:
                    (root / 'reference').mkdir()
                    (root / 'reference/optional-catalogue.json').write_bytes(b'{}')
                with self.assertRaises((WorkflowError, ValueError, OSError)):
                    staging.verify(root)

    def test_recipe_escape_link_and_source_caps_refuse_before_stage_publication(self):
        import os
        from tools import dotnet_catalogue_free_build as staging
        for mode in ('traversal', 'hardlink', 'byte-cap', 'file-cap'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root, target = Path(temporary) / 'source', Path(temporary) / 'staged'
                (root / 'tools').mkdir(parents=True)
                (root / staging.SELF).write_bytes(b'')
                recipe = ('../foreign.py',) if mode == 'traversal' else (staging.SELF,)
                options = {'RECIPE': recipe, 'DATA': frozenset()}
                if mode == 'hardlink':
                    os.link(root / staging.SELF, root / 'tools/link.py')
                elif mode == 'byte-cap':
                    (root / staging.SELF).write_bytes(b'too many bytes')
                    options['MAX_BYTES'] = 1
                elif mode == 'file-cap':
                    options['MAX_FILES'] = 0
                with patch.multiple(staging, **options), self.assertRaises((WorkflowError, ValueError, OSError)):
                    staging.stage(root, target)
                self.assertFalse(target.exists())

    def test_wrong_expected_stage_identity_refuses_before_any_compiler_work(self):
        from tools import dotnet_catalogue_free_build as staging
        from tools.rust_capsule_project import ROOT
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'staged'
            staging.stage(ROOT, root)
            args = ['--project', 'unused-project', '--output', 'unused-output', '--tools', 'unused-tools',
                '--contracts-tool', 'unused-contracts', '--packager', 'unused-packager',
                '--repository', 'https://github.com/example/project', '--expect-source-digest', digest(b'foreign')]
            with patch.object(staging, 'ROOT', root), patch.object(staging, 'build') as build, \
                    self.assertRaisesRegex(WorkflowError, 'catalogue-free-unexpected-stage'):
                staging.main(args)
            build.assert_not_called()


class ActualBoundaryPreparation(unittest.TestCase):
    def test_boundary_installer_reaches_real_resolver_with_exact_extended_library_and_descriptor(self):
        from tools.dotnet_application_dependencies import declarations
        reached = []
        outer = self
        class StopAtNativeBoundary(Exception):
            pass
        class SourceOnlyCompiler:
            def __init__(self, tools, commands, vendor, *, offline, captured):
                outer.assertTrue(offline and captured)
                self.commands, self.dotnet = commands, Path('never-executed-dotnet')
            def run(self, name, executable, *arguments):
                outer.assertEqual(name, 'reflection-library')
                library = Path(arguments[1]).parent
                outer.assertEqual((library / 'Library.cs').read_text(), fixture.BOUNDARY_LIBRARY)
                destination = library / 'bin/Release/net10.0'
                destination.mkdir(parents=True)
                (destination / 'ReflectionInput.dll').write_bytes(b'modeled-not-executed-boundary-library')
            def check_unchanged(self):
                reached.append('recheck')
        def resolve(project, candidate, *, dotnet, tools, policy):
            selected = declarations(snapshot(project))
            outer.assertEqual(selected['trimmingDescriptors'][0]['digest'], digest(fixture.BOUNDARY_ROOTS))
            outer.assertIn('OutsideReflectionBoundary.Describe', (project / 'src/Main.cs').read_text())
            outer.assertEqual(len(selected['packages']), 1)
            outer.assertEqual(dotnet, Path('never-executed-dotnet'))
            reached.append('normal-native-resolve')
            raise StopAtNativeBoundary()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = create(root / 'project', 'greeting')
            sdk = (project / 'sdk-lock.json').read_bytes()
            with patch.object(fixture, 'Compiler', SourceOnlyCompiler), patch.object(fixture, 'resolve', side_effect=resolve), \
                    self.assertRaises(StopAtNativeBoundary):
                fixture.install(project, root / 'outside', root / 'unused-tools', boundaries=True)
            self.assertEqual(reached, ['recheck', 'normal-native-resolve'])
            self.assertEqual((project / 'sdk-lock.json').read_bytes(), sdk)
            self.assertEqual(list((root / 'outside').iterdir()), [])

    def test_isolated_build_entry_uses_ordinary_offline_builder_and_rechecks_actual_recipe(self):
        from tools import dotnet_catalogue_free_build as staging
        from tools.rust_capsule_project import ROOT
        for changed in (False, True):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / 'stage'
                receipt = staging.stage(ROOT, root)
                output = Path(temporary) / 'output'
                def build(project, destination, contracts, packager, repository, *, tools, offline):
                    self.assertTrue(offline)
                    destination.mkdir()
                    recipe = {name: receipt['files'][name] for name in staging.RECIPE}
                    if changed:
                        recipe['tools/dotnet_guest/build.py'] = {'digest': digest(b'foreign'), 'size': 7}
                    (destination / 'recipe-inputs.json').write_text(json.dumps(recipe))
                    return destination
                args = ['--project', str(Path(temporary) / 'project'), '--output', str(output),
                    '--tools', 'unused-tools', '--contracts-tool', 'unused-contracts', '--packager', 'unused-packager',
                    '--repository', 'https://github.com/example/project', '--expect-source-digest', receipt['inventoryDigest']]
                with patch.object(staging, 'ROOT', root), patch.object(staging, 'build', side_effect=build), \
                        patch('builtins.print'):
                    if changed:
                        with self.assertRaisesRegex(WorkflowError, 'catalogue-free-actual-recipe-not-staged'):
                            staging.main(args)
                    else:
                        self.assertEqual(staging.main(args), output)

    def test_failed_qualification_observer_preserves_the_original_exception_identity(self):
        from tools import qualify_dotnet_reflection_boundaries as qualifier
        original = RuntimeError('private error remains private')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(qualifier, 'prepared_inputs', side_effect=original), \
                    patch.object(qualifier, 'write_json', side_effect=RecursionError('observer')):
                with self.assertRaises(RuntimeError) as caught:
                    qualifier.qualify(root / 'unused', root / 'output', root / 'unused-tools')
            self.assertIs(caught.exception, original)


if __name__ == '__main__':
    unittest.main()
