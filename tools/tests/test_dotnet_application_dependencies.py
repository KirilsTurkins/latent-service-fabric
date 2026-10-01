"""NuGet selection and MSBuild execution boundaries, independent of catalogues."""
import base64
import copy
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
import os
import shutil
import sys

from tools.application_dependency_store import DependencyError
from tools.dotnet_application_dependencies import analyze, condition, declarations, executable_resources, feed_config, managed_image, selection
from tools.dotnet_guest.project import create
from tools.rust_capsule_project import snapshot


HASH = base64.b64encode(b'\x01' * 64).decode()


class NugetDependencies(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.files = snapshot(create(self.root / 'application', 'greeting'))

    def extend(self, item):
        files = dict(self.files)
        files['Capsule.csproj'] = files['Capsule.csproj'].replace(b'</Project>', b'<ItemGroup>' + item + b'</ItemGroup></Project>')
        return files

    def native(self):
        sdk_row = {'type': 'Direct', 'resolved': '1.0.0', 'contentHash': HASH}
        baseline = {'version': 1, 'dependencies': {'net10.0': {'Maintained.Compiler': sdk_row}}}
        direct = {'type': 'Direct', 'resolved': '2.0.0', 'contentHash': HASH}
        child = {'type': 'Transitive', 'resolved': '3.0.0', 'contentHash': HASH}
        lock = {'version': 1, 'dependencies': {'net10.0': {'Maintained.Compiler': sdk_row, 'Outside.Library': direct, 'Transitive.Code': child}, 'net10.0/wasi-wasm': {}}}
        targets = {'Maintained.Compiler/1.0.0': {}, 'Outside.Library/2.0.0': {'dependencies': {'Transitive.Code': '[3.0.0]'}, 'compile': {'lib/net10.0/Outside.dll': {}}}, 'Transitive.Code/3.0.0': {}}
        libraries = {key: {'type': 'package', 'path': key.lower(), 'sha512': HASH, 'files': ['lib/net10.0/Outside.dll'] if key.startswith('Outside') else []} for key in targets}
        assets = {'version': 3, 'targets': {'net10.0': targets, 'net10.0/wasi-wasm': targets}, 'libraries': libraries}
        return lock, assets, baseline, declarations(self.files)

    def test_native_package_and_resource_declarations_preserve_sdk(self):
        files = self.extend(b'<PackageReference Include="Outside.Library" Version="[2.0.0]" /><EmbeddedResource Include="resources/greeting.txt" LogicalName="outside.greeting" />')
        files['resources/greeting.txt'] = b'Hello, '
        result = declarations(files)
        self.assertEqual(result['packages'][0]['attributes']['Include'], 'Outside.Library')
        self.assertEqual(result['resources'][0]['size'], 7)
        self.assertEqual(result['resources'][0]['attributes']['LogicalName'], 'outside.greeting')
        self.assertEqual(self.files['vendor/lsf/sdk/dotnet-guest/probes/smoke/Smoke.csproj'], files['vendor/lsf/sdk/dotnet-guest/probes/smoke/Smoke.csproj'])

    def test_application_import_task_and_property_functions_never_evaluate(self):
        for item in (b'<Import Project="/etc/passwd" />', b'<Target Name="Restore"><Exec Command="curl secret" /></Target>',
                     b'<PackageReference Include="Outside" Version="$([System.IO.File]::ReadAllText(\'secret\'))" />'):
            with self.subTest(item=item), self.assertRaises(DependencyError):
                declarations(self.extend(item))

    def test_supported_target_conditions_are_exact_and_other_evaluation_is_denied(self):
        selected = selection()
        self.assertTrue(condition("'$(TargetFramework)' == 'net10.0' And '$(RuntimeIdentifier)' == 'wasi-wasm'", selected))
        self.assertFalse(condition("'$(RuntimeIdentifier)' == 'linux-x64'", selected))
        for text in ('Exists(\'/etc/passwd\')', "'$(UserProfile)' != ''", '$([System.Environment]::GetEnvironmentVariable(\'TOKEN\'))'):
            with self.assertRaisesRegex(DependencyError, 'condition-not-reviewed'):
                condition(text, selected)

    def test_sdk_compiler_properties_cannot_be_overridden_by_application(self):
        for before, after in ((b'<AllowUnsafeBlocks>true', b'<AllowUnsafeBlocks>false'), (b'World="service"', b'World="other"')):
            with self.assertRaises(DependencyError):
                declarations({**self.files, 'Capsule.csproj': self.files['Capsule.csproj'].replace(before, after)})

    def test_native_transitive_closure_is_selected_without_catalogue(self):
        result = analyze(*self.native())
        row = next(row for row in result['packages'] if row['package'] == 'outside.library')
        self.assertEqual({value['id'] for value in row['dependencies']}, {'transitive.code/3.0.0'})
        self.assertIn('lib/net10.0/Outside.dll', row['targets']['net10.0']['compile'])

    def test_missing_transitive_and_changed_sdk_hash_fail(self):
        lock, assets, baseline, declared = self.native()
        del assets['targets']['net10.0']['Transitive.Code/3.0.0']
        with self.assertRaisesRegex(DependencyError, 'not-closed'):
            analyze(lock, assets, baseline, declared)
        lock, assets, baseline, declared = self.native()
        lock['dependencies']['net10.0']['Maintained.Compiler'] = {**lock['dependencies']['net10.0']['Maintained.Compiler'], 'contentHash': base64.b64encode(b'\x02' * 64).decode()}
        with self.assertRaisesRegex(DependencyError, 'sdk-compiler-runtime-lock-mutated'):
            analyze(lock, assets, baseline, declared)

    def test_analyzer_and_build_assets_are_executable_inputs(self):
        lock, assets, baseline, declared = self.native()
        assets['libraries']['Outside.Library/2.0.0']['files'] += ['build/net10.0/Outside.targets', 'analyzers/dotnet/cs/Outside.dll']
        assets['targets']['net10.0']['Outside.Library/2.0.0']['build'] = {'build/net10.0/Outside.targets': {}}
        result = analyze(lock, assets, baseline, declared)
        row = next(row for row in result['packages'] if row['package'] == 'outside.library')
        self.assertEqual(row['executableAssets'], ['analyzers/dotnet/cs/Outside.dll', 'build/net10.0/Outside.targets'])

    def test_unsafe_native_asset_paths_and_wrong_profiles_fail(self):
        lock, assets, baseline, declared = self.native()
        assets['targets']['net10.0']['Outside.Library/2.0.0']['runtime'] = {'../../private.dll': {}}
        with self.assertRaises(DependencyError):
            analyze(lock, assets, baseline, declared)
        with self.assertRaisesRegex(DependencyError, 'not-installed'):
            selection({'runtimeProfile': 'native-clr'})
        with self.assertRaises(DependencyError):
            managed_image(b'MZ' + b'\0' * 256)

    def test_private_feed_policy_receipt_excludes_location_and_credentials(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {'LSF_TEST_NUGET_AUTH': 'private-test-value'}):
            config, receipt = feed_config({'sources': [{'name': 'private', 'url': 'https://feed.example.test/index.json', 'patterns': ['Outside.*'],
                'authorizationEnv': 'LSF_TEST_NUGET_AUTH'}]}, self.root, self.files['vendor/lsf/sdk/dotnet-guest/nuget.config'])
        self.assertIn(b'private-test-value', config)
        public = json.dumps(receipt)
        self.assertNotIn('private-test-value', public)
        self.assertNotIn('feed.example.test', public)
        mapping = ET.fromstring(config).find('packageSourceMapping')
        self.assertEqual(mapping.find("packageSource[@key='private']/package").attrib['pattern'], 'Outside.*')

    def test_private_feed_invalid_credential_and_endpoint_fail_without_fallback(self):
        from unittest.mock import patch
        baseline = self.files['vendor/lsf/sdk/dotnet-guest/nuget.config']
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(DependencyError, 'credential-missing'):
            feed_config({'sources': [{'name': 'private', 'url': 'https://feed.example.test/index.json',
                'authorizationEnv': 'LSF_REQUIRED_NUGET_CREDENTIAL'}]}, self.root, baseline)
        for endpoint in ('http://feed.example.test/index.json', 'https://user:password@feed.example.test/index.json',
                         'https://feed.example.test/index.json?credential=value'):
            with self.subTest(endpoint=endpoint), self.assertRaisesRegex(DependencyError, 'endpoint-invalid'):
                feed_config({'sources': [{'name': 'private', 'url': endpoint}]}, self.root, baseline)

    def test_embedded_resources_cannot_read_absolute_or_uncaptured_files(self):
        for name in (b'/etc/passwd', b'../outside.txt', b'resources/absent.txt'):
            with self.assertRaises(DependencyError):
                declarations(self.extend(b'<EmbeddedResource Include="' + name + b'" />'))

    def test_resx_processing_is_an_explicit_executable_input(self):
        files = self.extend(b'<EmbeddedResource Include="resources/custom.resx" LogicalName="outside.custom" />')
        files['resources/custom.resx'] = b'<root />'
        specs = executable_resources(declarations(files), files)
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0]['role'], 'build-tool')
        self.assertEqual(specs[0]['metadata']['source'], 'resources/custom.resx')
        changed = {**files, 'resources/custom.resx': b'<root><data /></root>'}
        with self.assertRaisesRegex(DependencyError, 'preimage-mismatch'):
            executable_resources(declarations(files), changed)

    def test_nuget_standard_archive_metadata_preserves_safe_brackets(self):
        from tools.application_dependency_store import archive_files
        import io
        import zipfile
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('[Content_Types].xml', b'<Types />')
            archive.writestr('_rels/.rels', b'<Relationships />')
        self.assertEqual(set(archive_files(output.getvalue(), 'zip')), {'[Content_Types].xml', '_rels/.rels'})
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('../[Content_Types].xml', b'outside')
        with self.assertRaises(DependencyError):
            archive_files(output.getvalue(), 'zip')

    def test_composer_profile_rejects_stale_selection_and_changed_binary(self):
        from tools.dotnet_guest.composer import selection as composer_selection, observed
        from tools.rust_capsule_project import ROOT
        selected = composer_selection(ROOT / 'sdk/dotnet-guest')
        sdk = self.root / 'sdk'
        sdk.mkdir()
        selected['version'] = '0.10.0'
        (sdk / 'component-composer.json').write_text(json.dumps(selected))
        with self.assertRaisesRegex(ValueError, 'unreviewed'):
            composer_selection(sdk)
        tools = self.root / 'tools/component-composer'
        tools.mkdir(parents=True)
        (tools / 'wac').write_bytes(b'changed composer')
        with self.assertRaisesRegex(ValueError, 'differs'):
            observed(tools.parent, ROOT / 'sdk/dotnet-guest')

    def test_namespace_argument_transport_preserves_literals_and_denies_mutation(self):
        if sys.platform != 'linux' or not shutil.which('bwrap'):
            if os.environ.get('LSF_REQUIRE_COMPILER_ISOLATION') == '1':
                self.fail('required Linux namespace profile unavailable')
            self.skipTest('Linux namespace profile unavailable')
        from tools.dotnet_compiler_isolation import DotnetIsolation
        from tools.build_process import run_bounded_result
        workspace = self.root / 'workspace with spaces;literal'
        workspace.mkdir()
        distribution = workspace / 'compiler'
        distribution.mkdir()
        shell = distribution / 'shell'
        shutil.copyfile(Path(shutil.which('sh')).resolve(), shell)
        shell.chmod(0o700)
        isolated = DotnetIsolation(workspace,
            {name: shell for name in ('shell', 'dotnet', 'python', 'wasm-tools', 'wit-bindgen')}, {'sdk': distribution})
        for index in range(80):
            path = workspace / ('input ' + str(index))
            path.write_bytes(b'captured')
            isolated.protect_inputs(path)
        literal = 'literal-$(touch /tmp/should-never-run)'
        command = isolated.wrap(shell, ['-c', 'printf %s "$1"', 'sdk-control', literal], workspace, {})
        self.assertLessEqual(len(command), 256)
        result = run_bounded_result(command, workspace, {'PATH': os.defpath}, 15, 16384)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stdout.decode(), literal)
        isolated.check_unchanged()
        argument_file = next(iter(isolated.argument_files))
        argument_file.write_bytes(b'changed')
        with self.assertRaisesRegex(DependencyError, 'namespace-arguments-mutated'):
            isolated.check_unchanged()


