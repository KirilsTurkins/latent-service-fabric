"""Fail-closed controls for actual ordinary queued-root ownership evidence."""
import copy
import json
from pathlib import Path
import unittest

from tools import qualify_go_synchronization as reference


def rows():
    return [{'case': case, 'tenant': tenant, 'index': index, 'outcome': outcome}
            for case, tenant, index, outcome in reference.QUEUED_ROWS]


def output(values, filtered=50):
    records = '\n'.join('GO_QUEUED_CASE ' + json.dumps(value) for value in values)
    return (f'test {reference.QUEUED_CASE} ... ok\n{records}\n'
            f'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; {filtered} filtered out; finished in 21.00s\n').encode()


class GoQueued(unittest.TestCase):
    def test_both_tenants_require_seven_actual_queued_successors_after_original_cancel_and_trap(self):
        values = rows()
        self.assertEqual(len(values), 34)
        self.assertEqual(reference.queued_observations(output(values), 50), values)
        for tenant in ('tenant-a', 'tenant-b'):
            self.assertEqual([value['index'] for value in values
                              if value['case'] == 'queued-fresh' and value['tenant'] == tenant], list(range(7)))
        self.assertEqual([value['outcome'] for value in values if value['case'] == 'original'],
                         ['cancelled', 'guest-trap'])

    def test_each_queue_requires_foreign_refusal_owned_cancel_original_deadline_and_two_replacements(self):
        values = rows()
        for case, expected in [('foreign-cancel', 'not-found'), ('queued-cancel', 'cancelled'),
                               ('queued-deadline', 'deadline-exceeded'), ('saturated', 'resource-exhausted'),
                               ('replacement-queued', 'pending'), ('deadline-replacement', 'pending')]:
            selected = [value for value in values if value['case'] == case]
            self.assertEqual(len(selected), 2)
            self.assertEqual({value['outcome'] for value in selected}, {expected})
            for original in selected:
                changed = copy.deepcopy(values)
                changed[values.index(original)]['outcome'] = 'success'
                with self.subTest(case=case), self.assertRaisesRegex(ValueError, 'observation-contract'):
                    reference.queued_observations(output(changed), 50)

    def test_missing_duplicate_reordered_and_wrong_tenant_rows_cannot_substitute_for_queue_retirement(self):
        wrong = rows()
        wrong[10]['tenant'] = 'tenant-a'
        for values in [rows()[:-1], rows() + rows()[:1], list(reversed(rows())), wrong]:
            with self.subTest(values=values[-1]), self.assertRaisesRegex(ValueError, 'missing-or-extra|observation-contract'):
                reference.queued_observations(output(values), 50)

    def test_bool_index_unknown_private_fields_and_unbounded_or_duplicate_successor_indices_are_rejected(self):
        for key, value in [('private', 'not-exported'), ('index', True), ('index', 2**64),
                           ('tenant', 'tenant-c'), ('case', 'unknown'), ('outcome', False)]:
            changed = rows()
            changed[0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'private-or-unknown|observation-contract'):
                reference.queued_observations(output(changed), 50)
        changed = rows()
        indices = [index for index, value in enumerate(changed) if value['case'] == 'queued-fresh']
        changed[indices[1]]['index'] = 0
        with self.assertRaisesRegex(ValueError, 'observation-contract'):
            reference.queued_observations(output(changed), 50)

    def test_other_target_ignored_extra_pass_and_incomplete_or_oversized_stdout_are_not_qualification(self):
        raw = output(rows())
        for old, new in [(reference.QUEUED_CASE.encode(), reference.ADMISSION_CASE.encode()),
                         (b'0 ignored', b'1 ignored'), (b'50 filtered', b'49 filtered'),
                         (b'1 passed', b'2 passed'), (b'GO_QUEUED_CASE', b'GO_ADMISSION_CASE')]:
            with self.subTest(new=new), self.assertRaises(ValueError):
                reference.queued_observations(raw.replace(old, new), 50)
        with self.assertRaisesRegex(ValueError, 'output-bound'):
            reference.queued_observations(b'x' * (2 * 1024 * 1024 + 1), 50)

    def test_only_original_v5_managed_component_is_selected_and_queued_source_is_authenticated(self):
        fixture = Path('owned-managed-fixture')
        plan = reference.campaign('queued', fixture, None)
        self.assertEqual(plan, {'case': reference.QUEUED_CASE, 'fixture': 'managed-idle',
                                'variable': 'LSF_GO_MANAGED_IDLE_FIXTURE',
                                'inputs': [(fixture, 'go-component-activation-v5')]})
        with self.assertRaisesRegex(ValueError, 'unreviewed-campaign-or-negative'):
            reference.campaign('queued', fixture, Path('forbidden-v1'))
        snapshot = reference.source_snapshot(reference.ROOT)
        path = 'crates/latent-wasmtime/tests/local_service/runtime/go/queued.rs'
        self.assertEqual(snapshot[path], reference.digest((reference.ROOT / path).read_bytes()))


if __name__ == '__main__':
    unittest.main()
