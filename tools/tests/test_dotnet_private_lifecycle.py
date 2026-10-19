"""Pure source/protocol controls; actual managed/TLS/node campaign runs in Linux CI."""
import base64
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import dotnet_private_feed_fixture as fixture
from tools import qualify_dotnet_private_dependencies as qualification
from tools.build_snapshot import digest
from tools.phase2_operator_process import WorkflowError


class PrivateProtocol(unittest.TestCase):
    def test_actual_flat_container_authentication_and_transitive_package_are_bounded_and_redacted(self):
        payload = fixture.package('Outside.Example.Main', '1.0.0', 'PrivateMain', b'not-executed-dll', 'Outside.Example.Leaf')
        feed = fixture.Feed('https://127.0.0.1:9443', {('outside.example.main', '1.0.0'): payload}, 'private-sentinel')
        for authorization in ('', 'Basic wrong', 'credential-shaped-sentinel', '\u00e9', None):
            self.assertEqual(feed.response('/index.json', authorization), (401, b'authentication-required'))
        authorization = 'Basic ' + base64.b64encode(b'fixture:private-sentinel').decode()
        status, raw = feed.response('/index.json', authorization)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)['resources'], [{'@id': 'https://127.0.0.1:9443/flat/', '@type': 'PackageBaseAddress/3.0.0'}])
        self.assertEqual(feed.response('/flat/outside.example.main/index.json', authorization), (200, b'{"versions": ["1.0.0"]}'))
        self.assertEqual(feed.response('/flat/outside.example.main/1.0.0/outside.example.main.1.0.0.nupkg', authorization), (200, payload))
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            self.assertEqual(archive.read('lib/net10.0/PrivateMain.dll'), b'not-executed-dll')
            self.assertIn(b'id="Outside.Example.Leaf" version="[1.0.0]"', archive.read('Outside.Example.Main.nuspec'))
        public = json.dumps(feed.observations)
        for private in ('private-sentinel', authorization, '/flat/', 'credential-shaped-sentinel'):
            self.assertNotIn(private, public)
        self.assertTrue(all(set(row) == {'asset', 'authorized', 'status'} for row in feed.observations))

    def test_unknown_paths_never_get_package_bytes_and_request_budget_does_not_grow(self):
        feed = fixture.Feed('https://fixture.invalid', {('example', '1.0.0'): b'package'}, 'test-value')
        self.assertEqual(feed.response('/credential-shaped-private-path', feed.authorization), (404, b'not-found'))
        for _ in range(fixture.MAX_REQUESTS - 1):
            feed.response('/index.json', '')
        before = copy.deepcopy(feed.observations)
        with self.assertRaisesRegex(WorkflowError, 'peer-request-bound'):
            feed.response('/index.json', feed.authorization)
        self.assertEqual(feed.observations, before)

    def test_private_credential_scope_restores_absent_or_existing_caller_value(self):
        import os
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(fixture.TOKEN_SLOT, None)
            with fixture.credential('new-private-value'):
                self.assertEqual(os.environ[fixture.TOKEN_SLOT], 'new-private-value')
            self.assertNotIn(fixture.TOKEN_SLOT, os.environ)
            os.environ[fixture.TOKEN_SLOT] = 'previous-value'
            with self.assertRaisesRegex(RuntimeError, 'original'), fixture.credential(None):
                self.assertNotIn(fixture.TOKEN_SLOT, os.environ)
                raise RuntimeError('original')
            self.assertEqual(os.environ[fixture.TOKEN_SLOT], 'previous-value')

    def test_real_greeting_hook_is_exact_and_removal_restores_identical_original(self):
        from tools.dotnet_guest.project import create
        with tempfile.TemporaryDirectory() as temporary:
            app = create(Path(temporary) / 'app', 'greeting')
            original = (app / 'src/Main.cs').read_bytes()
            sdk = (app / 'sdk-lock.json').read_bytes()
            self.assertEqual(fixture.edit_source(app), original)
            self.assertIn(b'PrivateMain.Describe(text.Substring(14))', (app / 'src/Main.cs').read_bytes())
            self.assertIn(b'return $"Hello, {text}!"', (app / 'src/Main.cs').read_bytes())
            with self.assertRaisesRegex(WorkflowError, 'original-greeting-required'):
                fixture.edit_source(app)
            fixture.edit_source(app, original)
            self.assertEqual((app / 'src/Main.cs').read_bytes(), original)
            self.assertEqual((app / 'sdk-lock.json').read_bytes(), sdk)


