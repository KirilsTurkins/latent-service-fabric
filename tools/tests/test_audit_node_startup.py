"""Finite startup configuration and refusal diagnostics, without host execution."""
from pathlib import Path
import copy
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import qualify_audit_node_startup as owner
from tools.phase2_operator_process import WorkflowError


def failure():
    return {'schemaVersion': 'latent.startup-failure-observation.v1',
        'startupSucceeded': False, 'terminalFailure': {'owner': 'platform', 'reason': 'resource-exhausted'},
        'observations': [{'stage': 'auditCatalog',
                          'failure': {'owner': 'platform', 'reason': 'resource-exhausted'}}],
        'truncated': False, 'shutdown': None}


class AuditNodeStartupTests(unittest.TestCase):
    def test_real_startup_cases_keep_record_policies_and_default_node_limits(self):
        self.assertEqual(owner.CASES, (('two-records-audit-only', 2, False),
            ('two-records-provider', 2, True), ('lowered-provider', 1024, True),
            ('default-provider', 4096, True), ('oversized-fixed-refusal', 16384, True)))
        for _, records, providers in owner.CASES:
            value = owner.configuration(records, providers)
            self.assertEqual(value['audit'].get('records', 4096), records)
            self.assertNotIn('metadataBytes', value['audit'])
            self.assertNotIn('maximumMetadataBytes', value)
            self.assertEqual('providers' in value, providers)
            if providers:
                self.assertEqual(len(value['providers']['bindings']), 1)
        self.assertEqual(owner.configuration(4096, True)['audit'], {'mode': 'durable'})
        for records, providers in ((True, True), (3, True), (16385, True), (2, 1)):
            with self.assertRaises(WorkflowError):
                owner.configuration(records, providers)

    def test_oversize_requires_actual_original_bank_capacity_error_before_journal_birth(self):
        value = failure()
        raw = json.dumps(value).encode()
        self.assertEqual(owner.expected_refusal(raw, 1, False)['status'], 'observed')
        for code, exists in ((0, False), (2, False), (1, True)):
            with self.assertRaises(WorkflowError):
                owner.expected_refusal(raw, code, exists)
        for key, replacement in (('terminalFailure', {'owner': 'platform', 'reason': 'unavailable'}),
                                 ('observations', [{'stage': 'providerCatalog',
                                     'failure': {'owner': 'platform', 'reason': 'resource-exhausted'}}]),
                                 ('truncated', True)):
            changed = copy.deepcopy(value)
            changed[key] = replacement
            with self.assertRaises(WorkflowError):
                owner.expected_refusal(json.dumps(changed).encode(), 1, False)

    def test_refused_startup_retains_actual_bounded_stderr_without_retry(self):
        raw = json.dumps(failure()).encode()

        class RefusedProcess:
            def __init__(self, *_args, **_kwargs):
                self.buffers = [bytearray(), bytearray(raw)]

            def complete(self, _deadline):
                return subprocess.CompletedProcess([], 1, b'', raw)

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as temporary, patch.object(owner, 'Process', RefusedProcess):
            output = Path(temporary)
            result = owner.startup_case(Path('cli'), Path('node'), output, owner.CASES[-1],
                                       owner.time.monotonic() + 60, None)
            self.assertEqual(result['status'], 'passed')
            retained = output / owner.CASES[-1][0]
            self.assertEqual((retained / 'stderr.txt').read_bytes(), raw)
            self.assertEqual(json.loads((retained / 'result.json').read_bytes()), result)

    def test_prebuild_refusal_keeps_failure_receipt_without_cargo_or_products(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(owner.sys, 'platform', 'linux'), \
                patch.object(owner.host_codec_wasmtime, 'verify', side_effect=ValueError('fixed-test-refusal')), \
                patch.object(owner, 'Commands') as commands:
            output = Path(temporary) / 'capture'
            with self.assertRaises(ValueError):
                owner.qualify(output, 'a' * 40)
            result = json.loads((output / 'result.json').read_bytes())
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['failedStage'], 'prebuild-source')
            self.assertEqual(result['commands'], [])
            self.assertFalse(result['guestSourceCompiled'])
            self.assertFalse((output / 'native-binaries').exists())
            commands.assert_not_called()


if __name__ == '__main__':
    unittest.main()
