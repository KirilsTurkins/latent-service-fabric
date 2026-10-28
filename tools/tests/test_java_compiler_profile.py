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

    def test_expired_origin_uses_only_exact_archived_prepared_cache(self):
        from tools.java_guest import compiler_profile_distribution as delivery
        from tools.java_guest import llvm_private_store_inputs as inputs
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            value = self.fixture(root / 'first', root / 'second')
            value['buildInput']['expiresAt'] = '2000-01-01T00:00:00Z'
            value['qualification']['publicArtifact']['expiresAt'] = '2000-01-01T00:00:00Z'
            prepared = root / 'prepared'
            prepared.mkdir()
            (prepared / 'producer.zip').write_bytes(b'fixture archive')
            (prepared / 'public-compiler.json').write_bytes(b'fixture public')
            environment = {'LSF_DEV_COMPILER_CACHE': str(root / 'cache'),
                           'LSF_DEV_JAVA_COMPILER_INPUT': str(prepared)}
            with mock.patch.object(profile, 'read', return_value=profile.encoded(value)), \
                    mock.patch.dict(delivery.os.environ, environment), \
                    mock.patch.object(inputs, '_response', side_effect=AssertionError('expired API must not be read')) as api, \
                    mock.patch.object(delivery.urllib.request, 'urlopen', side_effect=AssertionError('offline cache')) as network:
                # An operator's exact archived pair seeds the ordinary digest
                # cache, without a token or a still-live Actions artifact.
                delivery.acquire(root / 'seeded', '')
                for name in ('producer.zip', 'public-compiler.json'):
                    self.assertEqual((root / 'seeded' / name).read_bytes(), (prepared / name).read_bytes())
                delivery.os.environ['LSF_DEV_JAVA_COMPILER_INPUT'] = ''
                delivery.acquire(root / 'cache-hit', '')
                for name in ('producer.zip', 'public-compiler.json'):
                    self.assertEqual((root / 'cache-hit' / name).read_bytes(), (prepared / name).read_bytes())
                cache = root / 'cache/java-prepared'
                receipt = cache / (value['qualification']['publicReceipt']['sha256'] + '.archive')
                receipt.write_bytes(b'wrong bytes')
                with self.assertRaisesRegex(ValueError, 'prepared-cache-digest'):
                    delivery.acquire(root / 'tampered', '')
                receipt.unlink()
                with self.assertRaisesRegex(ValueError, 'cold-build-requires-prepared-input'):
                    delivery.acquire(root / 'missing', '')
                api.assert_not_called()
                # Even with a token, an otherwise matching expired origin
                # cannot replace the missing archived receipt.
                producer = value['producer']
                api.side_effect = None
                api.return_value = profile.encoded({'id': producer['artifact'],
                    'name': 'java-llvm-private-stores-producer-' + producer['head'],
                    'expired': True, 'size_in_bytes': producer['archive']['bytes'],
                    'digest': 'sha256:' + producer['archive']['sha256'],
                    'workflow_run': {'id': producer['run'], 'head_sha': producer['head']}})
                with self.assertRaisesRegex(ValueError, 'build-input-origin'):
                    delivery.acquire(root / 'expired-cold', 'test-only-token')
                api.assert_called_once()
                network.assert_not_called()

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


