"""Normal compiler admission mechanisms; no SDK acquisition or tool execution."""
from pathlib import Path
import json
import tempfile
import urllib.error
import unittest
from unittest import mock

from tools.java_guest import compiler_profile as profile
from tools.java_guest.compiler import Compiler, tool_inventory
from tools import dev_managed_distribution as distribution


class NormalJavaCompilerProfile(unittest.TestCase):
    def inactive(self) -> bytes:
        value = json.loads(profile.read())
        for name in profile.FUTURE:
            value[name] = None
        return profile.encoded(value)

    def fixture(self, first: Path, second: Path) -> dict:
        value = json.loads(self.inactive())
        value['producer'] = {'head': 'a' * 40, 'tree': 'b' * 40, 'run': 1, 'job': 2,
                             'artifact': 3, 'archive': profile.identity(b'fixture archive')}
        value['qualification'] = {'producerReceipt': profile.identity(b'fixture producer'),
            'publicReceipt': profile.identity(b'fixture public'),
            'publicComponent': profile.identity(b'not an executable component'),
            'normalCommandShape': profile.identity(b'fixture command shape'),
            'publicHead': 'c' * 40, 'publicRun': 4, 'publicJob': 5,
            'publicArtifact': {'id': 6, 'archive': profile.identity(b'fixture public archive'),
                               'expiresAt': '2026-10-28T20:00:00Z'}}
        value['carrier'] = profile.identity(b'fixture carrier')
        value['manifest'] = profile.identity(b'fixture manifest')
        value['notices'] = {name: profile.identity(name.encode()) for name in profile.NOTICES}
        version = ('\n'.join(('29.0-lsf-private-scalar-v1', 'wasi-libc: ac020b86fd44',
            'llvm: 222fc11f2b8f', 'llvm-version: 21.1.4', 'config: f992bcc08219',
            'lsf-llvm-patch-sha256: ' + value['notices']['LLVM-PRIVATE-STORES.json']['sha256'])) + '\n').encode()
        value['version'] = profile.identity(version)
        for root in (first, second):
            root.mkdir()
            (root / 'VERSION').write_bytes(version)
            (root / 'bin').mkdir()
            (root / 'bin/clang').write_bytes(b'source-only distribution fixture; never executed')
        # Two finite real file trees exercise the two pinned-identity slots.
        # They do not purport to be the actual SDK or its link-flattening proof.
        (second / 'fixture-copy').write_bytes(b'second source-owned representation')
        value['inventories'] = {'linked': profile.identity(tool_inventory({'wasi-sdk': first})),
                                'managed': profile.identity(tool_inventory({'wasi-sdk': second}))}
        value['buildInput'] = {'kind': 'prepared-compiler-inputs', 'artifactId': 3,
                              'archive': value['producer']['archive'], 'expiresAt': '2026-10-28T20:00:00Z'}
        return value

    def test_unfilled_source_preserves_official_default_and_refuses_new_sdk_before_inventory(self):
        inactive = self.inactive()
        with mock.patch.object(profile, 'read', return_value=inactive):
            self.assertIsNone(profile.pin())
            self.assertEqual(distribution.sources('java'),
                             {name: distribution.SOURCES[name] for name in ('wasi-sdk', 'jdk', 'gradle')})
            with mock.patch.object(profile, 'read', side_effect=AssertionError('dotnet must not select Java profile')):
                self.assertEqual(distribution.sources('dotnet'),
                                 {name: distribution.SOURCES[name] for name in ('wasi-sdk', 'dotnet')})
            with tempfile.TemporaryDirectory() as folder:
                sdk = Path(folder)
                compiler = Compiler.__new__(Compiler)
                compiler.wasi_sdk = sdk
                (sdk / 'VERSION').write_text('\n'.join(profile.OFFICIAL) + '\n', encoding='utf-8')
                self.assertEqual(compiler._wasi_compiler_version(), '21.1.4-wasi-sdk')
                self.assertIsNone(compiler.wasi_compiler_profile)
                (sdk / 'VERSION').write_text('29.0-' + profile.PROFILE + '\n', encoding='utf-8')
                with mock.patch('tools.java_guest.compiler.tool_inventory') as inventory:
                    with self.assertRaisesRegex(ValueError, 'unreviewed WASI-SDK Java compiler'):
                        compiler._wasi_compiler_version()
                    inventory.assert_not_called()

    def test_partial_or_unreviewed_source_cannot_change_normal_default(self):
        value = json.loads(self.inactive())
        value['producer'] = {}
        with mock.patch.object(profile, 'read', return_value=profile.encoded(value)):
            with self.assertRaisesRegex(ValueError, 'partial-promotion'):
                distribution.sources('java')
        value = json.loads(self.inactive())
        value['unreviewed'] = True
        with mock.patch.object(profile, 'read', return_value=profile.encoded(value)):
            with self.assertRaisesRegex(ValueError, 'schema'):
                profile.pin()

    def test_only_two_complete_source_owned_inventories_admit_and_retain_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first, second = root / 'first', root / 'second'
            value = self.fixture(first, second)
            raw = profile.encoded(value)
            with mock.patch.object(profile, 'read', return_value=raw):
                for sdk, representation in ((first, 'linked'), (second, 'managed')):
                    compiler = Compiler.__new__(Compiler)
                    compiler.wasi_sdk = sdk
                    self.assertEqual(compiler._wasi_compiler_version(), profile.CLANG_VERSION)
                    observed = json.loads(compiler.wasi_compiler_profile)
                    self.assertEqual(observed['representation'], representation)
                    self.assertEqual(observed['sourceProfile'], profile.identity(raw))
                    self.assertEqual(observed['compilerInventory'], value['inventories'][representation])
                    self.assertFalse(observed['runtimeQualification'])
                    profile.recheck(compiler.wasi_compiler_profile)
                    with mock.patch.object(profile, 'read', return_value=raw + b' '):
                        with self.assertRaisesRegex(ValueError, 'source-changed-during-build'):
                            profile.recheck(compiler.wasi_compiler_profile)
                self.assertNotIn('wasi-sdk', distribution.sources('java'))
                self.assertEqual(distribution.sources('dotnet')['wasi-sdk'], distribution.SOURCES['wasi-sdk'])
                (first / 'bin/clang').write_bytes(b'changed fixture bytes')
                with self.assertRaisesRegex(ValueError, 'complete-sdk-inventory'):
                    profile.admit(first)
                forgery = root / 'version-only'
                forgery.mkdir()
                (forgery / 'VERSION').write_bytes(profile.version_bytes(value))
                with self.assertRaisesRegex(ValueError, 'complete-sdk-inventory'):
                    profile.admit(forgery)

    def test_foreign_artifact_redirect_never_receives_a_blob_request(self):
        from tools.java_guest import compiler_profile_distribution as delivery
        from tools.java_guest import llvm_private_store_inputs as inputs
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            value = self.fixture(root / 'first', root / 'second')
            producer = value['producer']
            metadata = {'id': 3, 'name': 'java-llvm-private-stores-producer-' + 'a' * 40,
                'expired': False, 'size_in_bytes': producer['archive']['bytes'],
                'digest': 'sha256:' + producer['archive']['sha256'],
                'workflow_run': {'id': 1, 'head_sha': 'a' * 40}}
            redirect = urllib.error.HTTPError('https://api.github.com/fixture', 302, 'redirect',
                                              {'Location': 'https://unreviewed.example/payload'}, None)
            with mock.patch.object(profile, 'read', return_value=profile.encoded(value)), \
                    mock.patch.object(inputs, '_response', return_value=profile.encoded(metadata)), \
                    mock.patch.object(delivery.urllib.request, 'build_opener') as opener, \
                    mock.patch.object(delivery.urllib.request, 'urlopen') as blob:
                opener.return_value.open.side_effect = redirect
                with self.assertRaisesRegex(ValueError, 'build-input-blob-origin'):
                    delivery.acquire(root / 'inputs', 'test-only-token')
                blob.assert_not_called()

    def test_unqualified_builder_refuses_before_reading_any_candidate_archive(self):
        inactive = self.inactive()
        with mock.patch.object(profile, 'read', return_value=inactive):
            from tools.java_guest.compiler_profile_distribution import extract
            with self.assertRaisesRegex(ValueError, 'unqualified-distribution'):
                extract(Path('not-read/derived-sdk.tar.gz'), Path('not-created'))
            from tools import build_dev_guest_tools as builder
            arguments = ['builder', '--language', 'java', '--output', 'not-created',
                         '--python-prefix', 'not-read', '--java-compiler-input', 'not-read']
            with mock.patch('sys.argv', arguments), \
                    mock.patch.object(builder.subprocess, 'check_output') as git, \
                    mock.patch.object(builder, 'run_bounded_result') as compiler:
                with self.assertRaisesRegex(ValueError, 'unqualified-prepared-java-compiler'):
                    builder.main()
                git.assert_not_called()
                compiler.assert_not_called()


if __name__ == '__main__':
    unittest.main()