class NativeAotRuntimeCoverage(unittest.TestCase):
    def graph(self, *, export=False):
        interfaces = [{'name': 'streams', 'package': 0, 'types': {'input-stream': 0},
                       'functions': {'[method]input-stream.read': {'name': '[method]input-stream.read'}}}]
        return {'worlds': [{'name': 'root', 'package': 1,
                           'imports': {} if export else {'streams': {'interface': {'id': 0}}},
                           'exports': {'streams': {'interface': {'id': 0}}} if export else {}}],
                'interfaces': interfaces, 'types': [{'kind': 'resource', 'name': 'input-stream'}],
                'packages': [{'name': 'wasi:io@0.2.6'}, {'name': 'test:component'}]}

    def test_partial_resource_exports_report_exact_missing_members(self):
        from tools.dotnet_guest.compatibility import coverage, findings
        raw, adapter = self.graph(), self.graph(export=True)
        adapter['interfaces'][0]['functions'] = {}
        adapter['interfaces'][0]['types'] = {}
        result = coverage(raw, adapter)
        self.assertEqual(result['gaps'], [
            {'interface': 'wasi:io/streams@0.2.6', 'kind': 'types', 'symbol': 'input-stream'},
            {'interface': 'wasi:io/streams@0.2.6', 'kind': 'functions', 'symbol': '[method]input-stream.read'}])
        self.assertEqual({row['classification'] for row in findings(result)}, {'missing-runtime-port'})
        self.assertEqual(result['authority'], 'none')

    def test_missing_http_is_not_a_clock_grant_or_catalogue_decision(self):
        from tools.dotnet_guest.compatibility import coverage, findings
        raw = self.graph()
        raw['packages'][0]['name'] = 'wasi:http@0.2.0'
        raw['interfaces'][0]['name'] = 'types'
        result = coverage(raw, self.graph(export=True))
        self.assertEqual(result['gaps'], [{'interface': 'wasi:http/types@0.2.0', 'kind': 'interface'}])
        self.assertEqual(findings(result)[0]['ownerIssue'], 693)

    def test_present_names_do_not_claim_signature_or_runtime_qualification(self):
        from tools.dotnet_guest.compatibility import coverage
        raw, adapter = self.graph(), self.graph(export=True)
        adapter['interfaces'][0]['functions']['[method]input-stream.read']['params'] = [{'name': 'changed', 'type': 'string'}]
        result = coverage(raw, adapter)
        self.assertEqual(result['gaps'], [])
        self.assertEqual(result['analysisCompleteness'], 'required-member-names')
        self.assertEqual(result['authority'], 'none')

    def test_malformed_world_tables_type_indices_and_function_names_fail(self):
        from tools.dotnet_guest.compatibility import coverage
        for mutation in ('index', 'type', 'function', 'table', 'worlds'):
            raw = self.graph()
            if mutation == 'index':
                raw['worlds'][0]['imports']['streams']['interface']['id'] = 99
            elif mutation == 'type':
                raw['interfaces'][0]['types']['input-stream'] = True
            elif mutation == 'function':
                raw['interfaces'][0]['functions']['[method]input-stream.read']['name'] = 'other'
            elif mutation == 'table':
                raw['interfaces'][0]['functions'] = []
            else:
                raw['worlds'].append(raw['worlds'][0])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                coverage(raw, self.graph(export=True))

    def test_failure_report_rechecks_raw_bytes_and_does_not_invent_source_identity(self):
        from tools.build_snapshot import canonical, digest
        from tools.dotnet_guest.compatibility import coverage, retain_failure, PROFILE
        from tools.guest_compatibility import read as read_report
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            raw, adapter = self.graph(), self.graph(export=True)
            adapter['interfaces'][0]['functions'] = {}
            raw_graph, adapter_graph = canonical(raw), canonical(adapter)
            (output / 'native-aot-raw.wit.json').write_bytes(raw_graph)
            (output / 'closed-runtime-adapter.wit.json').write_bytes(adapter_graph)
            (output / 'native-aot-raw.wasm').write_bytes(b'retained-compiler-input')
            receipt = coverage(raw, adapter)
            receipt.update(schemaVersion='lsf.dotnet.runtime.coverage.v1', runtimeProfile=PROFILE,
                rawComponentDigest=digest(b'retained-compiler-input'), runtimeAdapterDigest=digest(b'adapter'),
                rawWitDigest=digest(raw_graph), runtimeWitDigest=digest(adapter_graph))
            (output / 'closed-runtime-coverage.json').write_bytes(canonical(receipt))
            retain_failure(output)
            self.assertFalse((output / 'compatibility-report.json').exists())
            (output / 'source-inputs.json').write_bytes(b'reviewed-source-inventory')
            retain_failure(output)
            report = read_report((output / 'compatibility-report.json').read_bytes())
            self.assertEqual(report['status'], 'blocked')
            self.assertEqual(report['sourceDigest'], digest(b'reviewed-source-inventory'))
            self.assertEqual(report['componentDigest'], digest(b'retained-compiler-input'))
            (output / 'native-aot-raw.wasm').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'stale-receipt'):
                retain_failure(output)

    def test_actual_raw_failure_retention_preserves_shared_failure_report(self):
        from tools.build_snapshot import canonical, digest
        from tools.dotnet_guest.compatibility import coverage, retain_failure, PROFILE
        from tools.guest_compatibility import read as read_report
        from tools.guest_compatibility_build import failure_report
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            raw, adapter = self.graph(), self.graph(export=True)
            adapter['interfaces'][0]['functions'] = {}
            raw_graph, adapter_graph = canonical(raw), canonical(adapter)
            raw_bytes, source = b'retained-compiler-input', b'reviewed-source-inventory'
            (output / 'native-aot-raw.wit.json').write_bytes(raw_graph)
            (output / 'closed-runtime-adapter.wit.json').write_bytes(adapter_graph)
            (output / 'native-aot-raw.wasm').write_bytes(raw_bytes)
            (output / 'source-inputs.json').write_bytes(source)
            receipt = coverage(raw, adapter)
            receipt.update(schemaVersion='lsf.dotnet.runtime.coverage.v1', runtimeProfile=PROFILE,
                rawComponentDigest=digest(raw_bytes), runtimeAdapterDigest=digest(b'adapter'),
                rawWitDigest=digest(raw_graph), runtimeWitDigest=digest(adapter_graph))
            (output / 'closed-runtime-coverage.json').write_bytes(canonical(receipt))
            failure_report(output, 'dotnet', 'compile')
            shared = (output / 'compatibility-report.json').read_bytes()
            retain_failure(output)
            self.assertEqual((output / 'compatibility-report.json').read_bytes(), shared)
            report = read_report((output / 'compatibility-raw-report.json').read_bytes())
            self.assertEqual(report['sourceDigest'], digest(source))
            self.assertEqual(report['componentDigest'], digest(raw_bytes))
            self.assertEqual(report['findings'][0]['classification'], 'missing-runtime-port')
            self.assertEqual(report['status'], 'blocked')
            retained = (output / 'compatibility-raw-report.json').read_bytes()
            (output / 'native-aot-raw.wasm').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'stale-receipt'):
                retain_failure(output)
            self.assertEqual((output / 'compatibility-report.json').read_bytes(), shared)
            self.assertEqual((output / 'compatibility-raw-report.json').read_bytes(), retained)


