"""Source/peer controls only; hosted Java components supply execution evidence."""
from copy import deepcopy
from pathlib import Path
import socket
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from tools import java_http_fiber_node as node
from tools import qualify_java_http_fibers as campaign
from tools.java_capsule_build import FIBER_IO_PROFILE
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import digest, read_file, read_json
from tools.standard_http.peer import Peer, Gate


class JavaHttpFiberSource(unittest.TestCase):
    def test_actual_normal_project_retains_sdk_and_published_lock_with_explicit_world(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = campaign.project(Path(temporary)/'application')
            descriptor = read_json(app/'capsule-project.json')
            lock = read_json(app/'sdk-lock.json')
            source, wit = read_file(campaign.ROOT/campaign.SOURCE), read_file(campaign.ROOT/campaign.WORLD)
            self.assertEqual(descriptor['service'], 'examples/java-standard-http')
            self.assertEqual(descriptor['limits']['outboundRequests'], 8)
            self.assertEqual(descriptor['limits']['cpuFuel'], 1_000_000_000)
            self.assertEqual(descriptor['limits']['wallTimeLimitMillis'], 120000)
            self.assertEqual(lock['template']['sourceDigest'], digest(source))
            self.assertEqual(lock['template']['witDigest'], digest(wit))
            self.assertEqual(read_file(app/'src/dev/latent/app/Capsule.java'), source)
            self.assertEqual(read_file(app/'wit/deps/activation-runtime/package.wit'),
                read_file(app/'vendor/lsf/wit/platform/activation-runtime/package.wit'))
            self.assertIn(b'import latent:runtime/activation@0.1.0;', wit)
            declaration = read_json(app/'java-dependencies.json')
            self.assertIn('http-request', str(declaration))
            for name, identity in lock['sdk'].items():
                self.assertEqual(digest(read_file(app/'vendor/lsf'/name)), identity['digest'])

    def test_only_existing_qualified_profile_and_normal_apis_are_selected(self):
        self.assertEqual(FIBER_IO_PROFILE, 'teavm-activation-fibers-io-v1')
        text = (campaign.ROOT/campaign.SOURCE).read_text(encoding='utf-8')
        for operation in ('HttpRequest.get(', 'new Thread(', 'new Timer(',
                          'Executors.newSingleThreadExecutor()', 'child.join()',
                          'Thread.yield()', 'new ThreadLocal<>()'):
            self.assertIn(operation, text)
        for forbidden in ('ConnectionFactory', 'setConnectionFactory', 'dev.latent.guest.runtime',
                          '.connectTimeout(', '.readTimeout(', 'System.gc(', 'Runtime.getRuntime'):
            self.assertNotIn(forbidden, text)
        self.assertIn('if (which == 2) return invocation + ":root-return:" + completed;', text)
        self.assertIn('if (which == 3) throw new IllegalStateException("owned-root-failure");', text)

    def test_budget_narrowing_never_mutates_or_elevates_original(self):
        target = {'budget': {'cpuFuel': 1_000_000_000, 'wallTimeLimitMillis': 120000, 'outboundRequests': 8}}
        original = deepcopy(target)
        self.assertEqual(node.narrowed_target(target, 5)['budget']['wallTimeLimitMillis'], 3000)
        self.assertEqual(node.narrowed_target(target, 6)['budget']['cpuFuel'], 100_000_000)
        self.assertEqual(target, original)
        for mode in (True, -1, 8, '1'):
            with self.subTest(mode=mode), self.assertRaisesRegex(WorkflowError, 'unknown-case'):
                node.narrowed_target(target, mode)
        for key, value, mode in (('cpuFuel', 99_999_999, 6), ('wallTimeLimitMillis', 2999, 5)):
            changed = deepcopy(target); changed['budget'][key] = value
            with self.subTest(key=key), self.assertRaises(WorkflowError):
                node.narrowed_target(changed, mode)

    def test_real_peer_requires_completed_independent_primary_response(self):
        from contextlib import closing
        credential = ('Bearer ' + 'a'*64).encode('ascii')
        with closing(Peer(credential, maximum_seconds=5)) as peer:
            origin = peer.origin()
            host = f"127.0.0.1:{origin['port']}".encode('ascii')
            with socket.create_connection((origin['host'], origin['port']), timeout=1) as pending, \
                    socket.create_connection((origin['host'], origin['port']), timeout=1) as ready:
                pending.sendall(b'GET /conformance/hold/headers HTTP/1.1\r\nHost: ' + host + b'\r\nAuthorization: '
                                + credential + b'\r\n\r\n')
                for _ in range(64):
                    peer.poll(.005)
                    if peer.gates(): break
                self.assertEqual(len(peer.gates()), 1)
                gate = peer.gates()[0]
                self.assertFalse(node.ready_sibling(peer.observation(), 0, gate))
                ready.sendall(b'GET /conformance/json HTTP/1.1\r\nHost: ' + host + b'\r\nAuthorization: '
                              + credential + b'\r\n\r\n')
                for _ in range(64):
                    peer.poll(.005)
                    if node.ready_sibling(peer.observation(), 0, gate): break
                self.assertTrue(node.ready_sibling(peer.observation(), 0, gate))
                self.assertFalse(node.ready_sibling(peer.observation(), len(peer.observation()['requests']), gate))
                peer.release(gate)
                with self.assertRaises(ValueError): peer.release(gate)
            observation = peer.close()
            self.assertEqual(observation['startedRequests'], 2)
            self.assertEqual(observation['openConnections'], 0)
            self.assertEqual(observation['listeningOrigins'], 0)
            self.assertNotIn(credential.decode(), str(observation))

    def test_forged_or_stale_sibling_observation_does_not_release(self):
        for row in ({'vector': 'domain-json'}, {'vector': 'pending-headers', 'role': 'primary',
                    'closeReason': 'response-write-complete'}, {'vector': 'domain-json', 'role': 'secondary',
                    'closeReason': 'response-write-complete'}):
            with self.subTest(row=row): self.assertFalse(node.ready_sibling({'requests': [row]}, 0))

    def test_sibling_completion_before_pending_gate_cannot_prove_concurrent_progress(self):
        gate = Gate('a'*32, 1, 'headers')
        row = {'request': 2, 'vector': 'domain-json', 'role': 'primary',
               'closeReason': 'response-write-complete'}
        value = {'requests': [{'request': 1}, row], 'events': [
            {'sequence': 1, 'kind': 'response-write-complete', 'request': 2},
            {'sequence': 2, 'kind': 'gate-pending', 'request': 1, 'phase': 'headers'}]}
        self.assertFalse(node.ready_sibling(value, 0, gate))
        value['events'] = [{'sequence': 1, 'kind': 'gate-pending', 'request': 1, 'phase': 'headers'},
                           {'sequence': 2, 'kind': 'response-write-complete', 'request': 2}]
        self.assertTrue(node.ready_sibling(value, 0, gate))

    def test_result_checks_actual_full_resolved_revision_and_known_reaped_outcome(self):
        selected = {'publicationId': 'p', 'releaseDigest': 'sha256:'+'1'*64,
                    'revisionId': 'r', 'routeGeneration': '7'}
        row = {'processReaped': True, 'exitCode': 0, 'decoded': [node.EXPECTED[2]],
               'response': {'outcomeKnown': True, 'data': {'resolvedRevision': selected}}}
        node.validate_result(row, 2, selected)
        changes = []
        for key in selected:
            v = deepcopy(row);v['response']['data']['resolvedRevision'][key] += '-other';changes.append(v)
        v = deepcopy(row);v['response']['outcomeKnown'] = False;changes.append(v)
        v = deepcopy(row);v['processReaped'] = False;changes.append(v)
        v = deepcopy(row);v['decoded'] = ['1:root-return:1'];changes.append(v)
        for value in changes:
            with self.subTest(value=value), self.assertRaises(WorkflowError): node.validate_result(value, 2, selected)

    def test_terminal_codes_cannot_replace_cancellation_deadline_or_fuel(self):
        selected = {'publicationId': 'p'}
        for mode, code in node.FAILURES.items():
            row = {'processReaped': True, 'exitCode': 4, 'decoded': None, 'response': {
                'outcomeKnown': True, 'category': 'platform-failure', 'error': {'code': code},
                'data': {'resolvedRevision': selected, 'terminalState': code.replace('-', '_')}}}
            node.validate_result(row, mode, selected)
            for other in set(node.FAILURES.values()) - {code}:
                changed = deepcopy(row);changed['response']['error']['code'] = other
                with self.subTest(mode=mode, other=other), self.assertRaisesRegex(WorkflowError, 'terminal-result'):
                    node.validate_result(changed, mode, selected)


class JavaHttpFiberControlBoundaries(unittest.TestCase):
    def test_supervisor_releases_once_only_after_pending_owner_and_later_sibling(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = {'done': False, 'started': False, 'released': 0}
            gate = Gate('a'*32, 1, 'headers')
            def observation():
                if not state['started']: return {'requests': []}
                return {'failure': None, 'openConnections': 0, 'requests': [
                    {'request': 1, 'role': 'primary', 'vector': 'pending-headers'},
                    {'request': 2, 'role': 'primary', 'vector': 'domain-json',
                     'closeReason': 'response-write-complete'}], 'events': [
                    {'sequence': 1, 'kind': 'gate-pending', 'request': 1, 'phase': 'headers'},
                    {'sequence': 2, 'kind': 'response-write-complete', 'request': 2}]}
            def release(selected):
                self.assertEqual(selected, gate)
                self.assertTrue(state['started'])
                state['released'] += 1;state['done'] = True
            peer = SimpleNamespace(origin=lambda: {'host': '127.0.0.1', 'port': 1234},
                observation=observation, gates=lambda: [gate] if not state['done'] else [],
                poll=lambda delay: state.update(started=True), release=release)
            client = SimpleNamespace(deadline=time.monotonic()+10, evidence=Path(temporary),
                call=mock.Mock(return_value={'data': {'nodeUsage': {'unavailable': False,
                    'counters': {name: '0' for name in node.ACTIVE_COUNTERS}}}}))
            process = SimpleNamespace(owner=SimpleNamespace(exited=lambda: state['done']),
                                      drain=mock.Mock(), close=mock.Mock())
            row = {'processReaped': True, 'exitCode': 0, 'decoded': [node.EXPECTED[0]],
                   'response': {'outcomeKnown': True, 'data': {'resolvedRevision': {'p': 1}}}}
            with mock.patch.object(node, 'start_call', return_value=process), \
                    mock.patch.object(node, 'selected_revision', return_value={'p': 1}), \
                    mock.patch.object(node, 'finish_call', return_value=row), \
                    mock.patch.object(node, 'sample', side_effect=[{'held': True}, {'idle': True}]) as samples:
                result = node.invoke(client, SimpleNamespace(drain=mock.Mock()), {'name': 'route', 'budget': {}},
                                     peer, None, 0, 'pending-progress')
            self.assertEqual(state['released'], 1)
            self.assertTrue(result['releasedOnce'])
            self.assertEqual(result['pendingOwner'], {'held': True})
            self.assertEqual(result['retired'], {'idle': True})
            self.assertEqual(samples.call_count, 2)
            self.assertTrue(samples.call_args_list[0].kwargs['active'])
            process.close.assert_called_once()

    def test_missing_pending_witness_cannot_pass_an_early_root_return(self):
        process = SimpleNamespace(owner=SimpleNamespace(exited=lambda: True), close=mock.Mock())
        peer = SimpleNamespace(origin=lambda: {'host': '127.0.0.1', 'port': 1234},
                               observation=lambda: {'requests': []})
        client = SimpleNamespace(deadline=time.monotonic()+10)
        row = {'processReaped': True, 'exitCode': 0, 'decoded': [node.EXPECTED[2]],
               'response': {'outcomeKnown': True, 'data': {'resolvedRevision': {'p': 1}}}}
        with mock.patch.object(node, 'start_call', return_value=process), \
                mock.patch.object(node, 'selected_revision', return_value={'p': 1}), \
                mock.patch.object(node, 'finish_call', return_value=row), \
                self.assertRaisesRegex(WorkflowError, 'no-actual-pending-witness'):
            node.invoke(client, None, {'budget': {}}, peer, None, 2, 'root-return')
        process.close.assert_called_once()

    def test_uncertain_cancellation_preserves_original_exception_without_replay(self):
        failure = RuntimeError('synthetic control failure')
        cancel = mock.Mock(side_effect=failure)
        client = SimpleNamespace(deadline=time.monotonic()+10, call=cancel)
        process = SimpleNamespace(owner=SimpleNamespace(exited=lambda: False), drain=mock.Mock(), close=mock.Mock())
        gate = Gate('a'*32, 1, 'headers')
        observations = iter([{'requests': []}, {'requests': [{'vector': 'pending-headers'}], 'failure': None}])
        peer = SimpleNamespace(origin=lambda: {'host': '127.0.0.1', 'port': 1234},
            observation=lambda: next(observations), gates=lambda: [gate], poll=mock.Mock(), release=mock.Mock())
        with mock.patch.object(node, 'start_call', return_value=process), \
                mock.patch.object(node, 'selected_revision', return_value={}), \
                mock.patch.object(node, 'sample', return_value={'active': True}), \
                self.assertRaises(RuntimeError) as caught:
            node.invoke(client, SimpleNamespace(drain=mock.Mock()), {'budget': {}}, peer, None, 4, 'cancel')
        self.assertIs(caught.exception, failure)
        cancel.assert_called_once()
        peer.release.assert_not_called()
        process.close.assert_called_once()

    def test_changed_candidate_refuses_before_review_cache_or_compilation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binaries = {}
            for name in ('latent', 'latentd', 'capsule_authoring', 'capsule_contracts', 'package'):
                path=root/name;path.write_bytes(name.encode());binaries[name]=path
            def resolve(label, *argv):
                Path(argv[argv.index('--candidate')+1]).write_bytes(b'changed reviewed graph')
            commands = SimpleNamespace(run=mock.Mock(side_effect=resolve), deadline=time.monotonic()+30)
            with mock.patch.object(campaign, 'project', return_value=root/'application'), \
                    mock.patch.object(campaign, 'compiler_cache') as cache, \
                    mock.patch.object(campaign, 'build') as build, \
                    self.assertRaisesRegex(WorkflowError, 'original-client-closure'):
                campaign.execute(commands, binaries, root/'sdk', root/'evidence')
            commands.run.assert_called_once()
            cache.assert_not_called();build.assert_not_called()
            self.assertEqual(read_json(root/'evidence/FAILED.json')['stage'], 'normal-resolve')

    def test_failure_observer_preserves_original_exception(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);binary=root/'binary';binary.write_bytes(b'controlled')
            failure=RuntimeError('fixture boundary')
            with mock.patch.object(campaign, 'project', side_effect=failure), \
                    mock.patch.object(campaign, 'write_json', side_effect=OSError('observer')), \
                    self.assertRaises(RuntimeError) as caught:
                campaign.execute(SimpleNamespace(), {'latent': binary}, root/'sdk', root/'evidence')
            self.assertIs(caught.exception, failure)

    def test_nonlinux_refuses_before_prepared_read_or_output_creation(self):
        with mock.patch.object(campaign.sys, 'platform', 'win32'), \
                mock.patch.object(campaign, 'verify_prepared') as verify, \
                mock.patch.object(campaign, 'fresh') as fresh, \
                self.assertRaisesRegex(WorkflowError, 'linux-required'):
            campaign.run(Path('output'), Path('prepared'), Path('sdk'))
        verify.assert_not_called();fresh.assert_not_called()


class JavaPublicCFailureContext(unittest.TestCase):
    def test_failed_move_definitions_and_uses_stay_inside_the_actual_function(self):
        from tools.java_guest import c_failure_context as context
        with tempfile.TemporaryDirectory() as temporary:
            generated = Path(temporary)/'generated'
            path = generated/'c/d/l/a/Capsule.c';path.parent.mkdir(parents=True)
            path.write_text('void actual_function(void) {\n'
                '    int32_t teavm_local_6;\n    void* teavm_local_17;\n'
                '    teavm_local_17 = teavm_local_6;\n'
                + '\n'.join('    ignored();' for _ in range(200))
                + '\n    teavm_local_6 = teavm_local_17;\n}\n'
                'void other_function(void) {\n    teavm_local_17 = unrelated();\n}\n', encoding='utf-8')
            log = f'{path.as_posix()}:205:1: error: incompatible pointer to integer conversion\n'.encode()
            row = context.collect(generated, log, context.FIXTURE_SOURCES)['errors'][0]
            self.assertEqual(row['symbols'], ['teavm_local_6', 'teavm_local_17'])
            self.assertEqual(row['referenceCount'], 4)
            self.assertEqual(row['omittedReferences'], 0)
            self.assertIn('    teavm_local_17 = teavm_local_6;', [item['text'] for item in row['references']])
            self.assertNotIn('unrelated', str(row['references']))

    def test_reference_witness_bound_is_explicit_without_changing_the_original_failure(self):
        from tools.java_guest import c_failure_context as context
        with tempfile.TemporaryDirectory() as temporary:
            generated = Path(temporary)/'generated'
            path = generated/'c/d/l/a/Capsule.c';path.parent.mkdir(parents=True)
            path.write_text('void actual_function(void) {\n'
                '    int32_t teavm_local_6;\n    void* teavm_local_17;\n'
                + '\n'.join('    teavm_local_6 = teavm_local_17;' for _ in range(200))
                + '\n}\n', encoding='utf-8')
            log = f'{path.as_posix()}:203:1: error: incompatible pointer to integer conversion\n'.encode()
            row = context.collect(generated, log, context.FIXTURE_SOURCES)['errors'][0]
            self.assertEqual(row['referenceCount'], 202)
            self.assertEqual(len(row['references']), 128)
            self.assertEqual(row['omittedReferences'], 74)

    def test_retained_actual_teavm_nested_c_layout_reaches_both_selected_sources(self):
        from tools.java_guest import c_failure_context as context
        with tempfile.TemporaryDirectory() as temporary:
            generated = Path(temporary)/'compiled/project/build/teavm-c/c'
            # Independent literal layout from the completed compiler log,
            # rather than constructing paths from the collector allowlist.
            names = ('c/d/l/a/Capsule.c', 'c/j/u/z/GZIPInputStream.c')
            log = b''
            for name in names:
                path = generated/name;path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('void actual_function(void* argument) {\n'
                    '    int32_t teavm_local_6;\n    void* teavm_local_17;\n'
                    '    teavm_local_6 = teavm_local_17;\n}\n', encoding='utf-8')
                log += f'{path.as_posix()}:4:19: error: incompatible pointer to integer conversion\n'.encode()
            result = context.collect(generated, log, context.FIXTURE_SOURCES)
            self.assertEqual(tuple(row['path'] for row in result['errors']), names)
            self.assertTrue(all(row['errorLine'] == 4 for row in result['errors']))

    @staticmethod
    def fixture(root):
        from tools.java_guest import c_failure_context as context
        generated = root/'generated'
        for name in context.FIXTURE_SOURCES:
            path = generated/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('void example(void* argument) {\n'
                '    int32_t teavm_local_6 = 0;\n'
                '    void* teavm_local_17 = argument;\n'
                '    if (argument != NULL) {\n'
                '        goto block_1;\n'
                '    }\n'
                'block_1:\n'
                '    teavm_local_6 = teavm_local_17;\n'
                '}\n', encoding='utf-8')
        log = ''.join(f'{(generated/name).as_posix()}:8:19: error: incompatible pointer to integer conversion\n'
                      for name in context.FIXTURE_SOURCES).encode('utf-8')
        return generated, log

    def test_exact_context_retains_real_declarations_control_flow_and_byte_identities(self):
        from tools.java_guest import c_failure_context as context
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); generated, log = self.fixture(root)
            value = context.collect(generated, log, context.FIXTURE_SOURCES)
            self.assertEqual(value['logDigest'], digest(log))
            self.assertEqual([row['path'] for row in value['errors']], list(context.FIXTURE_SOURCES))
            for row in value['errors']:
                self.assertEqual(row['sourceDigest'], digest(read_file(generated/row['path'])))
                self.assertEqual(row['function']['text'], 'void example(void* argument) {')
                self.assertEqual([line['text'].strip() for line in row['declarations']],
                    ['int32_t teavm_local_6 = 0;', 'void* teavm_local_17 = argument;'])
                self.assertIn('block_1:', [line['text'] for line in row['context']])
                self.assertEqual(row['errorLine'], 8)
                self.assertIn('    teavm_local_6 = teavm_local_17;', [line['text'] for line in row['context']])
            self.assertNotIn(str(root), context.encoded(value).decode())
            self.assertLessEqual(len(context.encoded(value)), context.MAX_CONTEXT)

    def test_real_failed_compiler_command_preserves_original_command_and_retains_before_cleanup(self):
        from tools.java_guest import c_failure_context as context
        from tools.java_guest.compiler import Compiler
        from tools.java_capsule_build import retain_logs
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); generated, log = self.fixture(root)
            compiler = Compiler.__new__(Compiler)
            compiler.directory = root/'compiler';compiler.directory.mkdir()
            compiler.records = [];compiler.retained_bytes = 0
            compiler.paths = {};compiler.environment = {};compiler.deadline = time.monotonic()+30
            arguments = ('-target', 'wasm32-wasip1', '-O2', generated/'all.c')
            with mock.patch('tools.java_guest.compiler.run_bounded_result',
                    return_value=SimpleNamespace(returncode=1, stdout=b'', stderr=log)) as command, \
                    self.assertRaisesRegex(ValueError, 'Java compiler stage failed: c-to-wasm'):
                context.run(compiler, generated, context.FIXTURE_SOURCES, *arguments)
            self.assertEqual(command.call_count, 1)
            self.assertEqual(command.call_args.args[0], ['clang', *map(str, arguments)])
            self.assertEqual(compiler.records[0]['exitCode'], 1)
            retained = compiler.directory/'0-c-to-wasm-context.command.json'
            self.assertEqual(read_json(retained)['status'], 'observed')
            output = root/'output';output.mkdir();retain_logs(compiler.directory, output)
            self.assertEqual(read_file(output/'compiler-logs'/retained.name), read_file(retained))

    def test_default_and_success_paths_never_read_or_retain_source(self):
        from tools.java_guest import c_failure_context as context
        compiler = SimpleNamespace(run=mock.Mock(return_value='original success'))
        with mock.patch.object(context, 'collect') as collect, mock.patch.object(context.paths, 'read') as read:
            for selected in ((), context.FIXTURE_SOURCES):
                self.assertEqual(context.run(compiler, Path('not-read'), selected, '-O2'), 'original success')
            failure = RuntimeError('original failed compiler')
            compiler.run.side_effect = failure
            with self.assertRaises(RuntimeError) as caught:
                context.run(compiler, Path('not-read'), (), '-O2')
            self.assertIs(caught.exception, failure)
            collect.assert_not_called();read.assert_not_called()

    def test_unknown_selection_or_outside_location_cannot_read_arbitrary_sources(self):
        from tools.java_guest import c_failure_context as context
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);generated, log = self.fixture(root)
            for selected in (['d/l/a/Capsule.c'], ('other.c',), ('../Capsule.c',), (True,)):
                with self.subTest(selected=selected), mock.patch.object(context.paths, 'read') as read, \
                        self.assertRaises(ValueError):
                    context.collect(generated, log, selected)
                read.assert_not_called()
            outside = root/'outside.c';outside.write_bytes(b'private source should not be read')
            with mock.patch.object(context.paths, 'read') as read, self.assertRaisesRegex(ValueError, 'outside-generated-root'):
                context.collect(generated, f'{outside.as_posix()}:1:1: error: opaque\n'.encode(), context.FIXTURE_SOURCES)
            read.assert_not_called()
            ignored = generated/'unselected.c';ignored.write_bytes(b'private unselected data')
            value = context.collect(generated, log + f'{ignored.as_posix()}:1:1: error: opaque\n'.encode(), context.FIXTURE_SOURCES)
            self.assertNotIn('private', context.encoded(value).decode())

    def test_anchored_reader_rejects_hardlinks_and_linked_directories(self):
        import os
        from tools.java_guest import c_failure_context as context
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);generated, log = self.fixture(root)
            source = generated/context.FIXTURE_SOURCES[0]
            alias = root/'alias.c';os.link(source, alias)
            with self.assertRaises(Exception):
                context.collect(generated, log, context.FIXTURE_SOURCES)
            alias.unlink()
            linked = root/'linked'
            try:
                linked.symlink_to(generated, target_is_directory=True)
            except OSError:
                return  # Windows without symlink permission; hardlink refusal above remains mandatory.
            linked_log = log.replace(generated.as_posix().encode(), linked.as_posix().encode())
            with self.assertRaises(Exception):
                context.collect(linked, linked_log, context.FIXTURE_SOURCES)

    def test_source_log_error_declaration_and_output_bounds_fail_closed(self):
        from tools.java_guest import c_failure_context as context
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);generated, log = self.fixture(root)
            for changed in (b'x'*(context.MAX_FILE+1), log*3, log.replace(b':8:19:', b':9999999:19:')):
                with self.subTest(size=len(changed)), self.assertRaises(ValueError):
                    context.collect(generated, changed, context.FIXTURE_SOURCES)
            source = generated/context.FIXTURE_SOURCES[0]
            for payload in (b'x'*(context.MAX_FILE+1), b'\0', b'x'*4097):
                source.write_bytes(payload)
                with self.subTest(size=len(payload)), self.assertRaises(Exception):
                    context.collect(generated, log, context.FIXTURE_SOURCES)
            lines = ['void example(void* argument) {', *[f'    int32_t teavm_local_{i} = 0;' for i in range(65)],
                     '    teavm_local_0 = argument;', '}']
            source.write_text('\n'.join(lines), encoding='utf-8')
            changed = f'{source.as_posix()}:67:1: error: incompatible pointer\n'.encode()
            with self.assertRaisesRegex(ValueError, 'declaration-bound'):
                context.collect(generated, changed, context.FIXTURE_SOURCES)
            generated, log = self.fixture(root)
            with mock.patch.object(context, 'MAX_CONTEXT', 128), self.assertRaisesRegex(ValueError, 'byte-bound'):
                context.collect(generated, log, context.FIXTURE_SOURCES)

    def test_observation_failure_retains_closed_unavailable_and_original_exception_identity(self):
        from tools.java_guest import c_failure_context as context
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            failure = RuntimeError('original compiler hard failure')
            compiler = SimpleNamespace(run=mock.Mock(side_effect=failure), records=[{'stage': 'c-to-wasm'}],
                                       directory=root, retained_bytes=0)
            with self.assertRaises(RuntimeError) as caught:
                context.run(compiler, root/'missing-generated', context.FIXTURE_SOURCES, '-O2')
            self.assertIs(caught.exception, failure)
            value = read_json(root/'0-c-to-wasm-context.command.json')
            self.assertEqual(value, {'schemaVersion': context.SCHEMA, 'status': 'unavailable', 'stage': 'c-to-wasm',
                'publicFixtureOnly': True, 'reason': 'bounded-selected-context-unavailable',
                'refusal': 'file-unavailable-or-unsafe'})
            self.assertEqual(context.refusal(ValueError('private path and diagnostic')), 'unavailable')
            (root/'0-c-to-wasm-context.command.json').unlink()
            with mock.patch.object(context.paths, 'write_new', side_effect=OSError('observer')), \
                    self.assertRaises(RuntimeError) as caught:
                context.run(compiler, root/'missing-generated', context.FIXTURE_SOURCES, '-O2')
            self.assertIs(caught.exception, failure)
            self.assertEqual(compiler.run.call_count, 2)


