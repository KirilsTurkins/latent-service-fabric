"""Finite evidence guards and real adapter/peer controls, not native qualification."""
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from tools import qualify_typescript_fetch_runtime as fetch
from tools.phase2_operator_process import WorkflowError
from tools.standard_http.peer import Peer


class TypeScriptFetchRuntimeTests(unittest.TestCase):
    def write(self, path, value):
        path.write_text(json.dumps(value)+'\n', encoding='utf-8')

    def evidence(self, root):
        (root/'package').mkdir()
        (root/'component.wasm').write_bytes(b'\0asm\x0d\0\x01\0')
        selected = {'profile': fetch.IMPORT_PROFILE, 'qualification': 'unknown', 'apiSupport': 'not-evaluated'}
        for name, value in (('source-inputs.json', {'files': []}), ('recipe-inputs.json', {'files': []}),
                            ('package-inputs.json', {'files': []}), ('typescript-runtime-selection.json', selected)):
            self.write(root/name, value)
        component = fetch.file_identity(root/'component.wasm')
        observation = {'componentDigest': component['sha256'], 'componentSize': component['bytes'],
            'parameters': {'compiler': 'componentize-js', 'bindings': 'jco', 'language': 'typescript',
                'target': 'wasm32-component', 'runtime': 'spidermonkey', 'ambientWasi': False},
            'materials': []}
        for name, file in (('build-recipe', 'recipe-inputs.json'), ('package-inputs', 'package-inputs.json'),
                           ('typescript-runtime-selection', 'typescript-runtime-selection.json')):
            identity = fetch.file_identity(root/file)
            observation['materials'].append({'name': name, 'digest': identity['sha256'], 'size': identity['bytes']})
        self.write(root/'build-observation.json', observation)
        complete = {'packageAssembled': True, 'componentDigest': component['sha256'],
            'sourceDigest': fetch.file_identity(root/'source-inputs.json')['sha256'],
            'observationDigest': fetch.file_identity(root/'build-observation.json')['sha256']}
        self.write(root/'BUILD-COMPLETE.json', complete)
        return complete, observation, selected

    def test_normal_captured_fixture_keeps_exact_async_world_sdk_and_original_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            app = fetch.project(Path(directory)/'application')
            project, lock, _pins = fetch.validate(fetch.snapshot(app))
            self.assertEqual(project['runtimeProfile'], fetch.IMPORT_PROFILE)
            self.assertEqual(project['world'], 'examples:typescript-fetch/service@1.0.0')
            self.assertEqual(project['service'], fetch.SERVICE)
            self.assertEqual(project['limits']['outboundRequests'], 1)
            self.assertEqual(project['limits']['memoryBytes'], 134217728)
            self.assertEqual(project['limits']['wallTimeLimitMillis'], 120000)
            for name in ('main.ts', 'default-client.ts'):
                self.assertEqual((app/'src'/name).read_bytes(), (fetch.ROOT/fetch.FIXTURE/name).read_bytes())
            self.assertEqual(lock['template']['sourceDigest'], fetch.digest((app/'src/main.ts').read_bytes()))
            self.assertEqual(lock['template']['witDigest'], fetch.digest((app/'wit/world.wit').read_bytes()))

    def test_native_selection_cannot_fall_back_between_prepared_and_ordinary_inputs(self):
        with patch.object(fetch, 'prepared_native') as prepared, patch.object(fetch, 'ordinary_tuple') as ordinary:
            for native, receipt, captured in ((None, None, None), (Path('native'), None, None),
                    (None, Path('tuple.json'), None), (Path('native'), None, Path('prepared')),
                    (None, Path('tuple.json'), Path('prepared'))):
                with self.subTest(native=native, receipt=receipt, captured=captured), self.assertRaises(WorkflowError):
                    fetch.native_inputs(native, receipt, captured)
            prepared.assert_not_called()
            ordinary.assert_not_called()
            prepared.return_value = ({'latent': Path('captured-latent')}, {'scope': 'source-authenticated'})
            self.assertEqual(fetch.native_inputs(None, None, Path('prepared')), prepared.return_value)
            prepared.assert_called_once_with(Path('prepared'))

    def test_compiler_only_and_mutated_normal_build_cannot_substitute_for_packaged_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            complete, _observation, _selected = self.evidence(root)
            original = fetch.build_evidence(root)
            self.assertEqual(original['component'], fetch.file_identity(root/'component.wasm'))
            for key, value in (('packageAssembled', False), ('componentDigest', 'sha256:'+'1'*64),
                                ('observationDigest', 'sha256:'+'2'*64), ('sourceDigest', 'sha256:'+'3'*64)):
                changed = dict(complete, **{key: value})
                self.write(root/'BUILD-COMPLETE.json', changed)
                with self.subTest(key=key), self.assertRaisesRegex(WorkflowError, 'packaged-build-required'):
                    fetch.build_evidence(root)
            self.write(root/'BUILD-COMPLETE.json', complete)
            (root/'component.wasm').write_bytes(b'changed real component')
            with self.assertRaisesRegex(WorkflowError, 'packaged-build-required'):
                fetch.build_evidence(root)

    def test_source_profile_promotion_and_material_substitution_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            complete, observation, selected = self.evidence(root)
            for key, value in (('profile', 'spidermonkey-public-sync-v1'), ('qualification', 'passed'),
                                ('apiSupport', 'qualified')):
                self.write(root/'typescript-runtime-selection.json', dict(selected, **{key: value}))
                with self.subTest(key=key), self.assertRaisesRegex(WorkflowError, 'source-owned-profile-required'):
                    fetch.build_evidence(root)
            self.write(root/'typescript-runtime-selection.json', selected)
            for mutation in ('missing', 'duplicate', 'wrong-digest'):
                changed = deepcopy(observation)
                if mutation == 'missing': changed['materials'].pop()
                elif mutation == 'duplicate': changed['materials'].append(changed['materials'][0])
                else: changed['materials'][0]['digest'] = 'sha256:'+'1'*64
                self.write(root/'build-observation.json', changed)
                self.write(root/'BUILD-COMPLETE.json', dict(complete,
                    observationDigest=fetch.file_identity(root/'build-observation.json')['sha256']))
                with self.subTest(mutation=mutation), self.assertRaisesRegex(WorkflowError, 'material-binding'):
                    fetch.build_evidence(root)

    def row(self, *, denied=False):
        return {'exitCode': 4 if denied else 0, 'decoded': None if denied else ['1:200:used'],
            'processReaped': True, 'response': {'outcomeKnown': True,
                'error': {'code': 'permission-denied'} if denied else None,
                'data': {'consumption': {'cpuFuel': '0' if denied else '100',
                    'outboundRequests': 0 if denied else 1, 'childCalls': 0, 'effectCount': 0}}}}

    def test_grant_denial_requires_permission_code_zero_execution_and_reaped_process(self):
        original = self.row(denied=True)
        fetch.require_denied(original)
        for change in ('code', 'cpuFuel', 'outboundRequests', 'childCalls', 'effectCount', 'reaped', 'payload', 'outcome'):
            row = deepcopy(original)
            if change == 'code': row['response']['error']['code'] = 'guest-trap'
            elif change == 'reaped': row['processReaped'] = False
            elif change == 'payload': row['decoded'] = ['forged']
            elif change == 'outcome': row['response']['outcomeKnown'] = False
            else: row['response']['data']['consumption'][change] = '1' if change == 'cpuFuel' else 1
            with self.subTest(change=change), self.assertRaises(WorkflowError): fetch.require_denied(row)

    def test_success_requires_exact_typed_result_known_outcome_and_one_charged_get(self):
        original = self.row()
        fetch.require_result(original, '1:200:used', 1)
        for change in ('decoded', 'outcome', 'reaped', 'outboundRequests', 'childCalls', 'effectCount'):
            row = deepcopy(original)
            if change == 'decoded': row['decoded'] = ['2:200:used']
            elif change == 'outcome': row['response']['outcomeKnown'] = False
            elif change == 'reaped': row['processReaped'] = False
            else: row['response']['data']['consumption'][change] = 0 if change == 'outboundRequests' else 1
            with self.subTest(change=change), self.assertRaises(WorkflowError):
                fetch.require_result(row, '1:200:used', 1)

    def test_configuration_and_grants_keep_authority_exact_service_get_paths_and_owner_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root/'node.json'
            self.write(config, {'cells': [{}], 'execution': {}, 'cache': {}, 'audit': {}})
            credential = root/'authorization'
            startup = {'destinations': [{'name': 'fixed-destination'}]}
            with patch.object(fetch, 'configure_node', return_value=config):
                result = fetch.read_json(fetch.configuration(root, root/'releases', startup, credential))
            self.assertEqual(result['providers']['activationRuntime']['limits'], fetch.OWNER_LIMITS)
            self.assertNotIn('random', result['providers'])
            self.assertNotIn('engine', result)
            self.assertTrue(all(x['consumerService'] == fetch.SERVICE for x in result['providers']['bindings']))
            descriptors = [{'id': name, 'capability': capability, 'profile': profile, 'configurationDigest': 'sha256:'+'1'*64}
                for name, (capability, profile, _operation, _kind) in fetch.profiles('java').items()]
            descriptors += [{'id': 'activation', 'capability': fetch.ACTIVATION, 'profile': 'activation-owned-v1',
                'configurationDigest': 'sha256:'+'2'*64}, {'id': 'http-standard', 'capability': fetch.HTTP,
                'profile': 'bounded-streaming-http-identity-v1', 'configurationDigest': 'sha256:'+'3'*64}]
            node = type('Node', (), {'startup_record': {'providers': descriptors}})()
            origin = {'scheme': 'http', 'host': '127.0.0.1', 'port': 1234}
            with patch.object(fetch, 'policy') as policy:
                runtime, authorized = fetch.grants(object(), node, 'publication', origin)
            self.assertNotIn(fetch.HTTP, [x['capability'] for x in runtime])
            self.assertEqual(len(authorized), len(runtime)+1)
            rules = [x.args[3]['rules'][0] for x in policy.call_args_list if x.args[1] == 'policy']
            self.assertTrue(all(x['services'] == [fetch.SERVICE] and x['publications'] == ['publication'] for x in rules))
            http = next(x for x in rules if x['capability'] == fetch.HTTP)
            self.assertEqual(http['resources'], {'kind': 'http', 'origins': [origin], 'methods': ['GET'],
                'paths': ['/conformance/json', '/conformance/status/404'], 'pathPrefixes': []})
            descriptors[0]['profile'] = 'foreign-profile'
            with patch.object(fetch, 'policy'), self.assertRaisesRegex(WorkflowError, 'provider-profile'):
                fetch.grants(object(), node, 'publication', origin)

    def test_provider_read_window_matches_actual_adapter_without_relaxing_total_body_or_owners(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'The pinned Node reference host is required')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root/'node.json'
            self.write(config, {'cells': [{}], 'execution': {}, 'cache': {}, 'audit': {}})
            with patch.object(fetch, 'configure_node', return_value=config):
                value = fetch.read_json(fetch.configuration(root, root/'releases',
                    {'destinations': [{'name': 'fixed-destination'}]}, root/'authorization'))
            provider = value['providers']['httpStreaming']
            self.assertEqual(provider['configuration']['limits'], {'maximumRequestBodyBytes': 4096,
                'maximumResponseBodyBytes': 8192, 'maximumEncodedResponseBytes': 16384,
                'maximumHeaderBytes': 4096, 'maximumHeaders': 16, 'maximumRedirects': 0})
            self.assertEqual(value['providers']['activationRuntime']['limits'], fetch.OWNER_LIMITS)
            self.write(root/'windows.json', {'actual': provider['limits'],
                'old': dict(provider['limits'], maximumChunkBytes=4096)})
            script = r"""
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
import {stripTypeScriptTypes} from 'node:module';
import {pathToFileURL} from 'node:url';
const [fixture, backend, output] = process.argv.slice(2);
const {installFetch} = await import(pathToFileURL(backend));
const windows = JSON.parse(await readFile(output+'/windows.json','utf8'));
for (const name of ['default-client','main']) {
  const source=stripTypeScriptTypes(await readFile(fixture+'/'+name+'.ts','utf8'));
  await writeFile(output+'/'+name+'.mjs',source.replace("'./default-client.js'","'./default-client.mjs'"));
}
for (const [label, limits] of Object.entries(windows)) {
  let contacts=0, reads=0;
  const events=[], requested=[];
  const owner=kind=>({[Symbol.dispose]() {events.push('drop-'+kind);}});
  const upload=owner('upload'), body=owner('body'), chunk=owner('chunk');
  installFetch({
    async open() {contacts++;return upload;},
    async finish(value) {assert.equal(value,upload);events.push('consume-upload');return {status:200,headers:[],body};},
    async read(value, maximum) {
      assert.equal(value,body);requested.push(maximum);
      // Same finite capacity refusal as IoTransfer::output_buffer, before polling.
      if (maximum===0 || maximum>limits.maximumChunkBytes) throw {tag:'invalid-state'};
      return reads++===0 ? chunk : undefined;
    },
    async chunkBytes(value) {assert.equal(value,chunk);return new TextEncoder().encode('{"message":"window"}');},
  },()=>false);
  const {api}=await import(pathToFileURL(output+'/main.mjs').href+'?'+label);
  assert.equal(await api.run(2,'https://fixture.invalid/conformance/json'),'request-ready');
  assert.equal(contacts,0);
  const result=await api.run(0,'https://fixture.invalid/conformance/json');
  assert.equal(result,label==='old' ? '1:diagnostic:fetch:TypeError' : '1:200:{"message":"window"}:used');
  assert.equal(contacts,1);
  assert.deepEqual(requested,label==='old' ? [65536] : [65536,65536]);
  assert.deepEqual(events,label==='old' ? ['consume-upload','drop-body'] : ['consume-upload','drop-chunk','drop-body']);
}
"""
            (root/'control.mjs').write_text(script, encoding='utf-8')
            result = subprocess.run([node, str(root/'control.mjs'), str(fetch.ROOT/fetch.FIXTURE),
                str(fetch.ROOT/'tools/typescript_guest/fetch.mjs'), str(root)],
                capture_output=True, text=True, timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertEqual(provider['limits'], {'maximumInputBytes': 4096, 'maximumOutputBytes': 8192,
                'maximumChunkBytes': 65536, 'maximumOutstandingChunks': 2})

    def test_real_peer_requires_exact_three_contacts_and_no_denied_contact_or_mutation(self):
        credential = b'Bearer '+b'0'*64
        with closing(Peer(credential, maximum_seconds=10)) as peer:
            origin = peer.origin('primary')
            for path in ('/conformance/json', '/conformance/status/404', '/conformance/json'):
                with socket.create_connection((origin['host'], origin['port']), timeout=2) as connection:
                    host = f"127.0.0.1:{origin['port']}".encode()
                    connection.sendall(b'GET '+path.encode()+b' HTTP/1.1\r\nHost: '+host+b'\r\nAuthorization: '+credential+b'\r\n\r\n')
                    connection.setblocking(False)
                    deadline, received = time.monotonic()+2, b''
                    while True:
                        peer.poll(.001)
                        try: chunk = connection.recv(4096)
                        except BlockingIOError: chunk = None
                        if chunk == b'': break
                        if chunk is not None: received += chunk
                        self.assertLess(time.monotonic(), deadline)
                    self.assertTrue(received.startswith(b'HTTP/1.1 '))
            peer.close()
            observation = peer.observation()
        self.assertEqual(fetch.peer_evidence(observation), observation)
        for name, value in (('startedRequests', 4), ('committedMutations', 1), ('openConnections', 1)):
            changed = dict(observation, **{name: value})
            with self.subTest(name=name), self.assertRaises(ValueError): fetch.peer_evidence(changed)

    def test_actual_fixture_default_globals_one_shot_body_and_fresh_instance_counter(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'The pinned Node reference host is required')
        script = r"""
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
import {stripTypeScriptTypes} from 'node:module';
import {pathToFileURL} from 'node:url';
const [fixture, output, backend, allowedJson] = process.argv.slice(2);
const allowedHeaders=JSON.parse(allowedJson);
const {installFetch} = await import(pathToFileURL(backend));
let contacts=0, drops=0, reads=0, status=200;
const owner=()=>({[Symbol.dispose]() {drops++;}});
installFetch({
  async open(request) {
    if (request.headers.some(header=>!allowedHeaders.includes(header.name))) {
      throw {payload:{tag:'invalid-request'}};
    }
    contacts++; reads=0; status=request.url.endsWith('/404') ? 404 : 200;
    assert.equal(request.method,'get');
    assert.deepEqual(request.headers,[{name:'x-conformance',value:'ordinary-global'}]);
    return owner();
  },
  async finish() {return {status,headers:[],body:owner()};},
  async read() {return reads++===0 ? owner() : undefined;},
  async chunkBytes() {return new TextEncoder().encode('{"message":"fixture"}');},
},()=>false);
for(const name of ['default-client','main']) {
  const source=stripTypeScriptTypes(await readFile(fixture+'/'+name+'.ts','utf8'));
  await writeFile(output+'/'+name+'.mjs',source.replace("'./default-client.js'","'./default-client.mjs'"));
  await writeFile(output+'/old-'+name+'.mjs',source.replaceAll('x-conformance','x-client')
    .replace("'./default-client.js'","'./old-default-client.mjs'"));
}
const old=(await import(pathToFileURL(output+'/old-main.mjs'))).api;
assert.equal(await old.run(0,'https://fixture.invalid/conformance/json'),'1:diagnostic:fetch:TypeError');
assert.equal(contacts,0);
const main=pathToFileURL(output+'/main.mjs');
const {api}=await import(main);
assert.equal(contacts,0);
assert.equal(await api.run(1,'https://fixture.invalid/conformance/json'),'entered');
assert.equal(await api.run(2,'https://fixture.invalid/conformance/json'),'request-ready');
assert.equal(contacts,0);
assert.equal(await api.run(0,'https://fixture.invalid/conformance/json'),'1:200:{"message":"fixture"}:used');
assert.equal(await api.run(0,'https://fixture.invalid/conformance/status/404'),'2:404:{"message":"fixture"}:used');
const fresh=(await import(main.href+'?fresh')).api;
assert.equal(await fresh.run(0,'https://fixture.invalid/conformance/json'),'1:200:{"message":"fixture"}:used');
assert.equal(contacts,3);assert.equal(drops,6);
const original=Response.prototype.json;
Response.prototype.json=async()=>({message:'fabricated-without-consuming'});
assert.equal(await api.run(0,'https://fixture.invalid/conformance/json'),'3:diagnostic:body-after:Error');
Response.prototype.json=original;
await assert.rejects(api.run(99,'https://fixture.invalid/conformance/json'),/unsupported-fetch-runtime-mode/);
assert.equal(contacts,4);
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'control.mjs').write_text(script, encoding='utf-8')
            with closing(Peer(b'Bearer '+b'0'*64, maximum_seconds=10)) as peer:
                allowed = peer.provider_destinations()[0]['allowedRequestHeaders']
            self.assertIn('x-conformance', allowed)
            self.assertNotIn('x-client', allowed)
            completed = subprocess.run([node, str(root/'control.mjs'), str(fetch.ROOT/fetch.FIXTURE),
                str(root), str(fetch.ROOT/'tools/typescript_guest/fetch.mjs'), json.dumps(allowed)],
                capture_output=True, text=True, timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_no_http_promise_and_request_copy_controls_retain_real_thenable_await_and_listener_cleanup(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'The pinned Node reference host is required')
        script = r"""
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
import {stripTypeScriptTypes} from 'node:module';
import {pathToFileURL} from 'node:url';
const [fixture, output, backend] = process.argv.slice(2);
const {installFetch} = await import(pathToFileURL(backend));
const forbidden = () => { throw new Error('no-http-control-contacted-provider'); };
installFetch({open:forbidden,finish:forbidden,read:forbidden,chunkBytes:forbidden},()=>false);
for(const name of ['default-client','main']) {
  const source=stripTypeScriptTypes(await readFile(fixture+'/'+name+'.ts','utf8'));
  await writeFile(output+'/'+name+'.mjs',source.replace("'./default-client.js'","'./default-client.mjs'"));
}
const {api}=await import(pathToFileURL(output+'/main.mjs'));
assert.equal(await api.run(3,'https://fixture.invalid/conformance/json'),'promise-ready');
let added=0,removed=0;
const add=AbortSignal.prototype.addEventListener, remove=AbortSignal.prototype.removeEventListener;
AbortSignal.prototype.addEventListener=function(...args){added++;return add.apply(this,args);};
AbortSignal.prototype.removeEventListener=function(...args){removed++;return remove.apply(this,args);};
assert.equal(await api.run(4,'https://fixture.invalid/conformance/json'),'request-copy-ready');
assert.equal(added,1);assert.equal(removed,1);
AbortSignal.prototype.addEventListener=add;AbortSignal.prototype.removeEventListener=remove;
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'control.mjs').write_text(script, encoding='utf-8')
            completed = subprocess.run([node, str(root/'control.mjs'), str(fetch.ROOT/fetch.FIXTURE),
                str(root), str(fetch.ROOT/'tools/typescript_guest/fetch.mjs')], capture_output=True, text=True, timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_closed_guest_diagnostics_cannot_replace_signed_success(self):
        for stage in ('request', 'fetch', 'body-before', 'body-json', 'body-after', 'body-repeat', 'serialize'):
            for kind in ('TypeError', 'RangeError', 'Error', 'other'):
                row = self.row()
                row['decoded'] = ['1:diagnostic:'+stage+':'+kind]
                with self.subTest(stage=stage, kind=kind), self.assertRaisesRegex(WorkflowError, 'typed-result'):
                    fetch.require_result(row, '1:200:used', 1)

    def test_actual_fixture_diagnostics_keep_closed_stages_and_never_observe_private_error_fields(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'The pinned Node reference host is required')
        script = r"""
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
import {stripTypeScriptTypes} from 'node:module';
import {pathToFileURL} from 'node:url';
const [fixture, output, backend] = process.argv.slice(2);
const {installFetch} = await import(pathToFileURL(backend));
let contacts=0;
installFetch({async open() {contacts++; throw new Error('unexpected contact');}},()=>false);
await writeFile(output+'/client.mjs',stripTypeScriptTypes(await readFile(fixture+'/default-client.ts','utf8')));
const client=await import(pathToFileURL(output+'/client.mjs'));
assert.equal(client.requestReady('https://fixture.invalid/'),'request-ready');
assert.equal(contacts,0);
const originalRequest=Request, originalFetch=fetch;
const privateValue='https://credential-fixture.invalid/private?token=never-export';
globalThis.Request=class {constructor() {throw new RangeError(privateValue);}};
assert.equal(client.requestReady(privateValue),'diagnostic:request:RangeError');
assert.equal(await client.request(privateValue),'diagnostic:request:RangeError');
globalThis.Request=originalRequest;
globalThis.fetch=async()=>{throw new TypeError(privateValue);};
assert.equal(await client.request('https://fixture.invalid/'),'diagnostic:fetch:TypeError');
globalThis.fetch=async()=>({bodyUsed:true});
assert.equal(await client.request('https://fixture.invalid/'),'diagnostic:body-before:Error');
let observed=0;
const privateError={get name() {observed++;throw 1;},get message() {observed++;throw 1;},
  toString() {observed++;throw 1;}};
globalThis.fetch=async()=>({bodyUsed:false,async json() {throw privateError;}});
assert.equal(await client.request('https://fixture.invalid/'),'diagnostic:body-json:other');
assert.equal(observed,0);
globalThis.fetch=async()=>({bodyUsed:false,async json() {return {};}});
assert.equal(await client.request('https://fixture.invalid/'),'diagnostic:body-after:Error');
globalThis.fetch=async()=>({bodyUsed:false,async json() {this.bodyUsed=true;return {};}});
assert.equal(await client.request('https://fixture.invalid/'),'diagnostic:body-repeat:Error');
const circular={};circular.self=circular;
globalThis.fetch=async()=>({bodyUsed:false,async json() {
  if(this.bodyUsed)throw new TypeError('used');this.bodyUsed=true;return circular;
}});
assert.equal(await client.request('https://fixture.invalid/'),'diagnostic:serialize:TypeError');
assert.equal(contacts,0);
globalThis.fetch=originalFetch;
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'control.mjs').write_text(script, encoding='utf-8')
            completed = subprocess.run([node, str(root/'control.mjs'), str(fetch.ROOT/fetch.FIXTURE),
                str(root), str(fetch.ROOT/'tools/typescript_guest/fetch.mjs')], capture_output=True, text=True, timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == '__main__':
    unittest.main()
