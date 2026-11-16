"""Libtest execution labels must not replace discovered case identities."""
import unittest

from tools import ci_suite_discovery as discovery


class LibtestOutcomeTests(unittest.TestCase):
    available = frozenset({'clock::ordinary', 'clock::refuses', 'clock::external'})
    ignored = frozenset({'clock::external'})
    log = (
        'test clock::ordinary ... ok\n'
        'test clock::refuses - should panic ... ok\n'
        'test clock::external ... ignored, needs signed fixture\n'
        'test result: ok. 2 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out;\n'
    )

    def check(self, raw):
        return discovery.execution_cases(raw.encode(), self.available, self.ignored)

    def test_expected_panic_uses_the_discovered_identity(self):
        self.assertEqual(self.check(self.log),
                         (['clock::ordinary', 'clock::refuses'], ['clock::external']))

    def test_expected_panic_failure_is_not_promoted_to_success(self):
        for summary in ('2 passed; 0 failed', '1 passed; 1 failed'):
            with self.subTest(summary=summary), self.assertRaises(ValueError):
                self.check(self.log.replace('should panic ... ok', 'should panic ... FAILED')
                           .replace('2 passed; 0 failed', summary))

    def test_unknown_and_repeated_execution_labels_are_refused(self):
        for name in ('foreign - should panic', 'clock::refuses - should panic - should panic',
                     'clock::refuses - should fail', 'clock::refuses - should panic extra'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.check(self.log.replace('clock::refuses - should panic', name))

    def test_missing_duplicate_and_ignored_outcomes_remain_fail_closed(self):
        line = 'test clock::refuses - should panic ... ok\n'
        for raw in (self.log.replace(line, ''), self.log.replace(line, line + line),
                    self.log.replace(line, 'test clock::refuses ... ok\n' + line),
                    self.log.replace('should panic ... ok', 'should panic ... ignored')):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.check(raw)

    def test_interleaved_diagnostics_cannot_supply_missing_outcomes(self):
        for replacement in (
            'LSF-GO-ZERO-CLOCK-V1|wait-pending|0|5test clock::ordinary ... ok',
            'test clock::ordinary ... LSF-GO-ZERO-CLOCK-V1|wait-pending|0|5\nok',
        ):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                self.check(self.log.replace('test clock::ordinary ... ok', replacement))

    def test_exact_discovered_name_takes_precedence_over_a_label(self):
        name = 'generated case - should panic'
        raw = f'test {name} ... ok\ntest result: ok. 1 passed; 0 failed; 0 ignored;\n'
        self.assertEqual(discovery.execution_cases(raw.encode(), frozenset({name}), frozenset()),
                         ([name], []))

    def test_workspace_receipt_retains_underlying_names(self):
        receipt = {
            'schemaVersion': 'latent.ci.discovery.v1', 'sourceRevision': 'a' * 40,
            'suites': [{'id': 'clock.lib.clock', 'artifact': 'clock-abc',
                        'cases': sorted(self.available), 'ignored': sorted(self.ignored)}],
        }
        raw = '    Running unittests src/lib.rs (target/debug/deps/clock-abc)\n' + self.log
        report, errors = discovery.workspace_execution(receipt, raw)
        self.assertEqual(errors, [])
        self.assertEqual(report['suites'][0]['executed'], ['clock::ordinary', 'clock::refuses'])
        self.assertEqual(report['suites'][0]['skipped'], ['clock::external'])
        self.assertEqual(report['suites'][0]['failed'], [])
        self.assertTrue(discovery.workspace_execution(
            receipt, raw.replace('should panic ... ok', 'should panic ... FAILED'))[1])


if __name__ == '__main__':
    unittest.main()
