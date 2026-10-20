"""Finite wait observations require real pending work and exact public results."""
import copy
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tools import dotnet_finite_wait_fixture as fixture, dotnet_finite_wait_node as node
from tools import qualify_dotnet_finite_waits as qualification
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import digest, write_json
from tools.tests.test_dotnet_finite_task_wait import FINITE
from tools.tests import test_dotnet_task_wait as controls


class FiniteWaitProgramme(unittest.TestCase):
    def test_current_native_source_requires_full_identity_of_the_authenticated_producer(self):
        expected={'sha256':'sha256:'+'a'*64,'files':3315,'bytes':26086384}
        with patch.object(qualification,'git_source_identity',return_value=expected) as original:
            for observed in (expected,{**expected,'files':3316},{**expected,'sha256':'sha256:'+'b'*64}):
                with self.subTest(observed=observed),patch.object(qualification,'source_identity',return_value=observed):
                    if observed==expected:self.assertEqual(qualification.current_native_source(),expected)
                    else:
                        with self.assertRaisesRegex(WorkflowError,'must-match-producer'):qualification.current_native_source()
            original.assert_called_with(qualification.products.SOURCE)

    def row(self,mode):
        revision={'releaseDigest':'sha256:'+'a'*64}
        usage={k:0 for k in ('outboundRequests','childCalls','effectCount','logBytes','stateReadBytes',
            'stateWriteBytes','blobReadBytes','blobWriteBytes')};usage.update(cpuFuel=100,peakMemoryBytes=4096)
        row={'processReaped':True,'exitCode':0,'decoded':[{'ok':fixture.expected(mode)}],
            'response':{'outcomeKnown':True,'data':{'consumption':usage,'resolvedRevision':revision}}}
        return row,revision

    def test_standard_values_reject_changed_task_results_effects_unknown_outcomes_and_unreaped_calls(self):
        row,revision=self.row('timeout-false-then-fresh');component=revision['releaseDigest']
        node.checked(row,component,revision,'timeout-false-then-fresh')
        for change in ('result','effects','unknown','unreaped','component'):
            r=copy.deepcopy(row);selected=component
            if change=='result':r['decoded']=[{'ok':'true'}]
            elif change=='effects':r['response']['data']['consumption']['outboundRequests']=1
            elif change=='unknown':r['response']['outcomeKnown']=False
            elif change=='unreaped':r['processReaped']=False
            else:selected='sha256:'+'b'*64
            with self.subTest(change=change),self.assertRaises(WorkflowError):node.checked(r,selected,revision,'timeout-false-then-fresh')

    def test_root_cancellation_and_deadline_can_never_count_as_successful_task_completion(self):
        for mode,code in (('root-cancel','cancelled'),('root-deadline','deadline-exceeded')):
            r,revision=self.row('infinite-join-regression');r['exitCode']=4;r['response']['error']={'code':code}
            node.checked(r,revision['releaseDigest'],revision,mode)
            for changed in ('success','wrong-terminal'):
                candidate=copy.deepcopy(r)
                if changed=='success':candidate['exitCode']=0
                else:candidate['response']['error']['code']='guest-trap'
                with self.subTest(mode=mode,changed=changed),self.assertRaises(WorkflowError):
                    node.checked(candidate,revision['releaseDigest'],revision,mode)

    def test_pending_observer_is_fresh_and_uses_one_actual_deployment_population(self):
        original=time.monotonic()+100
        client=SimpleNamespace(deadline=original,node=SimpleNamespace(drain=lambda:None,buffers=[b'',b'old-current']),
            call=lambda *args,**kw: {'category':'success','data':{'page':{'nextPageToken':None}}} if args[0]=='audit'
                else {'data':{'inventory':{}}} if args[0]=='node' else {'data':{}})
        active=SimpleNamespace(owner=SimpleNamespace(exited=lambda:False),authoring_activation='node-stop-pending',
            authoring_started_unix_millis=1)
        received=[]
        def witness(*args):received.append(args[-1]);return {'positive':True} if args[-1]==b'current' else None
        with tempfile.TemporaryDirectory() as temporary,patch.object(node.witness,'pending_witness',side_effect=witness),\
                patch.object(node,'sample',return_value={}) as sample,patch.object(node.time,'sleep'):
            with self.assertRaisesRegex(RuntimeError,'pending-witness-attempts'):
                node.pending(client,active,None,{'name':'owned'},Path(temporary),'stale',11)
            actual=node.pending(client,active,None,{'name':'owned'},Path(temporary),'current',4)
            self.assertTrue(actual['witness']['positive']);self.assertEqual(received[-1],b'current')
            self.assertEqual(sample.call_args.args[-1],1);self.assertTrue(sample.call_args.kwargs['active'])
            self.assertEqual(client.deadline,original)

    def build(self,root):
        control=controls.TaskWaitPortTests();control.setUp();self.addCleanup(control.doCleanups)
        derived={'name':'task-wait-derived-corelib','digest':'sha256:'+'b'*64,'size':1}
        original={'name':'original','digest':qualification.task_wait.SOURCE,'size':5694976}
        final='sha256:'+'c'*64
        port={**control.receipt,**FINITE,'profile':qualification.task_wait.PROFILE,
            'frameworkInput':original,'derived':derived,'outputDigest':derived['digest'],
            'tool':{},'sourceCaptureDigest':'sha256:'+'d'*64,'targetsDigest':'sha256:'+'e'*64,
            'selection':{'requiredDeclarations':sorted(qualification.DECLARATIONS),'asyncExportBridge':{}},
            'nativeAotReferenceBinding':{'responseFiles':[{}],'finalCoreLibDerivation':{
                'intermediateDigest':derived['digest'],'selectedDigest':final}}}
        docs={'source-inputs.json':{},'recipe-inputs.json':{},'package-inputs.json':{},
            'runtime-profile.json':{'profile':'runtime','declaredImports':list(qualification.DECLARATIONS)},
            'task-wait-port.json':port,'closed-filesystem-port.json':{'derived':{'digest':final},
                'nativeAotReferenceBinding':{'selectedCoreLibDigest':final}},
            'noncrypto-entropy-port.json':{},'managed-entropy-port.json':{},
            'compiler-patches.json':{'formatVersion':1,'patches':[{'name':qualification.task_wait.PROFILE,
                'selected':derived,'original':original,'selection':dict(FINITE)}]}}
        (root/'component.wasm').write_bytes(b'component')
        for name,value in docs.items():write_json(root/name,value)
        observed={'componentDigest':digest(b'component'),'componentSize':9,'parameters':{
            'compiler':'native-aot-llvm','bindings':'wit-bindgen-csharp','language':'csharp',
            'target':'wasi-wasm','runtime':'native-aot','locked':True,'ambientWasi':False},'materials':[]}
        bindings=(('build-recipe','recipe-inputs.json'),('package-inputs','package-inputs.json'),
            ('runtime-profile','runtime-profile.json'),('dotnet-task-wait-port','task-wait-port.json'),
            ('dotnet-closed-filesystem-port','closed-filesystem-port.json'),('standard-rng-managed-port','managed-entropy-port.json'))
        def refresh():
            observed['materials']=[{'name':name,'digest':digest((root/file).read_bytes()),'size':(root/file).stat().st_size}
                for name,file in bindings]
            (root/'build-observation.json').write_bytes((json.dumps(observed)+'\n').encode())
            marker={'packageAssembled':True,'componentDigest':digest(b'component'),
                'observationDigest':digest((root/'build-observation.json').read_bytes()),
                'sourceDigest':digest((root/'source-inputs.json').read_bytes())}
            (root/'BUILD-COMPLETE.json').write_bytes((json.dumps(marker)+'\n').encode())
        refresh();return docs,refresh

    def test_rehashed_old_infinite_receipt_and_changed_final_corelib_still_refuse(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(qualification,'package_identity',return_value={}):
            root=Path(temporary);docs,refresh=self.build(root)
            self.assertEqual(qualification.build_evidence(root)['component']['sha256'],digest(b'component'))
            for change in ('old-port','token','final-corelib','implicit-authority','compiler-patch'):
                selected=copy.deepcopy(docs)
                if change=='old-port':selected['task-wait-port.json']['finiteAndCancellableWaits']='original-unsupported'
                elif change=='token':selected['task-wait-port.json']['waitCancellation']='replacement-token'
                elif change=='final-corelib':selected['closed-filesystem-port.json']['derived']['digest']='sha256:'+'f'*64
                elif change=='implicit-authority':selected['runtime-profile.json']['declaredImports'].pop()
                else:selected['compiler-patches.json']['patches'][0]['selection']['generatedHelperCount']=9
                for name,value in selected.items():(root/name).write_bytes((json.dumps(value)+'\n').encode())
                refresh()
                with self.subTest(change=change),self.assertRaises((WorkflowError,ValueError)):qualification.build_evidence(root)

    def test_outside_library_calls_ordinary_task_wait_without_candidate_or_application_pump(self):
        text=fixture.LIBRARY_SOURCE
        self.assertIn('=> task.Wait(milliseconds,token);',text)
        self.assertNotIn('WasiEventLoop',text);self.assertNotIn('LsfWait',text)
        self.assertEqual(len(fixture.CASES),14);self.assertNotIn('pending-root',fixture.CASES)
        for mode in fixture.CASES:self.assertIn('case "'+mode+'"',text)
        self.assertIn('Wait(pending.Task, 60000, CancellationToken.None)',text)


if __name__=='__main__':unittest.main()
