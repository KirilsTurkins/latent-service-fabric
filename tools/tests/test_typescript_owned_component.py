"""Input/evidence refusals only; synthetic rows are never engine observations."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.typescript_guest import owned_component_controls as controls,owned_result_component as component


class TypeScriptOwnedComponentTests(unittest.TestCase):
    def test_evidence_parser_refuses_owner_leaks_zero_start_and_false_scope(self):
        # Explicit parser specimens only; this is not a runtime state model.
        # Concrete11-case expectations come from the reviewed fixture contract.
        specimens=[]
        allocation=[1,2,2,2,1,0,2,0,1,2,0];imports=[1,2,2,2,2,1,2,1,1,2,1]
        for case in range(11):
            refusal=case==8;n=allocation[case]
            specimens.append(dict(schemaVersion='latent.typescript.canonical-own-case.v1',case=case,status='passed',
                allocations=n,destructorCalls=n,connectionDestructorCalls=0 if case==3 else (1 if case==9 else n),
                chunkDestructorCalls=2 if case==3 else int(case==9),payloadDropsBeforeStoreDrop=0 if refusal else n,
                payloadDropsAfterStoreDrop=n,liveBeforeStoreDrop=refusal,payloadCapacity=1,
                sameStorePayloadReuse=case in (1,2,3,6,9),canonicalResourceDropActual=n>0,canonicalTableIndexObserved=False,
                futureStarts=imports[case],futureDrops=imports[case],pendingProviderStarts=int(case==7),
                matchedImportNativeOwnersBeforeStoreDrop=2 if refusal else 0,
                matchedImportResultOwnersBeforeStoreDrop=int(refusal),observedImports=imports[case],
                runtimeOwnersBeforeStoreDrop=[0,0,0,0,0,1,2] if refusal else [0,0,0,0,0,0,4],
                peakLinearMemoryBytes=65536,fuel=100,nestedBackingStorageQualified=False,
                physicalProviderQualified=False,signedExecution=False))
        def wire(rows):return ('diagnostic compiler optimization: none\ndiagnostic compile millis: 10\n'+
                                  '\n'.join(json.dumps(row) for row in rows)+'\n').encode()
        self.assertEqual(controls.rows(wire(specimens)),specimens)
        for which,key,value in [(7,'futureStarts',0),(7,'futureDrops',0),(7,'pendingProviderStarts',0),
                                 (1,'matchedImportNativeOwnersBeforeStoreDrop',1),
                                 (1,'matchedImportResultOwnersBeforeStoreDrop',1),(4,'sameStorePayloadReuse',True),
                                 (5,'canonicalResourceDropActual',True),(8,'liveBeforeStoreDrop',False),
                                 (9,'chunkDestructorCalls',0),(0,'canonicalTableIndexObserved',True)]:
            changed=copy.deepcopy(specimens);changed[which][key]=value
            with self.assertRaises(ValueError):controls.rows(wire(changed))
        with self.assertRaises(ValueError):controls.rows(wire(specimens[:-1]))

    def test_failed_or_promoted_input_cannot_reach_normal_compiler_validation(self):
        head='9d07a6dfa3ebb77aa75eb1b5899cb9360e26728d';ref='refs/heads/fixed'
        header=dict(schemaVersion='latent.typescript.owned-result-prerequisites.v1',
            scope='fresh-normal-compiler-engine-unit-native-ABI-prerequisites',status='passed',sourceCommit=head,
            freshSplicerBuildCount=1,freshEngineBuildCount=1,machBuildCount=0,
            canonicalOwnComponentExecuted=False,tableReuseQualified=False,signedExecution=False,
            physicalProviderQualified=False,wholeCostQualification=False,
            workflowOrigin=dict(GITHUB_REPOSITORY='KirilsTurkins/latent-service-fabric',GITHUB_SHA=head,
                GITHUB_WORKFLOW_SHA=head,GITHUB_EVENT_NAME='push',GITHUB_REF=ref,
                GITHUB_WORKFLOW_REF='KirilsTurkins/latent-service-fabric/.github/workflows/typescript-owned-results.yml@'+ref))
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(component.native_build,'source_splicer',side_effect=AssertionError('must refuse before compiler spending')):
            root=Path(temporary)
            for key,value in [('status','failed'),('sourceCommit','0'*40),('freshEngineBuildCount',True),
                             ('canonicalOwnComponentExecuted',True),('wholeCostQualification',True)]:
                (root/'OWN-RESULTS.json').write_text(json.dumps(dict(header,**{key:value})))
                with self.assertRaises(ValueError):component.select_products(root,head)
            (root/'OWN-RESULTS.json').write_text('[]')
            with self.assertRaises(ValueError):component.select_products(root,head)

    def test_setup_time_reduces_the_single_monotonic_nine_hundred_second_budget(self):
        with patch.dict(os.environ,LSF_OWN_COMPONENT_STARTED_NS='100000000000'), \
             patch.object(controls.time,'time_ns',return_value=160000000000), \
             patch.object(controls.time,'monotonic',return_value=50):
            deadline,setup=controls.setup_deadline()
            self.assertEqual(setup,60);self.assertEqual(deadline.end,890)
            self.assertEqual(deadline.remaining(600),600)
        with patch.dict(os.environ,LSF_OWN_COMPONENT_STARTED_NS='1'), \
             patch.object(controls.time,'time_ns',return_value=900_000_000_001):
            with self.assertRaisesRegex(ValueError,'aggregate-setup-deadline'):controls.setup_deadline()
