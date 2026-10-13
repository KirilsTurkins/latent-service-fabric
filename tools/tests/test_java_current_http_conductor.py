"""Explicit current collector selections retain the historical protocol boundary."""
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from tools import run_java_transaction_http_qualification as conductor
from tools.java_transaction_qualification import current_recipient, policies
from tools.phase2_operator_process import write_json
from tools.tests.test_java_transaction_provision import observation


class CurrentHttpConductor(unittest.TestCase):
    def test_return_to_legacy_records_both_deployments_without_reusing_measured_case(self):
        from unittest.mock import patch
        from tools.java_transaction_qualification import configuration as cfg, evidence, lifecycle
        from tools.java_transaction_qualification.current_activation import CurrentActivation
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            collector = evidence.Evidence(root / 'evidence')
            activation = CurrentActivation.__new__(CurrentActivation)
            activation.client = SimpleNamespace(evidence=collector)
            activation.configuration = SimpleNamespace(authority='localhost:1')
            activation.node = SimpleNamespace(process=None, start=lambda *_a, **_k: None)
            name = 'put-once-legacy-v1'
            activation.items = {name: SimpleNamespace(name=name)}
            activation.path = lambda _: root / 'selected.json'
            activation.metadata = {name: ({'generation': '1'}, {'deploymentGeneration': 1})}
            with patch.object(lifecycle, 'bind_http_routes') as binding:
                activation.start(None, name, 'legacy-runtime')
                activation.metadata[name] = ({'generation': '3'}, {'deploymentGeneration': 3})
                activation.start(None, name, 'legacy-after-diagnostic')
                self.assertEqual(binding.call_count, 2)
            self.assertEqual(collector.cases, ['deploy-' + name + '-legacy-runtime',
                                              'deploy-' + name + '-legacy-after-diagnostic'])
            self.assertEqual(len(collector.files), 2)
            from tools.phase2_operator_process import read_json
            receipts = [read_json(collector.directory / row['path']) for row in collector.files]
            self.assertEqual([row['observed']['deployment']['generation'] for row in receipts], ['1', '3'])

    def test_current_proposals_bind_native_state_staging_and_exact_http_dispatch_grants(self):
        from tools.java_transaction_qualification import configuration as cfg
        value, operations, publications = observation()
        for row in value['deferredHttp']:
            row['operation'] = 'http'
        hosts = policies.ObservedHosts.read(value, operations, intent_operation='http')
        endpoint = current_recipient.endpoint({'scheme': 'https', 'host': 'localhost', 'port': 52027}, 'e' * 64)
        proposal = policies.documents(hosts, publications, current_http_endpoint=endpoint)
        grants = {row['capability']: row for row in proposal['deploymentGrants']}
        self.assertEqual(len(grants), len(proposal['deploymentGrants']))
        self.assertEqual(set(grants), {*(pair[0] for pair in cfg.CLOCKS.values()),
                                      policies.STATE_CONTRACT, policies.INTENT_CONTRACT})
        self.assertEqual(grants[policies.STATE_CONTRACT], {'capability': policies.STATE_CONTRACT,
                         'policy': cfg.STATE_POLICY, 'operations': policies.DATA_OPERATIONS})
        self.assertEqual(grants[policies.INTENT_CONTRACT], {'capability': policies.INTENT_CONTRACT,
                         'policy': cfg.STAGING_POLICY, 'operations': ['stage']})
        self.assertNotIn(policies.HTTP_CONTRACT, grants)
        provider = hosts.providers['http']
        self.assertEqual(proposal['bindings']['java-dispatch-installed'], policies.binding(
            policies.HTTP_CONTRACT, provider['profile'], provider['configurationDigest'],
            int(provider['configurationEpoch']), ['send']))
        for rule, source in zip(proposal['policies'][cfg.DISPATCH_POLICY]['rules'], hosts.effects):
            self.assertEqual(rule['capability'], policies.HTTP_CONTRACT)
            self.assertEqual(rule['operations'], ['send'])
            self.assertEqual(rule['publications'], [source['publication']])
            self.assertEqual(rule['principals'], [{'kind': 'service', 'subject': source['dispatchSubject']}])
            self.assertEqual(rule['resources'], {'kind': 'http', 'origins': [endpoint['origin']],
                'methods': ['GET', 'POST'], 'paths': ['/effect'], 'pathPrefixes': ['/receipts/']})
            self.assertEqual(rule['ceiling'], {'operations': 1, 'inputBytes': 27,
                'outputBytes': 2048, 'wallTimeMillis': 2000})
        value['deferredHttp'][0]['operation'] = 'put-once'
        with self.assertRaises(ValueError):
            policies.documents(hosts, publications, current_http_endpoint=endpoint)

    def test_current_session_program_requires_explicit_profile_order_and_single_runtime(self):
        from unittest.mock import patch
        from tools.java_transaction_qualification import lifecycle
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with self.assertRaises(ValueError):
                lifecycle.Node(SimpleNamespace(phase4=False), root / 'unused', root,
                               current_publication_program=True)
            node = lifecycle.Node(SimpleNamespace(phase4=True), root / 'unused', root,
                                  current_publication_program=True)
            path = root / 'configuration.json'
            write_json(path, {'state': {'formatVersion': 2, 'operations': []}})
            with patch.object(lifecycle, 'Process') as process:
                for position, session in ((0, None), (0, 'authority'), (2, 'namespace-create'),
                                           (14, 'restored-runtime')):
                    node.ordinal = position
                    with self.subTest(position=position, session=session), self.assertRaises(ValueError):
                        node.start(path, current_session=session)
                node.ordinal = 0
                path = root / 'populated-configuration.json'
                write_json(path, {'state': {'formatVersion': 2, 'operations': [{'publication': 'extra'}]}})
                with self.assertRaises(ValueError):
                    node.start(path, current_session='publish')
                process.assert_not_called()
            legacy = lifecycle.Node(SimpleNamespace(), root / 'unused', root)
            legacy.ordinal = 6
            with self.assertRaises(ValueError):
                legacy.start(path)

    def test_current_transition_retires_before_metadata_and_never_starts_after_uncertain_mutation(self):
        from unittest.mock import patch
        from tools.java_transaction_qualification.current_activation import CurrentActivation
        from tools.java_transaction_qualification import configuration as cfg, lifecycle
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            names = ('aggregate', 'put-once-legacy-v1', 'put-once-compatible-v2',
                     'put-once-writer-v2', 'put-once-diagnostics')
            publications = {name: 'publication:sha256:' + str(index + 1) * 64
                            for index, name in enumerate(names)}
            items = tuple(SimpleNamespace(name=name, component_digest='sha256:' + str(index + 5) * 64)
                          for index, name in enumerate(names))
            rows = [{'tenant': cfg.TENANT, 'contract': cfg.CONTRACT, 'binding': cfg.DEPLOYMENT,
                     'deployment': cfg.DEPLOYMENT, 'incarnation': 1, 'function': function,
                     'publication': publications[item.name], 'componentDigest': item.component_digest}
                    for item in items for function in ('update', 'query', 'scan')]
            full = root / 'inspected.json'
            write_json(full, {'state': {'formatVersion': 2, 'operations': rows}})
            configuration = cfg.Configuration(root / 'bootstrap.json',
                {'state': {'formatVersion': 2, 'operations': []}}, 'localhost:1', {})
            events = []
            node = SimpleNamespace(process=None, current_publication_program=True)
            node.start = lambda path, **kwargs: events.append(('start', path, kwargs))
            node.stop = lambda: events.append(('stop',))
            client = SimpleNamespace(phase4=True, evidence=SimpleNamespace(passed=lambda *_: None))
            activation = CurrentActivation(client, configuration, node, root, items, publications,
                                           {'deploymentGrants': ['original']}, full)
            with patch.object(lifecycle, 'deployment_metadata', side_effect=ValueError('uncertain')) as metadata, \
                 patch.object(lifecycle, 'admission_lease_interval') as lease:
                with self.assertRaisesRegex(ValueError, 'uncertain'):
                    activation.select_metadata('put-once-legacy-v1', 'legacy-metadata')
                self.assertEqual([row[0] for row in events], ['start', 'stop'])
                self.assertEqual(activation.metadata, {})
                lease.assert_not_called()
                metadata.assert_called_once()
            events.clear()
            with patch.object(lifecycle, 'deployment_metadata', return_value=({'generation': '1'}, {'original': True})), \
                 patch.object(lifecycle, 'admission_lease_interval', side_effect=lambda _: events.append(('lease',))):
                selected = activation.select_metadata('put-once-legacy-v1', 'legacy-metadata')
            self.assertEqual([row[0] for row in events], ['start', 'stop', 'lease'])
            from tools.phase2_operator_process import read_json
            self.assertEqual(read_json(selected)['state']['operations'], rows[3:6])
            self.assertEqual(configuration.value['state']['operations'], [])

    def test_active_runtime_selects_one_exact_publication_and_copies_original_operations(self):
        from tools.java_transaction_qualification import configuration as cfg
        rows = []
        for index in (1, 2):
            for function in ('update', 'query', 'scan'):
                rows.append({'tenant': cfg.TENANT, 'contract': cfg.CONTRACT, 'binding': cfg.DEPLOYMENT,
                             'deployment': cfg.DEPLOYMENT, 'incarnation': 1, 'function': function,
                             'publication': 'publication:sha256:' + str(index) * 64,
                             'componentDigest': 'sha256:' + str(index + 2) * 64})
        before = copy.deepcopy(rows)
        selected = cfg.active_operations(rows, 'publication:sha256:' + '1' * 64, 'sha256:' + '3' * 64)
        self.assertEqual(selected, rows[:3])
        selected[0]['function'] = 'changed-local-copy'
        self.assertEqual(rows, before)
        for changed in (rows[:2], rows[:3] + [rows[0]], [dict(row, componentDigest='sha256:' + '4' * 64) for row in rows[:3]]):
            with self.assertRaises(ValueError):
                cfg.active_operations(changed, 'publication:sha256:' + '1' * 64, 'sha256:' + '3' * 64)

    def test_retained_decoders_have_four_distinct_explicit_signed_sources_without_generic_alias(self):
        from tools.java_transaction_qualification import recovery
        names = ('put-once-legacy-v1', 'put-once-compatible-v2', 'put-once-writer-v2', 'put-once-diagnostics')
        items = {name: SimpleNamespace(component_digest='sha256:' + str(index + 1) * 64)
                 for index, name in enumerate(names)}
        publications = {name: 'publication:sha256:' + str(index + 5) * 64 for index, name in enumerate(names)}
        items['aggregate'] = SimpleNamespace(component_digest='sha256:' + 'a' * 64)
        publications['aggregate'] = 'publication:sha256:' + 'b' * 64
        selected = recovery.decoder_sources(items, publications)
        self.assertEqual(len(selected), 4)
        self.assertFalse(any(row['publication'] == publications['aggregate'] for row in selected))
        for changed in (dict(publications, **{names[0]: publications[names[1]]}),
                        {key: value for key, value in publications.items() if key != names[0]}):
            with self.assertRaises(ValueError):
                recovery.decoder_sources(items, changed)

    def test_installation_keeps_exact_declared_ca_reference_and_body_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            tls = root / 'tls'
            tls.mkdir()
            for name in ('ca.der', 'server.pem', 'key.pem'):
                (tls / name).write_bytes(b'synthetic-source-control-only')
            endpoint = current_recipient.endpoint({'scheme': 'https', 'host': 'localhost', 'port': 52027}, 'e' * 64)
            endpoint_path = root / 'endpoint.json'
            write_json(endpoint_path, endpoint)
            installation = {'identity': {'id': 'http', 'tenant': 'examples', 'service': 'runtime-host', 'epoch': 1},
                            'credentialDirectory': '/original/private/credentials',
                            'credentials': [{'reference': 'java-current-http', 'file': 'original',
                                             'destination': 0, 'header': 'authorization'}],
                            'deferred': [endpoint], 'configuration': {
                                'formatVersion': 1, 'publicRoots': False,
                                'extraRoots': [list((tls / 'ca.der').read_bytes())], 'destinations': [],
                                'limits': {'maximumRequestBodyBytes': 27, 'maximumResponseBodyBytes': 2048,
                                           'maximumEncodedResponseBytes': 2048, 'maximumHeaderBytes': 8192,
                                           'maximumHeaders': 32, 'maximumRedirects': 0}}}
            path = root / 'installation.json'
            write_json(path, installation)
            args = SimpleNamespace(current_http_installation=path, current_http_tls=tls,
                                   current_http_endpoint=endpoint_path)
            self.assertEqual(conductor.current_installation(args), installation)
            for index, changed in enumerate((('ca', None), ('reference', None), ('limits', None), ('approval', None))):
                invalid = copy.deepcopy(installation)
                if changed[0] == 'ca':
                    invalid['configuration']['extraRoots'] = [[1, 2, 3]]
                elif changed[0] == 'reference':
                    invalid['credentials'][0]['reference'] = 'java-put-once'
                elif changed[0] == 'limits':
                    invalid['configuration']['limits']['maximumRequestBodyBytes'] = 32768
                else:
                    invalid['configuration']['approved'] = True
                invalid_path = root / f'install-{index}.json'
                write_json(invalid_path, invalid)
                args.current_http_installation = invalid_path
                with self.assertRaises(ValueError):
                    conductor.current_installation(args)

    def test_endpoint_file_is_closed_and_retains_original_twenty_seven_byte_ceiling(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            value = current_recipient.endpoint({'scheme': 'https', 'host': 'localhost', 'port': 52027}, 'e' * 64)
            path = root / 'endpoint.json'
            write_json(path, value)
            self.assertEqual(conductor.current_endpoint(SimpleNamespace(current_http_endpoint=path)), value)
            for index, change in enumerate(({'approved': True}, {'maximumPayloadBytes': 4096},
                                            {'origin': {'scheme': 'http', 'host': 'localhost', 'port': 52027}})):
                invalid = root / f'invalid-{index}.json'
                write_json(invalid, dict(value, **change))
                with self.assertRaises(ValueError):
                    conductor.current_endpoint(SimpleNamespace(current_http_endpoint=invalid))

    def test_current_endpoint_cannot_select_historical_or_unpaired_capsules(self):
        with self.assertRaisesRegex(ValueError, 'current-http-requires-explicit-current-captures'):
            conductor.current_mode(SimpleNamespace(current_selections=None, current_selections_digest=None,
                                                    current_http_endpoint=Path('/not-read')))

    def test_observed_current_operation_requires_explicit_selection_and_all_publications_match(self):
        value, operations, _ = observation()
        for row in value['deferredHttp']:
            row['operation'] = 'http'
        before = copy.deepcopy(value)
        with self.assertRaises(ValueError):
            policies.ObservedHosts.read(value, operations)
        hosts = policies.ObservedHosts.read(value, operations, intent_operation='http')
        self.assertEqual(hosts.value, before)
        value['deferredHttp'][0]['operation'] = 'put-once'
        with self.assertRaises(ValueError):
            policies.ObservedHosts.read(value, operations, intent_operation='http')

    def test_fault_staging_framing_uses_exact_operation_without_changing_historical_accounting(self):
        from tools.java_transaction_qualification import diagnostic_campaign as diagnostic
        self.assertEqual(diagnostic.stage_write_bytes('put-once'), diagnostic.STAGE_WRITE_BYTES)
        self.assertEqual(diagnostic.stage_write_bytes('http'), diagnostic.STAGE_WRITE_BYTES - 4)
        with self.assertRaises(ValueError):
            diagnostic.stage_write_bytes('unknown')


if __name__ == '__main__':
    unittest.main()
