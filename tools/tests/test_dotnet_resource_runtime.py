"""Finite managed authority, pending-owner and observed compiler boundaries."""
import copy
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from tools import dotnet_resource_runtime_node as runtime
from tools import qualify_dotnet_resource_runtime as qualification
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_node import configure
from tools.rust_capsule_project import digest,write_json


class ManagedResourceRuntime(unittest.TestCase):
    def test_normal_async_greeting_world_and_public_namespace_cannot_be_relabelled(self):
        component='sha256:'+'a'*64
        release={'name':'my-greeting','service':'my-greeting','world':'examples:greeting/service@1.0.0',
            'componentDigest':component}
        capsule={'metadata':{'name':'examples/my-greeting','tenant':'examples'},
            'exports':['examples:greeting/api@1.0.0'],'component':{'world':release['world'],'digest':component}}
        qualification.checked_release(release,capsule,{'component':{'sha256':component}})
        for change in ('world','export','component','service'):
            r,c=copy.deepcopy((release,capsule))
            if change=='world':r['world']=c['component']['world']='foreign:greeting/service@1.0.0'
            elif change=='export':c['exports']=['examples:resource-runtime/api@1.0.0']
            elif change=='component':r['componentDigest']=c['component']['digest']='sha256:'+'b'*64
            else:r['service']='foreign/my-greeting'
            with self.subTest(change=change),self.assertRaises(WorkflowError):
                qualification.checked_release(r,c,{'component':{'sha256':component}})

    @staticmethod
    def capsule():
        return {'execution':{'limits':{'memoryBytes':134217728}},'imports':[
            {'contract':name,'optional':False} for name in (*runtime.SCALARS,runtime.ACTIVATION)]}

    def test_original_managed_bounds_distinct_tenant_aliases_and_no_implicit_grants(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'node').mkdir();(root/'signed').mkdir()
            (root/'signed/policy.json').write_bytes(b'{}\n')
            _,settings=configure(root/'node',root/'signed',12345,language='dotnet')
            before=copy.deepcopy(settings);runtime.configure(settings,self.capsule())
            self.assertEqual(settings['workers'],before['workers']);self.assertEqual(settings['cells'],before['cells'])
            self.assertEqual(settings['providers']['http'],before['providers']['http'])
            self.assertEqual(settings['providers']['activationRuntime']['limits'],
                {'tasks':8,'executors':2,'queuedWork':8,'waits':16,'timers':8,'results':8,'nativeOwners':8})
            self.assertEqual(len(settings['providers']['bindings']),11)
            self.assertEqual(len(settings['providers']['scalarAliases']),5)
            identities=[settings['providers'][key]['identity'] for key in ('clockMonotonic','clockWall','random','log')]
            self.assertTrue(all(row['service']=='runtime-host' for row in identities))
            self.assertEqual(settings['providers']['activationRuntime']['identity']['service'],'activation-host')
            self.assertEqual(settings['providers']['scalarAliases'][-1]['identity']['service'],'foreign-activation')
            self.assertNotIn('grants',settings['providers']['activationRuntime'])
            self.assertEqual(runtime.OPERATIONS,['register','park','wake','settle','close','observe','wait-for',
                'wait-until','timer-start','timer-next','timer-stop'])

    def test_missing_optional_duplicate_or_foreign_import_fails_before_configuration(self):
        for change in ('missing','optional','duplicate','foreign'):
            selected=self.capsule()
            if change=='missing':selected['imports'].pop()
            elif change=='optional':selected['imports'][0]['optional']=True
            elif change=='duplicate':selected['imports'][-1]=selected['imports'][0]
            else:selected['imports'][0]['contract']='outside:unsupported/runtime@1.0.0'
            with self.subTest(change=change),self.assertRaisesRegex(WorkflowError,'exact-imports'):
                runtime.configure({},selected)

    @staticmethod
    def witness():
        inventory={'topology':{'available':True,'complete':True,'entries':[
            {'name':name,'activeCount':'1'} for name in runtime.LIVE]}}
        usage={'tenantUsage':{'scope':'tenant','unavailable':[],'counters':{'calls':'1','sessions':'1'}},
            'nodeUsage':{'scope':'node','unavailable':[],'counters':{'broker_calls':'1'}}}
        pages=[{'category':'success','outcomeKnown':True,'data':{'page':{'nextPageToken':None},
            'coverage':{'droppedObservations':'1'},'records':[]}}]
        stderr=runtime.observer.PREFIX+b'|pending|wait-pending|1|0|1|1\n'
        return inventory,usage,pages,stderr

    def test_positive_native_pair_and_all_physical_provider_owners_remain_mandatory_even_with_audit_loss(self):
        inv,usage,pages,stderr=self.witness()
        proof=runtime.pending_witness(inv,usage,pages,'node-stop-pending',stderr)
        self.assertEqual(proof['physicalOwners'],dict.fromkeys(runtime.LIVE,1))
        self.assertTrue(proof['providerCallRetained']);self.assertFalse(proof['auditAloneIsBarrierEvidence'])
        self.assertTrue(proof['audit']['explicitLoss'])
        for change in ('no-native','no-store','no-provider','zero-loss','start-only'):
            i,u,p,s=copy.deepcopy((inv,usage,pages,stderr))
            if change=='no-native':s=b''
            elif change=='no-store':i['topology']['entries'][2]['activeCount']='0'
            elif change=='no-provider':u['nodeUsage']['counters']['broker_calls']='0'
            elif change=='zero-loss':p[0]['data']['coverage']['droppedObservations']='0'
            else:s=runtime.observer.PREFIX+b'|pending|start-accepted|1|1|0|1\n'
            with self.subTest(change=change):self.assertIsNone(runtime.pending_witness(i,u,p,'node-stop-pending',s))

    def test_zero_task_actual_pending_and_multiple_waits_keep_original_limits_and_positive_point(self):
        i,u,p,s=self.witness()
        actual=runtime.pending_witness(i,u,p,'node-stop-pending',s)
        self.assertEqual(actual['positiveTimer']['records'][0]['tasks'],0)
        second=runtime.observer.PREFIX+b'|pending|wait-pending|2|0|2|2\n'
        self.assertEqual(len(runtime.pending_witness(i,u,p,'node-stop-pending',s+second)
            ['positiveTimer']['records']),2)
        for counts in (b'0|0|1',b'0|1|0',b'9|1|1',b'0|17|1',b'0|1|9'):
            raw=runtime.observer.PREFIX+b'|pending|wait-pending|1|'+counts+b'\n'
            with self.subTest(counts=counts),self.assertRaises(WorkflowError):
                runtime.pending_witness(i,u,p,'node-stop-pending',raw)
        with self.assertRaises(WorkflowError):
            runtime.pending_witness(i,u,p,'node-stop-pending',s+runtime.observer.PREFIX+b'|overflow\n')

    def test_refused_audit_is_exact_closed_data_and_never_native_barrier_evidence(self):
        i,u,_p,s=self.witness()
        refused={'schemaVersion':'latent.cli.result.v1','category':'platform-failure','command':'audit query',
            'data':{},'error':{'code':'resource-exhausted','details':[],
                'message':'The platform reported a failure.','retryable':False},
            'outcomeKnown':True,'requestDispatched':True}
        proof=runtime.pending_witness(i,u,[refused],'node-stop-pending',s)
        self.assertFalse(proof['audit']['readRefusal']['barrierEvidence'])
        for change in ('unknown','details','outcome','duplicate'):
            row=copy.deepcopy(refused);pages=[row]
            if change=='unknown':row['error']['code']='internal'
            elif change=='details':row['error']['details']=['private']
            elif change=='outcome':row['outcomeKnown']=False
            else:pages.append(copy.deepcopy(row))
            with self.subTest(change=change),self.assertRaises(WorkflowError):
                runtime.pending_witness(i,u,pages,'node-stop-pending',s)

    def test_stale_before_invocation_pair_cannot_be_credited_and_read_deadline_is_restored(self):
        inv,usage,pages,stderr=self.witness()
        def control(*args,**_kwargs):
            if args[0]=='audit':return pages[0]
            if args[0]=='node':return {'data':{'inventory':inv}}
            if args[0]=='capability':return {'data':usage}
            self.fail('unexpected control')
        original=time.monotonic()+100
        client=SimpleNamespace(deadline=original,call=control,node=SimpleNamespace(drain=lambda:None,buffers=[b'',stderr]))
        pending=SimpleNamespace(owner=SimpleNamespace(exited=lambda:False),authoring_activation='node-stop-pending',
            authoring_started_unix_millis=1)
        with tempfile.TemporaryDirectory() as temporary,patch.object(runtime,'sample',return_value={}),patch.object(runtime.time,'sleep'):
            with self.assertRaisesRegex(RuntimeError,'pending-witness-attempts'):
                runtime.wait_pending(client,pending,None,{'name':'controlled'},Path(temporary),'stale',len(stderr))
            self.assertEqual(client.deadline,original)
            self.assertTrue(runtime.wait_pending(client,pending,None,{'name':'controlled'},Path(temporary),'current',0)
                ['witness']['providerCallRetained'])
        client.node.drain=Mock(side_effect=WorkflowError('owned-read-failure'))
        with self.assertRaisesRegex(WorkflowError,'owned-read-failure'):
            runtime.wait_pending(client,pending,None,{},None,'refusal',0)
        self.assertEqual(client.deadline,original)

    def test_secure_operation_upgrade_preserves_noncrypto_operation_budget_and_existing_grant(self):
        with tempfile.TemporaryDirectory() as temporary:
            original_binding={'formatVersion':1,'tenant':'examples','capability':runtime.RANDOM,
                'providerProfile':'system-random-v1','configurationDigest':'sha256:'+'a'*64,
                'configurationEpoch':1,'restriction':{'operations':['bytes']}}
            original_policy={'formatVersion':1,'tenant':'examples','rules':[{'id':'resource-runtime','effect':'allow',
                'principals':[{'kind':'administrator','subject':runtime.resources.SUBJECTS['examples']}],
                'services':['my-greeting'],'publications':['controlled-publication'],'capability':runtime.RANDOM,
                'operations':['bytes'],'resources':{'kind':'random'},
                'ceiling':{'operations':16,'inputBytes':8,'outputBytes':4096,'wallTimeMillis':5000}}]}
            observed={'random-examples-installed':('provider-binding','6',original_binding),
                'random-examples-allow':('policy','7',original_policy)}
            def control(*args):
                identity=args[args.index('--id')+1];kind,generation,document=observed[identity]
                if 'get' in args:return {'category':'success','outcomeKnown':True,'data':{'policy':{
                    'id':identity,'tenant':'examples','generation':generation,'recordKind':kind,
                    'revoked':False,'document':copy.deepcopy(document)}}}
                if args[-2:]!=('--expected-generation',generation):raise WorkflowError('state-conflict')
                return {'outcomeKnown':True}
            client=SimpleNamespace(directory=Path(temporary),call=Mock(side_effect=control))
            node=SimpleNamespace(startup_record={'providers':[{'id':'random','tenant':'examples',
                'profile':'system-random-v1','capability':runtime.RANDOM,'configurationDigest':'sha256:'+'a'*64}]})
            target={'service':'my-greeting','generation':'4','grants':[{'capability':runtime.RANDOM,'policy':'random-examples-allow'}]}
            with patch.object(runtime,'deploy',return_value=target) as deployment:
                runtime.grant_secure(client,node,None,'controlled-publication',target,'examples')
            binding=json.loads((client.directory/'resource-secure-binding-examples.json').read_bytes())
            policy=json.loads((client.directory/'resource-secure-policy-examples.json').read_bytes())
            self.assertEqual(binding['restriction']['operations'],['bytes','u64-value'])
            rule=policy['rules'][0];self.assertEqual(rule['operations'],['bytes','u64-value'])
            self.assertEqual(rule['ceiling'],{'operations':16,'inputBytes':8,'outputBytes':4096,'wallTimeMillis':5000})
            self.assertEqual(rule['id'],'resource-runtime')
            self.assertEqual(deployment.call_args.kwargs['grants'],target['grants'])
            calls=[args for args,kwargs in client.call.call_args_list]
            self.assertEqual(['get' in args for args in calls],[True,True,False,False])
            self.assertEqual([args[-1] for args in calls[2:]],['6','7'])

    def test_entropy_policy_generation_requires_exact_original_tenant_document_and_live_record(self):
        document={'restriction':{'operations':['bytes']}}
        original={'id':'controlled','tenant':'examples','generation':'6','recordKind':'provider-binding',
            'revoked':False,'document':document}
        for change in ('tenant','document','kind','revoked','zero','leading-zero','foreign-digit','unknown'):
            record=copy.deepcopy(original);response={'category':'success','outcomeKnown':True,'data':{'policy':record}}
            if change=='tenant':record['tenant']='foreign'
            elif change=='document':record['document']['restriction']['operations'].append('u64-value')
            elif change=='kind':record['recordKind']='policy'
            elif change=='revoked':record['revoked']=True
            elif change=='zero':record['generation']='0'
            elif change=='leading-zero':record['generation']='06'
            elif change=='foreign-digit':record['generation']='\u0666'
            else:response['outcomeKnown']=False
            client=SimpleNamespace(call=Mock(return_value=response))
            with self.subTest(change=change),self.assertRaisesRegex(WorkflowError,'original-entropy-policy-observation'):
                runtime.policy_generation(client,'controlled','examples','provider-binding',document)

    @staticmethod
    def build(directory):
        component=b'controlled-component';core='sha256:'+'b'*64
        docs={'source-inputs.json':{},'recipe-inputs.json':{},'package-inputs.json':{},'closed-runtime-coverage.json':{},
            'compiler-patches.json':{},'runtime-profile.json':{'profile':'runtime-logging','declaredImports':list(runtime.fixture.DECLARATIONS)},
            'task-wait-port.json':{'profile':qualification.TASK_PROFILE,'completion':'actual-task-only',
                'nativeAotReferenceBinding':{'responseFiles':[{}],'finalCoreLibDerivation':{'selectedDigest':core}}},
            'closed-filesystem-port.json':{'derived':{'digest':core},'nativeAotReferenceBinding':{'selectedCoreLibDigest':core}},
            'managed-entropy-port.json':{'nativeAotReferenceBinding':[{}]},
            'noncrypto-entropy-port.json':{'profile':'dotnet-native-entropy-v2','nativeLinkBinding':{'secureWrapOccurrences':1}}}
        for name,data in docs.items():write_json(directory/name,data)
        (directory/'component.wasm').write_bytes(component)
        materials=[]
        for name,file in [('build-recipe','recipe-inputs.json'),('package-inputs','package-inputs.json'),
            ('runtime-profile','runtime-profile.json'),('dotnet-task-wait-port','task-wait-port.json'),
            ('dotnet-closed-filesystem-port','closed-filesystem-port.json'),('standard-rng-managed-port','managed-entropy-port.json')]:
            raw=(directory/file).read_bytes();materials.append({'name':name,'digest':digest(raw),'size':len(raw)})
        observed={'componentDigest':digest(component),'componentSize':len(component),'materials':materials,'parameters':{
            'compiler':'native-aot-llvm','bindings':'wit-bindgen-csharp','language':'csharp','target':'wasi-wasm',
            'runtime':'native-aot','locked':True,'ambientWasi':False}}
        write_json(directory/'build-observation.json',observed)
        write_json(directory/'BUILD-COMPLETE.json',{'packageAssembled':True,'componentDigest':digest(component),
            'observationDigest':digest((directory/'build-observation.json').read_bytes()),
            'sourceDigest':digest((directory/'source-inputs.json').read_bytes())})
        return docs

    def test_build_reader_requires_actual_current_runtime_and_final_task_filesystem_rng_bindings(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(qualification,'package_identity',return_value={'controlled':'package'}):
            root=Path(temporary);docs=self.build(root)
            actual=json.loads((Path(__file__).parent/'fixtures/dotnet_resource_managed_df4.json').read_bytes())
            self.assertEqual(actual['source'],'df4f5628add1a9ba9b1562ee00353fad57e4f7d5')
            self.assertFalse(actual['guestQualification'])
            self.assertNotEqual(actual['records']['runtime-profile.json']['profile'],'runtime-logging')
            for name,value in actual['records'].items():
                docs.setdefault(name,{}).update(value)
            for name,value in docs.items():(root/name).write_bytes((json.dumps(value)+'\n').encode())
            observed=json.loads((root/'build-observation.json').read_bytes())
            observed['materials'].extend([docs['runtime-profile.json']['adapter'],{'name':'dotnet-internal-io-port'}])
            names={'build-recipe':'recipe-inputs.json','package-inputs':'package-inputs.json','runtime-profile':'runtime-profile.json',
                'dotnet-task-wait-port':'task-wait-port.json','dotnet-closed-filesystem-port':'closed-filesystem-port.json',
                'standard-rng-managed-port':'managed-entropy-port.json','dotnet-internal-io-port':'internal-io-port.json'}
            for material in observed['materials']:
                if material['name'] in names:
                    raw=(root/names[material['name']]).read_bytes();material.update(digest=digest(raw),size=len(raw))
            (root/'build-observation.json').write_bytes((json.dumps(observed)+'\n').encode())
            marker=json.loads((root/'BUILD-COMPLETE.json').read_bytes())
            marker['observationDigest']=digest((root/'build-observation.json').read_bytes())
            (root/'BUILD-COMPLETE.json').write_bytes((json.dumps(marker)+'\n').encode())
            self.assertEqual(qualification.build_evidence(root)['package'],{'controlled':'package'})
            for change in ('closed-profile','closed-metadata','corelib-drift','missing-ilc-binding'):
                selected=copy.deepcopy(docs)
                if change=='closed-profile':selected['runtime-profile.json']['profile']='closed-logging'
                elif change=='closed-metadata':selected['runtime-profile.json']['closedIoPort']={}
                elif change=='corelib-drift':selected['task-wait-port.json']['nativeAotReferenceBinding']['finalCoreLibDerivation']['selectedDigest']='sha256:'+'c'*64
                else:selected['managed-entropy-port.json']['nativeAotReferenceBinding']=[]
                # Rehash public observation metadata, so failure must be semantic.
                for name,value in selected.items():
                    (root/name).write_bytes((json.dumps(value)+'\n').encode())
                observed=json.loads((root/'build-observation.json').read_bytes())
                names={'build-recipe':'recipe-inputs.json','package-inputs':'package-inputs.json','runtime-profile':'runtime-profile.json',
                    'dotnet-task-wait-port':'task-wait-port.json','dotnet-closed-filesystem-port':'closed-filesystem-port.json',
                    'standard-rng-managed-port':'managed-entropy-port.json','dotnet-internal-io-port':'internal-io-port.json'}
                for material in observed['materials']:
                    if material['name'] not in names:continue
                    raw=(root/names[material['name']]).read_bytes();material.update(digest=digest(raw),size=len(raw))
                (root/'build-observation.json').write_bytes((json.dumps(observed)+'\n').encode())
                marker=json.loads((root/'BUILD-COMPLETE.json').read_bytes());marker.update(
                    observationDigest=digest((root/'build-observation.json').read_bytes()),sourceDigest=digest((root/'source-inputs.json').read_bytes()))
                (root/'BUILD-COMPLETE.json').write_bytes((json.dumps(marker)+'\n').encode())
                with self.subTest(change=change),self.assertRaises(WorkflowError):qualification.build_evidence(root)

    def test_managed_runtime_reader_binds_owner_private_io_and_original_timer_admission(self):
        mutations=(
            lambda d:d['runtime-profile.json'].update(profile='runtime-logging'),
            lambda d:d['runtime-profile.json']['declaredImports'].append('latent:http/streaming@0.3.0'),
            lambda d:d['retirement-port.json'].update(authority='http'),
            lambda d:d['retirement-port.json']['managedWork'].update(privateImport='foreign:work/owner@0.1.0'),
            lambda d:d['internal-io-port.json'].update(coreBytesUnchanged=False),
            lambda d:d['internal-io-port.json'].update(publicApplicationGraphUnchanged=False),
            lambda d:d['closed-runtime-coverage.json'].update(compilerPrivateImports=[]),
            lambda d:d['closed-runtime-coverage.json'].update(gaps=['missing']),
            lambda d:d['closed-runtime-coverage.json'].update(runtimeAdapterDigest='sha256:'+'c'*64),
            lambda d:d['task-wait-port.json']['managedAcceptedWork'].update(authoritativeLimits='unbounded'),
            lambda d:d['task-wait-port.json']['managedAcceptedWork'].update(timerAdmission='after-enqueue'),
            lambda d:d['task-wait-port.json']['managedAcceptedWork'].update(newAssemblyReferences=1))
        for mutate in mutations:
            with tempfile.TemporaryDirectory() as temporary,patch.object(qualification,'package_identity',return_value={}):
                root=Path(temporary);docs=self.build(root)
                actual=json.loads((Path(__file__).parent/'fixtures/dotnet_resource_managed_df4.json').read_bytes())
                for name,value in actual['records'].items():docs.setdefault(name,{}).update(value)
                observed=json.loads((root/'build-observation.json').read_bytes())
                observed['materials'].extend([copy.deepcopy(docs['runtime-profile.json']['adapter']),{'name':'dotnet-internal-io-port'}])
                mutate(docs)
                for name,value in docs.items():(root/name).write_bytes((json.dumps(value)+'\n').encode())
                names={'runtime-profile':'runtime-profile.json','dotnet-task-wait-port':'task-wait-port.json',
                    'dotnet-internal-io-port':'internal-io-port.json'}
                for material in observed['materials']:
                    if material['name'] in names:
                        raw=(root/names[material['name']]).read_bytes();material.update(digest=digest(raw),size=len(raw))
                (root/'build-observation.json').write_bytes((json.dumps(observed)+'\n').encode())
                marker=json.loads((root/'BUILD-COMPLETE.json').read_bytes())
                marker['observationDigest']=digest((root/'build-observation.json').read_bytes())
                (root/'BUILD-COMPLETE.json').write_bytes((json.dumps(marker)+'\n').encode())
                with self.assertRaises((WorkflowError,KeyError)):
                    qualification.build_evidence(root)

    def test_fractional_remaining_setup_time_floors_within_original_deadline_before_signing(self):
        actual_commands=qualification.Commands
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            with self.assertRaisesRegex(ValueError,'finite build command and overall deadlines required'):
                actual_commands(root,root,{},deadline_seconds=599.75,command_seconds=120)
            captured=[]
            def constructor(*args,**kwargs):
                captured.append(kwargs)
                actual_commands(*args,**kwargs)
                raise RuntimeError('controlled-before-signing')
            with patch.object(qualification,'build_evidence',return_value={}), \
                    patch.object(qualification.time,'monotonic',return_value=100.25), \
                    patch.object(qualification,'Commands',side_effect=constructor), \
                    self.assertRaisesRegex(RuntimeError,'controlled-before-signing'):
                qualification.execute(root/'build',{},root/'node',late_completion=True,deadline=700)
            self.assertEqual(captured,[{'deadline_seconds':599,'command_seconds':120}])
            self.assertLessEqual(100.25+captured[0]['deadline_seconds'],700)


if __name__=='__main__':unittest.main()