class ActualSelectedGraph(unittest.TestCase):
    def test_failed_public_receipt_preserves_original_qualification_exception_identity(self):
        original = RuntimeError('private original remains private')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(qualification, 'prepared_inputs', side_effect=original), \
                    patch.object(qualification, 'write_json', side_effect=RecursionError('observer unavailable')):
                with self.assertRaises(RuntimeError) as caught:
                    qualification.qualify(root / 'unused', root / 'output', root / 'unused-tools')
            self.assertIs(caught.exception, original)

    def test_actual_library_producer_captures_transitive_reference_inside_each_owned_build(self):
        from tools.dotnet_guest.project import create
        seen, constructors = [], []
        class SourceOnlyCompiler:
            def __init__(self, tools, commands, vendor, *, offline, captured):
                self.commands, self.dotnet = commands, Path('never-executed-dotnet')
                self_outer.assertTrue(offline and captured)
                # Match the real Compiler -> stage() exclusive owned layout;
                # a second instance under the same parent must not be hidden.
                stage = commands.root.parent / 'captured-dotnet-tools'
                stage.mkdir()
                constructors.append(stage)

            def run(self, stage, executable, *arguments):
                self_outer.assertEqual(stage, 'private-pure-managed-library')
                source = Path(arguments[1]).parent
                self_outer.assertEqual(self.commands.root.name, 'leaf-1.0.0')
                self_outer.assertTrue(source.is_relative_to(self.commands.root.parent))
                self_outer.assertEqual(arguments[0], 'build')
                self_outer.assertEqual(arguments[4], '-p:RestoreConfigFile=' + str(source / 'nuget.config'))
                project = (source / 'Library.csproj').read_text()
                text = (source / 'Library.cs').read_text()
                role = 'Main' if 'PrivateMain' in text else 'Leaf'
                if role == 'Main':
                    self_outer.assertIn('<HintPath>references/PrivateLeaf.dll</HintPath>', project)
                    self_outer.assertEqual((source / 'references/PrivateLeaf.dll').read_bytes(), b'modeled-Leaf-dll')
                    self_outer.assertIn('PrivateLeaf.Prefix()', text)
                else:
                    self_outer.assertIn('LogicalName="private.text"', project)
                    self_outer.assertIn('Gr\u00fc\u00dfe', (source / 'text.txt').read_text(encoding='utf-8'))
                destination = source / 'bin/Release/net10.0'
                destination.mkdir(parents=True)
                (destination / ('Private' + role + '.dll')).write_bytes(('modeled-' + role + '-dll').encode())
                seen.append(role)

            def check_unchanged(self):
                pass
        self_outer = self
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = create(root / 'app', 'greeting')
            outside = root / 'outside'
            outside.mkdir()
            with patch.object(fixture, 'Compiler', SourceOnlyCompiler):
                payloads = fixture.libraries(outside, app, root / 'unused-tools', 'a' * 24)
            self.assertEqual(seen, ['Leaf', 'Main', 'Leaf', 'Main'])
            self.assertEqual(len(constructors), 1)
            self.assertEqual(len(payloads), 4)
            self.assertEqual({version for _name, version in payloads}, set(fixture.VERSIONS))

    def test_actual_original_digests_transitive_edge_and_no_extra_package_are_required(self):
        payloads = {('main', '1.0.0'): b'main-package', ('child', '1.0.0'): b'child-package'}
        rows = [{'id': name + '/1.0.0', 'dependencies': ['child/1.0.0'] if name == 'main' else [],
                 'role': 'application', 'original': {'digest': digest(raw), 'size': len(raw)}}
                for (name, _), raw in payloads.items()]
        lock = {'artifacts': rows}
        qualification.closed_graph(lock, payloads, 'main', 'child', '1.0.0')
        for edit in ('edge', 'original', 'extra', 'role'):
            changed = copy.deepcopy(lock)
            if edit == 'edge':
                changed['artifacts'][0]['dependencies'] = []
            elif edit == 'original':
                changed['artifacts'][0]['original']['digest'] = digest(b'foreign')
            elif edit == 'extra':
                changed['artifacts'].append({**rows[0], 'id': 'foreign/1.0.0'})
            else:
                changed['artifacts'][0]['role'] = 'build-tool'
            with self.subTest(edit=edit), self.assertRaises(WorkflowError):
                qualification.closed_graph(changed, payloads, 'main', 'child', '1.0.0')

    def test_prepared_products_use_actual_dotnet_sources_and_exact_five_binary_bytes(self):
        from tools.phase3_resource_identity import file_identity
        from tools.rust_capsule_project import canonical
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'native-binaries').mkdir()
            source = {'exact-current-dotnet-source': {'digest': digest(b'source'), 'size': 6}}
            raw = canonical(source)
            for filename in ('source-inputs.json', 'source-inputs-after.json'):
                (root / filename).write_bytes(raw)
            products = {}
            for name in qualification.PRODUCTS:
                path = root / 'native-binaries' / name.replace('/', '-')
                path.write_bytes(('not-executed-' + name).encode())
                products[name] = file_identity(path, 512 * 1024 * 1024)
            builds = {}
            for name in qualification.COMPANIONS:
                path = root / 'builds' / name
                path.mkdir(parents=True)
                builds[name] = {'name': name, 'sourceDigest': digest(name.encode())}
                (path / 'BUILD-COMPLETE.json').write_bytes(canonical(builds[name]))
            receipt = {'status': 'passed', 'applicationDependencies': {}, 'sourceIdentityDigest': digest(raw),
                       'binaries': products, 'builds': builds}
            (root / 'qualification.json').write_bytes(canonical(receipt))
            with patch.object(qualification, 'inputs', return_value=source) as selected:
                qualification.prepared_inputs(root)
                selected.assert_called_with('dotnet')
                (root / 'native-binaries/latentd').write_bytes(b'changed')
                with self.assertRaisesRegex(WorkflowError, 'native-products-changed'):
                    qualification.prepared_inputs(root)


