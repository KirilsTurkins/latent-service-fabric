"""Preserve the actual bounded startup failure without retaining raw stderr."""
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import node_startup_observation
from tools.phase2_operator_process import WorkflowError
from tools.static_api import qualify


class StaticApiStartupFailure(unittest.TestCase):
    def test_failed_startup_retains_only_the_closed_observation_and_reaps_peer(self):
        report = {
            'schemaVersion': node_startup_observation.SCHEMA,
            'startupSucceeded': False,
            'terminalFailure': {'owner': 'platform', 'reason': 'unavailable'},
            'observations': [{'stage': 'auditCatalog',
                              'failure': {'owner': 'storage', 'reason': 'corrupt'}}],
            'truncated': False,
            'shutdown': None,
        }
        raw = b'private-fixture-marker\n' + json.dumps(report).encode() + b'\n'
        failure = WorkflowError('node-startup-exit-unavailable')
        failure.startup_failure = node_startup_observation.observe(raw)
        peer = SimpleNamespace(secret='test-only', close=Mock())
        client = SimpleNamespace(environment={}, failed_call=None, node=None)
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            args = SimpleNamespace(work=work, bin=work)
            with patch.object(qualify, 'owned_cancellation', return_value=nullcontext(None)), \
                    patch.object(qualify, 'Client', return_value=client), \
                    patch.object(qualify, 'certificates'), \
                    patch.object(qualify, 'Peer', return_value=peer), \
                    patch.object(qualify, 'configure', return_value=(work / 'config', 'host')), \
                    patch.object(qualify, 'connect', side_effect=failure) as connect:
                with self.assertRaises(WorkflowError) as raised:
                    qualify.run(args)
            self.assertIs(raised.exception, failure)
            connect.assert_called_once()
            peer.close.assert_called_once()
            receipt = json.loads((work / 'composition-receipt.json').read_bytes())
            self.assertFalse(receipt['passed'])
            self.assertEqual(receipt['cleanup'], 'owned-node-and-peer-reaped')
            self.assertEqual(receipt['failedNodeStartup'], failure.startup_failure)
            self.assertNotIn('private-fixture-marker', json.dumps(receipt))


if __name__ == '__main__':
    unittest.main()