class NugetGeneratedOutputs(unittest.TestCase):
    def approval(self):
        from types import SimpleNamespace
        from tools.build_snapshot import canonical, digest
        specification = {'inputIdentity': {'manifestDigest': digest(b'original manifest'),
            'lockDigest': digest(b'original executable lock')}, 'recipeDigest': digest(b'compiler recipe'),
            'compilerInputsDigest': digest(b'captured compiler and namespace')}
        return SimpleNamespace(identity=digest(canonical(specification)), specification=specification)

    def compiler(self, output, approval, run):
        from types import SimpleNamespace
        from tools.dotnet_guest.compiler import Compiler
        compiler = Compiler.__new__(Compiler)
        compiler.commands = SimpleNamespace(output=output)
        compiler.dotnet, compiler.wasi_sdk = Path('/captured/dotnet'), Path('/captured/wasi-sdk')
        compiler.application_closure, compiler.executable_approval = object(), approval
        compiler.run = run
        return compiler

    def test_native_aot_failure_retains_real_generated_bytes_after_temporary_cleanup(self):
        from tools.dotnet_guest.outputs import verify
        with tempfile.TemporaryDirectory() as retained:
            output, approval = Path(retained), self.approval()
            failure = ValueError('original-NativeAOT-command-failure')
            with tempfile.TemporaryDirectory() as temporary:
                compiled = Path(temporary)
                source = compiled / 'generator-outputs/Actual.Generator/Payload.g.cs'

                def run(stage, *arguments):
                    self.assertEqual(stage, 'native-aot')
                    self.assertIn('-p:EmitCompilerGeneratedFiles=true', arguments)
                    source.parent.mkdir(parents=True)
                    source.write_bytes(b'public partial class ActualPayload {}')
                    raise failure

                compiler = self.compiler(output, approval, run)
                with self.assertRaises(ValueError) as caught:
                    compiler.native_aot(compiled / 'project', compiled, compiled / 'wit-bindgen')
                self.assertIs(caught.exception, failure)
                self.assertFalse((output / 'BUILD-COMPLETE.json').exists())
            self.assertFalse(source.exists())
            receipt = verify(output, approval, compiler_command_succeeded=False)
            self.assertFalse(receipt['compilerCommandSucceeded'])
            self.assertEqual((output / 'executable-input-outputs/Actual.Generator/Payload.g.cs').read_bytes(),
                             b'public partial class ActualPayload {}')
            with self.assertRaisesRegex(DependencyError, 'stale-receipt'):
                verify(output, approval)

    def test_successful_compiler_capture_is_bound_before_component_exists(self):
        from tools.dotnet_guest.outputs import verify
        with tempfile.TemporaryDirectory() as temporary:
            root, approval = Path(temporary), self.approval()
            output, compiled = root / 'retained', root / 'compiled'
            output.mkdir()
            compiled.mkdir()

            def run(stage, *arguments):
                generated = compiled / 'generator-outputs/Payload.g.cs'
                generated.parent.mkdir()
                generated.write_bytes(b'public partial class ActualPayload {}')

            self.compiler(output, approval, run).native_aot(compiled / 'project', compiled, compiled / 'wit-bindgen')
            receipt = verify(output, approval, source=compiled / 'generator-outputs')
            self.assertTrue(receipt['compilerCommandSucceeded'])
            self.assertEqual(receipt['captureBoundary'], 'native-aot-process-reaped-before-component-composition')
            self.assertFalse((output / 'component.wasm').exists())
            self.assertFalse((output / 'BUILD-COMPLETE.json').exists())
            self.assertEqual(verify(output, approval), receipt)

    def test_retained_or_compiled_generated_byte_changes_are_rejected(self):
        from tools.dotnet_guest.outputs import capture, verify
        with tempfile.TemporaryDirectory() as temporary:
            root, approval = Path(temporary), self.approval()
            source, output = root / 'generated', root / 'retained'
            source.mkdir()
            output.mkdir()
            (source / 'Payload.g.cs').write_bytes(b'approved generated source')
            capture(source, output, approval, compiler_command_succeeded=True)
            retained = output / 'executable-input-outputs/Payload.g.cs'
            retained.write_bytes(b'changed output')
            with self.assertRaisesRegex(DependencyError, 'output-mutated'):
                verify(output, approval, source=source)
            retained.write_bytes(b'approved generated source')
            (source / 'Payload.g.cs').write_bytes(b'changed compiler input')
            with self.assertRaisesRegex(DependencyError, 'output-mutated'):
                verify(output, approval, source=source)
            (source / 'Payload.g.cs').write_bytes(b'approved generated source')
            receipt = output / 'executable-input-outputs.json'
            value = json.loads(receipt.read_bytes())
            value['approvalIdentity'] = 'sha256:' + '0' * 64
            receipt.write_text(json.dumps(value))
            with self.assertRaisesRegex(DependencyError, 'stale-receipt'):
                verify(output, approval)

    def test_output_receipt_binds_exact_approval_and_cannot_be_recaptured(self):
        from tools.dotnet_guest.outputs import capture, verify
        with tempfile.TemporaryDirectory() as temporary:
            root, approval = Path(temporary), self.approval()
            source, output = root / 'generated', root / 'retained'
            source.mkdir()
            output.mkdir()
            with self.assertRaisesRegex(DependencyError, 'output-approval'):
                capture(source, output, None, compiler_command_succeeded=True)
            receipt = capture(source, output, approval, compiler_command_succeeded=True)
            self.assertEqual(receipt['inputIdentity'], approval.specification['inputIdentity'])
            self.assertEqual(receipt['recipeDigest'], approval.specification['recipeDigest'])
            with self.assertRaisesRegex(DependencyError, 'capture-exists'):
                capture(source, output, approval, compiler_command_succeeded=True)
            approval.specification['recipeDigest'] = 'sha256:' + '1' * 64
            with self.assertRaisesRegex(DependencyError, 'output-approval'):
                verify(output, approval)

    def test_bounded_capture_failure_does_not_mask_original_compiler_failure(self):
        from unittest.mock import patch
        from tools.dotnet_guest.outputs import capture
        with tempfile.TemporaryDirectory() as temporary:
            root, approval = Path(temporary), self.approval()
            output, compiled = root / 'retained', root / 'compiled'
            output.mkdir()
            compiled.mkdir()
            source = compiled / 'generator-outputs'
            source.mkdir()
            (source / 'Payload.g.cs').write_bytes(b'four')
            failure = ValueError('original-compiler-error')

            def run(stage, *arguments):
                raise failure

            with patch('tools.dotnet_guest.outputs.MAX_BYTES', 3):
                with self.assertRaisesRegex(DependencyError, 'output-limit'):
                    capture(source, output, approval, compiler_command_succeeded=True)
                with self.assertRaises(ValueError) as caught:
                    self.compiler(output, approval, run).native_aot(compiled / 'project', compiled, compiled / 'wit-bindgen')
                self.assertIs(caught.exception, failure)
            self.assertFalse((output / 'executable-input-outputs.json').exists())
            self.assertFalse((output / 'executable-input-outputs').exists())

    def test_missing_empty_capture_directory_and_non_boolean_status_are_rejected(self):
        from tools.dotnet_guest.outputs import capture, verify
        with tempfile.TemporaryDirectory() as temporary:
            root, approval = Path(temporary), self.approval()
            output = root / 'retained'
            output.mkdir()
            with self.assertRaisesRegex(DependencyError, 'output-status'):
                capture(root / 'absent', output, approval, compiler_command_succeeded=1)
            capture(root / 'absent', output, approval, compiler_command_succeeded=True)
            (output / 'executable-input-outputs').rmdir()
            with self.assertRaisesRegex(DependencyError, 'output-missing'):
                verify(output, approval)


