"""Offline fixtures for the package-manager derivation; no package code executes."""
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('npm_prepare', Path(__file__).resolve().parents[1] / 'prepare.py')
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)


def archive(files, *, stamp=12):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as writer:
        for name, value in files:
            member = tarfile.TarInfo(name)
            member.mtime = stamp
            if value is None:
                member.type = tarfile.SYMTYPE
                member.linkname = '/outside'
                writer.addfile(member)
            else:
                raw = json.dumps(value).encode() if isinstance(value, dict) else value
                member.size = len(raw)
                writer.addfile(member, io.BytesIO(raw))
    return output.getvalue()


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.base = [('package/package.json', {'name': 'npm', 'version': '11.19.1'}),
                     ('package/bin/npm-cli.js', b'never executed'),
                     ('package/node_modules/ip-address/package.json', {'name': 'ip-address', 'version': '10.5.0'}),
                     ('package/node_modules/ip-address/obsolete.js', b'old removed bytes'),
                     ('package/node_modules/undici/package.json', {'name': 'undici', 'version': '6.28.0'}),
                     ('package/node_modules/brace-expansion/package.json', {'name': 'brace-expansion', 'version': '5.0.9'}),
                     ('package/node_modules/brace-expansion/obsolete.js', b'old removed brace bytes'),
                     ('package/node_modules/balanced-match/package.json', {'name': 'balanced-match', 'version': '4.0.4'})]
        self.patches = []
        for name, old, new in [('ip-address', '10.5.0', '10.7.2'), ('undici', '6.28.0', '6.28.1'),
                               ('brace-expansion', '5.0.9', '5.0.12')]:
            manifest = {'name': name, 'version': new}
            if name == 'brace-expansion':
                manifest['dependencies'] = {'balanced-match': '^4.0.2'}
            raw = archive([('package/package.json', manifest),
                           ('package/index.js', b'patched bytes')])
            self.patches.append(({'name': name, 'from': old, 'version': new, 'integrity': prepare.integrity(raw)}, raw))

    def test_deterministic_tar_ignores_input_order_timestamps_and_gzip(self):
        a = prepare.compose(archive(self.base), self.patches)
        b = prepare.compose(archive(list(reversed(self.base)), stamp=4567), self.patches)
        self.assertEqual(a, b)

    def test_complete_packages_replaced_without_stale_files(self):
        raw = prepare.compose(archive(self.base), self.patches)
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as reader:
            self.assertNotIn('package/node_modules/ip-address/obsolete.js', reader.getnames())
            self.assertNotIn('package/node_modules/brace-expansion/obsolete.js', reader.getnames())
            self.assertEqual(reader.extractfile('package/bin/npm-cli.js').read(), b'never executed')
            for pin, _ in self.patches:
                data = reader.extractfile(f'package/node_modules/{pin["name"]}/package.json').read()
                self.assertEqual(json.loads(data)['version'], pin['version'])
            for member in reader:
                self.assertTrue(member.isfile())
                self.assertEqual((member.uid, member.gid, member.mtime), (0, 0, 0))

    def test_unexpected_original_or_missing_replacements_rejected(self):
        for patches in [[], self.patches[:1], self.patches[:2], [self.patches[0], self.patches[0]]]:
            with self.subTest(patches=len(patches)), self.assertRaises(ValueError):
                prepare.compose(archive(self.base), patches)
        changed = list(self.base)
        changed[0] = (changed[0][0], {'name': 'npm', 'version': '12.1.0'})
        with self.assertRaises(ValueError):
            prepare.compose(archive(changed), self.patches)

    def test_new_dependency_graph_requires_review(self):
        pin, _ = self.patches[0]
        raw = archive([('package/package.json', {'name': pin['name'], 'version': pin['version'],
                                                'dependencies': {'unexpected': '1.0.0'}})])
        with self.assertRaisesRegex(ValueError, 'graph requires review'):
            prepare.compose(archive(self.base), [(pin, raw), self.patches[1]])

    def test_brace_uses_only_the_exact_existing_reviewed_dependency(self):
        raw = prepare.compose(archive(self.base), self.patches)
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as reader:
            dependency = json.loads(reader.extractfile('package/node_modules/balanced-match/package.json').read())
            self.assertEqual(dependency, {'name': 'balanced-match', 'version': '4.0.4'})
            replacement = json.loads(reader.extractfile('package/node_modules/brace-expansion/package.json').read())
            self.assertEqual(replacement['dependencies'], {'balanced-match': '^4.0.2'})

    def test_brace_rejects_dependency_changes_and_shadowed_resolution(self):
        name = 'package/node_modules/balanced-match/package.json'
        for manifest in [{'name': 'balanced-match', 'version': '4.0.3'},
                         {'name': 'different', 'version': '4.0.4'},
                         {'name': 'balanced-match', 'version': '4.0.4', 'dependencies': {'other': '1.0.0'}}]:
            changed = [(key, manifest if key == name else value) for key, value in self.base]
            with self.subTest(manifest=manifest), self.assertRaisesRegex(ValueError, 'dependency graph'):
                prepare.compose(archive(changed), self.patches)
        shadow = self.base + [('package/node_modules/brace-expansion/node_modules/balanced-match/package.json',
                              {'name': 'balanced-match', 'version': '4.0.3'})]
        with self.assertRaisesRegex(ValueError, 'shadowed'):
            prepare.compose(archive(shadow), self.patches)

    def test_replacements_reject_unreviewed_requirements_and_hidden_package_graphs(self):
        pin, _ = self.patches[-1]
        manifest = {'name': pin['name'], 'version': pin['version'], 'dependencies': {'balanced-match': '^4.0.2'}}
        for field, value in [('dependencies', {'balanced-match': '*'}),
                             ('optionalDependencies', {'other': '1.0.0'}),
                             ('peerDependencies', {'other': '1.0.0'}),
                             ('bundleDependencies', ['other']), ('bundledDependencies', ['other'])]:
            raw = archive([('package/package.json', {**manifest, field: value})])
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'graph requires review'):
                prepare.compose(archive(self.base), self.patches[:-1] + [(pin, raw)])
        raw = archive([('package/package.json', manifest), ('package/node_modules/hidden/index.js', b'not allowed')])
        with self.assertRaisesRegex(ValueError, 'graph requires review'):
            prepare.compose(archive(self.base), self.patches[:-1] + [(pin, raw)])

    def test_embedded_lock_cannot_silently_disagree(self):
        with self.assertRaisesRegex(ValueError, 'embedded npm lock'):
            prepare.compose(archive(self.base + [('package/npm-shrinkwrap.json', b'{}')]), self.patches)

    def test_links_traversal_absolute_and_duplicate_paths_rejected(self):
        for files in [[('package/link', None)], [('package/../escape', b'x')],
                      [('/package/absolute', b'x')], [('package/a', b'x'), ('package/a', b'y')],
                      [('package/a\\b', b'x')], [('./package/a', b'x')]]:
            with self.subTest(files=files), self.assertRaises(ValueError):
                prepare.unpack(archive(files))

    def test_expanded_and_entry_limits_checked(self):
        with patch.object(prepare, 'EXPANDED_LIMIT', 2), self.assertRaisesRegex(ValueError, 'expanded'):
            prepare.unpack(archive([('package/large', b'abc')]))
        with self.assertRaises(ValueError):
            prepare.unpack(archive([(f'package/{i}', b'') for i in range(6001)]))

    def test_cached_bytes_are_authenticated_without_network(self):
        pin, raw = self.patches[0]
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            file = cache / f'{pin["name"]}-{pin["version"]}.tgz'
            file.write_bytes(raw)
            with patch.object(prepare.urllib.request, 'build_opener', side_effect=AssertionError('network')):
                self.assertEqual(prepare.acquire(pin, cache, False), raw)
                file.write_bytes(raw + b'edited')
                with self.assertRaisesRegex(ValueError, 'integrity'):
                    prepare.acquire(pin, cache, True)
            file.unlink()
            with self.assertRaisesRegex(ValueError, 'offline input missing'):
                prepare.acquire(pin, cache, True)

    def test_download_bound_and_invalid_identity_rejected(self):
        pin, raw = self.patches[0]
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            (cache / f'{pin["name"]}-{pin["version"]}.tgz').write_bytes(raw)
            with patch.object(prepare, 'LIMIT', 2), self.assertRaises(ValueError):
                prepare.acquire(pin, cache, True)
            with self.assertRaises(ValueError):
                prepare.acquire({**pin, 'name': '../escape'}, cache, True)

    def test_locked_preparation_and_failed_refresh_preserve_last_good_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / 'inputs'
            cache.mkdir()
            base = archive(self.base)
            (cache / 'npm-11.19.1.tgz').write_bytes(base)
            for pin, raw in self.patches:
                (cache / f'{pin["name"]}-{pin["version"]}.tgz').write_bytes(raw)
            config = {'schema': 1, 'profile': prepare.PROFILE,
                      'base': {'name': 'npm', 'version': '11.19.1', 'integrity': prepare.integrity(base)},
                      'patches': [pin for pin, _ in self.patches]}
            (root / 'source.json').write_text(json.dumps(config))
            target = root / 'generated.tar'
            with patch.multiple(prepare, HERE=root, CACHE=cache, OUTPUT=target):
                actual = prepare.prepare(offline=True, refresh=True)
                original = target.read_bytes()
                row = {'resolved': 'file:../../target/website-package-manager/' + prepare.PROFILE + '.tar',
                       'integrity': actual}
                (root / 'package-lock.json').write_text(json.dumps({'packages': {'node_modules/npm': row}}))
                self.assertEqual(prepare.prepare(offline=True), actual)
                row['integrity'] = 'invalid'
                (root / 'package-lock.json').write_text(json.dumps({'packages': {'node_modules/npm': row}}))
                with self.assertRaisesRegex(ValueError, 'reviewed package lock'):
                    prepare.prepare(offline=True)
                self.assertEqual(target.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
