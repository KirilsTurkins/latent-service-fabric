import copy
import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator

from tools import static_site as site
from tools.build_snapshot import SnapshotError, canonical, digest
from tools.static_fonts import prepare_primeicons


class StaticSiteCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        schema = Path(__file__).resolve().parents[2] / 'schemas/web-application.schema.json'
        cls.web_schema = Draft202012Validator(json.loads(schema.read_bytes()))

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
        self.web_schema.validate(web)
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
        self.web_schema.validate(web)
        self.assertEqual(web['routes'], [{'path': '/', 'mode': 'client', 'asset': '/index.html'}])
        self.assertEqual((left / 'public/index.html').read_bytes(), (right / 'public/index.html').read_bytes())

    def test_xml_sitemap_bytes_and_exact_media_are_preserved_without_parsing(self):
        xml = b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>'
        (self.root / 'sitemap.xml').write_bytes(xml)
        config = copy.deepcopy(self.config)
        config['assets'].append({'path': '/sitemap.xml', 'source': 'sitemap.xml'})
        output, _ = self.capture(config)
        self.assertEqual((output / 'public/sitemap.xml').read_bytes(), xml)
        web = json.loads((output / 'metadata/web-application.json').read_bytes())
        self.assertEqual(next(row['mediaType'] for row in web['assets'] if row['path'] == '/sitemap.xml'), 'application/xml')
        config['assets'][-1]['mediaType'] = 'text/xml'
        self.reject(config)
        for suffix in ('woff', 'ttf', 'eot', 'bin'):
            with self.assertRaises(SnapshotError):
                site.public_file('fonts/font.' + suffix)

    def test_font_preparation_keeps_glyphs_and_only_one_woff2_resource(self):
        package = Path(self.temp.name) / 'primeicons'
        (package / 'fonts').mkdir(parents=True)
        (package / 'package.json').write_text('{"name":"primeicons","version":"8.0.1"}')
        (package / 'LICENSE.md').write_text('Test-only fixture license')
        (package / 'fonts/primeicons.woff2').write_bytes(b'wOF2' + b'\0' * 44)
        css = "@font-face { font-family: 'primeicons'; src: url('./fonts/old.eot'); src: url('./fonts/primeicons.woff2') format('woff2'); }\n.pi-check:before { content: '\\e909'; }"
        (package / 'primeicons.css').write_text(css)
        output = Path(self.temp.name) / 'prepared-fonts'
        prepare_primeicons(package, output)
        prepared = (output / 'primeicons.css').read_text()
        self.assertNotIn('.eot', prepared)
        self.assertEqual(prepared.count('url('), 1)
        self.assertIn('.pi-check:before', prepared)
        self.assertEqual({p.name for p in output.iterdir()}, {'primeicons.css', 'primeicons.woff2', 'LICENSE.txt'})
        for unsupported in [css + '\n@import "https://example.test/other.css";', css + '\n.other { background: url(foreign.svg); }', css + css]:
            (package / 'primeicons.css').write_text(unsupported)
            rejected = Path(self.temp.name) / 'rejected-fonts'
            with self.assertRaises(SnapshotError):
                prepare_primeicons(package, rejected)
            self.assertFalse(rejected.exists())

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

    def test_optional_error_document_is_signed_html_without_rewriting_assets_or_adding_layers(self):
        original, before = self.capture()
        config = copy.deepcopy(self.config)
        config['errorDocument'] = {'profile': 'html-not-found-v1', 'document': '/guide/index.html'}
        output, after = self.capture(config, 'error-document')
        web = json.loads((output / 'metadata/web-application.json').read_bytes())
        self.web_schema.validate(web)
        self.assertEqual(web['staticRouting']['errorDocument'], config['errorDocument'])
        self.assertEqual(before['assetsDigest'], after['assetsDigest'])
        self.assertNotEqual(before['webManifestDigest'], after['webManifestDigest'])
        for asset in web['assets']:
            self.assertEqual((original / asset['layer']).read_bytes(), (output / asset['layer']).read_bytes())
        self.assertEqual(len(json.loads((output / 'package-source.json').read_bytes())['layers']), len(config['assets']) + 2)
        for value in [None, {}, {'profile': 'other-v1', 'document': '/index.html'},
                      {'profile': 'html-not-found-v1', 'document': '/missing.html'},
                      {'profile': 'html-not-found-v1', 'document': '/assets/main.js'},
                      {'profile': 'html-not-found-v1', 'document': '/_lsf/foreign/index.html'},
                      {'profile': 'html-not-found-v1', 'document': '/server/private.html'},
                      {'profile': 'html-not-found-v1', 'document': 'https://foreign.test/index.html'},
                      {'profile': 'html-not-found-v1', 'document': '/../index.html'},
                      {'profile': 'html-not-found-v1', 'document': '/index.html', 'status': 200}]:
            rejected = copy.deepcopy(self.config)
            rejected['errorDocument'] = value
            self.reject(rejected)

    def test_excessive_counts_paths_input_bytes_and_asset_bytes_fail_before_emission(self):
        config = copy.deepcopy(self.config); config['assets'] *= 64
        self.reject(config)
        config = copy.deepcopy(self.config); config['assets'][0]['path'] = '/' + 'x' * 233 + '.html'
        self.reject(config)
        with self.assertRaises(SnapshotError): site.decode(b' ' * (site.MAX_INPUT_BYTES + 1))
        with (self.root / 'assets/main.js').open('wb') as stream: stream.truncate(site.MAX_ASSET_BYTES + 1)
        self.reject(self.config)

    def test_complete_multilingual_inventory_at_the_limit_and_exact_count_diagnostics(self):
        config = copy.deepcopy(self.config)
        config['assets'] = [{'path': '/index.html', 'source': 'index.html'}]
        config['errorDocument'] = {'profile': 'html-not-found-v1', 'document': '/index.html'}
        for number in range(1, 252):
            locale = 'en' if number % 2 else 'de'
            name = f'{locale}/page-{number:03}/' + 'x' * 50 + '/' + 'y' * 50 + '.html'
            file = self.root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(f'<html lang="{locale}"><title>Page {number}</title></html>'.encode())
            config['assets'].append({'path': '/' + name, 'source': name})
        output, report = self.capture(config)
        raw = (output / 'metadata/web-application.json').read_bytes()
        self.assertGreater(len(raw), 64 * 1024)
        self.assertEqual(len(json.loads(raw)['assets']), 252)
        self.assertEqual(len(json.loads((output / 'package-source.json').read_bytes())['layers']), 254)
        schema = Path(__file__).resolve().parents[2] / 'schemas/static-site-budget.schema.json'
        Draft202012Validator(json.loads(schema.read_bytes())).validate(report['budget'])
        self.assertEqual(report['budget']['captureLimits']['publicAssetCount'],
                         {'actual': 252, 'maximum': 252, 'remaining': 0, 'unit': 'paths'})
        self.assertEqual(report['budget']['captureLimits']['webManifestBytes']['actual'], len(raw))
        self.assertEqual(report['budget']['generatedInputs']['standardPackageLayers']['remaining'], 0)
        config['assets'].append({'path': '/extra.html', 'source': 'extra.html'})
        with self.assertRaisesRegex(SnapshotError, 'asset-count: actual=253 maximum=252'):
            self.capture(config, 'too-many')
        self.assertFalse((Path(self.temp.name) / 'too-many').exists())

    def test_budget_is_exact_bounded_deterministic_and_preserves_duplicate_path_charges(self):
        config = copy.deepcopy(self.config)
        shared = b'/* same public content */' * 10
        for name in ['z.js', 'a.js', 'f.js', 'b.js', 'e.js', 'c.js']:
            (self.root / name).write_bytes(shared)
            config['assets'].append({'path': '/' + name, 'source': name})
        long_name = 'a' * 64 + '/' + 'b' * 64 + '/' + 'c' * 32 + '.css'
        long_file = self.root / long_name
        long_file.parent.mkdir(parents=True)
        long_file.write_bytes(b'')
        config['assets'].append({'path': '/' + long_name, 'source': long_name})
        output, captured = self.capture(config)
        budget = captured['budget']
        schema = Path(__file__).resolve().parents[2] / 'schemas/static-site-budget.schema.json'
        Draft202012Validator(json.loads(schema.read_bytes())).validate(budget)
        raw = (output / 'metadata/web-application.json').read_bytes()
        web = json.loads(raw)
        self.assertEqual([row['path'] for row in budget['largestAssets']], ['/a.js', '/b.js', '/c.js', '/e.js', '/f.js'])
        self.assertEqual(len(budget['largestAssets']), site.LARGEST_ASSETS)
        self.assertEqual(budget['selection']['webManifestDigest'], digest(raw))
        self.assertEqual(budget['selection']['sourceObservationDigest'], config['observations'][0]['digest'])
        logical = sum(row['size'] for row in web['assets'])
        distinct = {row['digest']: row['size'] for row in web['assets']}
        self.assertEqual(budget['captureLimits']['logicalPublicBytes']['actual'], logical)
        self.assertEqual(budget['storageObservation']['deduplicatedPublicBytes'], sum(distinct.values()))
        self.assertGreater(logical, budget['storageObservation']['deduplicatedPublicBytes'])
        self.assertEqual(budget['captureLimits']['excludedCount']['actual'], 2)
        self.assertEqual(budget['captureLimits']['longestRelativePathBytes']['actual'], len(long_name))
        self.assertEqual(budget['captureLimits']['longestPathSegmentBytes']['remaining'], 0)
        for row in budget['captureLimits'].values():
            self.assertEqual(row['remaining'], row['maximum'] - row['actual'])
        for key, filename in [('webManifestBytes', 'metadata/web-application.json'),
                              ('captureObservationBytes', 'metadata/static-observation.json'),
                              ('packageSourceBytes', 'package-source.json'), ('sbomInputsBytes', 'sbom-inputs.json')]:
            self.assertEqual(budget['generatedInputs'][key], len((output / filename).read_bytes()))
        self.assertFalse(any(budget['qualification'].values()))
        self.assertEqual(budget['nodeCapacity'], 'not-observed')
        self.assertIn('logical paths remain independently charged', site.human_budget(budget))
        reversed_config = copy.deepcopy(config)
        reversed_config['assets'].reverse()
        _, reordered = self.capture(reversed_config, 'reordered')
        self.assertEqual(reordered['budget']['largestAssets'], budget['largestAssets'])
        self.assertEqual(reordered['budget']['captureLimits']['logicalPublicBytes'], budget['captureLimits']['logicalPublicBytes'])

    def test_budget_exact_byte_limits_and_one_over_fail_before_output(self):
        payload = b'<html>' + b'x' * (site.MAX_ASSET_BYTES - 6)
        (self.root / 'index.html').write_bytes(payload)
        (self.root / 'copy.html').write_bytes(payload)
        config = copy.deepcopy(self.config)
        config['assets'] = [{'path': '/' + name, 'source': name} for name in ['index.html', 'copy.html']]
        _, captured = self.capture(config)
        limits = captured['budget']['captureLimits']
        self.assertEqual(limits['largestAssetBytes']['remaining'], 0)
        self.assertEqual(limits['logicalPublicBytes']['remaining'], 0)
        self.assertEqual(captured['budget']['storageObservation']['deduplicatedPublicBytes'], site.MAX_ASSET_BYTES)
        (self.root / 'one.js').write_bytes(b'x')
        config['assets'].append({'path': '/one.js', 'source': 'one.js'})
        with self.assertRaisesRegex(SnapshotError, f'asset-tree-bytes: actual={site.MAX_TREE_BYTES + 1} maximum={site.MAX_TREE_BYTES}'):
            self.capture(config, 'aggregate-over')
        self.assertFalse((Path(self.temp.name) / 'aggregate-over').exists())
        (self.root / 'index.html').write_bytes(payload + b'x')
        with self.assertRaisesRegex(SnapshotError, f'source-bytes: actual={site.MAX_ASSET_BYTES + 1} maximum={site.MAX_ASSET_BYTES}'):
            self.capture(config, 'asset-over')
        self.assertFalse((Path(self.temp.name) / 'asset-over').exists())

    def test_budget_uses_exact_input_and_encoded_manifest_with_no_partial_failure_summary(self):
        from unittest.mock import patch
        self.assertEqual(site.encode_input(self.config), canonical(self.config))
        oversized = copy.deepcopy(self.config)
        oversized['assets'] *= 4096
        with self.assertRaisesRegex(SnapshotError, 'input-bytes: actual='):
            self.capture(oversized, 'unbounded-descriptor')
        self.assertFalse((Path(self.temp.name) / 'unbounded-descriptor').exists())
        raw = json.dumps(self.config, indent=2).encode()
        raw += b' ' * (site.MAX_INPUT_BYTES - len(raw))
        output = Path(self.temp.name) / 'exact-input'
        captured = site.capture(self.root, self.config, output, input_raw=raw)
        self.assertEqual(captured['budget']['captureLimits']['inputDescriptorBytes']['remaining'], 0)
        self.assertEqual(captured['budget']['selection']['inputDescriptorDigest'], digest(raw))
        with self.assertRaisesRegex(SnapshotError, 'input-bytes: actual=262145 maximum=262144'):
            site.capture(self.root, self.config, Path(self.temp.name) / 'input-over', input_raw=raw + b' ')
        self.assertFalse((Path(self.temp.name) / 'input-over').exists())
        manifest_bytes = len((output / 'metadata/web-application.json').read_bytes())
        with patch.object(site, 'MAX_WEB_MANIFEST_BYTES', manifest_bytes):
            _, exact = self.capture(name='manifest-exact')
        self.assertEqual(exact['budget']['captureLimits']['webManifestBytes']['remaining'], 0)
        with patch.object(site, 'MAX_WEB_MANIFEST_BYTES', manifest_bytes - 1):
            with self.assertRaisesRegex(SnapshotError, f'web-manifest-bytes: actual={manifest_bytes} maximum={manifest_bytes - 1}'):
                self.capture(name='manifest-over')
        self.assertFalse((Path(self.temp.name) / 'manifest-over').exists())

    def test_budget_uses_the_captured_snapshot_once_and_detects_changes_during_read(self):
        from unittest.mock import patch
        original_read = site.read
        original = (self.root / 'assets/main.js').read_bytes()
        calls = []
        def mutate_after_capture(root, relative, maximum):
            calls.append(relative)
            data = original_read(root, relative, maximum)
            if relative == 'assets/main.js':
                (root / relative).write_bytes(b'misleading larger replacement after stable capture' * 10)
            return data
        with patch.object(site, 'read', side_effect=mutate_after_capture):
            output, captured = self.capture()
        self.assertEqual(len(calls), len(self.config['assets']) + len(self.config['observations']))
        self.assertEqual(len(set(calls)), len(calls))
        self.assertEqual((output / 'public/assets/main.js').read_bytes(), original)
        web = json.loads((output / 'metadata/web-application.json').read_bytes())
        row = next(row for row in web['assets'] if row['path'] == '/assets/main.js')
        self.assertEqual((row['size'], row['digest']), (len(original), digest(original)))
        self.assertEqual(captured['budget']['captureLimits']['logicalPublicBytes']['actual'], sum(row['size'] for row in web['assets']))
        fstat = site.os.fstat
        changed = False
        def change_during_read(fd):
            nonlocal changed
            before = fstat(fd)
            if not changed:
                changed = True
                (self.root / 'index.html').write_bytes(b'changed while opened')
            return before
        with patch.object(site.os, 'fstat', side_effect=change_during_read):
            with self.assertRaises((SnapshotError, OSError)):
                self.capture(name='changed-during-read')
        self.assertFalse((Path(self.temp.name) / 'changed-during-read').exists())

    def test_budget_diagnostics_do_not_change_artifact_bytes_or_provenance_claims(self):
        from unittest.mock import patch
        left, report = self.capture()
        with patch.object(site, 'LARGEST_ASSETS', 1):
            right, compact = self.capture(name='compact-report')
        self.assertNotEqual(report['budget']['largestAssets'], compact['budget']['largestAssets'])
        first = {p.relative_to(left).as_posix(): p.read_bytes() for p in left.rglob('*') if p.is_file()}
        second = {p.relative_to(right).as_posix(): p.read_bytes() for p in right.rglob('*') if p.is_file()}
        self.assertEqual(first, second)
        observation = json.loads(first['metadata/static-observation.json'])
        self.assertNotIn('budget', observation)
        self.assertEqual(observation, {key: value for key, value in report.items() if key != 'budget'})
        self.assertEqual(observation['inputObservationTrust'], 'operator-supplied')
        self.assertEqual(observation['reproducibility'], 'not-checked')
        self.assertFalse(observation['frameworkBuildExecuted'])
        self.assertNotIn(b'latent.static-site.budget.v1', b''.join(first.values()))

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