class RuntimeAdapterCapture(unittest.TestCase):
    def family(self, root):
        from tools.dotnet_guest.runtime import ADAPTERS
        source = root / 'installed'
        source.mkdir()
        result = {}
        for name, (_example, filename) in ADAPTERS.items():
            result[name] = source / filename
            result[name].write_bytes(('captured-' + name).encode())
        return result

    def test_all_three_runtime_adapters_are_captured_under_the_owned_namespace(self):
        from tools.dotnet_compiler_isolation import stage_adapters
        from tools.dotnet_guest.runtime import ADAPTERS
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = self.family(root)
            destination = root / 'private-adapters'
            captured = stage_adapters(original, destination)
            self.assertEqual(set(captured), set(ADAPTERS))
            for name, path in captured.items():
                self.assertEqual(path, destination / ADAPTERS[name][1])
                self.assertEqual(path.read_bytes(), original[name].read_bytes())
                self.assertTrue(path.is_relative_to(destination))
                self.assertNotEqual(path, original[name])

    def test_missing_or_additional_runtime_profiles_fail_before_staging(self):
        from tools.dotnet_compiler_isolation import stage_adapters
        for changed in ('missing', 'additional'):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                original = self.family(root)
                if changed == 'missing':
                    del original['http']
                else:
                    original['unattributed'] = original['closed']
                destination = root / 'private-adapters'
                with self.assertRaisesRegex(DependencyError, 'adapters-not-captured'):
                    stage_adapters(original, destination)
                self.assertFalse(destination.exists())

    def test_changed_source_during_capture_cannot_publish_an_adapter_family(self):
        from unittest.mock import patch
        import shutil
        from tools.dotnet_compiler_isolation import stage_adapters
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = self.family(root)
            copy = shutil.copyfile
            def changed_copy(source, destination):
                result = copy(source, destination)
                source.write_bytes(b'changed-after-capture')
                return result
            with patch('tools.dotnet_compiler_isolation.shutil.copyfile', side_effect=changed_copy):
                with self.assertRaisesRegex(DependencyError, 'adapter-input-mutated'):
                    stage_adapters(original, root / 'private-adapters')


