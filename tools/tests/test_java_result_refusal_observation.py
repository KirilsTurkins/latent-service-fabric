"""A failed HTTP result gets one bounded read-only diagnostic, never a retry."""
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.java_transaction_qualification import refusal_observation as observer
from tools.java_transaction_qualification.campaign import Campaign
from tools.java_transaction_qualification.evidence import Evidence


class OriginalResultObservationTests(unittest.TestCase):
    def test_original_503_observes_same_key_once_and_redacts_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'selected.json'
            publication = 'publication:sha256:' + '1' * 64
            path.write_text(json.dumps({'state': {'operations': [
                {'function': name, 'publication': publication} for name in ('update', 'query', 'scan')]}}))
            evidence = Evidence(root / 'evidence')
            result = {'schemaVersion': 'latent.cli.result.v1', 'category': 'success', 'error': None,
                      'outcomeKnown': True, 'requestDispatched': True, 'data': {}}
            client = SimpleNamespace(deadline=200, call=Mock(return_value=result), evidence=evidence)
            campaign = SimpleNamespace(client=client, full_path=path)
            with patch.object(observer.time, 'monotonic', return_value=100), \
                    patch('tools.java_transaction_qualification.lifecycle.as_user', return_value=nullcontext()):
                observer.observe_original_result(campaign, 'private-original-key')
            client.call.assert_called_once()
            args, kwargs = client.call.call_args
            self.assertEqual(args[-2:], ('--client-key', 'private-original-key'))
            self.assertEqual(kwargs['timeout'], 5)
            summary = json.loads((evidence.directory/'http-original-result-rpc-observation.json').read_bytes())
            self.assertEqual(summary['category'], 'success')
            self.assertTrue(summary['observationAvailable'])
            self.assertNotIn('private-original-key', json.dumps(summary))

    def test_http_result_remains_original_and_observer_does_not_retry(self):
        campaign = Campaign.__new__(Campaign)
        campaign.socket = Mock(return_value={'status': 503})
        campaign.result = Mock(side_effect=ValueError('original-http-failure'))
        with patch.object(observer, 'observe_original_result') as observe:
            with self.assertRaisesRegex(ValueError, 'original-http-failure'):
                campaign.original('original-key')
        campaign.socket.assert_called_once_with('result', original_key='original-key')
        observe.assert_called_once_with(campaign, 'original-key')
        campaign.result.assert_called_once_with({'status': 503})


if __name__ == '__main__':
    unittest.main()
