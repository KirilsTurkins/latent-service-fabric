import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import dotnet_monitor_cancel_fixture as original
from tools import dotnet_monitor_cause_fixture as fixture
from tools import dotnet_monitor_cause_node as node
from tools import dotnet_task_runtime_fixture as normal
from tools.phase2_operator_process import WorkflowError


class CauseFixtureTests(unittest.TestCase):
    def test_original_control_and_default_cases_remain_exact(self):
        prior=original.library_source(normal.LIBRARY_SOURCE)
        expanded=fixture.library_source(normal.LIBRARY_SOURCE)
        self.assertEqual(expanded.replace(fixture.PROBE_CASE,'').replace(fixture.DISPATCH_PROBE_CASE,''),prior)
        self.assertEqual(expanded.count(original.MONITOR_CASE),1)
        self.assertEqual(fixture.CASES,('monitor-wait','monitor-cause','monitor-dispatch'))
        self.assertNotIn('case "monitor-cause"',normal.LIBRARY_SOURCE)
        self.assertNotIn('case "monitor-dispatch"',normal.LIBRARY_SOURCE)
        self.assertEqual(expanded.count(fixture.PROBE_CASE), 1)
        self.assertEqual(expanded.count(fixture.DISPATCH_PROBE_CASE), 1)
        self.assertLess(fixture.DISPATCH_PROBE_CASE.index('Volatile.Write(ref started, 1);'),
                        fixture.DISPATCH_PROBE_CASE.index('lock (condition)', fixture.DISPATCH_PROBE_CASE.index('Task.Run')))
        self.assertLess(fixture.DISPATCH_PROBE_CASE.index('Monitor.Wait(condition, 1000)'),
                        fixture.DISPATCH_PROBE_CASE.index('Volatile.Read(ref started)'))
        self.assertEqual(fixture.PROBE_CASE.count('Monitor.Wait(condition, 1000)'),1)
        self.assertIn('if (phase != 1) throw new Exception("monitor acquired before wait released it");',
                      fixture.PROBE_CASE)
        with self.assertRaises(WorkflowError):
            normal.prepare(None,None,None,monitor_cancel=True,monitor_cause=True)

    def test_dispatch_observation_is_mode_specific_and_bounded(self):
        for started in (0, 1):
            value = ('ordinary-tasks:monitor-dispatch-timeout-p1-h1-n0-s' + str(started)
                     + '-inner1-joinok|fresh=1')
            self.assertEqual(fixture.observation({'decoded':[{'ok':value}]}, 'monitor-dispatch'), value)
            with self.assertRaises(WorkflowError): fixture.observation({'decoded':[{'ok':value}]})
        invalid = 'ordinary-tasks:monitor-dispatch-timeout-p1-h1-n0-s2-inner1-joinok|fresh=1'
        with self.assertRaises(WorkflowError): fixture.observation({'decoded':[{'ok':invalid}]}, 'monitor-dispatch')
        with self.assertRaises(WorkflowError): fixture.observation({'decoded':[]}, 'unknown')

    def test_observation_vocabulary_is_closed(self):
        for outcome in ('timeout','signaled','exception-sync','exception-other'):
            value='ordinary-tasks:monitor-cause-'+outcome+'-p1-h1-n0-inner1-joinok|fresh=1'
            self.assertEqual(fixture.observation({'decoded':[{'ok':value}]}),value)
        for row in ({'decoded':[{'ok':'monitor-wait passed'}]},
                    {'decoded':[{'err':'timeout'}]}, {'decoded':[]},
                    {'decoded':[{'ok':'ordinary-tasks:monitor-cause-timeout-p1-h1-n0-inner1-joinok|fresh=2'}]}):
            with self.assertRaises(WorkflowError):
                fixture.observation(row)


class CauseObservationTests(unittest.TestCase):
    def setUp(self):
        self.revision={'releaseDigest':'sha256:'+'a'*64,'revisionId':'r1'}
        self.component={'sha256':self.revision['releaseDigest']}
        self.target={'budget':{'cpuFuel':1000000000,'memoryBytes':134217728}}
        directory=tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.client=SimpleNamespace(node=SimpleNamespace(owner=SimpleNamespace(exited=lambda:False)),
                                    evidence=Path(directory.name))
        self.used={'cpuFuel':'1','peakMemoryBytes':'1','outboundRequests':'0','childCalls':'0',
                   'effectCount':'0','logBytes':'0','stateReadBytes':'0','stateWriteBytes':'0',
                   'blobReadBytes':'0','blobWriteBytes':'0'}

    def row(self,decoded):
        return {'processReaped':True,'exitCode':0,'decoded':decoded,
                'response':{'outcomeKnown':True,'data':{'consumption':copy.deepcopy(self.used),
                                                         'resolvedRevision':self.revision}}}

    def test_failure_control_is_retained_before_probe_and_both_are_reaped(self):
        control=self.row([{'err':'ordinary-task-failure:monitor-wait-block:unknown'}])
        probe=self.row([{'ok':'ordinary-tasks:monitor-cause-timeout-p1-h1-n0-inner1-joinok|fresh=1'}])
        dispatch=self.row([{'ok':'ordinary-tasks:monitor-dispatch-timeout-p1-h1-n0-s0-inner1-joinok|fresh=1'}])
        record={'attempts':[]}
        def check(_client,row,expected):
            if row['decoded']!=expected: raise WorkflowError('observed mismatch')
        with patch.object(node,'selected_revision',return_value=self.revision), \
             patch.object(node,'call',side_effect=[control,probe,dispatch]), \
             patch.object(node,'assert_value',side_effect=check), \
             patch.object(node.owners,'provider_idle',return_value={'idle':True}), \
             patch.object(node,'sample',return_value={'idle':True}):
            self.assertFalse(node.observe_cases(self.client,self.target,self.component,record,None,lambda:None))
        self.assertEqual([a['status'] for a in record['attempts']],['unexpected-result','observed','observed'])
        self.assertEqual(record['attempts'][1]['diagnosticObservation'],probe['decoded'][0]['ok'])
        self.assertEqual(record['attempts'][2]['diagnosticObservation'],dispatch['decoded'][0]['ok'])
        self.assertTrue(all(a['retirement']['provider']['idle'] for a in record['attempts']))

    def test_unknown_cause_outcome_never_starts_dispatch_probe(self):
        control=self.row([{'ok':original.expected('monitor-wait')}])
        probe=self.row([{'err':'unknown'}])
        probe['response']['outcomeKnown']=False
        with patch.object(node,'selected_revision',return_value=self.revision), \
             patch.object(node,'call',side_effect=[control,probe]) as invoke, \
             patch.object(node,'assert_value',return_value=None), \
             patch.object(node.owners,'provider_idle',return_value={'idle':True}), \
             patch.object(node,'sample',return_value={'idle':True}):
            with self.assertRaisesRegex(WorkflowError,'exact-terminal-and-revision'):
                node.observe_cases(self.client,self.target,self.component,{'attempts':[]},None,lambda:None)
        self.assertEqual(invoke.call_count,2)

    def test_unknown_control_outcome_never_starts_probe(self):
        control=self.row([{'err':'unknown'}])
        control['response']['outcomeKnown']=False
        with patch.object(node,'selected_revision',return_value=self.revision), \
             patch.object(node,'call',return_value=control) as invoke:
            with self.assertRaisesRegex(WorkflowError,'exact-terminal-and-revision'):
                node.observe_cases(self.client,self.target,self.component,{'attempts':[]},None,lambda:None)
        self.assertEqual(invoke.call_count,1)


if __name__=='__main__':
    unittest.main()