class RetainedJavaCompilerCustody(unittest.TestCase):
    def test_complete_outer_inventory_refuses_unknown_duplicate_link_and_changed_bytes(self):
        import stat
        import time
        import zipfile
        from tools.java_guest import compiler_profile_distribution as delivery
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            expected = {'first.json': profile.identity(b'first'), 'second.zip': profile.identity(b'second')}

            def archive(name, entries):
                path = root / name
                with zipfile.ZipFile(path, 'x') as package:
                    for label, raw, mode in entries:
                        entry = zipfile.ZipInfo(label)
                        entry.external_attr = mode << 16
                        package.writestr(entry, raw)
                return path

            good = [('first.json', b'first', stat.S_IFREG | 0o600),
                    ('second.zip', b'second', stat.S_IFREG | 0o600)]
            source = archive('good.zip', good)
            delivery._custody_outer(source, root / 'accepted', expected, time.monotonic() + 5)
            self.assertEqual({p.name: p.read_bytes() for p in (root / 'accepted').iterdir()},
                             {'first.json': b'first', 'second.zip': b'second'})
            variants = [good + [('foreign', b'x', stat.S_IFREG)],
                        [good[0], good[0]],
                        [('first.json', b'first', stat.S_IFLNK), good[1]],
                        [('first.json', b'other', stat.S_IFREG), good[1]]]
            for index, entries in enumerate(variants):
                with self.subTest(index=index), self.assertRaisesRegex(ValueError, 'custody-member'):
                    delivery._custody_outer(archive(str(index) + '.zip', entries), root / str(index),
                                            expected, time.monotonic() + 5)

    def test_original_producer_receipt_and_linked_profile_are_required_after_managed_admission(self):
        import time
        from tools.java_guest import compiler_profile_distribution as delivery
        from tools.java_guest.llvm_private_store_distribution import MANIFEST
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            value = NormalJavaCompilerProfile().fixture(root / 'linked', root / 'managed')
            provenance = root / 'provenance'
            provenance.mkdir()
            bodies = {name: name.encode() for name in profile.NOTICES}
            bodies.update({'result.json': b'fixture producer', 'public-compiler.json': b'fixture public',
                           MANIFEST: b'fixture manifest', 'source.json': b'{}', 'commands.json': b'[]',
                           'units.xml': b'<testsuite/>', 'lit.xml': b'<testsuite/>'})
            for name, raw in bodies.items():
                (provenance / name).write_bytes(raw)
            with mock.patch.object(profile, 'read', return_value=profile.encoded(value)):
                managed = profile.admit(root / 'managed')
                self.assertIsNotNone(managed)
                original = json.loads(managed[1])
                original.update(representation='linked', compilerInventory=value['inventories']['linked'])
                (provenance / 'normal-compiler-profile.json').write_bytes(profile.encoded(original))
                delivery._custody_provenance(provenance, managed[1], value, time.monotonic() + 5)
                (provenance / 'result.json').write_bytes(b'changed producer')
                with self.assertRaisesRegex(ValueError, 'custody-provenance-digest|file-bound'):
                    delivery._custody_provenance(provenance, managed[1], value, time.monotonic() + 5)
                (provenance / 'result.json').write_bytes(b'fixture producer')
                original['producer']['head'] = 'f' * 40
                (provenance / 'normal-compiler-profile.json').write_bytes(profile.encoded(original))
                with self.assertRaisesRegex(ValueError, 'custody-original-profile'):
                    delivery._custody_provenance(provenance, managed[1], value, time.monotonic() + 5)

    def test_recovery_refuses_unqualified_or_nonfresh_roots_before_network_or_output(self):
        from tools.java_guest import compiler_profile_distribution as delivery
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with mock.patch.object(profile, '_source_pin', return_value=None), \
                    mock.patch.object(delivery, '_custody_download') as download:
                with self.assertRaisesRegex(ValueError, 'unqualified-custody'):
                    delivery.recover_custody(root, root / 'result', 'not-used')
                download.assert_not_called()
                self.assertFalse((root / 'result').exists())
            (root / 'sentinel').write_bytes(b'preserved')
            with mock.patch.object(delivery, '_custody_download') as download:
                with self.assertRaisesRegex(ValueError, 'custody-fresh-root'):
                    delivery.recover_custody(root, root / 'result', 'not-used')
                download.assert_not_called()
                self.assertEqual((root / 'sentinel').read_bytes(), b'preserved')
                self.assertFalse((root / 'result').exists())


if __name__ == '__main__':
    unittest.main()
