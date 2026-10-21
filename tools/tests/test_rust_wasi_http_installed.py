"""Real approval/registry boundaries used by the installed Rust programme."""
import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

from tools.application_dependency_approval import request as normal_request
from tools.dev_guest_tools import stage_registry
from tools.rust_capsule_project import canonical, digest
from tools import rust_wasi_http_installed_build as installed
from tools import qualify_rust_wasi_http_installed as owning
from tools import rust_wasi_http_installed_node as node
from tools import rust_wasi_http_installed_inputs as inputs


class InstalledRustHttp(unittest.TestCase):
    def test_real_controller_packaging_joins_actual_tool_and_preserves_original_compiler_records(self):
        from unittest.mock import patch
        from tools.dev_workflow import build_artifacts,build_provenance
        import json,time
        artifact=self.root/'attempt/output';artifact.mkdir(parents=True)
        (artifact/'component.wasm').write_bytes(b'component')
        packager=self.root/'latent';packager.write_bytes(b'actual-controlled-cli')
        signer=self.root/'signer';signer.write_bytes(b'actual-controlled-signer')
        observed={'componentDigest':digest(b'component'),'componentSize':9,'materials':[],
            'startedAt':10,'finishedAt':11}
        raw=canonical(observed);(artifact/'build-observation.json').write_bytes(raw)
        marker=canonical({'formatVersion':1,'componentDigest':digest(b'component'),
            'observationDigest':digest(raw),'packageAssembled':False})
        (artifact/'BUILD-COMPLETE.json').write_bytes(marker)
        result={'componentDigest':digest(b'component'),'packageDigest':'sha256:'+'a'*64}
        refused=SimpleNamespace(returncode=1,stdout=b'',stderr=b'controlled unsigned refusal')
        with patch.object(owning,'run_bounded_result',return_value=refused), \
                patch.object(build_artifacts,'package',return_value=result) as actual, \
                patch.object(build_provenance.time,'time',return_value=12):
            record=owning.complete_installed_package(artifact,{'latent':packager,'capsule_authoring':signer},
                self.root/'packaging',time.monotonic()+30)
        self.assertEqual(actual.call_count,1)
        self.assertEqual(actual.call_args.args[:2],(packager,artifact.parent))
        self.assertEqual(actual.call_args.args[2]['component'],'output/component.wasm')
        self.assertFalse(actual.call_args.kwargs['cached'])
        self.assertEqual((artifact/'compiler-build-observation.json').read_bytes(),raw)
        self.assertEqual((artifact/'compiler-BUILD-COMPLETE.json').read_bytes(),marker)
        self.assertTrue(json.loads((artifact/'BUILD-COMPLETE.json').read_bytes())['packageAssembled'])
        joined=json.loads((artifact/'build-observation.json').read_bytes())
        self.assertEqual(joined['materials'],[{'name':'packager','digest':digest(packager.read_bytes()),
            'size':len(packager.read_bytes())}])
        self.assertFalse(record['componentCompilationPerformed'])
        self.assertEqual((self.root/'packaging/compile-only-signing.stderr').read_bytes(),refused.stderr)
        self.assertEqual(record['controllerPackaging']['sha256'],digest((artifact/'controller-packaging.json').read_bytes()))

    def test_selected_installed_rust_imports_include_linux_dispatch_without_controller_only_inventory(self):
        import json
        from tools import dev_tool_distribution as distribution
        payload=self.root/'isolated-payload';payload.mkdir()
        distribution.recipe(payload,'rust',rust_http_runtime=True)
        recipe=payload/'recipe'
        self.assertFalse((recipe/'tools/dev_workflow/tool_inventory.py').exists())
        for name in ('build_process.py','build_process_linux.py','build_process_signals.py'):
            self.assertEqual((recipe/'tools'/name).read_bytes(),(inputs.ROOT/'tools'/name).read_bytes())
        script=('import sys,importlib,json;sys.path.insert(0,sys.argv[1]);'
            'mods=("tools.dev_guest_recipe","tools.rust_capsule_build","tools.dev_rust_http_runtime",'
            '"tools.rust_wasi_http_compose","tools.application_dependency_approval",'
            '"tools.rust_application_dependencies","tools.captured_compiler_isolation",'
            '"tools.build_process_linux");'
            '[importlib.import_module(name) for name in mods];print(json.dumps(mods))')
        result=subprocess.run([sys.executable,'-I','-B','-c',script,str(recipe)],
            cwd=self.root,env={**os.environ,'PYTHONPATH':''},capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr.decode())
        self.assertIn('tools.build_process_linux',json.loads(result.stdout))

    def test_outer_inventory_boundary_uses_the_genuine_checker_and_refuses_payload_or_source_drift(self):
        from tools import dev_tool_distribution as distribution
        from tools.phase3_resource_identity import file_identity
        payload=self.root/'payload'
        (payload/'recipe').mkdir(parents=True)
        control=payload/'recipe/control.py';control.write_bytes(b'controlled unexecuted recipe')
        value=distribution.compiler_inventory(payload,'a'*40,'rust')
        original=file_identity(payload/'guest-tools.json')
        assembled={'inventoryIdentity':value['identity']}
        owning.check_installed_inventory(payload,assembled,original)
        for changed in ('file','inventory-source','selected-inventory','assembled-identity'):
            raw=(payload/'guest-tools.json').read_bytes()
            chosen=copy.deepcopy(assembled);selected=copy.deepcopy(original)
            if changed=='file':control.write_bytes(b'altered recipe')
            elif changed=='inventory-source':
                import json
                inventory=json.loads(raw);inventory['sourceCommit']='b'*40
                (payload/'guest-tools.json').write_bytes(canonical(inventory))
            elif changed=='selected-inventory':selected['sha256']=digest(b'different inventory')
            else:chosen['inventoryIdentity']=digest(b'different selected source')
            with self.subTest(changed=changed),self.assertRaises((ValueError,RuntimeError)):
                owning.check_installed_inventory(payload,chosen,selected)
            control.write_bytes(b'controlled unexecuted recipe')
            (payload/'guest-tools.json').write_bytes(raw)

    def test_fixed_source_and_all_auxiliary_inputs_precede_installed_product_use(self):
        from unittest.mock import Mock, patch
        from tools import activation_stack_native_source as guard
        products = Mock(SOURCE=guard.SOURCE)
        products.verify_prepared.return_value = {'original': 'authenticated receipt'}
        products.native_products.return_value = {'contracts': 'unexecuted'}
        proof = {'compiledSourceRevision': guard.SOURCE, 'compiledNativeSource': guard.COMPILED,
                 'consumerNativeSource': guard.TEST_DEFAULTS}
        auxiliary = {'input-'+str(i): {'sha256': 'exact', 'bytes': i} for i in range(134)}
        manifest = {'native': copy.deepcopy(guard.COMPILED), 'materials': copy.deepcopy(auxiliary)}
        with patch.object(inputs, 'products', products), \
                patch.object(inputs, 'assert_current', return_value=proof), \
                patch.object(inputs, 'read_json', return_value=manifest), \
                patch.object(inputs, 'file_identity', side_effect=lambda path: auxiliary[path.name]):
            self.assertEqual(inputs.native_evidence(Path('prepared')),
                (products.verify_prepared.return_value, proof, auxiliary, products.native_products.return_value))
            products.native_products.reset_mock()
            manifest['materials']['input-0'] = {'sha256': 'different', 'bytes': 0}
            with self.assertRaisesRegex(RuntimeError, 'native-auxiliary-exact'):
                inputs.native_evidence(Path('prepared'))
            products.native_products.assert_not_called()
            products.SOURCE = 'f' * 40
            with self.assertRaisesRegex(RuntimeError, 'exact-native-origin'):
                inputs.native_evidence(Path('prepared'))
            products.native_products.assert_not_called()
            products.verify_prepared.side_effect = RuntimeError('original producer drift')
            with patch.object(inputs, 'assert_current', side_effect=AssertionError('receipt must precede guard')), \
                    self.assertRaisesRegex(RuntimeError, '^original producer drift$'):
                inputs.native_evidence(Path('prepared'))

    def test_cleanup_failure_never_masks_original_and_cannot_turn_success_into_pass(self):
        original=RuntimeError('original controlled failure')
        def refuse():raise OSError('controlled cleanup failure')
        record={}
        with self.assertRaises(RuntimeError) as seen:
            with node.owned_cleanup(record) as cleanup:
                cleanup.callback(refuse)
                raise original
        self.assertIs(seen.exception,original)
        self.assertEqual(record,{'cleanupRefused':True,'originalFailurePreserved':True})
        with self.assertRaises(OSError):
            with node.owned_cleanup({}) as cleanup:
                cleanup.callback(refuse)

    def test_owning_cli_bootstraps_without_pythonpath_or_compiler_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            result=subprocess.run([sys.executable,'-B',str(Path(owning.__file__)),'--help'],
                cwd=temporary,env={**os.environ,'PYTHONPATH':''},capture_output=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr.decode())
            self.assertIn(b'--native-products',result.stdout)
            self.assertEqual(list(Path(temporary).iterdir()),[])

    def setUp(self):
        owned = tempfile.TemporaryDirectory()
        self.addCleanup(owned.cleanup)
        self.root = Path(owned.name)
        self.app = self.root/'app'
        self.denied = self.root/'denied'
        self.app.mkdir(); self.denied.mkdir()
        self.lock = {'selection': {'runtimeProfile': 'closed'}, 'artifacts': [
            {'role': 'build-tool', 'id': 'original-'+str(i)} for i in range(16)]}
        isolation = SimpleNamespace(receipt={'profile': 'linux-captured-compiler-namespaces-v1',
            'tools': {'actual-control': {'digest': digest(b'compiler'), 'size': 8}}})
        spec = normal_request(SimpleNamespace(identity=digest(b'captured'), lock=self.lock),
            isolation, digest(b'recipe'))
        self.value = {'formatVersion': 1, 'specification': spec, 'identity': digest(canonical(spec))}
        self.failed = {'stage': 'executable-input-approval', 'commands': [{'stage': 'rust-version', 'exitCode': 0}]}
        self.write()

    def write(self):
        for path, value in ((self.app/'latent.dependencies.lock.json', self.lock),
                (self.denied/'BUILD-FAILED.json', self.failed),
                (self.denied/'executable-input-approval-request.json', self.value)):
            path.write_bytes(canonical(value))

    def test_original_normal_producer_request_is_preserved_without_inferred_approval(self):
        self.assertEqual(installed.request(self.denied, self.app, canonical, digest), self.value)
        self.assertFalse((self.denied/'BUILD-COMPLETE.json').exists())

    def test_changed_identity_closure_isolation_or_earlier_compile_cannot_authorize_installed_build(self):
        original = copy.deepcopy((self.value, self.failed, self.lock))
        for kind in ('identity', 'closure', 'isolation', 'network', 'compile', 'stage', 'count', 'boolean'):
            self.value, self.failed, self.lock = (copy.deepcopy(value) for value in original)
            if kind == 'identity': self.value['identity'] = digest(b'other')
            elif kind == 'closure': self.value['specification']['executableInputs'][0]['id'] = 'different'
            elif kind == 'isolation': self.value['specification']['isolationProfile'] = 'ambient'
            elif kind == 'network': self.value['specification']['network'] = 'allowed'
            elif kind == 'compile': self.failed['commands'].append({'stage': 'compile', 'exitCode': 0})
            elif kind == 'stage': self.failed['stage'] = 'capture'
            elif kind == 'count': self.lock['artifacts'].pop()
            else: self.value['formatVersion'] = True
            if kind in {'closure', 'isolation', 'network'}:
                self.value['identity'] = digest(canonical(self.value['specification']))
            self.write()
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                installed.request(self.denied, self.app, canonical, digest)

    def test_completed_marker_cannot_be_reinterpreted_as_request_only_attempt(self):
        (self.denied/'BUILD-COMPLETE.json').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'unapproved-before-compile'):
            installed.request(self.denied, self.app, canonical, digest)

    def test_existing_registry_freshness_requires_two_separate_attempts_without_a_waiver(self):
        source = self.root/'registry'
        source.mkdir(); (source/'exact-input').write_bytes(b'unchanged')
        first, second = self.root/'request-cache', self.root/'approved-cache'
        stage_registry(source, first, lambda: None)
        with self.assertRaisesRegex(ValueError, 'cache-must-be-fresh'):
            stage_registry(source, first, lambda: None)
        stage_registry(source, second, lambda: None)
        self.assertEqual((first/'exact-input').read_bytes(), (second/'exact-input').read_bytes())

    def test_outer_namespace_has_no_network_or_checkout_mount_and_installed_isolated_entry(self):
        payload, capture, work = (self.root/name for name in ('payload', 'capture', 'work'))
        control = work/'control.py'
        command = installed.namespace_command(Path('/usr/bin/bwrap'), payload, capture, work, control,
            'a'*40, 'sha256:'+'b'*64)
        self.assertIn('--unshare-all', command)
        self.assertIn('--clearenv', command)
        self.assertNotIn('--share-net', command)
        self.assertNotIn(str(Path.cwd()), command)
        self.assertEqual(command[command.index('--')+1:command.index('--')+5],
            [str(payload/'sdk/bin/python'), '-I', '-B', str(control)])
        mounts = [command[i+1:i+3] for i, token in enumerate(command) if token in {'--bind', '--ro-bind'}]
        self.assertIn([str(work), str(work)], mounts)
        self.assertIn([str(payload), str(payload)], mounts)
        self.assertIn([str(capture), str(capture)], mounts)
        self.assertIn([str(control), str(control)], mounts)
        with self.assertRaisesRegex(ValueError, 'owned-inputs'):
            installed.namespace_command(Path('/usr/bin/bwrap'), payload, capture, payload/'nested', control,
                'a'*40, 'sha256:'+'b'*64)


if __name__ == '__main__':
    unittest.main()
