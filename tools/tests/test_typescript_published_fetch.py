"""Source/receipt refusals; these do not replace actual native qualification."""
from copy import copy, deepcopy
from contextlib import closing
import json
from pathlib import Path
import tempfile
import socket
import time
import unittest
import zipfile

from tools import qualify_typescript_published_fetch as qualify
from tools import typescript_fetch_replay_inputs as inputs
from tools import typescript_published_fetch_fixture as fixture
from tools.phase2_operator_process import WorkflowError
from tools.standard_http.peer import Peer


class PublishedFetchTests(unittest.TestCase):
    def test_owner_dimension_probes_change_only_their_named_original_ceiling(self):
        with tempfile.TemporaryDirectory() as temporary:
            for probe,key,value in [('task-only','tasks',64),('queue-only','queuedWork',64),('native-only','nativeOwners',256)]:
                path=Path(temporary)/(probe+'.json')
                original={'providers':{'activationRuntime':{'limits':dict(qualify.base.OWNER_LIMITS)}}}
                path.write_text(json.dumps(original))
                self.assertEqual(qualify.owner_probe_configuration(path,probe),{**qualify.base.OWNER_LIMITS,key:value})
                self.assertEqual(json.loads(path.read_bytes())['providers']['activationRuntime']['limits'],{**qualify.base.OWNER_LIMITS,key:value})
            path=Path(temporary)/'unknown.json';path.write_text(json.dumps(original));before=path.read_bytes()
            with self.assertRaisesRegex(WorkflowError,'probe-selection'):
                qualify.owner_probe_configuration(path,'arbitrary-profile')
            self.assertEqual(path.read_bytes(),before)

    def test_owner_probe_is_separate_bounded_and_preserves_every_other_node_setting(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'config.json'
            original={'providers':{'activationRuntime':{'limits':dict(qualify.base.OWNER_LIMITS)}},
                'execution':{'maximumWallTimeMillis':120000},'budgetProfile':{'maximumOutboundRequests':1}}
            path.write_text(json.dumps(original))
            changed=qualify.owner_probe_configuration(path)
            self.assertEqual(changed,{**qualify.base.OWNER_LIMITS,'tasks':64,'queuedWork':64,'nativeOwners':256})
            actual=json.loads(path.read_bytes())
            actual['providers']['activationRuntime']['limits']=dict(qualify.base.OWNER_LIMITS)
            self.assertEqual(actual,original)
            with self.assertRaisesRegex(WorkflowError,'original-limits'):
                qualify.owner_probe_configuration(path)
        self.assertEqual(qualify.base.OWNER_LIMITS['tasks'],16)
        self.assertEqual(qualify.base.OWNER_LIMITS['queuedWork'],16)
        self.assertEqual(qualify.base.OWNER_LIMITS['nativeOwners'],64)

    def test_failed_client_is_recorded_as_failure_and_never_relabelled_success(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            client=type('Client',(),{'evidence':Path(temporary)})()
            row={'exitCode':4,'decoded':None}
            with patch('tools.capsule_invocation_diagnostics.capture') as capture:
                self.assertIs(qualify.checked_client_result(client,row,'1|ky:expected','ky-json'),False)
                capture.assert_called_once_with(client,row)
            expected=['buffered-reader-probe','buffered-json-probe']+[row[0] for row in qualify.VECTORS]
            qualify.require_original_clients(expected,[])
            with self.assertRaises(WorkflowError):qualify.require_original_clients(expected,['ky-json'])
            with self.assertRaises(WorkflowError):qualify.require_original_clients(expected[:-1],[])

    def test_reader_probes_and_closed_diagnostics_cannot_replace_client_success(self):
        self.assertIn(b"mode === 5",fixture.MAIN)
        self.assertIn(b"mode === 6",fixture.MAIN)
        self.assertIn(b"catch (error) { return diagnostic(error); }",fixture.MAIN)
        self.assertIn(b"labels.get(error.message) ?? 'unknown'",fixture.MAIN)
        self.assertNotIn(b'${error.message}',fixture.MAIN)
        self.assertEqual(qualify.VECTORS[0],('ky-json',0,'/conformance/json','ky:'))

    def test_artifact_run_head_is_distinct_from_exact_compiled_pull_request_merge(self):
        identity,size,sha=inputs.ARTIFACTS['engine']
        metadata={'id':identity,'size_in_bytes':size,'digest':'sha256:'+sha,'expired':False,
                  'workflow_run':{'id':inputs.RUN,'head_sha':inputs.RUN_HEAD}}
        inputs.artifact_metadata(metadata,identity,size,sha)
        self.assertNotEqual(inputs.SOURCE,inputs.RUN_HEAD)
        self.assertEqual(inputs.MERGE_PARENTS[1],inputs.RUN_HEAD)
        for key,value in (('id',identity+1),('size_in_bytes',size+1),('digest','sha256:'+'0'*64),('expired',True)):
            changed=deepcopy(metadata); changed[key]=value
            with self.subTest(key=key),self.assertRaises(WorkflowError):
                inputs.artifact_metadata(changed,identity,size,sha)
        for key,value in (('id',inputs.RUN+1),('head_sha',inputs.SOURCE)):
            changed=deepcopy(metadata); changed['workflow_run'][key]=value
            with self.subTest(key=key),self.assertRaises(WorkflowError):
                inputs.artifact_metadata(changed,identity,size,sha)

    def test_caller_uses_original_global_clients_and_original_world_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = fixture.project(Path(temporary)/'project', 'outside-fetch-alpha')
            value = json.loads((app/'capsule-project.json').read_bytes())
            self.assertEqual(value['world'], 'examples:typescript-fetch/service@1.0.0')
            self.assertEqual(value['limits']['outboundRequests'], 1)
            self.assertEqual(value['limits']['memoryBytes'], 134217728)
            self.assertEqual(value['limits']['wallTimeLimitMillis'], 120000)
            caller = (app/'src/default-client.ts').read_text()
            self.assertIn("import ky, {HTTPError} from 'ky'", caller)
            self.assertIn("import wretch from 'wretch'", caller)
            self.assertIn("await ky.get(url).json()", caller)
            self.assertIn("await wretch(url).get().json()", caller)
            self.assertNotRegex(caller, r'\bfetch\s*:\s*(?:[a-zA-Z_({])')
            self.assertIn("from 'outside-fetch-alpha'", caller)
            self.assertNotIn('latent:', caller)

    def test_outside_identity_cannot_escape_its_owned_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            for name in ('../escape', '@scope/name', 'outside-fetch-../escape', 'outside-fetch-'):
                with self.subTest(name=name), self.assertRaises(WorkflowError):
                    fixture.project(Path(temporary)/'never-created', name)

    def test_private_source_is_transitive_ordinary_fetch_client_and_variants_differ(self):
        self.assertIn(b"import wretch from 'wretch'", fixture.PRIVATE)
        self.assertIn(b'return await wretch(url).get().json()', fixture.PRIVATE)
        self.assertNotIn(b'fetch: ', fixture.PRIVATE)
        self.assertEqual(len(set(qualify.IDENTITIES)), 2)
        self.assertEqual(len({name for name, _version in qualify.IDENTITIES}), 2)
        self.assertEqual(len({version for _name, version in qualify.IDENTITIES}), 2)
        self.assertEqual(fixture.PACKAGES, {'ky':'2.2.0','wretch':'3.0.9'})

    def test_default_error_helper_unsupported_is_never_claimed_as_http_error_qualification(self):
        errors = [row for row in qualify.VECTORS if row[2].endswith('/404')]
        self.assertEqual(len(errors), 2)
        self.assertEqual(errors[0], ('ky-http404-unsupported',3,'/conformance/status/404','ky:unsupported:response-status-text'))
        self.assertEqual(errors[1], ('wretch-http404-error',4,'/conformance/status/404','wretch:error:404'))
        self.assertIn("error.message === 'lsf-fetch-buffered-v1:unsupported:response-status-text'", fixture.CLIENT)
        self.assertNotIn('throwHttpErrors: false', fixture.CLIENT)
        self.assertNotIn('ignoreResponseError: true', fixture.CLIENT)

    def test_fixed_archive_members_reject_duplicate_unsafe_and_missing_inputs(self):
        entries = [zipfile.ZipInfo('engine.wasm'), zipfile.ZipInfo('engine-input.json')]
        for item in entries: item.file_size=8
        self.assertEqual(inputs.members('engine', entries), entries)
        for invalid in (entries[:1], entries+[copy(entries[0])]):
            with self.assertRaises(WorkflowError): inputs.members('engine', invalid)
        for field, value in (('external_attr',0o120777 << 16), ('flag_bits',1), ('file_size',0), ('file_size',193*1024**2)):
            invalid = deepcopy(entries); setattr(invalid[0],field,value)
            with self.subTest(field=field,value=value), self.assertRaises(WorkflowError):
                inputs.members('engine',invalid)
        invalid=[zipfile.ZipInfo('splicer/../escape'),zipfile.ZipInfo('splicer-input.json')]
        for item in invalid: item.file_size=8
        with self.assertRaises(WorkflowError): inputs.members('splicer',invalid)

    def test_native_inputs_reject_fabricated_current_receipts_before_using_binaries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'qualification.json').write_text(json.dumps({'status':'passed','source':'current'}))
            with self.assertRaisesRegex(WorkflowError,'original-normal-preimage'):
                inputs.native_inputs(root)

    def test_peer_requires_all_six_exact_authorized_contacts(self):
        self.assertEqual([row[1] for row in qualify.VECTORS], [0,1,2,3,4,0])
        credential = b'Bearer '+b'0'*64
        with closing(Peer(credential, maximum_seconds=10)) as peer:
            origin = peer.origin('primary')
            for _name, _mode, path, _expected in qualify.VECTORS:
                with socket.create_connection((origin['host'], origin['port']), timeout=2) as connection:
                    host = f"127.0.0.1:{origin['port']}".encode()
                    connection.sendall(b'GET '+path.encode()+b' HTTP/1.1\r\nHost: '+host+
                                       b'\r\nAuthorization: '+credential+b'\r\n\r\n')
                    connection.setblocking(False)
                    deadline, received = time.monotonic()+2, b''
                    while True:
                        peer.poll(.001)
                        try: chunk = connection.recv(4096)
                        except BlockingIOError: chunk = None
                        if chunk == b'': break
                        if chunk is not None: received += chunk
                        self.assertLess(time.monotonic(),deadline)
                    self.assertTrue(received.startswith(b'HTTP/1.1 '))
            peer.close()
            observation=peer.observation()
        self.assertEqual(qualify.peer_evidence(observation),observation)
        for key, value in (('startedRequests',7),('committedMutations',1),('openConnections',1)):
            with self.subTest(key=key), self.assertRaises((ValueError,WorkflowError)):
                qualify.peer_evidence(dict(observation,**{key:value}))


if __name__ == '__main__':
    unittest.main()
