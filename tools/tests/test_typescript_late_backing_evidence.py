"""Observation-parser specimens only; these rows are never runtime evidence."""
import copy
import json
import unittest
from tools.typescript_guest import late_backing_evidence as evidence


def channel(rows,compile_row=True):
    prefix='diagnostic compiler optimization: none\n'
    if compile_row:prefix+='diagnostic compile millis: 1\n'
    return (prefix+'\n'.join(json.dumps(row) for row in rows)+'\n').encode()


class LateBackingEvidenceTests(unittest.TestCase):
    def backing(self):
        rows=[]
        for which,count in enumerate((0,0,5,1,0,3,1,None)):
            refused=which==7;allocation=int(which in (5,7))
            rows.append(dict(schemaVersion='latent.typescript.late-backing-case.v1',case=which,status='passed',
                ordinaryDeliveryOnly=which in (0,4),backingFreeReturnsBeforeStoreDrop=count,
                postTrapFreeCountObserved=False,parentFreeAfterTrapUnreachableByEmittedOrder=refused,
                destructorRefused=refused,allocations=allocation,destructorCalls=allocation,
                payloadDropsBeforeStoreDrop=0 if refused else allocation,payloadDropsAfterStoreDrop=allocation,
                futureStarts=1,futureDrops=1,observedImports=1,matchedImportNativeOwnersBeforeStoreDrop=2 if refused else 0,
                matchedImportResultOwnersBeforeStoreDrop=int(refused),runtimeOwnersBeforeStoreDrop=[0,0,0,0,0,int(refused),2],
                peakLinearMemoryBytes=65536,fuel=100,allocatorBoundaryOnly=True,osOrLinearMemoryReturnQualified=False,
                deliveredStorageCleanupQualified=False,parametersCleanupQualified=False,partialLowerCleanupQualified=False,
                wholeCostQualification=False,physicalProviderQualified=False,signedExecution=False))
        return rows

    def test_real_backing_parser_requires_before_store_counts_and_truthful_refusal(self):
        rows=self.backing()
        self.assertEqual(evidence.backing_rows(channel(rows)),rows)
        for which,key,value in [(2,'backingFreeReturnsBeforeStoreDrop',4),(0,'backingFreeReturnsBeforeStoreDrop',False),
                (2,'matchedImportNativeOwnersBeforeStoreDrop',1),(2,'futureStarts',0),
                (7,'backingFreeReturnsBeforeStoreDrop',0),(7,'postTrapFreeCountObserved',True),
                (7,'matchedImportResultOwnersBeforeStoreDrop',0),(4,'deliveredStorageCleanupQualified',True),
                (1,'osOrLinearMemoryReturnQualified',True),(1,'partialLowerCleanupQualified',True)]:
            changed=copy.deepcopy(rows);changed[which][key]=value
            with self.assertRaises(ValueError):evidence.backing_rows(channel(changed))

    def test_core_parser_binds_loaded_hashes_and_keeps_counter_double_scope(self):
        modules=[dict(case=name,bytes=8,sha256=f'sha256:{index:064x}')
                 for index,name in enumerate(evidence.BACKING_CORE_CASES)]
        emitted=dict(executed=False,allocatorEvidence=False,manifest={'sha256':'sha256:'+'a'*64},modules=modules)
        rows=[dict(schemaVersion='latent.typescript.backing-core-case.v1',case=entry['case'],index=which,status='passed',
            moduleBytes=8,moduleSha256=entry['sha256'].removeprefix('sha256:'),manifestSha256='a'*64,
            returned=None if which==7 else int(which in (4,5)),trapped=which==7,doubleFreeReturns=0,
            originalDropCalls=int(which==7),fuel=100,allocatorEvidence=False,guestRootReopened=False)
            for which,entry in enumerate(modules)]
        self.assertEqual(evidence.core_rows(channel(rows,False),emitted),rows)
        for which,key,value in [(0,'moduleSha256','b'*64),(0,'manifestSha256','b'*64),
                (0,'doubleFreeReturns',1),(4,'returned',False),(7,'returned',0),
                (7,'originalDropCalls',0),(7,'guestRootReopened',True),(0,'allocatorEvidence',True)]:
            changed=copy.deepcopy(rows);changed[which][key]=value
            with self.assertRaises(ValueError):evidence.core_rows(channel(changed,False),emitted)

    def test_actual_raw_channel_refuses_missing_duplicate_or_foreign_rows(self):
        rows=self.backing()
        for changed in (rows[:-1],rows+rows[:1],rows[::-1]):
            with self.assertRaises(ValueError):evidence.backing_rows(channel(changed))
        for raw in (channel(rows).replace(b'optimization: none',b'optimization: speed'),
                    channel(rows)+b'unexpected diagnostic\n',
                    channel(rows).replace(b'late-backing-case',b'unrecognized-case',1)):
            with self.assertRaises(ValueError):evidence.backing_rows(raw)


if __name__=='__main__':unittest.main()
