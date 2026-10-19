"""Source/consumer controls; NativeAOT and signed compatibility remain hosted."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import dotnet_reflection_fixture as fixture
from tools import qualify_dotnet_reflection as qualification
from tools.build_snapshot import canonical, digest
from tools.dotnet_application_dependencies import declarations
from tools.dotnet_guest.compiler import verify_application_resources
from tools.dotnet_guest.project import create
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import snapshot


class SelectedDescriptor(unittest.TestCase):
    def test_actual_project_selects_real_descriptor_without_sdk_or_wit_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = create(Path(temporary) / 'project', 'greeting')
            before = {name: (project / name).read_bytes() for name in ('sdk-lock.json', 'wit/world.wit', 'global.json')}
            fixture.select(project)
            selected = declarations(snapshot(project))
            self.assertEqual(selected['trimmingDescriptors'], [{'attributes': {'Include': fixture.DESCRIPTOR},
                'active': True, 'digest': digest(fixture.ROOTS), 'size': len(fixture.ROOTS)}])
            verify_application_resources(selected, project)
            self.assertEqual({name: (project / name).read_bytes() for name in before}, before)
            self.assertIn(b'? Reflect(clean.Substring(11))', (project / 'src/Main.cs').read_bytes())
            self.assertIn(b'OutsideReflection.Describe(request, output.ToArray())', (project / 'src/Main.cs').read_bytes())
            self.assertIn(b': $"Hello, {clean}!"', (project / 'src/Main.cs').read_bytes())
            self.assertIn('Assembly.GetType(fields[0]', fixture.LIBRARY)
            self.assertIn('type.GetMethod(fields[1]', fixture.LIBRARY)
            self.assertIn('method.Invoke(null', fixture.LIBRARY)
            self.assertNotIn('DynamicDependency', fixture.LIBRARY)
            self.assertNotIn('UnconditionalSuppressMessage', fixture.LIBRARY)

    def test_changed_or_missing_descriptor_refuses_at_the_actual_compiler_consumer(self):
        from tools.application_dependency_store import DependencyError
        with tempfile.TemporaryDirectory() as temporary:
            project = create(Path(temporary) / 'project', 'greeting')
            fixture.select(project)
            selected = declarations(snapshot(project))
            path = project / fixture.DESCRIPTOR
            for mode in ('changed', 'missing'):
                with self.subTest(mode=mode):
                    if mode == 'changed':
                        path.write_bytes(fixture.ROOTS + b'changed')
                    else:
                        path.unlink()
                    with self.assertRaisesRegex(DependencyError, 'nuget-compiler-resource-preimage-mismatch'):
                        verify_application_resources(selected, project)
                    path.write_bytes(fixture.ROOTS)

    def test_repeated_or_foreign_project_selection_refuses_instead_of_replacing_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = create(Path(temporary) / 'project', 'greeting')
            fixture.select(project)
            before = snapshot(project)
            with self.assertRaisesRegex(WorkflowError, 'reflection-original-project-required'):
                fixture.select(project)
            self.assertEqual(snapshot(project), before)


class ActualProducerBoundary(unittest.TestCase):
    def test_capture_requires_exact_ordinary_original_and_no_hidden_graph_or_executable(self):
        raw = b'bounded-modeled-original'
        row = {'id': 'outside.reflection/0.3.7', 'role': 'application', 'dependencies': [],
               'original': {'digest': digest(raw), 'size': len(raw)}}
        lock = {'artifacts': [row], 'executableInputs': []}
        self.assertEqual(fixture.captured_package(lock, 'Outside.Reflection', '0.3.7', raw), row)
        for mode in ('identity', 'original', 'role', 'edge', 'extra', 'executable'):
            with self.subTest(mode=mode):
                changed = copy.deepcopy(lock)
                if mode == 'identity':
                    changed['artifacts'][0]['id'] = 'foreign/0.3.7'
                elif mode == 'original':
                    changed['artifacts'][0]['original']['digest'] = digest(b'foreign')
                elif mode == 'role':
                    changed['artifacts'][0]['role'] = 'build-tool'
                elif mode == 'edge':
                    changed['artifacts'][0]['dependencies'] = ['uncaptured/1.0.0']
                elif mode == 'extra':
                    changed['artifacts'].append(copy.deepcopy(row))
                else:
                    changed['executableInputs'] = ['unapproved']
                with self.assertRaisesRegex(WorkflowError, 'reflection-exact-local-graph-required'):
                    fixture.captured_package(changed, 'Outside.Reflection', '0.3.7', raw)

    def test_actual_installer_reaches_normal_native_resolve_with_captured_descriptor_and_pure_library(self):
        reached = []
        class StopAtNativeBoundary(Exception):
            pass
        outer = self
        class SourceOnlyCompiler:
            def __init__(self, tools, commands, vendor, *, offline, captured):
                outer.assertTrue(offline and captured)
                self.commands, self.dotnet = commands, Path('never-executed-dotnet')
                (commands.root.parent / 'captured-dotnet-tools').mkdir()
            def run(self, name, executable, *arguments):
                outer.assertEqual(name, 'reflection-library')
                project = Path(arguments[1]).parent
                outer.assertEqual(project, self.commands.root)
                outer.assertEqual((project / 'Library.cs').read_text(encoding='utf-8'), fixture.LIBRARY)
                outer.assertIn('<AssemblyName>ReflectionInput</AssemblyName>', (project / 'Library.csproj').read_text())
                destination = project / 'bin/Release/net10.0'
                destination.mkdir(parents=True)
                (destination / 'ReflectionInput.dll').write_bytes(b'modeled-not-executed-library')
            def check_unchanged(self):
                reached.append('recheck')
        def resolve(project, candidate, *, dotnet, tools, policy):
            selected = declarations(snapshot(project))
            self.assertEqual(len(selected['packages']), 1)
            self.assertEqual(selected['trimmingDescriptors'][0]['digest'], digest(fixture.ROOTS))
            self.assertEqual(selected['resources'], [{'attributes': {'Include': fixture.LOAD_INPUT,
                'LogicalName': 'reflection.dynamic-input'}, 'active': True,
                'digest': digest(b'modeled-not-executed-library'), 'size': len(b'modeled-not-executed-library')}])
            self.assertEqual(dotnet, Path('never-executed-dotnet'))
            self.assertEqual(len(list(Path(policy['sources'][0]['path']).glob('*.nupkg'))), 1)
            reached.append('normal-native-resolve')
            raise StopAtNativeBoundary()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = create(root / 'project', 'greeting')
            sdk = (project / 'sdk-lock.json').read_bytes()
            with patch.object(fixture, 'Compiler', SourceOnlyCompiler), patch.object(fixture, 'resolve', side_effect=resolve), \
                    patch.object(fixture.authoring, 'review') as review, self.assertRaises(StopAtNativeBoundary):
                fixture.install(project, root / 'outside', root / 'unused-tools')
            review.assert_not_called()
            self.assertEqual(reached, ['recheck', 'normal-native-resolve'])
            self.assertEqual((project / 'sdk-lock.json').read_bytes(), sdk)
            self.assertEqual(list((root / 'outside').iterdir()), [])


class DescriptorEvidence(unittest.TestCase):
    def test_prepared_qualification_rechecks_current_source_and_the_exact_completed_native_products(self):
        from tools.phase3_resource_identity import file_identity
        with tempfile.TemporaryDirectory() as temporary:
            prepared = Path(temporary)
            (prepared / 'native-binaries').mkdir()
            source = {'reviewed-source': {'digest': digest(b'source'), 'size': 6}}
            raw = canonical(source)
            for name in ('source-inputs.json', 'source-inputs-after.json'):
                (prepared / name).write_bytes(raw)
            binaries = {}
            for name in qualification.PRODUCTS:
                path = prepared / 'native-binaries' / name.replace('/', '-')
                path.write_bytes(('modeled-not-executed-' + name).encode())
                binaries[name] = file_identity(path, 512 * 1024 * 1024)
            builds = {}
            for name in qualification.COMPANIONS:
                path = prepared / 'builds' / name
                path.mkdir(parents=True)
                builds[name] = {'componentDigest': digest(name.encode())}
                (path / 'BUILD-COMPLETE.json').write_bytes(canonical(builds[name]))
            receipt = {'status': 'passed', 'applicationDependencies': {}, 'sourceIdentityDigest': digest(raw),
                       'binaries': binaries, 'builds': builds}
            (prepared / 'qualification.json').write_bytes(canonical(receipt))
            with patch.object(qualification, 'inputs', return_value=source) as selected:
                qualification.prepared_inputs(prepared)
                selected.assert_called_with('dotnet')
                (prepared / 'native-binaries/latentd').write_bytes(b'changed')
                with self.assertRaisesRegex(WorkflowError, 'reflection-native-products-changed'):
                    qualification.prepared_inputs(prepared)
            with patch.object(qualification, 'inputs', return_value={'new-source': {}}):
                with self.assertRaisesRegex(WorkflowError, 'reflection-exact-prepared-source-required'):
                    qualification.prepared_inputs(prepared)

    def test_actual_source_compiler_selection_and_build_material_must_bind_same_descriptor(self):
        identity = {'digest': digest(fixture.ROOTS), 'size': len(fixture.ROOTS)}
        assembly = {'digest': digest(b'ordinary-managed-assembly'), 'size': 25}
        selected = {'trimmingDescriptors': [{'attributes': {'Include': fixture.DESCRIPTOR}, 'active': True, **identity}],
                    'resources': [{'attributes': {'Include': fixture.LOAD_INPUT, 'LogicalName': 'reflection.dynamic-input'},
                                   'active': True, **assembly}]}
        raw = canonical(selected)
        materials = [{'name': 'nuget-build-inputs', 'digest': digest(raw), 'size': len(raw)}]
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary)
            for mode in ('valid', 'selection-removed', 'selection-stale', 'source-stale', 'unbound-material', 'dynamic-input-stale'):
                with self.subTest(mode=mode):
                    current, source, observed = copy.deepcopy(selected), {fixture.DESCRIPTOR: identity,
                        fixture.LOAD_INPUT: assembly}, copy.deepcopy(materials)
                    if mode == 'selection-removed':
                        current['trimmingDescriptors'] = []
                    elif mode == 'selection-stale':
                        current['trimmingDescriptors'][0]['digest'] = digest(b'foreign')
                    elif mode == 'source-stale':
                        source[fixture.DESCRIPTOR] = {'digest': digest(b'foreign'), 'size': 7}
                    elif mode == 'unbound-material':
                        observed = []
                    elif mode == 'dynamic-input-stale':
                        current['resources'][0]['digest'] = digest(b'foreign')
                    (artifact / 'nuget-build-inputs.json').write_bytes(canonical(current))
                    (artifact / 'source-inputs.json').write_bytes(canonical(source))
                    (artifact / 'build-observation.json').write_bytes(canonical({'materials': observed}))
                    if mode == 'valid':
                        self.assertEqual(qualification.descriptor_material(artifact, assembly)['descriptor'], identity)
                    else:
                        with self.assertRaisesRegex(WorkflowError, 'reflection-compiler-descriptor-not-bound'):
                            qualification.descriptor_material(artifact, assembly)

    def test_failed_public_observer_preserves_the_original_exception_identity(self):
        original = RuntimeError('private failure text stays private')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(qualification, 'prepared_inputs', side_effect=original), \
                    patch.object(qualification, 'write_json', side_effect=RecursionError('observer')):
                with self.assertRaises(RuntimeError) as caught:
                    qualification.qualify(root / 'unused', root / 'output', root / 'unused-tools')
            self.assertIs(caught.exception, original)


class SignedBoundary(unittest.TestCase):
    def execute(self, *, fail_code='guest-trap', wrong_revision=False, known=True, reaped=True):
        from tools import rust_capsule_node as node
        revision = {'publicationId': 'selected', 'routeGeneration': '18', 'releaseDigest': digest(b'actual-component'), 'revisionId': 'revision'}
        target = {'generation': '1', 'budget': {'memoryBytes': 134217728}}
        values, calls = [], []
        def call(client, selected, template, function, arguments, activation):
            self.assertIs(selected, target)
            self.assertEqual((template, function), ('greeting', 'greet'))
            index = len(calls)
            calls.append(arguments)
            failed = fixture.CASES[index][1] is None
            return {'exitCode': 4 if failed else 0, 'processReaped': reaped, 'activation': activation,
                'response': {'outcomeKnown': known, 'category': 'platform-failure' if failed else 'success',
                    'error': {'code': fail_code} if failed else None,
                    'data': {'terminalState': fail_code.replace('-', '_') if failed else 'succeeded',
                        'consumption': {'peakMemoryBytes': '4096', 'outboundRequests': '0'},
                        'resolvedRevision': {**revision, 'routeGeneration': '1'} if wrong_revision else revision}}}
        result = {'invocations': [], 'samples': [], 'providerIdle': []}
        with patch.object(node, 'selected_revision', return_value=revision), patch.object(node, 'call', side_effect=call), \
                patch.object(node, 'assert_value', side_effect=lambda _client, row, value: values.append(value)), \
                patch.object(node, 'sample', return_value={'idle': True}), patch.object(node, 'provider_idle', return_value=True):
            fixture.probe(object(), target, object(), result, 5)
        self.assertEqual([v[0]['ok'] for v in values], ['descriptor-reflected:first', 'dynamic-loading-unsupported', 'descriptor-reflected:fresh'])
        self.assertEqual(calls, [['reflection:' + mode] for mode, _expected in fixture.CASES])
        self.assertEqual(len(result['samples']), 4)
        self.assertFalse(result['dotnetReflection']['fullTicketQualification'])
        self.assertEqual(result['dotnetReflection']['trapCause'], 'not-inferred-from-generic-node-error')

    def test_caught_refusal_terminal_trap_and_fresh_supported_reflection_are_distinct(self):
        self.execute()

    def test_resource_exhaustion_is_never_accepted_as_the_uncaught_operation_trap(self):
        with self.assertRaisesRegex(WorkflowError, 'rust-library-failure-result'):
            self.execute(fail_code='resource-exhausted')

    def test_uncertain_terminal_result_refuses(self):
        with self.assertRaisesRegex(WorkflowError, 'rust-library-failure-result'):
            self.execute(known=False)

    def test_stale_global_revision_refuses_even_when_deployment_object_generation_matches(self):
        with self.assertRaisesRegex(WorkflowError, 'reflection-selected-signed-revision'):
            self.execute(wrong_revision=True)

    def test_unreaped_invocation_refuses(self):
        with self.assertRaisesRegex(WorkflowError, 'reflection-client-not-reaped'):
            self.execute(reaped=False)

    def test_selector_is_default_off_strict_bool_dotnet_only_before_any_effect(self):
        from tools import run_rust_capsule_workflow as workflow
        for options in ({'language': 'rust', 'dotnet_reflection': True}, {'language': 'dotnet', 'dotnet_reflection': 1},
                        {'language': 'dotnet', 'dotnet_reflection': True, 'captured_dependency_recovery': True}):
            with self.subTest(options=options), patch.object(workflow, 'fresh') as fresh, \
                    self.assertRaisesRegex(WorkflowError, 'authoring-dotnet-reflection-language'):
                workflow.run(None, None, None, None, **options)
            fresh.assert_not_called()


if __name__ == '__main__':
    unittest.main()
