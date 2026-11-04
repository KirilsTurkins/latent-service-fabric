"""Closed selected Audit owner controls and retained failures; no Cargo execution."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from tools import qualify_audit_memory as owner
from tools.phase2_operator_process import WorkflowError


class AuditMemoryProgrammeTests(unittest.TestCase):
    def test_twenty_five_actual_new_cases_are_closed_registered_and_not_ignored(self):
        names = owner.control_inventory()
        self.assertEqual(len(names), 25)
        registry = json.loads((owner.ROOT / 'tools/ci/suites.json').read_text(encoding='utf-8'))
        for _, package, _, _, expected in owner.CONTROLS:
            suite = next(row for row in registry['suites']
                         if row.get('package') == package and row['kind'] == 'lib')
            self.assertTrue(set(expected) <= set(suite['expectedCases']))
            self.assertFalse(set(expected) & set(suite['expectedIgnored']))
        # The immutable193 six survive the two reviewed envelope additions.
        # The six historical cases remain unselected here; exactly the two
        # envelope additions are now shared with this 25-case Audit programme.
        from tools.qualify_host_codec_native import CONTROLS as original
        historical = (
  'budget::descendants::tests::host_memory_resize_confirms_parent_peak_and_retains_terminal_child_capacity',
  'budget::host_memory::tests::actual_native_owner_keeps_capacity_after_terminal_report_and_settles_once',
  'budget::host_memory::tests::failed_pending_replacement_refunds_only_unallocated_capacity',
  'budget::host_memory::tests::growing_overlap_competes_before_allocation_and_shrink_keeps_peak',
  'budget::host_memory::tests::native_and_linear_memory_compete_before_allocation_and_failed_preparations_roll_back',
  'budget::host_memory::tests::partial_confirmation_keeps_pending_capacity_without_inventing_allocated_peak',
        )
        additions = (
  'budget::host_memory::tests::native_envelope_refuses_unobserved_retirement_before_mutating_original_ledger',
  'budget::host_memory::tests::original_native_envelope_reuses_only_retired_storage_without_refunding_capacity',
        )
        self.assertEqual(original[0][3], (*historical[:-1], *additions, historical[-1]))
        self.assertEqual(tuple(case for case in original[0][3] if case not in additions), historical)
        self.assertFalse(set(names) & set(historical))
        self.assertEqual(set(names) & set(original[0][3]), set(additions))
        group = next(row for row in original if row[0] == 'original-host-memory')
        self.assertEqual(group[1:3], ('latent-core', 'host_memory'))
        self.assertEqual(len(group[3]), 8)
        self.assertEqual(set(group[3]), set(historical) | set(additions))

    def test_selected_commands_bind_only_owned_packages_and_exact_new_wide_filter_cases(self):
        for group in owner.CONTROLS:
            args = owner.selected_arguments(('cargo',), group)
            self.assertEqual(args[:3], ('cargo', 'test', '--locked'))
            self.assertEqual(args[3:7], ('-p', group[1], '--lib', group[2]))
            self.assertEqual('--exact' in args, group[3])
            self.assertNotIn('--ignored', args)
            if group[1] == 'latent-core' and 'host_memory' in group[2]:
                self.assertTrue(group[3])
        bad = ('foreign', 'foreign-package', 'test', True, ('test',))
        with self.assertRaisesRegex(WorkflowError, 'closed-package-selector'):
            owner.selected_arguments(('cargo',), bad)

    def test_result_guards_reject_missing_extra_failed_or_ignored_controls(self):
        expected = ('owned::first', 'owned::second')
        listed = b'owned::first: test\nowned::second: test\n'
        passed = (b'test owned::first ... ok\ntest owned::second ... ok\n'
                  b'test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;\n')
        owner.exact_list(listed, expected)
        owner.exact_result(passed, expected)
        for raw in (listed.replace(b'owned::second: test\n', b''),
                    listed + b'owned::extra: test\n'):
            with self.assertRaises(WorkflowError):
                owner.exact_list(raw, expected)
        for raw in (passed.replace(b'owned::second ... ok', b'owned::second ... FAILED'),
                    passed.replace(b'owned::second ... ok', b'owned::second ... ignored'),
                    passed + b'test owned::extra ... ok\n',
                    passed.replace(b'0 ignored;', b'1 ignored;')):
            with self.assertRaises(WorkflowError):
                owner.exact_result(raw, expected)

    def test_prebuild_admission_failure_is_retained_without_launching_cargo(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(owner.sys, 'platform', 'linux'), \
                patch.object(owner.host_codec_wasmtime, 'verify', side_effect=ValueError('fixed-test-refusal')), \
                patch.object(owner, 'Commands') as commands:
            output = Path(temporary) / 'evidence'
            with self.assertRaises(ValueError):
                owner.qualify(output, 'a' * 40)
            failure = json.loads((output / 'result.json').read_text(encoding='utf-8'))
            self.assertEqual(failure['status'], 'failed')
            self.assertEqual(failure['failedStage'], 'prebuild-source-and-original-vendor-inputs')
            self.assertEqual(failure['commands'], [])
            self.assertFalse(failure['guestSourceCompiled'])
            commands.assert_not_called()


if __name__ == '__main__':
    unittest.main()