class PinnedCoroutinePhiRepair(unittest.TestCase):
    def test_exact_pinned_source_repairs_only_copied_phi_filter(self):
        from tools.java_guest import coroutine_patch as patch
        source = read_file(campaign.ROOT/'sdk/java-guest/fibers/compiler-patch/CoroutineTransformation.java')
        corrected = patch.corrected_source(source)
        expected = source.replace(patch.DOMAIN.encode(), patch.COPIED_DOMAIN.encode()).replace(
            patch.BEFORE.encode(), patch.AFTER.encode())
        for name in patch.RELOCATED_IMPORTS:
            expected = expected.replace(('import com.carrotsearch.hppc.'+name+';').encode(),
                ('import org.teavm.hppc.'+name+';').encode())
        self.assertEqual(corrected, expected)
        self.assertIn(b'Licensed under the Apache License, Version 2.0', corrected)
        self.assertIn(b'phi.getIncomings().removeIf(incoming -> domainSet.contains(incoming.getSource().getIndex()));', corrected)
        for changed in (source+b' ', source.replace(b'0;', b'1;', 1), b'private source'):
            with self.subTest(size=len(changed)), self.assertRaisesRegex(ValueError, 'unreviewed-teavm-coroutine-source'):
                patch.corrected_source(changed)

    def test_private_jar_replaces_exact_compiled_closure_and_retains_every_other_entry(self):
        import zipfile
        from tools.java_guest import coroutine_patch as patch
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); original=root/'original.jar'; classes=root/'classes'; classes.mkdir()
            rows={name:b'old-'+name.encode() for name in patch.PATCH_CLASSES}
            rows.update({'META-INF/MANIFEST.MF':b'Manifest-Version: 1.0\n', 'unrelated/Class.class':b'unchanged'})
            with zipfile.ZipFile(original,'w') as jar:
                for name,raw in rows.items():jar.writestr(name,raw)
            original_bytes=original.read_bytes()
            for name in patch.PATCH_CLASSES|{patch.CONTROL}:
                path=classes/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'\xca\xfe\xba\xbecompiled-'+name.encode())
            target=root/'replacement.jar'; receipt=patch.replace_jar(original,classes,target)
            self.assertEqual(original.read_bytes(),original_bytes)
            self.assertEqual(receipt['unchangedEntries'],2)
            self.assertEqual(set(receipt['replacedClasses']),patch.PATCH_CLASSES)
            observed=patch.jar_entries(target)
            for name,raw in rows.items():
                self.assertEqual(observed[name],(classes/name).read_bytes() if name in patch.PATCH_CLASSES else raw)
            (classes/'unexpected.class').write_bytes(b'not selected')
            with self.assertRaisesRegex(ValueError,'compiled-closure'):
                patch.replace_jar(original,classes,root/'rejected.jar')
            self.assertFalse((root/'rejected.jar').exists())

    def test_jar_duplicates_unsafe_members_and_missing_class_refuse(self):
        import warnings,zipfile
        from tools.java_guest import coroutine_patch as patch
        for invalid in ('duplicate','escape','missing'):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as temporary:
                path=Path(temporary)/'core.jar'
                with warnings.catch_warnings(), zipfile.ZipFile(path,'w') as jar:
                    warnings.simplefilter('ignore')
                    for name in sorted(patch.PATCH_CLASSES):jar.writestr(name,b'original')
                    if invalid=='duplicate':jar.writestr(sorted(patch.PATCH_CLASSES)[0],b'other')
                    elif invalid=='escape':jar.writestr('../outside',b'outside')
                if invalid=='missing':
                    with zipfile.ZipFile(path,'w') as jar:jar.writestr('some.class',b'other')
                with self.assertRaises(ValueError):patch.jar_entries(path)

    def test_loaded_class_receipt_binds_actual_private_jar_and_refuses_mutation(self):
        import hashlib,json
        from tools.java_guest import coroutine_patch as patch
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);folder=root/'compiler-patch';folder.mkdir()
            jar=folder/'teavm-core-patched.jar';jar.write_bytes(b'owned bytes')
            sha=hashlib.sha256(jar.read_bytes()).hexdigest()
            receipt={'replacementJarSha256':sha,'replacedClasses':{
                name:{'replacementSha256':sha} for name in patch.PATCH_CLASSES}}
            actual={'schemaVersion':'latent.java.coroutine-compiler-load.v1',
                'selectedOwnedReplacement':True,'replacementJarSha256':sha,
                'loadedJarSha256':sha,'codeSourceKind':'owned-replacement',
                'loadedClasses':{name:sha for name in patch.PATCH_CLASSES}}
            marker=folder/'loaded.json';marker.write_text(json.dumps(actual))
            self.assertEqual(patch.loaded(root,receipt)['loadedCompiler'],actual)
            for changed in ({'selectedOwnedReplacement':False},{'selectedOwnedReplacement':1},
                            {'replacementJarSha256':'0'*64},
                            {'schemaVersion':'private unknown'},{'extra':'private path'}):
                marker.write_text(json.dumps({**actual,**changed}))
                with self.assertRaisesRegex(ValueError,'loaded-receipt-mismatch'):patch.loaded(root,receipt)
            marker.write_text(json.dumps(actual));jar.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'used-jar-mutated'):patch.loaded(root,receipt)

    def test_hosted_real_ir_control_requires_old_defect_and_corrected_loop_values(self):
        text=(campaign.ROOT/'sdk/java-guest/fibers/compiler-patch/Check.java').read_text()
        for required in ('new Program()', 'new Phi()', 'GraphUtils.isIrreducible(',
                'transform.new SplittingBackend().split(', 'sources(headerPhi)',
                'Set.of(remaining.getIndex(), copies[1])', 'Set.of(copies[0])',
                'copiedTail.getIncomings().get(0).getValue() != current',
                'coroutine-control-unreviewed-original', 'coroutine-control-copied-loop-input-lost'):
            self.assertIn(required,text)
        from tools.java_guest import coroutine_patch as patch
        self.assertEqual(patch.PATCH_CLASSES,frozenset(patch.CLASS_ROOT+name for name in (
            'CoroutineTransformation.class','CoroutineTransformation$1.class',
            'CoroutineTransformation$SplittingBackend.class')))


    def test_real_pinned_inventory_and_process_boundary_stage_private_patch_only(self):
        import hashlib,json,zipfile
        from tools.java_guest import coroutine_patch as patch
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);sdk=root/'sdk';(sdk/'tools').mkdir(parents=True)
            (sdk/'tools/dependencies.py').write_bytes(read_file(campaign.ROOT/'sdk/java-guest/tools/dependencies.py'))
            sources=sdk/'fibers/compiler-patch';sources.mkdir(parents=True)
            for name in ('CoroutineTransformation.java','Compile.java','Check.java'):
                (sources/name).write_bytes(read_file(campaign.ROOT/'sdk/java-guest/fibers/compiler-patch'/name))
            cache=root/'files-2.1';base=cache/'org.teavm/teavm-core/0.15.0/pinned';base.mkdir(parents=True)
            core=base/'teavm-core-0.15.0.jar'
            with zipfile.ZipFile(core,'w') as jar:
                for name in sorted(patch.PATCH_CLASSES):jar.writestr(name,b'original class')
                jar.writestr('unchanged.class',b'original unrelated')
            raw=core.read_bytes();sha=hashlib.sha256(raw).hexdigest()
            hppc=cache/'org.teavm/teavm-relocated-libs-hppc/0.15.0/pinned/teavm-relocated-libs-hppc-0.15.0.jar'
            hppc.parent.mkdir(parents=True)
            with zipfile.ZipFile(hppc,'w') as jar:
                for name in patch.RELOCATED_IMPORTS:jar.writestr('org/teavm/hppc/'+name+'.class',b'\xca\xfe\xba\xbeactual-fixture')
            hppc_raw=hppc.read_bytes();hppc_sha=hashlib.sha256(hppc_raw).hexdigest()
            project=root/'project';(project/'gradle').mkdir(parents=True)
            (project/'dependencies.lock.json').write_text(json.dumps({'schemaVersion':1,
                'maven':'https://repo.maven.apache.org/maven2/','artifacts':[{
                'path':'org/teavm/teavm-core/0.15.0/teavm-core-0.15.0.jar',
                'sha256':sha,'size':len(raw),'platform':'any'}, {
                'path':'org/teavm/teavm-relocated-libs-hppc/0.15.0/teavm-relocated-libs-hppc-0.15.0.jar',
                'sha256':hppc_sha,'size':len(hppc_raw),'platform':'any'}]}))
            (project/'gradle/verification-metadata.xml').write_text(
                '<verification-metadata xmlns="https://schema.gradle.org/dependency-verification">'
                '<configuration><verify-metadata>true</verify-metadata><verify-signatures>false</verify-signatures></configuration>'
                '<components><component group="org.teavm" name="teavm-core" version="0.15.0">'
                '<artifact name="teavm-core-0.15.0.jar"><sha256 value="'+sha+'"/></artifact>'
                '</component><component group="org.teavm" name="teavm-relocated-libs-hppc" version="0.15.0">'
                '<artifact name="teavm-relocated-libs-hppc-0.15.0.jar"><sha256 value="'+hppc_sha+'"/></artifact>'
                '</component></components></verification-metadata>')
            original_script=read_file(campaign.ROOT/'sdk/java-guest/compiler.gradle')
            (project/'build.gradle').write_bytes(original_script)
            patch.record_original_classpath(project)
            (project/'coroutine-patch-original-classpath.json').write_text(json.dumps({
                'schemaVersion':'latent.java.original-compiler-classpath.v1','outOfProcess':False,
                'files':patch.jar_identities(cache,[core,hppc])}))
            calls=[]
            def run(stage,tool,*args):
                calls.append((stage,tool,args))
                self.assertEqual(tool,'java')
                if stage=='java-coroutine-patch':
                    classes=Path(args[3]);classes.mkdir()
                    for name in patch.PATCH_CLASSES|{patch.CONTROL}:
                        path=classes/name;path.parent.mkdir(parents=True,exist_ok=True)
                        path.write_bytes(b'\xca\xfe\xba\xbecompiled')
                    return ''
                mode='original' if stage=='java-coroutine-original-control' else 'corrected'
                self.assertEqual(args[-1],mode)
                self.assertEqual(args[0],'-cp')
                expected=core if mode=='original' else project/'compiler-patch/teavm-core-patched.jar'
                self.assertTrue(args[1].startswith(str(expected)))
                return json.dumps({'schemaVersion':'latent.java.coroutine-phi-control.v1','mode':mode,'passed':True})
            compiler=SimpleNamespace(sdk=sdk,dependency_cache=cache,run=run,directory=root/'compiler-logs')
            compiler.directory.mkdir()
            receipt=patch.stage(compiler,project,root)
            from tools.java_capsule_build import retain_logs
            retain_logs(compiler.directory,root)
            self.assertEqual([call[0] for call in calls],['java-coroutine-patch',
                'java-coroutine-original-control','java-coroutine-corrected-control'])
            self.assertEqual(core.read_bytes(),raw)
            self.assertEqual(receipt['checkedCompilerJars'],[{'coordinate':
                'org/teavm/teavm-core/0.15.0/teavm-core-0.15.0.jar','sha256':sha,'bytes':len(raw)},
                {'coordinate':'org/teavm/teavm-relocated-libs-hppc/0.15.0/teavm-relocated-libs-hppc-0.15.0.jar',
                'sha256':hppc_sha,'bytes':len(hppc_raw)}])
            self.assertEqual(json.loads((root/'coroutine-compiler-preparation.json').read_bytes()),receipt)
            script=(project/'build.gradle').read_text()
            for guard in ('org.teavm.backend.c.CTarget.class.classLoader','actual.protectionDomain.codeSource',
                    'coroutine-patch-loaded-class-mismatch','coroutine-patch-loaded-jar-mutated'):
                self.assertIn(guard,script)
            marker=project/'compiler-patch/loaded.json'
            marker.write_text(json.dumps({'schemaVersion':'latent.java.coroutine-compiler-load.v1',
                'selectedOwnedReplacement':True,'replacementJarSha256':receipt['replacementJarSha256'],
                'loadedJarSha256':receipt['replacementJarSha256'],'codeSourceKind':'owned-replacement',
                'loadedClasses':{name:row['replacementSha256'] for name,row in receipt['replacedClasses'].items()}}))
            patch.loaded(project,receipt,compiler=compiler)
            core.write_bytes(raw+b'changed')
            with self.assertRaises(ValueError):patch.loaded(project,receipt,compiler=compiler)

    def test_published_relocated_classes_are_present_before_any_compiler_execution(self):
        import zipfile
        from tools.java_guest import coroutine_patch as patch
        with tempfile.TemporaryDirectory() as temporary:
            jar=Path(temporary)/'teavm-relocated-libs-hppc-0.15.0.jar'
            with self.assertRaisesRegex(ValueError,'relocated-library'):patch.check_relocated_classes([])
            for invalid in ('missing','unrelocated','malformed'):
                with self.subTest(invalid=invalid):
                    with zipfile.ZipFile(jar,'w') as output:
                        for name in patch.RELOCATED_IMPORTS:
                            if invalid=='missing' and name=='IntSet':continue
                            prefix='com/carrotsearch/hppc/' if invalid=='unrelocated' else 'org/teavm/hppc/'
                            output.writestr(prefix+name+'.class',b'not a class' if invalid=='malformed' else b'\xca\xfe\xba\xbevalid')
                    with self.assertRaises((ValueError,KeyError)):patch.check_relocated_classes([jar])


