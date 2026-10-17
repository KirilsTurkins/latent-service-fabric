"""Reference execution cannot hide skipped, substituted or undiscovered cases."""
import unittest

from tools import run_rust_tls_reference as reference
from tools.dev_workflow.common import DevError


class TlsReferenceExecution(unittest.TestCase):
    def listing(self, names):
        return ('\n'.join(name + ': test' for name in names)
                + f'\n\n{len(names)} tests, 0 benchmarks\n').encode()

    def test_complete_source_reference_case_set_includes_both_root_ownership_controls(self):
        names = reference.discovered(self.listing(reference.CASES))
        self.assertEqual(names, list(reference.CASES))
        self.assertEqual(len(names), 23)
        self.assertIn('denied_root_task_prevents_context_allocation_and_native_admission', names)
        self.assertIn('root_bootstrap_admits_original_task_before_context_and_retains_it_through_final_epilogue', names)

    def test_missing_duplicate_or_substituted_native_case_rejects_before_execution(self):
        for names in (reference.CASES[:-1], (*reference.CASES[:-1], reference.CASES[0]),
                      (*reference.CASES[:-1], 'substituted_unrelated_case')):
            with self.subTest(names=names[-2:]), self.assertRaisesRegex(DevError, 'case-set'):
                reference.discovered(self.listing(names))

    def test_zero_cases_ignored_or_failed_reference_cannot_count_as_pass(self):
        reference.passed(b'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 19 filtered out;')
        for raw in (b'test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured;',
                    b'test result: ok. 0 passed; 0 failed; 1 ignored; 0 measured;',
                    b'test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured;'):
            with self.subTest(raw=raw), self.assertRaisesRegex(DevError, 'not-executed'):
                reference.passed(raw)


if __name__ == '__main__':
    unittest.main()
