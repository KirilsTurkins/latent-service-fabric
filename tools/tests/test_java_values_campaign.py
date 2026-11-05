"""Synthetic authority controls; these do not establish guest execution."""
import copy
import unittest

from tools.java_transaction_qualification import current_recipient, policies
from tools.tests.test_java_transaction_provision import observation


class JavaValuesAuthority(unittest.TestCase):
    def test_single_http_selection_remains_exact_and_does_not_grant_guest_http(self):
        value, operations, _ = observation()
        value['deferredHttp'] = value['deferredHttp'][:1]
        value['deferredHttp'][0]['operation'] = 'http'
        operations = operations[:1]
        publication = operations[0]['publication']
        with self.assertRaises(ValueError):
            policies.ObservedHosts.read(value, operations, intent_operation='http')
        hosts = policies.ObservedHosts.read(value, operations, intent_operation='http', single_http=True)
        endpoint = current_recipient.endpoint({'scheme': 'https', 'host': 'localhost', 'port': 45321}, 'e' * 64)
        result = policies.documents(hosts, {'put-once-values': publication},
                                    current_http_endpoint=endpoint, single_http=True)
        self.assertNotIn(policies.HTTP_CONTRACT, {row['capability'] for row in result['deploymentGrants']})
        rules = result['policies'][policies.DISPATCH_POLICY]['rules']
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]['publications'], [publication])
        self.assertEqual(rules[0]['principals'][0]['kind'], 'service')
        with self.assertRaises(ValueError):
            policies.documents(hosts, {'put-once-values': publication}, single_http=True)
        changed = copy.deepcopy(value)
        changed['deferredHttp'][0]['publication'] = 'publication:sha256:' + 'f' * 64
        with self.assertRaises(ValueError):
            policies.ObservedHosts.read(changed, operations, intent_operation='http', single_http=True)
        with self.assertRaises(ValueError):
            policies.ObservedHosts.read(value, operations, intent_operation='put-once', single_http=True)


if __name__ == '__main__':
    unittest.main()
