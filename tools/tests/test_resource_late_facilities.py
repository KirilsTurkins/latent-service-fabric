"""Refuse false late-callback, logging, budget and retirement witnesses."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import resource_late_facilities as late
from tools import dotnet_resource_runtime_fixture as managed
from tools import java_resource_runtime_fixture as java
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT, read_file


class ResourceLateFacilities(unittest.TestCase):
    def row(self, language='java', mode='late'):
        budget = {'cpuFuel': 1000000000, 'memoryBytes': 67108864, 'logBytes': 256}
        revision = {'releaseDigest': 'sha256:'+'a'*64, 'generation': '2'}
        usage = {name: '0' for name in ('outboundRequests', 'childCalls', 'effectCount',
            'stateReadBytes', 'stateWriteBytes', 'blobReadBytes', 'blobWriteBytes')}
        usage.update(cpuFuel='10', peakMemoryBytes='4096', logBytes=str(late.log_charge('jl-a', 'L')))
        row = {'activation': 'jl-a', 'processReaped': True, 'exitCode': 0,
            'decoded': [{'ok': late.EXPECTED[language][mode]}],
            'response': {'outcomeKnown': True, 'requestDispatched': True, 'category': 'success',
                'data': {'resolvedRevision': revision, 'consumption': usage}}}
        return row, budget, revision

    def test_exact_late_and_fresh_results_require_one_linked_completion_record(self):
        for language in late.EXPECTED:
            for mode in late.EXPECTED[language]:
                row, budget, revision = self.row(language, mode)
                late.checked(row, language, mode, budget, revision['releaseDigest'], revision)
                row['response']['data']['consumption']['logBytes'] = '1'
                with self.assertRaises(WorkflowError):
                    late.checked(row, language, mode, budget, revision['releaseDigest'], revision)

    def test_terminal_result_revision_and_process_cannot_be_substituted(self):
        for mutate in (
                lambda r: r.update(processReaped=False),
                lambda r: r.update(exitCode=4),
                lambda r: r.update(decoded=[{'ok': late.EXPECTED['java']['fresh']}]),
                lambda r: r['response'].update(outcomeKnown=False),
                lambda r: r['response'].update(requestDispatched=False),
                lambda r: r['response'].update(category='platform-failure'),
                lambda r: r['response']['data'].update(resolvedRevision={'releaseDigest': 'other'})):
            row, budget, revision = self.row(); mutate(row)
            with self.assertRaises(WorkflowError):
                late.checked(row, 'java', 'late', budget, revision['releaseDigest'], revision)

    def test_original_budgets_zero_other_effects_and_canonical_counts_remain_mandatory(self):
        for name, value in (('cpuFuel', '0'), ('cpuFuel', '1000000001'),
                ('peakMemoryBytes', '67108865'), ('logBytes', '0'), ('logBytes', '257'),
                ('outboundRequests', '1'), ('childCalls', '1'), ('stateWriteBytes', '1'),
                ('cpuFuel', True), ('cpuFuel', '-1'), ('cpuFuel', '01'), ('cpuFuel', '\uff11')):
            row, budget, revision = self.row()
            row['response']['data']['consumption'][name] = value
            with self.subTest(name=name, value=value), self.assertRaises(WorkflowError):
                late.checked(row, 'java', 'late', budget, revision['releaseDigest'], revision)

    def test_log_identity_is_bounded_ascii_and_message_is_one_closed_marker(self):
        self.assertEqual(late.log_charge('jl-a', 'L'), late.log_charge('jf-b', 'F'))
        self.assertEqual(late.log_charge('a'*32, 'L')-late.log_charge('a', 'L'), 62)
        for activation, marker in (('', 'L'), ('a'*33, 'L'), ('\u96ea', 'L'), ('a', 'LL'), ('a', '\n')):
            with self.assertRaises(WorkflowError): late.log_charge(activation, marker)

    def test_retirement_uses_real_list_shape_and_all_eighteen_unsigned_counters(self):
        original = {'scope': 'node', 'unavailable': [],
            'counters': {name: '0' for name in late.ACTIVE_COUNTERS}}
        client = Mock(); client.call.return_value = {'data': {'nodeUsage': original, 'nextPageToken': None}}
        with tempfile.TemporaryDirectory() as temporary, patch.object(late, 'sample', return_value={'idle': True}) as sample:
            late.retired(client, object(), {'name': 'resource-examples'}, Path(temporary), 'jl-a')
            self.assertEqual(sample.call_args.args[-1], 2)
            for mutate in (lambda n: n.update(unavailable=False), lambda n: n.update(unavailable=None),
                    lambda n: n.update(unavailable=['calls']), lambda n: n.update(scope='tenant'),
                    lambda n: n['counters'].pop(late.ACTIVE_COUNTERS[0]),
                    lambda n: n['counters'].update({late.ACTIVE_COUNTERS[0]: '1'}),
                    lambda n: n['counters'].update({late.ACTIVE_COUNTERS[0]: True})):
                changed = copy.deepcopy(original); mutate(changed)
                client.call.return_value['data']['nodeUsage'] = changed
                with self.assertRaises((WorkflowError, KeyError)):
                    late.retired(client, object(), {'name': 'resource-examples'}, Path(temporary), 'bad')

    def test_first_rejected_outcome_and_bounded_cli_streams_are_retained(self):
        row, budget, revision = self.row(); row['decoded'] = [{'ok': 'wrong'}]
        process = Mock(); process.buffers = [bytearray(b'fixed public result'), bytearray()]
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(late, 'selected_revision', return_value=revision), \
                patch.object(late, 'start_call', return_value=process), \
                patch.object(late, 'finish_call', return_value=row):
            root = Path(temporary)
            with self.assertRaises(WorkflowError):
                late.programme({'examples': Mock()}, {'examples': {'budget': budget}}, object(), root,
                    revision['releaseDigest'], 'java')
            value = json.loads((root/'programme-progress.json').read_bytes())
            self.assertEqual(value['status'], 'failed'); self.assertEqual(value['failedMode'], 'late')
            self.assertEqual(value['attempts'][0]['invocation'], row); self.assertEqual(value['cases'], [])
            self.assertEqual((root/'failed-jl-a-stdout.txt').read_bytes(), b'fixed public result')
            process.close.assert_called()

    def test_default_managed_library_and_opted_late_source_keep_original_resources_and_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            normal, _ = managed.project(root/'normal', root/'original')
            selected, _ = managed.project(root/'selected', root/'late', late_completion=True)
            self.assertEqual((root/'original/library/Library.cs').read_bytes(), managed.LIBRARY_SOURCE.encode())
            self.assertEqual((root/'late/library/Library.cs').read_bytes(),
                read_file(ROOT/'tools/fixtures/dotnet-resource-late/Library.cs'))
            self.assertEqual((normal/'capsule-project.json').read_bytes(), (selected/'capsule-project.json').read_bytes())
            for name, raw in managed.DATA.items():
                self.assertEqual((root/'original/library/child'/name).read_bytes(), raw)
                self.assertEqual((root/'late/library/child'/name).read_bytes(), raw)

    def test_truthy_non_boolean_selectors_refuse_before_capture_or_project_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for value in (1, 'true', None):
                with self.assertRaises(WorkflowError):
                    managed.project(root/'project', root/'outside', late_completion=value)
                with self.assertRaises(WorkflowError):
                    java.capture(root/'java', Mock(), late_completion=value)
            self.assertEqual(list(root.iterdir()), [])


if __name__ == '__main__': unittest.main()
