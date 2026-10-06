import copy
import unittest

from tools.qualify_transaction_contracts import check_surface, definition_report_details
from tools.typescript_guest.compiler import declaration_aliases


class TransactionCompilerTests(unittest.TestCase):
    def test_public_dotnet_checksum_projection_preserves_original_inventory_and_other_evidence(self):
        original = {"bindings": {"bindings": {"authoritativeWitSha256": "1" * 64,
                    "outputs": {"KeyValueImportsInterop.cs": "a" * 64, "Clock.cs": "sha256:" + "b" * 64}},
                    "componentBytes": 1234}, "compilerClosureDigest": "sha256:" + "c" * 64}
        retained = copy.deepcopy(original)
        projected = definition_report_details("dotnet", original)
        self.assertEqual(original, retained)
        self.assertEqual(projected["bindings"]["bindings"]["authoritativeWitSha256"], "sha256:" + "1" * 64)
        self.assertEqual(projected["bindings"]["bindings"]["outputs"]["KeyValueImportsInterop.cs"], "sha256:" + "a" * 64)
        self.assertEqual(projected["bindings"]["bindings"]["outputs"]["Clock.cs"], "sha256:" + "b" * 64)
        self.assertEqual(projected["bindings"]["componentBytes"], 1234)
        self.assertEqual(projected["compilerClosureDigest"], original["compilerClosureDigest"])
        self.assertEqual(definition_report_details("dotnet", projected), projected)
        for language in ("rust", "c", "go", "java", "typescript"):
            self.assertIs(definition_report_details(language, original), original)

    def test_public_dotnet_checksum_projection_rejects_unidentified_or_malformed_digests(self):
        for invalid in ("", "A" * 64, "a" * 63, "sha256:" + "a" * 65, "unknown:" + "a" * 64, None, 123):
            for field in ("authoritativeWitSha256", "outputs"):
                original = {"bindings": {"bindings": {"authoritativeWitSha256": "a" * 64,
                            "outputs": {"KeyValueImportsInterop.cs": "b" * 64}}}}
                if field == "outputs":
                    original["bindings"]["bindings"][field]["KeyValueImportsInterop.cs"] = invalid
                else:
                    original["bindings"]["bindings"][field] = invalid
                with self.subTest(value=invalid, field=field), self.assertRaises(ValueError):
                    definition_report_details("dotnet", original)

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