class ExactCoroutineCompilerClasspath(unittest.TestCase):
    def test_record_hook_preserves_original_module_and_requires_exact_declared_preimage(self):
        from tools.java_guest import coroutine_patch as patch
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            original = read_file(campaign.ROOT / 'sdk/java-guest/compiler.gradle')
            build = project / 'build.gradle'; build.write_bytes(original)
            patch.record_original_classpath(project)
            script = build.read_text()
            self.assertTrue(script.startswith(original.decode()))
            for exact in ("tasks.named('classes')", 'buildscript.configurations.classpath', 'configuration.files.collect',
                    'resolvedConfiguration.resolvedArtifacts', 'original-compiler-classpath.v1',
                    'outOfProcess.get()', 'coroutine-patch-original-classpath.json'):
                self.assertIn(exact, script)
            with self.assertRaisesRegex(ValueError, 'classpath-record-drift'):
                patch.record_original_classpath(project)
            build.write_bytes(original.replace(b'teavm-gradle-plugin:0.15.0', b'teavm-gradle-plugin:0.16.0'))
            with self.assertRaisesRegex(ValueError, 'classpath-record-drift'):
                patch.record_original_classpath(project)

    def test_exact_original_classpath_retains_order_and_rejects_unknown_missing_or_mutated_rows(self):
        import json
        from tools.java_guest import coroutine_patch as patch
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); cache = root / 'cache'
            core = cache / 'org.teavm/teavm-core/0.15.0/pin/teavm-core-0.15.0.jar'
            library = cache / 'org.teavm/teavm-tooling/0.15.0/pin/teavm-tooling-0.15.0.jar'
            app = cache / 'unrelated/app/1.0/pin/app-1.0.jar'
            for index, path in enumerate((core, library, app)):
                path.parent.mkdir(parents=True); path.write_bytes(b'pinned' + bytes([index]))
            compiler = SimpleNamespace(dependency_cache=cache)
            project = root / 'project'; project.mkdir()
            rows = patch.jar_identities(cache, [core, library, app])
            by_name = {row['coordinate']: row for row in rows}
            selected = [row for row in rows if '/app/' not in row['coordinate']][::-1]
            original = {'schemaVersion': 'latent.java.original-compiler-classpath.v1',
                'outOfProcess': False, 'files': selected}
            record = project / 'coroutine-patch-original-classpath.json'
            record.write_text(json.dumps(original))
            result = patch.original_classpath(compiler, project, [core, library, app])
            self.assertEqual(result, [library, core])
            self.assertNotIn(app, result)
            for kind in ('missing-core', 'unknown', 'duplicate', 'changed', 'out-of-process'):
                with self.subTest(kind=kind):
                    value = json.loads(json.dumps(original))
                    if kind == 'missing-core': value['files'] = value['files'][:1]
                    elif kind == 'unknown': value['files'][0]['coordinate'] = 'private/unknown.jar'
                    elif kind == 'duplicate': value['files'].append(value['files'][0])
                    elif kind == 'changed': value['files'][0]['sha256'] = '0' * 64
                    else: value['outOfProcess'] = True
                    record.write_text(json.dumps(value))
                    with self.assertRaises(ValueError): patch.original_classpath(compiler, project, [core, library, app])


