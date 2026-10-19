"""Private RNG derivation and exact NativeAOT reference refusal controls."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from tools.build_observation import file_identity
from tools.dotnet_guest import managed_entropy as entropy
from tools.rust_capsule_project import ROOT, inventory, snapshot


class ManagedEntropyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lsf-managed-entropy-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        shutil.copytree(ROOT / 'sdk/dotnet-guest/tools/managed-entropy', self.source)

    def test_pinned_upstream_algorithms_have_only_the_closed_namespace_and_base_derivation(self):
        files = entropy.verify_source(self.source)
        self.assertEqual(len(files), 17)
        self.assertIn(b'<UseAppHost>false</UseAppHost>', files['Rewrite.csproj'])
        self.assertEqual(files['HexConverter.cs'], files['upstream/HexConverter.cs'])
        self.assertIn(b'global::System.Security.Cryptography.RandomNumberGenerator', files['RandomNumberGenerator.cs'])
        self.assertNotIn(b'CryptoConfig.CreateFromName', files['RandomNumberGenerator.cs'])
        self.assertIn(b'RandomNumberGeneratorImplementation.FillSpan', files['RandomNumberGenerator.cs'])
        self.assertIn(b'throw new CryptographicException()', files['Support.cs'])
        self.assertEqual(files['ManagedEntropy.targets'].count(b'<DirectPInvoke Include="System.Native"'), 1)
        self.assertIn(b"'%(IlcReference.Filename)' == 'System.Security.Cryptography'", files['ManagedEntropy.targets'])

    def test_rewriter_reference_uses_the_authenticated_captured_support_copy(self):
        support = self.root / 'captured-support'
        cecil = support / 'http-errors/Mono.Cecil.dll'
        cecil.parent.mkdir(parents=True)
        cecil.write_bytes(b'bounded captured Cecil stand-in')
        compiler = SimpleNamespace(sdk=ROOT / 'sdk/dotnet-guest', package_cache=self.root / 'packages',
            tools=self.root / 'unmounted-original-tools', http_error_tools=support, dotnet=self.root / 'dotnet')
        class BuildObserved(Exception):
            pass
        def observe(name, executable, *arguments):
            self.assertEqual(name, 'managed-entropy-build-managedentropy')
            reference = next(str(value) for value in arguments if str(value).startswith('-p:LsfCecilPath='))
            self.assertEqual(reference, '-p:LsfCecilPath=' + str(cecil))
            self.assertTrue(cecil.is_file())
            raise BuildObserved()
        compiler.run = observe
        output = self.root / 'output'
        output.mkdir()
        with patch.object(entropy, 'original', return_value={}), patch.object(entropy.http_errors,
                'CECIL_DIGEST', entropy.digest(cecil.read_bytes())):
            with self.assertRaises(BuildObserved):
                entropy.prepare(compiler, self.root / 'project', output)

    def test_changed_upstream_bytes_or_descriptor_refuse(self):
        path = self.source / 'upstream/RandomNumberGenerator.cs'
        before = path.read_bytes()
        path.write_bytes(before + b'\n')
        with self.assertRaisesRegex(ValueError, 'upstream-preimage'):
            entropy.verify_source(self.source)
        path.write_bytes(before)
        path = self.source / 'upstream.json'
        value = json.loads(path.read_text())
        value['revision'] = '0' * 40
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'upstream-identity'):
            entropy.verify_source(self.source)

    def test_changed_derived_algorithm_refuses(self):
        path = self.source / 'RandomNumberGeneratorImplementation.Browser.cs'
        path.write_bytes(path.read_bytes().replace(b'Interop.GetCryptographicallySecureRandomBytes', b'Interop.Fallback'))
        with self.assertRaisesRegex(ValueError, 'unreviewed-source-derivation'):
            entropy.verify_source(self.source)

    def test_unselected_framework_preimage_refuses(self):
        path = self.root / 'System.Security.Cryptography.dll'
        path.write_bytes(b'unsupported replacement')
        with self.assertRaisesRegex(ValueError, 'unsupported-framework-preimage'):
            entropy.original(path)

    def port(self):
        paths = (self.root / 'System.Security.Cryptography.dll', self.root / 'Lsf.StandardEntropy.dll')
        identities = {}
        for index, path in enumerate(paths):
            path.write_bytes(b'unit boundary material ' + str(index).encode())
            identities[path] = file_identity(path, 'unit-material', entropy.MAXIMUM)
        target = self.root / 'ManagedEntropy.targets'
        target.write_bytes(b'captured target')
        refs = self.root / 'references.txt'
        refs.write_text('\n'.join(map(str, paths)))
        project = self.root / 'project'
        (project / 'obj').mkdir(parents=True)
        rsp = project / 'obj/ilc.rsp'
        rsp.write_text('\n'.join('-r:' + str(path) for path in paths))
        port = entropy.Port(self.source, (), identities, inventory(snapshot(self.source)), target,
                            target.read_bytes(), refs, {'profile': entropy.PROFILE})
        return port, project, paths, rsp

    def test_both_exact_private_assemblies_are_observed_once(self):
        port, project, paths, _ = self.port()
        result = port.finish(project, self.root)
        self.assertEqual(len(result['nativeAotReferenceBinding']), 1)
        self.assertTrue((self.root / 'managed-entropy-port.json').is_file())

    def test_missing_duplicate_or_original_native_reference_refuses(self):
        port, project, paths, rsp = self.port()
        original = self.root / 'shared/System.Security.Cryptography.dll'
        for selected in ((paths[0],), (*paths, paths[0]), (original, paths[1])):
            with self.subTest(selected=selected):
                rsp.write_text('\n'.join('-r:' + str(path) for path in selected))
                with self.assertRaisesRegex(ValueError, 'native-reference-drift'):
                    port.finish(project, self.root)
        self.assertFalse((self.root / 'managed-entropy-port.json').exists())

    def test_generated_material_target_or_captured_source_drift_refuses(self):
        port, _, paths, _ = self.port()
        for path in (paths[0], port.targets, self.source / 'Support.cs'):
            with self.subTest(path=path):
                before = path.read_bytes()
                path.write_bytes(before + b'changed')
                with self.assertRaisesRegex(ValueError, 'drift'):
                    port.recheck()
                path.write_bytes(before)


if __name__ == '__main__':
    unittest.main()
