"""Synthetic reader boundaries; no fixture here claims compiler or runtime qualification."""
import io
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import java_checkpoint_gc_retained as reader
from tools.phase2_operator_process import WorkflowError
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import digest, fresh, write_json


class RetainedGcReaderTests(unittest.TestCase):
    @staticmethod
    def archive(name='original.txt', mode=stat.S_IFREG):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            entry = zipfile.ZipInfo(name);entry.external_attr = (mode | 0o600) << 16
            archive.writestr(entry, b'original')
        return buffer.getvalue()

    def test_whole_identity_member_digest_and_safe_regular_copy(self):
        for name, mode, bad_digest in [('original.txt', stat.S_IFREG, False),
                ('../escape', stat.S_IFREG, False), ('link', stat.S_IFLNK, False),
                ('original.txt', stat.S_IFREG, True)]:
            raw = self.archive(name, mode)
            rows = {name: {'bytes': 8, 'sha256': digest(b'changed!' if bad_digest else b'original')}}
            with self.subTest(name=name, mode=mode, bad_digest=bad_digest), tempfile.TemporaryDirectory() as temp:
                with patch.object(reader, 'ARTIFACT', {'size_in_bytes': len(raw), 'digest': digest(raw)}), \
                        patch.object(reader, 'pins', return_value=rows):
                    if name == 'original.txt' and mode == stat.S_IFREG and not bad_digest:
                        reader.extract(raw, Path(temp)/'out')
                        self.assertEqual((Path(temp)/'out/original.txt').read_bytes(), b'original')
                        with self.assertRaises(WorkflowError):reader.extract(raw[:-1]+b'x', Path(temp)/'bad')
                    else:
                        with self.assertRaises(WorkflowError):reader.extract(raw, Path(temp)/'out')
                        self.assertFalse((Path(temp)/'escape').exists())

    def test_current_source_bridge_never_exempts_compiled_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);(root/'compiler').write_bytes(b'old');(root/'controller').write_bytes(b'new')
            original = {'digest': digest(b'old'), 'size': 3}
            rows = {n: original for n in ('compiler', 'controller')}
            with patch.object(reader, 'ROOT', root), patch.object(reader, 'CURRENT_DIFFERENCES',
                    {'controller': file_identity(root/'controller')}):
                self.assertEqual(set(reader.current_preimages(rows, {'compiler'})), {'controller'})
                with self.assertRaises(WorkflowError):reader.current_preimages(rows, {'compiler', 'controller'})
                (root/'compiler').write_bytes(b'new')
                with self.assertRaises(WorkflowError):reader.current_preimages(rows, {'compiler'})
                (root/'compiler').write_bytes(b'old');(root/'controller').write_bytes(b'???')
                with self.assertRaises(WorkflowError):reader.current_preimages(rows, {'compiler'})

    def test_original_library_identity_refuses_replaced_or_extra_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'jar';path.write_bytes(b'library')
            with patch.object(reader, 'LIBRARY_IDENTITY', {'bytes': 7, 'sha256': digest(b'library')}):
                self.assertEqual(reader.recover_library(path), b'library')
                path.write_bytes(b'changed')
                with self.assertRaises(WorkflowError):reader.recover_library(path)
                path.write_bytes(b'library-extra')
                with self.assertRaises(ValueError):reader.recover_library(path)

    @staticmethod
    def package(root):
        build = fresh(root/'original/build');project = fresh(root/'static')
        data = {n: b'original-wit-'+str(i).encode() for i, n in enumerate(reader.WITS)}
        data.update({n: b'original-resource-'+str(i).encode() for i, n in enumerate(reader.RESOURCE_MEMBERS)})
        expected = {}
        for name, raw in {**data, **{n: b'{}' for n in ('capsule.json', 'contracts.json', 'wit-lock.json',
                'compatibility-report.json', 'resource-index.json')}, 'component.wasm': b'wasm'}.items():
            expected[name] = {'digest': digest(raw), 'size': len(raw)}
            if name not in data:(build/name).write_bytes(raw)
            elif name in reader.WITS:
                path = project/name;path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(raw)
        write_json(build/'package-source.json', {'layers': [{'source': n} for n in expected]})
        value = (build/'package-source.json').read_bytes()
        expected['package-source.json'] = {'digest': digest(value), 'size': len(value)}
        write_json(build/'package-inputs.json', expected)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            for name, member in reader.RESOURCE_MEMBERS.items():archive.writestr(member, data[name])
        return build, project, buffer.getvalue()

    def test_reconstruction_requires_original_package_hash_and_exact_absence(self):
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as temp:
                root = Path(temp);build, project, library = self.package(root)
                if corrupt:(project/reader.WITS[0]).write_bytes(b'replacement')
                with patch.object(reader.fixture, 'project', return_value=project):
                    if corrupt:
                        with self.assertRaises(WorkflowError):reader.recover_package(build.parent, root, library)
                    else:
                        proof = reader.recover_package(build.parent, root, library)
                        self.assertEqual(len(proof['originalPackageInputs']), 12)
                        self.assertEqual(len(proof['reconstructedOriginalInputs']), 5)
                        self.assertEqual(proof['compilerInvocations'], 0)
                        with self.assertRaises(WorkflowError):reader.recover_package(build.parent, root, library)


if __name__ == '__main__':unittest.main()
