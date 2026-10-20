"""Diagnostic success never promotes a failed callback into qualification."""
import copy
import unittest
from tools import java_resource_runtime_diagnostic as diagnostic
from tools.phase2_operator_process import WorkflowError

class JavaResourceDiagnostic(unittest.TestCase):
    @staticmethod
    def row():
        revision={'releaseDigest':'sha256:'+'a'*64}
        used={'cpuFuel':'1','peakMemoryBytes':'1','logBytes':'219',**dict.fromkeys(('outboundRequests','childCalls','effectCount','stateReadBytes','stateWriteBytes','blobReadBytes','blobWriteBytes'),'0')}
        row={'processReaped':True,'exitCode':0,'decoded':[{'ok':diagnostic.runtime.fixture.EXPECTED['fresh']}],
            'response':{'outcomeKnown':True,'category':'success','data':{'consumption':used,'resolvedRevision':revision},'error':None}}
        return row,revision
    def test_exact_value_and_real_trap_remain_distinct_nonqualifying_observations(self):
        row,revision=self.row();self.assertEqual(diagnostic.checked(row,revision['releaseDigest'],revision,'fresh'),'exact-success-value')
        row.update(exitCode=4,decoded=None);row['response'].update(category='platform-failure',error={'code':'guest-trap'})
        self.assertEqual(diagnostic.checked(row,revision['releaseDigest'],revision,'fresh'),'guest-trap')
    def test_unknown_foreign_unreaped_effectful_or_overbudget_results_refuse(self):
        for change in ('unknown','revision','unreaped','value','effects','log-cap','failure'):
            row,revision=self.row()
            if change=='unknown':row['response']['outcomeKnown']=False
            elif change=='revision':row['response']['data']['resolvedRevision']={'releaseDigest':'sha256:'+'b'*64}
            elif change=='unreaped':row['processReaped']=False
            elif change=='value':row['decoded']=[{'ok':'foreign'}]
            elif change=='effects':row['response']['data']['consumption']['outboundRequests']='1'
            elif change=='log-cap':row['response']['data']['consumption']['logBytes']='257'
            else:row['exitCode']=4;row['response'].update(category='platform-failure',error={'code':'permission-denied'})
            with self.subTest(change=change),self.assertRaises(WorkflowError):diagnostic.checked(row,revision['releaseDigest'],revision,'fresh')
    def test_closed_cases_preserve_same_original_public_ids_and_no_pending_claim(self):
        self.assertEqual(diagnostic.CASES,(('foreign','fresh','resource-java-foreign-fresh'),('examples','clear','resource-java-clear'),('examples','parallel','resource-java-parallel')))

if __name__=='__main__':unittest.main()
