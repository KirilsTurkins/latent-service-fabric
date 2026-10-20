"""Closed same-node Java HTTP programme boundaries; no native execution here."""
import copy
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import java_http_tenant_node as tenants
from tools.guest_runtime_profiles import profiles
from tools.phase2_operator_process import WorkflowError


class JavaHttpTenantTests(unittest.TestCase):
    def test_configuration_keeps_original_caps_and_installs_independent_http_and_scalar_scopes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);signed = root/'signed';signed.mkdir();(signed/'policy.json').write_text('{}')
            peers, credentials = {}, {}
            for index, tenant in enumerate(tenants.TENANTS):
                directory = root/tenant;directory.mkdir();credentials[tenant] = directory/'authorization'
                credentials[tenant].write_bytes(b'Bearer synthetic-'+tenant.encode())
                origin = {'scheme':'http','host':'127.0.0.1','port':32000+index}
                destinations = [{'origin':origin,'addresses':{'networks':['127.0.0.1/32'],
                    'specialAddresses':['127.0.0.1']},'resolution':{'kind':'static','addresses':['127.0.0.1']},
                    'allowedRequestHeaders':['accept','user-agent','x-conformance'],'redirectDestinations':[]}]
                peers[tenant] = SimpleNamespace(provider_destinations=lambda rows=destinations:copy.deepcopy(rows))
            original_dir = root/'original';original_dir.mkdir();node = root/'node';node.mkdir()
            path = tenants.phase.configuration(original_dir,signed,peers['examples'],credentials['examples'],[])
            original = json.loads(path.read_bytes())
            actual = json.loads(tenants.configuration(node,signed,peers,credentials).read_bytes())
            for key in ('workers','cells','execution','cache','budgetProfile','capabilityPolicies','shutdownGraceMillis'):
                self.assertEqual(actual[key],original[key],key)
            self.assertEqual(actual['providers']['httpStreaming'],original['providers']['httpStreaming'])
            second, = actual['providers']['additionalHttpStreaming']
            self.assertEqual(second['identity'],{'id':'http-standard-foreign','tenant':'foreign','service':'foreign-http','epoch':1})
            self.assertEqual(second['configuration']['destinations'],peers['foreign'].provider_destinations())
            for key in ('limits','credentials'):
                self.assertEqual(second[key],original['providers']['httpStreaming'][key])
            self.assertEqual(second['credentialDirectory'],str(credentials['foreign'].parent))
            self.assertNotEqual(second['credentialDirectory'],original['providers']['httpStreaming']['credentialDirectory'])
            self.assertEqual(second['configuration']['limits'],original['providers']['httpStreaming']['configuration']['limits'])
            aliases = actual['providers']['scalarAliases']
            self.assertEqual({row['source'] for row in aliases},{*profiles('java'),'activation'})
            self.assertTrue(all(row['identity']['tenant']=='foreign' for row in aliases))
            self.assertTrue(all(row['consumerService']==tenants.SERVICE for row in actual['providers']['bindings']))
            self.assertEqual(len([row for row in actual['providers']['bindings'] if row['contract']==tenants.phase.CAPABILITY]),2)

    def test_changed_single_cell_or_preexisting_additional_installation_is_refused(self):
        for change in ('capacity','extra'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary);node=root/'node';node.mkdir();signed=root/'signed';signed.mkdir()
                (signed/'policy.json').write_text('{}');credential=root/'authorization';credential.write_bytes(b'Bearer synthetic')
                peers={name:SimpleNamespace(provider_destinations=lambda:[]) for name in tenants.TENANTS}
                def changed(*arguments):
                    path=tenants.phase.configuration(*arguments);value=json.loads(path.read_bytes())
                    if change=='capacity':value['cells'][0]['capacity']=2
                    else:value['providers']['additionalHttpStreaming']=[{'unexpected':True}]
                    path.write_text(json.dumps(value));return path
                with self.assertRaises(WorkflowError):
                    tenants.configuration(node,signed,peers,{name:credential for name in tenants.TENANTS},factory=changed)

    def test_foreign_grants_require_all_exact_descriptors_before_any_policy_mutation(self):
        rows=[]
        for name,(capability,profile,_,_) in profiles('java').items():
            rows.append({'id':name+'-foreign','tenant':'foreign','service':'foreign-runtime',
                'capability':capability,'profile':profile,'configurationEpoch':'1','configurationDigest':'sha256:'+name})
        rows.extend([{'id':'activation-foreign','tenant':'foreign','service':'foreign-activation',
            'capability':tenants.phase.ACTIVATION,'profile':'activation-owned-v1','configurationEpoch':'1',
            'configurationDigest':'sha256:activation'},
            {'id':'http-standard-foreign','tenant':'foreign','service':'foreign-http','capability':tenants.phase.CAPABILITY,
            'profile':tenants.phase.PROFILE,'configurationEpoch':'1','configurationDigest':'sha256:http'}])
        origin={'scheme':'http','host':'127.0.0.1','port':32001};documents=[]
        with patch.object(tenants,'policy',side_effect=lambda client,kind,name,value:documents.append((kind,name,value))):
            grants=tenants.grants(object(),SimpleNamespace(startup_record={'providers':rows}),'foreign-publication','foreign',origin)
        self.assertEqual(len(grants),4)
        self.assertTrue(all(row['tenant']=='foreign' for _,_,row in documents))
        policies=[row['rules'][0] for kind,_,row in documents if kind=='policy']
        self.assertTrue(all(row['services']==[tenants.SERVICE] and row['publications']==['foreign-publication']
            and row['principals']==[{'kind':'administrator','subject':tenants.SUBJECTS['foreign']}] for row in policies))
        http,=[row for row in policies if row['capability']==tenants.phase.CAPABILITY]
        self.assertEqual(http['resources'],{'kind':'http','origins':[origin],'methods':['GET'],
            'paths':['/conformance/json','/conformance/hold/headers'],'pathPrefixes':[]})
        self.assertEqual(http['ceiling'],{'operations':64,'inputBytes':65536,'outputBytes':262144,'wallTimeMillis':5000})
        for index in range(len(rows)):
            for field in ('tenant','service','capability','profile','configurationEpoch'):
                broken=copy.deepcopy(rows);broken[index][field]='changed'
                with self.subTest(index=index,field=field),patch.object(tenants,'policy') as mutate:
                    with self.assertRaisesRegex(WorkflowError,'exact-scoped-installation'):
                        tenants.grants(object(),SimpleNamespace(startup_record={'providers':broken}),'foreign-publication','foreign',origin)
                    mutate.assert_not_called()

    def test_neutral_signing_keeps_actual_component_and_all_original_compiler_materials(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);artifact=root/'artifact';artifact.mkdir();signed=root/'signed';signed.mkdir()
            component=b'original-component';(artifact/'component.wasm').write_bytes(component)
            identity=tenants.file_identity(artifact/'component.wasm')
            capsule={'metadata':{'name':'examples/java-standard-http','tenant':'examples'},
                'exports':['examples:java-standard-http/api@1.0.0'],
                'component':{'world':'examples:java-standard-http/service@1.0.0','digest':identity['sha256']}}
            (artifact/'capsule.json').write_text(json.dumps(capsule))
            before={'source':{'revision':'source'},'parameters':{'profile':'selected'},'componentDigest':identity['sha256'],
                'componentSize':identity['bytes'],'buildType':'actual-compiler','materials':[
                {'name':'compiler','digest':'sha256:compiler','size':5},
                {'name':'package-inputs','digest':'sha256:package','size':6}]}
            (artifact/'build-observation.json').write_text(json.dumps(before))
            original={name:tenants.file_identity(artifact/name) for name in ('component.wasm','build-observation.json')}
            observed=copy.deepcopy(before);observed.update(hermetic=False,reproducibility='not-checked')
            observed['materials']=[before['materials'][0],{'name':'package-inputs','digest':'sha256:new-package','size':7},
                {'name':'resource-original-build-observation','digest':original['build-observation.json']['sha256'],
                 'size':original['build-observation.json']['bytes']},
                {'name':'resource-neutral-package-source','digest':'sha256:neutral-package','size':8},
                {'name':'resource-neutral-derivation','digest':'sha256:derivation','size':9}]
            path=signed/'build-observation.json';path.write_text(json.dumps(observed))
            release={'name':'java-standard-http','service':'java-standard-http','world':capsule['component']['world'],
                'componentDigest':identity['sha256'],'observationDigest':tenants.file_identity(path)['sha256']}
            record={'schemaVersion':'latent.capsule.demo.v1','tenants':list(tenants.TENANTS),'packagingOnly':True,
                'componentCompilationPerformed':False,'trust':'isolated-neutral-resource-two-tenant-test-only',
                'inheritedCompilerObservationAsset':'resource-original-build-observation.json',
                'expiresAtUnixSeconds':10**12,'releases':[release]}
            self.assertEqual(len(tenants.checked_signing(signed,artifact,record,original)['derivationMaterials']),3)
            for field in ('schemaVersion','inheritedCompilerObservationAsset','packagingOnly','componentCompilationPerformed'):
                changed=copy.deepcopy(record);changed[field]='changed'
                with self.subTest(field=field),self.assertRaises(WorkflowError):
                    tenants.checked_signing(signed,artifact,changed,original)
            for change in ('source','parameters','compiler','inherited','component'):
                mutated=copy.deepcopy(observed)
                if change in ('source','parameters'):mutated[change]={'changed':True}
                elif change=='component':mutated['componentDigest']='sha256:changed'
                else:mutated['materials'][0 if change=='compiler' else 2]['digest']='sha256:changed'
                path.write_text(json.dumps(mutated));current=copy.deepcopy(record)
                current['releases'][0]['observationDigest']=tenants.file_identity(path)['sha256']
                with self.subTest(change=change),self.assertRaises(WorkflowError):
                    tenants.checked_signing(signed,artifact,current,original)

    def test_neutral_deployment_never_inherits_tenant_or_grants_and_keeps_original_immutable(self):
        original={'metadata':{'name':'java-standard-http'},'spec':{'service':tenants.SERVICE,'grants':[]}}
        before=copy.deepcopy(original)
        actual=tenants.scoped_deployment(original,'foreign')
        self.assertEqual(actual['metadata'],{'name':'java-http-foreign','tenant':'foreign'})
        self.assertEqual(original,before);self.assertEqual(actual['spec']['grants'],[])
        for changed in ({**original,'metadata':{'tenant':'examples'}},
                {**original,'spec':{**original['spec'],'grants':[{'capability':'inherited'}]}},
                {**original,'spec':{**original['spec'],'service':'examples/java-standard-http'}}):
            with self.assertRaises(WorkflowError):tenants.scoped_deployment(changed,'foreign')
        with self.assertRaises(WorkflowError):tenants.scoped_deployment(original,'unselected')

    def test_result_guard_distinguishes_root_cancellation_phase_timeout_and_uncaught_origin_refusal(self):
        revision={'releaseDigest':'sha256:component','generation':'1'}
        def result(mode):
            terminal=mode==5
            return {'processReaped':True,'exitCode':4 if terminal else 0,'decoded':None if terminal else [tenants.phase.expected(mode)],
                'response':{'outcomeKnown':True,'category':'platform-failure' if terminal else 'success',
                'error':{'code':'cancelled'} if terminal else None,'data':{'resolvedRevision':revision,
                'terminalState':'cancelled' if terminal else 'completed','consumption':{'cpuFuel':'10','outboundRequests':'1'}}}}
        for mode in (0,2,5,6,10):tenants.validate_result(result(mode),revision,mode)
        wrong=result(5);wrong['response']['error']['code']='deadline-exceeded'
        with self.assertRaises(WorkflowError):tenants.validate_result(wrong,revision,5)
        refused=result(6);refused.update(exitCode=4,decoded=None)
        refused['response'].update(category='platform-failure',error={'code':'guest-trap'})
        refused['response']['data']['consumption']['outboundRequests']='0'
        tenants.validate_result(refused,revision,6,denied_origin=True)
        for field,value in (('outboundRequests','1'),('cpuFuel','0')):
            changed=copy.deepcopy(refused);changed['response']['data']['consumption'][field]=value
            with self.assertRaises(WorkflowError):tenants.validate_result(changed,revision,6,denied_origin=True)
        changed=copy.deepcopy(refused);changed['response']['data']['resolvedRevision']={}
        with self.assertRaises(WorkflowError):tenants.validate_result(changed,revision,6,denied_origin=True)

    def test_cleanup_preserves_original_exception_identity_and_refuses_standalone_cleanup_failure(self):
        original=ValueError('original');cleanup=RuntimeError('cleanup');record={}
        owner=SimpleNamespace(close=Mock(side_effect=cleanup))
        with self.assertRaises(ValueError) as raised:
            with ExitStack() as stack:
                tenants.cleanup_owner(stack,owner,record,'node')
                raise original
        self.assertIs(raised.exception,original);self.assertEqual(record,{'cleanupRefusals':['node']})
        with self.assertRaises(RuntimeError) as raised:
            with ExitStack() as stack:tenants.cleanup_owner(stack,owner,{},'node')
        self.assertIs(raised.exception,cleanup)

    def test_startup_failure_preserves_primary_cause_and_writes_closed_failed_stage_despite_cleanup_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);artifact=root/'artifact';artifact.mkdir()
            for name in tenants.ORIGINALS:(artifact/name).write_bytes(b'original')
            native={name:root/name for name in ('latent','latentd','capsule_authoring')}
            for path in native.values():path.write_bytes(b'original-native')
            output=root/'output';original=RuntimeError('original-startup')
            def sign(argv,*args,**kwargs):
                signed=Path(argv[2]);signed.mkdir();(signed/'release-set.json').write_text('{}')
                return SimpleNamespace(returncode=0)
            def configure(directory,*arguments):
                path=directory/'node.json';path.write_text('{}');return path
            class BrokenPeer:
                def __init__(self,*args,**kwargs):pass
                def close(self):raise RuntimeError('cleanup-only')
            with patch.object(tenants,'run_bounded_result',side_effect=sign),\
                    patch.object(tenants,'checked_signing',return_value={}),\
                    patch.object(tenants,'configuration',side_effect=configure),\
                    patch.object(tenants,'RecordingClient',return_value=object()),\
                    patch.object(tenants,'Peer',BrokenPeer),\
                    patch.object(tenants,'connect',side_effect=original):
                with self.assertRaises(RuntimeError) as raised:
                    tenants.run(artifact,native,output,deadline=10**12)
            self.assertIs(raised.exception,original)
            failed=json.loads((output/'FAILED.json').read_bytes())
            self.assertEqual(failed['stage'],'same-node-startup')
            self.assertEqual(failed['cleanupRefusals'],['peer','peer'])
            self.assertFalse(failed['componentCompilationPerformed'])
            self.assertNotIn('original-startup',json.dumps(failed))
