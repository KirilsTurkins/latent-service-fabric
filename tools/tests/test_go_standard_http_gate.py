"""Captured project/native-product boundaries for the separate signed gate."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.go_capsule_project import validate
from tools.go_standard_http_project import project
from tools.phase3_resource_identity import file_identity
from tools.phase2_operator_process import WorkflowError
from tools.qualify_go_standard_http import NATIVE_NAMES, qualify
from tools.rust_capsule_project import ROOT, read_file, snapshot


class StandardHttpGate(unittest.TestCase):
    def test_entry_probes_keep_original_http_cases_separate_and_retire_without_external_effects(self):
        from tools import go_standard_http_node as node
        source = read_file(ROOT/'sdk/go-guest/runtime/standard-http-conformance/main.go').decode()
        self.assertLess(source.index('if which == 25'),source.index('client := &http.Client'))
        self.assertLess(source.index('http.NewRequestWithContext'),source.index('if which == 26'))
        self.assertLess(source.index('if which == 26'),source.index('client.Do(request)'))
        rows = [{'exitCode':0,'decoded':[value],'processReaped':True,
                 'response':{'data':{'consumption':{'outboundRequests':0,'effectCount':0}}}}
                for value in ('entered','request-ready')]
        result = {'cases':[]}
        with patch.object(node,'invoke',side_effect=rows) as invoke, patch.object(node,'retire_case') as retire:
            node.entry_probes('client','probe',{'name':'target'},Path('output'),'http://fixture/json',result)
        self.assertEqual(result['cases'],[])
        self.assertEqual([row['name'] for row in result['entryProbes']],['entry','request-setup'])
        self.assertEqual([call.args[2] for call in invoke.call_args_list],[25,26])
        self.assertEqual([call.args[-1] for call in retire.call_args_list],['probe-entry','probe-request-setup'])
        self.assertTrue(all(call.args[3] == 'http://fixture/json' for call in invoke.call_args_list))

    def test_failed_or_effectful_entry_probe_is_retained_and_cannot_qualify_or_continue(self):
        from tools import go_standard_http_node as node
        for changed in ({'exitCode':4}, {'decoded':['wrong']}, {'processReaped':False},
                        {'outboundRequests':1}, {'effectCount':1}):
            row = {'exitCode':0,'decoded':['entered'],'processReaped':True,
                   'response':{'data':{'consumption':{'outboundRequests':0,'effectCount':0}}}}
            for key,value in changed.items():
                if key in {'outboundRequests','effectCount'}:
                    row['response']['data']['consumption'][key] = value
                else:
                    row[key] = value
            result = {'cases':[]}
            with self.subTest(changed=changed), patch.object(node,'invoke',return_value=row) as invoke, \
                    patch.object(node,'retire_case') as retire:
                with self.assertRaisesRegex(WorkflowError,'standard-go-probe-'):
                    node.entry_probes('client','probe',{'name':'target'},Path('output'),'http://fixture/json',result)
                self.assertEqual(invoke.call_count,1)
                retire.assert_not_called()
                self.assertEqual(len(result['entryProbes']),1)
                self.assertEqual(result['cases'],[])

    def test_compile_qualifier_selects_the_actual_captured_world_for_both_fixtures(self):
        from tools import qualify_go_http_context
        for fixture in ('http-context-conformance','standard-http-conformance'):
            with self.subTest(fixture=fixture), tempfile.TemporaryDirectory() as directory, \
                    patch.object(qualify_go_http_context,'Commands'), \
                    patch.object(qualify_go_http_context,'Compiler') as factory:
                compiler = factory.return_value
                compiler.materials = []
                def compile_fixture(source, wit, world, output, **kwargs):
                    package = read_file(wit/'world.wit').decode().split('package ',1)[1].split('@',1)[0]
                    self.assertEqual(world,package+'/service@1.0.0')
                    output.mkdir()
                    component = output/'component.wasm'
                    component.write_bytes(b'not-executed-component-control')
                    return component, {}
                compiler.compile.side_effect = compile_fixture
                result = qualify_go_http_context.qualify(Path(directory)/'compile',fixture_name=fixture)
                self.assertEqual(result['status'],'passed')
                self.assertEqual(result['qualification'],'compile-only')
                self.assertEqual(result['signedExecution'],'not-run')
                self.assertFalse(result['defaultNetHttpQualification'])

    def test_project_world_and_export_package_share_the_declared_tenant(self):
        with tempfile.TemporaryDirectory() as directory:
            app = project(Path(directory)/'application')
            descriptor = json.loads(read_file(app/'capsule-project.json'))
            package = read_file(app/'wit/world.wit').decode().split('package ',1)[1].split('@',1)[0]
            self.assertEqual(package.split(':',1)[0], descriptor['tenant'])
            self.assertEqual(descriptor['world'], package+'/service@1.0.0')
            self.assertEqual(read_file(app/'src/main.go').decode().splitlines()[0],
                'package export_'+package.replace(':','_').replace('-','_')+'_api')

    def test_signed_peer_carrier_is_an_existing_runnable_shared_owner(self):
        import sys
        from tools.go_standard_http_node import PEER_SOURCE
        from tools.build_process import run_bounded_result
        from tools.build_observation import build_environment
        with tempfile.TemporaryDirectory() as directory:
            result = run_bounded_result([sys.executable,str(ROOT/PEER_SOURCE),'--help'],
                ROOT,build_environment(Path(directory)),10,65536)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn(b'--credential',result.stdout)

    def test_project_captures_exact_ordinary_fixture_and_immutable_sdk_for_real_build(self):
        with tempfile.TemporaryDirectory() as directory:
            app = project(Path(directory)/'application')
            descriptor, _lock, _pins = validate(snapshot(app))
            self.assertEqual(descriptor['runtimeProfile'],'go-component-activation-v4')
            self.assertEqual(descriptor['world'],'examples:go-standard-http/service@1.0.0')
            self.assertEqual(read_file(app/'src/main.go'),
                read_file(ROOT/'sdk/go-guest/runtime/standard-http-conformance/main.go'))
            self.assertEqual(read_file(app/'wit/world.wit'),
                read_file(ROOT/'sdk/go-guest/runtime/standard-http-conformance/world.wit'))
            self.assertEqual(descriptor['limits']['memoryBytes'],67108864)
            self.assertEqual(descriptor['limits']['wallTimeLimitMillis'],120000)
            changed = app/'vendor/lsf/sdk/go-guest/runtime/http_async.go.in'
            changed.write_bytes(read_file(changed)+b'\nchanged')
            with self.assertRaisesRegex(ValueError,'vendored SDK changed'):
                validate(snapshot(app))

    def test_tampered_frozen_native_product_is_rejected_before_project_or_compiler(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); native = root/'native'; native.mkdir(); (native/'native-binaries').mkdir()
            identities = {}
            for name,key in NATIVE_NAMES.items():
                path = native/'native-binaries'/key.replace('/','-')
                path.write_bytes(name.encode())
                identities[key] = file_identity(path)
            (native/'qualification.json').write_text(json.dumps({
                'schemaVersion':'latent.go-capsule.qualification.v1','status':'passed','binaries':identities}))
            (native/'native-binaries/latentd').write_bytes(b'changed')
            with patch('tools.qualify_go_standard_http.project') as capture, \
                    patch('tools.qualify_go_standard_http.run_bounded_result') as compiler:
                with self.assertRaisesRegex(WorkflowError,'frozen-native-products-mismatch'):
                    qualify(root/'qualification',native)
                capture.assert_not_called(); compiler.assert_not_called()
            failure = json.loads(read_file(root/'qualification/FAILED.json'))
            self.assertEqual(failure['stage'],'native-products')


if __name__ == '__main__': unittest.main()
