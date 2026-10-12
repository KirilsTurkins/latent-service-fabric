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
