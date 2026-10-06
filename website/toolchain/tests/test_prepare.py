"""Offline fixtures for the package-manager derivation; no package code executes."""
import importlib.util
import errno
import http.client
import http.server
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import threading
import ssl
import time
import types
import unittest
from unittest.mock import Mock, patch

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
                     ('package/node_modules/http-cache-semantics/package.json', {'name': 'http-cache-semantics', 'version': '4.2.0'}),
                     ('package/node_modules/http-cache-semantics/obsolete.js', b'old removed cache bytes'),
                     ('package/node_modules/postcss-selector-parser/package.json', {'name': 'postcss-selector-parser', 'version': '7.1.4',
                         'dependencies': {'cssesc': '^3.0.0', 'util-deprecate': '^1.0.2'}}),
                     ('package/node_modules/postcss-selector-parser/obsolete.js', b'old removed selector bytes'),
                     ('package/node_modules/cssesc/package.json', {'name': 'cssesc', 'version': '3.0.0'}),
                     ('package/node_modules/util-deprecate/package.json', {'name': 'util-deprecate', 'version': '1.0.2'}),
                     ('package/node_modules/brace-expansion/package.json', {'name': 'brace-expansion', 'version': '5.0.9',
                         'dependencies': {'balanced-match': '^4.0.2'}}),
                     ('package/node_modules/brace-expansion/obsolete.js', b'old removed brace bytes'),
                     ('package/node_modules/balanced-match/package.json', {'name': 'balanced-match', 'version': '4.0.4'})]
        self.patches = []
        for name, old, new in [('ip-address', '10.5.0', '10.7.2'), ('undici', '6.28.0', '6.28.1'),
                               ('http-cache-semantics', '4.2.0', '4.3.0'),
                               ('postcss-selector-parser', '7.1.4', '7.1.6'),
                               ('brace-expansion', '5.0.9', '5.0.12')]:
            manifest = {'name': name, 'version': new}
            if name == 'brace-expansion':
                manifest['dependencies'] = {'balanced-match': '^4.0.2'}
            elif name == 'postcss-selector-parser':
                manifest['dependencies'] = {'cssesc': '^3.0.0', 'util-deprecate': '^1.0.2'}
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
            self.assertNotIn('package/node_modules/http-cache-semantics/obsolete.js', reader.getnames())
            self.assertNotIn('package/node_modules/postcss-selector-parser/obsolete.js', reader.getnames())
            balanced = json.loads(reader.extractfile('package/node_modules/balanced-match/package.json').read())
            self.assertEqual(balanced['version'], '4.0.4')
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
            prepare.compose(archive(self.base), [(pin, raw), *self.patches[1:]])
        brace_pin, _ = self.patches[-1]
        for graph in ({}, {'balanced-match': '^5.0.0'}, {'unexpected': '1.0.0'}):
            raw = archive([('package/package.json', {'name': 'brace-expansion', 'version': '5.0.12', 'dependencies': graph})])
            with self.subTest(graph=graph), self.assertRaisesRegex(ValueError, 'graph requires review'):
                prepare.compose(archive(self.base), [*self.patches[:-1], (brace_pin, raw)])
        for graph in ({}, {'balanced-match': '^5.0.0'}, {'unexpected': '1.0.0'}):
            changed = [(path, {**value, 'dependencies': graph}
                        if path == 'package/node_modules/brace-expansion/package.json' else value)
                       for path, value in self.base]
            with self.subTest(original_graph=graph), self.assertRaisesRegex(ValueError, 'graph requires review'):
                prepare.compose(archive(changed), self.patches)
        for version in ('4.0.1', '5.0.0'):
            changed = [(path, {'name': 'balanced-match', 'version': version} if path == 'package/node_modules/balanced-match/package.json' else value)
                       for path, value in self.base]
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, 'graph requires review'):
                prepare.compose(archive(changed), self.patches)

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

    def test_selector_uses_only_the_existing_exact_dependencies(self):
        raw = prepare.compose(archive(self.base), self.patches)
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as reader:
            for name, version in [('cssesc', '3.0.0'), ('util-deprecate', '1.0.2')]:
                dependency = json.loads(reader.extractfile(f'package/node_modules/{name}/package.json').read())
                self.assertEqual(dependency, {'name': name, 'version': version})
            replacement = json.loads(reader.extractfile('package/node_modules/postcss-selector-parser/package.json').read())
            self.assertEqual(replacement['version'], '7.1.6')
            self.assertEqual(replacement['dependencies'], {'cssesc': '^3.0.0', 'util-deprecate': '^1.0.2'})

    def test_selector_rejects_changed_dependencies_and_shadowed_resolution(self):
        for name, version in [('cssesc', '3.0.0'), ('util-deprecate', '1.0.2')]:
            location = f'package/node_modules/{name}/package.json'
            for manifest in [{'name': name, 'version': '0.0.0'}, {'name': 'different', 'version': version},
                             {'name': name, 'version': version, 'dependencies': {'other': '1.0.0'}},
                             {'name': name, 'version': version, 'optionalDependencies': {'other': '1.0.0'}},
                             {'name': name, 'version': version, 'peerDependencies': {'other': '1.0.0'}},
                             {'name': name, 'version': version, 'bundleDependencies': ['other']},
                             {'name': name, 'version': version, 'bundledDependencies': ['other']}]:
                changed = [(key, manifest if key == location else value) for key, value in self.base]
                with self.subTest(name=name, manifest=manifest), self.assertRaisesRegex(ValueError, 'dependency graph'):
                    prepare.compose(archive(changed), self.patches)
        shadow = self.base + [('package/node_modules/postcss-selector-parser/node_modules/cssesc/package.json',
                              {'name': 'cssesc', 'version': '3.0.0'})]
        with self.assertRaisesRegex(ValueError, 'dependency graph'):
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
            repairs = []
            library = None
            for name, version, profile, names, dependencies in [
                ('braces', '3.0.3', 'braces-3.0.3-lsf-depth-v1',
                 ['lib/utils.js', 'lib/compile.js', 'lib/expand.js', 'lib/stringify.js', 'lib/parse.js'],
                 {'fill-range': '^7.1.1'}),
                ('http-cache-semantics', '4.3.0', 'http-cache-semantics-4.3.0-lsf-cache-v1', ['index.js'], {})]:
                pin, raw = next(((pin, raw) for pin, raw in self.patches if pin['name'] == name), (None, None))
                if pin is None:
                    raw = archive([('package/package.json', {'name': name, 'version': version, 'dependencies': dependencies})]
                                  + [('package/' + path, b'patched bytes') for path in names])
                    pin = {'name': name, 'version': version, 'integrity': prepare.integrity(raw)}
                    library = pin
                    (cache / f'{name}-{version}.tgz').write_bytes(raw)
                document = {'schema': 1, 'profile': profile, 'name': name, 'version': version,
                            'upstreamIntegrity': pin['integrity'], 'files': [
                                {'path': path, 'beforeSha256': hashlib.sha256(b'patched bytes').hexdigest(),
                                 'afterSha256': hashlib.sha256(b'repaired bytes').hexdigest(),
                                 'edits': [{'before': 'patched bytes', 'after': 'repaired bytes', 'count': 1}]}
                                for path in names]}
                encoded = (json.dumps(document) + '\n').encode()
                repair_path = root / 'repairs' / (name + '.json')
                repair_path.parent.mkdir(exist_ok=True)
                repair_path.write_bytes(encoded)
                repairs.append({'path': 'repairs/' + name + '.json', 'sha256': hashlib.sha256(encoded).hexdigest()})
            config = {'schema': 1, 'profile': prepare.PROFILE,
                      'base': {'name': 'npm', 'version': '11.19.1', 'integrity': prepare.integrity(base)},
                      'patches': [pin for pin, _ in self.patches], 'libraries': [library], 'repairs': repairs}
            (root / 'source.json').write_text(json.dumps(config))
            target = root / 'generated.tar'
            with patch.multiple(prepare, ROOT=root, HERE=root, CACHE=cache, OUTPUT=target):
                actual = prepare.prepare(offline=True, refresh=True)
                original = target.read_bytes()
                row = {'resolved': 'file:../../target/website-package-manager/' + prepare.PROFILE + '.tar',
                       'integrity': actual}
                (root / 'package-lock.json').write_text(json.dumps({'packages': {'node_modules/npm': row}}))
                for directory, relative in [('website', '../'), ('examples/framework-compatibility', '../../')]:
                    path = root / directory / 'package-lock.json'
                    path.parent.mkdir(parents=True, exist_ok=True)
                    rows = {f'node_modules/{document["name"]}': {
                                'version': document['version'],
                                'resolved': 'file:' + relative + 'target/website-package-manager/' + document['profile'] + '.tar',
                                'integrity': prepare.integrity((root / (document['profile'] + '.tar')).read_bytes())}
                            for repair in repairs
                            for document in [json.loads((root / repair['path']).read_bytes())]}
                    path.write_text(json.dumps({'packages': rows}))
                self.assertEqual(prepare.prepare(offline=True), actual)
                row['integrity'] = 'invalid'
                (root / 'package-lock.json').write_text(json.dumps({'packages': {'node_modules/npm': row}}))
                with self.assertRaisesRegex(ValueError, 'reviewed package lock'):
                    prepare.prepare(offline=True)
                self.assertEqual(target.read_bytes(), original)