class ActualContainmentReceipt(unittest.TestCase):
    def exercise(self, receipt, *, oversized=False):
        from types import SimpleNamespace
        from tools.rust_capsule_project import canonical
        original = RuntimeError('source-only signing boundary')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / 'artifact'
            artifact.mkdir()
            OfflineBuildEvidence.artifact(artifact, b'not-executed')
            path = artifact / 'compiler-containment.json'
            path.write_bytes(canonical(receipt))
            if oversized:
                with path.open('r+b') as stream:
                    stream.truncate(32 * 1024 * 1024 + 1)
            commands = SimpleNamespace(run=unittest.mock.Mock(side_effect=original))
            with patch.object(qualification, 'Commands', return_value=commands), \
                    patch.object(qualification, 'prepared_inputs', return_value=({}, {}, {
                        name: root / name.replace('/', '-') for name in qualification.PRODUCTS})), \
                    patch.object(qualification, 'capture', return_value=([(root / 'app', {}, '1.0.0', False)], {})), \
                    patch.object(qualification, 'source_files', return_value={'source': b'unchanged'}), \
                    patch.object(qualification.dependencies, 'verify_inputs', return_value=SimpleNamespace(lock={})), \
                    patch.object(qualification, 'build', return_value=artifact) as build:
                try:
                    qualification.qualify(root / 'prepared', root / 'output', root / 'tools')
                except Exception as error:
                    return error, original, build.call_count, commands.run.call_count
                self.fail('source-only signing boundary was not reached')

    def test_real_post_build_reader_accepts_producer_receipt_above_fixture_default(self):
        receipt = {'network': 'denied', 'credentials': 'not-inherited', 'distributions': {'identity': 'a' * (5 * 1024 * 1024)}}
        error, original, builds, signs = self.exercise(receipt)
        self.assertIs(error, original)
        self.assertEqual((builds, signs), (2, 1))

    def test_real_post_build_reader_retains_exact_producer_byte_ceiling(self):
        error, _original, builds, signs = self.exercise({}, oversized=True)
        self.assertIsInstance(error, ValueError)
        self.assertEqual((builds, signs), (1, 0))

    def test_large_receipt_does_not_weaken_network_or_credential_refusal(self):
        for field, value in (('network', 'allowed'), ('credentials', 'inherited')):
            receipt = {'network': 'denied', 'credentials': 'not-inherited', 'distributions': {'identity': 'a' * (5 * 1024 * 1024)}}
            receipt[field] = value
            with self.subTest(field=field):
                error, _original, builds, signs = self.exercise(receipt)
                self.assertIsInstance(error, WorkflowError)
                self.assertEqual(str(error), 'private-NuGet-offline-compiler-not-contained')
                self.assertEqual((builds, signs), (1, 0))


