"""Real wire fixture and standard compiler capture controls for the V7 consumer."""
from contextlib import closing
import json
from pathlib import Path
import socket
import tempfile
import time
import unittest
from urllib.parse import urlsplit
from unittest.mock import patch

from tools import typescript_fetch_phase_fixture as fixture
from tools import qualify_typescript_fetch_phases as qualification
from tools import qualify_typescript_fetch_runtime as original
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import snapshot
from tools.typescript_guest.project import validate


class PhaseExecutionTests(unittest.TestCase):
    def test_closed_native_records_use_only_the_explicit_typescript_profile_bounds(self):
        from tools import typescript_phase_abort_observer as reader
        from tools import go_node_stop_timer_observer as go_reader
        raw = (b'LSF-GO-NODE-STOP-TIMER-V1|pending|start-accepted|1|32|0|1\n'
               b'LSF-GO-NODE-STOP-TIMER-V1|pending|next-entered|2|32|1|1\n'
               b'LSF-GO-NODE-STOP-TIMER-V1|drain|start-accepted|3|64|8|8\n')
        result = reader.observe(raw)
        self.assertEqual(result['status'], 'observed')
        self.assertEqual(len(result['records']), 3)
        self.assertIs(result['qualification'], False)
        self.assertEqual(go_reader.observe(raw)['status'], 'invalid-marker')
        for changed in (raw.replace(b'|64|8|8', b'|65|8|8'),
                        raw.replace(b'|64|8|8', b'|64|9|8'),
                        raw.replace(b'|64|8|8', b'|64|8|9'),
                        raw.replace(b'|drain|', b'|private|'),
                        raw.replace(b'|3|64|', b'|2|64|'), raw+raw):
            self.assertEqual(reader.observe(changed)['status'], 'invalid-marker')
        self.assertEqual(reader.observe(raw+b'LSF-GO-NODE-STOP-TIMER-V1|overflow\n')['status'], 'overflow')
        self.assertEqual(reader.observe(b'x'*262145)['status'], 'invalid-source')

    def test_nominal_dependency_preserves_every_original_type_and_removes_only_legacy_calls(self):
        import re
        source = (fixture.ROOT/'wit/platform/http-v3/package.wit').read_bytes()
        projected = fixture.nominal_type_owner(source)
        declarations = re.findall(rb'^    [a-z-]+: async func[^\n]*;\n', source, re.MULTILINE)
        self.assertEqual(len(declarations), 8)
        expected = source
        for declaration in declarations:
            expected = expected.replace(declaration, b'', 1)
        self.assertEqual(projected, expected)
        self.assertNotIn(b'func(', projected)
        for resource in (b'upload', b'body', b'chunk'):
            self.assertIn(b'resource '+resource+b';', projected)
        for changed in (source+b'\n', source.replace(b'resource upload;', b'resource foreign;'),
                        source.replace(b'option<u64>', b'option<u32>', 1), projected):
            with self.assertRaisesRegex(WorkflowError, 'nominal-canonical-preimage'):
                fixture.nominal_type_owner(changed)

    def test_declared_phase_profile_captures_its_manifest_without_changing_legacy_or_transaction_authority(self):
        from tools import guest_compatibility_build as compatibility
        from tools.dev_workflow.common import DevError
        from tools.rust_capsule_project import inventory, read_file

        phase = {'imports': [fixture.HTTP, original.ACTIVATION]}
        self.assertEqual(compatibility.declared_host_abi(phase), 'lsf-host-abi-phase3-v7')
        self.assertEqual(compatibility.declared_host_abi({'imports': {fixture.HTTP: {}}}),
                         'lsf-host-abi-phase3-v7')
        for imports, expected in (([], 'lsf-host-abi-phase3-v4'),
                ([original.HTTP], 'lsf-host-abi-phase3-v4'),
                ([original.ACTIVATION], 'lsf-host-abi-phase3-v5'),
                (['latent:http/phase-timing@0.5.0', original.ACTIVATION], 'lsf-host-abi-phase3-v5'),
                (['latent:state/key-value@0.2.0'], 'lsf-host-abi-phase4-v1')):
            self.assertEqual(compatibility.declared_host_abi({'imports': imports}), expected)
        for transaction in compatibility.TRANSACTION_INTERFACES:
            with self.assertRaisesRegex(DevError, 'phase-transaction-profile-unsupported'):
                compatibility.declared_host_abi({'imports': [fixture.HTTP, transaction]})
        original_files = {name: read_file(compatibility.ROOT/name) for name in compatibility.RECIPE}
        original_record = inventory(original_files)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            captured = dict(original_files)
            updated = compatibility.capture_host_recipe(path, captured, original_record, phase)
            selected = 'wit/host-abi-phase3-v7.json'
            self.assertEqual(set(captured)-set(original_files), {selected})
            self.assertTrue(all(captured[name] == raw for name, raw in original_files.items()))
            self.assertEqual(captured[selected], read_file(compatibility.ROOT/selected))
            self.assertEqual(updated, inventory(captured))
            self.assertEqual((path/'recipe-inputs.json').read_bytes(), updated)
            stale = dict(original_files)
            stale['tools/guest_compatibility_build.py'] += b'\n# changed after capture\n'
            with self.assertRaisesRegex(DevError, 'compatibility-stale-recipe'):
                compatibility.capture_host_recipe(path, stale, inventory(stale), phase)

    def test_real_peer_writes_exact_empty_and_latin1_without_changing_body(self):
        authorization = b'Bearer '+b'0'*64
        with closing(fixture.PhasePeer(authorization, maximum_seconds=10)) as peer:
            for vector, expected in [('http-404', b'HTTP/1.1 404 \r\n'),
                                     ('http-500', b'HTTP/1.1 500  Caf\xff \r\n')]:
                address = urlsplit(peer.url(vector))
                with socket.create_connection((address.hostname, address.port), timeout=2) as client:
                    client.sendall(b'GET '+address.path.encode()+b' HTTP/1.1\r\nHost: '
                        +address.netloc.encode()+b'\r\nAuthorization: '+authorization+b'\r\n\r\n')
                    client.setblocking(False)
                    raw = bytearray()
                    expires = time.monotonic()+3
                    while True:
                        self.assertLess(time.monotonic(), expires)
                        peer.poll(.001)
                        try:
                            part = client.recv(8192)
                        except BlockingIOError:
                            continue
                        if not part:
                            break
                        raw.extend(part)
                        self.assertLess(len(raw), 8192)
                    self.assertTrue(raw.startswith(expected))
                    head, body = raw.split(b'\r\n\r\n')
                    self.assertIn(b'Content-Length: '+str(len(body)).encode(), head)
                    self.assertEqual(json.loads(body)['status'], int(vector[-3:]))
            self.assertEqual(peer.observation()['completedResponseWrites'], 2)

    def test_wire_rewrite_is_closed_to_exact_fixed_status_preimages(self):
        for vector in ('http-404', 'http-500'):
            with self.assertRaises((WorkflowError, ValueError)):
                fixture.wire_prefix(b'HTTP/1.1 200 OK\r\n\r\n', vector)
        untouched = b'HTTP/1.1 200 Fixture\r\nContent-Length: 0\r\n\r\n'
        self.assertIs(fixture.wire_prefix(untouched, 'domain-json'), untouched)

    def test_phase_project_keeps_public_package_sources_and_immutable_sdk_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            old = original.project(directory/'original')
            app = fixture.project(directory/'phase')
            manifest, lock, _ = validate(snapshot(app))
            self.assertEqual(manifest, json.loads((old/'capsule-project.json').read_bytes()))
            self.assertEqual(lock['sdk'], json.loads((old/'sdk-lock.json').read_bytes())['sdk'])
            self.assertEqual((app/'src/default-client.ts').read_text(),
                fixture.published.CLIENT.replace('@PRIVATE@', fixture.PRIVATE_NAME))
            self.assertEqual((app/'src/main.ts').read_bytes(), (fixture.ROOT/fixture.SOURCE).read_bytes())
            self.assertIn(b'import latent:http/phase-timing@0.4.0;', (app/'wit/world.wit').read_bytes())
            self.assertIn(b'package latent:http@0.3.0;', (app/'wit/deps/http-v3/package.wit').read_bytes())

    def test_selected_configuration_supplies_only_explicit_phase_binding_and_original_client_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            startup = {'destinations': [], 'origins': {}}
            (directory/'node').mkdir()
            (directory/'releases').mkdir()
            (directory/'releases/policy.json').write_bytes(b'{}\n')
            path, owner = qualification.configuration(directory/'node', directory/'releases', startup,
                                                       directory/'credential')
            value = json.loads(path.read_bytes())
            self.assertIs(value['providers']['httpStreaming']['phaseTiming'], True)
            contracts = [row['contract'] for row in value['providers']['bindings']]
            self.assertIn(fixture.HTTP, contracts)
            self.assertNotIn(original.HTTP, contracts)
            self.assertEqual(owner['limits'], qualification.published.CLIENT_OWNER_LIMITS)
            self.assertEqual(value['budgetProfile']['maximumOutboundRequests'], 1)

    def test_grants_require_the_actual_phase_provider_and_never_authorize_legacy_calls(self):
        descriptors = [{'id': name, 'capability': capability, 'profile': profile,
                        'configurationDigest': 'sha256:'+'1'*64}
            for name, (capability, profile, _operation, _kind) in original.profiles('java').items()]
        descriptors += [{'id': 'activation', 'capability': original.ACTIVATION,
                         'profile': 'activation-owned-v1', 'configurationDigest': 'sha256:'+'2'*64},
                        {'id': 'http-standard', 'capability': fixture.HTTP,
                         'profile': 'bounded-streaming-http-phase-timing-v1',
                         'configurationDigest': 'sha256:'+'3'*64}]
        node = type('Node', (), {'startup_record': {'providers': descriptors}})()
        origin = {'scheme': 'http', 'host': '127.0.0.1', 'port': 1234}
        with patch.object(qualification, 'policy') as policy:
            runtime, authorized = qualification.grants(object(), node, 'publication', origin)
        self.assertNotIn(fixture.HTTP, [row['capability'] for row in runtime])
        self.assertEqual(authorized[-1], {'capability': fixture.HTTP, 'policy': 'http-allow'})
        documents = [row.args[3] for row in policy.call_args_list]
        self.assertFalse(any(row.get('capability') == original.HTTP for row in documents))
        rules = [row['rules'][0] for row in documents if 'rules' in row]
        self.assertTrue(all(row['publications'] == ['publication'] and row['services'] == [original.SERVICE]
                            for row in rules))
        http = next(row for row in rules if row['capability'] == fixture.HTTP)
        self.assertEqual(http['resources']['origins'], [origin])
        self.assertEqual(http['resources']['methods'], ['GET', 'POST'])
        self.assertEqual(http['resources']['pathPrefixes'], [])
        descriptors[-1]['profile'] = 'bounded-streaming-http-identity-v1'
        with patch.object(qualification, 'policy'), self.assertRaisesRegex(WorkflowError, 'phase-fetch-http-provider'):
            qualification.grants(object(), node, 'publication', origin)


if __name__ == '__main__':
    unittest.main()