class TransportTests(unittest.TestCase):
    class Clock:
        value = 100.0
        def __call__(self):
            return self.value

    class Response:
        def __init__(self, parts, *, clock=None, costs=None, length=None):
            self.parts = list(parts)
            self.clock, self.costs, self.length = clock, list(costs or []), length
            self.closed = False
            self.timeouts, self.reads, self.received = [], [], 0
            self.fp = types.SimpleNamespace(raw=types.SimpleNamespace(_sock=self))
        def settimeout(self, value):
            self.timeouts.append(value)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.closed = True
        def read1(self, amount):
            self.reads.append(amount)
            if self.costs:
                cost = self.costs.pop(0)
                if cost >= self.timeouts[-1]:
                    self.clock.value += self.timeouts[-1]
                    raise TimeoutError('read timeout')
                self.clock.value += cost
            part = self.parts.pop(0) if self.parts else b''
            if isinstance(part, BaseException):
                raise part
            if len(part) > amount:
                self.parts.insert(0, part[amount:])
                part = part[:amount]
            self.received += len(part)
            if self.length is not None:
                self.length -= len(part)
            return part

    def setUp(self):
        self.raw = b'authenticated full archive'
        self.pin = {'name': 'example', 'version': '1.2.3', 'integrity': prepare.integrity(self.raw)}

    def acquire(self, opener, cache):
        with patch.object(prepare.urllib.request, 'build_opener', return_value=opener):
            return prepare.acquire(self.pin, cache, False)

    def test_transport_open_retries_only_reset_timeout_and_tls_eof(self):
        for error in (ConnectionResetError(104, 'reset'),
                      prepare.urllib.error.URLError(ConnectionResetError(104, 'reset')),
                      TimeoutError('timeout'), prepare.urllib.error.URLError(TimeoutError('timeout')),
                      ssl.SSLEOFError('peer EOF'), http.client.RemoteDisconnected('peer EOF')):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as temporary:
                response = self.Response([self.raw], length=len(self.raw))
                opener = types.SimpleNamespace(open=Mock(side_effect=[error, response]))
                cache = Path(temporary) / 'inputs'
                self.assertEqual(self.acquire(opener, cache), self.raw)
                self.assertEqual(opener.open.call_count, 2)
                self.assertTrue(response.closed)
                self.assertEqual((cache / 'example-1.2.3.tgz').read_bytes(), self.raw)
                self.assertEqual(len(list(cache.iterdir())), 1)

    def test_partial_reset_discarded_before_authenticated_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = self.Response([b'bad partial', ConnectionResetError(104, 'reset')])
            second = self.Response([self.raw], length=len(self.raw))
            opener = types.SimpleNamespace(open=Mock(side_effect=[first, second]))
            cache = Path(temporary) / 'inputs'
            self.assertEqual(self.acquire(opener, cache), self.raw)
            self.assertTrue(first.closed and second.closed)
            self.assertEqual((cache / 'example-1.2.3.tgz').read_bytes(), self.raw)

    def test_declared_partial_body_eof_retries_and_preserves_total_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = self.Response([b'x', b''], length=len(self.raw))
            second = self.Response([self.raw], length=len(self.raw))
            opener = types.SimpleNamespace(open=Mock(side_effect=[first, second]))
            with patch.object(prepare, 'LIMIT', len(self.raw) + 1):
                self.assertEqual(self.acquire(opener, Path(temporary) / 'inputs'), self.raw)
            self.assertEqual(first.received + second.received, len(self.raw) + 1)
            self.assertTrue(first.closed and second.closed)

    def test_permanent_errors_are_never_retried(self):
        errors = [ssl.SSLCertVerificationError('untrusted certificate'),
                  prepare.urllib.error.URLError(ssl.SSLCertVerificationError('untrusted certificate')),
                  ssl.SSLError('protocol error'), ValueError('unexpected registry redirect'),
                  OSError(errno.ENOSPC, 'disk failure'),
                  prepare.urllib.error.URLError('unclassified transport failure')]
        errors += [prepare.urllib.error.HTTPError('https://registry.npmjs.org', status, 'HTTP', {}, None)
                   for status in (401, 403, 404, 429, 500, 503)]
        for error in errors:
            with self.subTest(error=repr(error)), tempfile.TemporaryDirectory() as temporary:
                opener = types.SimpleNamespace(open=Mock(side_effect=error))
                cache = Path(temporary) / 'inputs'
                with self.assertRaises(type(error)):
                    self.acquire(opener, cache)
                self.assertEqual(opener.open.call_count, 1)
                self.assertFalse(cache.exists())

    def test_checksum_and_oversized_archive_do_not_retry(self):
        for raw, limit in ((b'changed bytes', prepare.LIMIT), (self.raw, 2)):
            with self.subTest(limit=limit), tempfile.TemporaryDirectory() as temporary:
                response = self.Response([raw], length=len(raw))
                opener = types.SimpleNamespace(open=Mock(return_value=response))
                cache = Path(temporary) / 'inputs'
                with patch.object(prepare, 'LIMIT', limit), self.assertRaises(ValueError):
                    self.acquire(opener, cache)
                self.assertEqual(opener.open.call_count, 1)
                self.assertLessEqual(response.received, limit + 1)
                self.assertTrue(response.closed)
                self.assertFalse(cache.exists())

    def test_failed_partial_body_budget_cannot_be_reset_by_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = self.Response([b'123456', ConnectionResetError(104, 'reset')])
            second = self.Response([self.raw], length=len(self.raw))
            opener = types.SimpleNamespace(open=Mock(side_effect=[first, second]))
            cache = Path(temporary) / 'inputs'
            with patch.object(prepare, 'LIMIT', 7), self.assertRaisesRegex(ValueError, 'cumulative'):
                self.acquire(opener, cache)
            self.assertEqual(first.received + second.received, 8)
            self.assertEqual(second.reads, [2])
            self.assertTrue(first.closed and second.closed)
            self.assertFalse(cache.exists())

    def test_incomplete_read_exception_partial_counts_toward_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            response = self.Response([http.client.IncompleteRead(b'12345678', 2)])
            opener = types.SimpleNamespace(open=Mock(return_value=response))
            cache = Path(temporary) / 'inputs'
            with patch.object(prepare, 'LIMIT', 7), self.assertRaisesRegex(ValueError, 'cumulative'):
                self.acquire(opener, cache)
            self.assertEqual(opener.open.call_count, 1)
            self.assertTrue(response.closed)
            self.assertFalse(cache.exists())

    def test_three_attempts_share_original_thirty_second_budget(self):
        clock = self.Clock()
        timeouts = []
        def denied(url, *, timeout):
            timeouts.append(timeout)
            clock.value += timeout
            raise TimeoutError('bounded inactivity')
        opener = types.SimpleNamespace(open=Mock(side_effect=denied))
        with tempfile.TemporaryDirectory() as temporary, patch.object(prepare.time, 'monotonic', clock):
            with self.assertRaises(TimeoutError):
                self.acquire(opener, Path(temporary) / 'inputs')
        self.assertEqual(timeouts, [10, 10, 10])
        self.assertEqual(clock.value, 130)
        self.assertEqual(opener.open.call_count, 3)

    def test_body_reads_use_remaining_shared_deadline(self):
        clock = self.Clock()
        response = self.Response([b'a', b'b', b'c', self.raw], clock=clock, costs=[9, 9, 9, 9])
        opener = types.SimpleNamespace(open=Mock(return_value=response))
        with tempfile.TemporaryDirectory() as temporary, patch.object(prepare.time, 'monotonic', clock):
            cache = Path(temporary) / 'inputs'
            with self.assertRaises(TimeoutError):
                self.acquire(opener, cache)
            self.assertFalse(cache.exists())
        self.assertEqual(response.timeouts, [10, 10, 10, 3])
        self.assertEqual(clock.value, 130)
        self.assertEqual(opener.open.call_count, 1)
        self.assertTrue(response.closed)

    def test_fast_failures_stop_after_three_attempts(self):
        opener = types.SimpleNamespace(open=Mock(side_effect=ConnectionResetError(104, 'reset')))
        with tempfile.TemporaryDirectory() as temporary, self.assertRaises(ConnectionResetError):
            self.acquire(opener, Path(temporary) / 'inputs')
        self.assertEqual(opener.open.call_count, 3)

    def test_disk_failure_after_download_does_not_retry_network(self):
        response = self.Response([self.raw], length=len(self.raw))
        opener = types.SimpleNamespace(open=Mock(return_value=response))
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(Path, 'mkdir', side_effect=OSError(errno.ENOSPC, 'disk full')):
                with self.assertRaises(OSError):
                    self.acquire(opener, Path(temporary) / 'inputs')
        self.assertEqual(opener.open.call_count, 1)
        self.assertTrue(response.closed)

    def test_changed_pin_is_not_retried_or_cached(self):
        response = self.Response([self.raw], length=len(self.raw))
        def changed(url, *, timeout):
            self.pin['integrity'] = prepare.integrity(b'different source')
            return response
        opener = types.SimpleNamespace(open=Mock(side_effect=changed))
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / 'inputs'
            with self.assertRaisesRegex(ValueError, 'integrity'):
                self.acquire(opener, cache)
            self.assertFalse(cache.exists())
        self.assertEqual(opener.open.call_count, 1)

    def test_real_http_response_partial_eof_then_authenticated_success(self):
        calls, body = [], self.raw
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append(self.path)
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body[:1] if len(calls) == 1 else body)
                self.wfile.flush()
                self.close_connection = True
            def log_message(self, *args):
                pass
        server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
        thread.start()
        try:
            local = prepare.urllib.request.build_opener(prepare.urllib.request.ProxyHandler({}), prepare.NoRedirect())
            with tempfile.TemporaryDirectory() as temporary:
                def request(url, *, timeout):
                    self.assertEqual(url, 'https://registry.npmjs.org/example/-/example-1.2.3.tgz')
                    return local.open('http://127.0.0.1:' + str(server.server_port) + '/archive', timeout=timeout)
                opener = types.SimpleNamespace(open=Mock(side_effect=request))
                self.assertEqual(self.acquire(opener, Path(temporary) / 'inputs'), body)
                self.assertEqual(opener.open.call_count, 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)
            self.assertFalse(thread.is_alive())

    def test_real_blocked_response_cannot_extend_acquisition_deadline(self):
        release = threading.Event()
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Length', '100')
                self.end_headers()
                self.wfile.write(b'x')
                self.wfile.flush()
                release.wait(1)
                self.close_connection = True
            def log_message(self, *args):
                pass
        server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
        thread.start()
        try:
            local = prepare.urllib.request.build_opener(prepare.urllib.request.ProxyHandler({}), prepare.NoRedirect())
            def request(url, *, timeout):
                return local.open('http://127.0.0.1:' + str(server.server_port) + '/archive', timeout=timeout)
            opener = types.SimpleNamespace(open=Mock(side_effect=request))
            with tempfile.TemporaryDirectory() as temporary, patch.object(prepare, 'NETWORK_TIMEOUT', 0.12):
                cache = Path(temporary) / 'inputs'
                started = time.monotonic()
                with self.assertRaises(Exception) as rejected:
                    self.acquire(opener, cache)
                self.assertTrue(prepare.transient_transport(rejected.exception))
                self.assertLess(time.monotonic() - started, 1)
                self.assertLessEqual(opener.open.call_count, 3)
                self.assertFalse(cache.exists())
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join(3)
            self.assertFalse(thread.is_alive())


if __name__ == '__main__':
    unittest.main()
