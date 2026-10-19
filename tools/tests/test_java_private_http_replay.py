"""Pure source/material controls; no native product or compiler execution."""
import ast
import copy
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import java_replay_materials as materials
from tools import qualify_java_private_http as production
from tools import replay_java_private_http as replay
from tools.phase3_resource_identity import file_identity


class JavaPrivateHttpReplayTest(unittest.TestCase):
    def test_exact_frozen_git_source_distinguishes_other_compiled_revision(self):
        self.assertEqual(materials.git_source_identity(materials.HOST_SOURCE), materials.HOST_IDENTITY)
        self.assertNotEqual(materials.git_source_identity(materials.ORIGINAL), materials.HOST_IDENTITY)

    def test_host_profile_and_product_refuse_foreign_or_nonordinary_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'latentd').write_bytes(b'non-executable source-only product fixture')
            product = file_identity(root/'latentd')
            info = {'compiledSource': materials.HOST_SOURCE, 'sourceIdentity': materials.HOST_IDENTITY,
                'binary': product, 'features': [], 'ordinaryDefaults': True,
                'profile': {'opt_level': '0', 'debuginfo': 0, 'debug_assertions': True,
                            'overflow_checks': True, 'test': False}}
            with patch.object(materials, 'HOST_BINARY', product), patch.object(
                    materials, 'git_source_identity', return_value=materials.HOST_IDENTITY):
                (root/'current-host.json').write_text(json.dumps(info))
                materials.validate_host(root)
                for key, value in (('compiledSource', '0'*40), ('ordinaryDefaults', 1),
                                   ('features', ['development-test-node']),
                                   ('sourceIdentity', {}), ('binary', {}), ('profile', {})):
                    changed = copy.deepcopy(info); changed[key] = value
                    (root/'current-host.json').write_text(json.dumps(changed))
                    with self.subTest(field=key), self.assertRaises(RuntimeError):
                        materials.validate_host(root)
                (root/'current-host.json').write_text(json.dumps(info))
                (root/'latentd').write_bytes(b'changed real bytes')
                with self.assertRaises(RuntimeError):
                    materials.validate_host(root)

    def test_range_reads_are_bounded_and_require_exact_partial_response(self):
        class Response(io.BytesIO):
            status = 206
            headers = {'Content-Range': 'bytes 0-2/3'}
        remote = materials.Ranges('https://example.invalid/signed-in-memory', 3)
        with patch.object(materials.urllib.request, 'urlopen', return_value=Response(b'abc')) as opened:
            self.assertEqual(remote.read(), b'abc')
            self.assertEqual(remote.requests, 1)
            self.assertNotIn('Authorization', opened.call_args.args[0].headers)
        with self.assertRaises(RuntimeError):
            materials.Ranges('https://example.invalid', 10**9).read(8*1024**2+1)
        remote = materials.Ranges('https://example.invalid', 3)
        remote.requests = 4096
        with self.assertRaises(RuntimeError):
            remote.read(1)
        remote = materials.Ranges('https://example.invalid', 3)
        response = Response(b'abc'); response.status = 200
        with patch.object(materials.urllib.request, 'urlopen', return_value=response), self.assertRaises(RuntimeError):
            remote.read(3)

    def test_only_fixed_regular_archive_members_can_be_retained(self):
        name = 'go-entropy-retained/current-host.json'
        for mode in (stat.S_IFREG | 0o600, stat.S_IFLNK | 0o777):
            data = io.BytesIO()
            with zipfile.ZipFile(data, 'w') as writer:
                row = zipfile.ZipInfo(name); row.external_attr = mode << 16
                writer.writestr(row, b'{}')
            data.seek(0)
            artifact = materials.Artifact.__new__(materials.Artifact)
            artifact.kind, artifact.selected = 'host', {}
            artifact.archive = zipfile.ZipFile(data)
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory)/'result.json'
                if stat.S_IFMT(mode) == stat.S_IFREG:
                    artifact.extract(name, target)
                    self.assertEqual(target.read_bytes(), b'{}')
                else:
                    with self.assertRaises(RuntimeError):
                        artifact.extract(name, target)
                    self.assertFalse(target.exists())
                with self.assertRaises(RuntimeError):
                    artifact.extract('../current-host.json', Path(directory)/'escape')

    def test_replay_preserves_entire_two_variant_acceptance_loop(self):
        import inspect
        normal = ast.parse(inspect.getsource(production.qualify)).body[0]
        diagnostic = ast.parse(inspect.getsource(replay.qualify)).body[0]
        def loop(function):
            rows = [node for node in ast.walk(function) if isinstance(node, ast.For)
                    and isinstance(node.iter, ast.Call) and isinstance(node.iter.func, ast.Name)
                    and node.iter.func.id == 'enumerate' and len(node.iter.args) == 1
                    and isinstance(node.iter.args[0], ast.Name) and node.iter.args[0].id == 'projects']
            self.assertEqual(len(rows), 1)
            return ast.dump(rows[0], include_attributes=False)
        self.assertEqual(loop(normal), loop(diagnostic))
        self.assertIs(replay.make_jars, production.make_jars)
        self.assertIs(replay.capture, production.capture)
        self.assertIs(replay.negative_inputs, production.negative_inputs)
        self.assertIs(replay.verify_node, production.verify_node)
        self.assertEqual(file_identity(materials.ROOT/'tools/qualify_java_private_http.py')['sha256'],
                         'sha256:dc99932e14b8628091e8820d6551ded6f7397395e6130923f2f74f3a9de7c405')

    def test_native_mapping_keeps_each_historical_host_separate(self):
        root = Path('owned-prepared')
        selected = materials.native_products(root)
        self.assertEqual(set(selected), set(production.PRODUCTS))
        self.assertEqual(selected['latentd'], root/'host/latentd')
        self.assertEqual(selected['latent'], root/'native/latent')
        self.assertNotIn(root/'native/latentd', selected.values())


if __name__ == '__main__':
    unittest.main()
