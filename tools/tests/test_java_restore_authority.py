"""Once-read generation and byte-custody controls; no native authority claim."""
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from tools.java_transaction_qualification import configuration as cfg, restore_authority as authority


class RestoreAuthorityControls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.proposals = {'bindings': {'original-binding': {'formatVersion': 1, 'tenant': cfg.TENANT}},
                          'policies': {'original-policy': {'formatVersion': 1, 'tenant': cfg.TENANT}}}
        self.calls = []
        self.unknown = False
        self.client = SimpleNamespace(call=self.call)

    def call(self, *arguments):
        self.calls.append(arguments)
        kind, name = arguments[2], arguments[arguments.index('--id') + 1]
        record = {'id': name, 'tenant': cfg.TENANT, 'recordKind': kind,
                  'generation': '7', 'revoked': False, 'document': {'original': True}}
        if 'get' in arguments:
            return {'outcomeKnown': True, 'category': 'success', 'data': {'policy': record}}
        operation = arguments[arguments.index('--operation-id') + 1]
        receipt = dict(record, generation='8', operationId=operation)
        return {'outcomeKnown': not self.unknown, 'category': 'success', 'data': {'receipt': receipt}}

    def test_each_current_generation_is_read_once_and_exact_files_apply_once(self):
        rows = authority.prepare(self.client, self.proposals, self.root)
        receipts = authority.apply(self.client, self.proposals, self.root, rows)
        self.assertEqual(len(self.calls), 4)
        self.assertTrue(all('get' in row for row in self.calls[:2]))
        self.assertTrue(all('apply' in row for row in self.calls[2:]))
        self.assertEqual([row[row.index('--expected-generation') + 1] for row in self.calls[2:]], ['7', '7'])
        self.assertEqual([value['generation'] for value in receipts.values()], ['8', '8'])

    def test_any_retained_input_drift_refuses_before_first_mutation(self):
        rows = authority.prepare(self.client, self.proposals, self.root)
        (self.root / rows[-1]['file']).write_bytes(b'{"changed":true}')
        with self.assertRaisesRegex(ValueError, 'input-byte-drift'):
            authority.apply(self.client, self.proposals, self.root, rows)
        self.assertEqual(len(self.calls), 2)

    def test_unknown_mutation_is_not_refreshed_retried_or_converted_to_success(self):
        rows = authority.prepare(self.client, self.proposals, self.root)
        self.unknown = True
        with self.assertRaisesRegex(ValueError, 'mutation-receipt'):
            authority.apply(self.client, self.proposals, self.root, rows)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(sum('get' in row for row in self.calls), 2)

    def test_changed_scope_generation_and_approval_fields_refuse_without_mutation(self):
        rows = authority.prepare(self.client, self.proposals, self.root)
        for field, value in (('expectedGeneration', '8'), ('file', '../outside'), ('approved', True)):
            invalid = copy.deepcopy(rows)
            invalid[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                authority.apply(self.client, self.proposals, self.root, invalid)
        for invalid in (True, 7, '0', '07', str(2**64), '1' * 100):
            with self.assertRaises(ValueError):
                authority.generation(invalid)
        self.assertEqual(len(self.calls), 2)

    def test_additional_session_is_exclusive_to_current_empty_operation_restore(self):
        from tools.java_transaction_qualification.lifecycle import Node
        from tools.phase2_operator_process import write_json
        node = Node(SimpleNamespace(), self.root / 'not-invoked', self.root)
        node.ordinal = 6
        path = self.root / 'settings.json'
        with self.assertRaisesRegex(ValueError, 'bounded-exclusive-node-session'):
            node.start(path)
        for index, state in enumerate(({'formatVersion': 1, 'operations': [], 'createIfMissing': False},
                      {'formatVersion': 2, 'operations': ['strict-command'], 'createIfMissing': False},
                      {'formatVersion': 2, 'operations': [], 'createIfMissing': True})):
            path = self.root / f'settings-{index}.json'
            write_json(path, {'state': state})
            with self.assertRaisesRegex(ValueError, 'bounded-current-restore-authority-session'):
                node.start(path, restore_authority=True)
        self.assertEqual(node.restore_authority_sessions, 0)
        self.assertEqual(node.ordinal, 6)


if __name__ == '__main__':
    unittest.main()