class ActualSignedProbe(unittest.TestCase):
    def execute(self, *, removed=False, wrong_revision=False):
        from tools import rust_capsule_node as node
        value = {'nonce': 'a' * 24, 'version': '2.0.0', 'removed': removed}
        revision = {'publicationId': 'intended', 'routeGeneration': '35', 'releaseDigest': digest(b'component'), 'revisionId': 'revision'}
        target = {'generation': '1', 'publication': 'intended'}
        calls = []
        def call(_client, selected_target, template, function, arguments, activation):
            self.assertIs(selected_target, target)
            self.assertEqual((template, function), ('greeting', 'greet'))
            text = arguments[0] if removed else arguments[0].removeprefix(fixture.PREFIX)
            expected = 'Hello, ' + text + '!' if removed else fixture.expected(value['nonce'], value['version'], text)
            calls.append(arguments)
            return {'exitCode': 0, 'decoded': [{'ok': expected}], 'activation': activation, 'processReaped': True,
                'response': {'outcomeKnown': True, 'data': {'resolvedRevision': {**revision, 'routeGeneration': '1'} if wrong_revision else revision}}}
        result = {'invocations': [], 'samples': []}
        with patch.object(node, 'selected_revision', return_value=revision), patch.object(node, 'call', side_effect=call), \
                patch.object(node, 'sample', return_value={'idle': True}):
            fixture.probe(object(), target, object(), result, 5, value)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(result['invocations']), 3)
        self.assertEqual(result['capturedDotnetPrivate']['status'], 'passed')
        self.assertTrue(all(row['freshState'] and row['actualSignedTarget'] for row in result['capturedDotnetPrivate']['cases']))

    def test_private_resources_and_transitive_calls_bind_global_signed_revision_not_object_generation(self):
        self.execute()

    def test_removed_phase_uses_ordinary_greeting_without_a_private_assembly(self):
        self.execute(removed=True)

    def test_wrong_or_stale_signed_revision_refuses_even_with_the_expected_value(self):
        with self.assertRaisesRegex(WorkflowError, 'signed-target'):
            self.execute(wrong_revision=True)

    def test_malformed_probe_refuses_before_any_node_call(self):
        from tools import rust_capsule_node as node
        for value in (None, {}, {'nonce': 'secret-shaped-value', 'version': '1.0.0', 'removed': False},
                      {'nonce': 'a' * 24, 'version': '1.0.0', 'removed': 1},
                      {'nonce': 'a' * 24, 'version': '3.0.0', 'removed': False}):
            with self.subTest(value=value), patch.object(node, 'selected_revision') as selected, self.assertRaises(WorkflowError):
                fixture.probe(object(), {}, object(), {}, 5, value)
            selected.assert_not_called()

    def test_private_selector_is_default_off_strict_bool_and_only_dotnet_before_any_effect(self):
        from tools import run_rust_capsule_workflow as workflow
        for options in ({'language': 'rust', 'captured_dotnet_private': True},
                        {'language': 'dotnet', 'captured_dotnet_private': 1},
                        {'language': 'dotnet', 'captured_dotnet_private': True, 'captured_dependency_recovery': True}):
            with self.subTest(options=options), patch.object(workflow, 'fresh') as fresh, self.assertRaisesRegex(WorkflowError, 'private-NuGet-language'):
                workflow.run(None, None, None, None, **options)
            fresh.assert_not_called()


