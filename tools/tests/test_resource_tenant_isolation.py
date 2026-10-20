"""Source-only tenant/package/product controls; no node runs in this module."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import resource_tenant_inputs as inputs, resource_tenant_node as node
from tools import qualify_resource_tenants as programme, resource_tenant_originals as originals
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import digest


class ResourceTenantIsolation(unittest.TestCase):
    def producer(self):
        return {'id':inputs.PRODUCER_ARTIFACT,'name':'sdk-native-products-'+inputs.PRODUCER_HEAD,'expired':False,
            'size_in_bytes':inputs.PRODUCER_BYTES,'digest':inputs.PRODUCER_DIGEST,'workflow_run':{'id':inputs.PRODUCER_RUN,
                'head_sha':inputs.PRODUCER_HEAD,'repository_id':inputs.REPOSITORY_ID,
                'head_repository_id':inputs.REPOSITORY_ID}}

    def native_fixture(self, root):
        binaries=root/'native-binaries';binaries.mkdir()
        products={}
        for name in inputs.PRODUCTS:
            p=binaries/name.replace('/','-');p.write_bytes(('test-owned-'+name).encode())
            products[name]=file_identity(p)
        materials={name:{'sha256':'sha256:'+'1'*64,'bytes':1} for name in inputs.MATERIALS}
        source={'sha256':'sha256:'+'2'*64,'files':3,'bytes':128,
            'scope':'explicit-apps-crates-rust-sdk-workloads-and-workspace-inputs',
            'hermetic':False,'implicitCompilerInputs':'not-attested'}
        value={'schemaVersion':'latent.sdk.native-products.v1','status':'built',
            'sourceRevision':inputs.PRODUCER_HEAD,'profile':'normal-managed-guest-default-features',
            'compiler':inputs.COMPILER,'source':source,'materials':materials,
            'products':products,'commands':[{'stage':stage,'exitCode':0,'seconds':1.0} for stage in inputs.STAGES],
            'signedQualification':False,'guestComponentsCompiled':False,'historicalReceiptRewritten':False}
        (root/'native-products.json').write_bytes(json.dumps(value).encode())
        (root/'source-inputs.json').write_bytes(json.dumps({'native':source,'materials':materials}).encode())
        return value

    def settings(self):
        return {'workers':{'runtime':1,'control':1},'cells':[{'capacity':1,'queueCapacity':2,
            'maximumMemoryBytes':67108864}],'execution':{'maximumCpuFuel':10_000_000_000,'maximumWallTimeMillis':5000},
            'cache':{'entries':2,'preparations':1},'audit':{'records':1024,'diskBytes':16777216},
            'credentials':[{'token':node.TOKEN,'subject':'workflow-operator','tenant':'examples','role':'operator'}],
            'providers':{'formatVersion':1,'http':{'identity':{'id':'http','tenant':'examples'}},
                'bindings':[{'name':'original-http-observation','contract':'latent:http/client@0.2.0',
                    'tenant':'examples','consumerService':'examples/my-http-status'}]}}

    def capsule(self, imports=()):
        return {'imports':[{'contract':name,'optional':False} for name in imports],
            'execution':{'limits':{'memoryBytes':67108864}}}

    def test_producer_requires_fixed_run_source_repo_and_normal_identity_without_guest_claim(self):
        observed=inputs.validate_producer(self.producer())
        self.assertFalse(observed['signedQualification']);self.assertFalse(observed['guestComponentsCompiled'])
        for field in ('name','expired','size_in_bytes','digest','id','run','source','repository','head_repository'):
            value=self.producer()
            if field=='run':value['workflow_run']['id']+=1
            elif field=='source':value['workflow_run']['head_sha']='b'*40
            elif field=='repository':value['workflow_run']['repository_id']+=1
            elif field=='head_repository':value['workflow_run']['head_repository_id']+=1
            elif field=='expired':value[field]=True
            else:value[field]=False
            with self.subTest(field=field),self.assertRaises(RuntimeError):inputs.validate_producer(value)

    def test_native_receipt_rechecks_every_product_and_exact_required_control_stages(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);receipt=self.native_fixture(root)
            with patch.object(inputs,'PRODUCER_RECEIPT',file_identity(root/'native-products.json')), \
                    patch.object(inputs,'PRODUCER_SOURCE',file_identity(root/'source-inputs.json')):
                paths,proof=inputs.native_products(root,self.producer())
            self.assertEqual(set(paths),set(inputs.PRODUCTS));self.assertFalse(proof['compiledCurrentConsumerSource'])
            for name,path in paths.items():
                before=path.read_bytes();path.write_bytes(before+b'changed')
                with self.subTest(name=name),self.assertRaisesRegex(RuntimeError,'product-bytes'):
                    with patch.object(inputs,'PRODUCER_RECEIPT',file_identity(root/'native-products.json')), \
                            patch.object(inputs,'PRODUCER_SOURCE',file_identity(root/'source-inputs.json')):
                        inputs.native_products(root,self.producer())
                path.write_bytes(before)
            for mode in ('stage','failed','snapshot','claim','profile'):
                value=copy.deepcopy(receipt)
                if mode=='stage':value['commands'].pop()
                elif mode=='failed':value['commands'][2]['exitCode']=1
                elif mode=='snapshot':value['source']['sha256']='sha256:'+'9'*64
                elif mode=='claim':value['signedQualification']=True
                else:value['profile']='alternate-host'
                (root/'native-products.json').write_bytes(json.dumps(value).encode())
                with self.subTest(mode=mode),self.assertRaises(RuntimeError):inputs.native_products(root,self.producer())

    def test_original_producers_refuse_foreign_archive_or_run_even_with_valid_looking_digests(self):
        for language,row in originals.ORIGINALS.items():
            value={'id':row['artifact'],'name':row['name'],'size_in_bytes':row['bytes'],
                'digest':row['digest'],'expired':False,'workflow_run':{'id':row['run'],
                    'head_sha':row['head'],'repository_id':inputs.REPOSITORY_ID,
                    'head_repository_id':inputs.REPOSITORY_ID}}
            self.assertEqual(originals.validate_producer(language,value),row)
            for field in ('id','name','size_in_bytes','digest','run','head_sha','repository_id','expired'):
                changed=copy.deepcopy(value)
                owner=changed['workflow_run'] if field in {'run','head_sha','repository_id'} else changed
                owner['id' if field=='run' else field]=True if field=='expired' else 'foreign'
                with self.subTest(language=language,field=field),self.assertRaises(RuntimeError):
                    originals.validate_producer(language,changed)

    def test_public_wit_restoration_must_match_both_original_source_and_package_inventories(self):
        for language in originals.ORIGINALS:
            for name,raw in originals.public_wit(language).items():
                selected={'digest':digest(raw),'size':len(raw)}
                self.assertEqual(originals.restored_public_bytes(language,name,selected,{name:selected},{}),raw)
                for package,source in ((selected,{name:{'digest':'sha256:'+'0'*64,'size':len(raw)}}),
                        ({'digest':digest(raw),'size':len(raw)+1},{name:selected})):
                    with self.subTest(language=language,name=name),self.assertRaises(RuntimeError):
                        originals.restored_public_bytes(language,name,package,source,{})
        with self.assertRaisesRegex(RuntimeError,'not-authorized'):
            originals.restored_public_bytes('go','unretained-private-source',{}, {}, {})

    def test_restored_java_objects_require_exact_original_index_membership_and_payload(self):
        raw=b'\x00\xff\x80A\r\n';name='resources/objects/'+digest(raw)[7:]
        selected={'digest':digest(raw),'size':len(raw)}
        index={'resources':[{'object':name,**selected}]}
        self.assertEqual(originals.restored_public_bytes('java',name,selected,{},index),raw)
        for altered in ({'resources':[]},{'resources':[{'object':name,**selected,'size':7}]}):
            with self.assertRaisesRegex(RuntimeError,'not-original-index'):
                originals.restored_public_bytes('java',name,selected,{},altered)
        with self.assertRaises(RuntimeError):
            originals.restored_public_bytes('java','resources/objects/'+'0'*64,selected,{},index)

    def test_two_tenant_aliases_keep_original_single_cell_and_observation_provider_unchanged(self):
        settings=self.settings();http=copy.deepcopy(settings['providers'])
        selected=node.configure(settings,self.capsule(node.PROFILES),'dotnet')
        self.assertEqual(selected['providers']['http'],http['http'])
        self.assertEqual(selected['providers']['bindings'][0],http['bindings'][0])
        self.assertEqual(len(selected['providers']['bindings']),9)
        self.assertEqual(len(selected['providers']['scalarAliases']),4)
        self.assertEqual(selected['cells'][0]['capacity'],1);self.assertEqual(selected['cells'][0]['queueCapacity'],2)
        self.assertEqual(selected['execution']['maximumCpuFuel'],10_000_000_000)
        self.assertEqual({row['identity']['tenant'] for row in selected['providers']['scalarAliases']},{'foreign'})
        self.assertEqual({row['consumerService'] for row in selected['providers']['bindings'][1:]},{'my-greeting'})
        for tenant in node.TENANTS:
            rows=[row for row in selected['providers']['bindings'][1:] if row['tenant']==tenant]
            self.assertEqual(len(rows),4)
            self.assertTrue(all(tenant in row['providerBinding'] for row in rows))

    def test_unknown_optional_duplicate_imports_or_preexisting_shared_authority_fail_closed(self):
        for imports in ([{'contract':'unowned:clock/source@1.0.0','optional':False}],
                [{'contract':next(iter(node.PROFILES)),'optional':True}],
                [{'contract':next(iter(node.PROFILES)),'optional':False}]*2):
            value=self.capsule();value['imports']=imports
            with self.assertRaises(RuntimeError):node.required_imports(value)
        settings=self.settings();settings['cells'][0]['capacity']=2
        with self.assertRaisesRegex(RuntimeError,'single-cell'):node.configure(settings,self.capsule(),'rust')

    def test_neutral_deployments_only_change_own_operator_scope_and_leave_original_bytes_model_intact(self):
        original={'metadata':{'name':'my-greeting'},'spec':{'service':'my-greeting','release':'sha256:'+'1'*64,
            'resources':{'cpuFuel':10},'grants':[]}}
        before=copy.deepcopy(original)
        for tenant in node.TENANTS:
            value=node.scoped_deployment(original,tenant)
            self.assertEqual(value['spec'],original['spec'])
            self.assertEqual(value['metadata'],{'tenant':tenant,'name':'resource-'+tenant})
        self.assertEqual(original,before)
        for tenant in ('other','../examples'):
            with self.assertRaises(RuntimeError):node.scoped_deployment(original,tenant)
        original['spec']['grants']=[{'capability':'inherited-authority'}]
        with self.assertRaises(RuntimeError):node.scoped_deployment(original,'foreign')

    def test_grants_are_bound_to_the_selected_tenant_subject_service_and_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);seen={}
            capability='latent:random/random@0.1.0'
            for tenant in node.TENANTS:
                directory=root/tenant;directory.mkdir()
                client=SimpleNamespace(directory=directory,call=lambda *args,**kwargs: seen.setdefault(tenant,[]).append(args))
                descriptor={'id':'random' if tenant=='examples' else 'random-foreign','tenant':tenant,
                    'service':'runtime-host' if tenant=='examples' else 'foreign-runtime','capability':capability,
                    'profile':'system-random-v1','configurationEpoch':'1','configurationDigest':'sha256:'+'3'*64}
                target={'service':'my-greeting','grants':[],'generation':'1'}
                with patch.object(node,'deploy',side_effect=lambda _client,_source,_publication,**kwargs:kwargs):
                    granted=node.install_grants(client,SimpleNamespace(startup_record={'providers':[descriptor]}),
                        directory/'deployment.json','publication-'+tenant,target,[capability],'dotnet',tenant)
                self.assertEqual(granted['grants'],[{'capability':capability,'policy':'random-'+tenant+'-allow'}])
                policy=json.loads((directory/('random-'+tenant+'-allow.json')).read_bytes())
                rule=policy['rules'][0]
                self.assertEqual(policy['tenant'],tenant);self.assertEqual(rule['publications'],['publication-'+tenant])
                self.assertEqual(rule['principals'],[{'kind':'administrator','subject':node.SUBJECTS[tenant]}])
                self.assertEqual(rule['operations'],['bytes']);self.assertEqual(rule['ceiling']['inputBytes'],8)
                self.assertEqual(rule['ceiling']['operations'],16)

    def test_provider_barrier_requires_all_eighteen_configured_owner_counters_available_and_zero(self):
        value={'nextPageToken':None,'nodeUsage':{'unavailable':[],
            'counters':{name:'0' for name in node.ACTIVE_COUNTERS}}}
        client=SimpleNamespace(call=lambda *args,**kwargs:{'data':value})
        self.assertEqual(node.provider_idle(client,{'name':'resource-examples'}),value['nodeUsage'])
        for mode in ('missing','live','unavailable','page'):
            changed=copy.deepcopy(value)
            if mode=='missing':changed['nodeUsage']['counters'].pop(node.ACTIVE_COUNTERS[0])
            elif mode=='live':changed['nodeUsage']['counters'][node.ACTIVE_COUNTERS[0]]='1'
            elif mode=='unavailable':changed['nodeUsage']['unavailable']=['pool-not-configured']
            else:changed['nextPageToken']='remaining'
            client=SimpleNamespace(call=lambda *args,**kwargs:{'data':changed})
            with self.subTest(mode=mode),self.assertRaises((RuntimeError,KeyError)):
                node.provider_idle(client,{'name':'resource-examples'})

    def test_foreign_credential_denial_keeps_authorized_scope_unchanged_and_restores_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);config=root/'client.json'
            original={'profiles':[{'token':node.FOREIGN_TOKEN,'tenant':'foreign'}]}
            config.write_bytes(json.dumps(original).encode())
            before={'outcomeKnown':True,'category':'success','data':{
                'deployment':{'manifest':{'metadata':{'tenant':'foreign'}}}}}
            denied={'schemaVersion':'latent.cli.result.v1','command':'deployment get','category':'not-found',
                'data':{'deployment':None,'durability':None,'routeGeneration':None,'stateVersion':None},
                'error':None,'outcomeKnown':True,'requestDispatched':True}
            state={'calls':0}
            client=SimpleNamespace(config=config,directory=root,last_exit_status=0)
            def call(*_args,**_kwargs):
                state['calls']+=1
                if state['calls']==2:
                    self.assertEqual(json.loads(client.config.read_bytes())['profiles'][0]['token'],node.TOKEN)
                    client.last_exit_status=6;return denied
                client.last_exit_status=0;return copy.deepcopy(before)
            client.call=call
            observed=programme.credential_denial(client,{'name':'resource-foreign'})
            self.assertEqual(client.config,config)
            self.assertEqual(json.loads(config.read_bytes()),original)
            self.assertEqual(observed['authorizedBefore'],observed['authorizedAfter'])
            self.assertFalse(observed['credentialsRetained'])

    def test_unused_observation_peer_requires_exact_zero_counts_and_actual_reap(self):
        counts={name:0 for name in ('requests','authorized','unexpected','holds','closedHolds')}
        for mode in ('valid','contact','boolean','missing','duplicate','extra-line','unreaped','exit'):
            value=copy.deepcopy(counts)
            if mode=='contact':value['requests']=1
            elif mode=='boolean':value['holds']=False
            elif mode=='missing':value.pop('closedHolds')
            raw=json.dumps(value).encode()+b'\n'
            if mode=='duplicate':raw=raw.replace(b'{',b'{"requests":0,',1)
            if mode=='extra-line':raw+=b'{}\n'
            calls=[]
            peer=SimpleNamespace(buffers=[bytearray(raw),bytearray()],closed=True,
                owner=SimpleNamespace(finished=mode!='unreaped',
                    process=SimpleNamespace(returncode=1 if mode=='exit' else 0)),stop=lambda:calls.append('stop'))
            if mode=='valid':
                observed=programme.stop_observation_peer(peer)
                self.assertEqual(observed,{'counts':counts,'closed':True,'reaped':True,'exitCode':0})
            else:
                with self.subTest(mode=mode),self.assertRaises((RuntimeError,ValueError)):
                    programme.stop_observation_peer(peer)
            self.assertEqual(calls,['stop'])

    def test_seven_call_order_traps_one_scope_then_checks_fresh_resources_in_both_scopes(self):
        for language in inputs.LANGUAGES:
            argument,expected,trapped=node.sequence(language);calls=[]
            def invoke(client,target,source,label,_component):
                calls.append((client,source,label))
                return {'activation':label,'exitCode':4 if source==trapped else 0,
                    'decoded':None if source==trapped else [{'ok':expected}],
                    'response':{'error':{'code':'guest-trap'},'data':{'terminalState':'guest_trap'}}}
            observed={'invocations':[],'providerIdle':[],'samples':[]}
            with patch.object(node,'invoke',side_effect=invoke),patch.object(node,'provider_idle',return_value={'zero':True}), \
                    patch.object(node,'sample',return_value={'retired':True}):
                result=node.programme({'examples':'A','foreign':'B'},{'examples':{},'foreign':{}},None,'same-component',language,observed)
            self.assertEqual([(scope,source) for scope,source,_label in calls],
                [('A',argument),('A',trapped),('B',argument),('A',argument),('B',trapped),('A',argument),('B',argument)])
            self.assertEqual(len(observed['invocations']),7);self.assertEqual(len(observed['providerIdle']),7)
            self.assertFalse(result['concurrentResourceReadsQualified']);self.assertFalse(result['pendingFlushQualified'])
            self.assertFalse(result['fullTicketQualification'])


if __name__ == '__main__':unittest.main()
