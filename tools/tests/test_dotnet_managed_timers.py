"""Exact original timer producer and ownership receipt boundaries; no guest credit."""
import copy
import json
from pathlib import Path
import unittest

from tools.dotnet_guest import managed_work, task_wait
from tools.dotnet_managed_work_controls import TIMER_CASES
from tools.rust_capsule_project import ROOT

FIXTURE = ROOT/'sdk/dotnet-guest/tests/fixtures/managed-timer-rewrite.json'


class ManagedTimerContractTests(unittest.TestCase):
    def test_actual_serialized_corelib_receipt_keeps_original_and_timer_identities(self):
        value = json.loads(FIXTURE.read_text(encoding='utf8'))
        task_wait.validate_receipt(value, finite=True, managed=True)
        self.assertEqual(value['generatedHelperCount'], 91)
        self.assertEqual(value['unchangedOriginalMethods'], 44719)
        selected = value['managedAcceptedWork']
        self.assertEqual(len(selected['modifiedOriginalMethods']), 23)
        self.assertEqual(selected['copiedRegistryMethods'], 58)
        self.assertEqual(selected['structuralTimerLimit'], 32)
        self.assertFalse(selected['qualified'])

    def test_each_original_producer_and_every_timer_policy_is_required(self):
        value = json.loads(FIXTURE.read_text(encoding='utf8'))
        selected = value['managedAcceptedWork']
        for name in selected['modifiedOriginalMethods']:
            changed = copy.deepcopy(value)
            changed['managedAcceptedWork']['modifiedOriginalMethods'][name] = '0'*64
            with self.subTest(method=name), self.assertRaises(ValueError):
                task_wait.validate_receipt(changed, finite=True, managed=True)
        for key in ('timerAdmission', 'timerRetirement', 'timerCallbackContext', 'structuralTimerLimit'):
            changed = copy.deepcopy(value)
            changed['managedAcceptedWork'][key] = True if type(selected[key]) is int else 'unproved'
            with self.subTest(key=key), self.assertRaises(ValueError):
                task_wait.validate_receipt(changed, finite=True, managed=True)

    def test_timer_and_old_registry_receipts_cannot_mix_counts_or_methods(self):
        value = json.loads(FIXTURE.read_text(encoding='utf8'))
        for count in (True, 77, 90, 92):
            changed = copy.deepcopy(value); changed['generatedHelperCount'] = count
            with self.subTest(count=count), self.assertRaises(ValueError):
                task_wait.validate_receipt(changed, finite=True, managed=True)
        changed = copy.deepcopy(value); changed['managedAcceptedWork']['patch'] = managed_work.REWRITE_RECEIPT['patch']
        with self.assertRaises(ValueError): task_wait.validate_receipt(changed, finite=True, managed=True)
        old = json.loads((ROOT/'sdk/dotnet-guest/tests/fixtures/managed-work-rewrite.json').read_text(encoding='utf8'))
        task_wait.validate_receipt(old, finite=True, managed=True)
        self.assertEqual(old['generatedHelperCount'], 77)

    def test_producer_ports_are_explicit_and_each_causal_state_has_a_control(self):
        self.assertEqual(len(TIMER_CASES), len(set(TIMER_CASES)))
        self.assertEqual(len(TIMER_CASES), 11)
        source = (ROOT/'sdk/dotnet-guest/tests/fixtures/managed-timer-state-control/Program.cs').read_text(encoding='utf8')
        for name in TIMER_CASES:
            self.assertEqual(source.count('"'+name+'"'), 1)
        self.assertIn('timerProducerState = "explicit-test-port"', source)
        self.assertIn('guestQualified = false', source)


if __name__ == '__main__':
    unittest.main()
