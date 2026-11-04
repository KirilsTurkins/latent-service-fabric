"""Single captured post-stage policy cannot gain direct HTTP authority."""
import unittest

from tools.java_transaction_qualification import current_recipient, policies
from tools.tests.test_java_transaction_provision import observation


class SinglePoststagePolicyTests(unittest.TestCase):
    def test_single_native_effect_has_narrow_staging_and_service_dispatch(self):
        value, operations, publications = observation()
        effect = value['deferredHttp'][0]
        effect['operation'] = 'http'
        publication = effect['publication']
        value['deferredHttp'] = [effect]
        operations = [row for row in operations if row['publication'] == publication]
        endpoint = current_recipient.endpoint({'scheme': 'https', 'host': 'localhost', 'port': 52027}, 'e' * 64)
        with self.assertRaises(ValueError):
            policies.ObservedHosts.read(value, operations, intent_operation='http')
        hosts = policies.ObservedHosts.read(value, operations, intent_operation='http', single_http=True)
        proposal = policies.documents(hosts, {'poststage': publication}, current_http_endpoint=endpoint, single_http=True)
        self.assertNotIn(policies.HTTP_CONTRACT, {row['capability'] for row in proposal['deploymentGrants']})
        dispatch = proposal['policies']['java-dispatch']['rules']
        self.assertEqual(len(dispatch), 1)
        self.assertEqual(dispatch[0]['publications'], [publication])
        self.assertEqual(dispatch[0]['principals'][0]['kind'], 'service')
        with self.assertRaises(ValueError):
            policies.documents(hosts, {'poststage': publication}, single_http=True)
        with self.assertRaises(ValueError):
            policies.ObservedHosts.read(value, operations, intent_operation='put-once', single_http=True)


if __name__ == '__main__':
    unittest.main()
