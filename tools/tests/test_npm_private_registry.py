"""Owned npm registry protocol, credential and signed-route refusal controls."""
import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from tools import npm_private_registry_fixture as fixture, qualify_npm_private_dependencies as gate
from tools import rust_capsule_node as node
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import digest


class PrivateRegistry(unittest.TestCase):
    def test_native_packuments_integrity_archives_conditions_and_resources_are_consistent(self):
        nonce = 'a'*24
        assets = fixture.assets(nonce, 'https://127.0.0.1:1234')
        self.assertEqual(len(assets), 6)
        for role in ('root', 'leaf'):
            identity, _ = fixture.packages(nonce, fixture.VERSIONS[0], role)
            versions = json.loads(assets['/'+identity][1])['versions']
            for version in fixture.VERSIONS:
                _, files = fixture.packages(nonce, version, role)
                raw = assets['/tarballs/'+role+'-'+version+'.tgz'][1]
                self.assertEqual(versions[version]['dist']['integrity'],
                    'sha512-'+base64.b64encode(hashlib.sha512(raw).digest()).decode())
                with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
                    self.assertEqual({entry.name.removeprefix('package/'): archive.extractfile(entry).read()
                                      for entry in archive.getmembers()}, files)
                if role == 'root':
                    self.assertEqual(versions[version]['dependencies'], {'@private-'+nonce+'/leaf': version})
                    self.assertEqual(versions[version]['exports'][fixture.CONDITION], './selected.mjs')
                    self.assertIn(b'fresh private state', files['selected.mjs'])
                    self.assertIn(b'bytes[1] !== 255', files['selected.mjs'])
                else:
                    self.assertEqual(files['resource.bin'], bytes((0, 255, 65, 128)))
                    self.assertIn('Gr\u00fc\u00dfe'.encode(), files['resource.txt'])

    def test_open_or_invalid_coordinates_are_refused_before_archive_generation(self):
        for nonce, version, role in (('a'*23, '1.0.0', 'root'), ('G'*24, '1.0.0', 'root'),
                ('a'*24, 'latest', 'root'), ('a'*24, '1.0.0', '../leaf')):
            with self.subTest(selection=(nonce, version, role)), self.assertRaises(WorkflowError):
                fixture.packages(nonce, version, role)

    def test_actual_https_peer_requires_selected_ca_and_bearer_then_reaps_listener(self):
        openssl = shutil.which('openssl')
        if openssl is None and sys.platform == 'win32':
            openssl = str(Path(shutil.which('git')).resolve().parents[1] / 'usr/bin/openssl.exe')
        self.assertTrue(openssl and Path(openssl).is_file(), 'owned TLS fixture requires normal OpenSSL')
        class Commands:
            def run(self, stage, executable, *args):
                subprocess.run([openssl, *map(str, args)], check=True, timeout=30,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        nonce = 'a'*24
        with tempfile.TemporaryDirectory() as temporary:
            with fixture.server(Path(temporary), Commands(), nonce, 'opaque-peer-token') as (feed, endpoint, ca, _key):
                trusted = ssl.create_default_context(cadata=ca.decode())
                url = endpoint + '/@private-' + nonce + '%2froot'
                with self.assertRaises(URLError):
                    urlopen(Request(url, headers={'Authorization': 'Bearer opaque-peer-token'}), timeout=5)
                for credential in ('', 'Bearer wrong-peer-token'):
                    with self.assertRaises(HTTPError) as denied:
                        urlopen(Request(url, headers={'Authorization': credential}), context=trusted, timeout=5)
                    self.assertEqual(denied.exception.code, 401)
                    denied.exception.close()
                with urlopen(Request(url, headers={'Authorization': 'Bearer opaque-peer-token'}),
                             context=trusted, timeout=5) as reply:
                    self.assertEqual(json.load(reply)['name'], '@private-'+nonce+'/root')
                self.assertNotIn('opaque-peer-token', json.dumps(feed.observations))
            self.assertGreater(feed.handshake_failures, 0)
            self.assertEqual([row['status'] for row in feed.observations], [401, 401, 200])

    def test_peer_authentication_exact_asset_allowlist_and_redacted_observations(self):
        peer = fixture.Feed({'/known': ('private-zip', b'zip')}, 'opaque-test-value')
        expected = 'Bearer opaque-test-value'
        self.assertEqual(peer.response('/known', ''), (401, b'authentication-required'))
        self.assertEqual(peer.response('/known', 'Basic wrong'), (401, b'authentication-required'))
        self.assertEqual(peer.response('/known', expected), (200, b'zip'))
        self.assertEqual(peer.response('/unknown', expected), (404, b'not-found'))
        self.assertTrue(all(set(row) == {'asset', 'authorized', 'status'} for row in peer.observations))
        self.assertNotIn('opaque-test-value', json.dumps(peer.observations))
        self.assertNotIn('/known', json.dumps(peer.observations))

    def test_peer_total_request_bound_is_finite(self):
        peer = fixture.Feed({}, 'fixture')
        for _ in range(fixture.MAX_REQUESTS):
            peer.response('/missing', '')
        with self.assertRaisesRegex(WorkflowError, 'request-bound'):
            peer.response('/missing', '')
        self.assertEqual(len(peer.observations), fixture.MAX_REQUESTS)

    def test_authority_is_child_only_and_previous_environment_restored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root/'logs').mkdir()
            commands = SimpleNamespace(records=[], environment={fixture.TOKEN_SLOT: 'previous'}, output=root)
            def run(stage, *args):
                self.assertEqual(commands.environment[fixture.TOKEN_SLOT], 'credential')
                commands.records.append({'exitCode': 0})
                for stream in ('stdout', 'stderr'):
                    (root/'logs'/('00-' + stage + '.' + stream + '.txt')).write_bytes(b'fixed-public-output')
            commands.run = run
            gate.author(commands, 'capture', 'dependencies', token='credential', confidential=(b'credential',))
            self.assertEqual(commands.environment, {fixture.TOKEN_SLOT: 'previous'})

    def test_native_failure_and_confidential_streams_cannot_be_mistaken_for_success(self):
        for exit_code, output in ((2, b'bounded failure'), (1, b'credential')):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); (root/'logs').mkdir()
                commands = SimpleNamespace(records=[], environment={}, output=root)
                def run(stage, *args):
                    commands.records.append({'exitCode': exit_code})
                    for stream in ('stdout', 'stderr'):
                        (root/'logs'/('00-' + stage + '.' + stream + '.txt')).write_bytes(output)
                    raise ValueError('fixed-native-failure')
                commands.run = run
                with self.assertRaises(WorkflowError):
                    gate.author(commands, 'negative', expected=1, token='credential', confidential=(b'credential',))
                self.assertNotIn(fixture.TOKEN_SLOT, commands.environment)

    def test_unexpected_native_failure_also_redacts_retained_confidential_streams(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root/'logs').mkdir()
            commands = SimpleNamespace(records=[], environment={}, output=root)
            def run(stage, *args):
                commands.records.append({'exitCode': 2})
                for stream in ('stdout', 'stderr'):
                    (root/'logs'/('00-'+stage+'.'+stream+'.txt')).write_bytes(b'opaque-credential')
                raise ValueError('unexpected-failure')
            commands.run = run
            with self.assertRaisesRegex(WorkflowError, 'public-command-secret'):
                gate.author(commands, 'negative', expected=1, token='opaque-credential', confidential=(b'opaque-credential',))
            for path in (root/'logs').iterdir():
                self.assertEqual(path.read_bytes(), b'private-command-output-redacted\n')
            self.assertNotIn(fixture.TOKEN_SLOT, commands.environment)

    def observations(self, changed=None):
        selected = {'publicationId': 'p', 'target': 't', 'releaseDigest': 'r', 'revisionId': 'v'}
        row = {'response': {'data': {'resolvedRevision': selected,
                    'consumption': {'outboundRequests': '0', 'childCalls': '0', 'effectCount': '0'}}},
               'processReaped': True}
        if changed == 'revision':
            row['response']['data']['resolvedRevision'] = {**selected, 'revisionId': 'other'}
        elif changed == 'process':
            row['processReaped'] = False
        elif changed:
            row['response']['data']['consumption'][changed] = '1'
        return selected, row

    def test_signed_values_use_full_route_tuple_and_original_physical_idle(self):
        for removed in (False, True):
            selected, row = self.observations()
            result = {'invocations': [], 'samples': []}
            with patch.object(node, 'selected_revision', return_value=selected), \
                 patch.object(node, 'call', return_value=row) as call, \
                 patch.object(node, 'assert_value') as value, patch.object(node, 'sample'), \
                 patch.object(node, 'provider_idle') as idle:
                fixture.probe('client', 'target', 'probe', result, 32,
                              {'nonce': 'a'*24, 'version': fixture.VERSIONS[0], 'removed': removed, 'condition': 'enabled'})
            self.assertEqual(len(result['capturedNpmPrivate']['cases']), 3)
            self.assertEqual(idle.call_count, 3)
            self.assertEqual(len(result['invocations']), 3)
            expected = 'Hello, alpha!' if removed else fixture.expected('a'*24, fixture.VERSIONS[0], 'alpha')
            self.assertEqual(value.call_args_list[0].args[2], [{'ok': expected}])
            self.assertEqual(call.call_args_list[0].args[4], ['alpha' if removed else 'private-npm:alpha'])

    def test_wrong_revision_unreaped_or_effectful_calls_never_qualify(self):
        for change in ('revision', 'process', 'outboundRequests', 'childCalls', 'effectCount'):
            selected, row = self.observations(change)
            result = {'invocations': [], 'samples': []}
            with self.subTest(change=change), patch.object(node, 'selected_revision', return_value=selected), \
                 patch.object(node, 'call', return_value=row), patch.object(node, 'assert_value'), \
                 patch.object(node, 'sample'), patch.object(node, 'provider_idle') as idle:
                with self.assertRaisesRegex(WorkflowError, 'signed-selected-revision'):
                    fixture.probe('client', 'target', 'probe', result, 32,
                                  {'nonce': 'a'*24, 'version': fixture.VERSIONS[0], 'removed': False, 'condition': 'enabled'})
                idle.assert_not_called()
                self.assertNotIn('capturedNpmPrivate', result)

    def test_private_probe_cannot_run_in_another_language_or_via_truthy_selection(self):
        from tools.run_rust_capsule_workflow import run
        for language, flag in (('go', True), ('rust', True), ('typescript', 1), ('typescript', 'yes')):
            with self.subTest(language=language, flag=flag), self.assertRaisesRegex(WorkflowError, 'npm-private-language'):
                run(None, None, None, None, language=language, captured_npm_private=flag)

    def test_probe_metadata_is_closed_and_validated_before_any_invocation(self):
        for metadata in ({}, {'nonce': 'a'*24, 'version': 'v1.0.0', 'removed': 0},
                         {'nonce': 'a'*24, 'version': 'v1.0.0', 'removed': False, 'skip': True}):
            with patch.object(node, 'call') as call, self.assertRaises(WorkflowError):
                fixture.probe(None, None, None, {}, 0, metadata)
            call.assert_not_called()

    def test_integrity_controls_restore_exact_owned_objects_and_ca_even_on_refusal_failure(self):
        from tools.application_dependency_store import Store
        for unexpected in (False, True):
            with self.subTest(unexpected=unexpected), tempfile.TemporaryDirectory() as temporary:
                app = Path(temporary)
                store = Store(app/'dependency-inputs/objects')
                entry = {**store.put(b'owned selected source'), 'path': 'value.go'}
                lock = {'artifacts': [{'metadata': {'assetType': 'selected-node-modules'},
                                      'role': 'application', 'files': [entry]}]}
                for name in ('latent.dependencies.json', 'latent.dependencies.lock.json', 'package.json',
                             'package-lock.json', 'npm-resolved.lock.json', 'sdk-lock.json'):
                    (app/name).write_bytes(b'unchanged')
                (app/'registry-trust').mkdir()
                ca = app/'registry-trust/roots.pem'; ca.write_bytes(b'original-public-ca')
                before = gate.accepted(app)
                path = store.path(entry['digest'])
                def command(_commands, case, *args, expected=0, **kwargs):
                    if unexpected:
                        raise RuntimeError('owned-control-did-not-refuse')
                    if case == 'missing-cas-object':
                        self.assertFalse(path.exists())
                    elif case == 'tampered-cas-object':
                        self.assertNotEqual(path.read_bytes(), b'owned selected source')
                    elif case == 'changed-public-ca':
                        self.assertNotEqual(ca.read_bytes(), b'original-public-ca')
                    else:
                        self.assertEqual(path.read_bytes(), b'owned selected source')
                        self.assertEqual(ca.read_bytes(), b'original-public-ca')
                    self.assertEqual(expected, 0 if case.endswith('-restored') else 1)
                with patch.object(gate, 'author', side_effect=command) as author:
                    if unexpected:
                        with self.assertRaises(RuntimeError):
                            gate.integrity_controls(None, app, lock, ())
                    else:
                        rows = gate.integrity_controls(None, app, lock, ())
                        self.assertEqual(len(rows), 3)
                        self.assertEqual(author.call_count, 6)
                self.assertEqual(path.read_bytes(), b'owned selected source')
                self.assertEqual(ca.read_bytes(), b'original-public-ca')
                self.assertEqual(gate.accepted(app), before)

    def test_failed_receipt_error_preserves_the_original_failure_identity(self):
        for diagnostic in (RuntimeError('observer unavailable'), RecursionError('observer exhausted')):
            with self.subTest(diagnostic=type(diagnostic).__name__), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                original = ValueError('owned-original-failure')
                with patch.object(gate, 'frozen', side_effect=original), \
                     patch.object(gate, 'write_json', side_effect=diagnostic):
                    with self.assertRaises(ValueError) as raised:
                        gate.qualify(root/'prepared', root/'output', root/'tools')
                self.assertIs(raised.exception, original)

    def test_campaign_rejects_stale_baseline_before_native_acquisition(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(gate, 'frozen', side_effect=ValueError('source mismatch')), \
                 patch.object(gate, 'capture') as capture:
                with self.assertRaises(ValueError):
                    gate.qualify(root/'prepared', root/'output', root/'tools')
            capture.assert_not_called()
            failed = json.loads((root/'output/FAILED.json').read_bytes())
            self.assertEqual(failed['stage'], 'original-native-products')
            self.assertFalse(failed['fullTicketQualification'])


if __name__ == '__main__':
    unittest.main()
