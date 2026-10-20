"""Closed configuration/publication boundaries for the real tenant programme."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import qualify_typescript_fetch_phases as phase
from tools import typescript_fetch_tenant_programme as tenants
from tools.guest_runtime_profiles import profiles
from tools.phase2_operator_process import WorkflowError
from tools.resource_tenant_node import TENANTS
from tools.typescript_guest.runtime_profile import scoped_selected_world


class FetchTenantTests(unittest.TestCase):
    def test_owned_cleanup_preserves_original_failure_and_reports_standalone_cleanup_failure(self):
        from contextlib import ExitStack
        calls=[];record={}
        def close():calls.append('closed');raise RuntimeError('cleanup')
        owner=SimpleNamespace(close=close)
        with self.assertRaisesRegex(ValueError,'original'):
            with ExitStack() as stack:
                tenants.register_cleanup(stack,owner,record,'peer')
                raise ValueError('original')
        self.assertEqual(calls,['closed']);self.assertEqual(record,{'cleanupRefusals':['peer']})
        with self.assertRaisesRegex(RuntimeError,'cleanup'):
            with ExitStack() as stack:tenants.register_cleanup(stack,owner,{},'peer')

    def test_signing_ancestry_preserves_original_compiler_materials_and_names_packaging_derivation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);original=root/'original';original.mkdir();signed=root/'signed';signed.mkdir()
            build={'source':{'revision':'original'},'componentDigest':'sha256:component','componentSize':123,
                'buildType':'original-compiler','materials':[{'name':'compiler','digest':'sha256:compiler','size':4},
                    {'name':'package-inputs','digest':'sha256:old-package','size':5}]}
            (original/'build-observation.json').write_text(json.dumps(build))
            identity=tenants.file_identity(original/'build-observation.json')
            derived=copy.deepcopy(build)
            derived['materials']=[build['materials'][0],
                {'name':'package-inputs','digest':'sha256:new-package','size':6},
                {'name':'resource-original-build-observation','digest':identity['sha256'],'size':identity['bytes']},
                {'name':'resource-neutral-package-source','digest':'sha256:package-source','size':7},
                {'name':'resource-neutral-derivation','digest':'sha256:derivation','size':8}]
            path=signed/'build-observation.json';path.write_text(json.dumps(derived))
            release={'componentDigest':build['componentDigest'],'observationDigest':tenants.file_identity(path)['sha256']}
            self.assertEqual(len(tenants.checked_signing(signed,original,release)['derivationMaterials']),3)
            for kind in ('compiler','source','inherited'):
                changed=copy.deepcopy(derived)
                if kind=='compiler':changed['materials'][0]['digest']='sha256:changed'
                elif kind=='source':changed['source']['revision']='changed'
                else:changed['materials'][2]['digest']='sha256:changed'
                path.write_text(json.dumps(changed))
                selected={**release,'observationDigest':tenants.file_identity(path)['sha256']}
                with self.subTest(kind=kind),self.assertRaises(WorkflowError):tenants.checked_signing(signed,original,selected)

    def fixture(self, root):
        signed = root/'signed';signed.mkdir();(signed/'policy.json').write_text('{}')
        credentials, startups = {}, {}
        for index,tenant in enumerate(TENANTS):
            directory=root/tenant;directory.mkdir()
            credentials[tenant]=directory/'authorization'
            credentials[tenant].write_bytes(b'Bearer '+bytes([ord('a')+index])*64)
            startups[tenant]={'destinations':[{'identity':tenant}],
                'origins':{'primary':{'scheme':'http','host':'127.0.0.1','port':32000+index}}}
        node=root/'node';node.mkdir()
        return node,signed,startups,credentials

    def test_configuration_retains_original_limits_and_independent_http_scopes_and_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);node,signed,startups,credentials=self.fixture(root)
            other=root/'original';other.mkdir()
            original_path,original_owner=phase.configuration(other,signed,startups['examples'],credentials['examples'])
            original=json.loads(original_path.read_bytes())
            path,owner=tenants.configure(phase.configuration,node,signed,startups,credentials)
            actual=json.loads(path.read_bytes())
            self.assertEqual(owner,original_owner)
            for key in ('workers','cells','execution','cache','budgetProfile','capabilityPolicies','shutdownGraceMillis'):
                self.assertEqual(actual[key],original[key],key)
            self.assertEqual(actual['providers']['httpStreaming'],original['providers']['httpStreaming'])
            second,=actual['providers']['additionalHttpStreaming']
            self.assertEqual(second['identity'],{'id':'http-standard-foreign','tenant':'foreign','service':'foreign-http','epoch':1})
            self.assertEqual(second['configuration']['destinations'],startups['foreign']['destinations'])
            self.assertEqual(second['credentialDirectory'],str(credentials['foreign'].parent))
            self.assertNotEqual(second['credentialDirectory'],original['providers']['httpStreaming']['credentialDirectory'])
            self.assertEqual(second['configuration']['limits'],original['providers']['httpStreaming']['configuration']['limits'])
            self.assertEqual(second['limits'],original['providers']['httpStreaming']['limits'])
            self.assertEqual({a['source'] for a in actual['providers']['scalarAliases']},{*profiles('java'),'activation'})
            self.assertTrue(all(b['consumerService']==tenants.SERVICE for b in actual['providers']['bindings']))
            self.assertEqual(len([b for b in actual['providers']['bindings'] if b['contract']==tenants.fixture.HTTP]),2)

    def test_changed_cell_capacity_refuses_before_any_tenant_configuration_is_returned(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);node,signed,startups,credentials=self.fixture(root)
            def changed(*arguments):
                path,owner=phase.configuration(*arguments)
                value=json.loads(path.read_bytes());value['cells'][0]['capacity']=2
                path.write_text(json.dumps(value));return path,owner
            with self.assertRaisesRegex(WorkflowError,'original-single-cell'):
                tenants.configure(changed,node,signed,startups,credentials)

    def test_foreign_grants_bind_only_original_foreign_descriptors_and_destination(self):
        rows=[]
        for name,values in profiles('java').items():
            capability,profile,_,_=values
            rows.append({'id':name+'-foreign','tenant':'foreign','capability':capability,
                         'profile':profile,'configurationEpoch':'1','configurationDigest':'sha256:'+name})
        rows.extend([{'id':'activation-foreign','tenant':'foreign','capability':tenants.base.ACTIVATION,
            'profile':'activation-owned-v1','configurationEpoch':'1','configurationDigest':'sha256:activation'},
            {'id':'http-standard-foreign','tenant':'foreign','capability':tenants.fixture.HTTP,
             'profile':'bounded-streaming-http-phase-timing-v1','configurationEpoch':'1','configurationDigest':'sha256:http'}])
        node=SimpleNamespace(startup_record={'providers':rows})
        origin={'scheme':'http','host':'127.0.0.1','port':32001}
        documents=[]
        with patch.object(tenants,'policy',side_effect=lambda client,kind,name,document:documents.append((kind,name,document))):
            selected=tenants.grants(object(),node,'foreign-publication','foreign',origin)
        self.assertEqual(len(selected),4)
        self.assertTrue(all(d['tenant']=='foreign' for _,_,d in documents))
        bindings=[d for kind,_,d in documents if kind=='provider-binding']
        self.assertEqual({d['configurationDigest'] for d in bindings},{r['configurationDigest'] for r in rows})
        policies=[d for kind,_,d in documents if kind=='policy']
        self.assertTrue(all(d['rules'][0]['publications']==['foreign-publication'] for d in policies))
        http,=[d['rules'][0] for d in policies if d['rules'][0]['capability']==tenants.fixture.HTTP]
        self.assertEqual(http['resources']['origins'],[origin]);self.assertEqual(http['resources']['methods'],['GET'])
        self.assertEqual(http['principals'],[{'kind':'administrator','subject':tenants.SUBJECTS['foreign']}])
        broken=copy.deepcopy(rows);broken[0]['tenant']='examples'
        with patch.object(tenants,'policy') as sent, self.assertRaisesRegex(WorkflowError,'exact-scoped-installation'):
            tenants.grants(object(),SimpleNamespace(startup_record={'providers':broken}),'foreign-publication','foreign',origin)
        sent.assert_not_called()

    def test_neutral_packaging_keeps_original_component_world_exports_and_no_inherited_grants(self):
        digest='sha256:'+'a'*64
        world=scoped_selected_world('examples:typescript-fetch/service@1.0.0')
        capsule={'metadata':{'name':'examples/typescript-fetch','tenant':'examples'},
            'exports':['examples:typescript-fetch/api@1.0.0'],'component':{'world':world,'digest':digest}}
        release={'name':'typescript-fetch','service':'typescript-fetch','world':world,'componentDigest':digest}
        original={'component':{'sha256':digest}}
        tenants.checked_release(release,capsule,original)
        for field in ('world','componentDigest','service','name'):
            changed={**release,field:'changed'}
            with self.subTest(field=field),self.assertRaisesRegex(WorkflowError,'original-component-world'):
                tenants.checked_release(changed,capsule,original)
        deployment={'metadata':{'name':'typescript-fetch'},'spec':{'service':'typescript-fetch','grants':[]}}
        selected=tenants.scoped_deployment(deployment,'foreign')
        self.assertEqual(selected['metadata']['tenant'],'foreign');self.assertEqual(selected['spec']['grants'],[])
        self.assertNotIn('tenant',deployment['metadata'])
        for changed in ({**deployment,'metadata':{'tenant':'examples'}},
                        {**deployment,'spec':{**deployment['spec'],'grants':[{'capability':'foreign'}]}}):
            with self.assertRaisesRegex(WorkflowError,'original-neutral-deployment'):
                tenants.scoped_deployment(changed,'foreign')