class CoroutineLoadedCopyTests(unittest.TestCase):
    def test_byte_equal_copy_requires_all_three_actual_class_identities(self):
        import hashlib, json
        from tools.java_guest import coroutine_patch as patch
        with tempfile.TemporaryDirectory() as temporary:
            project=Path(temporary); folder=project/'compiler-patch'; folder.mkdir()
            jar=folder/'teavm-core-patched.jar'; jar.write_bytes(b'owned selected jar')
            sha=hashlib.sha256(jar.read_bytes()).hexdigest()
            classes={name:hashlib.sha256(name.encode()).hexdigest() for name in patch.PATCH_CLASSES}
            receipt={'replacementJarSha256':sha,'replacedClasses':{
                name:{'replacementSha256':value} for name,value in classes.items()}}
            actual={'schemaVersion':'latent.java.coroutine-compiler-load.v1',
                'selectedOwnedReplacement':True,'replacementJarSha256':sha,
                'loadedJarSha256':sha,'codeSourceKind':'byte-identical-copy','loadedClasses':classes}
            marker=folder/'loaded.json'; marker.write_text(json.dumps(actual))
            self.assertEqual(patch.loaded(project,receipt)['loadedCompiler'],actual)
            for changes in ({'loadedJarSha256':'0'*64},{'codeSourceKind':'other'},{'codeSourceKind':[]},
                    {'loadedClasses':{}},{'loadedClasses':{**classes,'unknown.class':sha}},
                    {'loadedClasses':{**classes,next(iter(classes)):'0'*64}},
                    {'selectedOwnedReplacement':1},{'extra':'private path'}):
                with self.subTest(changes=tuple(changes)):
                    marker.write_text(json.dumps({**actual,**changes}))
                    with self.assertRaisesRegex(ValueError,'loaded-receipt-mismatch'):
                        patch.loaded(project,receipt)
            marker.write_text(json.dumps({**actual,'codeSourceKind':'owned-replacement'}))
            self.assertEqual(patch.loaded(project,receipt)['loadedCompiler']['codeSourceKind'],
                'owned-replacement')

    def test_gradle_load_fence_keeps_source_and_three_resource_identities(self):
        import inspect
        from tools.java_guest import coroutine_patch as patch
        source=inspect.getsource(patch.stage)
        for required in ('actualHash != hash', 'hash !=', 'expectedClasses.each',
                'java.nio.file.LinkOption.NOFOLLOW_LINKS', 'java.net.JarURLConnection',
                'loadedClass.classLoader != actual.classLoader', 'canonicalFile != observed',
                'classHash != expected', 'it.readNBytes(1048577)',
                'coroutine-compiler-preparation.json'):
            self.assertIn(required,source)
        self.assertNotIn('if (observed != selected)',source)


