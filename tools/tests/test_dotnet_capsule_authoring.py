"""Outside-checkout source captures are not NativeAOT execution evidence."""
import json
import io
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from tools import build_process, qualify_rust_capsules, wait_capsule_audit_idle as audit_idle
from tools.dotnet_guest.build import build
from tools.dotnet_guest.project import create, validate
from tools.dotnet_guest.compiler import packages
from tools.dotnet_guest import runtime
from tools.build_dotnet_guest_capsules import NAMES, project
from tools.rust_capsule_project import TEMPLATES, snapshot
from tools.tests.test_build_process import _alive


class DotnetAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lsf-dotnet-authoring-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def files(self):
        return snapshot(create(self.root / "project", "greeting"))

    def test_http_managed_failure_observation_accepts_only_finite_unqualified_values(self):
        from tools.dotnet_standard_http_node import managed_failure
        for phase in ('entry', 'request-ready', 'send-begun', 'headers-ready', 'stream-ready',
                      'body-copied', 'json-parsed', 'result-ready'):
            for family in ('platform-not-supported', 'disposed', 'invalid-operation', 'not-supported',
                           'argument', 'out-of-memory', 'cancelled', 'http', 'json', 'io', 'other'):
                value = ['managed-failure-v1:' + phase + ':' + family]
                self.assertEqual(managed_failure(value), {
                    'formatVersion': 1, 'phase': phase, 'exceptionFamily': family, 'qualification': False})
        for value in (None, True, {}, [], [1], ['1:200:domain:7:ordinary'],
                      ['managed-failure-v2:entry:other'], ['managed-failure-v1:unknown:other'],
                      ['managed-failure-v1:entry:SecretSentinel'], ['managed-failure-v1:entry:other:SecretSentinel'],
                      ['managed-failure-v1:entry:other\nSecretSentinel'], ['x' * 129],
                      ['managed-failure-v1:entry:other', 'SecretSentinel']):
            with self.subTest(value=value):
                self.assertIsNone(managed_failure(value))

    def test_all_templates_capture_actual_source_and_pinned_sdk(self):
        for name in TEMPLATES:
            files = snapshot(create(self.root / name, name))
            config, lock, _pins = validate(files)
            self.assertEqual(config["world"], f"examples:{name}/service@1.0.0")
            self.assertIn(b"class ApiExportsImpl", files["src/Main.cs"])
            self.assertIn(b"latent:clock/monotonic@0.1.0", files["wit/world.wit"])
            self.assertEqual(lock["language"], "dotnet")
            self.assertEqual(json.loads(files["global.json"])["sdk"]["version"], "10.0.100")

    def test_application_source_and_authoritative_wit_remain_editable(self):
        files = self.files()
        files["src/Main.cs"] += b"\n// an application change\n"
        files["wit/world.wit"] += b"\n// a contract change\n"
        validate(files)

    def test_sdk_capture_cannot_drift(self):
        files = self.files()
        files["vendor/lsf/sdk/dotnet-guest/ownership/Owner.cs"] += b"// drift\n"
        with self.assertRaisesRegex(ValueError, "vendored SDK changed"):
            validate(files)

    def test_application_cannot_inject_msbuild_or_package_overrides(self):
        original = self.files()
        for name in ["src/Directory.Build.props", "nuget.config", "packages.lock.json", "src/evil.csproj"]:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "overrides"):
                validate({**original, name: b"<Project/>"})

    def test_compiler_configuration_is_closed(self):
        files = self.files()
        for name in ["Capsule.csproj", "global.json"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate({**files, name: files[name] + b" "})

    def test_names_and_existing_directories_are_rejected(self):
        for name in ["../escape", "", "Upper", "x;cmd", "x" * 65]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                create(self.root / "invalid", "greeting", name)
        create(self.root / "existing", "greeting")
        with self.assertRaises((ValueError, FileExistsError)):
            create(self.root / "existing", "greeting")

    def test_budgets_reject_overflow_boolean_and_zero_required_dimensions(self):
        files = self.files()
        original = json.loads(files["capsule-project.json"])
        for value in [-1, 2**64, True, 0]:
            config = {**original, "limits": {**original["limits"], "cpuFuel": value}}
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate({**files, "capsule-project.json": json.dumps(config).encode()})

    def test_all_real_sdk_sources_use_the_same_capture_path(self):
        for name in NAMES:
            config, _, _ = validate(snapshot(project(self.root / name, name)))
            self.assertEqual(config["tenant"], None if name in {"service", "callee"} else "tests")
            self.assertEqual(config["limits"]["cpuFuel"], 10_000_000_000)
            self.assertEqual(config["limits"]["memoryBytes"], (256 if name == "service" else 128) * 1024 * 1024)

    def test_nuget_uses_verified_content_identity_not_raw_signed_zip_hash(self):
        directory = self.root / "packages/test/1.0.0"
        directory.mkdir(parents=True)
        archive = directory / "test.1.0.0.nupkg"
        archive.write_bytes(b"synthetic archive; no compiler authority")
        lock = {"dependencies": {"net10.0": {"Test": {"resolved": "1.0.0", "contentHash": "verified-content"}}}}
        seen = []
        def verified(path):
            seen.append(path)
            return "verified-content"
        self.assertEqual(packages(lock, self.root / "packages", verified), {"nuget/test/1.0.0": directory})
        self.assertEqual(seen, [archive])
        with self.assertRaisesRegex(ValueError, "content hash differs"):
            packages(lock, self.root / "packages", lambda _: "different")

    def test_public_contract_rejection_precedes_compiler_work(self):
        source = create(self.root / "unsupported", "greeting")
        output = self.root / "output"
        tool = self.root / "contracts-tool"
        tool.write_bytes(b"synthetic tool identity; never executed")
        with patch("tools.dotnet_guest.build.Commands") as commands, \
                patch("tools.dotnet_guest.build.Compiler") as compiler:
            commands.return_value.records = []
            commands.return_value.run.side_effect = ValueError("unsupported-public-resource")
            with self.assertRaisesRegex(ValueError, "unsupported-public-resource"):
                build(source, output, tool, tool,
                      "https://github.com/KirilsTurkins/latent-service-fabric",
                      tools=self.root / "compiler")
            compiler.assert_not_called()
            self.assertEqual(commands.return_value.run.call_args.args[0], "contracts")
        receipt = json.loads((output / "BUILD-FAILED.json").read_text())
        self.assertEqual(receipt["stage"], "contracts")
        self.assertFalse((output / "component.wasm").exists())
        self.assertFalse((output / "BUILD-COMPLETE.json").exists())


class HttpPrefixDiagnosticTests(unittest.TestCase):
    def row(self, decoded=None, *, trapped=False):
        return {'exitCode': 4 if trapped else 0, 'decoded': decoded, 'processReaped': True,
            'response': {'outcomeKnown': True, 'requestDispatched': True,
                'category': 'platform-failure' if trapped else 'success',
                'error': {'code': 'guest-trap'} if trapped else None,
                'data': {'terminalState': 'guest_trap' if trapped else 'completed',
                    'resolvedRevision': {'publicationId': 'publication:sha256:'+'1'*64,
                        'releaseDigest': 'sha256:'+'2'*64,
                        'revisionId': 'revision-v1:sha256:'+'3'*64, 'routeGeneration': '4'}}}}

    def observe(self, original, invoke, retire, *, deadline=100, clock=1):
        from types import SimpleNamespace
        from tools import dotnet_standard_http_node as node
        result = {'artifact': {'component.wasm': {'sha256': 'sha256:'+'2'*64}}, 'cases': []}
        client, target, probe = SimpleNamespace(deadline=deadline), {'name': 'unchanged-target'}, object()
        with patch.object(node, 'invoke', side_effect=invoke), patch.object(node, 'retire', side_effect=retire), \
                patch.object(node.time, 'monotonic', return_value=clock):
            node.prefix_diagnostics(result, client, target, 'http://127.0.0.1:12345', probe, Path('owned'), original)
        self.assertEqual(client.deadline, deadline)
        self.assertEqual(result['cases'], [])
        self.assertIs(result['prefixDiagnostics']['qualification'], False)
        self.assertIs(result['prefixDiagnostics']['originalFailurePreserved'], True)
        return result['prefixDiagnostics']

    def test_all_original_csharp_operations_cleanup_and_fourteen_cases_are_preserved(self):
        import hashlib
        from tools import dotnet_standard_http_node as node
        root = Path(__file__).resolve().parents[2]
        source = (root/'examples/dotnet-standard-http/Main.cs').read_text()
        body = source[source.index('    private static string RunCore'):]
        body = body.replace(', ref Phase phase, Phase stopAfter)', ', ref Phase phase)')
        for phase, boundary in (('RequestReady', 'request-ready-plus-cleanup'),
                                ('HeadersReady', 'headers-ready-plus-cleanup'),
                                ('StreamReady', 'stream-ready-plus-cleanup'),
                                ('BodyCopied', 'body-copied-plus-cleanup')):
            checkpoint = f'if (stopAfter == Phase.{phase}) return "fixture-prefix-v1:{boundary}";'
            self.assertEqual(body.count(checkpoint), 1)
            body = ''.join(line for line in body.splitlines(keepends=True) if checkpoint not in line)
        self.assertEqual(hashlib.sha256(body.encode()).hexdigest(),
                         'd34893b3805fb2d806646611eabf8955df74aa3e5a278197fec9400d9da5e2b0')
        self.assertIn('if (which == 100) return "fixture-prefix-v1:entry-export";', source)
        self.assertIn('if (stopAfter != Phase.Entry) which = 0;', source)
        for selector, phase in ((101, 'RequestReady'), (102, 'HeadersReady'),
                                (103, 'StreamReady'), (104, 'BodyCopied')):
            self.assertIn(f'{selector} => Phase.{phase}', source)
        self.assertIn('_ => Phase.Entry', source)
        owner = (root/'tools/dotnet_standard_http_node.py').read_text()
        cases = owner[owner.index('            cases = '):owner.index('            for name, which, path, expected in cases:')]
        self.assertEqual(hashlib.sha256(cases.encode()).hexdigest(),
                         '73411b0891a2f90e53fa1d283e7c1ec89d3aed1a65285830537beacb53085305')
        self.assertIn("observation['startedRequests'] == 12", owner)
        self.assertIn('expires = min(time.monotonic()+300, deadline)', owner)
        self.assertEqual(tuple(selector for selector, _ in node.PREFIXES), (100, 101, 102, 103, 104))

    def test_only_failed_first_case_observes_and_original_exception_identity_survives(self):
        from tools import dotnet_standard_http_node as node
        observer = unittest.mock.Mock(side_effect=AssertionError('must remain failure-only'))
        node.require_case_result('json', {'exitCode': 0, 'decoded': ['expected']}, 'expected', observer)
        with self.assertRaisesRegex(RuntimeError, 'standard-dotnet-fresh-result'):
            node.require_case_result('fresh', {'exitCode': 4, 'decoded': None}, 'expected', observer)
        observer.assert_not_called()
        for failure in (RuntimeError('private-observer'), RecursionError('private-parser'), KeyboardInterrupt()):
            original = ValueError('standard-dotnet-json-result')
            with patch.object(node, 'require', side_effect=original), \
                    self.assertRaises(ValueError) as observed:
                node.require_case_result('json', {'exitCode': 4, 'decoded': None}, 'expected',
                    unittest.mock.Mock(side_effect=failure))
            self.assertIs(observed.exception, original)

    def test_five_fresh_same_revision_probes_have_idle_boundaries_and_no_acceptance_credit(self):
        from tools import dotnet_standard_http_node as node
        history = []
        def invoke(client, target, selector, url, activation):
            history.append(('invoke', selector))
            self.assertEqual(target, {'name': 'unchanged-target'})
            self.assertEqual(url, 'http://127.0.0.1:12345/conformance/json')
            self.assertEqual(activation, 'standard-prefix-'+str(selector))
            self.assertEqual(client.deadline, 100)
            return self.row(['fixture-prefix-v1:'+dict(node.PREFIXES)[selector]])
        def retire(client, target, probe, output, name):
            history.append(('idle', name))
        diagnostic = self.observe(self.row(trapped=True), invoke, retire)
        expected = [('idle', 'failed-json')]
        for selector, _ in node.PREFIXES:
            expected.extend([('invoke', selector), ('idle', 'prefix-'+str(selector))])
        self.assertEqual(history, expected)
        self.assertEqual(diagnostic['status'], 'observed')
        self.assertEqual([row['outcome'] for row in diagnostic['probes']], ['checkpoint-returned']*5)
        self.assertTrue(all(row['ownersIdle'] for row in diagnostic['probes']))

    def test_known_trap_and_closed_managed_family_remain_diagnostic_only(self):
        from tools import dotnet_standard_http_node as node
        rows = [self.row(trapped=True), self.row(['managed-failure-v1:request-ready:other'])]
        rows += [self.row(['fixture-prefix-v1:'+boundary]) for _, boundary in node.PREFIXES[2:]]
        diagnostic = self.observe(self.row(trapped=True), lambda *args: rows.pop(0), lambda *args: None)
        self.assertEqual([row['outcome'] for row in diagnostic['probes'][:2]], ['guest-trap', 'managed-failure'])
        self.assertEqual(diagnostic['probes'][1]['managedFailure'], {
            'formatVersion': 1, 'phase': 'request-ready', 'exceptionFamily': 'other', 'qualification': False})
        self.assertEqual(diagnostic['status'], 'observed')

    def test_unconfirmed_original_never_launches_or_observes_idle(self):
        import copy
        rows = [None, {}, self.row(['ordinary-success']), self.row(['managed-failure-v1:entry:other'])]
        for path, value in ((('exitCode',), True), (('processReaped',), False),
                (('response', 'outcomeKnown'), False), (('response', 'requestDispatched'), False),
                (('response', 'data', 'resolvedRevision', 'releaseDigest'), 'sha256:'+'4'*64),
                (('response', 'data', 'resolvedRevision', 'publicationId'), 'token-secret'),
                (('response', 'data', 'resolvedRevision', 'revisionId'), 'token-secret'),
                (('response', 'data', 'resolvedRevision', 'routeGeneration'), True),
                (('response', 'data', 'terminalState'), 'unknown'),
                (('response', 'error', 'code'), 'permission-denied')):
            row = copy.deepcopy(self.row(trapped=True)); current = row
            for key in path[:-1]: current = current[key]
            current[path[-1]] = value; rows.append(row)
        for row in rows:
            with self.subTest(row=row):
                invoke, retire = unittest.mock.Mock(), unittest.mock.Mock()
                self.assertEqual(self.observe(row, invoke, retire)['status'], 'not-eligible')
                invoke.assert_not_called(); retire.assert_not_called()

    def test_unknown_probe_identity_payload_or_reaping_stops_without_retry_or_private_output(self):
        import copy
        variants = [self.row(['token-secret']), self.row(['managed-failure-v1:entry:token-secret'])]
        for path, value in ((('processReaped',), False),
                (('response', 'outcomeKnown'), False),
                (('response', 'data', 'resolvedRevision', 'revisionId'), 'revision-v1:sha256:'+'4'*64),
                (('response', 'data', 'resolvedRevision', 'routeGeneration'), '5')):
            row = copy.deepcopy(self.row(['fixture-prefix-v1:entry-export'])); current = row
            for key in path[:-1]: current = current[key]
            current[path[-1]] = value; variants.append(row)
        for row in variants:
            with self.subTest(row=row):
                invoke, retire = unittest.mock.Mock(return_value=row), unittest.mock.Mock()
                diagnostic = self.observe(self.row(trapped=True), invoke, retire)
                self.assertEqual(invoke.call_count, 1)
                self.assertEqual(retire.call_count, 2 if row['processReaped'] else 1)
                self.assertNotEqual(diagnostic['status'], 'observed')
                self.assertNotIn('token-secret', json.dumps(diagnostic))

    def test_original_deadline_and_any_idle_failure_prevent_following_probes(self):
        invoke, retire = unittest.mock.Mock(), unittest.mock.Mock()
        diagnostic = self.observe(self.row(trapped=True), invoke, retire, deadline=1, clock=1)
        self.assertEqual(diagnostic['failurePhase'], 'original-deadline')
        invoke.assert_not_called(); self.assertEqual(retire.call_count, 1)
        for failure_call in (1, 2):
            calls = []
            def idle(*args):
                calls.append(args[-1])
                if len(calls) == failure_call: raise RuntimeError('private-owner-details')
            invoke = unittest.mock.Mock(return_value=self.row(['fixture-prefix-v1:entry-export']))
            diagnostic = self.observe(self.row(trapped=True), invoke, idle)
            self.assertEqual(invoke.call_count, failure_call-1)
            self.assertEqual(diagnostic['failurePhase'], 'original-retirement' if failure_call == 1 else 'prefix-retirement')
            self.assertNotIn('private-owner-details', json.dumps(diagnostic))

    def test_actual_retirement_keeps_complete_sampler_cleanup_slots_and_provider_guards(self):
        from tools import dotnet_standard_http_node as node
        inventory = {'inventory': {'topology': {'entries': [{'name': 'invocation-cleanup-slots', 'activeCount': '0'}]}}}
        usage = {'unavailable': False, 'counters': {name: '0' for name in node.ACTIVE_COUNTERS}}
        client = unittest.mock.Mock(); client.call.return_value = {'data': {'nodeUsage': usage}}
        target, probe, output = {'name': 'unchanged-target'}, object(), Path('owned')
        with patch.object(node, 'sample', return_value=inventory) as sample, patch.object(node, 'write_json') as write:
            node.retire(client, target, probe, output, 'prefix-100')
            sample.assert_called_once_with(client, probe, 'after-prefix-100', 1)
            write.assert_called_once_with(output/'after-prefix-100.json', inventory)
            client.call.assert_called_once_with('capability', 'list', '--deployment', 'unchanged-target', '--include-node-usage')
            for change in ('slots', 'unavailable', 'missing', 'active'):
                with self.subTest(change=change):
                    inventory['inventory']['topology']['entries'][0]['activeCount'] = '1' if change == 'slots' else '0'
                    usage['unavailable'] = change == 'unavailable'
                    usage['counters'] = {name: '0' for name in node.ACTIVE_COUNTERS}
                    first = next(iter(usage['counters']))
                    if change == 'missing': del usage['counters'][first]
                    if change == 'active': usage['counters'][first] = '1'
                    with self.assertRaises(RuntimeError): node.retire(client, target, probe, output, 'prefix-100')


class RuntimeProfileTests(unittest.TestCase):
    def setUp(self):
        from tools.dotnet_guest import runtime
        self.runtime = runtime

    def test_retained_http_imports_do_not_create_network_authority(self):
        emitted = ["wasi:http/types@0.2.0", "wasi:http/outgoing-handler@0.2.0",
                   "wasi:io/streams@0.2.6", "wasi:io/poll@0.2.6"]
        self.assertEqual(self.runtime.select([self.runtime.CLOCK], emitted), "closed")
        self.assertEqual(self.runtime.select([self.runtime.CLOCK, self.runtime.ACTIVATION], emitted), "runtime")

    def test_http_profile_requires_both_exact_declared_capabilities(self):
        emitted = ["wasi:http/types@0.2.0", "wasi:http/outgoing-handler@0.2.0"]
        self.assertEqual(self.runtime.select([self.runtime.CLOCK, self.runtime.HTTP, self.runtime.ACTIVATION], emitted), "http")
        self.assertEqual(self.runtime.select([self.runtime.CLOCK, self.runtime.HTTP], emitted), "closed")
        self.assertEqual(self.runtime.select([self.runtime.CLOCK, self.runtime.ACTIVATION], emitted), "runtime")

    def test_http_profile_requires_actual_outgoing_wasi_graph(self):
        declared = [self.runtime.CLOCK, self.runtime.HTTP, self.runtime.ACTIVATION]
        for emitted in ([], [self.runtime.HTTP], ["wasi:io/streams@0.2.6"],
                        ["wasi:http/types@0.2.0"], ["wasi:http/outgoing-handler@0.2.0"]):
            with self.subTest(emitted=emitted):
                self.assertEqual(self.runtime.select(declared, emitted), "runtime")
        self.assertEqual(self.runtime.select(declared, [self.runtime.HTTP, *sorted(self.runtime.WASI_HTTP_IMPORTS)]), "http")

    def test_generated_streaming_sdk_keeps_its_independent_runtime_profile(self):
        with tempfile.TemporaryDirectory(prefix="lsf-dotnet-streaming-profile-") as temporary:
            source = project(Path(temporary) / "streaming", "streaming")
            files = snapshot(source)
            validate(files)
            declared = re.findall(r"(?m)^\s*import\s+([^\s;]+);", files["wit/world.wit"].decode())
            self.assertEqual(set(declared), {self.runtime.CLOCK, self.runtime.HTTP})
            # Preflight has no emitted graph yet. The actual SDK call remains a
            # direct typed import even if NativeAOT retains unused WASI HTTP.
            self.assertEqual(self.runtime.select(declared, []), "closed")
            self.assertEqual(self.runtime.select(declared, [self.runtime.HTTP]), "closed")
            self.assertEqual(self.runtime.select(declared, [self.runtime.HTTP, *sorted(self.runtime.WASI_HTTP_IMPORTS)]), "closed")

    def test_opaque_stream_authority_cannot_enable_standard_http(self):
        self.assertEqual(self.runtime.select([self.runtime.CLOCK, self.runtime.ACTIVATION,
            "latent:network/streams@0.1.0"], ["wasi:http/outgoing-handler@0.2.0"]), "runtime")

    def test_undeclared_emitted_lsf_authority_is_rejected(self):
        for name in (self.runtime.ACTIVATION, self.runtime.HTTP, "latent:network/streams@0.1.0"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "undeclared-emitted-import"):
                self.runtime.select([self.runtime.CLOCK], [name])

    def test_unknown_wasi_versions_and_sockets_are_rejected(self):
        for name in ("wasi:http/types@0.2.1", "wasi:io/streams@0.2.0", "wasi:sockets/tcp@0.2.6"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "unsupported-wasi-import"):
                self.runtime.select([self.runtime.CLOCK, self.runtime.ACTIVATION, self.runtime.HTTP], [name])

    def test_source_ambient_authority_and_changed_profile_versions_are_rejected(self):
        for name in ("wasi:http/outgoing-handler@0.2.0", "latent:runtime/activation@0.1.1",
                     "latent:http/streaming@0.3.1"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.runtime.select([self.runtime.CLOCK, name], [])
        with self.assertRaisesRegex(ValueError, "requires-declared-monotonic-clock"):
            self.runtime.select([self.runtime.ACTIVATION, self.runtime.HTTP], [])

    def test_runtime_capture_rejects_modified_backend_sources(self):
        with tempfile.TemporaryDirectory(prefix="lsf-dotnet-runtime-capture-") as temporary:
            original = snapshot(create(Path(temporary) / "project", "greeting"))
            for path in (*self.runtime.EXAMPLES, "tools/toolchain-smoke/Cargo.toml"):
                name = "vendor/lsf/" + path
                with self.subTest(path=path), self.assertRaisesRegex(ValueError, "vendored SDK changed"):
                    validate({**original, name: original[name] + b"\n// changed backend source\n"})

    def test_actual_default_http_wall_dependency_requires_exact_declared_clock(self):
        emitted = [*sorted(self.runtime.WASI_HTTP_IMPORTS), self.runtime.WASI_WALL]
        declared = [self.runtime.CLOCK, self.runtime.HTTP, self.runtime.ACTIVATION]
        with self.assertRaisesRegex(ValueError, "http-wall-clock-requires-declaration"):
            self.runtime.select(declared, emitted)
        with self.assertRaisesRegex(ValueError, "http-wall-clock-requires-declaration"):
            self.runtime.additional(declared, emitted)
        declared.append(self.runtime.WALL)
        self.assertEqual(self.runtime.select(declared, emitted), "http")
        self.assertEqual(self.runtime.additional(declared, emitted), ("wall",))

    def test_retained_closed_wall_dependency_does_not_create_clock_authority(self):
        emitted = [self.runtime.WASI_WALL, *sorted(self.runtime.WASI_HTTP_IMPORTS)]
        declared = [self.runtime.CLOCK]
        self.assertEqual(self.runtime.select(declared, emitted), "closed")
        self.assertEqual(self.runtime.additional(declared, emitted), ())
        self.assertEqual(self.runtime.additional([*declared, self.runtime.WALL], emitted), ("wall",))
        self.assertEqual(self.runtime.additional([*declared, self.runtime.WALL], []), ())
        # The historical direct SDK path still has no activation declaration.
        self.assertEqual(self.runtime.select([*declared, self.runtime.HTTP], emitted), "closed")

    def test_wall_facet_preserves_independently_declared_entropy_and_exact_versions(self):
        declared = [self.runtime.CLOCK, self.runtime.HTTP, self.runtime.ACTIVATION,
                    self.runtime.WALL, self.runtime.RANDOM]
        emitted = [*sorted(self.runtime.WASI_HTTP_IMPORTS), self.runtime.WASI_WALL,
                   *sorted(self.runtime.WASI_INSECURE_IMPORTS)]
        self.assertEqual(self.runtime.additional(declared, emitted), ("entropy", "wall"))
        for changed in ("latent:clock/wall@0.1.1", "latent:clock/wall@0.2.0"):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, "unsupported-wall-clock-version"):
                self.runtime.select([self.runtime.CLOCK, changed], [])
        with self.assertRaisesRegex(ValueError, "unsupported-wasi-import"):
            self.runtime.select(declared, ["wasi:clocks/wall-clock@0.2.0"])
        with self.assertRaisesRegex(ValueError, "undeclared-emitted-import"):
            self.runtime.select([self.runtime.CLOCK], [self.runtime.WALL])


class AuditDrainTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lsf-audit-drain-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / "client.json"
        self.config.write_text("{}")
        self.cli = Path(sys.executable)

    def response(self, **counters):
        return {"schemaVersion": "latent.cli.result.v1", "command": "capability list",
                "category": "success", "outcomeKnown": True, "requestDispatched": True, "error": None,
                "data": {"nextPageToken": None, "nodeUsage": {"scope": "node", "unavailable": [],
                    "counters": {**dict.fromkeys((*audit_idle.COUNTERS, *audit_idle.STATES), "0"), **counters}}}}

    def raw(self, **counters):
        return json.dumps(self.response(**counters)).encode()

    def read(self, **counters):
        return subprocess.CompletedProcess([], 0, self.raw(**counters), b"")

    def wait(self, **kwargs):
        return audit_idle.wait(self.cli, self.config, "my-greeting", **kwargs)

    def assert_read_only(self, argv, options):
        self.assertEqual(argv[:6], [str(self.cli.resolve()), "--config", str(self.config.resolve()),
                                  "--output", "json", "--rpc-timeout-ms"])
        self.assertTrue(0 < int(argv[6]) <= 750)
        self.assertEqual(argv[7:], ["capability", "list", "--deployment", "my-greeting", "--include-node-usage"])
        self.assertEqual(options["cwd"], self.config.parent)
        self.assertEqual(options["max_output_bytes"], 65536)
        self.assertTrue(0 < options["timeout_seconds"] <= 1)

    def test_busy_to_idle_observations_are_only_bounded_read_only_calls(self):
        with patch.object(audit_idle, "run_bounded", side_effect=[
                self.read(audit_reserved_records="2", audit_queued_bytes="32768"),
                self.read(audit_queued_bytes="16384"), self.read()]) as run:
            result = self.wait()
        self.assertEqual(result["status"], "idle")
        self.assertEqual(result["observations"], 3)
        self.assertEqual(result["counters"], dict.fromkeys((*audit_idle.COUNTERS, *audit_idle.STATES), 0))
        for call in run.call_args_list:
            self.assert_read_only(call.args[0], call.kwargs)

    def test_every_owner_counter_must_be_present_and_zero_before_idle(self):
        for name in audit_idle.COUNTERS:
            with self.subTest(counter=name), patch.object(audit_idle, "run_bounded", side_effect=[
                    self.read(**{name: "1"}), self.read()]) as run:
                self.assertEqual(self.wait()["observations"], 2)
                self.assertEqual(run.call_count, 2)
        for name in (*audit_idle.COUNTERS, *audit_idle.STATES):
            value = self.response()
            del value["data"]["nodeUsage"]["counters"][name]
            with self.subTest(missing=name), self.assertRaisesRegex(audit_idle.AuditDrainError, "missing-counter"):
                audit_idle.counters(json.dumps(value).encode())

    def test_missing_audit_owner_closed_and_recovery_states_fail_closed(self):
        for name in audit_idle.STATES:
            with self.subTest(state=name), self.assertRaises(audit_idle.AuditDrainError):
                audit_idle.counters(self.raw(**{name: "1"}))
        for unavailable in [None, "", ["audit-owner-not-configured"], ["unrecognized"], [0]]:
            value = self.response()
            value["data"]["nodeUsage"]["unavailable"] = unavailable
            with self.subTest(unavailable=unavailable), self.assertRaisesRegex(audit_idle.AuditDrainError, "unavailable"):
                audit_idle.counters(json.dumps(value).encode())
        value = self.response()
        value["data"]["nodeUsage"]["unavailable"] = sorted(audit_idle.UNRELATED_UNAVAILABLE)
        self.assertEqual(audit_idle.counters(json.dumps(value).encode()),
                         dict.fromkeys((*audit_idle.COUNTERS, *audit_idle.STATES), 0))

    def test_counter_values_reject_malformed_numbers_and_unsigned_overflow(self):
        for value in [True, 0, -1, 0.5, "-1", "+1", "01", " 0", "1.0", str(2**64), "1" * 40, None]:
            with self.subTest(value=value), self.assertRaises(audit_idle.AuditDrainError):
                audit_idle.counters(self.raw(audit_queued_bytes=value))
        self.assertEqual(audit_idle.counters(self.raw(audit_queued_bytes=str(2**64 - 1)))["audit_queued_bytes"],
                         2**64 - 1)

    def test_malformed_paginated_ambiguous_and_unbounded_responses_are_rejected(self):
        invalid = [b"{", b"\xff", b"[]", b"{\"key\":0,\"key\":0}", b"NaN", b"0.0",
                   b" " * (audit_idle.MAX_OUTPUT_BYTES + 1)]
        for field, value in [("outcomeKnown", False), ("requestDispatched", False),
                             ("category", "platform-failure"), ("command", "deployment delete")]:
            response = self.response()
            response[field] = value
            invalid.append(json.dumps(response).encode())
        for field, value in [("nodeUsage", None), ("nextPageToken", "more")]:
            response = self.response()
            response["data"][field] = value
            invalid.append(json.dumps(response).encode())
        for raw in invalid:
            with self.subTest(shape=raw[:24]), self.assertRaises(audit_idle.AuditDrainError):
                audit_idle.counters(raw)

    def test_invalid_bounds_and_identifiers_do_not_spawn(self):
        with patch.object(audit_idle, "run_bounded") as run:
            for value in [0, -1, True, float("nan"), float("inf"), 6, 10**1000]:
                with self.assertRaises(audit_idle.AuditDrainError):
                    self.wait(timeout_seconds=value)
            for name in ["", "../secret", "--delete", "x" * 65]:
                with self.assertRaises(audit_idle.AuditDrainError):
                    audit_idle.wait(self.cli, self.config, name)
            run.assert_not_called()

    def test_observation_limit_and_deadline_stop_without_effect_retries(self):
        with patch.object(audit_idle, "run_bounded", return_value=self.read(audit_queued_bytes="1")) as run, \
                patch.object(audit_idle.time, "monotonic", return_value=0), \
                patch.object(audit_idle.time, "sleep"):
            with self.assertRaisesRegex(audit_idle.AuditDrainError, "observation-limit"):
                self.wait()
            self.assertEqual(run.call_count, 32)
        for ticks, calls in [([0, 6], 0), ([0, 0, 6], 1), ([0, 0, 0, 6], 1)]:
            with patch.object(audit_idle, "run_bounded", return_value=self.read()) as run, \
                    patch.object(audit_idle.time, "monotonic", side_effect=ticks):
                with self.assertRaisesRegex(audit_idle.AuditDrainError, "deadline"):
                    self.wait()
                self.assertEqual(run.call_count, calls)

    def test_failed_read_stops_once_and_cli_failure_discards_private_response(self):
        with patch.object(audit_idle, "run_bounded", side_effect=build_process.BuildProcessError("command-exit")) as run:
            with self.assertRaisesRegex(build_process.BuildProcessError, "command-exit"):
                self.wait()
            self.assertEqual(run.call_count, 1)
        with patch.object(audit_idle, "run_bounded", return_value=subprocess.CompletedProcess([], 0, b"PRIVATE", b"")), \
                patch("sys.stdout", new_callable=io.StringIO) as output, \
                patch("sys.stderr", new_callable=io.StringIO) as error:
            status = audit_idle.main(["--cli", str(self.cli), "--config", str(self.config), "--deployment", "my-greeting"])
        self.assertEqual(status, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(error.getvalue(), "Audit drain failed: audit-observation-invalid-json\n")

    def test_real_process_deadline_and_output_overflow_retire_owned_process(self):
        factory = build_process._new_owner
        for code, timeout, reason in [("import time; time.sleep(30)", 0.2, "command-deadline"),
                                      ("import os; os.write(1,b'x'*65537)", 5, "command-output-limit")]:
            owners = []
            def owner():
                value = factory()
                owners.append(value)
                return value
            def execute(argv, **options):
                self.assert_read_only(argv, options)
                return build_process.run_bounded([sys.executable, "-c", code], **options)
            started = time.monotonic()
            with self.subTest(reason=reason), patch.object(build_process, "_new_owner", owner), \
                    patch.object(audit_idle, "run_bounded", side_effect=execute) as run:
                with self.assertRaisesRegex(build_process.BuildProcessError, "^" + reason + "$"):
                    self.wait(timeout_seconds=timeout)
                self.assertEqual(run.call_count, 1)
            self.assertLess(time.monotonic() - started, timeout + 6)
            self.assertEqual(len(owners), 1)
            self.assertIsNotNone(owners[0].process.returncode)
            self.assertFalse(_alive(owners[0].process.pid))

    def test_helper_and_dependencies_are_captured_and_guide_deletes_only_once(self):
        from tools import qualify_java_capsules
        with patch.object(qualify_rust_capsules, "source_identity", return_value={}), \
                patch.object(qualify_rust_capsules, "directory_identity", return_value={}), \
                patch.object(qualify_rust_capsules, "file_identity", return_value={}):
            captured = {language: qualify_rust_capsules.inputs(language)["helpers"] for language in ("dotnet", "go")}
        captured["java"] = qualify_java_capsules.JAVA_HELPERS
        for language, helpers in captured.items():
            with self.subTest(language=language):
                self.assertTrue({"wait_capsule_audit_idle.py", "build_process.py", "build_process_linux.py",
                                 "build_process_windows.py", "build_process_signals.py"}.issubset(helpers))
                source = (qualify_rust_capsules.ROOT / f"docs/component-development/{language}-authoring.md").read_text()
                blocks = re.findall(r"^```bash\n(.*?)^```$", source, re.M | re.S)
                self.assertEqual(len(blocks), 6)
                deletion = language + "_cli deployment delete"
                self.assertEqual(source.count(deletion), 1)
                self.assertLess(blocks[-1].index("tools/wait_capsule_audit_idle.py"), blocks[-1].index(deletion))


if __name__ == "__main__":
    unittest.main()
