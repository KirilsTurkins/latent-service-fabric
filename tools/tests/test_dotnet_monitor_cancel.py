"""Bounded owner checks for actual ordinary monitor/cancellation observations."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import (admit_dotnet_monitor_cancel_evidence as admission,
                   dotnet_monitor_cancel_node as node,
                   qualify_dotnet_monitor_cancel as qualify)
from tools.phase2_operator_process import WorkflowError
from tools.phase3_resource_identity import file_identity


class TwoCaseObservation(unittest.TestCase):
    def setUp(self):
        self.revision = {'releaseDigest': 'sha256:' + 'a' * 64, 'revisionId': 'r1'}
        self.component = {'sha256': self.revision['releaseDigest']}
        self.target = {'budget': {'cpuFuel': 1000000000, 'memoryBytes': 134217728}}
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.client = SimpleNamespace(node=SimpleNamespace(owner=SimpleNamespace(exited=lambda: False)),
            evidence=Path(temporary.name))
        self.used = {'cpuFuel': '1', 'peakMemoryBytes': '1', 'outboundRequests': '0',
            'childCalls': '0', 'effectCount': '0', 'logBytes': '0', 'stateReadBytes': '0',
            'stateWriteBytes': '0', 'blobReadBytes': '0', 'blobWriteBytes': '0'}

    def row(self, mode):
        return {'processReaped': True, 'exitCode': 0,
            'response': {'outcomeKnown': True, 'data': {'consumption': copy.deepcopy(self.used),
                'resolvedRevision': self.revision}},
            'decoded': [{'ok': node.fixture.expected(mode)}]}

    def run_cases(self, rows, record, checkpoints):
        with patch.object(node, 'selected_revision', return_value=self.revision), \
             patch.object(node, 'call', side_effect=rows), \
             patch.object(node.owners, 'provider_idle', return_value={'idle': True}), \
             patch.object(node, 'sample', return_value={'idle': True}):
            return node.observe_cases(self.client, self.target, self.component, record, None,
                lambda: checkpoints.append(copy.deepcopy(record)))

    def test_deployment_budget_refuses_extra_authority_and_changed_limits(self):
        target = {'budget': dict(node.ORIGINAL_BUDGET)}
        self.assertEqual(node.original_budget(target), node.ORIGINAL_BUDGET)
        for key, value in (('cpuFuel', 1000000001), ('memoryBytes', 134217729),
                ('wallTimeLimitMillis', 120001), ('outboundRequests', 1), ('effectCount', 1), ('logBytes', False)):
            changed = {'budget': dict(node.ORIGINAL_BUDGET)}; changed['budget'][key] = value
            with self.subTest(key=key), self.assertRaises(WorkflowError): node.original_budget(changed)

    def test_both_actual_outcomes_require_separate_retirement(self):
        record = {'attempts': []}; checkpoints = []
        self.assertTrue(self.run_cases([self.row(mode) for mode in node.MODES], record, checkpoints))
        self.assertEqual([r['mode'] for r in record['attempts']], list(node.MODES))
        self.assertTrue(all(r['retirement']['provider']['idle'] for r in record['attempts']))
        self.assertEqual(len(checkpoints), 6)
        self.assertNotIn('retirement', checkpoints[0]['attempts'][0])
        self.assertIn('retirement', checkpoints[2]['attempts'][0])

    def test_unexpected_monitor_result_is_retained_before_failure(self):
        first, second = (self.row(mode) for mode in node.MODES)
        second['decoded'] = [{'error': 'monitor-unsupported'}]
        record = {'attempts': []}; checkpoints = []
        def check(_client, row, expected):
            if row['decoded'] != expected:
                raise WorkflowError('observed mismatch')
        with patch.object(node, 'assert_value', side_effect=check):
            self.assertFalse(self.run_cases([first, second], record, checkpoints))
        self.assertEqual(record['attempts'][-1]['invocation']['decoded'], second['decoded'])
        self.assertEqual(checkpoints[-1]['attempts'][-1]['invocation']['decoded'], second['decoded'])
        self.assertIn('retirement', record['attempts'][0])
        self.assertIn('retirement', record['attempts'][-1])
        self.assertEqual(record['attempts'][-1]['status'], 'unexpected-result')

    def test_first_unexpected_terminal_continues_only_after_confirmed_idle(self):
        first, second = (self.row(mode) for mode in node.MODES)
        first['decoded'] = [{'error': 'first-unexpected'}]
        record = {'attempts': []}; checkpoints = []
        def check(_client, row, expected):
            if row['decoded'] != expected: raise WorkflowError('observed mismatch')
        with patch.object(node, 'assert_value', side_effect=check):
            self.assertFalse(self.run_cases([first, second], record, checkpoints))
        self.assertEqual([row['mode'] for row in record['attempts']], list(node.MODES))
        self.assertEqual(record['attempts'][0]['status'], 'unexpected-result')
        self.assertTrue(all('retirement' in row for row in record['attempts']))
        self.client.node.owner.exited = lambda: True
        with patch.object(node, 'assert_value', side_effect=check):
            stopped = {'attempts': []}
            with self.assertRaisesRegex(WorkflowError, 'node-exited-before-retirement'):
                self.run_cases([first, second], stopped, [])
        self.assertEqual(len(stopped['attempts']), 1)

    def test_both_mismatch_diagnostics_are_retained_separately(self):
        rows = [self.row(mode) for mode in node.MODES]
        record = {'attempts': []}
        def mismatch(client, row, expected):
            (client.evidence / 'unexpected-invocation-diagnostics.json').write_text(
                json.dumps({'expected': expected}), encoding='utf-8')
            raise WorkflowError('observed mismatch')
        with patch.object(node, 'assert_value', side_effect=mismatch):
            self.assertFalse(self.run_cases(rows, record, []))
        for mode, attempt in zip(node.MODES, record['attempts']):
            name = 'unexpected-' + mode + '-diagnostics.json'
            self.assertEqual(attempt['diagnostic'], name)
            self.assertEqual(json.loads((self.client.evidence / name).read_text())['expected'],
                [{'ok': node.fixture.expected(mode)}])
        self.assertFalse((self.client.evidence / 'unexpected-invocation-diagnostics.json').exists())

    def test_unexpected_assertion_error_stops_before_second_invocation(self):
        record = {'attempts': []}
        with patch.object(node, 'selected_revision', return_value=self.revision), \
             patch.object(node, 'call', side_effect=[self.row(mode) for mode in node.MODES]) as invoke, \
             patch.object(node, 'assert_value', side_effect=ValueError('unexpected')):
            with self.assertRaisesRegex(ValueError, 'unexpected'):
                node.observe_cases(self.client, self.target, self.component, record, None, lambda: None)
        self.assertEqual(invoke.call_count, 1)
        self.assertEqual(len(record['attempts']), 1)

    def test_unknown_terminal_stops_before_second_invocation(self):
        first = self.row(node.MODES[0]); first['response']['outcomeKnown'] = False
        record = {'attempts': []}; checkpoints = []
        with patch.object(node, 'selected_revision', return_value=self.revision), \
             patch.object(node, 'call', side_effect=[first, self.row(node.MODES[1])]) as invoke:
            with self.assertRaisesRegex(WorkflowError, 'exact-terminal-and-revision'):
                node.observe_cases(self.client, self.target, self.component, record, None,
                    lambda: checkpoints.append(copy.deepcopy(record)))
        self.assertEqual(invoke.call_count, 1)
        self.assertEqual(checkpoints[-1]['attempts'][0]['invocation'], first)
        self.assertNotIn('retirement', record['attempts'][0])

    def test_changed_revision_budget_or_effects_refuse(self):
        for mutation in ('revision', 'fuel', 'effect'):
            first = self.row(node.MODES[0])
            if mutation == 'revision':
                first['response']['data']['resolvedRevision'] = {'releaseDigest': 'sha256:other'}
            elif mutation == 'fuel': first['response']['data']['consumption']['cpuFuel'] = '1000000001'
            else: first['response']['data']['consumption']['outboundRequests'] = '1'
            with self.subTest(mutation=mutation), self.assertRaises(WorkflowError):
                self.run_cases([first], {'attempts': []}, [])


class FixtureSelection(unittest.TestCase):
    def test_original_cases_and_source_stay_unchanged_without_opt_in(self):
        from tools import dotnet_task_runtime_fixture as normal, dotnet_monitor_cancel_fixture as witness
        self.assertEqual(normal.CASES, qualify.ORIGINAL_CASES)
        combined = witness.library_source(normal.LIBRARY_SOURCE)
        self.assertEqual(combined.replace(witness.CANCEL_CASE, '').replace(witness.MONITOR_CASE, ''), normal.LIBRARY_SOURCE)
        self.assertEqual(witness.CASES, ('cancel-pending', 'monitor-wait'))
        self.assertNotIn('case "cancel-pending"', normal.LIBRARY_SOURCE)
        self.assertNotIn('case "monitor-wait"', normal.LIBRARY_SOURCE)
        with self.assertRaises(WorkflowError):
            witness.library_source(normal.LIBRARY_SOURCE + '        case "cancel-pending":\n')


class SourceFailureRetention(unittest.TestCase):
    def test_dirty_source_refuses_before_compilation_and_retains_stage(self):
        import sys
        import types
        fake = types.ModuleType('tools.wasmtime_48_0_8_678b_native_products')
        head = 'a' * 40
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); native = root / 'native'; tools = root / 'tools'
            native.mkdir(); tools.mkdir(); output = root / 'output'
            with patch.dict(sys.modules, {'tools.wasmtime_48_0_8_678b_native_products': fake}), \
                 patch.object(qualify.sys, 'platform', 'linux'), \
                 patch.object(qualify.subprocess, 'check_output', side_effect=[head.encode(), b' dirty']):
                with self.assertRaisesRegex(WorkflowError, 'clean-exact-source'):
                    qualify.qualify(native, tools, output, expected_head=head)
            failed = json.loads((output / 'FAILED.json').read_text())
            self.assertEqual(failed['stage'], 'exact-source-and-native-authentication')
            self.assertFalse(failed['nativeAotCompilationAttempted'])
            self.assertFalse(failed['fullTicketQualification'])


class ProductAndRetention(unittest.TestCase):
    def test_all_native_materials_must_match_and_changed_input_refuses(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'source'; root.mkdir()
            native = Path(temporary) / 'native'; native.mkdir()
            entries = {}
            for index in range(135):
                name = f'materials/{index:03}.txt'; file = root / name
                file.parent.mkdir(exist_ok=True); file.write_text(str(index))
                entries[name] = file_identity(file)
            (native / 'native-products.json').write_text(json.dumps({'materials': entries}))
            with patch.object(qualify, 'ROOT', root):
                self.assertEqual(qualify.current_materials(native), entries)
                (root / 'materials/042.txt').write_text('changed')
                with self.assertRaisesRegex(WorkflowError, 'current-native-material'):
                    qualify.current_materials(native)
            (native / 'native-products.json').write_text(json.dumps({'materials': {'../outside': {}}}))
            with self.assertRaisesRegex(WorkflowError, 'material-count'):
                qualify.current_materials(native)

    def test_public_admission_excludes_private_files_and_refuses_overflow(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); evidence = root / 'witness/node/FAILED.json'
            evidence.parent.mkdir(parents=True); evidence.write_text('{"status":"failed"}')
            private = root / 'witness/project/private.txt'; private.parent.mkdir(); private.write_text('private')
            value = admission.admit(root)
            self.assertEqual(value['status'], 'passed')
            self.assertTrue((root / 'public/witness/node/FAILED.json').is_file())
            self.assertFalse((root / 'public/witness/project/private.txt').exists())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); evidence = root / 'witness/node/FAILED.json'
            evidence.parent.mkdir(parents=True); evidence.write_text('x' * 40)
            with patch.object(admission, 'MAX_TOTAL', 10), self.assertRaises(WorkflowError):
                admission.admit(root)
            self.assertFalse((root / 'public').exists())
            self.assertEqual(json.loads((root / 'evidence-admission.json').read_text())['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
