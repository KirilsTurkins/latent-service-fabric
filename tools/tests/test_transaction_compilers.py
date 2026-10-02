import copy
import unittest

from tools.qualify_transaction_contracts import check_surface
from tools.typescript_guest.compiler import declaration_aliases


class TransactionCompilerTests(unittest.TestCase):
    def test_reserved_delete_declaration_projection_is_exact_and_rejects_drift(self):
        text = ('/** @module Interface latent:state/key-value@0.2.0 **/\n'
                'export { _delete as delete };\n'
                'function _delete(transaction: Transaction, key: Uint8Array): void;\n')
        self.assertEqual(declaration_aliases(text), text.replace('\nfunction ', '\ndeclare function '))
        for forged in (text.replace('Transaction', 'number'), text.replace('0.2.0', '0.1.0'), text + text):
            with self.subTest(forged=forged), self.assertRaises(ValueError):
                declaration_aliases(forged)
        unrelated = 'export function get(key: string): void;\n'
        self.assertEqual(declaration_aliases(unrelated), unrelated)

    def test_actual_shape_requires_canonical_resources_async_operations_and_no_extra_authority(self):
        state = {'types': {'transaction': {'resource': 'latent:state/key-value@0.2.0/transaction'}},
                 'functions': {'get': {'kind': 'async-freestanding', 'params': ['borrow-transaction'], 'result': 'option-value'}}}
        intents = {'types': state['types'], 'functions': {'stage': {'kind': 'async-freestanding', 'params': ['borrow-transaction'], 'result': 'result-sequence'}}}
        runtime = {'types': {}, 'functions': {'now': {'kind': 'freestanding', 'params': [], 'result': 'u64'}}}
        expected = {'imports': {'latent:state/key-value@0.2.0': state, 'latent:intents/staging@0.1.0': intents,
                                'latent:clock/monotonic@0.1.0': runtime}, 'exports': {'run': 'async-u64'}}
        actual = copy.deepcopy(expected)
        actual['imports'].pop('latent:clock/monotonic@0.1.0')
        check_surface(expected, actual)
        for change in ('missing-intents', 'sync-call', 'new-resource', 'immediate-http', 'changed-export'):
            altered = copy.deepcopy(actual)
            if change == 'missing-intents': altered['imports'].pop('latent:intents/staging@0.1.0')
            elif change == 'sync-call': altered['imports']['latent:state/key-value@0.2.0']['functions']['get']['kind'] = 'freestanding'
            elif change == 'new-resource': altered['imports']['latent:intents/staging@0.1.0']['types'] = {'transaction': 'independent-owner'}
            elif change == 'immediate-http': altered['imports']['latent:http/client@0.2.0'] = runtime
            else: altered['exports'] = {'run': 'sync-u64'}
            with self.subTest(change=change), self.assertRaises(ValueError):
                check_surface(expected, altered)

if __name__ == '__main__':
    unittest.main()
