"""No native/compiler execution: boundaries of the signed import diagnostic."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

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
            self.assertEqual(worlds[0], worlds[1])
            self.assertEqual(worlds[0], read_file(ROOT/'sdk/go-guest/runtime/standard-http-conformance/world.wit'))

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
