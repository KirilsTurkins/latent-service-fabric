"""Refuse false pending/retirement and compiler provenance observations."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

from tools import resource_runtime_node as runtime, typescript_resource_runtime_inputs as inputs
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_node import configure


class ResourceRuntimeBoundaries(unittest.TestCase):
    def test_real_normal_derived_world_preserves_original_export_component_and_namespace(self):
        from tools.qualify_typescript_resource_runtime import checked_release
        world='examples:lsf-typescript-activation/selected@1.0.0'
        release={'name':'my-greeting','service':'my-greeting','world':world,'componentDigest':'sha256:'+'a'*64}
        capsule={'metadata':{'name':'examples/my-greeting','tenant':'examples'},
            'component':{'world':world,'digest':release['componentDigest']},
            'exports':['examples:resource-runtime/api@1.0.0']}
        build={'component':{'sha256':release['componentDigest']}}
        self.assertEqual(checked_release(release,capsule,build),release)
        for change in ('source-world','foreign-namespace','changed-export','changed-component','foreign-service'):
            r,c,b=copy.deepcopy((release,capsule,build))
            if change=='source-world':r['world']='examples:resource-runtime/service@1.0.0'
            elif change=='foreign-namespace':r['world']=c['component']['world']='foreign:lsf-typescript-activation/selected@1.0.0'
            elif change=='changed-export':c['exports']=['examples:other/api@1.0.0']
            elif change=='changed-component':r['componentDigest']=c['component']['digest']='sha256:'+'b'*64
            else:r['service']='other'
            with self.subTest(change=change),self.assertRaises(WorkflowError):checked_release(r,c,b)

    @staticmethod
    def capsule():
        return {'execution':{'limits':{'memoryBytes':134217728}},
                'imports':[{'contract':name,'optional':False} for name in (*runtime.SCALARS,runtime.ACTIVATION)]}

    def test_configuration_retains_original_cell_budgets_and_explicit_per_tenant_aliases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);node=root/'node';node.mkdir();signed=root/'signed';signed.mkdir()
            (signed/'policy.json').write_bytes(b'{}\n')
            _path,settings=configure(node,signed,12345,language='typescript')
            before=copy.deepcopy(settings)
            selected=runtime.configure(settings,self.capsule())
            self.assertEqual(selected['workers'],before['workers'])
            self.assertEqual(selected['cells'],before['cells'])
            self.assertEqual(selected['providers']['http'],before['providers']['http'])
            self.assertEqual(len(selected['providers']['bindings']),9)
            self.assertEqual(selected['providers']['activationRuntime']['limits'],runtime.LIMITS)
            alias=selected['providers']['scalarAliases'][-1]
            self.assertEqual(alias,{'source':'activation','identity':{'id':'activation-foreign',
                'tenant':'foreign','service':'foreign-activation','epoch':1}})
            bindings=[b for b in selected['providers']['bindings'] if b['contract']==runtime.ACTIVATION]
            self.assertEqual([b['tenant'] for b in bindings],['examples','foreign'])
            self.assertTrue(all(b['consumerService']=='my-greeting' for b in bindings))
            self.assertNotIn('grants',selected['providers']['activationRuntime'])

    def test_activation_identity_keeps_the_native_installation_scope_distinct_from_clocks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);node=root/'node';node.mkdir();signed=root/'signed';signed.mkdir()
            (signed/'policy.json').write_bytes(b'{}\n')
            _path,settings=configure(node,signed,12345,language='typescript')
            runtime.configure(settings,self.capsule())
            providers=settings['providers'];activation=providers['activationRuntime']['identity']
            # The native installation rejects a shared tenant/service with clocks.
            for field in ('http','clockMonotonic','clockWall'):
                identity=providers[field]['identity']
                self.assertNotEqual((activation['tenant'],activation['service']),
                                    (identity['tenant'],identity['service']))
            self.assertEqual(activation['service'],'activation-host')
            self.assertEqual(providers['clockMonotonic']['identity']['service'],'runtime-host')
            self.assertEqual(providers['clockWall']['identity']['service'],'runtime-host')
            bindings=[b for b in providers['bindings'] if b['contract']==runtime.ACTIVATION]
            self.assertEqual([(b['tenant'],b['providerService']) for b in bindings],
                             [('examples','activation-host'),('foreign','foreign-activation')])
            self.assertEqual(providers['activationRuntime']['limits'],runtime.LIMITS)

    def test_unknown_optional_duplicate_or_undeclared_runtime_import_is_refused(self):
        for change in ('missing','optional','duplicate','foreign'):
            capsule=self.capsule()
            if change=='missing':capsule['imports'].pop()
            elif change=='optional':capsule['imports'][-1]['optional']=True
            elif change=='duplicate':capsule['imports'][-1]=capsule['imports'][0]
            else:capsule['imports'][-1]['contract']='outside:unknown/clock@1.0.0'
            with self.subTest(change=change),self.assertRaisesRegex(WorkflowError,'exact-declared-imports'):
                runtime.configure({},capsule)

    @staticmethod
    def witness():
        inventory={'topology':{'available':True,'complete':True,'entries':[
            {'name':name,'activeCount':'1'} for name in runtime.LIVE]}}
        usage={'tenantUsage':{'scope':'tenant','unavailable':[],'counters':{'calls':'1','sessions':'1'}},
               'nodeUsage':{'scope':'node','unavailable':[],'counters':{'broker_calls':'1'}}}
        identity={'activation':'node-stop-pending','rootActivation':'node-stop-pending','capability':runtime.ACTIVATION,
                  'providerProfile':'activation-owned-v1'}
        def row(sequence,kind,operation):
            selected={**identity,'operation':operation}
            if operation=='timer-start':selected['providerOutcome']='AUDIT_PROVIDER_OUTCOME_HOST_COMPLETED'
            return {'epoch':'a'*32,'sequence':str(sequence),'data':{'observation':{
                'kind':'PHASE2_AUDIT_EVENT_KIND_CAPABILITY_'+kind,
                'outcome':'AUDIT_OBSERVATION_OUTCOME_SUCCEEDED','identities':{'capability':selected}}}}
        pages=[{'category':'success','outcomeKnown':True,'data':{'page':{'nextPageToken':None},
            'coverage':{'droppedObservations':'0'},'records':[
                row(1,'PROVIDER_OUTCOME','timer-start'),row(2,'GRANT_ALLOWED','timer-next')]}}]
        return inventory,usage,pages

    @staticmethod
    def timer_records():
        return (runtime.timer_observer.PREFIX+b'|pending|start-accepted|1|2|0|1\n'+
                runtime.timer_observer.PREFIX+b'|pending|next-entered|2|2|1|1\n')

    def test_pending_requires_later_real_timer_wait_and_positive_physical_provider_owners(self):
        inventory,usage,pages=self.witness()
        proof=runtime.pending_witness(inventory,usage,pages,'node-stop-pending',self.timer_records())
        self.assertTrue(proof['retainedProviderCall'])
        self.assertEqual(proof['completedTimerStarts'],[1]);self.assertEqual(proof['laterTimerWaitAdmissions'],[2])
        for change in ('store-zero','call-zero','missing-start','missing-wait','wrong-root','earlier-wait'):
            i,u,p=copy.deepcopy((inventory,usage,pages));records=p[0]['data']['records']
            if change=='store-zero':i['topology']['entries'][2]['activeCount']='0'
            elif change=='call-zero':u['nodeUsage']['counters']['broker_calls']='0'
            elif change=='missing-start':records.pop(0)
            elif change=='missing-wait':records.pop()
            elif change=='wrong-root':
                for row in records:row['data']['observation']['identities']['capability']['activation']='other'
            else:records.reverse();records[0]['sequence']='1';records[1]['sequence']='2'
            with self.subTest(change=change):self.assertIsNone(runtime.pending_witness(i,u,p,'node-stop-pending',self.timer_records()))

    def test_completed_or_dispatched_audit_never_substitutes_for_actual_accepted_timer_wait(self):
        i,u,p=self.witness()
        for raw in (b'',runtime.timer_observer.PREFIX+b'|pending|start-accepted|1|2|0|1\n'):
            with self.subTest(raw=raw):
                self.assertIsNone(runtime.pending_witness(i,u,p,'node-stop-pending',raw))
        for raw in (self.timer_records().replace(b'next-entered',b'host-dispatched'),
                    self.timer_records().replace(b'|2|2|1|1',b'|2|2|0|1'),
                    self.timer_records()+runtime.timer_observer.PREFIX+b'|pending|root-close|3|2|1|1\n',
                    self.timer_records()+runtime.timer_observer.PREFIX+b'|overflow\n'):
            with self.subTest(raw=raw),self.assertRaises(WorkflowError):
                runtime.pending_witness(i,u,p,'node-stop-pending',raw)
        self.assertFalse(runtime.pending_witness(i,u,p,'node-stop-pending',self.timer_records())
                         ['auditEventsAloneProveTypedSuccess'])

    def test_pending_rejects_unavailable_incomplete_duplicate_and_malformed_observations(self):
        for change in ('incomplete','unavailable','scope','duplicate','bool','negative','epoch','page'):
            i,u,p=self.witness()
            if change=='incomplete':i['topology']['complete']=False
            elif change=='unavailable':u['tenantUsage']['unavailable']=['calls']
            elif change=='scope':u['nodeUsage']['scope']='tenant'
            elif change=='duplicate':p[0]['data']['records'].append(copy.deepcopy(p[0]['data']['records'][0]))
            elif change=='bool':i['topology']['entries'][0]['activeCount']=True
            elif change=='negative':u['nodeUsage']['counters']['broker_calls']='-1'
            elif change=='epoch':p[0]['data']['records'][0]['epoch']='unknown'
            else:p[0]['data']['page']['nextPageToken']='not-complete'
            with self.subTest(change=change),self.assertRaises(WorkflowError):
                runtime.pending_witness(i,u,p,'node-stop-pending',self.timer_records())

    def test_completed_process_is_not_a_pending_witness_and_never_triggers_cancellation(self):
        client=SimpleNamespace(deadline=time.monotonic()+1,call=Mock())
        pending=SimpleNamespace(owner=SimpleNamespace(exited=lambda:True))
        with self.assertRaisesRegex(WorkflowError,'real-pending-before-terminal'):
            runtime.wait_pending(client,pending,None,None,None,'closed-source-control')
        client.call.assert_not_called()

    def test_pending_read_budget_is_applied_to_real_cli_deadline_and_restored_on_failure(self):
        original=time.monotonic()+100
        def failed_drain():
            self.assertLessEqual(client.deadline,time.monotonic()+10)
            raise WorkflowError('owned-drain-control')
        client=SimpleNamespace(deadline=original,node=SimpleNamespace(drain=failed_drain))
        pending=SimpleNamespace(owner=SimpleNamespace(exited=lambda:False))
        with self.assertRaisesRegex(WorkflowError,'owned-drain-control'):
            runtime.wait_pending(client,pending,None,None,None,'source-control')
        self.assertEqual(client.deadline,original)

    def test_compiler_metadata_refuses_foreign_run_digest_and_native_input_kind(self):
        identity,size,sha=inputs.original.ARTIFACTS['engine']
        metadata={'id':identity,'size_in_bytes':size,'digest':'sha256:'+sha,'expired':False,
            'workflow_run':{'id':inputs.original.RUN,'head_sha':inputs.original.RUN_HEAD,
                            'repository_id':1337591365,'head_repository_id':1337591365}}
        self.assertEqual(inputs.metadata('engine',metadata)['source'],inputs.original.SOURCE)
        for field,value in [('id',identity+1),('digest','sha256:'+'0'*64),('expired',True)]:
            changed=copy.deepcopy(metadata);changed[field]=value
            with self.subTest(field=field),self.assertRaises(WorkflowError):inputs.metadata('engine',changed)
        with self.assertRaises(WorkflowError):inputs.metadata('native',metadata)

    def test_self_rehashed_compiler_member_cannot_replace_the_pinned_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);pins={};record={'schemaVersion':'latent.typescript.resource-runtime-compiler.v1',
                'credentialsRetained':False,'nativeHostsDownloaded':0,'inputs':{}}
            for kind,files in [('engine',{'engine.wasm':b'public-unit-engine','engine-input.json':b'{}'}),
                               ('splicer',{'splicer-input.json':b'{}','splicer/unit.mjs':b'public-unit-splicer'})]:
                buffer=io.BytesIO()
                with zipfile.ZipFile(buffer,'w') as archive:
                    for name,body in files.items():archive.writestr(name,body)
                raw=buffer.getvalue();sha=hashlib.sha256(raw).hexdigest();identity=1 if kind=='engine' else 2
                pins[kind]=(identity,len(raw),sha);(root/('archive-'+kind+'.zip')).write_bytes(raw)
                members=[]
                for name,body in files.items():
                    path=root/kind/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
                    members.append({'path':name,'sha256':'sha256:'+hashlib.sha256(body).hexdigest(),'bytes':len(body)})
                record['inputs'][kind]={'artifact':identity,'bytes':len(raw),'digest':'sha256:'+sha,
                    'run':inputs.original.RUN,'source':inputs.original.SOURCE,'workflowHead':inputs.original.RUN_HEAD,
                    'wholeArchiveDigestVerified':True,'members':members}
            receipt=root/'acquisition.json';receipt.write_bytes(json.dumps(record).encode())
            with patch.object(inputs.original,'ARTIFACTS',pins):
                self.assertEqual(inputs.verify(root),record)
                changed=b'self-rehashed-foreign-engine';(root/'engine/engine.wasm').write_bytes(changed)
                record['inputs']['engine']['members'][0].update(sha256='sha256:'+hashlib.sha256(changed).hexdigest(),bytes=len(changed))
                receipt.write_bytes(json.dumps(record).encode())
                with self.assertRaisesRegex(WorkflowError,'cannot-rebind-archive-members'):inputs.verify(root)


if __name__=='__main__':unittest.main()
