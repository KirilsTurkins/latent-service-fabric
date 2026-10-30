"""Source-stage protocol reader controls, never signed Go execution evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from tools import qualify_go_write_progress_runtime as progress


def records(uncertain=False,close='closed'):
    values=[]
    for label,mode,wanted in progress.EXPECTED:
        n=24577 if mode==2 else wanted  # Deliberately not a full host-chunk multiple.
        if mode==2:
            values.append(('QUOTA',{'inputBudgetBytes':1048576,'acceptedWriteBytes':n,'liveConnection':True,
                'pendingPermitRead':True,'stores':1,'activeActivations':1,'ioStagedBytes':2,'ioBuffers':2,
                'perConnectionInputCap':1048576,'perStoreTransferCap':2097152,'kernelRetirementQualified':False}))
            result='quota|accepted='+str(n)+'|may-have-applied='+str(uncertain).lower()+'|n='+str(n)+'|close='+close+'|fresh=1'
        else:
            result=('write' if mode==0 else 'copy')+'|n='+str(n)+'|close=closed|fresh=1'
        values.append(('CASE',{'case':label,'mode':mode,'result':result,'n':n,'acceptedPrefix':n if mode==2 else None,
            'mayHaveApplied':uncertain if mode==2 else None,'close':close if mode==2 else 'closed','fresh':1,
            'outboundRequests':1,'reportedEffectCount':0,'cpuFuel':123,'peakMemoryBytes':4000000,
            'kernelRetirementQualified':False,'normalProviderInstalled':False}))
        values.append(('PEER',{'case':label,'peer':{'bytes':n,'sha256':progress.pattern_digest(n),'eof':True,'exactOriginalPattern':True}}))
        values.append(('OWNER',{'case':label,'stores':0,'instances':0,'streamOwners':0,'ioOwners':0,'kernelRetirementQualified':False}))
    values.append(('COMPLETE',{'cases':4,'contacts':4,'cleanLogicalProviderStop':True,'kernelRetirementQualified':False,
        'normalProviderInstalled':False,'wholeGoNetworkingQualified':False}))
    return values


def wire(values):
    return ('\n'.join('GO_WRITE_PROGRESS_'+kind+' '+json.dumps(value) for kind,value in values)+'\n'+
        'test '+progress.CASE+' ... ok\n'+'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;\n').encode()


class GoWriteProgressReader(unittest.TestCase):
    def test_variable_real_prefix_and_uncertainty_close_outcome_are_preserved(self):
        for uncertainty,close in [(False,'closed'),(True,'exhausted')]:
            selected=progress.outcomes(wire(records(uncertainty,close)))
            self.assertEqual(selected['cases'][2]['n'],24577)
            self.assertIs(selected['cases'][2]['mayHaveApplied'],uncertainty)
            self.assertEqual(selected['cases'][2]['close'],close)
            self.assertFalse(selected['completion']['kernelRetirementQualified'])
            self.assertFalse(selected['completion']['normalProviderInstalled'])

    def test_credit_peer_and_retirement_mismatches_cannot_qualify(self):
        changes=[('QUOTA','inputBudgetBytes',1048575),('QUOTA','acceptedWriteBytes',24576),
            ('QUOTA','liveConnection',False),('QUOTA','pendingPermitRead',False),
            ('QUOTA','inputBudgetBytes',1048576.0),('OWNER','streamOwners',1),
            ('CASE','n',True),('CASE','cpuFuel',0),('CASE','normalProviderInstalled',True)]
        for kind,key,value in changes:
            values=records();row=next(row for category,row in values if category==kind);row[key]=value
            with self.subTest(kind=kind,key=key,value=value),self.assertRaises(ValueError):progress.outcomes(wire(values))
        for key,value in [('bytes',24576),('sha256','sha256:'+'0'*64),('eof',False)]:
            values=records();row=[row for kind,row in values if kind=='PEER'][2];row['peer'][key]=value
            with self.subTest(peer=key),self.assertRaises(ValueError):progress.outcomes(wire(values))
        values=records();row=[row for kind,row in values if kind=='CASE'][2];row['acceptedPrefix']=24576
        with self.assertRaises(ValueError):progress.outcomes(wire(values))

    def test_order_duplicates_unknown_scope_and_ignored_native_case_are_refused(self):
        values=records();values[6],values[7]=values[7],values[6]
        with self.assertRaisesRegex(ValueError,'order'):progress.outcomes(wire(values))
        for values in [records()[:-1],records()+[('UNKNOWN',{})],records()+[records()[0]]]:
            with self.assertRaises(ValueError):progress.outcomes(wire(values))
        raw=wire(records()).replace(b'"inputBudgetBytes": 1048576',b'"inputBudgetBytes": 1048576,"inputBudgetBytes": 1048576')
        with self.assertRaisesRegex(ValueError,'duplicate'):progress.outcomes(raw)
        for raw in [wire(records()).replace(b'0 ignored',b'1 ignored'),b'x'*(1024*1024+1),'not bytes']:
            with self.assertRaises(ValueError):progress.outcomes(raw)

    def test_declared_inputs_extend_original_source_guard_without_running_a_compiler(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            names=('tools/ci/suites.d/go-write-progress-runtime.json','.github/workflows/go-write-progress-runtime.yml')
            for name in names:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'original')
            original={'original':{'digest':'sha256:'+'0'*64,'size':1}}
            with mock.patch.object(progress,'original_source_inputs',return_value=original):
                before=progress.source_inputs(root)
                (root/names[0]).write_bytes(b'changed')
                after=progress.source_inputs(root)
            self.assertNotEqual(before[names[0]],after[names[0]])
            self.assertEqual(before['original'],after['original'])
            self.assertEqual(before[names[1]],after[names[1]])


if __name__=='__main__':unittest.main()