class JavaFailedLifecycleObservation(unittest.TestCase):
    def test_failed_actual_result_keeps_pending_peer_and_original_assertion(self):
        import json
        from tools.phase2_operator_process import WorkflowError
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            original=WorkflowError('java-http-fiber-ordinary-result')
            peer=SimpleNamespace(observation=lambda:{'schemaVersion':'fixture',
                'startedRequests':2,'requests':[{'vector':'pending-headers'},{'vector':'domain-json'}]})
            row={'exitCode':4,'decoded':None,'response':{'error':{'code':'guest-trap'}}}
            with mock.patch.object(node,'validate_result',side_effect=original):
                with self.assertRaises(WorkflowError) as caught:
                    node.validate_observed_result(row,0,{},peer,SimpleNamespace(evidence=root),1,
                        Gate('a'*32,2,'headers'),{'occupied':1},False,None)
            self.assertIs(caught.exception,original)
            value=json.loads((root/'invocation-failure.json').read_bytes())
            self.assertEqual(value['invocation'],row)
            self.assertEqual(value['peer']['startedRequests'],2)
            self.assertEqual(value['pendingOwner'],{'occupied':1})
            self.assertEqual(value['gate'],{'request':2,'phase':'headers'})
            self.assertIs(value['releasedOnce'],False)
            self.assertEqual(value['requestOffset'],1)

    def test_observation_error_never_replaces_original_result_failure(self):
        original=RuntimeError('original guest result')
        with (mock.patch.object(node,'validate_result',side_effect=original),
                mock.patch.object(node,'write_json',side_effect=ValueError('observer failure'))):
            with self.assertRaises(RuntimeError) as caught:
                node.validate_observed_result({},0,{},SimpleNamespace(observation=lambda:{}),
                    SimpleNamespace(evidence=Path('unused')),0,None,None,False,None)
        self.assertIs(caught.exception,original)


