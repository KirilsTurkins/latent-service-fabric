"""Source, authority and real peer-oracle controls; not signed guest evidence."""
import copy
from contextlib import closing
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from tools import go_http_tenant_fixture as fixture, go_http_tenant_node as node
from tools.go_standard_http_node import configuration
from tools.phase2_operator_process import WorkflowError
from tools.qualify_go_http_tenants import CONSUMER_NATIVE, NATIVE_TEST_ONLY, validate_native_delta
from tools.rust_capsule_project import ROOT
from tools.standard_http.peer import Peer


class GoHttpTenantControls(unittest.TestCase):
    def test_published_clients_and_transitive_worker_remain_exact_original_source(self):
        source = (ROOT/fixture.LIBRARY_SOURCE).read_bytes()
        derived = fixture.derive(source)
        self.assertEqual(derived.replace(fixture.DISPATCH,b''),source)
        self.assertEqual(derived.count(fixture.DISPATCH),1)
        self.assertLess(derived.index(b'private.Marker()'),derived.index(fixture.DISPATCH))
        self.assertLess(derived.index(fixture.DISPATCH),derived.index(b'client := sling.New()'))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app,library = fixture.project(root/'application',root/'private','outside.example.test/http-library/tenant-control')
            self.assertEqual((app/'src/main.go').read_bytes(),derived.replace(
                b'@private-module@',b'outside.example.test/http-library/tenant-control'))
            self.assertEqual((app/'src/tenant.go').read_bytes(),(ROOT/fixture.CONTROL_SOURCE).read_bytes())
            self.assertIn(b'go func()', (library/'marker.go').read_bytes())
            self.assertIn(b'//go:embed marker.txt', (library/'marker.go').read_bytes())
            self.assertEqual(json.loads((app/'capsule-project.json').read_bytes())['runtimeProfile'],
                'go-component-activation-v4')

    def test_changed_or_duplicated_original_dispatch_anchor_is_refused(self):
        source = (ROOT/fixture.LIBRARY_SOURCE).read_bytes()
        for changed in (source.replace(fixture.ANCHOR,b''),source+fixture.ANCHOR,fixture.derive(source)):
            with self.subTest(changed=len(changed)),self.assertRaises(ValueError):fixture.derive(changed)

    def configured(self):
        temporary = tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root = Path(temporary.name);releases = root/'releases';releases.mkdir()
        (root/'node').mkdir()
        (releases/'policy.json').write_bytes(b'{}')
        startups = {};credentials = {}
        for number,tenant in enumerate(node.TENANTS):
            origin = {'scheme':'http','host':'127.0.0.1','port':18001+number}
            startups[tenant] = {'origins':{'primary':origin},'destinations':[{'origin':origin,
                'allowedRequestHeaders':['accept','user-agent','x-conformance']}]}
            credentials[tenant] = root/tenant/'authorization'
        original = json.loads(configuration(root/'node',releases,startups['examples'],credentials['examples']).read_bytes())
        return original,startups,credentials

    def test_independent_http_installations_preserve_all_original_bounds_and_shared_cell(self):
        original,startups,credentials = self.configured();before = copy.deepcopy(original)
        selected = node.settings(original,startups,credentials)
        self.assertEqual(original,before)
        for key in original.keys()-{'providers','credentials'}:self.assertEqual(selected[key],original[key])
        self.assertEqual(selected['providers']['activationRuntime'],original['providers']['activationRuntime'])
        self.assertEqual(selected['providers']['activationRuntime']['limits'],node.RUNTIME_LIMITS)
        providers = [selected['providers']['httpStreaming'],*selected['providers']['additionalHttpStreaming']]
        for tenant,provider in zip(node.TENANTS,providers,strict=True):
            self.assertEqual(provider['identity']['tenant'],tenant)
            self.assertEqual(provider['identity']['service'],'http-'+tenant)
            self.assertEqual(provider['configuration']['destinations'],startups[tenant]['destinations'])
            self.assertEqual(provider['credentialDirectory'],str(credentials[tenant].parent))
            self.assertEqual(provider['limits'],original['providers']['httpStreaming']['limits'])
        self.assertEqual(len(selected['providers']['bindings']),10)
        self.assertEqual(len(selected['providers']['scalarAliases']),4)
        self.assertTrue(all(row['source'] != 'httpStreaming' for row in selected['providers']['scalarAliases']))
        installed_ids = {selected['providers'][name]['identity']['id'] for name in (*node.RUNTIME,'activationRuntime')}
        self.assertEqual({row['source'] for row in selected['providers']['scalarAliases']},installed_ids)

    def test_runtime_limit_increase_or_another_cell_cannot_enter_isolation_programme(self):
        original,startups,credentials = self.configured()
        mutations = [copy.deepcopy(original),copy.deepcopy(original)]
        mutations[0]['providers']['activationRuntime']['limits']['tasks'] = 16
        mutations[1]['cells'].append(copy.deepcopy(original['cells'][0]))
        for changed in mutations:
            with self.assertRaises(WorkflowError):node.settings(changed,startups,credentials)

    def test_neutral_component_gets_distinct_real_tenant_objects_and_cannot_inherit_grants(self):
        original = {'metadata':{'name':'go-standard-http'},'spec':{'service':node.SERVICE,'grants':[]}}
        first,second = (node.deployment(original,tenant) for tenant in node.TENANTS)
        self.assertNotEqual(first['metadata']['name'],second['metadata']['name'])
        self.assertEqual([first['metadata']['tenant'],second['metadata']['tenant']],list(node.TENANTS))
        self.assertEqual(original['metadata'],{'name':'go-standard-http'})
        scoped = copy.deepcopy(original);scoped['metadata']['tenant'] = 'examples'
        granted = copy.deepcopy(original);granted['spec']['grants'] = [{'policy':'foreign'}]
        for changed in (scoped,granted):
            with self.assertRaises(WorkflowError):node.deployment(changed,'foreign')

    def test_each_grant_binds_real_tenant_publication_subject_profile_and_origin(self):
        from types import SimpleNamespace
        descriptors = []
        for tenant in node.TENANTS:
            for name,(capability,profile,_operation,_kind) in node.RUNTIME.items():
                descriptors.append({'id':name+('-foreign' if tenant == 'foreign' else ''),'tenant':tenant,
                    'capability':capability,'profile':profile,'configurationEpoch':'1','configurationDigest':'digest-'+tenant})
            descriptors += [{'id':'activation'+('-foreign' if tenant == 'foreign' else ''),'tenant':tenant,
                'capability':node.original.ACTIVATION,'profile':'activation-v1','configurationEpoch':'1','configurationDigest':'activation-'+tenant},
                {'id':'http-'+tenant,'tenant':tenant,'capability':node.original.CAPABILITY,
                'profile':'bounded-streaming-http-identity-v1','configurationEpoch':'1','configurationDigest':'http-'+tenant}]
        for tenant in node.TENANTS:
            origin = {'scheme':'http','host':'127.0.0.1','port':19001 if tenant == 'examples' else 19002}
            with patch.object(node,'policy') as applied:
                runtime,all_grants = node.grant('client',SimpleNamespace(startup_record={'providers':descriptors}),
                    'publication-'+tenant,tenant,origin)
            self.assertEqual(len(runtime),4);self.assertEqual(len(all_grants),5)
            documents = [row.args[3] for row in applied.call_args_list if row.args[1] == 'policy']
            self.assertEqual(len(documents),5)
            for document in documents:
                self.assertEqual(document['tenant'],tenant)
                rule, = document['rules']
                self.assertEqual(rule['principals'],[{'kind':'administrator','subject':node.SUBJECTS[tenant]}])
                self.assertEqual(rule['services'],[node.SERVICE])
                self.assertEqual(rule['publications'],['publication-'+tenant])
            self.assertEqual(documents[-1]['rules'][0]['resources']['origins'],[origin])
            self.assertEqual(documents[-1]['rules'][0]['ceiling'],node.CEILING)

    def test_neutral_service_and_original_typed_export_are_used_without_global_rebinding(self):
        with patch.object(node,'call',return_value='row') as called:
            self.assertEqual(node.invoke('client',{'service':node.SERVICE},300,'http://owned','label'),'row')
        self.assertEqual(called.call_args.args,('client',{'service':node.SERVICE},'go-standard-http','run',[300,'http://owned'],'label'))
        self.assertEqual(node.original.SERVICE,'examples/go-standard-http')

    def test_closed_native_compatibility_refuses_any_product_change_or_extra_test(self):
        self.assertEqual(CONSUMER_NATIVE,'0c31349294b74da6620f67994f1e21fba58c3454')
        validate_native_delta(sorted(NATIVE_TEST_ONLY))
        for changed in ([],sorted(NATIVE_TEST_ONLY)*2,sorted(NATIVE_TEST_ONLY)+['crates/latent-http/src/lib.rs'],
                ['crates/latent-wasmtime/tests/new.rs']):
            with self.assertRaises(WorkflowError):validate_native_delta(changed)

    def test_programme_requires_delegated_authority_refusals_and_both_cross_tenant_retirement_directions(self):
        cases = node.cases()
        self.assertEqual(len(cases),19)
        self.assertEqual(sum(row[5] for row in cases),15)
        for tenant in node.TENANTS:
            selected = {name:(which,path,expected,contacts) for who,name,which,path,expected,contacts in cases if who == tenant}
            self.assertEqual(selected['delegating-extension'][0],300)
            self.assertEqual(selected['delegating-extension'][3],1)
            self.assertEqual(selected['delegating-origin-denied'],(300,
                'foreign' if tenant == 'examples' else 'examples','delegated-transport-error:1',0))
            self.assertEqual(selected['trap-pending'],(302,'/conformance/body/partial',None,1))
            self.assertEqual(selected['return-pending'],(301,'/conformance/body/partial','root-returned-with-pending-body',1))
            self.assertIn('requests-after-other-trap',selected)
            self.assertIn('sling-after-other-return',selected)
        source = (ROOT/fixture.CONTROL_SOURCE).read_text()
        self.assertIn('http.DefaultTransport.RoundTrip(request)',source)
        self.assertNotIn('time.',source)
        self.assertNotIn('cancel()',source)

    def test_captured_build_preserves_normal_go_bubblewrap_namespace_prerequisite(self):
        from tools.ci_lane_inventory import workflow_model
        original = workflow_model((ROOT/'.github/workflows/go-guest.yml').read_text())
        maintained = next(step['run'] for job in original['jobs'].values() for step in job['steps']
            if step.get('name') == 'Install captured Go compiler namespace')
        selected = workflow_model((ROOT/'.github/workflows/go-http-tenant-catalogue.yml').read_text())
        steps = selected['jobs']['tenants']['steps']
        namespace = [(index,step) for index,step in enumerate(steps)
            if step.get('name') == 'Install captured Go compiler namespace']
        self.assertEqual(len(namespace),1)
        index,step = namespace[0]
        self.assertEqual(step['run'],maintained)
        compile_index = next(i for i,row in enumerate(steps) if 'tools/qualify_go_http_tenants.py' in row.get('run',''))
        self.assertLess(index,compile_index)

    def test_real_controlled_peer_oracle_requires_exact_contacts_authority_and_unreleased_body_gates(self):
        token = b'Bearer '+b'0'*64
        for tenant in node.TENANTS:
            with closing(Peer(token,maximum_seconds=300)) as peer:
                for who,_name,mode,path,_expected,contacts in node.cases():
                    if who != tenant or not contacts:continue
                    stream = socket.create_connection(('127.0.0.1',peer.origin()['port']),timeout=2)
                    try:
                        method = 'POST' if mode in (1,101) else 'GET'
                        body = b'\x00\x01\x02\x03' if method == 'POST' else b''
                        raw = (f'{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{peer.origin()["port"]}\r\n'
                            'Authorization: '+token.decode()+'\r\nConnection: close\r\n'+
                            (f'Content-Length: {len(body)}\r\nContent-Type: application/octet-stream\r\n' if body else '')+'\r\n').encode()+body
                        stream.sendall(raw)
                        for _ in range(32):
                            peer.poll(.01)
                            if peer.rows and peer.rows[-1]['state'] in {'closed','held-body'}:break
                        self.assertIn(peer.rows[-1]['state'],{'closed','held-body'})
                    finally:stream.close()
                    for _ in range(32):
                        peer.poll(.01)
                        if peer.rows[-1]['state'] == 'closed':break
                value = peer.close()
            node.peer_outcome(value,tenant)
            for change in ('authority','contact','gate'):
                altered = copy.deepcopy(value)
                if change == 'authority':altered['requests'][0]['authorizationPresent'] = False
                elif change == 'contact':altered['startedRequests'] += 1
                else:
                    gate = next(row for row in altered['events'] if row['kind'] == 'gate-pending')
                    gate['kind'] = 'gate-released'
                with self.subTest(tenant=tenant,change=change),self.assertRaises((WorkflowError,ValueError)):
                    node.peer_outcome(altered,tenant)