class CapturedCompilerSelection(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        from tools.dotnet_guest.compiler import Compiler
        from tools.dotnet_guest import runtime
        self.namespace = SimpleNamespace
        self.compiler_type = Compiler
        self.runtime_profiles = runtime
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.evidence = self.root / 'evidence'
        self.evidence.mkdir()
        self.stages = []

    def graph(self, imports):
        interfaces, packages = [], [{'name': 'examples:greeting@1.0.0'}]
        for identity in imports:
            base, version = identity.split('@')
            package, name = base.rsplit('/', 1)
            packages.append({'name': package + '@' + version})
            interfaces.append({'name': name, 'package': len(packages) - 1, 'functions': {}, 'types': {}})
        return {'worlds': [{'name': 'service', 'package': 0,
                'imports': {str(index): {'interface': {'id': index}} for index in range(len(interfaces))},
                'exports': {}}], 'interfaces': interfaces, 'types': [], 'packages': packages}

    def application(self, workspace, *, emitted=None, final=None):
        from unittest.mock import Mock
        from tools.rust_capsule_project import write_json
        compiler = self.compiler_type.__new__(self.compiler_type)
        work = create(workspace / 'application', 'greeting')
        project_xml = work / 'Capsule.csproj'
        project_xml.write_bytes(project_xml.read_bytes().replace(b'</Project>',
            b'<ItemGroup><PackageReference Include="Outside.Library" Version="[2.0.0]" /></ItemGroup></Project>'))
        compiler.sdk = work / 'vendor/lsf/sdk/dotnet-guest'
        baseline = json.loads((compiler.sdk / 'probes/smoke/packages.lock.json').read_bytes())
        lock = copy.deepcopy(baseline)
        lock['dependencies']['net10.0']['Outside.Library'] = {
            'type': 'Direct', 'resolved': '2.0.0', 'contentHash': HASH}
        libraries = {name + '/' + row['resolved']: {'type': 'package',
            'path': (name + '/' + row['resolved']).lower(), 'sha512': row['contentHash'],
            'files': ['lib/net10.0/Outside.dll'] if name == 'Outside.Library' else []}
            for rows in lock['dependencies'].values() for name, row in rows.items()}
        targets = {name: {'compile': {'lib/net10.0/Outside.dll': {}}} if name.startswith('Outside.Library/')
            else {} for name in libraries}
        assets = {'version': 3, 'targets': {name: targets for name in ('net10.0', 'net10.0/wasi-wasm')},
                  'libraries': libraries}
        selected = analyze(lock, assets, baseline, declarations(snapshot(work)))
        write_json(work / 'packages.lock.json', lock)
        write_json(work / 'nuget-resolved.lock.json', selected)
        compiler.package_cache = workspace / 'packages'
        compiler.package_cache.mkdir()
        compiler.application_closure, compiler.offline = object(), True
        compiler.commands = self.namespace(output=self.evidence, environment={})
        compiler.isolation = self.namespace(workspace=workspace, read_only_inputs=[])
        compiler.isolation.protect_inputs = lambda *paths: compiler.isolation.read_only_inputs.extend(paths)
        compiler.dotnet = compiler.wasm = compiler.python = compiler.wac = workspace / 'compiler-tool'
        compiler.runtimes = {}
        for profile, (_example, filename) in self.runtime_profiles.ADAPTERS.items():
            adapter = workspace / filename
            adapter.write_bytes(b'\0asm\x0d\0\x01\0')
            compiler.runtimes[profile] = adapter
        raw_graph = self.graph(emitted if emitted is not None else [self.runtime_profiles.CLOCK])
        final_graph = self.graph(final if final is not None else [self.runtime_profiles.CLOCK])
        receipt = {'outputs': {'ServiceWorld.cs': 'reviewed-binding'}}
        compiled = workspace / 'compiled'

        def run(stage, executable, *arguments):
            self.stages.append(stage)
            if stage == 'declared-runtime-wit':
                return json.dumps(self.graph([self.runtime_profiles.CLOCK])).encode()
            if stage == 'bindings':
                generated = compiled / 'generated'
                generated.mkdir()
                write_json(generated / 'bindings.json', receipt)
                (generated / 'ServiceWorld.cs').write_text('namespace ServiceWorld.wit.Exports.examples.greeting;\n')
            if stage == 'canonical-wit' or stage == 'surface':
                return (work / 'wit/world.wit').read_bytes()
            if stage == 'locked-restore':
                objects = compiled / 'project/obj'
                objects.mkdir()
                write_json(objects / 'project.assets.json', assets)
            if stage in {'native-runtime-wit', 'native-aot-raw-wit'}:
                return json.dumps(raw_graph).encode()
            if stage == 'closed-runtime-adapter-wit':
                return json.dumps(self.graph([])).encode()
            if stage == 'closed-runtime-composition':
                (compiled / 'component.wasm').write_bytes(b'\0asm\x0d\0\x01\0')
            if stage == 'runtime-final-wit':
                return json.dumps(final_graph).encode()
            return b''

        def native_aot(project, output, wrapper):
            self.stages.append('native-aot')
            write_json(project / 'obj/bindings.json', receipt)
            raw = project / 'bin/Release/net10.0/wasi-wasm/publish/Capsule.wasm'
            raw.parent.mkdir(parents=True)
            raw.write_bytes(b'\0asm\x0d\0\x01\0')

        compiler.run, compiler.native_aot = run, native_aot
        self.configure = Mock(return_value=selected)
        return compiler, work, compiled

    def test_captured_nuget_selection_preserves_authoritative_wit_imports(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            compiler, work, output = self.application(Path(temporary))
            with patch('tools.dotnet_application_dependencies.configure', self.configure):
                component, receipt = compiler.compile(work, 'examples:greeting/service@1.0.0', output)
            self.configure.assert_called_once_with(compiler.application_closure, work, compiler.package_cache)
            self.assertTrue(component.is_file())
            self.assertEqual(receipt['runtimeProfile']['declaredImports'], [self.runtime_profiles.CLOCK])
            self.assertEqual(receipt['runtimeProfile']['profile'], 'closed')
            self.assertIn('closed-runtime-composition', self.stages)
            self.assertEqual(json.loads((self.evidence / 'nuget-build-inputs.json').read_bytes())['packages'],
                             self.configure.return_value['packages'])

    def test_profile_rejection_retains_raw_component_and_wit_after_workspace_cleanup(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            compiler, work, output = self.application(Path(temporary), emitted=['wasi:http/types@0.2.1'])
            with patch('tools.dotnet_application_dependencies.configure', self.configure):
                with self.assertRaisesRegex(ValueError, 'dotnet-runtime-unsupported-wasi-import:wasi:http/types@0.2.1'):
                    compiler.compile(work, 'examples:greeting/service@1.0.0', output)
            self.assertNotIn('closed-runtime-composition', self.stages)
            self.assertFalse((self.evidence / 'runtime-profile.json').exists())
        self.assertEqual((self.evidence / 'native-aot-raw.wasm').read_bytes(), b'\0asm\x0d\0\x01\0')
        self.assertEqual(json.loads((self.evidence / 'native-aot-raw.wit.json').read_bytes()),
                         self.graph(['wasi:http/types@0.2.1']))

    def test_final_component_cannot_introduce_undeclared_authority(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            compiler, work, output = self.application(Path(temporary),
                final=[self.runtime_profiles.CLOCK, 'latent:secrets/reader@0.1.0'])
            with patch('tools.dotnet_application_dependencies.configure', self.configure):
                with self.assertRaisesRegex(ValueError, 'runtime adapter introduced undeclared authority:latent:secrets/reader@0.1.0'):
                    compiler.compile(work, 'examples:greeting/service@1.0.0', output)
            self.assertIn('closed-runtime-composition', self.stages)
            self.assertFalse((output / 'component.wit').exists())

    def test_oversized_raw_wit_is_rejected_before_diagnostic_publication(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            compiler, work, output = self.application(Path(temporary))
            run = compiler.run
            oversized = json.dumps(self.graph([self.runtime_profiles.CLOCK])).encode()
            oversized += b' ' * (4 * 1024 * 1024 + 1 - len(oversized))
            compiler.run = lambda stage, *arguments: oversized if stage == 'native-runtime-wit' else run(stage, *arguments)
            with patch('tools.dotnet_application_dependencies.configure', self.configure):
                with self.assertRaisesRegex(ValueError, 'native-aot-raw-wit-byte-limit'):
                    compiler.compile(work, 'examples:greeting/service@1.0.0', output)
            self.assertFalse((self.evidence / 'native-aot-raw.wit.json').exists())
            self.assertFalse((self.evidence / 'runtime-profile.json').exists())
            self.assertNotIn('closed-runtime-composition', self.stages)
        self.assertEqual((self.evidence / 'native-aot-raw.wasm').read_bytes(), b'\0asm\x0d\0\x01\0')

    def test_offline_asset_drift_still_fails_before_native_aot(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            compiler, work, output = self.application(Path(temporary))
            selected = json.loads((work / 'nuget-resolved.lock.json').read_bytes())
            next(row for row in selected['packages'] if row['package'] == 'outside.library')['files'] = []
            (work / 'nuget-resolved.lock.json').write_text(json.dumps(selected))
            with patch('tools.dotnet_application_dependencies.configure', self.configure):
                with self.assertRaisesRegex(ValueError, 'offline-NuGet-native-asset-selection-differs-from-reviewed-capture'):
                    compiler.compile(work, 'examples:greeting/service@1.0.0', output)
            self.assertNotIn('native-aot', self.stages)
            self.assertTrue((self.evidence / 'nuget-asset-selection-drift.json').is_file())


if __name__ == '__main__':
    unittest.main()
