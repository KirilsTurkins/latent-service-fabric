"""Controls for the signed combined witness's explicit capability custody."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import rust_thread_http_combined_node as node
from tools.phase2_operator_process import WorkflowError


def descriptors():
    return [{'id': identity, 'capability': capability, 'tenant': 'examples',
             'profile': profile, 'configurationEpoch': '1', 'configurationDigest': 'sha256:' + '1' * 64}
            for identity, capability, _ops, profile, _kind in node.PROVIDERS]


class CombinedGrantControls(unittest.TestCase):
    def test_shared_provider_identity_still_requires_four_distinct_capabilities(self):
        observed = []
        peer = SimpleNamespace(origin=lambda role: {'scheme': 'http', 'host': '127.0.0.1', 'port': 1234})
        owner = SimpleNamespace(startup_record={'providers': descriptors()})
        with patch.object(node, 'policy', side_effect=lambda *args: observed.append(args)):
            grants = node.grant(object(), owner, 'signed-publication', peer)
        self.assertEqual({row['capability'] for row in grants}, set(node.IMPORTS))
        self.assertEqual(len(observed), 8)
        native = [args for args in observed if args[2] == 'native-examples-allow']
        self.assertEqual(len(native), 1)
        self.assertEqual(native[0][3]['rules'][0]['operations'], ['start'])
        self.assertEqual(native[0][3]['rules'][0]['resources'], {'kind': 'context'})

    def test_missing_native_descriptor_refuses_before_any_policy_write(self):
        owner = SimpleNamespace(startup_record={'providers': descriptors()[:-2] + descriptors()[-1:]})
        peer = SimpleNamespace(origin=lambda role: None)
        with patch.object(node, 'policy') as mutation:
            with self.assertRaises(WorkflowError):
                node.grant(object(), owner, 'signed-publication', peer)
        mutation.assert_not_called()


if __name__ == '__main__':
    unittest.main()
