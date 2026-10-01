"""Synthetic provisioning/oracle inputs; these are never native grant evidence."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from tools.java_transaction_qualification import configuration as cfg, http, policies


def observation():
    publications = {name: 'publication:sha256:' + str(index) * 64
                    for index, name in enumerate(('aggregate', 'legacy', 'compatible', 'writer'), 1)}
    alice = {'subject': cfg.ALICE, 'ownerKind': 'user', 'tenant': cfg.TENANT,
             'service': None, 'recoveryKind': 'original-caller', 'recoveryScope': 'alice-native-test-scope'}
    operator = dict(alice, subject=cfg.OPERATOR, ownerKind='administrator',
                    recoveryScope='operator-native-test-scope')
    value = {'schemaVersion': 'latent.transaction-host-inspection.v1',
             'configuredHttpCallers': [alice], 'configuredTransportCallers': [alice, operator],
             'stateProviderProfile': 'native-state-test-profile',
             'stateConfigurationDigest': 'sha256:' + 'a' * 64, 'stateConfigurationEpoch': 1,
             'configuredProviders': [], 'deferredHttp': []}
    for name, contract in [(name, pair[0]) for name, pair in cfg.CLOCKS.items()] + [('http', 'latent:http/client@0.2.0')]:
        value['configuredProviders'].append({'id': name, 'tenant': cfg.TENANT, 'service': 'runtime-host',
            'capability': contract, 'profile': 'native-test-' + name,
            'configurationDigest': 'sha256:' + 'b' * 64, 'configurationEpoch': '1'})
    operations = []
    for publication in list(publications.values())[1:]:
        deferred = {'stagingBinding': 'java-staging-installed', 'dispatchBinding': 'java-dispatch-installed'}
        operations.append({'publication': publication, 'incarnation': 1, 'deferredHttp': deferred})
        value['deferredHttp'].append({'tenant': cfg.TENANT, 'service': cfg.SERVICE,
            'publication': publication, 'namespace': cfg.NAMESPACE, 'incarnation': 1,
            'logicalBinding': 'qualified-http', 'operation': 'put-once', **deferred,
            'providerProfile': 'native-put-once-test-profile', 'configurationDigest': 'sha256:' + 'c' * 64,
            'configurationEpoch': 1, 'dispatchSubject': 'native-source-service-test',
            'dispatchRecoveryKind': 'service-integration', 'dispatchRecoveryScope': 'native-service-test-scope',
            'resultPolicy': cfg.RESULT_POLICY})
    return value, operations, publications


class ProvisioningOracle(unittest.TestCase):
    def test_prior_runtime_without_transport_principal_observation_refuses(self):
        value, operations, _ = observation()
        del value['configuredTransportCallers']
        with self.assertRaises(ValueError):
            policies.ObservedHosts.read(value, operations)

    def test_http_and_rpc_scope_must_be_same_original_authenticated_user(self):
        for field, replacement in (('recoveryScope', 'different-owner'), ('tenant', 'foreign'),
                                   ('ownerKind', 'administrator'), ('service', 'guest-selected')):
            value, operations, _ = observation()
            value['configuredTransportCallers'][0] = dict(value['configuredTransportCallers'][0],
                                                        **{field: replacement})
            with self.subTest(field=field), self.assertRaises(ValueError):
                policies.ObservedHosts.read(value, operations)

    def test_configuration_or_unknown_field_cannot_substitute_native_authority(self):
        for name in ('enabled', 'granted', 'continuityProven', 'installed'):
            value, operations, _ = observation()
            value[name] = True
            with self.subTest(name=name), self.assertRaises(ValueError):
                policies.ObservedHosts.read(value, operations)

    def test_duplicate_or_wrong_provider_contract_never_provisions_a_binding(self):
        for change in ('duplicate', 'contract', 'epoch'):
            value, operations, _ = observation()
            if change == 'duplicate':
                value['configuredProviders'][2] = copy.deepcopy(value['configuredProviders'][0])
            elif change == 'contract':
                value['configuredProviders'][2]['capability'] = policies.STATE_CONTRACT
            else:
                value['configuredProviders'][2]['configurationEpoch'] = True
            with self.subTest(change=change), self.assertRaises(ValueError):
                policies.ObservedHosts.read(value, operations)

    def test_effect_profile_requires_exact_original_publication_and_purpose(self):
        for field, replacement in (('publication', 'publication:sha256:' + '9' * 64),
                                   ('namespace', 'foreign'), ('incarnation', 2),
                                   ('operation', 'send'), ('logicalBinding', 'caller-selected'),
                                   ('dispatchRecoveryKind', 'original-caller')):
            value, operations, _ = observation()
            value['deferredHttp'][0][field] = replacement
            with self.subTest(field=field), self.assertRaises(ValueError):
                policies.ObservedHosts.read(value, operations)

    def test_missing_duplicate_or_changed_native_effect_profiles_refuse(self):
        for change in ('missing', 'duplicate', 'changed'):
            value, operations, _ = observation()
            if change == 'missing':
                del value['deferredHttp'][0]['dispatchSubject']
            elif change == 'duplicate':
                value['deferredHttp'][2] = copy.deepcopy(value['deferredHttp'][0])
            else:
                value['deferredHttp'][2]['configurationDigest'] = 'sha256:' + 'd' * 64
            with self.subTest(change=change), self.assertRaises(ValueError):
                policies.ObservedHosts.read(value, operations)

    def test_state_and_dispatch_proposals_keep_distinct_current_caller_purposes(self):
        value, operations, publications = observation()
        hosts = policies.ObservedHosts.read(value, operations)
        proposal = policies.documents(hosts, publications)
        user, admin = proposal['policies'][cfg.STATE_POLICY]['rules']
        self.assertEqual(user['principals'], [{'kind': 'user', 'subject': cfg.ALICE}])
        self.assertEqual(admin['principals'], [{'kind': 'administrator', 'subject': cfg.OPERATOR}])
        self.assertNotIn('namespace-create', user['operations'])
        self.assertNotIn('acquire-command', admin['operations'])
        self.assertNotEqual(user['resources']['scopes'][0]['recoveryScope'],
                            admin['resources']['scopes'][0]['recoveryScope'])
        dispatch = proposal['policies'][cfg.DISPATCH_POLICY]['rules']
        self.assertEqual(len(dispatch), 3)
        for row, original in zip(dispatch, value['deferredHttp']):
            self.assertEqual(row['publications'], [original['publication']])
            self.assertEqual(row['principals'], [{'kind': 'service', 'subject': original['dispatchSubject']}])
            self.assertEqual(row['operations'], ['dispatch'])
            self.assertEqual(row['resources']['scopes'][0]['recoveryKind'], 'service-integration')
        self.assertEqual(proposal['bindings']['transaction-java-aggregate']['configurationDigest'],
                         value['stateConfigurationDigest'])
        self.assertEqual(len(proposal['deploymentGrants']), 2)
        self.assertTrue(all(row['capability'].startswith('latent:clock/') for row in proposal['deploymentGrants']))

    def test_original_publication_set_cannot_be_guessed_or_aliased(self):
        value, operations, publications = observation()
        hosts = policies.ObservedHosts.read(value, operations)
        for changed in ({'only': publications['aggregate']},
                        dict(publications, writer=publications['legacy']),
                        dict(publications, writer='component:sha256:' + '4' * 64)):
            with self.subTest(count=len(changed)), self.assertRaises(ValueError):
                policies.documents(hosts, changed)

    def test_selected_configuration_preserves_original_checkpoint_and_refuses_large_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = {'state': {'clockCheckpoint': '/original/protected-clock', 'operations': []}}
            config = cfg.Configuration(root / 'bootstrap', original, 'localhost:1234', {})
            path = config.selected(root / 'selected.json', [{'publication': 'original-selected'}])
            selected = json.loads(path.read_bytes())
            self.assertEqual(selected['state']['clockCheckpoint'], '/original/protected-clock')
            self.assertEqual(original['state']['operations'], [])
            for operations in ([{}] * 13, [{'oversized': 'x' * 65536}]):
                with self.assertRaises(ValueError):
                    config.selected(root / 'refused.json', operations)
            self.assertFalse((root / 'refused.json').exists())


class OriginalHttpRequest(unittest.TestCase):
    def test_real_bodyless_query_and_result_transport_carry_no_content_type(self):
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append((self.command, self.path, dict(self.headers)))
                self.send_response(200)
                self.send_header('Content-Length', '0')
                self.end_headers()

            def log_message(self, *_args):
                pass

        server = HTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=lambda: [server.handle_request() for _ in range(2)])
        server.timeout = 2
        worker.start()
        try:
            peer = http.Http('localhost:' + str(server.server_port), time.monotonic() + 5, maximum_requests=2)
            peer.request('GET', '/query')
            peer.request('GET', '/result', headers=(('Idempotency-Key', 'original'),))
        finally:
            worker.join(3)
            server.server_close()
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(seen), 2)
        self.assertTrue(all('Content-Type' not in row[2] and 'Content-Length' not in row[2] for row in seen))
        self.assertEqual(seen[1][2]['Idempotency-Key'], 'original')

    def test_header_overflow_and_injection_refuse_before_any_network_request(self):
        for headers in ((('X', 'a\r\nForged: true'),), (('X', 'x' * 8193),), (('X', 'v'),) * 17):
            peer = http.Http('localhost:1', time.monotonic() + 5)
            with self.subTest(fields=len(headers)), self.assertRaises(ValueError):
                peer.request('GET', '/query', headers=headers)
            self.assertEqual(peer.requests, 0)


if __name__ == '__main__':
    unittest.main()
