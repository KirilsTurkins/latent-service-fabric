"""Explicit normal BCL stdio selection, source identity and authority boundaries."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import tomllib
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET
import io
import copy
import json
import zipfile

from tools.dotnet_guest import runtime, project
from tools.dotnet_guest.compiler import runtime_inputs
from tools.rust_capsule_project import decode_json
from tools import dotnet_standard_console_fixture as fixture, dotnet_standard_console_probe as probe
from tools.qualify_dotnet_standard_console import inherited
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import TEMPLATES, digest


class StandardConsole(unittest.TestCase):
    def test_log_selection_requires_declared_exact_authority_and_actual_stdio(self):
        for base, declared, emitted in (
            ('closed', [runtime.CLOCK], []),
            ('runtime', [runtime.CLOCK, runtime.ACTIVATION], []),
            ('http', [runtime.CLOCK, runtime.ACTIVATION, runtime.HTTP], list(runtime.WASI_HTTP_IMPORTS))):
            with self.subTest(base=base):
                self.assertEqual(runtime.select(declared, emitted), base)
                self.assertEqual(runtime.select([*declared, runtime.LOG], emitted), base)
                self.assertEqual(runtime.select(declared, [*emitted, *runtime.WASI_STDIO]), base)
                self.assertEqual(runtime.select([*declared, runtime.LOG], [*emitted, *runtime.WASI_STDIO]), base + '-logging')
                self.assertEqual(runtime.additional([*declared, runtime.LOG], [*emitted, *runtime.WASI_STDIO]), ())

    def test_log_selection_preserves_existing_duplicate_version_and_missing_clock_refusals(self):
        for declared, emitted, reason in (
            ([runtime.LOG], list(runtime.WASI_STDIO), 'declared-monotonic'),
            ([runtime.CLOCK, runtime.LOG, runtime.LOG], [], 'duplicate-import'),
            ([runtime.CLOCK, runtime.LOG], ['wasi:cli/stdout@0.2.7'], 'unsupported-wasi'),
            ([runtime.CLOCK, 'latent:log/log@9.0.0'], list(runtime.WASI_STDIO), 'unsupported-log-version')):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                runtime.select(declared, emitted)

    def test_logging_primaries_keep_real_world_inputs_and_original_adapter_family(self):
        root = project.ROOT
        model = tomllib.loads((root / 'tools/toolchain-smoke/Cargo.toml').read_text(encoding='utf-8'))
        examples = {row['name']: row for row in model['example']}
        self.assertEqual((root / 'sdk/dotnet-guest/runtime/wit/deps/log.wit').read_bytes(),
                         (root / 'wit/platform/log/package.wit').read_bytes())
        world = (root / 'sdk/dotnet-guest/runtime/wit/world.wit').read_text(encoding='utf-8')
        for name, original in (('closed', 'closed'), ('runtime', 'activation'), ('http', 'http')):
            example, binary = runtime.ADAPTERS[name + '-logging']
            row = examples[example]
            self.assertFalse(row['test']); self.assertEqual(row['crate-type'], ['cdylib'])
            body = (root / 'tools/toolchain-smoke' / row['path']).read_text(encoding='utf-8')
            before = (root / 'tools/toolchain-smoke/examples' / ('dotnet_' + original + '_runtime.rs')).read_text(encoding='utf-8')
            expected = before.replace('world: "' + name + '"', 'world: "' + name + '-logging"')
            expected = expected.replace('/console/closed.rs', '/console/logging.rs')
            if name == 'closed':
                expected = expected.replace('"latent:clock/monotonic@0.1.0": generate,',
                    '"latent:clock/monotonic@0.1.0": generate,\n        "latent:log/log@0.1.0": generate,')
            self.assertEqual(body, expected)
            self.assertIn('world ' + name + '-logging { include ' + name + '; import latent:log/log@0.1.0; }', world)
            self.assertTrue(binary.endswith('.wasm'))

    def test_independent_project_and_runtime_inventory_bind_all_actual_port_inputs(self):
        with tempfile.TemporaryDirectory() as owned:
            app = project.create(Path(owned) / 'greeting', 'greeting')
            files = project.snapshot(app)
            project.validate(files)
            selected = decode_json(runtime_inputs(app / 'vendor/lsf'))
            paths = set(selected)
            for path in ('sdk/dotnet-guest/runtime/console/logging.rs',
                         'sdk/dotnet-guest/runtime/console/closed.rs',
                         'sdk/dotnet-guest/runtime/wit/deps/log.wit', *runtime.EXAMPLES):
                self.assertIn(path, paths)
            self.assertNotIn(runtime.LOG, (app / 'wit/world.wit').read_text(encoding='utf-8'))

    def test_console_declaration_changes_application_authority_without_changing_immutable_sdk(self):
        with tempfile.TemporaryDirectory() as owned:
            app = project.create(Path(owned) / 'greeting', 'greeting')
            lock = (app / 'sdk-lock.json').read_bytes()
            fixture.declare(app)
            files = project.snapshot(app)
            project.validate(files)
            self.assertEqual((app / 'sdk-lock.json').read_bytes(), lock)
            self.assertEqual((app / 'wit/deps/log/package.wit').read_bytes(),
                             (project.ROOT / 'wit/platform/log/package.wit').read_bytes())
            self.assertEqual(decode_json(files['capsule-project.json'])['limits']['logBytes'], 16384)
            with self.assertRaisesRegex(RuntimeError, 'world-preimage'): fixture.declare(app)

    def test_outside_packages_keep_exact_transitive_identity_and_resource_bytes(self):
        with tempfile.TemporaryDirectory() as owned:
            feed = Path(owned)
            for identity, child in ((fixture.PARENT, False), (fixture.CHILD, True)):
                assembly = b'actual-managed-bytes-placeholder-' + identity.encode()
                fixture.pack(feed, identity, assembly, child=child)
                with zipfile.ZipFile(io.BytesIO((feed / (identity.lower() + '.1.0.0.nupkg')).read_bytes())) as archive:
                    self.assertEqual(archive.read('lib/net10.0/' + identity + '.dll'), assembly)
                    metadata = ET.fromstring(archive.read(identity + '.nuspec'))
                    dependencies = metadata.findall('.//dependency')
                    self.assertEqual([row.attrib for row in dependencies], [] if child else [
                        {'id': fixture.CHILD, 'version': '[1.0.0]'}])
            self.assertEqual(fixture.RESOURCE, bytes((71, 114, 195, 188, 195, 159, 101)))
            self.assertIn('System.Console.OpenStandardOutput()', fixture.LIBRARY_SOURCE)
            self.assertNotIn('Console.SetOut', fixture.LIBRARY_SOURCE)

    def test_log_admission_preserves_the_actual_runtime_grant_list_and_refuses_missing_or_foreign_provider(self):
        def observe(*, grant_clock=True, foreign=False, denied_fuel=0):
            with tempfile.TemporaryDirectory() as owned:
                client = SimpleNamespace(directory=Path(owned), call=Mock())
                target = {'service': 'examples/my-greeting', 'generation': 3,
                    'grants': [{'capability': runtime.CLOCK, 'policy': 'clock'}, {'capability': 'extra', 'policy': 'existing'}]}
                if not grant_clock: target['grants'].pop(0)
                node = SimpleNamespace(startup_record={'providers': [{'id': 'log', 'capability': runtime.LOG,
                    'tenant': 'other' if foreign else 'examples', 'service': 'runtime-host',
                    'profile': 'activation-log-v1', 'configurationEpoch': '1', 'configurationDigest': 'sha256:' + 'a' * 64}]})
                denied = {'exitCode': 4, 'processReaped': True, 'response': {'outcomeKnown': True,
                    'error': {'code': 'permission-denied'}, 'data': {'terminalState': 'rejected',
                    'consumption': {'cpuFuel': str(denied_fuel), 'peakMemoryBytes': '0', 'effectCount': 0}}}}
                result = {'invocations': [], 'providerIdle': []}
                with patch('tools.rust_capsule_node.call', return_value=denied), \
                        patch('tools.rust_capsule_node.provider_idle', return_value={}), \
                        patch('tools.rust_capsule_node.deploy', return_value={}) as deployed:
                    probe.grant(client, node, Path(owned), {'greeting': target}, {'greeting': 'publication'}, result)
                self.assertEqual(deployed.call_args.kwargs['grants'], [*target['grants'],
                    {'capability': runtime.LOG, 'policy': 'dotnet-console'}])
                self.assertEqual(len(result['invocations']), 2)
        observe()
        with self.assertRaisesRegex(RuntimeError, 'preserve-existing-runtime-grants'): observe(grant_clock=False)
        with self.assertRaisesRegex(RuntimeError, 'provider-identity'): observe(foreign=True)
        with self.assertRaisesRegex(RuntimeError, 'missing-grant-before-guest'): observe(denied_fuel=1)

    def test_all_eight_console_cases_require_charged_logs_and_trap_fuel_physical_recovery(self):
        def observe(*, reaped=True, success_reaped=True, fault_fuel=110_000_000, logged=32, baseline=55_000_000):
            def invoke(_client, target, _template, _function, args, activation):
                mode = args[0].removeprefix('console:')
                consumed = {'logBytes': str(logged), 'outboundRequests': '0',
                    'peakMemoryBytes': '10', 'cpuFuel': str(baseline)}
                if mode in {'trap', 'fuel'}:
                    code = 'guest-trap' if mode == 'trap' else 'resource-exhausted'
                    consumed['cpuFuel'] = str(fault_fuel)
                    return {'exitCode': 4, 'processReaped': reaped, 'response': {'outcomeKnown': True,
                        'error': {'code': code}, 'data': {'terminalState': code.replace('-', '_'), 'consumption': consumed}}}
                return {'exitCode': 0, 'processReaped': success_reaped, 'activation': activation,
                    'decoded': [{'ok': fixture.EXPECTED[mode]}], 'response': {'outcomeKnown': True,
                    'data': {'consumption': consumed}}}
            result = {'invocations': [], 'providerIdle': [], 'samples': []}
            with patch('tools.rust_capsule_node.call', side_effect=invoke) as calls, \
                    patch('tools.rust_capsule_node.provider_idle', return_value={}), \
                    patch('tools.rust_capsule_node.sample', return_value={}) as samples:
                probe.probe(None, {'budget': {'cpuFuel': 1_000_000_000, 'memoryBytes': 100, 'logBytes': 16384}},
                            None, result, 17)
            return result, calls, samples
        result, calls, samples = observe()
        self.assertEqual([row['case'] for row in result['dotnetStandardConsoleCases']], list(fixture.CASES))
        self.assertEqual([row['case'] for row in result['dotnetStandardConsoleRecovery']], ['trap', 'fuel'])
        self.assertEqual(len(result['invocations']), 12); self.assertEqual(samples.call_count, 12)
        self.assertEqual(calls.call_args_list[8].args[1]['budget']['cpuFuel'], 1_000_000_000)
        self.assertEqual(calls.call_args_list[10].args[1]['budget']['cpuFuel'], 110_000_000)
        with self.assertRaisesRegex(RuntimeError, 'failure-shape'): observe(reaped=False)
        with self.assertRaisesRegex(RuntimeError, 'invocation-process'): observe(success_reaped=False)
        with self.assertRaisesRegex(RuntimeError, 'original-fuel-bound'): observe(fault_fuel=109_999_999)
        with self.assertRaisesRegex(RuntimeError, 'charged-log'): observe(logged=0)
        with self.assertRaisesRegex(RuntimeError, 'startup-fuel-margin'): observe(baseline=500_000_000)

    def test_console_execution_selector_rejects_foreign_language_and_bool_alias_before_creating_output(self):
        from tools.run_rust_capsule_workflow import run
        with tempfile.TemporaryDirectory() as owned:
            for language, flag in (('java', True), ('dotnet', 1)):
                destination = Path(owned) / 'must-not-exist'
                with self.assertRaisesRegex(RuntimeError, 'dotnet-standard-logging-language'):
                    run(Path('missing'), Path('missing'), Path('missing'), destination,
                        language=language, dotnet_standard_logging=flag)
                self.assertFalse(destination.exists())

    def test_reused_companions_and_native_tuple_require_original_receipt_and_exact_build_bytes(self):
        current = {'source': 'current'}
        expected = patch('tools.qualify_dotnet_standard_console.inputs', return_value=current)
        expected.start(); self.addCleanup(expected.stop)
        with tempfile.TemporaryDirectory() as owned:
            root = Path(owned)
            from tools.qualify_dotnet_standard_console import NATIVE_NAMES
            binaries = root / 'native-binaries'; binaries.mkdir()
            native = {}
            for name in NATIVE_NAMES.values():
                path = binaries / name.replace('/', '-'); path.write_bytes(name.encode())
                native[name] = file_identity(path)
            builds = {}
            for template in TEMPLATES:
                if template == 'greeting': continue
                directory = root / 'builds' / template; directory.mkdir(parents=True)
                row = {}
                for name, field in (('component.wasm', 'componentDigest'), ('source-inputs.json', 'sourceDigest'),
                                    ('build-observation.json', 'observationDigest')):
                    data = (template + name).encode(); (directory / name).write_bytes(data); row[field] = digest(data)
                (directory / 'BUILD-COMPLETE.json').write_text(json.dumps(row), encoding='utf-8')
                builds[template] = row
            receipt = {'schemaVersion': 'latent.dotnet-capsule.qualification.v1', 'status': 'passed',
                       'binaries': native, 'builds': builds}
            source = root / 'source-inputs.json'; source.write_text(json.dumps(current), encoding='utf-8')
            receipt['sourceIdentityDigest'] = digest(source.read_bytes())
            receipt_path = root / 'qualification.json'; receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
            paths, companions, before = inherited(root)
            self.assertEqual(len(paths), 5); self.assertEqual(len(companions), 4)
            self.assertEqual(before, inherited(root)[2])
            for field, value in (('status', 'failed'), ('schemaVersion', 'latent.c-capsule.qualification.v1')):
                changed = copy.deepcopy(receipt); changed[field] = value
                receipt_path.write_text(json.dumps(changed), encoding='utf-8')
                with self.assertRaisesRegex(RuntimeError, 'observed-native-qualification-required'): inherited(root)
            receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
            source.write_text('{"source":"foreign"}', encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'prepared-source-mismatch'): inherited(root)
            changed = copy.deepcopy(receipt); changed['sourceIdentityDigest'] = digest(source.read_bytes())
            receipt_path.write_text(json.dumps(changed), encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'prepared-source-mismatch'): inherited(root)
            source.write_text(json.dumps(current), encoding='utf-8')
            receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
            selected = next(iter(companions.values())) / 'component.wasm'
            old = selected.read_bytes(); selected.write_bytes(b'changed-component')
            with self.assertRaisesRegex(RuntimeError, 'companion-bytes-mismatch'): inherited(root)
            selected.write_bytes(old)
            paths['latent'].write_bytes(b'changed-native')
            with self.assertRaisesRegex(RuntimeError, 'native-tuple-mismatch'): inherited(root)


if __name__ == '__main__':
    unittest.main()
