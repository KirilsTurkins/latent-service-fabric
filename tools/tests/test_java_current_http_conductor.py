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
