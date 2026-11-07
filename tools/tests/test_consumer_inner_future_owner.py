"""Boundaries for the focused consumer poll-factory owner."""
import unittest
from tools import qualify_consumer_inner_future as owner


class ConsumerInnerFutureOwnerTests(unittest.TestCase):
    def raw(self, case):
        return (f"running 1 test\ntest {case} ... ok\n\n"
                "test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 49 filtered out; finished in 0.01s\n").encode()

    def test_fixed_cases_distinguish_private_inline_and_original_budget(self):
        self.assertEqual(len(owner.CASES), 12)
        self.assertEqual(len(set(owner.CASES)), 12)
        for case in owner.CASES:
            result = owner.case_result(self.raw(case), case)
            expected = ('private-counter-inline-component' if case in (*owner.PRIVATE_ORIGINAL, *owner.PRIVATE_DEFERRED)
                else 'private-counter-helper' if case in (*owner.PRIVATE_NEW, *owner.PRIVATE_REGRESSION) else 'public-original-ActivationBudget')
            self.assertEqual((result['passed'], result['ignored'], result['scope']), (1, 0, expected))

    def test_changed_or_missing_results_never_count_as_success(self):
        case = owner.PRIVATE_NEW[0]
        raw = self.raw(case)
        for changed in (raw + raw, raw.replace(b'0 ignored', b'1 ignored'),
                raw.replace(b'1 passed', b'0 passed'), raw.replace(b' ... ok', b' ... FAILED')):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                owner.case_result(changed, case)
        with self.assertRaises(ValueError):
            owner.case_result(raw, 'unregistered::case')

    def test_producer_branch_adds_private_and_public_cases_without_changing_consumer_selection(self):
        consumer = owner.cases_for(owner.BRANCH)
        producer = owner.cases_for(owner.PRODUCER_BRANCH)
        self.assertEqual(consumer, owner.CASES)
        self.assertEqual(len(consumer), 12)
        self.assertEqual(len(producer), 19)
        self.assertEqual(len(set(producer)), 19)
        added = (*owner.PRODUCER_PRIVATE, *owner.PRODUCER_PUBLIC)
        self.assertEqual(tuple(case for case in producer if case not in added), consumer)
        self.assertEqual(len(owner.PRODUCER_PRIVATE), 4)
        self.assertEqual(len(owner.PRODUCER_PUBLIC), 3)
        for case in added:
            self.assertNotIn(case, consumer)
            with self.assertRaisesRegex(ValueError, 'case-and-output'):
                owner.case_result(self.raw(case), case)
            result = owner.case_result(self.raw(case), case, producer)
            expected = ('private-counter-inline-component' if case in owner.PRODUCER_GUEST
                else 'private-counter-host-pipe' if case in owner.PRODUCER_HOST
                else 'private-counter-helper' if case in owner.PRODUCER_HELPERS
                else 'public-original-ActivationBudget')
            self.assertEqual((result['passed'], result['ignored'], result['scope']), (1, 0, expected))
            self.assertEqual(owner.case_ignored(case), case in owner.PRODUCER_GUEST)

        with self.assertRaisesRegex(ValueError, 'consumer-inner-future-branch'):
            owner.cases_for('unreviewed-branch')
        with self.assertRaisesRegex(ValueError, 'case-and-output'):
            owner.case_result(self.raw(consumer[0]), consumer[0], consumer[:-1])
        with self.assertRaisesRegex(ValueError, 'case-and-ignored-selection'):
            owner.case_ignored('unregistered::case')


if __name__ == '__main__':
    unittest.main()