class JavaClosedPendingDiagnostic(unittest.TestCase):
    def test_pending_usage_is_closed_numeric_and_has_no_identity_or_payload_fields(self):
        value={'nextPageToken':None,'nodeUsage':{'unavailable':[],'counters':{
            'io_calls':'2','io_occupied_running_slots':'1','pool_pending_requests':'1',
            'private/path':'credential'}},'tenantUsage':{'unavailable':[],'counters':{
            'calls':'2','waiting':'1','live_children':'1','private':'payload'}}}
        expected={'status':'observed','node':{'io_calls':2,'io_occupied_running_slots':1,
            'pool_pending_requests':1},'tenant':{'calls':2,'waiting':1,'live_children':1}}
        self.assertEqual(node.closed_usage(value),expected)
        for changes in ({'nextPageToken':'private'}, {'nodeUsage':{'unavailable':['private'],'counters':{}}},
                {'nodeUsage':{'unavailable':[],'counters':{'io_calls':True}}},
                {'tenantUsage':{'unavailable':[],'counters':{'waiting':'private'}}},
                {'tenantUsage':{'unavailable':[],'counters':{'waiting':str(2**64)}}}):
            with self.subTest(changes=tuple(changes)):
                self.assertEqual(node.closed_usage({**value,**changes}),{'status':'unavailable'})

    def test_optional_usage_and_audit_failures_do_not_expose_private_exception_or_retry(self):
        client=SimpleNamespace(call=mock.Mock(side_effect=RuntimeError('private/path/token')))
        self.assertEqual(node.observe_usage(client,{'name':'owned'}),{'status':'unavailable'})
        client.call.assert_called_once_with('capability','list','--deployment','owned','--include-node-usage')
        client.call.reset_mock()
        self.assertEqual(node.observe_audit(client,'owned-call'),{'status':'unavailable'})
        client.call.assert_called_once_with('audit','query','--scope','tenant','--page-size','64')

    def test_audit_observer_retains_one_public_bounded_page_and_never_follows_cursor(self):
        value={'category':'success','data':{'records':[{'data':{'observation':{
            'identities':{'capability':{'rootActivation':'owned-call','capability':node.ACTIVATION,
                'operation':'register','private':'payload'}},'reason':'capacity'}}}],
            'page':{'nextPageToken':'opaque-owned-cursor'},
            'coverage':{'scanned':'1','droppedObservations':'2','unknownOutcomes':'0'}}}
        client=SimpleNamespace(call=mock.Mock(return_value=value))
        self.assertEqual(node.observe_audit(client,'owned-call'),{'status':'observed','complete':False,
            'rows':[{'capability':node.ACTIVATION,'operation':'register','reason':'capacity'}],
            'coverage':{'scanned':1,'droppedObservations':2,'unknownOutcomes':0}})
        client.call.assert_called_once()
        client.call.return_value={'category':'success','data':{'padding':'x'*262145}}
        self.assertEqual(node.observe_audit(client,'owned-call'),{'status':'unavailable'})

    def test_pending_diagnostic_samples_two_owner_snapshots_without_replaying_invocation(self):
        import itertools
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);selected={'publicationId':'published'}
            usage={'nextPageToken':None,'nodeUsage':{'unavailable':[],'counters':{'io_calls':'2'}},
                'tenantUsage':{'unavailable':[],'counters':{'calls':'2'}}}
            page={'category':'success','data':{'records':[],'page':{'nextPageToken':None},
                'coverage':{'scanned':'0','droppedObservations':'0','unknownOutcomes':'0'}}}
            def call(*args):return {'data':usage} if args[0]=='capability' else page
            client=SimpleNamespace(evidence=root,deadline=10000,call=mock.Mock(side_effect=call))
            process=SimpleNamespace(owner=SimpleNamespace(exited=mock.Mock(side_effect=[False]*4+[True])),
                close=mock.Mock(),drain=mock.Mock())
            samples=itertools.count()
            peer=SimpleNamespace(origin=lambda:{'host':'127.0.0.1','port':1},poll=mock.Mock(),
                gates=lambda:[Gate('a'*32,1,'headers')],
                observation=lambda:{'requests':[] if next(samples)==0 else [{'request':1}],
                    'openConnections':0,'failure':None})
            row={'exitCode':0,'processReaped':True,'decoded':['1:diagnostic:6:107:112:1:1:1:0:0'],
                'response':{'outcomeKnown':True,'data':{'resolvedRevision':selected,'activationId':'owned-call'}}}
            target={'name':'owned','budget':{'cpuFuel':1_000_000_000,'wallTimeLimitMillis':120000,'outboundRequests':8}}
            with mock.patch.object(node,'selected_revision',return_value=selected), \
                    mock.patch.object(node,'start_call',return_value=process) as start, \
                    mock.patch.object(node,'finish_call',return_value=row) as finish, \
                    mock.patch.object(node,'sample',return_value={'active':0}), \
                    mock.patch.object(node,'ready_sibling',return_value=False), \
                    mock.patch.object(node.time,'monotonic',side_effect=itertools.count(1000,.4)):
                result=node.diagnose_pending(client,SimpleNamespace(drain=mock.Mock()),target,peer,SimpleNamespace())
            start.assert_called_once();finish.assert_called_once();process.close.assert_called_once()
            self.assertEqual(len(result['pendingUsage']),2)
            self.assertTrue(all(row['usage']['node']['io_calls']==2 for row in result['pendingUsage']))
            self.assertEqual(client.call.call_count,3)
            self.assertEqual(result['audit']['rows'],[])
            self.assertIs(result['qualification'],False)

    def test_process_result_and_caught_observation_have_distinct_create_only_paths(self):
        from itertools import count
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);client=SimpleNamespace(evidence=root,deadline=time.monotonic()+10)
            process=SimpleNamespace(owner=SimpleNamespace(exited=lambda:True),close=mock.Mock())
            selected={'publicationId':'published'}
            row={'exitCode':0,'processReaped':True,'decoded':['1:diagnostic:5:0:105:0:1:1:0:0'],
                'response':{'outcomeKnown':True,'data':{'resolvedRevision':selected}}}
            steps=count()
            def observed():
                return {'requests':[] if next(steps)==0 else [{'request':1}], 'openConnections':0}
            peer=SimpleNamespace(origin=lambda:{'host':'127.0.0.1','port':1},
                observation=observed,poll=lambda _:None)
            def finish(_client,_process):
                node.write_json(root/'pending-closed-diagnostic.json',row)
                return row
            target={'budget':{'cpuFuel':1_000_000_000,'wallTimeLimitMillis':120000,'outboundRequests':8}}
            with mock.patch.object(node,'selected_revision',return_value=selected), \
                    mock.patch.object(node,'start_call',return_value=process), \
                    mock.patch.object(node,'finish_call',side_effect=finish), \
                    mock.patch.object(node,'sample',return_value={'active':0}):
                value=node.diagnose_pending(client,SimpleNamespace(),target,peer,SimpleNamespace())
            self.assertIs(value['qualification'],False)
            self.assertEqual(value['result']['childError'],105)
            self.assertEqual(read_json(root/'pending-closed-diagnostic.json'),row)
            self.assertEqual(read_json(root/'pending-closed-diagnostic-observation.json'),value)
            process.close.assert_called_once_with()

    def test_only_exact_numeric_fixture_result_is_published(self):
        value={'exitCode':0,'processReaped':True,'decoded':['1:diagnostic:6:111:105:1:1:1:0:0']}
        self.assertEqual(node.closed_diagnostic(value),{'status':'observed','phase':6,'rootError':111,
            'childError':105,'timerFired':True,'childEntered':True,'childCompleted':True,
            'siblingStatus':0,'childStatus':0})
        for changes in ({'decoded':['private/token/path']},{'decoded':[True]},
                {'decoded':['1:diagnostic:6:999:105:1:1:1:0:0']},
                {'decoded':['1:diagnostic:6:111:105:2:1:1:0:0']},
                {'decoded':['1:diagnostic:6:111:105:1:1:1:302:0']},
                {'decoded':['1:diagnostic:6:111:105:1:1:1:0:0','extra']},
                {'exitCode':4},{'exitCode':False},{'processReaped':1}):
            with self.subTest(changes=changes):
                self.assertEqual(node.closed_diagnostic({**value,**changes}),{'status':'unavailable'})

    def test_diagnostic_does_not_change_original_strict_result_or_budget_functions(self):
        import ast,hashlib
        # Source-derived immutable preimages; no historical Git object is needed
        # in a hosted shallow checkout to protect the original strict programme.
        expected={'validate_result': 'b34eca23f3b4ca0820e974863a342ae0b442bfe3055d042b9ac50a45f744032e', 'validate_observed_result': '9c22b499a68afa1357aa9f4947af14c11e8f41ba16b7ff2e99cffe7d7c1eaeaa', 'narrowed_target': '200c450f06e4f1132aef5e02d7d80601ad774ebeea9757906c92b8909bf6a952', 'invoke': '972fa506e550e8ec2b1244451b77bab51a8ab72c55d39ca43096735f60308e05'}
        tree=ast.parse((campaign.ROOT/'tools/java_http_fiber_node.py').read_bytes())
        for name,sha in expected.items():
            current=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name==name)
            self.assertEqual(hashlib.sha256(ast.dump(current,include_attributes=False).encode()).hexdigest(),sha)

    def test_fixed_preparation_survives_actual_retention_and_unrelated_json_is_omitted(self):
        from tools.java_capsule_build import retain_logs
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'private';source.mkdir();output=root/'public';output.mkdir()
            name='coroutine-compiler-preparation.json'; raw=b'{"schemaVersion":"public-fixture-identities"}'
            (source/name).write_bytes(raw);(source/'unrelated.json').write_bytes(b'private/path')
            (source/'actual.log').write_bytes(b'fixed public compiler log')
            retain_logs(source,output)
            self.assertEqual((output/name).read_bytes(),raw)
            self.assertEqual((output/'compiler-logs/actual.log').read_bytes(),b'fixed public compiler log')
            self.assertFalse((output/'unrelated.json').exists())
            (source/name).write_bytes(b' ' * 262145)
            other=root/'bounded';other.mkdir()
            with self.assertRaises(ValueError):retain_logs(source,other)
            self.assertFalse((other/name).exists())
