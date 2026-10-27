import unittest
from tools import qualify_host_stream_protected as owner


class FocusedStreamHostOwner(unittest.TestCase):
    def test_six_closed_case_ids_require_original_single_green_nonignored_outcome(self):
        names = [name for group in owner.CASES.values() for name in group]
        self.assertEqual(len(names), 6)
        self.assertEqual(len(set(names)), 6)
        for name in names:
            raw = ('test '+name+' ... ok\ntest result: ok. 1 passed; 0 failed; '
                '0 ignored; 0 measured; 123 filtered out; finished in 1s\n').encode()
            self.assertEqual(owner.outcome(raw,name),name)
            for changed in (raw.replace(b'1 passed',b'0 passed'),
                    raw.replace(b'0 failed',b'1 failed'),raw.replace(b'0 ignored',b'1 ignored'),
                    raw.replace(b'... ok',b'... FAILED'),b'',raw+raw):
                with self.assertRaises(ValueError):
                    owner.outcome(changed,name)

    def test_other_registered_case_cannot_satisfy_selected_case_or_missing_totals(self):
        first,second = owner.CASES['latent-streams']
        raw = ('test '+first+' ... ok\ntest result: ok. 1 passed; 0 failed; '
            '0 ignored; 0 measured; 123 filtered out; finished in 1s\n').encode()
        for changed,name in ((raw,second),(raw.split(b'test result:')[0],first),
                (raw.replace(b'1 passed',b'2 passed'),first),
                (raw.replace(b'0 measured',b'1 measured'),first)):
            with self.assertRaises(ValueError):
                owner.outcome(changed,name)

class OwnedTimerBoxOwner(unittest.TestCase):
    def test_closed_five_timer_ids_require_single_exact_nonignored_result(self):
        expected = (
            'runtime::owned_timer::original_budget_refuses_before_factory_and_preserves_foreign_capacity',
            'runtime::owned_timer::pending_drop_keeps_original_charge_through_concrete_future_destruction',
            'runtime::owned_timer::actual_sleep_pending_cancel_and_elapsed_keep_original_charge_until_drop',
            'runtime::owned_timer::unknown_owned_provider_refuses_without_legacy_fallback',
            'runtime::owned_timer::observed_inner_and_outer_refusals_and_pending_drop_preserve_originals',
        )
        self.assertEqual(owner.OWNED_TIMER_CASES, expected)
        self.assertEqual(owner.OWNED_TIMER_BRANCH, 'feat/sdk-owned-timer-box-20261027')
        self.assertTrue(callable(owner.qualify_owned_timer_box))
        for count in (0, 1, 7):
            self.assertTrue(owner.owned_timer_command_retired(
                {'returncode': 0, 'cleaned': True, 'reaped': count}))
        for count in (-1, False, True, None, '0'):
            self.assertFalse(owner.owned_timer_command_retired(
                {'returncode': 0, 'cleaned': True, 'reaped': count}))
        for field, value in (('cleaned', False), ('cleaned', 1),
                ('returncode', 1), ('returncode', -1), ('returncode', False)):
            row = {'returncode': 0, 'cleaned': True, 'reaped': 0}
            row[field] = value
            self.assertFalse(owner.owned_timer_command_retired(row))
        old = owner.CASES['latent-streams'][0]
        for name in expected:
            raw = ('test '+name+' ... ok\ntest result: ok. 1 passed; 0 failed; '
                '0 ignored; 0 measured; 123 filtered out; finished in 0.01s\n').encode()
            self.assertEqual(owner.outcome(raw, name), name)
            for changed in (
                raw.replace(name.encode(), old.encode()),
                raw.replace(b'0 ignored', b'1 ignored'),
                raw.replace(b'0 failed', b'1 failed'),
                raw.replace(b'1 passed', b'0 passed'),
                raw.split(b'test result:')[0],
                raw+raw,
            ):
                with self.assertRaises(ValueError):
                    owner.outcome(changed, name)
