"""Fail-closed source/oracle controls; no guest or native compilation."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from tools import qualify_rust_wasi_http_runtime as qualification
from tools import rust_wasi_http_runtime_node as node
from tools.rust_capsule_project import canonical,digest


class SourceAndNativeSeparation(unittest.TestCase):
    def test_catalogue_absence_is_bound_to_complete_actual_source_and_recipe_names(self):
        source={'src/lib.rs':{},'sdk/src/lib.rs':{},'sdk-lock.json':{}}
        recipe={'sdk/wasi-http-runtime/types.rs':{},'tools/rust_capsule_build.py':{}}
        proof=qualification.catalogue_inputs(source,recipe)
        self.assertEqual(proof['catalogueDataInputs'],[])
        self.assertEqual(proof['sourceInputNames'],sorted(source))
        self.assertEqual(proof['recipeInputNames'],sorted(recipe))
        self.assertEqual(proof['sdkInputNames']['captured-source'],['sdk/src/lib.rs'])
        self.assertFalse(proof['repositoryPublicationDataDeleted'])
        for selected in ('source','recipe'):
            for name in ('docs/compatibility-catalogue/v3/evidence/entry.json','catalogue.json','../hidden','/absolute','a\\b'):
                a=copy.deepcopy(source);b=copy.deepcopy(recipe)
                (a if selected=='source' else b)[name]={}
                with self.subTest(selected=selected,name=name),self.assertRaises(Exception):
                    qualification.catalogue_inputs(a,b)

    def test_only_the_reviewed_unlinked_frontend_pair_may_differ(self):
        original={f'wit/unchanged-{i}.wit':{'sha256':'sha256:'+'1'*64,'bytes':3} for i in range(133)}
        current=copy.deepcopy(original)
        for name,(before,after) in qualification.FRONTEND.items():original[name]=before;current[name]=after
        value=qualification.native_compatibility(original,current)
        self.assertEqual(value['unchangedAuxiliaryRows'],133)
        self.assertFalse(value['allAuxiliaryRowsCurrentAtProducerCompilation'])
        for mutate in ('new-source','new-WIT','missing','extra','old-frontend'):
            changed=copy.deepcopy(current)
            if mutate=='new-source':changed['tools/rust_capsule_build.py']['sha256']='sha256:'+'2'*64
            if mutate=='new-WIT':changed['wit/unchanged-0.wit']['bytes']=4
            if mutate=='missing':changed.pop('wit/unchanged-1.wit')
            if mutate=='extra':changed['unknown']={'sha256':'sha256:'+'3'*64,'bytes':1}
            if mutate=='old-frontend':changed['tools/rust_capsule_build.py']=original['tools/rust_capsule_build.py']
            with self.subTest(mutate=mutate),self.assertRaises(Exception):
                qualification.native_compatibility(original,changed)

    def test_unsupported_platform_refuses_before_output_or_product_acquisition(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(qualification.sys,'platform','win32'):
            out=Path(temporary)/'absent'
            with self.assertRaisesRegex(Exception,'linux-python313'):
                qualification.qualify(Path('not-present'),Path('not-present'),out)
            self.assertFalse(out.exists())

    def test_each_original_core_namespace_must_remain_in_the_actual_selected_component(self):
        core=b'\0asm\x01\0\0\0'
        component=b'\0asm\x0d\0\x01\0'+b'\x01'+bytes([len(core)])+core
        projection={'root':False,'coreBytesUnchanged':True,'publicApplicationGraphUnchanged':True,
            'runtimeQualification':False,'cores':[{'sha256':digest(core),'bytes':len(core)}]}
        record={'schemaVersion':'latent.rust.http.exact-composition.v1','profile':qualification.PROFILE,
            'publicGraphUnchanged':True,'librarySourceRewritten':False,'signedExecutionQualification':False,
            'selectedComponentDigest':digest(component),'imports':sorted(qualification.AUTHORITY),
            'exports':['examples:greeting/api@1.0.0'],'originalCoreModulesRetained':1,
            'internalIo':projection,'privateDrain':{**projection,'root':True}}
        adapter={'cores':[{'digest':digest(core),'size':len(core)}]}
        qualification.verify_composition(record,component,adapter)
        for mutate in ('private-leak','new-core','public-graph','duplicate-missing','claim-runtime'):
            changed=copy.deepcopy(record)
            if mutate=='private-leak':changed['imports'].append('latent:rust-http-retirement/owner@0.1.0')
            if mutate=='new-core':changed['internalIo']['cores'][0]['sha256']='sha256:'+'0'*64
            if mutate=='public-graph':changed['publicGraphUnchanged']=False
            if mutate=='duplicate-missing':
                changed['internalIo']['cores']*=2;changed['originalCoreModulesRetained']=2
            if mutate=='claim-runtime':changed['privateDrain']['runtimeQualification']=True
            with self.subTest(mutate=mutate),self.assertRaises(Exception):
                qualification.verify_composition(changed,component,adapter)


class RuntimeOracles(unittest.TestCase):
    def test_real_library_diagnostics_discriminate_timeout_permission_json_and_opaque_stream_errors(self):
        def payload(client,phase,display,debug,**public):
            base=({'typedWasiErrorCode':None,'serdeJsonError':False} if client=='waki' else {
                'isBuilder':False,'isRequest':True,'isBody':False,'isDecode':False,'isTimeout':False,
                'isStatus':False,'serdeJsonError':False,'sourceDisplay':None})
            base.update(public)
            value={'phase':phase,'display':display,'debug':debug,'displayBytes':len(display.encode()),
                'debugBytes':len(debug.encode()),'truncated':False,'public':base}
            return 'library-error:'+json.dumps(value)
        cases=[('waki','error:timeout-option',payload('waki','send','failed to set connect_timeout','failed to set connect_timeout')),
            ('golem','error:timeout-option',payload('golem','send','error sending request','real upstream request debug',sourceDisplay='set_first_byte_timeout')),
            ('waki','error:request-denied',payload('waki','send','HttpRequestDenied','HttpRequestDenied',typedWasiErrorCode='HttpRequestDenied')),
            ('golem','error:request-denied',payload('golem','send','error sending request','real upstream request debug',sourceDisplay='HttpRequestDenied')),
            ('waki','error:reserved-header',payload('waki','send','Forbidden','Forbidden')),
            ('golem','error:reserved-header',payload('golem','send','error sending request','real upstream request debug',sourceDisplay='Forbidden')),
            ('waki','error:json-decode',payload('waki','json','expected value','Error("expected value", line: 1, column: 1)',serdeJsonError=True)),
            ('golem','error:json-decode',payload('golem','json','error decoding response body','real serde source debug',isRequest=False,isDecode=True,serdeJsonError=True))]
        for client,expected,value in cases:
            self.assertTrue(node.library_error(value,client,expected)['exactUnderlyingCategoryProven'])
            for mutate in ('truncated','count','phase','json-kind','permission-substitution'):
                changed=json.loads(value.removeprefix('library-error:'))
                if mutate=='truncated':changed['truncated']=True
                if mutate=='count':changed['debugBytes']+=1
                if mutate=='phase':changed['phase']='unknown'
                if mutate=='json-kind':changed['public']['serdeJsonError']=not changed['public']['serdeJsonError']
                if mutate=='permission-substitution':
                    changed['public']['serdeJsonError']=False
                    changed['debug']=changed['display']='HttpRequestDenied'
                    changed['debugBytes']=changed['displayBytes']=len('HttpRequestDenied')
                    changed['public']['sourceDisplay' if client=='golem' else 'typedWasiErrorCode']='HttpRequestDenied'
                    if expected=='error:request-denied':
                        changed['public']['sourceDisplay' if client=='golem' else 'typedWasiErrorCode']='InternalError(Some("latent-runtime-unavailable"))'
                if mutate=='json-kind' and expected in {'error:request-denied','error:reserved-header'}:continue
                with self.subTest(client=client,expected=expected,mutate=mutate),self.assertRaises(Exception):
                    node.library_error('library-error:'+json.dumps(changed),client,expected)
        opaque=payload('waki','body','stream failed','input_stream read failed: LastOperationFailed(Error { handle: 1 })')
        proof=node.library_error(opaque,'waki','error:response-size')
        self.assertFalse(proof['exactUnderlyingCategoryProven'])
        self.assertFalse(proof['nativeErrorInferredFromResourceHandle'])
        with self.assertRaises(Exception):node.library_error(opaque,'waki','error:timeout-option')

    def row(self,action=''):
        code={'trap':'guest-trap','cancel':'cancelled','deadline':'deadline-exceeded'}.get(action)
        revision={'releaseDigest':'controlled-original'}
        data={'resolvedRevision':revision,'consumption':{'outboundRequests':1,'effectCount':0,
            'cpuFuel':'10','peakMemoryBytes':'65536'}}
        response={'outcomeKnown':True,'requestDispatched':True,'data':data}
        row={'processReaped':True,'exitCode':0,'decoded':[{'ok':'fresh:waki:'+node.DOMAIN_TEXT}], 'response':response}
        if code:
            data['terminalState']=code.replace('-','_')
            response.update(category='platform-failure',error={'code':code})
            row.update(exitCode=4,decoded=None)
        spec=('name','json','/conformance/json',None if code else node.DOMAIN_TEXT,1,'domain-json',action)
        return row,spec,revision,{'cpuFuel':100,'memoryBytes':1048576}

    def test_result_is_the_real_rust_result_type_with_exact_current_revision_and_budget(self):
        row,spec,revision,budget=self.row()
        node.outcome(row,spec,'waki',revision,budget)
        mutations=[lambda v:v.update(decoded=['fresh:waki:'+node.DOMAIN_TEXT]),
            lambda v:v.update(decoded=[{'err':'transport error'}]),lambda v:v.update(processReaped=False),
            lambda v:v.update(exitCode=False),
            lambda v:v['response']['data']['consumption'].update(cpuFuel=True),
            lambda v:v['response']['data']['consumption'].update(peakMemoryBytes=65536.5),
            lambda v:v['response'].update(outcomeKnown=False),
            lambda v:v['response']['data'].update(resolvedRevision={}),
            lambda v:v['response']['data']['consumption'].update(outboundRequests=2),
            lambda v:v['response']['data']['consumption'].update(cpuFuel='101'),
            lambda v:v['response']['data']['consumption'].update(peakMemoryBytes='1048577')]
        for mutate in mutations:
            changed=copy.deepcopy(row);mutate(changed)
            with self.subTest(mutate=mutate),self.assertRaises(Exception):node.outcome(changed,spec,'waki',revision,budget)

    def test_root_cancel_deadline_and_trap_never_accept_successful_library_completion(self):
        for action in ('trap','cancel','deadline'):
            row,spec,revision,budget=self.row(action)
            node.outcome(row,spec,'waki',revision,budget)
            for code in ('success','socket-timeout','unavailable','resource-exhausted'):
                changed=copy.deepcopy(row);changed['response']['error']['code']=code
                with self.subTest(action=action,code=code),self.assertRaises(Exception):
                    node.outcome(changed,spec,'waki',revision,budget)

    def test_pending_requires_all_five_original_physical_owners_and_current_tenant_provider_work(self):
        physical={'inventory':{'topology':{'entries':[{'name':name,'activeCount':'1'} for name in node.PHYSICAL]}}}
        counts={'nodeUsage':{'unavailable':False,'counters':dict.fromkeys(node.ACTIVE_COUNTERS,'0')},
            'tenantUsage':{'unavailable':False,'counters':{'calls':'1','sessions':'1'}}}
        for name in ('broker_calls','pool_active_connections','pool_running_requests'):
            counts['nodeUsage']['counters'][name]='1'
        with patch.object(node,'sample',return_value=physical),patch.object(node,'usage',return_value=counts):
            self.assertIn('owners',node.positive_pending(None,None,None)['proof'])
            for name in node.PHYSICAL:
                changed=copy.deepcopy(physical)
                next(r for r in changed['inventory']['topology']['entries'] if r['name']==name)['activeCount']='0'
                with self.subTest(owner=name),patch.object(node,'sample',return_value=changed),self.assertRaises(Exception):
                    node.positive_pending(None,None,None)
            for key in ('calls','sessions'):
                changed=copy.deepcopy(counts);changed['tenantUsage']['counters'][key]='0'
                with self.subTest(owner=key),patch.object(node,'usage',return_value=changed),self.assertRaises(Exception):
                    node.positive_pending(None,None,None)

    def test_programme_remains_within_original_peer_and_per_activation_authority_limits(self):
        rows=node.cases()
        self.assertEqual(len(rows),25)
        self.assertEqual(len({r[0] for r in rows}),25)
        self.assertEqual(sum(r[4] for r in rows)+1+1,31) # original max32: queue holder and final fresh
        self.assertTrue(all(0<=r[4]<=8 for r in rows))
        for label in ('reserved-auth','reserved-cookie','foreign-target','timeout-option-unsupported'):
            row,=[r for r in rows if r[0]==label]
            self.assertEqual(row[4],0)
        for label,action in (('pending-cancel','cancel'),('pending-deadline','deadline'),('root-trap','trap')):
            self.assertEqual(next(r for r in rows if r[0]==label)[6],action)
        self.assertEqual(next(r for r in rows if r[0]=='uncertain-post')[4:6],(1,'commit-close'))

    def test_capacity_uses_actual_accepted_count_and_specific_error_without_naming_an_unobserved_owner(self):
        for client in ('waki','golem'):
            row,_spec,revision,budget=self.row()
            spec=next(r for r in node.cases() if r[0]=='resource-capacity')
            code='InternalError(Some("latent-runtime-resource-exhausted"))'
            public=({'typedWasiErrorCode':code,'serdeJsonError':False} if client=='waki' else {
                'isBuilder':False,'isRequest':True,'isBody':False,'isDecode':False,'isTimeout':False,
                'isStatus':False,'serdeJsonError':False,'sourceDisplay':code})
            error={'phase':'send','display':code,'debug':code,'displayBytes':len(code),'debugBytes':len(code),
                'truncated':False,'public':public}
            for accepted in (1,5,8):
                row['decoded']=[{'ok':f'fresh:{client}:capacity:{accepted}:library-error:'+json.dumps(error)}]
                row['response']['data']['consumption']['outboundRequests']=accepted
                proof=node.outcome(row,spec,client,revision,budget)
                self.assertEqual(proof['observedAcceptedResponses'],accepted)
                self.assertFalse(proof['limitingOwnerKindProven'])
                self.assertFalse(proof['taskExhaustionClaimed'])
            for mutate in ('zero','ninth','count','unavailable','permission','unsupported'):
                changed=copy.deepcopy(row);value=copy.deepcopy(error)
                if mutate in {'zero','ninth'}:
                    changed['decoded']=[{'ok':f'fresh:{client}:capacity:{0 if mutate=="zero" else 9}:library-error:'+json.dumps(value)}]
                elif mutate=='count':changed['response']['data']['consumption']['outboundRequests']=7
                else:
                    value['public']['typedWasiErrorCode' if client=='waki' else 'sourceDisplay']=mutate
                    changed['decoded']=[{'ok':f'fresh:{client}:capacity:8:library-error:'+json.dumps(value)}]
                with self.subTest(client=client,mutate=mutate),self.assertRaises(Exception):
                    node.outcome(changed,spec,client,revision,budget)

    def test_golem_transitive_timer_uses_original_closed_pending_not_preparation_or_elapsed_time(self):
        prefix=node.TIMER_PREFIX
        def record(event=b'wait-pending',counts=b'1|2|1',sequence=b'1',mode=b'pending'):
            return prefix+b'|'+mode+b'|'+event+b'|'+sequence+b'|'+counts+b'\n'
        proof=node.golem_timer_pending(record(),'pending')
        self.assertEqual(proof['waitPending']['tasks'],1)
        self.assertFalse(proof['nativeHookChanged'])
        self.assertFalse(proof['otherLanguageExecutionClaimed'])
        self.assertEqual(proof['originalReader'],'tools/dotnet_resource_timer_observer.py')
        for raw in (b'',record(b'start-accepted'),record(b'next-entered'),record()[:-1],
            record(counts=b'0|2|1'),record(counts=b'1|0|1'),record(counts=b'1|2|0')):
            self.assertIsNone(node.golem_timer_pending(raw,'pending'))
        for raw in (record(counts=b'9|2|1'),record(counts=b'1|17|1'),record(counts=b'1|2|9'),
            prefix+b'|overflow\n',record(sequence=b'2'),record()+record(),
            record()+record(b'root-close',sequence=b'2')):
            with self.subTest(raw=raw),self.assertRaises(Exception):node.golem_timer_pending(raw,'pending')
        self.assertIsNone(node.golem_timer_pending(record(mode=b'drain'),'pending'))

    def test_two_tenant_configuration_binds_only_three_exact_authorities_and_policy_ids(self):
        values={'workers':{'runtime':1,'control':1},'cells':[{'capacity':1,'queueCapacity':2}],
            'credentials':[{'tenant':'examples'}],'providers':{'formatVersion':1,'bindings':[],
                'httpStreaming':{'identity':{'id':'http-standard','tenant':'examples','service':'http-host','epoch':1},
                    'configuration':{'destinations':[]},'credentialDirectory':'unchanged',
                    'credentials':[{'file':'unchanged'}]},
                'activationRuntime':{'identity':{'id':'activation','tenant':'examples','service':'activation-host','epoch':1},
                    'limits':dict(node.RUNTIME_LIMITS)}}}
        for name,capability in (('clockMonotonic',node.CLOCK),('clockWall','unused-wall'),('random','unused-random')):
            values['providers'][name]={'identity':{'id':name,'tenant':'examples','service':'runtime-host','epoch':1}}
        for name,capability in (('http-standard',node.HTTP),('activation',node.ACTIVATION),
            ('clockMonotonic',node.CLOCK),('clockWall','unused-wall'),('random','unused-random')):
            values['providers']['bindings'].append({'name':name,'tenant':'examples','consumerService':'old',
                'providerService':('http-host' if name=='http-standard' else 'activation-host' if name=='activation' else 'runtime-host'),
                'contract':capability,'providerBinding':name+'-old'})
        peers={tenant:Mock() for tenant in node.TENANTS}
        for peer in peers.values():peer.provider_destinations.return_value=[{'controlled':'origin'}]
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            credentials={t:root/t/'authorization' for t in node.TENANTS}
            path=root/'config.json'
            for http_present in (True,False):
                path.write_bytes(canonical(values))
                with patch.object(node.shared,'configuration',return_value=path):
                    self.assertEqual(node.configuration(root,root,peers,credentials,http_present=http_present),path)
                import json
                actual=json.loads(path.read_bytes())['providers']
                expected={node.CLOCK,node.ACTIVATION}|({node.HTTP} if http_present else set())
                self.assertEqual({r['contract'] for r in actual['bindings']},expected)
                self.assertEqual(len(actual['bindings']),2*len(expected))
                self.assertEqual(actual['activationRuntime']['limits'],node.RUNTIME_LIMITS)
                self.assertEqual(len(actual['scalarAliases']),2)
                names={node.HTTP:'http-standard',node.CLOCK:'clockMonotonic',node.ACTIVATION:'activation'}
                for row in actual['bindings']:
                    self.assertEqual(row['consumerService'],node.SERVICE)
                    self.assertEqual(row['providerBinding'],names[row['contract']]+'-'+row['tenant']+'-installed')
                self.assertNotIn('clockWall',actual);self.assertNotIn('random',actual)
                self.assertEqual('httpStreaming' in actual,http_present)

    def test_neutral_deployment_never_changes_world_or_inherits_foreign_grants(self):
        original={'metadata':{'name':'unchanged'},'spec':{'service':node.SERVICE,'grants':[]}}
        result=node.deployment(original,'foreign')
        self.assertEqual(result['metadata'],{'name':'rust-http-foreign','tenant':'foreign'})
        self.assertEqual(result['spec'],original['spec'])
        self.assertEqual(original['metadata'],{'name':'unchanged'})
        for mutate in ({'tenant':None},{'tenant':'examples'}):
            value=copy.deepcopy(original);value['metadata'].update(mutate)
            with self.assertRaises(Exception):node.deployment(value,'foreign')


if __name__=='__main__':unittest.main()
