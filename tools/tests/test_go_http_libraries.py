"""Captured-client fixture ownership; native compilation/execution is separate."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.go_capsule_project import validate
from tools.go_http_library_fixture import capture_source
from tools.phase2_operator_process import WorkflowError
from tools.phase3_resource_identity import file_identity
from tools.qualify_go_http_libraries import qualify
from tools.qualify_go_standard_http import NATIVE_NAMES
from tools.rust_capsule_project import read_file, snapshot


class HttpLibraryCapture(unittest.TestCase):
    def test_malformed_json_oracle_requires_paired_native_results_in_signed_runner(self):
        import ast
        import inspect
        from copy import deepcopy
        from tools import go_standard_http_node as node
        from tools.go_http_library_reference import malformed_outcomes
        from tools.standard_http.vectors import BY_ID, response
        from types import SimpleNamespace
        prefix, suffix = response(BY_ID['malformed-json'],SimpleNamespace(method=b'GET'),1)
        self.assertIn(b'Content-Length: 6\r\n',prefix)
        self.assertEqual(prefix.split(b'\r\n\r\n',1)[1]+suffix,b'{"id":')
        observed = {'schemaVersion':'latent.go.http-client.native-reference.v1','status':'passed','guestExecution':False,
                    'clients':[{'client':name,'result':result,'requests':1,'invalidRequest':False,'bodyBytes':5,'declaredBytes':32}
                               for name,result in (('sling','invalid-json'),('requests','transport-error'))],
                    'malformedJsonClients':[{'client':name,'result':result,'requests':1,'invalidRequest':False,'bodyBytes':6,'declaredBytes':6}
                               for name,result in (('sling','transport-error'),('requests','invalid-json'))]}
        self.assertEqual(malformed_outcomes(observed),{'sling':'transport-error','requests':'invalid-json'})
        rows = node.library_cases({'host':'127.0.0.1','port':1},observed)
        self.assertEqual(len(rows),30)
        self.assertEqual({row[0]:row[3] for row in rows if row[0].endswith('-malformed-json')},
                         {'sling-malformed-json':'transport-error','requests-malformed-json':'invalid-json'})
        changed = deepcopy(observed); changed['malformedJsonClients'][0]['result'] = 'invalid-json'
        self.assertEqual([row for row in rows if row[0] != 'sling-malformed-json'],
                         [row for row in node.library_cases({'host':'127.0.0.1','port':1},changed) if row[0] != 'sling-malformed-json'])
        tree = ast.parse(inspect.getsource(node.run))
        branch = next(value for value in ast.walk(tree) if isinstance(value,ast.If)
                      and ast.unparse(value.test) == "suite == 'libraries'" and any(
                          isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id == 'library_cases'
                          for statement in value.body for call in ast.walk(statement)))
        calls = [call.func.id for statement in branch.body for call in ast.walk(statement)
                 if isinstance(call,ast.Call) and isinstance(call.func,ast.Name)]
        self.assertLess(calls.index('malformed_outcomes'),calls.index('library_cases'))
        qualifier = ast.parse(inspect.getsource(qualify))
        observe = next(call for call in ast.walk(qualifier) if isinstance(call,ast.Call)
                       and isinstance(call.func,ast.Name) and call.func.id == 'native_reference')
        self.assertIs(next(value.value.value for value in observe.keywords
                           if value.arg == 'include_malformed'),True)
        for change in ({'bodyBytes':True},{'bodyBytes':5},{'declaredBytes':32},{'requests':True},
                       {'requests':0},{'requests':2},{'invalidRequest':True},{'client':'requests'},{'result':'invented'}):
            bad = deepcopy(observed); bad['malformedJsonClients'][0].update(change)
            with self.subTest(change=change), self.assertRaisesRegex(WorkflowError,'native-reference-client-result'):
                malformed_outcomes(bad)
        for rows in (None,[],observed['malformedJsonClients'][:1],list(reversed(observed['malformedJsonClients']))):
            bad = deepcopy(observed); bad['malformedJsonClients'] = rows
            with self.subTest(rows=rows), self.assertRaisesRegex(WorkflowError,'native-reference-'):
                malformed_outcomes(bad)

    def test_native_malformed_observations_share_frozen_build_and_persist_failed_row(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from tools import go_http_library_reference as reference
        for fail in (False,True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); app = root/'application'; (app/'src').mkdir(parents=True)
                source = b'package app\nfunc Run(uint32,string) string { return "unchanged" }\n'
                (app/'src/main.go').write_bytes(source)
                (app/'vendor/lsf/sdk/go-guest').mkdir(parents=True)
                (app/'vendor/lsf/sdk/go-guest/toolchain.lock.json').write_text('{"go":{"version":"go1.27.2"}}')
                go = root/'go'; go.write_bytes(b'pinned-go')
                cache = root/'download'; cache.mkdir(); (cache/'captured.mod').write_bytes(b'captured')
                closure = Mock(identity='captured-reviewed-graph')
                captured = Mock(files={'src/main.go':source},dependency_root=app)
                calls = []; output = root/'native-reference.json'
                def command(arguments, _work, environment, seconds, maximum):
                    calls.append(arguments)
                    self.assertLessEqual(seconds,120); self.assertEqual(maximum,65536)
                    self.assertEqual(environment['GOPROXY'],'off'); self.assertEqual(environment['GOFLAGS'],'-mod=readonly')
                    if arguments[1] == 'version': return SimpleNamespace(stdout=b'go version go1.27.2 linux/amd64')
                    if arguments[1] == 'build':
                        self.assertNotIn('-overlay',arguments)
                        harness = read_file(Path(arguments[-1]))
                        self.assertIn(b'scenario, body, declared = "malformed-json", `{"id":`, 6',harness)
                        self.assertIn(b'app.Run(which,',harness)
                        Path(arguments[arguments.index('-o')+1]).write_bytes(b'native-reference')
                        return SimpleNamespace(stdout=b'')
                    name = arguments[1]; malformed = len(arguments) == 3
                    row = {'client':name,'result':('transport-error' if name == 'sling' else 'invalid-json') if malformed else
                           ('invalid-json' if name == 'sling' else 'transport-error'),
                           'requests':1,'invalidRequest':False,'bodyBytes':6 if malformed else 5,'declaredBytes':6 if malformed else 32}
                    if fail and malformed and name == 'requests': row['requests'] = True
                    return SimpleNamespace(stdout=json.dumps(row).encode())
                with patch.object(reference.sys,'platform','linux'), patch.object(reference,'capture_source',return_value=captured), \
                        patch.object(reference,'prepare',return_value=closure), \
                        patch.object(reference,'configure',return_value={'module':'outside.test/app','downloadCache':str(cache)}), \
                        patch.object(reference,'run_bounded',side_effect=command):
                    if fail:
                        with self.assertRaisesRegex(WorkflowError,'native-reference-client-result'):
                            reference.observe(app,go,output,deadline=reference.time.monotonic()+120,include_malformed=True)
                    else:
                        result = reference.observe(app,go,output,deadline=reference.time.monotonic()+120,include_malformed=True)
                        self.assertEqual(reference.malformed_outcomes(result),{'sling':'transport-error','requests':'invalid-json'})
                        closure.check_unchanged.assert_called_once(); captured.check_unchanged.assert_called_once()
                saved = json.loads(read_file(output))
                self.assertEqual(saved['status'],'failed' if fail else 'passed')
                self.assertEqual(len(saved['clients']),2); self.assertEqual(len(saved['malformedJsonClients']),2)
                self.assertEqual(len(calls),6)
                self.assertEqual(sum(arguments[1] == 'build' for arguments in calls),1)
                self.assertEqual(json.loads(read_file(root/'native-reference-malformed-json-requests.json')),saved['malformedJsonClients'][1])
                self.assertEqual(read_file(app/'src/main.go'),source)

    def test_declared_oversized_response_is_refused_before_either_client_decoder(self):
        from types import SimpleNamespace
        from tools import go_standard_http_node as node
        from tools.standard_http.vectors import BY_ID, response
        from tools.rust_capsule_project import ROOT
        observed = {'schemaVersion':'latent.go.http-client.native-reference.v1','status':'passed','guestExecution':False,
                    'clients':[{'client':name,'result':result,'requests':1,'invalidRequest':False,'bodyBytes':5,'declaredBytes':32}
                               for name,result in (('sling','invalid-json'),('requests','transport-error'))]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root/'node.json'
            config.write_text(json.dumps({'cells':[{}],'execution':{},'audit':{}}))
            with patch.object(node,'configure_node',return_value=config):
                node.configuration(root,root,{'destinations':[]},root/'credential')
            provider = json.loads(read_file(config))['providers']['httpStreaming']
        prefix, suffix = response(BY_ID['oversized-body'],SimpleNamespace(method=b'GET'),1)
        head, body = prefix.split(b'\r\n\r\n',1)
        declared = int(next(line.split(b': ',1)[1] for line in head.split(b'\r\n') if line.startswith(b'Content-Length: ')))
        self.assertEqual(declared,len(body+suffix))
        self.assertEqual(declared,65536)
        self.assertEqual(provider['limits']['maximumOutputBytes'],32768)
        self.assertEqual(provider['configuration']['limits']['maximumResponseBodyBytes'],32768)
        self.assertGreater(declared,provider['limits']['maximumOutputBytes'])
        host = read_file(ROOT/'crates/latent-http/src/streaming/response.rs').decode()
        begin = host[host.index('pub(super) fn begin('):host.index('fn copy_headers(')]
        self.assertLess(begin.index('return Err(HttpError::ResponseTooLarge.into())'),begin.index('Ok(Body {'))
        cases = node.library_cases({'host':'127.0.0.1','port':1},observed)
        self.assertEqual(len(cases),30)
        self.assertEqual({row[0]:row[3] for row in cases if row[0].endswith('-oversized')},
                         {'sling-oversized':'transport-error','requests-oversized':'transport-error'})

    def test_truncated_oracle_requires_actual_native_observation_and_keeps_other_cases(self):
        def reference_rows():
            return {'schemaVersion':'latent.go.http-client.native-reference.v1','status':'passed','guestExecution':False,
                    'clients':[{'client':name,'result':result,'requests':1,'invalidRequest':False,'bodyBytes':5,'declaredBytes':32}
                               for name,result in (('sling','invalid-json'),('requests','transport-error'))]}
        from copy import deepcopy
        from tools import go_standard_http_node as node
        from tools.go_http_library_reference import outcomes
        observed = reference_rows()
        self.assertEqual(outcomes(observed), {'sling':'invalid-json','requests':'transport-error'})
        cases = node.library_cases({'host':'127.0.0.1','port':1},observed)
        self.assertEqual(len(cases),30)
        self.assertEqual({row[0]:row[3] for row in cases if row[0].endswith('-truncated')},
                         {'sling-truncated':'invalid-json','requests-truncated':'transport-error'})
        other = deepcopy(observed); other['clients'][0]['result'] = 'transport-error'
        changed = node.library_cases({'host':'127.0.0.1','port':1},other)
        self.assertEqual([row for row in cases if row[0] != 'sling-truncated'],
                         [row for row in changed if row[0] != 'sling-truncated'])
        for bad in (None, {**observed,'status':'failed'}, {**observed,'guestExecution':True}):
            with self.subTest(bad=bad), self.assertRaisesRegex(WorkflowError,'native-reference-required'):
                outcomes(bad)
        for change in ({'requests':True},{'requests':0},{'requests':2},{'invalidRequest':True},
                       {'bodyBytes':True},{'declaredBytes':31},{'result':'invented'},{'client':'requests'}):
            bad = deepcopy(observed); bad['clients'][0].update(change)
            with self.subTest(change=change), self.assertRaisesRegex(WorkflowError,'native-reference-client-result'):
                outcomes(bad)

    def test_native_reference_uses_captured_sources_offline_and_persists_before_refusal(self):
        def reference_rows():
            return {'schemaVersion':'latent.go.http-client.native-reference.v1','status':'passed','guestExecution':False,
                    'clients':[{'client':name,'result':result,'requests':1,'invalidRequest':False,'bodyBytes':5,'declaredBytes':32}
                               for name,result in (('sling','invalid-json'),('requests','transport-error'))]}
        from types import SimpleNamespace
        from unittest.mock import Mock
        from tools import go_http_library_reference as reference
        for fail in (False,True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); app = root/'application'; (app/'src').mkdir(parents=True)
                source = b'package export_example\nfunc Run(uint32,string) string { return "original" }\n'
                (app/'src/main.go').write_bytes(source)
                sdk = app/'vendor/lsf/sdk/go-guest'; sdk.mkdir(parents=True)
                (sdk/'toolchain.lock.json').write_text(json.dumps({'go':{'version':'go1.27.2'}}))
                go = root/'go'; go.write_bytes(b'original-pinned-go')
                cache = root/'captured-downloads'; cache.mkdir()
                captured = SimpleNamespace(files={'src/main.go':source},dependency_root=app,check_unchanged=Mock())
                closure = SimpleNamespace(identity='sha256:'+'a'*64,check_unchanged=Mock())
                rows = reference_rows()['clients']; calls = []
                if fail: rows[0]['requests'] = 2
                output = root/'native-reference.json'
                def run(arguments, work, environment, seconds, maximum):
                    calls.append(arguments)
                    self.assertEqual(read_file(work/'src/main.go'),source)
                    self.assertEqual(environment['GOPROXY'],'off')
                    self.assertEqual(environment['GOSUMDB'],'off')
                    self.assertEqual(environment['GOWORK'],'off')
                    self.assertEqual(environment['GOFLAGS'],'-mod=readonly')
                    self.assertEqual((environment['GOOS'],environment['GOARCH']),('linux','amd64'))
                    self.assertLessEqual(seconds,120)
                    self.assertEqual(maximum,65536)
                    if arguments[1] == 'version': return SimpleNamespace(stdout=b'go version go1.27.2 linux/amd64')
                    if arguments[1] == 'build':
                        self.assertNotIn('-overlay',arguments)
                        harness = read_file(Path(arguments[-1]))
                        self.assertIn(b'app "outside.test/application/src"',harness)
                        self.assertIn(b'app.Run(which,',harness)
                        self.assertNotIn(b'RoundTripper',harness)
                        Path(arguments[arguments.index('-o')+1]).write_bytes(b'native-reference-binary')
                        return SimpleNamespace(stdout=b'')
                    return SimpleNamespace(stdout=json.dumps(next(row for row in rows if row['client']==arguments[1])).encode())
                with patch.object(reference.sys,'platform','linux'), patch.object(reference,'capture_source',return_value=captured), \
                        patch.object(reference,'prepare',return_value=closure), \
                        patch.object(reference,'configure',return_value={'module':'outside.test/application','downloadCache':str(cache)}), \
                        patch.object(reference,'run_bounded',side_effect=run):
                    if fail:
                        with self.assertRaisesRegex(WorkflowError,'native-reference-client-result'):
                            reference.observe(app,go,output,deadline=reference.time.monotonic()+120)
                    else:
                        result = reference.observe(app,go,output,deadline=reference.time.monotonic()+120)
                        self.assertEqual(reference.outcomes(result),{'sling':'invalid-json','requests':'transport-error'})
                        captured.check_unchanged.assert_called_once(); closure.check_unchanged.assert_called_once()
                saved = json.loads(read_file(output))
                self.assertEqual(saved['status'],'failed' if fail else 'passed')
                self.assertEqual(len(saved['clients']),1 if fail else 2)
                self.assertEqual(json.loads(read_file(root/'native-reference-sling.json')),rows[0])
                self.assertEqual(len(calls),3 if fail else 4)
                self.assertFalse(saved['guestExecution'])
                self.assertEqual(read_file(app/'src/main.go'),source)

    def test_private_marker_probes_keep_original_cases_and_enforce_zero_effects_and_retirement(self):
        def reference_rows():
            return {'schemaVersion':'latent.go.http-client.native-reference.v1','status':'passed','guestExecution':False,
                    'clients':[{'client':name,'result':result,'requests':1,'invalidRequest':False,'bodyBytes':5,'declaredBytes':32}
                               for name,result in (('sling','invalid-json'),('requests','transport-error'))]}
        from copy import deepcopy
        from tools import go_standard_http_node as node
        from tools.rust_capsule_project import ROOT
        source = read_file(ROOT/'sdk/go-guest/runtime/http-library-conformance/main.go').decode()
        self.assertLess(source.index('if which == 200'),source.index('if private.Marker()'))
        self.assertLess(source.index('if private.Marker()'),source.index('if which == 201'))
        self.assertLess(source.index('if which == 201'),source.index('library, mode :='))
        rows = [{'exitCode':0,'decoded':[value],'processReaped':True,
                 'response':{'data':{'consumption':{'outboundRequests':0,'effectCount':0}}}}
                for value in ('library-entered','private-marker-ready')]
        original = node.library_cases({'host':'127.0.0.1','port':1},reference_rows())
        self.assertEqual(len(original),30)
        result = {'cases':['original-case-sentinel']}
        with patch.object(node,'invoke',side_effect=deepcopy(rows)) as invoke, patch.object(node,'retire_case') as retire:
            node.entry_probes('client','probe',{'name':'target'},Path('output'),'http://fixture/json',result,libraries=True)
        self.assertEqual(result['cases'],['original-case-sentinel'])
        self.assertEqual([row['name'] for row in result['entryProbes']],['library-entry','private-marker'])
        self.assertEqual([call.args[2] for call in invoke.call_args_list],[200,201])
        self.assertEqual([call.args[-1] for call in retire.call_args_list],['probe-library-entry','probe-private-marker'])
        self.assertEqual(node.library_cases({'host':'127.0.0.1','port':1},reference_rows()),original)
        for changed in ({'exitCode':4}, {'decoded':['wrong']}, {'processReaped':False},
                        {'outboundRequests':1}, {'effectCount':1}):
            trial = deepcopy(rows)
            for key,value in changed.items():
                if key in {'outboundRequests','effectCount'}:
                    trial[1]['response']['data']['consumption'][key] = value
                else:
                    trial[1][key] = value
            result = {'cases':[]}
            with self.subTest(changed=changed), patch.object(node,'invoke',side_effect=trial) as invoke, \
                    patch.object(node,'retire_case') as retire:
                with self.assertRaisesRegex(WorkflowError,'standard-go-probe-'):
                    node.entry_probes('client','probe',{'name':'target'},Path('output'),'http://fixture/json',result,libraries=True)
                self.assertEqual(invoke.call_count,2)
                self.assertEqual(retire.call_count,1)
                self.assertEqual(len(result['entryProbes']),2)
                self.assertEqual(result['cases'],[])

    def test_normal_lock_target_reparse_is_denied_before_capture_or_review(self):
        from types import SimpleNamespace
        from tools import go_http_library_fixture as fixture
        from tools.application_dependency_store import DependencyError
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            identity = 'outside.example.test/http-library/linked'
            app, library = capture_source(root/'application',root/'outside',identity)
            def lock(project, *, go):
                (project/'target/go-dependency-authoring').mkdir(parents=True)
                return {'status':'locked'}
            with patch.object(fixture,'run_bounded',return_value=SimpleNamespace(stdout=b'{}')), \
                    patch.object(fixture,'create_lock',side_effect=lock), \
                    patch('tools.application_dependency_store.is_reparse',side_effect=lambda path: path == app/'target'), \
                    patch.object(fixture,'resolve') as capture, patch.object(fixture,'review') as review:
                with self.assertRaisesRegex(DependencyError,'dependency-link-denied'):
                    fixture.install(app,library,identity,root/'pinned-go')
                capture.assert_not_called(); review.assert_not_called()
            self.assertFalse((app/'target/http-libraries.candidate.json').exists())
            self.assertTrue(library.exists())

    def test_ordinary_clients_use_normal_reviewable_native_lock_without_wit_source_imports(self):
        from types import SimpleNamespace
        from tools import go_http_library_fixture as fixture
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            identity = 'outside.example.test/http-library/ordinary'
            app, library = capture_source(root/'application',root/'outside',identity)
            source = read_file(app/'src/main.go')
            self.assertNotIn(b'go.bytecodealliance.org',source)
            order = []
            def native_command(arguments, _work, _environment, _seconds, _maximum):
                self.assertEqual(arguments[1:3],['mod','edit'])
                return SimpleNamespace(stdout=b'{}' if arguments[-1] == '-json' else b'')
            def lock(project, *, go):
                self.assertEqual(project,app); order.append('lock')
                self.assertEqual(read_file(project/'src/main.go'),source)
                (project/'target/go-dependency-authoring').mkdir(parents=True)
                (project/'target/normal-authoring-state.txt').write_bytes(b'retained normal lock state')
                return {'status':'locked','captureRequired':True,'reviewRequired':True}
            def capture(project, _candidate, *, go):
                self.assertEqual(order,['lock']); order.append('capture')
                (project/'go-resolved.lock.json').write_text('{}')
                _candidate.write_text('{}')
                return {'selection':{},'artifacts':[]}
            with patch.object(fixture,'run_bounded',side_effect=native_command), \
                    patch.object(fixture,'create_lock',side_effect=lock) as normal_lock, \
                    patch.object(fixture,'resolve',side_effect=capture), \
                    patch.object(fixture,'review') as review, \
                    patch.object(fixture,'direct_libraries',return_value=[]):
                record = fixture.install(app,library,identity,root/'pinned-go')
            normal_lock.assert_called_once_with(app,go=root/'pinned-go')
            review.assert_called_once()
            self.assertEqual(order,['lock','capture'])
            self.assertTrue(record['nativeLock']['captureRequired'])
            self.assertTrue(record['nativeLock']['reviewRequired'])
            self.assertEqual(read_file(app/'src/main.go'),source)
            self.assertEqual(read_file(app/'target/normal-authoring-state.txt'),b'retained normal lock state')

    def test_client_ci_gate_requires_normal_native_and_own_boundaries_without_waiving_shared_failure(self):
        from tools import ci_lane_inventory
        from tools.rust_capsule_project import ROOT
        workflow = ci_lane_inventory.structural_workflow(ci_lane_inventory.workflow_model(
            read_file(ROOT/'.github/workflows/go-guest.yml').decode()))
        job = workflow['jobs']['upstream-probe']
        steps = job['steps']
        normal = next(step for step in steps if step.get('id') == 'normal_go_qualification')
        boundaries = next(step for step in steps if step.get('id') == 'http_library_boundaries')
        clients = next(step for step in steps if step.get('name') ==
            'Qualify two captured default clients and renamed private transitive workers')
        shared = next(step for step in steps if step.get('name') ==
            'Qualify ordinary net/http contexts and disposal on the signed node')
        self.assertEqual(normal['run'],
            'python3 tools/qualify_go_capsules.py --output "$RUNNER_TEMP/go-capsule-authoring"\n')
        self.assertNotIn('if',normal)
        self.assertEqual(boundaries['run'],'python3 -m unittest tools.tests.test_go_http_libraries -v')
        self.assertEqual(boundaries['if'],
            "${{ !cancelled() && steps.normal_go_qualification.outcome == 'success' }}")
        self.assertEqual(clients['if'],
            "${{ !cancelled() && steps.normal_go_qualification.outcome == 'success' && steps.http_library_boundaries.outcome == 'success' }}")
        self.assertLess(steps.index(normal),steps.index(shared))
        self.assertLess(steps.index(shared),steps.index(boundaries))
        self.assertLess(steps.index(boundaries),steps.index(clients))
        self.assertNotIn('if',shared)
        for value in (job,normal,shared,boundaries,clients):
            self.assertFalse(value.get('continue-on-error',False))
        self.assertEqual(job['timeout-minutes'],45)

    def test_private_coordinates_change_application_inputs_without_changing_captured_sdk(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); snapshots = []
            for variant in ('first','renamed'):
                app, library = capture_source(root/('app-'+variant),root/('outside-'+variant),
                    'outside.example.test/http-library/'+variant)
                document, _lock, _pins = validate(snapshot(app))
                self.assertEqual(document['runtimeProfile'],'go-component-activation-v4')
                self.assertEqual(document['tenant'],'examples')
                self.assertEqual(document['world'],'examples:go-standard-http/service@1.0.0')
                self.assertTrue(read_file(app/'wit/world.wit').startswith(b'package examples:go-standard-http@1.0.0;\n'))
                self.assertTrue(read_file(app/'src/main.go').startswith(b'package export_examples_go_standard_http_api\n'))
                self.assertEqual(document['limits']['memoryBytes'],67108864)
                self.assertEqual(document['limits']['wallTimeLimitMillis'],120000)
                snapshots.append((read_file(app/'src/main.go'),snapshot(app/'vendor/lsf'),library))
                self.assertFalse(library.is_relative_to(app))
                self.assertEqual(read_file(library/'marker.txt'),b'captured-private-worker')
            self.assertNotEqual(snapshots[0][0],snapshots[1][0])
            self.assertEqual(snapshots[0][1],snapshots[1][1])

    def test_nested_private_origins_and_injected_coordinates_fail_before_writes(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for origin,identity in ((root/'app/private','outside.example.test/http-library/valid'),
                    (root/'private','outside.example.test/http-library/../escape'),
                    (root/'private','outside.example.test/http-library/quote"')):
                with self.subTest(origin=origin,identity=identity), self.assertRaisesRegex(ValueError,'go-http-private'):
                    capture_source(root/'app',origin,identity)
                self.assertFalse(origin.exists())

    def test_tampered_native_tuple_cannot_start_capture_resolution_compilation_or_node(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); native = root/'native'; (native/'native-binaries').mkdir(parents=True)
            identities = {}
            for key in NATIVE_NAMES.values():
                path = native/'native-binaries'/key.replace('/','-'); path.write_bytes(key.encode())
                identities[key] = file_identity(path)
            (native/'qualification.json').write_text(json.dumps({'schemaVersion':'latent.go-capsule.qualification.v1',
                'status':'passed','binaries':identities}))
            (native/'native-binaries/latentd').write_bytes(b'tampered')
            with patch('tools.qualify_go_http_libraries.capture_source') as source, \
                    patch('tools.qualify_go_http_libraries.run_bounded_result') as compiler, \
                    patch('tools.qualify_go_http_libraries.run') as node:
                with self.assertRaisesRegex(WorkflowError,'frozen-native-product-drift'):
                    qualify(root/'output',native)
                for operation in (source,compiler,node): operation.assert_not_called()


if __name__ == '__main__': unittest.main()