class OfflineBuildEvidence(unittest.TestCase):
    @staticmethod
    def artifact(path, component=b'owned initial component'):
        from tools.rust_capsule_project import canonical
        path.mkdir(parents=True, exist_ok=True)
        selected = {'source-inputs.json': b'captured graph and selected source',
                    'recipe-inputs.json': b'captured compiler recipe',
                    'compiler-inputs.json': b'pinned native tools and runtime adapters',
                    'nuget-build-inputs.json': b'locked package and asset selection'}
        for name, raw in selected.items(): (path/name).write_bytes(raw)
        (path/'component.wasm').write_bytes(component)
        outputs = {'Generated.cs': {'digest': digest(b'generated bindings'), 'size': 18}}
        binding = digest(json.dumps(outputs, sort_keys=True).encode())
        profile = {'schemaVersion': 'latent.dotnet.runtime.v1', 'profile': 'closed',
                   'declaredImports': [], 'emittedImports': [],
                   'adapter': {'name': 'closed-runtime', 'digest': digest(b'adapter'), 'size': 7}}
        (path/'bindings.json').write_bytes(canonical({'bindings': {'outputs': outputs},
            'filesDigest': binding, 'runtimeProfile': profile}))
        parameters = {'compiler': 'native-aot-llvm', 'bindings': 'wit-bindgen-csharp', 'language': 'csharp',
                      'target': 'wasi-wasm', 'runtime': 'native-aot', 'locked': True, 'ambientWasi': False}
        observation = {'componentDigest': digest(component), 'componentSize': len(component), 'parameters': parameters,
            'materials': [{'name': label, 'digest': digest(selected[name]), 'size': len(selected[name])}
                for name, label in zip(selected, ('source-snapshot', 'build-recipe', 'compiler-inputs', 'nuget-build-inputs'))]}
        raw = canonical(observation)
        (path/'build-observation.json').write_bytes(raw)
        marker = {'componentDigest': digest(component), 'observationDigest': digest(raw),
                  'sourceDigest': digest(selected['source-inputs.json']), 'sdkBindingDigest': binding}
        (path/'BUILD-COMPLETE.json').write_bytes(canonical(marker))
        (path/'compiler-containment.json').write_bytes(canonical({'network': 'denied', 'credentials': 'not-inherited'}))
        return marker

    def test_actual_pair_binds_two_distinct_outputs_without_claiming_reproducibility(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); a, b = root/'a', root/'b'
            self.artifact(a); self.artifact(b, b'owned rebuilt component with private debug identity')
            result = qualification.offline_pair(a, b)
            self.assertFalse(result['rawBytesIdentical'])
            self.assertEqual(result['reproducibility'], 'not-claimed')
            self.assertEqual(len(result['components']), 2)
            self.assertNotEqual(result['components'][0]['sha256'], result['components'][1]['sha256'])

    def test_source_recipe_compiler_graph_binding_runtime_and_containment_drift_still_refuse(self):
        from tools.rust_capsule_project import canonical
        for mode in ('source-inputs.json', 'recipe-inputs.json', 'compiler-inputs.json', 'nuget-build-inputs.json',
                     'binding', 'runtime', 'network', 'credentials', 'observation', 'component'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); a, b = root/'a', root/'b'; self.artifact(a); self.artifact(b, b'rebuilt')
                if mode.endswith('.json'): (b/mode).write_bytes(b'changed')
                elif mode in ('binding', 'runtime'):
                    value = json.loads((b/'bindings.json').read_bytes())
                    if mode == 'binding': value['filesDigest'] = digest(b'wrong binding')
                    else: value['runtimeProfile']['profile'] = 'different runtime'
                    (b/'bindings.json').write_bytes(canonical(value))
                elif mode in ('network', 'credentials'):
                    (b/'compiler-containment.json').write_bytes(canonical({
                        'network': 'allowed' if mode == 'network' else 'denied',
                        'credentials': 'inherited' if mode == 'credentials' else 'not-inherited'}))
                elif mode == 'observation': (b/'build-observation.json').write_bytes(b'{}')
                else: (b/'component.wasm').write_bytes(b'tampered actual output')
                with self.assertRaises((WorkflowError, KeyError)):
                    qualification.offline_pair(a, b)

    def test_actual_qualifier_signs_and_executes_both_initial_outputs_and_preserves_second_node_failure(self):
        from types import SimpleNamespace
        from tools.rust_capsule_project import canonical
        for fail_rebuild in (False, True):
            with self.subTest(fail_rebuild=fail_rebuild), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); commands = SimpleNamespace(deadline=float('inf'), records=[])
                original = RuntimeError('owned rebuilt node failed')
                signed, executed = [], []
                def sign(stage, _tool, command, target, artifact, *companions):
                    self.assertEqual(command, 'demo-sign'); signed.append(artifact.name); target.mkdir()
                commands.run = sign
                def build(app, output, *args, **kwargs):
                    self.assertTrue(kwargs['offline']); self.artifact(output, output.name.encode()); return output
                def node(_cli, _node, fixture, output, **kwargs):
                    self.assertTrue(kwargs['captured_dotnet_private']); self.assertTrue(kwargs['noncrypto_entropy'])
                    executed.append(output.name)
                    if fail_rebuild and output.name == 'node-initial-rebuild': raise original
                    output.mkdir(); (output/'workflow.json').write_bytes(canonical({'status': 'passed'}))
                    return {'status': 'passed', 'capturedDotnetPrivate': {'status': 'passed', 'cases': [0, 1, 2]}}
                products = {name: root/name.replace('/', '-') for name in qualification.PRODUCTS}
                phases = [(root/'app', {}, version, removed) for version, removed in
                          (('1.0.0', False), ('2.0.0', False), ('2.0.0', True))]
                with patch.object(qualification, 'Commands', return_value=commands), \
                     patch.object(qualification, 'prepared_inputs', return_value=({}, {'binaries': {}, 'sourceIdentityDigest': digest(b'{}')}, products)), \
                     patch.object(qualification, 'capture', return_value=(phases, {'nonce': 'a'*24})), \
                     patch.object(qualification, 'source_files', return_value={'source': b'unchanged'}), \
                     patch.object(qualification.dependencies, 'verify_inputs', return_value=SimpleNamespace(lock={})), \
                     patch.object(qualification, 'build', side_effect=build), \
                     patch.object(qualification, 'node_workflow', side_effect=node), \
                     patch.object(qualification, 'inputs', return_value={}):
                    if fail_rebuild:
                        with self.assertRaises(RuntimeError) as raised:
                            qualification.qualify(root/'prepared', root/'output', root/'tools')
                        self.assertIs(raised.exception, original)
                        self.assertEqual(signed, ['build-0', 'offline-rebuild'])
                        self.assertEqual(executed, ['node-0', 'node-initial-rebuild'])
                    else:
                        result = qualification.qualify(root/'prepared', root/'output', root/'tools')
                        self.assertEqual(signed, ['build-0', 'offline-rebuild', 'build-1', 'build-2'])
                        self.assertEqual(executed, ['node-0', 'node-initial-rebuild', 'node-1', 'node-2'])
                        self.assertEqual(len(result['nodeReceipts']), 4)
                        self.assertTrue(result['offlineRebuild']['separatelySignedAndExecuted'])
                        self.assertFalse(result['offlineRebuild']['rawBytesIdentical'])


if __name__ == '__main__':
    unittest.main()
