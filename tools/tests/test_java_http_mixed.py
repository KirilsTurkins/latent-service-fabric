"""Body controller and host-language boundaries; signed evidence is separate."""
import copy
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import java_http_mixed_fixture as fixture
from tools import java_http_mixed_node as node
from tools import qualify_java_http_mixed as campaign
from tools.build_observation import build_environment
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT, digest, read_json


class JavaHttpMixed(unittest.TestCase):
    def test_pending_observer_failure_retains_partial_streams_and_preserves_original_exception(self):
        selected = {'revisionId': 'revision:owned'}
        gate = SimpleNamespace(request=1, phase='body')
        process = Mock();process.owner.exited.return_value = False;process.owner.finished = False
        process.buffers = [bytearray(b'public-partial-result'), bytearray(b'public-partial-diagnostic')]
        peer = Mock();peer.origin.return_value = {'host': '127.0.0.1', 'port': 1234}
        peer.gates.return_value = [gate]
        peer.observation.return_value = {'failure': None, 'requests': [], 'openConnections': 1}
        original = RuntimeError('original-observer-failure')
        process.close.side_effect = OSError('cleanup-also-failed')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);client = SimpleNamespace(deadline=1e20, evidence=root)
            with patch.object(node, 'selected_revision', return_value=selected), \
                    patch.object(node, 'start_call', return_value=process), \
                    patch.object(node, 'finish_call') as finish, \
                    patch.object(node, 'sample', side_effect=original):
                with self.assertRaises(RuntimeError) as raised:
                    node.invoke(client, Mock(), {'name': 'owned', 'budget': {}}, peer, Mock(), 2, 'held-body')
            self.assertIs(raised.exception, original);finish.assert_not_called();process.close.assert_called_once()
            self.assertEqual((root/'held-body-partial.stdout').read_bytes(), bytes(process.buffers[0]))
            self.assertEqual((root/'held-body-partial.stderr').read_bytes(), bytes(process.buffers[1]))
            retained = read_json(root/'held-body-partial-failure.json')
            self.assertFalse(retained['qualification']);self.assertFalse(retained['processReaped'])
            self.assertEqual(retained['phase'], 'pending-owner')
            self.assertEqual(retained['gate'], {'request': 1, 'phase': 'body'})
            self.assertFalse(read_json(root/'held-body-cleanup-refusal.json')['ownedProcessCleanupConfirmed'])

    def test_released_body_is_never_released_again_while_guest_completion_is_pending(self):
        from tools.phase3_resource_profile import ACTIVE_COUNTERS
        selected = {'revisionId': 'revision:owned'}
        ticks = [0];gate = SimpleNamespace(request=1, phase='body')
        process = Mock();process.owner.exited.side_effect = lambda: ticks[0] >= 3
        peer = Mock();peer.origin.return_value = {'host': '127.0.0.1', 'port': 1234}
        observation = {'failure': None, 'requests': [{}, {}], 'openConnections': 0}
        peer.observation.side_effect = [dict(observation, requests=[])] + [observation]*10
        peer.poll.side_effect = lambda _delay: ticks.__setitem__(0, ticks[0]+1)
        peer.gates.side_effect = lambda: [gate] if peer.release.call_count == 0 else []
        row = {'processReaped': True, 'exitCode': 0, 'decoded': [node.EXPECTED[2]], 'response': {
            'outcomeKnown': True, 'data': {'resolvedRevision': selected, 'consumption': {'outboundRequests': '2'}}}}
        with tempfile.TemporaryDirectory() as temporary:
            client = SimpleNamespace(deadline=1e20, evidence=Path(temporary))
            with patch.object(node, 'selected_revision', return_value=selected), \
                    patch.object(node, 'start_call', return_value=process) as start, \
                    patch.object(node, 'finish_call', return_value=row), \
                    patch.object(node, 'sample', return_value={'owned': True}), \
                    patch.object(node.phase, 'usage', side_effect=[
                        {'counters': {key: '1' for key in ACTIVE_COUNTERS}},
                        {'counters': {key: '0' for key in ACTIVE_COUNTERS}}]), \
                    patch.object(node, 'ready_sibling', return_value=True), \
                    patch.object(node, 'validate_peer'):
                value = node.invoke(client, Mock(), {'name': 'owned', 'budget': {'unchanged': True}},
                    peer, Mock(), 2, 'held-body')
            peer.release.assert_called_once_with(gate);start.assert_called_once()
            process.close.assert_called_once()
            self.assertTrue(value['receipt']['bytes'] > 0)

    def test_every_result_requires_exact_revision_single_use_counts_and_known_retirement(self):
        selected = {'revisionId': 'revision:owned'}
        for mode in range(len(fixture.CASES)):
            row = {'processReaped': True, 'exitCode': 0, 'decoded': [node.EXPECTED[mode]],
                'response': {'outcomeKnown': True, 'category': 'success', 'data': {
                    'resolvedRevision': selected, 'consumption': {'outboundRequests': str(node.CONTACTS[mode])}}}}
            if mode == 7:
                row.update(exitCode=4, decoded=None)
                row['response'].update(category='platform-failure', error={'code': 'cancelled'})
                row['response']['data']['terminalState'] = 'cancelled'
            node.validate_result(row, mode, selected)
            for field in ('unreaped', 'unknown', 'other-revision', 'replayed', 'wrong-result'):
                value = copy.deepcopy(row)
                if field == 'unreaped': value['processReaped'] = False
                elif field == 'unknown': value['response']['outcomeKnown'] = False
                elif field == 'other-revision': value['response']['data']['resolvedRevision'] = {'revisionId': 'foreign'}
                elif field == 'replayed': value['response']['data']['consumption']['outboundRequests'] = str(node.CONTACTS[mode]+1)
                else: value.update(exitCode=0, decoded=['1:invented-success'])
                with self.subTest(mode=mode, mutation=field), self.assertRaises(WorkflowError):
                    node.validate_result(value, mode, selected)
        for invalid in (-1, True, 10):
            with self.assertRaises(WorkflowError): node.validate_result({}, invalid, selected)

    def test_project_retains_exact_phase_world_sdk_and_original_client_declarations(self):
        from tools.java_http_phase_fixture import project as original
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = original(root/'before');after = fixture.project(root/'after')
            for name in ('capsule-project.json', 'java-dependencies.json', 'wit/world.wit'):
                self.assertEqual((before/name).read_bytes(), (after/name).read_bytes())
            self.assertEqual((after/'src/dev/latent/app/Capsule.java').read_bytes(), (ROOT/fixture.SOURCE).read_bytes())
            for path in (before/'vendor').rglob('*'):
                if path.is_file(): self.assertEqual(path.read_bytes(), (after/path.relative_to(before)).read_bytes())
            old = read_json(before/'sdk-lock.json');new = read_json(after/'sdk-lock.json')
            new.pop('template');old.pop('template');self.assertEqual(old, new)
            limits = read_json(after/'capsule-project.json')['limits']
            self.assertEqual((limits['cpuFuel'], limits['memoryBytes'], limits['outboundRequests'],
                limits['wallTimeLimitMillis']), (1_000_000_000, 67108864, 8, 120000))

    def test_compiler_cache_resolves_only_strict_original_configurations_without_guest_compile(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            compiler = Mock();compiler.directory = output/'compiler-acquisition'
            compiler.directory.mkdir();compiler.records = [{'stage': 'public-dependency-acquisition'}]
            with patch.object(campaign, 'Compiler', return_value=compiler), \
                    patch.object(campaign, 'read_only_dependency_cache', side_effect=lambda path: path), \
                    patch.object(campaign, 'tool_inventory', return_value=b'captured-public-cache'):
                chosen = campaign.compiler_cache(output/'wasi-sdk', output, 100)
            compiler.compile.assert_not_called()
            compiler.run.assert_called_once_with('pinned-compiler-dependency-acquisition', 'gradle',
                '--no-daemon', 'captureCompilerDependencies', cwd=compiler.directory/'project')
            compiler.check_unchanged.assert_called_once()
            self.assertEqual(chosen, compiler.directory/'gradle-home/caches/modules-2')
            build = (compiler.directory/'project/build.gradle').read_bytes()
            self.assertEqual(build, (ROOT/'sdk/java-guest/compiler.gradle').read_bytes()+campaign.CACHE_TASK.encode())
            self.assertEqual((compiler.directory/'project/gradle/verification-metadata.xml').read_bytes(),
                (ROOT/'sdk/java-guest/feasibility/gradle/verification-metadata.xml').read_bytes())
            receipt = read_json(output/'compiler-cache-selection.json')
            self.assertEqual(receipt['guestComponentsCompiled'], 0)
            self.assertEqual(receipt['nativeProductsCompiled'], 0)
            self.assertEqual(receipt['taskDigest'], digest(campaign.CACHE_TASK.encode()))

    def test_gate_release_requires_same_request_and_completed_sibling_after_pending_event(self):
        from tools.java_http_fiber_node import ready_sibling
        gate = SimpleNamespace(request=1, phase='body')
        observed = {'requests': [{'request': 2, 'role': 'primary', 'vector': 'domain-json',
            'closeReason': 'response-write-complete'}], 'events': [
            {'kind': 'gate-pending', 'request': 1, 'phase': 'body', 'sequence': 3},
            {'kind': 'response-write-complete', 'request': 2, 'sequence': 4}]}
        self.assertTrue(ready_sibling(observed, 0, gate))
        for kind in ('prior-response', 'not-complete', 'foreign-gate', 'wrong-role'):
            changed = copy.deepcopy(observed);selected = gate
            if kind == 'prior-response': changed['events'][1]['sequence'] = 2
            elif kind == 'not-complete': changed['requests'][0].pop('closeReason')
            elif kind == 'wrong-role': changed['requests'][0]['role'] = 'secondary'
            else: selected = SimpleNamespace(request=8, phase='body')
            self.assertFalse(ready_sibling(changed, 0, selected))

    def test_response_boundary_is_exact_wire_bytes_and_existing_oversize_stays_distinct(self):
        from tools.standard_http import vectors
        request = SimpleNamespace(method=b'GET')
        prefix, suffix = vectors.response(vectors.BY_ID['response-boundary'], request, 1000)
        self.assertEqual(suffix, b'')
        headers, body = prefix.split(b'\r\n\r\n', 1)
        self.assertIn(b'Content-Length: 8192\r\n', headers+b'\r\n')
        self.assertEqual(body, b'x'*8192)
        old, _ = vectors.response(vectors.BY_ID['oversized-body'], request, 1000)
        self.assertEqual(len(old.split(b'\r\n\r\n', 1)[1]), 65536)

    @unittest.skipUnless(shutil.which('javac'), 'Host JDK required for checked-signature source control')
    def test_actual_fixture_compiles_with_checked_json_and_io_signatures(self):
        # Public API signatures only. This is neither a published-JAR nor guest
        # execution claim; those remain mandatory in the owning signed lane.
        sources = {
            'dev/latent/generated/Bindings.java': 'package dev.latent.generated; public final class Bindings { public interface Exports { String run(Long which, String endpoint); }}',
            'com/github/kevinsawicki/http/HttpRequest.java': '''package com.github.kevinsawicki.http;
                public final class HttpRequest { public static HttpRequest get(String value) { return new HttpRequest(); }
                public int code() { return 200; } public void disconnect() {}
                public HttpRequest receive(java.io.OutputStream output) { return this; } }''',
            'org/json/JSONException.java': 'package org.json; public final class JSONException extends Exception {}',
            'org/json/JSONObject.java': '''package org.json; public final class JSONObject {
                public JSONObject(String value) throws JSONException {}
                public String getString(String key) throws JSONException { return ""; }
                public boolean getBoolean(String key) throws JSONException { return true; }}'''}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);paths = []
            for name, source in sources.items():
                path = root/name;path.parent.mkdir(parents=True, exist_ok=True);path.write_text(source);paths.append(str(path))
            paths += [str(ROOT/fixture.SOURCE), str(ROOT/'sdk/java-guest/client/dev/latent/guest/client/HttpFailure.java')]
            command = [shutil.which('javac'), '-J-Xmx128m', '--release', '17', '-encoding', 'UTF-8',
                '-Xmaxerrs', '8', '-d', str(root/'classes'), *paths]
            result = subprocess.run(command, cwd=root, env=build_environment(root),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
            self.assertLessEqual(len(result.stdout), 262144)
            self.assertEqual(result.returncode, 0, result.stdout.decode('utf-8', 'replace'))


if __name__ == '__main__':
    unittest.main()
