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


if __name__ == '__main__':
    unittest.main()
