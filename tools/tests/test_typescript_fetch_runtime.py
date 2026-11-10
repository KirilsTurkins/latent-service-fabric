"""Finite evidence guards and real adapter/peer controls, not native qualification."""
from copy import deepcopy
from contextlib import closing
import hashlib
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
    def test_completed_capture_keeps_standard_workflow_owner(self):
        # The observation is manually invocable; the normal Fetch owner must
        # retain its original unconditional step and development-only trigger.
        workflow = '.github/workflows/typescript-guest.yml'
        source = (fetch.ROOT/workflow).read_text(encoding='utf-8')
        contracts = fetch.ROOT/'tools/ci/contracts/workflows/typescript-guest.yml'
        policy = json.loads((contracts/'workflow.json').read_text(encoding='utf-8'))
        job_contract = json.loads((contracts/'jobs/fetch-runtime.json').read_text(encoding='utf-8'))
        self.assertEqual(policy['workflow'], workflow)
        self.assertEqual(job_contract['workflow'], workflow)
        self.assertEqual(policy['policy']['on']['push']['branches'], ['development'])
        self.assertNotIn('feat/sdk-745-completed-capture-20261109', source)
        job = job_contract['definition']
        self.assertEqual(job['timeout-minutes'], 25)
        steps = job['steps']
        normal_name = 'Build, sign and invoke actual default Fetch through the typed HTTP provider'
        normal = [step for step in steps if step.get('name') == normal_name]
        self.assertEqual(len(normal), 1)
        self.assertNotIn('if', normal[0])
        self.assertTrue(all(step.get('name') not in {
            'Observe completed retained Promise callbacks with the same signed owner',
            'Retain completed Promise capture diagnostic separately',
        } for step in steps))
        body = source.split('  fetch-runtime:\n', 1)[1].split('  fetch-failure-frames:\n', 1)[0]
        self.assertIn('      - name: ' + normal_name + '\n        run: ' + normal[0]['run'], body)
        self.assertNotIn('--observe-completed-capture-from', body)

    def test_completed_capture_uses_release_retained_fresh_order(self):
        self.assertEqual(fetch.COMPLETED_CAPTURE_VECTORS, (
            ('combinator-completed-control', 30, 'combinator:completed:released:3'),
            ('combinator-completed-retained', 29, None),
            ('combinator-completed-fresh', 30, 'combinator:completed:released:3')))
        diagnostic = fetch.execution_vectors(True)
        self.assertEqual([(row[0], row[1], row[3]) for row in diagnostic],
                         list(fetch.COMPLETED_CAPTURE_VECTORS))
        self.assertTrue(all(row[4] == 0 for row in diagnostic))
        ordinary = fetch.execution_vectors(False)
        self.assertEqual(len(ordinary), 20)
        self.assertEqual(hashlib.sha256(json.dumps(ordinary, separators=(',', ':')).encode()).hexdigest(),
                         'c952d6ed1f30da648221945f606081d03a6a43f3a9f9d577f973d20919d123fa')
        with self.assertRaises(WorkflowError): fetch.execution_vectors(1)

    def test_completed_capture_requires_the_exact_lifecycle_trap(self):
        original = {'exitCode': 4, 'decoded': None, 'processReaped': True,
            'response': {'outcomeKnown': True, 'category': 'platform-failure',
                'error': {'code': 'guest-trap', 'details': [{'kind': 'activation.guest-trap',
                    'fields': {'code': 'runtime-lifecycle-unproven'}}]},
                'data': {'terminalState': 'guest_trap', 'consumption': {'cpuFuel': '100',
                    'peakMemoryBytes': '65536', 'outboundRequests': 0, 'childCalls': 0, 'effectCount': 0}}}}
        fetch.require_completed_capture_refusal(original)
        for mutation in ('exit', 'result', 'reaped', 'unknown', 'category', 'outer-code',
                         'trap-code', 'duplicate-trap', 'terminal', 'fuel', 'memory', 'outbound', 'boolean'):
            row = deepcopy(original)
            if mutation == 'exit': row['exitCode'] = 0
            elif mutation == 'result': row['decoded'] = ['combinator:completed:retained:3']
            elif mutation == 'reaped': row['processReaped'] = False
            elif mutation == 'unknown': row['response']['outcomeKnown'] = False
            elif mutation == 'category': row['response']['category'] = 'success'
            elif mutation == 'outer-code': row['response']['error']['code'] = 'internal'
            elif mutation == 'trap-code': row['response']['error']['details'][0]['fields']['code'] = 'guest-trap'
            elif mutation == 'duplicate-trap': row['response']['error']['details'].append(
                deepcopy(row['response']['error']['details'][0]))
            elif mutation == 'terminal': row['response']['data']['terminalState'] = 'succeeded'
            elif mutation == 'fuel': row['response']['data']['consumption']['cpuFuel'] = '0'
            elif mutation == 'memory': row['response']['data']['consumption']['peakMemoryBytes'] = '0'
            elif mutation == 'outbound': row['response']['data']['consumption']['outboundRequests'] = 1
            else: row['response']['data']['consumption']['childCalls'] = False
            with self.subTest(mutation=mutation), self.assertRaises(WorkflowError):
                fetch.require_completed_capture_refusal(row)

    def test_completed_capture_requires_one_bounded_native_bucket(self):
        from tools.runtime_owner_refusal_diagnostic import observe
        original = observe(b'LSF-RUNTIME-OWNER-REFUSAL-V1 tasks=0 executors=0 queued-work=0 waits=0 '
                           b'timers=0 results=0 native=3\n')
        self.assertEqual(fetch.require_completed_capture_owners(original)['native'], 3)
        for mutation in ('version', 'scope', 'task-scope', 'qualification', 'missing', 'extra', 'invalid', 'capture-limit', 'too-few',
                         'too-many', 'boolean', 'foreign-bucket', 'negative-bucket', 'other-limit', 'other-live'):
            value = deepcopy(original)
            if mutation == 'version': value['formatVersion'] = True
            elif mutation == 'scope': value['scope'] = 'some-other-observer'
            elif mutation == 'task-scope': value['tasksIncludesManagedIdleWorkers'] = False
            elif mutation == 'qualification': value['qualification'] = True
            elif mutation == 'missing': value['records'] = []
            elif mutation == 'extra': value['records'].append(deepcopy(value['records'][0]))
            elif mutation == 'invalid': value['invalidMarkerCount'] = 1
            elif mutation == 'capture-limit': value['atCaptureLimit'] = True
            elif mutation == 'too-few': value['records'][0]['native'] = 2
            elif mutation == 'too-many': value['records'][0]['native'] = 65
            elif mutation == 'boolean': value['records'][0]['native'] = True
            elif mutation == 'foreign-bucket': value['records'][0]['foreign'] = 1
            elif mutation == 'negative-bucket': value['records'][0]['tasks'] = -1
            elif mutation == 'other-limit': value['records'][0]['tasks'] = fetch.OWNER_LIMITS['tasks'] + 1
            else: value['records'][0]['waits'] = 1
            with self.subTest(mutation=mutation), self.assertRaises(WorkflowError):
                fetch.require_completed_capture_owners(value)
        marker = (b'LSF-RUNTIME-OWNER-REFUSAL-V1 tasks=0 executors=0 queued-work=0 waits=0 '
                  b'timers=0 results=0 native=3\n')
        for bad in (b'', marker.replace(b'native=3', b'native=03'),
                    marker.replace(b'native=3', b'native=3 extra=1'), marker + marker,
                    marker.replace(b'tasks=0', b'tasks=1')):
            with self.subTest(stderr=bad), self.assertRaises(WorkflowError):
                fetch.require_completed_capture_owners(observe(bad))

    def test_completed_capture_peer_refuses_any_contact(self):
        original = {'state': 'stopped', 'acceptedConnections': 0, 'startedRequests': 0,
            'completedResponseWrites': 0, 'rejectedRequests': 0, 'committedMutations': 0,
            'receivedBytes': 0, 'requests': [], 'events': []}
        with patch.object(fetch, 'validate_peer') as validate:
            self.assertEqual(fetch.empty_peer_evidence(original), original)
            validate.assert_called_once_with(original)
            for name in ('acceptedConnections', 'startedRequests', 'completedResponseWrites',
                         'rejectedRequests', 'committedMutations', 'receivedBytes'):
                changed = dict(original, **{name: 1})
                with self.subTest(name=name), self.assertRaises(WorkflowError):
                    fetch.empty_peer_evidence(changed)

    def test_completed_capture_reuses_exact_standard_build_with_a_separate_observation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            qualified = root/'standard'
            app, artifact, node = qualified/'application', qualified/'build', qualified/'node'
            for directory in (app/'src', app/'wit', artifact, node, qualified/'selected-native', root/'original'):
                directory.mkdir(parents=True, exist_ok=True)
            for name in ('main.ts', 'default-client.ts'):
                (app/'src'/name).write_bytes((fetch.ROOT/fetch.FIXTURE/name).read_bytes())
            (app/'wit/world.wit').write_bytes((fetch.ROOT/fetch.FIXTURE/'world.wit').read_bytes())
            (artifact/'BUILD-COMPLETE.json').write_bytes(b'{}\n')
            binaries = {}
            for name in fetch.PRODUCTS:
                original = root/'original'/name
                original.write_bytes(('native:'+name).encode())
                (qualified/'selected-native'/name).write_bytes(original.read_bytes())
                binaries[name] = original
            identity = {'source': 'synthetic-current-native'}
            self.write(qualified/'native-inputs.json', identity)
            normal_node = {'status': 'passed', 'signedExecution': 'passed', 'providerExecution': 'passed',
                           'cases': ['original-case']}
            self.write(node/'qualification.json', normal_node)
            component = {'bytes': 8, 'sha256': 'sha256:'+'a'*64}
            standard = {'schemaVersion': 'latent.typescript.signed-fetch-subset.v1', 'status': 'passed',
                'fullTicketQualification': False, 'runtimeProfile': fetch.IMPORT_PROFILE,
                'fetchProfile': fetch.PROFILE, 'nativeTuple': identity,
                'sourceIdentityDigest': fetch.digest(fetch.inventory(fetch.snapshot(app))),
                'component': component, 'build': fetch.file_identity(artifact/'BUILD-COMPLETE.json'),
                'execution': fetch.file_identity(node/'qualification.json'), 'cases': ['original-case']}
            self.write(qualified/'qualification.json', standard)

            def execute(_artifact, _binaries, output, *, completed_capture_diagnostic):
                self.assertTrue(completed_capture_diagnostic)
                output.mkdir()
                self.write(output/'qualification.json', {'status': 'observed'})
                self.write(output/'runtime-owner-refusals.json', {'native': 3})
                return {'status': 'observed', 'signedGuestExecuted': True,
                    'retainedInvocationSucceeded': False, 'physicalStoreRetirementProved': False,
                    'cases': [row[0] for row in fetch.COMPLETED_CAPTURE_VECTORS]}

            with patch.object(fetch, 'native_inputs', return_value=(binaries, identity)), \
                    patch.object(fetch, 'build_evidence', return_value={'component': component}), \
                    patch.object(fetch, 'execute', side_effect=execute) as observed:
                result = fetch.diagnose_completed_capture(qualified, root/'diagnostic', prepared=root/'prepared')
                self.assertEqual(result['status'], 'observed')
                self.assertEqual(result['retainedOutcome'], 'runtime-lifecycle-unproven')
                self.assertFalse(result['retainedInvocationSucceeded'])
                self.assertFalse(result['physicalStoreRetirementProved'])
                self.assertNotIn('signedExecution', result)
                self.assertEqual(fetch.read_json(qualified/'qualification.json'), standard)
                observed.assert_called_once()

                (app/'src/main.ts').write_text('changed source', encoding='utf-8')
                with self.assertRaisesRegex(WorkflowError, 'application-source'):
                    fetch.diagnose_completed_capture(qualified, root/'wrong-source', prepared=root/'prepared')
                observed.assert_called_once()

    def test_combinator_vectors_require_retention_denial_close_and_recovery(self):
        self.assertEqual(fetch.COMBINATOR_VECTORS, (
            ('combinator-retained', 27, 'combinator:retained:3:ordered'),
            ('combinator-refusal', 28, 'combinator:native-refusal:closed:recovered'),
            ('combinator-fresh', 27, 'combinator:retained:3:ordered')))
        self.assertEqual(fetch.OWNER_LIMITS['nativeOwners'], 64)
        node = shutil.which('node')
        self.assertIsNotNone(node, 'The pinned Node reference host is required')
        control = fetch.ROOT/'tools/tests/fixtures/typescript_record_retirement/combinator_signed_control.mjs'
        completed = subprocess.run([node, str(control), str(fetch.ROOT/fetch.FIXTURE/'main.ts')],
                                   capture_output=True, text=True, timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
        self.assertEqual(completed.stdout.strip(), 'fixture-controls-passed; engine-qualified=false')

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

    def test_large_event_clone_cases_require_real_repeated_and_nested_dispatch(self):
        self.assertEqual(fetch.EVENT_CLONE_VECTORS, (
            ('event-clone-repeated', 20, 'event-clone:repeated:12:40'),
            ('event-clone-nested', 21, 'event-clone:nested:12:ordered')))
        self.assertEqual(fetch.OWNER_LIMITS['nativeOwners'], 64)
        node = shutil.which('node')
        self.assertIsNotNone(node, 'The pinned Node reference host is required')
        script = r"""
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
import {stripTypeScriptTypes} from 'node:module';
import {pathToFileURL} from 'node:url';
const [fixture, output] = process.argv.slice(2);
let contacts=0, added=0, dispatched=0, depth=0, maxDepth=0;
globalThis.fetch=()=>{contacts++;throw new Error('unexpected-network');};
for (const name of ['default-client','main']) {
  const source=stripTypeScriptTypes(await readFile(fixture+'/'+name+'.ts','utf8'));
  await writeFile(output+'/'+name+'.mjs',source.replace("'./default-client.js'","'./default-client.mjs'"));
}
const {api}=await import(pathToFileURL(output+'/main.mjs'));
const add=EventTarget.prototype.addEventListener, dispatch=EventTarget.prototype.dispatchEvent;
EventTarget.prototype.addEventListener=function(...args){added++;return add.apply(this,args);};
EventTarget.prototype.dispatchEvent=function(...args){
  dispatched++;depth++;maxDepth=Math.max(maxDepth,depth);
  try{return dispatch.apply(this,args);}finally{depth--;}
};
assert.equal(await api.run(20,''),'event-clone:repeated:12:40');
assert.deepEqual([added,dispatched,maxDepth,contacts],[12,40,1,0]);
added=dispatched=maxDepth=0;
assert.equal(await api.run(21,''),'event-clone:nested:12:ordered');
assert.deepEqual([added,dispatched,maxDepth,contacts],[12,2,2,0]);
EventTarget.prototype.dispatchEvent=()=>true;
await assert.rejects(api.run(20,''),/event-clone-repeated-count/);
await assert.rejects(api.run(21,''),/event-clone-nested-dispatch/);
EventTarget.prototype.dispatchEvent=dispatch;
EventTarget.prototype.addEventListener=add;
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'control.mjs').write_text(script, encoding='utf-8')
            completed = subprocess.run([node, str(root/'control.mjs'), str(fetch.ROOT/fetch.FIXTURE), str(root)],
                capture_output=True, text=True, timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)

    def test_abort_clone_probe_requires_both_refusals_removal_and_recovered_capacity(self):
        self.assertEqual(fetch.ABORT_CLONE_VECTORS, (
            ('abort-clone-normal', 22, 'abort-clone:normal:12'),
            ('abort-clone-refusal', 23, 'abort-clone:two-native-register-refusals:recovered'),
            ('abort-clone-fresh', 22, 'abort-clone:normal:12')))
        self.assertEqual(fetch.OWNER_LIMITS['nativeOwners'], 64)
        node = shutil.which('node')
        self.assertIsNotNone(node, 'The pinned Node reference host is required')
        script = r"""
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
import {stripTypeScriptTypes} from 'node:module';
import {pathToFileURL} from 'node:url';
const [fixture, output] = process.argv.slice(2);
globalThis.fetch=()=>{throw new Error('unexpected-network');};
for (const name of ['default-client','main']) {
  const source=stripTypeScriptTypes(await readFile(fixture+'/'+name+'.ts','utf8'));
  await writeFile(output+'/'+name+'.mjs',source.replace("'./default-client.js'","'./default-client.mjs'"));
}
const {api}=await import(pathToFileURL(output+'/main.mjs'));
const expected='activation-runtime-promise-native-register-denied:2';
const oldController=globalThis.AbortController;
const add=EventTarget.prototype.addEventListener, remove=EventTarget.prototype.removeEventListener;
let held=0, fillDenials=0, abortDenials=0, removed=0, recovered=0, barrier=false;
let silenceAbort=false, rejectRecovery=false, wrongFill=false;
EventTarget.prototype.addEventListener=function(type,listener,...options){
  if(type==='fill') {
    if(held===4) {fillDenials++;throw new Error(wrongFill ? 'wrong-fill' : expected);}
    held++;
  }
  if(type==='recovered') {
    if(held!==0 || !barrier || rejectRecovery) throw new Error('recovery-refused');
    recovered++;
  }
  return add.call(this,type,listener,...options);
};
EventTarget.prototype.removeEventListener=function(type,listener,...options){
  const result=remove.call(this,type,listener,...options);
  if(type==='fill') {
    held--;removed++;
    if(held===0) queueMicrotask(()=>{barrier=true;});
  }
  return result;
};
class FakeSignal extends EventTarget { aborted=false; reason=undefined; }
class FakeController {
  signal=new FakeSignal();
  abort(reason) {
    this.signal.aborted=true;this.signal.reason=reason;
    if(held===4) {
      if(!silenceAbort) {abortDenials++;throw new Error(expected);}
      return;
    }
    this.signal.dispatchEvent(new Event('abort'));
  }
}
globalThis.AbortController=FakeController;
assert.equal(await api.run(22,''),'abort-clone:normal:12');
assert.equal(await api.run(23,''),'abort-clone:two-native-register-refusals:recovered');
assert.deepEqual([held,fillDenials,abortDenials,removed,recovered],[0,1,1,4,12]);
assert.equal(await api.run(22,''),'abort-clone:normal:12');
barrier=false;silenceAbort=true;
await assert.rejects(api.run(23,''),/abort-clone-failure-not-propagated/);
assert.equal(held,0);
silenceAbort=false;barrier=false;rejectRecovery=true;
await assert.rejects(api.run(23,''),/recovery-refused/);
assert.equal(held,0);
rejectRecovery=false;barrier=false;wrongFill=true;
await assert.rejects(api.run(23,''),/wrong-fill/);
assert.equal(held,0);
globalThis.AbortController=oldController;
EventTarget.prototype.addEventListener=add;
EventTarget.prototype.removeEventListener=remove;
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'control.mjs').write_text(script, encoding='utf-8')
            completed = subprocess.run([node, str(root/'control.mjs'), str(fetch.ROOT/fetch.FIXTURE), str(root)],
                capture_output=True, text=True, timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)

    def test_abort_any_frames_require_interruption_identity_nested_order_and_real_abort(self):
        self.assertEqual(fetch.ABORT_ANY_VECTORS, (
            ('abort-any-frames', 24, 'abort-any:80:nested:12:ordered'),
            ('abort-any-refusal', 25, 'abort-any:refusal:closed:recovered'),
            ('abort-any-fresh', 24, 'abort-any:80:nested:12:ordered')))
        self.assertEqual(fetch.OWNER_LIMITS['nativeOwners'], 64)
        node = shutil.which('node')
        self.assertIsNotNone(node, 'The pinned Node reference host is required')
        script = r"""
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
import {stripTypeScriptTypes} from 'node:module';
import {pathToFileURL} from 'node:url';
const [fixture, output] = process.argv.slice(2);
let contacts=0, calls=0, steps=0, depth=0, maxDepth=0;
globalThis.fetch=()=>{contacts++;throw new Error('unexpected-network');};
for (const name of ['default-client','main']) {
  const source=stripTypeScriptTypes(await readFile(fixture+'/'+name+'.ts','utf8'));
  await writeFile(output+'/'+name+'.mjs',source.replace("'./default-client.js'","'./default-client.mjs'"));
}
const {api}=await import(pathToFileURL(output+'/main.mjs'));
const nativeAny=AbortSignal.any;
AbortSignal.any=function(input) {
  calls++;depth++;maxDepth=Math.max(maxDepth,depth);
  const wrapped={ [Symbol.iterator]() {
    const original=input[Symbol.iterator]();
    return { next() {steps++;return original.next();},
             return(value) {return original.return ? original.return(value) : {done:true,value};} };
  }};
  try {return nativeAny.call(this,wrapped);} finally {depth--;}
};
assert.equal(await api.run(24,''),'abort-any:80:nested:12:ordered');
assert.deepEqual([calls,steps,maxDepth,contacts],[82,826,2,0]);
calls=steps=maxDepth=0;
assert.equal(await api.run(24,''),'abort-any:80:nested:12:ordered');
assert.deepEqual([calls,steps,maxDepth,contacts],[82,826,2,0]);
AbortSignal.any=function(input) {
  try {return nativeAny.call(this,input);} catch {return new AbortController().signal;}
};
await assert.rejects(api.run(24,''),/abort-any-interrupted-conversion/);
calls=0;
AbortSignal.any=function(input) {
  calls++;
  return nativeAny.call(this,calls===82 ? [] : input);
};
await assert.rejects(api.run(24,''),/abort-any-nested-iteration/);
AbortSignal.any=nativeAny;
const nativeAbort=AbortController.prototype.abort;
AbortController.prototype.abort=function() {return nativeAbort.call(this,{wrong:true});};
await assert.rejects(api.run(24,''),/abort-any-dependent-state/);
AbortController.prototype.abort=nativeAbort;
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'control.mjs').write_text(script, encoding='utf-8')
            completed = subprocess.run([node, str(root/'control.mjs'), str(fetch.ROOT/fetch.FIXTURE), str(root)],
                capture_output=True, text=True, timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)

    def test_abort_any_refusal_requires_ninth_step_close_original_error_and_recovery(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'The pinned Node reference host is required')
        script = r"""
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
import {stripTypeScriptTypes} from 'node:module';
import {pathToFileURL} from 'node:url';
const [fixture, output] = process.argv.slice(2);
globalThis.fetch=()=>{throw new Error('unexpected-network');};
for (const name of ['default-client','main']) {
  const source=stripTypeScriptTypes(await readFile(fixture+'/'+name+'.ts','utf8'));
  await writeFile(output+'/'+name+'.mjs',source.replace("'./default-client.js'","'./default-client.mjs'"));
}
const {api}=await import(pathToFileURL(output+'/main.mjs'));
const nativeAny=AbortSignal.any, add=EventTarget.prototype.addEventListener;
const remove=EventTarget.prototype.removeEventListener;
const expected='activation-runtime-promise-native-register-denied:2';
let held=0, removed=0, denials=0, barrier=false, mode='normal';
EventTarget.prototype.addEventListener=function(type,listener,...options) {
  if (type==='any-fill') {
    if (held===4) throw new Error(expected);
    held++;
  }
  return add.call(this,type,listener,...options);
};
EventTarget.prototype.removeEventListener=function(type,listener,...options) {
  const result=remove.call(this,type,listener,...options);
  if (type==='any-fill') {
    held--;removed++;
    if (held===0) queueMicrotask(()=>{barrier=true;});
  }
  return result;
};
// Finite reference double: only the signed engine can witness real admission.
AbortSignal.any=function(signals) {
  if (held===4) {
    if (mode==='no-close') {
      const iterator=signals[Symbol.iterator]();
      for (let index=0;index<9;index++) iterator.next();
      throw new Error(expected);
    }
    const collected=[];
    for (const signal of signals) {
      if (collected.length === (mode==='early' ? 7 : 8)) {
        denials++;
        throw new Error(mode==='wrong-error' ? 'wrong-register' : expected);
      }
      collected.push(signal);
    }
    return nativeAny.call(this,collected);
  }
  if (!barrier || mode==='no-recovery') throw new Error('recovery-refused');
  return nativeAny.call(this,signals);
};
assert.equal(await api.run(25,''),'abort-any:refusal:closed:recovered');
assert.deepEqual([held,removed,denials,barrier],[0,4,1,true]);
for (const selected of ['no-close','early','wrong-error']) {
  mode=selected;barrier=false;
  await assert.rejects(api.run(25,''),/abort-any-refusal-close/);
  assert.equal(held,0);
}
mode='no-recovery';barrier=false;
await assert.rejects(api.run(25,''),/recovery-refused/);
assert.equal(held,0);
AbortSignal.any=nativeAny;
EventTarget.prototype.addEventListener=add;
EventTarget.prototype.removeEventListener=remove;
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'control.mjs').write_text(script, encoding='utf-8')
            completed = subprocess.run([node, str(root/'control.mjs'), str(fetch.ROOT/fetch.FIXTURE), str(root)],
                capture_output=True, text=True, timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)

    def test_default_abort_reason_is_shared_and_thrown_by_each_dependent(self):
        self.assertEqual(fetch.ABORT_DEFAULT_VECTORS, (
            ('abort-default-reason', 26, 'abort-default:shared:2:thrown'),
            ('abort-default-fresh', 26, 'abort-default:shared:2:thrown')))
        node = shutil.which('node')
        self.assertIsNotNone(node, 'The pinned Node reference host is required')
        script = r"""
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
import {stripTypeScriptTypes} from 'node:module';
import {pathToFileURL} from 'node:url';
const [fixture, output] = process.argv.slice(2);
globalThis.fetch=()=>{throw new Error('unexpected-network');};
for (const name of ['default-client','main']) {
  const source=stripTypeScriptTypes(await readFile(fixture+'/'+name+'.ts','utf8'));
  await writeFile(output+'/'+name+'.mjs',source.replace("'./default-client.js'","'./default-client.mjs'"));
}
const {api}=await import(pathToFileURL(output+'/main.mjs'));
const nativeAbort=AbortController.prototype.abort, nativeAny=AbortSignal.any;
const nativeThrow=AbortSignal.prototype.throwIfAborted, add=AbortSignal.prototype.addEventListener;
let called=[];
AbortController.prototype.abort=function(...args) {
  called.push(args.length===0 ? 'omitted' : args[0]===undefined ? 'undefined' : 'ignored');
  return nativeAbort.apply(this,args);
};
assert.equal(await api.run(26,''),'abort-default:shared:2:thrown');
assert.deepEqual(called,['omitted','ignored','undefined','ignored']);
called=[];
assert.equal(await api.run(26,''),'abort-default:shared:2:thrown');
assert.deepEqual(called,['omitted','ignored','undefined','ignored']);
AbortController.prototype.abort=nativeAbort;
AbortSignal.any=function(signals) {
  const child=nativeAny.call(this,signals), wrong=new Error('other reason');
  wrong.name='AbortError';
  Object.defineProperty(child,'reason',{get(){return child.aborted ? wrong : undefined;}});
  return child;
};
await assert.rejects(api.run(26,''),/abort-default-reason-identity/);
AbortSignal.any=nativeAny;
AbortSignal.prototype.throwIfAborted=function() {if(this.aborted) throw new Error('other');};
await assert.rejects(api.run(26,''),/abort-default-thrown-reason/);
AbortSignal.prototype.throwIfAborted=nativeThrow;
AbortSignal.prototype.addEventListener=function() {};
await assert.rejects(api.run(26,''),/abort-default-reason-identity/);
AbortSignal.prototype.addEventListener=add;
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'control.mjs').write_text(script, encoding='utf-8')
            completed = subprocess.run([node, str(root/'control.mjs'), str(fetch.ROOT/fetch.FIXTURE), str(root)],
                capture_output=True, text=True, timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)

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
