"""Synthetic controls for the separate child-call qualification route."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.java_transaction_qualification import child_campaign as child, configuration as cfg, policies
from tools.tests.test_java_early_http_campaign import PUBLICATION, hosts


class ChildCampaignControls(unittest.TestCase):
    def test_policy_has_only_state_and_clocks_for_the_child_guest(self):
        documents = child.proposals(hosts(), PUBLICATION)
        self.assertEqual({row['capability'] for row in documents['deploymentGrants']},
                         {policies.STATE_CONTRACT, *[row[0] for row in cfg.CLOCKS.values()]})
        for policy in documents['policies'].values():
            for rule in policy['rules']:
                self.assertEqual(rule['services'], [child.SERVICE])
                self.assertEqual(rule['publications'], [PUBLICATION])

    def test_child_budget_or_unrelated_grant_is_refused_before_deployment(self):
        item = SimpleNamespace(name='forbidden-child', component_digest='sha256:' + 'a' * 64)
        client = Mock()
        manifest = {'metadata': {'tenant': cfg.TENANT, 'name': child.DEPLOYMENT},
                    'spec': {'service': child.SERVICE, 'release': item.component_digest,
                             'resources': {'outboundRequests': 0, 'childCalls': 1}}}
        grants = [{'capability': name} for name in
                  (policies.STATE_CONTRACT, *[row[0] for row in cfg.CLOCKS.values()])]
        with patch.object(child, 'read_json', return_value=manifest), self.assertRaises(ValueError):
            child.metadata(client, Path('/unused'), item, PUBLICATION, grants)
        client.call.assert_not_called()
        manifest['spec']['resources']['childCalls'] = 0
        with patch.object(child, 'read_json', return_value=manifest), self.assertRaises(ValueError):
            child.metadata(client, Path('/unused'), item, PUBLICATION,
                           grants + [{'capability': policies.HTTP_CONTRACT}])
        client.call.assert_not_called()


if __name__ == '__main__':
    unittest.main()
