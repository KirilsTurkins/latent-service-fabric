"""Adverse receipt/source controls; no compiler, node or guest is run locally."""
import copy
import unittest

from tools import go_resource_late as late, go_resource_runtime_fixture as fixture
from tools.phase2_operator_process import WorkflowError
from tools.qualify_typescript_resource_runtime import execute


class GoResourceLate(unittest.TestCase):
    def test_source_is_a_single_closed_ordinary_library_extension(self):
        original = fixture.LIBRARY_SOURCE
        selected = late.library_source(original)
        insertion = b'    if mode == "late" { return lateFacilities() }\n'
        self.assertEqual(selected.removesuffix(late.LATE).replace(insertion, b'', 1), original)
        for drift in (original.replace(b'    data.Check()\n', b''), original + b'    data.Check()\n', selected):
            with self.subTest(drift=len(drift)), self.assertRaises(WorkflowError):
                late.library_source(drift)
        self.assertLess(late.LATE.index(b'close(entered)'), late.LATE.index(b'<-gate'))
        self.assertLess(late.LATE.index(b'<-entered'), late.LATE.index(b'if timer.Stop()'))
        self.assertNotIn(b'hex.EncodeToString(entropy', selected)
        self.assertNotIn(b'logged(string(entropy', selected)
        for selector in (None, 1, 'late'):
            with self.subTest(selector=selector), self.assertRaises(WorkflowError):
                execute(None, None, None, language='go', late_completion=selector)
        with self.assertRaises(WorkflowError):
            execute(None, None, None, language='unsupported', late_completion=True)

    def test_foreign_unknown_unreaped_unexecuted_and_overbudget_results_are_refused(self):
        component = 'sha256:' + 'a' * 64
        revision = {'releaseDigest': component, 'publicationId': 'original-publication'}
        budget = {'cpuFuel': 100, 'memoryBytes': 100, 'logBytes': 16384}
        row = {'activation': 'resource-late-examples', 'processReaped': True, 'exitCode': 0, 'decoded': [{'ok': late.EXPECTED}],
            'response': {'outcomeKnown': True, 'requestDispatched': True, 'data': {
                'resolvedRevision': revision, 'consumption': dict(cpuFuel='1', peakMemoryBytes='2',
                    logBytes=str(late.log_charge('resource-late-examples')), outboundRequests='0', childCalls='0', effectCount='0',
                    stateReadBytes='0', stateWriteBytes='0', blobReadBytes='0', blobWriteBytes='0')}}}
        late.accepted(row, budget, revision, component, late.EXPECTED)
        for drift in ('unreaped', 'unknown', 'undispatched', 'foreign', 'wrong-result', 'trap',
                      'fuel', 'memory', 'log', 'zero-log', 'root-log-only', 'external-effect'):
            bad = copy.deepcopy(row)
            if drift == 'unreaped': bad['processReaped'] = False
            elif drift == 'unknown': bad['response']['outcomeKnown'] = False
            elif drift == 'undispatched': bad['response']['requestDispatched'] = False
            elif drift == 'foreign': bad['response']['data']['resolvedRevision']['publicationId'] = 'foreign'
            elif drift == 'wrong-result': bad['decoded'] = [{'ok': fixture.EXPECTED['fresh']}]
            elif drift == 'trap': bad['exitCode'] = 4
            else:
                key = {'fuel': 'cpuFuel', 'memory': 'peakMemoryBytes', 'log': 'logBytes',
                       'zero-log': 'logBytes', 'root-log-only': 'logBytes', 'external-effect': 'outboundRequests'}[drift]
                bad['response']['data']['consumption'][key] = (
                    '0' if drift == 'zero-log' else str(late.log_charge(row['activation'], (late.ROOT_LOG,)))
                    if drift == 'root-log-only' else '16385' if drift == 'log' else '101')
            with self.subTest(drift=drift), self.assertRaises(WorkflowError):
                late.accepted(bad, budget, revision, component, late.EXPECTED)


if __name__ == '__main__':
    unittest.main()
