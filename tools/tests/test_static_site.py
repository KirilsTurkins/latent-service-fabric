import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools import static_site as site
from tools.build_snapshot import SnapshotError, canonical, digest


class StaticSiteCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'build'
        self.root.mkdir()
        for name, data in {'index.html': b'<h1>version A</h1>', 'guide/index.html': b'<h1>guide</h1>',
                           'assets/main.js': b'export const version="A";', 'assets/main.css': b'h1{color:blue}',
                           'server/private.mjs': b'private backend', '.env': b'private token'}.items():
            file = self.root / name
            file.parent.mkdir(exist_ok=True, parents=True)
            file.write_bytes(data)
        observations = []
        for kind in ['source', 'toolchain', 'build']:
            raw = canonical({'kind': kind, 'observed': 'test-only'})
            (self.root / (kind + '.json')).write_bytes(raw)
            observations.append({'kind': kind, 'source': kind + '.json', 'digest': digest(raw)})
        self.config = {'formatVersion': 1, 'profile': 'static-site-input-v1', 'name': 'static-example', 'version': '1.0.0',
                       'assets': [{'path': '/' + name, 'source': name} for name in
                                  ['index.html', 'guide/index.html', 'assets/main.js', 'assets/main.css']],
                       'entryDocument': '/index.html', 'directoryIndex': {'mode': 'redirect', 'document': '/index.html'},
                       'fallback': {'mode': 'none'}, 'excluded': ['server/private.mjs', '.env'], 'observations': observations}

    def capture(self, config=None, name='inputs'):
        output = Path(self.temp.name) / name
        result = site.capture(self.root, config or self.config, output)
        return output, result

    def reject(self, config):
        output = Path(self.temp.name) / 'rejected'
        with self.assertRaises((SnapshotError, OSError)):
            site.capture(self.root, config, output)
        self.assertFalse(output.exists(), 'rejection must precede writing package inputs')

    def test_deterministic_sorted_capture_binds_public_bytes_routing_and_private_observation_refs(self):
        left, report = self.capture()
        config = copy.deepcopy(self.config)
        config['assets'].reverse()
        config['observations'].reverse()
        right, _ = self.capture(config, 'again')
        first = {p.relative_to(left).as_posix(): p.read_bytes() for p in left.rglob('*') if p.is_file()}
        second = {p.relative_to(right).as_posix(): p.read_bytes() for p in right.rglob('*') if p.is_file()}
        self.assertEqual(first, second)
        self.assertNotIn('server/private.mjs', first)
        self.assertNotIn('.env', first)
        self.assertNotIn(b'private token', b''.join(first.values()))
        web = json.loads(first['metadata/web-application.json'])
        self.assertNotIn('renderer', web)
        self.assertEqual(web['routes'], [])
        self.assertEqual([a['path'] for a in web['assets']], sorted(a['path'] for a in web['assets']))
        self.assertEqual(web['assetsDigest'], report['assetsDigest'])
        self.assertFalse(report['frameworkBuildExecuted'])
        self.assertEqual(report['inputObservationTrust'], 'operator-supplied')
        recipe = json.loads(first['package-source.json'])
        self.assertEqual(recipe['kind'], 'browser-assets')
        self.assertEqual(recipe['entrypoint'], 'public/index.html')
        inventory = json.loads(first['sbom-inputs.json'])
        self.assertEqual({r['path'] for r in recipe['layers']}, {r['path'] for r in inventory['entries']})

    def test_csr_entry_is_explicit_and_routing_changes_manifest_identity_without_changing_public_bytes(self):
        left, original = self.capture()
        config = copy.deepcopy(self.config)
        config['directoryIndex']['mode'] = 'disabled'
        config['fallback'] = {'mode': 'spa', 'document': '/index.html'}
        right, changed = self.capture(config, 'csr')
        self.assertEqual(original['assetsDigest'], changed['assetsDigest'])
        self.assertNotEqual(original['webManifestDigest'], changed['webManifestDigest'])
        web = json.loads((right / 'metadata/web-application.json').read_bytes())
        self.assertEqual(web['routes'], [{'path': '/', 'mode': 'client', 'asset': '/index.html'}])
        self.assertEqual((left / 'public/index.html').read_bytes(), (right / 'public/index.html').read_bytes())

    def test_closed_input_rejects_duplicate_fields_unknown_authority_and_executable_hooks(self):
        with self.assertRaises(SnapshotError):
            site.decode(b'{"assets":[],"assets":[]}')
        for field, value in [('command', 'npm run build'), ('tenant', 'foreign'), ('hostname', 'evil.test'),
                             ('root', '/etc'), ('postBuild', ['sh', '-c', 'false'])]:
            config = copy.deepcopy(self.config); config[field] = value
            self.reject(config)
        for version in ['01.0.0', '1.0.0-01', '1.0.0-a..b', '1.0.0-', '1.0.0+']:
            config = copy.deepcopy(self.config); config['version'] = version
            self.reject(config)

    def test_paths_cannot_alias_escape_reserved_namespace_or_collide_by_case(self):
        for name in ['/../secret.js', '//assets/main.js', '/assets//main.js', '/assets/%2fmain.js',
                     '/assets\\main.js', '/_lsf/main.js', '/_LSF/main.js', '/assets/./main.js',
                     '/assets/main.js?x=1', '/assets/main.js#x', '/C:/main.js']:
            config = copy.deepcopy(self.config); config['assets'][2]['path'] = name
            self.reject(config)
        for field in ['path', 'source']:
            config = copy.deepcopy(self.config)
            config['assets'].append({'path': '/extra.js', 'source': 'assets/main.js'})
            config['assets'][-1][field] = config['assets'][2][field].upper()
            self.reject(config)

    def test_explicit_mapping_still_rejects_obvious_server_private_maps_and_unsupported_media(self):
        for name in ['server/private.mjs', 'assets/main.js.map', '.env', 'assets/private/key.js',
                     'assets/credentials.json', 'assets/main.server.js', 'assets/unknown.bin']:
            config = copy.deepcopy(self.config)
            config['assets'].append({'path': '/' + name, 'source': name})
            self.reject(config)
        config = copy.deepcopy(self.config); config['assets'][2]['mediaType'] = 'text/html'
        self.reject(config)
        config = copy.deepcopy(self.config); config['assets'][2]['source'] = 'index.html'
        self.reject(config)

    def test_excluded_files_and_duplicate_source_aliases_cannot_be_published(self):
        config = copy.deepcopy(self.config); config['excluded'].append('assets/main.js')
        self.reject(config)
        config = copy.deepcopy(self.config); config['assets'].append({'path': '/other.js', 'source': 'assets/main.js'})
        self.reject(config)

    def test_entry_index_and_fallback_must_be_html_in_the_same_selected_inventory(self):
        for target in ['/missing.html', '/assets/main.js', '/_lsf/foreign/index.html']:
            for field in ['entry', 'index', 'fallback']:
                config = copy.deepcopy(self.config)
                if field == 'entry': config['entryDocument'] = target
                elif field == 'index': config['directoryIndex']['document'] = target
                else: config['fallback'] = {'mode': 'spa', 'document': target}
                self.reject(config)
        for fallback in [{'mode': 'none', 'document': '/index.html'}, {'mode': 'spa'}, {'mode': 'rewrite'}]:
            config = copy.deepcopy(self.config); config['fallback'] = fallback
            self.reject(config)

    def test_excessive_counts_paths_input_bytes_and_asset_bytes_fail_before_emission(self):
        config = copy.deepcopy(self.config); config['assets'] *= 31
        self.reject(config)
        config = copy.deepcopy(self.config); config['assets'][0]['path'] = '/' + 'x' * 233 + '.html'
        self.reject(config)
        with self.assertRaises(SnapshotError): site.decode(b' ' * (site.MAX_INPUT_BYTES + 1))
        with (self.root / 'assets/main.js').open('wb') as stream: stream.truncate(site.MAX_ASSET_BYTES + 1)
        self.reject(self.config)

    def test_missing_foreign_or_changed_observation_is_not_accepted_as_build_proof(self):
        for change in ['digest', 'missing', 'foreign', 'kind']:
            config = copy.deepcopy(self.config)
            if change == 'digest': config['observations'][0]['digest'] = 'sha256:' + '0' * 64
            elif change == 'missing': config['observations'].pop()
            elif change == 'foreign': config['observations'][0]['source'] = '../source.json'
            else: config['observations'][0]['kind'] = 'builder-secret'
            self.reject(config)
        (self.root / 'source.json').write_bytes(b'')
        config = copy.deepcopy(self.config); config['observations'][0]['digest'] = digest(b'')
        self.reject(config)

    def test_symlink_files_and_directories_are_rejected_before_reading_outside_output_root(self):
        outside = Path(self.temp.name) / 'outside.js'; outside.write_bytes(b'private')
        link = self.root / 'linked.js'
        try: link.symlink_to(outside)
        except OSError: self.skipTest('host does not permit symlink creation')
        config = copy.deepcopy(self.config); config['assets'].append({'path': '/linked.js', 'source': 'linked.js'})
        self.reject(config)
        directory = self.root / 'linked'; directory.symlink_to(outside.parent, target_is_directory=True)
        config['assets'][-1] = {'path': '/linked.js', 'source': 'linked/outside.js'}
        self.reject(config)
        with self.assertRaises(SnapshotError):
            site.capture(self.root, self.config, directory / 'package-inputs')

    def test_destination_cannot_overwrite_input_existing_data_or_follow_a_link(self):
        with self.assertRaises(SnapshotError): site.capture(self.root, self.config, self.root / 'inputs')
        output, _ = self.capture()
        with self.assertRaises(SnapshotError): site.capture(self.root, self.config, output)


if __name__ == '__main__':
    unittest.main()
