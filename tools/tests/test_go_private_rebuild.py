"""Actual receipt and qualifier boundaries over modeled bytes; no Go execution."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import qualify_go_private_dependencies as gate
from tools.application_dependency_store import DependencyError
from tools.rust_capsule_project import canonical, digest, inventory


class OfflineRebuild(unittest.TestCase):
    def produce(self, root, label, project, *, component=b'modeled component', changed=None):
        from tools import guest_runtime_receipts as runtime
        files = {'src/main.go': b'unchanged captured source', 'vendor/lsf/sdk/go-guest/runtime.go': b'original SDK',
            'wit/world.wit': b'package examples:modeled; world service {}',
            'capsule-project.json': canonical({'world': 'examples:modeled/service'})}
        for name, raw in files.items():
            path = project / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        output = root / label; output.mkdir()
        recipe = canonical({'tools/go_capsule_build.py': {'digest': digest(b'original compiler source'), 'size': 24}})
        bindings = canonical({'selected': 'same WIT output'})
        # networkResolution must be false on both real offline observations.
        dependency = canonical({'networkResolution': changed == 'network', 'language': 'go',
                                'lockDigest': digest(b'foreign' if changed == 'lock' else b'lock')})
        if changed == 'recipe': recipe += b' '
        if changed == 'bindings': bindings = canonical({'selected': 'foreign WIT output'})
        source = inventory(files)
        value = json.loads(bindings)
        bound = digest(json.dumps(value,sort_keys=True,separators=(',', ':')).encode())
        payloads = {'source-inputs.json': source, 'recipe-inputs.json': recipe, 'bindings.json': bindings,
                    'application-dependencies.json': dependency, 'component.wasm': component,
                    'compiler-containment.json': canonical({'network': 'denied', 'credentials': 'not-inherited'})}
        for name, raw in payloads.items(): (output / name).write_bytes(raw)
        materials = [{'name': name, 'digest': digest((name + ('foreign' if changed == 'tool' and name == 'go' else '')).encode()),
                      'size': len(name)} for name in gate.COMPILER_INPUTS]
        for name, key in [('source-snapshot','source-inputs.json'),('build-recipe','recipe-inputs.json'),
                          ('application-dependencies','application-dependencies.json'),('compiler-containment','compiler-containment.json')]:
            raw=payloads[key];materials.append({'name':name,'digest':digest(raw),'size':len(raw)})
        profile='go-component-async-v1'
        selected=runtime.emit(output,'go',profile,files,source,component,materials,graph=None,binding_digest=bound,
            configuration={'profile':profile,'world':'examples:modeled/service','target':'wasip1/wasm','selection':{}})
        observation={'source':{'snapshotDigest':digest(source)},'componentDigest':digest(component),
            'materials':[*materials,selected], 'parameters':{'runtime':profile,'locked':True,'ambientWasi':False}}
        raw=canonical(observation);(output/'build-observation.json').write_bytes(raw)
        (output/'BUILD-COMPLETE.json').write_bytes(canonical({'sourceDigest':digest(source),'componentDigest':digest(component),
            'observationDigest':digest(raw),'sdkBindingDigest':bound}))
        return output

    def test_distinct_real_receipt_outputs_preserve_inputs_and_require_both_signed_executions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);project=root/'project'
            first=self.produce(root,'first',project,component=b'first modeled component')
            second=self.produce(root,'second',project,component=b'second modeled component')
            receipt=gate.offline_rebuild(first,second,project)
            self.assertFalse(receipt['rawBytesIdentical'])
            self.assertEqual(receipt['componentReproducibility'],'not-claimed')
            self.assertTrue(receipt['bothSignedExecutionsRequired'])
            self.assertEqual(len(receipt['outputs']),2)
            self.assertNotEqual(receipt['outputs'][0]['component']['digest'],receipt['outputs'][1]['component']['digest'])

    def test_changed_recipe_binding_lock_tool_or_offline_policy_never_uses_byte_variance_exception(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);project=root/'project'
            first=self.produce(root,'first',project)
            for mode in ('recipe','bindings','lock','tool','network'):
                with self.subTest(mode=mode):
                    second=self.produce(root,mode,project,changed=mode)
                    with self.assertRaises(Exception): gate.offline_rebuild(first,second,project)

    def test_stale_component_or_runtime_receipt_refuses_before_signing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);project=root/'project'
            first=self.produce(root,'first',project)
            for mode in ('component','runtime'):
                with self.subTest(mode=mode):
                    second=self.produce(root,mode,project)
                    if mode=='component': (second/'component.wasm').write_bytes(b'uncaptured replacement')
                    else: (second/'standard-runtime-selection.json').write_bytes((first/'standard-runtime-selection.json').read_bytes()+b' ')
                    with self.assertRaises(Exception): gate.offline_rebuild(first,second,project)


class BothActualOutputs(unittest.TestCase):
    def test_real_qualifier_signs_and_executes_both_initial_outputs_plus_update_and_remove(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);go=root/'never-executed-go';go.write_bytes(b'fixture compiler identity')
            commands=SimpleNamespace(deadline=float('inf'))
            signed, observed=[],[]
            def run(stage, tool, command, destination, artifact, *companions):
                self.assertEqual(command,'demo-sign');destination.mkdir()
                signed.append(json.loads((artifact/'BUILD-COMPLETE.json').read_bytes())['componentDigest'])
            commands.run=run
            def build(project, output, *args):
                output.mkdir();raw=('modeled '+output.name).encode()
                (output/'BUILD-COMPLETE.json').write_bytes(canonical({'componentDigest':digest(raw)}))
                (output/'application-dependencies.json').write_bytes(canonical({'networkResolution':False}))
                return output
            def node(cli, binary, signed_path, output, **options):
                value=json.loads((signed_path/'private-Go-probe.json').read_bytes());observed.append(value)
                output.mkdir();(output/'workflow.json').write_bytes(canonical({'status':'passed'}))
                return {'status':'passed','capturedGoPrivate':{'status':'passed','cases':[0,1,2]}}
            products={name:root/name for name in ('capsule_contracts','package','capsule_authoring','latent','latentd')}
            receipt={'sourceIdentityDigest':digest(b'{}'),'binaries':{}}
            phases=[(root/'app',{},version,removed) for version,removed in [('v1.0.0',False),('v1.1.0',False),('v1.1.0',True)]]
            with patch.object(gate,'Commands',return_value=commands),patch.object(gate,'frozen',return_value=(receipt,products,[])), \
                 patch.object(gate,'capture',return_value=(phases,{'nonce':'a'*24})), \
                 patch.object(gate,'source_files',return_value={}),patch.object(gate,'inputs',return_value={}), \
                 patch.object(gate.dependencies,'verify_inputs',return_value=SimpleNamespace(lock={})), \
                 patch.object(gate,'build',side_effect=build),patch.object(gate,'node_workflow',side_effect=node), \
                 patch.object(gate,'offline_rebuild',create=True,return_value={'rawBytesIdentical':False}), \
                 patch('shutil.which',return_value=str(go)):
                result=gate.qualify(root/'prepared',root/'output')
            self.assertEqual(result['status'],'passed')
            self.assertEqual(len(signed),4)
            self.assertNotEqual(signed[0],signed[1])
            self.assertEqual([(r['version'],r['removed']) for r in observed],
                             [('v1.0.0',False),('v1.0.0',False),('v1.1.0',False),('v1.1.0',True)])
            self.assertEqual(len(result['nodeReceipts']),4)
            self.assertFalse(result['offlineRebuild']['rawBytesIdentical'])


class OwnedProxyAuthority(unittest.TestCase):
    def test_actual_netrc_producer_matches_exact_pinned_go_authority_without_cross_port_credentials(self):
            import os
            from tools import go_application_dependencies as native
            def matches(machine, url):
                prefix = url.removeprefix('https://').removesuffix('/')
                while True:
                    if prefix == machine:
                        return True
                    if '/' not in prefix:
                        return False
                    prefix = prefix.rsplit('/', 1)[0]
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                for ordinal, authority in enumerate(('127.0.0.1:45679', '[::1]:45679', 'packages.example')):
                    with self.subTest(authority=authority):
                        app = root / ('app-' + str(ordinal)); app.mkdir()
                        owned = root / ('owned-' + str(ordinal)); owned.mkdir()
                        policy = root / ('policy-' + str(ordinal) + '.json')
                        policy.write_bytes(canonical({'proxy': 'https://' + authority + '/proxy', 'sumdb': 'off',
                            'authorizationEnv': 'LSF_REPLAY_NETRC_AUTHORITY'}))
                        with patch.dict(os.environ, {'LSF_REPLAY_NETRC_AUTHORITY': 'owned-fixture-token'}):
                            environment, _policy, _raw = native.fetch_environment(app, owned, policy, project=app)
                        machine = Path(environment['NETRC']).read_text().split()[1]
                        self.assertEqual(machine, authority)
                        self.assertTrue(matches(machine, 'https://' + authority + '/proxy/module/@v/v0.1.0.mod'))
                        self.assertFalse(matches(machine, 'https://' + authority + '.different/proxy/module'))
                        if ':45679' in authority:
                            self.assertFalse(matches(machine, 'https://' + authority.replace(':45679', ':45680') + '/proxy/module'))

    def test_proxy_userinfo_still_refuses_before_owned_config_or_credential_lookup(self):
            from tools import go_application_dependencies as native
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); app = root / 'app'; app.mkdir(); owned = root / 'owned'; owned.mkdir()
                policy = root / 'policy.json'
                for credentials in ('username:private', '', ':', ':private', 'username:'):
                    with self.subTest(credentials=credentials):
                        policy.write_bytes(canonical({'proxy': 'https://' + credentials + '@127.0.0.1:45679', 'sumdb': 'off',
                                                      'authorizationEnv': 'NEVER_LOOK_UP_THIS_SECRET'}))
                        with patch.object(native.go_proxy_tls, 'prepare') as prepare:
                            with self.assertRaisesRegex(DependencyError, 'go-proxy-endpoint-invalid'):
                                native.fetch_environment(app, owned, policy, project=app)
                        prepare.assert_not_called()
                        self.assertEqual(list(owned.iterdir()), [])


if __name__=='__main__': unittest.main()