class FutureGoHttpNativeTests(unittest.TestCase):
    def test_future_tuple_is_separate_and_current_source_exact_without_relabelling_actual_1ad(self):
        from tools import wait_runtime_native_products as future
        from tools import qualify_go_http_tenants as q
        from tools.java_replay_materials import git_source_identity
        from tools.phase3_resource_identity import source_identity
        self.assertEqual(future.SOURCE,'f9192fb5785ca7bed8b33dbb869b3d775b72ab4b')
        self.assertEqual(q.SOURCE,'6f5f180136d140ac670561695260f71514781015')
        historical = git_source_identity(future.SOURCE)
        current = source_identity(q.ROOT)
        proof={'compiledSource':future.SOURCE,'signedQualification':False}
        auxiliary={'wit/host-abi-phase3-v7.json':q.file_identity(q.ROOT/'wit/host-abi-phase3-v7.json')}
        with patch.object(future,'verify_prepared',return_value=proof), \
                patch.object(future.READER,'_git_materials',return_value=auxiliary), \
                patch.object(q,'source_identity',return_value=historical):
            result=q.future_native_compatibility(Path('prepared'))
            self.assertEqual(result['compiledSource'],future.SOURCE)
            self.assertEqual(result['reviewedUncompiledTestDelta'],[])
            if current != historical:
                with patch.object(q,'source_identity',return_value=current), \
                        self.assertRaisesRegex(WorkflowError,'future-native-source-drift'):
                    q.future_native_compatibility(Path('prepared'))
            self.assertIs(result['currentNativeCompilationClaimed'],False)
            with patch.object(q,'source_identity',return_value={'unreviewed':'source'}), \
                    self.assertRaisesRegex(WorkflowError,'future-native-source-drift'):
                q.future_native_compatibility(Path('prepared'))
            with patch.object(future.READER,'_git_materials',return_value={}), \
                    self.assertRaisesRegex(WorkflowError,'future-producer-abi-or-schema-drift'):
                q.future_native_compatibility(Path('prepared'))


if __name__ == '__main__':unittest.main()
