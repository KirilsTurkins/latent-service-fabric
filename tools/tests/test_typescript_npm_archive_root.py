"""Safe original tar-root mapping; data-only controls, no npm/guest execution."""
import base64
import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import application_dependency_store as store
from tools.application_dependency_store import DependencyError
from tools.typescript_application_dependencies import cached_archive, check_unpacked_archive, npm_archive_files

FIXTURE = Path(__file__).parent/'fixtures/npm-types-buffer-xor-2.0.2.tgz'
INTEGRITY = 'sha512-OqdCua7QCTupPnJgmyGJUpxWgbuOi0IMIVslXTSePS2o+qDrDB6f2Pg44zRyqhUA5GbFAf39U8z0+mH4WG0fLQ=='


def archive(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as target:
        for name, data in entries:
            row = tarfile.TarInfo(name)
            if data is None:
                row.type = tarfile.DIRTYPE
                target.addfile(row)
            else:
                row.size = len(data)
                target.addfile(row, io.BytesIO(data))
    return output.getvalue()


class NpmArchiveRoot(unittest.TestCase):
    def test_arbitrary_single_roots_preserve_payloads_and_package_aliases(self):
        expected = {'index.js': b'exports.value=7;', 'package.json': b'{"name":"actual-name","version":"1.0.0"}',
                    'data.bin': bytes((0, 255, 1))}
        for root in ('package', 'ordinary-root', 'scope-source'):
            with self.subTest(root=root):
                raw = archive([(root+'/', None), *((root+'/'+name, data) for name, data in expected.items())])
                self.assertEqual(npm_archive_files(raw), expected)
                installed = {'alias/'+name: data for name, data in expected.items()}
                installed['alias/node_modules/child/index.js'] = b'captured separately'
                check_unpacked_archive(raw, installed, 'node_modules/alias')

    def test_actual_published_types_archive_is_sri_bound_and_kept_verbatim(self):
        raw = FIXTURE.read_bytes()
        self.assertEqual(len(raw), 1591)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), '09b105fe25242c1f5b349cfa9ed7558e8d2d2e75f9993e91aed20b53765ccf87')
        self.assertEqual('sha512-'+base64.b64encode(hashlib.sha512(raw).digest()).decode(), INTEGRITY)
        files = npm_archive_files(raw)
        self.assertEqual(set(files), {'LICENSE', 'README.md', 'index.d.ts', 'package.json'})
        self.assertIn(b'"name": "@types/buffer-xor"', files['package.json'])
        with tempfile.TemporaryDirectory() as temporary:
            digest = hashlib.sha512(raw).hexdigest()
            cache = Path(temporary)
            path = cache/'_cacache/content-v2/sha512'/digest[:2]/digest[2:4]/digest[4:]
            path.parent.mkdir(parents=True); path.write_bytes(raw)
            self.assertEqual(cached_archive(cache, INTEGRITY), raw)
            installed = {'@types/buffer-xor/'+name: data for name, data in files.items()}
            check_unpacked_archive(raw, installed, 'node_modules/@types/buffer-xor')

    def test_mixed_empty_and_rootless_archives_are_refused_including_directory_headers(self):
        cases = ([], [('index.js', b'x')], [('only-directory/', None)],
                 [('one/index.js', b'x'), ('two/index.js', b'y')],
                 [('one/index.js', b'x'), ('unrelated-empty-directory/', None)])
        for entries in cases:
            with self.subTest(entries=entries), self.assertRaisesRegex(DependencyError, 'archive-package-prefix'):
                npm_archive_files(archive(entries))

    def test_original_path_alias_type_count_and_byte_guards_remain_enforced(self):
        cases = ([('root/../outside', b'x')], [('root/a', b'x'), ('root/a', b'y')],
                 [('root/A', b'x'), ('root/a', b'y')], [('root//a', b'x')])
        for entries in cases:
            with self.subTest(entries=entries), self.assertRaises(DependencyError):
                npm_archive_files(archive(entries))
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w:gz') as target:
            row = tarfile.TarInfo('root/link'); row.type = tarfile.SYMTYPE; row.linkname = 'outside'
            target.addfile(row)
        with self.assertRaisesRegex(DependencyError, 'entry-denied'):
            npm_archive_files(output.getvalue())
        raw = archive([('root/a', b'abc'), ('root/b', b'x')])
        with patch.object(store, 'MAX_FILES', 1), self.assertRaisesRegex(DependencyError, 'entry-limit'):
            npm_archive_files(raw)
        with patch.object(store, 'MAX_EXPANDED', 2), self.assertRaisesRegex(DependencyError, 'expanded-byte-limit'):
            npm_archive_files(raw)

    def test_real_package_boundary_requires_manifest_and_every_original_byte(self):
        raw = archive([('source/package.json', b'{"name":"actual"}'), ('source/index.js', b'original')])
        original = {'alias/package.json': b'{"name":"actual"}', 'alias/index.js': b'original'}
        for name in original:
            changed = dict(original); changed[name] += b'changed'
            with self.subTest(name=name), self.assertRaisesRegex(DependencyError, 'source-differs-from-original'):
                check_unpacked_archive(raw, changed, 'node_modules/alias')
        with self.assertRaisesRegex(DependencyError, 'package-json-missing'):
            check_unpacked_archive(archive([('source/index.js', b'x')]), {'alias/index.js': b'x'}, 'node_modules/alias')


if __name__ == '__main__':
    unittest.main()
