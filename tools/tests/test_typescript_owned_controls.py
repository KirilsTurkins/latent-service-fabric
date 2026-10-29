"""Evidence/deadline refusals only; no native engine or SDK build is run here."""
import os
import unittest
from unittest.mock import patch

from tools.typescript_guest import owned_result_controls as controls


class TypeScriptOwnedControlsTests(unittest.TestCase):
    def test_exact_source_inventory_rejects_skips_missing_and_extra_cases(self):
        good={'testsRun':controls.SOURCE_CASES,'skipped':0,'failures':0,'errors':0}
        controls.source_controls(good)
        for key,value in [('testsRun',28),('testsRun',30),('testsRun',31),('testsRun',33),('skipped',1),('errors',1),('failures',1),('testsRun',True)]:
            with self.assertRaises(ValueError):controls.source_controls(dict(good,**{key:value}))
        with self.assertRaises(ValueError):controls.source_controls(dict(good,extra=0))

    def test_actual_rust_source_inventory_requires_all_thirteen_successes(self):
        import re
        names=[]
        for module,file in [('lsf_async','async_import_descriptor.rs'),('lsf_async_splice','async_import_splice.rs')]:
            raw=(controls.ROOT/'sdk/typescript-guest/activation'/file).read_text()
            names += [module+'::tests::'+name for name in re.findall(r'#\[test\]\s+fn ([a-zA-Z0-9_]+)\(',raw)]
        # Keep this original control identity; all original17 plus the new2
        # compiled source cases must now appear, with no skips/duplicates.
        self.assertEqual(len(names),19)
        log=('\n'.join('test '+name+' ... ok' for name in names)+'\ntest result: ok. 19 passed; 0 failed; 0 ignored;\n').encode()
        self.assertEqual(set(controls.rust_cases(log)),set(names))
        for changed in (log.replace(b'... ok',b'... ignored',1),log+('test '+names[0]+' ... ok\n').encode(),
                        log.replace(b'0 ignored',b'1 ignored')):
            with self.assertRaises(ValueError):controls.rust_cases(changed)

    def test_emitted_core_inventory_refuses_missing_extra_or_changed_contract(self):
        import json
        from pathlib import Path
        import tempfile
        # Metadata parser specimens only. These empty modules do not contain a
        # disposer and cannot pass the separate actual Wasmtime control runner.
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)/'emitted'
            with self.assertRaisesRegex(ValueError,'emission-required'):
                controls.emitted_backing_controls(directory)
            directory.mkdir();rows=[]
            for which,name in enumerate(controls.BACKING_CORE_CASES):
                file=f'{which:02}-{name}.wasm'
                (directory/file).write_bytes(b'\0asm\1\0\0\0')
                rows.append(dict(case=name,file=file,bytes=8,argument=32,
                    expectedReturn=None if which==7 else int(which in (4,5)),expectedTrap=which==7,
                    expectedDoubleFreeReturns=0,allocatorEvidence=False))
            manifest=directory/'manifest.json'
            manifest.write_text(json.dumps(rows))
            record=controls.emitted_backing_controls(directory)
            self.assertEqual(len(record['modules']),8)
            self.assertFalse(record['executed']);self.assertFalse(record['allocatorEvidence'])
            for key,value in [('case','unknown'),('file','../escape.wasm'),('expectedReturn',False),
                              ('allocatorEvidence',True),('bytes',9)]:
                changed=[dict(row) for row in rows];changed[0][key]=value
                manifest.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):controls.emitted_backing_controls(directory)
            manifest.write_text(json.dumps(rows))
            (directory/'unexpected.wasm').write_bytes(b'\0asm\1\0\0\0')
            with self.assertRaisesRegex(ValueError,'extra-products'):
                controls.emitted_backing_controls(directory)

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

    def test_partial_own_exact_rows_and_names_cannot_bless_refund_or_cross_profile(self):
        rows=[dict(case=case,status=0,retainedOwners=1,canonicalDrops=(5,0,0,1)[index],
                   sidecarBytes=384,planBytes=40,slotBytes=64,hostcallInGC=False)
              for index,case in enumerate(controls.PARTIAL_NATIVE_CASES)]
        self.assertEqual(controls.partial_native_rows(rows),dict(sidecarBytes=384,planBytes=40,slotBytes=64))
        for changed in [rows[:-1],rows+[rows[0]],list(reversed(rows)),[rows[0]]*4]:
            with self.assertRaises(ValueError):controls.partial_native_rows(changed)
        for key,value in [('status',True),('retainedOwners',0),('retainedOwners',2),
                          ('canonicalDrops',4),('canonicalDrops',True),('sidecarBytes',False),
                          ('hostcallInGC',True),('case','ordinary-own-source-case'),('extra',0)]:
            changed=[dict(row) for row in rows];changed[0][key]=value
            with self.assertRaises(ValueError):controls.partial_native_rows(changed)
        changed=[dict(row) for row in rows];changed[1]['slotBytes']=65
        with self.assertRaises(ValueError):controls.partial_native_rows(changed)
        for case in controls.PARTIAL_RUST_CASES:
            raw=('test '+case+' ... ok\ntest result: ok. 1 passed; 0 failed; 0 ignored; 18 filtered out;\n').encode()
            self.assertEqual(controls.partial_rust_case(raw,case),case)
            for changed in [raw.replace(b'... ok',b'... ignored'),raw+raw,
                            raw.replace(b'0 ignored',b'1 ignored')]:
                with self.assertRaises(ValueError):controls.partial_rust_case(changed,case)
        with self.assertRaises(ValueError):controls.partial_rust_case(b'',controls.PARTIAL_RUST_CASES[0])
        # Authenticate the actual current source and full historical inverse;
        # no producer receipt, current ROOT file or unrelated recipe is changed.
        name='tools/typescript_guest/activation_engine.py'
        raw=(controls.ROOT/name).read_bytes()
        old={'bytes':14962,'sha256':'sha256:5e576fd983990296b18a6ac743a1bca42d22c6a521f89a14c1e2221177a9b7a5'}
        proof=controls.native_build.library_recipe_equivalence(name,raw,old)
        self.assertEqual(proof['current'],controls.native_build.file_bytes(raw))
        self.assertEqual(proof['inverseIdentity'],old)
        self.assertFalse(proof['historicalReceiptReissued'])
        before=proof['inverse']['before'].encode();after=proof['inverse']['after'].encode()
        historical=raw.replace(after,before,1)
        self.assertEqual(controls.native_build.file_bytes(historical),old)
        self.assertIsNone(controls.native_build.library_recipe_equivalence(name,historical,old))
        self.assertIsNone(controls.native_build.library_recipe_equivalence(name,raw,proof['current']))
        for path,source,identity in [
                ('tools/typescript_guest/promise_library.py',raw,old),
                (name,raw+b' ',old),(name,raw.replace(after,before),proof['current']),
                (name,raw.replace(after,after+after),old),
                (name,raw.replace(b'FIREFOX_COMMIT',b'FIREFOX_COMMIX',1),old),
                (name,raw,dict(old,bytes=14963)),
                (name,raw,dict(old,sha256='sha256:'+'0'*64))]:
            with self.assertRaisesRegex(ValueError,'typescript-native-library-recipe-drift'):
                controls.native_build.library_recipe_equivalence(path,source,identity)
        self.assertIn('tools/typescript_guest/native_build.py',controls.PARTIAL_INPUTS)

