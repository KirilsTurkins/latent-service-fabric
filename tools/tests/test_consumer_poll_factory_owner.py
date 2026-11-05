"""Boundaries for the focused consumer poll-factory owner."""
import unittest
from tools import qualify_consumer_poll_factory as owner


class ConsumerPollFactoryOwnerTests(unittest.TestCase):
    def raw(self, case):
        return (f"running 1 test\ntest {case} ... ok\n\n"
                "test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 49 filtered out; finished in 0.01s\n").encode()

    def test_fixed_cases_distinguish_private_inline_and_original_budget(self):
        self.assertEqual(len(owner.CASES), 6)
        self.assertEqual(len(set(owner.CASES)), 6)
        for case in owner.CASES:
            result = owner.case_result(self.raw(case), case)
            expected = ('private-counter-inline-component' if case in owner.PRIVATE_ORIGINAL
                else 'private-counter-helper' if case in owner.PRIVATE_NEW else 'public-original-ActivationBudget')
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


if __name__ == '__main__':
    unittest.main()
