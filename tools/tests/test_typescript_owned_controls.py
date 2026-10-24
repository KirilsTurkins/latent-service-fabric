"""Evidence/deadline refusals only; no native engine or SDK build is run here."""
import os
import unittest
from unittest.mock import patch

from tools.typescript_guest import owned_result_controls as controls


class TypeScriptOwnedControlsTests(unittest.TestCase):
    def test_exact_source_inventory_rejects_skips_missing_and_extra_cases(self):
        good={'testsRun':controls.SOURCE_CASES,'skipped':0,'failures':0,'errors':0}
        controls.source_controls(good)
        for key,value in [('testsRun',28),('testsRun',30),('skipped',1),('errors',1),('failures',1),('testsRun',True)]:
            with self.assertRaises(ValueError):controls.source_controls(dict(good,**{key:value}))
        with self.assertRaises(ValueError):controls.source_controls(dict(good,extra=0))

    def test_actual_rust_source_inventory_requires_all_thirteen_successes(self):
        import re
        names=[]
        for module,file in [('lsf_async','async_import_descriptor.rs'),('lsf_async_splice','async_import_splice.rs')]:
            raw=(controls.ROOT/'sdk/typescript-guest/activation'/file).read_text()
            names += [module+'::tests::'+name for name in re.findall(r'#\[test\]\s+fn ([a-zA-Z0-9_]+)\(',raw)]
        log=('\n'.join('test '+name+' ... ok' for name in names)+'\ntest result: ok. 13 passed; 0 failed; 0 ignored;\n').encode()
        self.assertEqual(set(controls.rust_cases(log)),set(names))
        for changed in (log.replace(b'... ok',b'... ignored',1),log+('test '+names[0]+' ... ok\n').encode(),
                        log.replace(b'0 ignored',b'1 ignored')):
            with self.assertRaises(ValueError):controls.rust_cases(changed)

    def test_monotonic_deadline_clips_every_stage_and_refuses_late_success(self):
        with patch.object(controls.time,'monotonic',side_effect=[100,110,149,150,151]):
            deadline=controls.Deadline(50)
            self.assertEqual(deadline.remaining(900),40)
            self.assertEqual(deadline.remaining(120),1)
            with self.assertRaisesRegex(ValueError,'aggregate-deadline'):deadline.finish()
            with self.assertRaisesRegex(ValueError,'aggregate-deadline'):deadline.remaining(20)
        with patch.dict(os.environ,LSF_OWN_CAMPAIGN_STARTED_NS='100000000000'), \
             patch.object(controls.time,'time_ns',return_value=130000000000), \
             patch.object(controls.time,'monotonic',return_value=400):
            deadline,elapsed=controls.Deadline.workflow()
            self.assertEqual(elapsed,30)
            self.assertEqual(deadline.end,5770)
        with patch.dict(os.environ,LSF_OWN_CAMPAIGN_STARTED_NS='1'), \
             patch.object(controls.time,'time_ns',return_value=5400_000_000_001):
            with self.assertRaisesRegex(ValueError,'setup-deadline'):controls.Deadline.workflow()

    def test_native_evidence_requires_new_record_abi_and_real_cancel_counters(self):
        case=controls.NATIVE_CASES[-1]
        good=dict(case=case,status=0,hostcallInGC=False,dropOrderValid=True,owners=0,expectedQuarantine=False,
                  managerBytes=96,baselineManagerBytes=96,recordBytes=160,baselineRecordBytes=144,
                  recordAlignment=8,baselineRecordAlignment=8,observerBytes=32,subtaskDrops=2,
                  cancelRequests=0,exactAckRefusals=0,importStarts=2,importLifts=1,importFinishes=2,
                  importDisposals=1,nativeAdmissions=2,nativeAcknowledgements=2)
        controls.native_case(good,case)
        for key,value in [('recordBytes',144),('managerBytes',104),('importDisposals',0),('importLifts',0),
                          ('subtaskDrops',1),('owners',1),('status',False),('nativeAcknowledgements',True)]:
            with self.assertRaises(ValueError):controls.native_case(dict(good,**{key:value}),case)
        with self.assertRaises(ValueError):controls.native_case(good,'unknown-case')

    def test_native_refusal_evidence_cannot_turn_retained_owners_into_refund(self):
        case=controls.borrow_controls.REFUSAL_CASES[-1]
        row=dict(case=case,status=0,hostcallInGC=False,dropOrderValid=True,owners=1,expectedQuarantine=True,
                 managerBytes=96,baselineManagerBytes=96,recordBytes=160,baselineRecordBytes=144,
                 recordAlignment=8,baselineRecordAlignment=8,observerBytes=32,subtaskDrops=1,cancelRequests=1,
                 exactAckRefusals=1,recordDestroyed=True,observerDestroyed=True,importStarts=1,importLifts=0,
                 importFinishes=0,importDisposals=1,nativeAdmissions=1,nativeAcknowledgements=0)
        controls.native_case(row,case)
        for key,value in [('owners',0),('expectedQuarantine',False),('exactAckRefusals',0),('dropOrderValid',False)]:
            with self.assertRaises(ValueError):controls.native_case(dict(row,**{key:value}),case)
        immediate=controls.LIFECYCLE_CASES[0]
        reference=dict(case=immediate,status=0,subtaskDrops=0,joined=0,resultOwners=0,nativeOwners=0,tasks=0,idleWaits=0)
        controls.lifecycle_case(reference,immediate)
        for key,value in [('subtaskDrops',1),('tasks',1),('resultOwners',1),('nativeOwners',1),('status',False)]:
            with self.assertRaises(ValueError):controls.lifecycle_case(dict(reference,**{key:value}),immediate)

    def test_workflow_requires_same_source_and_owning_workflow_head(self):
        commit='a'*40;ref='refs/heads/feat/typescript-owned-result-disposal-compose-20261024'
        env=dict(GITHUB_REPOSITORY='KirilsTurkins/latent-service-fabric',GITHUB_SHA=commit,GITHUB_WORKFLOW_SHA=commit,
                 GITHUB_REF=ref,GITHUB_EVENT_NAME='push',GITHUB_RUN_ID='123',GITHUB_RUN_ATTEMPT='1',
                 GITHUB_WORKFLOW_REF='KirilsTurkins/latent-service-fabric/.github/workflows/typescript-owned-results.yml@'+ref)
        with patch.dict(os.environ,env,clear=True):self.assertEqual(controls.workflow_origin(commit),env)
        for key,value in [('GITHUB_WORKFLOW_SHA','b'*40),('GITHUB_SHA','b'*40),('GITHUB_RUN_ID','0'),
                          ('GITHUB_EVENT_NAME','pull_request'),('GITHUB_REPOSITORY','other/repo')]:
            with patch.dict(os.environ,dict(env,**{key:value}),clear=True),self.assertRaises(ValueError):
                controls.workflow_origin(commit)
