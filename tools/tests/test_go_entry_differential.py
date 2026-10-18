"""No native/compiler execution: boundaries of the signed import diagnostic."""
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import yaml

from tools import diagnose_go_entry as diagnostic
from tools.go_capsule_project import validate
from tools.phase2_operator_process import WorkflowError
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, read_file, snapshot


def native_fixture(root):
    native = root/'native'
    (native/'native-binaries').mkdir(parents=True)
    identities = {}
    for name, key in diagnostic.NATIVE_NAMES.items():
        path = native/'native-binaries'/key.replace('/', '-')
        path.write_bytes(name.encode())
        identities[key] = file_identity(path)
    (native/'qualification.json').write_text(json.dumps({
        'schemaVersion': 'latent.go-capsule.qualification.v1', 'status': 'passed', 'binaries': identities}))
    return native


class EntryDifferential(unittest.TestCase):
    def test_only_http_import_changes_same_v4_public_string_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources, worlds = [], []
            for variant in diagnostic.VARIANTS:
                app = diagnostic.capture(root/variant, variant)
                descriptor, _lock, _pins = validate(snapshot(app))
                self.assertEqual(descriptor['runtimeProfile'], 'go-component-activation-v4')
                self.assertEqual(descriptor['world'], 'examples:go-standard-http/service@1.0.0')
                self.assertEqual(descriptor['limits']['memoryBytes'], 67108864)
                sources.append(read_file(app/'src/main.go'))
                worlds.append(read_file(app/'wit/world.wit'))
            self.assertNotIn(b'net/http', sources[0])
            self.assertEqual(sources[0], sources[1].replace(b'import _ "net/http"\n\n', b''))
            self.assertIn(b'func Run(which uint32, address string) string { return "entered" }', sources[0])
            for declaration in (b'func IntegerControl() uint32 { return 42 }',
                                b'func InputString(value string) uint32 { return 42 }',
                                b'func OutputString() string { return "entered" }'):
                self.assertIn(declaration, sources[0])
            self.assertEqual(worlds[0], worlds[1])
            original = read_file(ROOT/'sdk/go-guest/runtime/standard-http-conformance/world.wit')
            self.assertEqual(worlds[0], original.replace(b'    import latent:http/streaming@0.3.0;\n', b'')
                             .replace(diagnostic.STRING_RUN, diagnostic.STRING_RUN+diagnostic.SIGNATURE_WIT))
            self.assertNotIn(b'latent:http/', worlds[0])
            self.assertEqual(diagnostic.SIGNATURES, (('integer-control', [], 42),
                             ('input-string', ['entry-input'], 42), ('output-string', [], 'entered')))

    def test_runtime_only_grants_and_failure_row_survive_unconfirmed_retirement(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as patches:
            root = Path(directory)
            binaries = {}
            for name in ('latent', 'latentd', 'capsule_authoring'):
                binaries[name] = root/name
                binaries[name].write_bytes(name.encode())
            output = root/'node'
            client, service, peer, probe = Mock(), Mock(), Mock(), Mock()
            origin = {'host': '127.0.0.1', 'port': 1}
            peer.line.return_value = {'origins': {'primary': origin}}
            probe.sample.return_value = {}
            client.call.return_value = {'data': {'operation': {'publication': {'id': 'publication'}}}}
            runtime = [{'capability': name} for name in ('clock-wall', 'clock-monotonic', 'random', 'activation')]
            authorized = runtime+[{'capability': 'latent:http/streaming@0.3.0'}]
            row = {'exitCode': 4, 'processReaped': True, 'decoded': None, 'response': {'data': {
                'terminalState': 'guest_trap', 'consumption': {'outboundRequests': 0, 'childCalls': 0, 'effectCount': 0}}}}
            def configuration(directory, _signed, _startup, _credential):
                path = directory/'config.json'
                path.write_text('{}')
                return path
            def fence(*args):
                if args[-1] != 'entry-differential':
                    name = args[-1].removeprefix('entry-')
                    self.assertEqual(json.loads(read_file(output/(name+'.json')))['entry'], row)
                    return
                self.assertEqual(json.loads(read_file(output/'entry.json'))['entry'], row)
                self.assertEqual(args[-1], 'entry-differential')
                raise WorkflowError('unconfirmed-retirement-control')
            replacements = {'RecordingClient': Mock(return_value=client), 'configuration': configuration,
                'connect': Mock(return_value=service), 'Probe': Mock(return_value=probe),
                'grants': Mock(return_value=(runtime, authorized)), 'deploy': Mock(return_value={'name': 'target'}),
                'invoke': Mock(return_value=row), 'retire_case': fence}
            for name, value in replacements.items():
                patches.enter_context(patch.object(diagnostic.node, name, value))
            patches.enter_context(patch.object(diagnostic, 'Process', return_value=peer))
            patches.enter_context(patch.object(diagnostic, 'run_bounded_result', return_value=SimpleNamespace(returncode=0)))
            invoke_signature = patches.enter_context(patch.object(diagnostic, 'invoke_signature', return_value=row))
            with self.assertRaisesRegex(WorkflowError, 'unconfirmed-retirement-control'):
                diagnostic.observe(root/'artifact', binaries, output, diagnostic.time.monotonic()+90)
            self.assertIs(replacements['deploy'].call_args.kwargs['grants'], runtime)
            saved = json.loads(read_file(output/'observation.json'))
            self.assertEqual(saved['entry'], row)
            self.assertEqual(saved['outcome'], 'trapped')
            self.assertEqual(saved['stage'], 'retirement')
            self.assertEqual(saved['status'], 'incomplete')
            self.assertFalse(saved['qualification'])
            self.assertEqual([item['function'] for item in saved['signatures']],
                             [item[0] for item in diagnostic.SIGNATURES])
            self.assertTrue(all(item['outcome'] == 'trapped' for item in saved['signatures']))
            self.assertEqual(invoke_signature.call_count, 3)
            service.close.assert_called_once()
            peer.close.assert_called_once()

    def test_signature_exports_use_the_ordinary_cli_and_original_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'controls').mkdir()
            client = SimpleNamespace(directory=root, evidence=root/'controls', executable='latent',
                config=root/'config.json', environment={}, cancellation=Mock(), deadline=diagnostic.time.monotonic()+9)
            target = {'name': 'route', 'budget': {'cpuFuel': '1000'}}
            for function, values, expected in diagnostic.SIGNATURES:
                payload = diagnostic.base64.b64encode(json.dumps([expected]).encode()).decode()
                process = Mock()
                process.complete.return_value = SimpleNamespace(returncode=0,
                    stdout=json.dumps({'data': {'payload': {'data': payload}}}).encode())
                process.owner.finished = True
                with patch.object(diagnostic, 'Process', return_value=process) as owned:
                    row = diagnostic.invoke_signature(client, target, function, values, 'entry-'+function)
                command = owned.call_args.args[0]
                self.assertEqual(command[command.index('--function')+1], function)
                self.assertEqual(command[command.index('--contract')+1], 'examples:go-standard-http/api@1.0.0')
                self.assertEqual(command[command.index('--budget-profile')+1], 'phase3')
                self.assertEqual(json.loads(read_file(root/('entry-'+function+'.json'))), values)
                self.assertEqual(json.loads(read_file(root/('entry-'+function+'-budget.json'))), target['budget'])
                self.assertEqual(owned.call_args.kwargs['maximum'], 65536)
                self.assertLessEqual(process.complete.call_args.args[0], client.deadline)
                process.close.assert_called_once()
                self.assertIs(row['processReaped'], True)
                self.assertEqual(row['decoded'], [expected])
                self.assertEqual(json.loads(read_file(root/'controls'/('entry-'+function+'.json'))), row)
            with patch.object(diagnostic, 'Process') as owned:
                with self.assertRaisesRegex(WorkflowError, 'unknown-signature'):
                    diagnostic.invoke_signature(client, target, 'input-string', [], 'wrong')
                owned.assert_not_called()

    def test_integer_control_rejects_coerced_or_inexact_decoded_results(self):
        row = {'exitCode': 0, 'processReaped': True, 'decoded': [42],
               'response': {'data': {'consumption': {'outboundRequests': 0, 'childCalls': 0, 'effectCount': 0}}}}
        self.assertEqual(diagnostic.outcome(row, 42), 'returned')
        for value in (42.0, '42', True, 41):
            row['decoded'] = [value]
            with self.subTest(value=value), self.assertRaisesRegex(WorkflowError, 'constant-result'):
                diagnostic.outcome(row, 42)

    def test_public_rows_require_reaping_and_zero_effects_without_turning_traps_into_qualification(self):
        row = {'exitCode': 0, 'processReaped': True, 'decoded': ['entered'],
               'response': {'data': {'consumption': {'outboundRequests': 0, 'childCalls': 0, 'effectCount': 0}}}}
        self.assertEqual(diagnostic.outcome(row), 'returned')
        trapped = deepcopy(row)
        trapped.update(exitCode=4, decoded=None)
        trapped['response']['data']['terminalState'] = 'guest_trap'
        self.assertEqual(diagnostic.outcome(trapped), 'trapped')
        for changed in ('outboundRequests', 'childCalls', 'effectCount', 'processReaped', 'decoded', 'exitCode'):
            value = deepcopy(row)
            if changed in value['response']['data']['consumption']:
                value['response']['data']['consumption'][changed] = 1
            else:
                value[changed] = {'processReaped': False, 'decoded': ['wrong'], 'exitCode': 1}[changed]
            with self.subTest(changed=changed), self.assertRaises(WorkflowError):
                diagnostic.outcome(value)
        trapped['response']['data']['terminalState'] = 'rejected'
        with self.assertRaisesRegex(WorkflowError, 'not-a-guest-trap'):
            diagnostic.outcome(trapped)
        for key in ('outboundRequests', 'childCalls', 'effectCount'):
            for value in (False, '0'):
                invalid = deepcopy(row)
                invalid['response']['data']['consumption'][key] = value
                with self.subTest(key=key, value=value), self.assertRaisesRegex(WorkflowError, 'external-effect'):
                    diagnostic.outcome(invalid)

    def test_normal_build_frozen_products_and_both_observations_keep_original_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = native_fixture(root)
            commands = []
            def compile_one(command, cwd, environment, maximum, output_bound):
                self.assertEqual(cwd, ROOT)
                self.assertLessEqual(maximum, 180)
                self.assertGreater(maximum, 0)
                self.assertEqual(output_bound, 2*1024**2)
                self.assertEqual(command[1], str(ROOT/'tools/go_capsule.py'))
                self.assertEqual(command[2], 'build')
                output = Path(command[command.index('--output')+1])
                output.mkdir()
                (output/'component.wasm').write_bytes(b'not-executed-diagnostic-control')
                commands.append(command)
                return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
            with patch.object(diagnostic, 'run_bounded_result', side_effect=compile_one), \
                    patch.object(diagnostic, 'observe', return_value={'qualification': False, 'status': 'observed', 'outcome': 'trapped'}) as observe:
                result = diagnostic.diagnose(root/'diagnostic', native)
            self.assertFalse(result['qualification'])
            self.assertEqual(result['status'], 'observed')
            self.assertEqual([x['variant'] for x in result['variants']], list(diagnostic.VARIANTS))
            self.assertEqual(len(commands), 2)
            self.assertEqual(observe.call_count, 2)
            self.assertTrue(all(x['node']['outcome'] == 'trapped' for x in result['variants']))
            self.assertEqual(result['limits'], {'overallSeconds': 600, 'compileSeconds': 180, 'nodeSeconds': 90})
            (native/'native-binaries/latentd').write_bytes(b'tampered')
            with patch.object(diagnostic, 'capture') as capture, patch.object(diagnostic, 'run_bounded_result') as compiler:
                with self.assertRaisesRegex(WorkflowError, 'frozen-native-products-mismatch'):
                    diagnostic.diagnose(root/'tampered', native)
                capture.assert_not_called()
                compiler.assert_not_called()

    def test_diagnostic_is_failure_only_and_neither_original_signed_gate_is_optional(self):
        workflow = yaml.safe_load(read_file(ROOT/'.github/workflows/go-guest.yml'))
        job = workflow['jobs']['upstream-probe']
        self.assertEqual(job['timeout-minutes'], 45)
        steps = job['steps']
        originals = [next(s for s in steps if s.get('name') == name) for name in (
            'Qualify ordinary net/http contexts and disposal on the signed node',
            'Qualify two captured default clients and renamed private transitive workers')]
        self.assertTrue(all(not s.get('continue-on-error', False) for s in originals))
        self.assertIn('tools/qualify_go_standard_http.py', originals[0]['run'])
        self.assertIn('tools/qualify_go_http_libraries.py', originals[1]['run'])
        added = next(s for s in steps if s.get('name') == 'Diagnose signed Go entry with and without net/http initialization')
        self.assertEqual(added['if'], "${{ !cancelled() && failure() && steps.normal_go_qualification.outcome == 'success' }}")
        self.assertIn('tools/diagnose_go_entry.py', added['run'])
        self.assertLess(steps.index(originals[1]), steps.index(added))
        artifacts = next(s['with']['path'] for s in steps if 'Retain successful and failed upstream' in s.get('name', ''))
        self.assertIn('go-entry-differential/observation.json', artifacts)
        self.assertIn('go-entry-differential/*/build/component.wasm', artifacts)


if __name__ == '__main__':
    unittest.main()
