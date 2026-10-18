"""Source-only checks: no private compiler, native binary or node executes here."""
from contextlib import ExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import yaml

from tools import diagnose_go_entry_frames as frames
from tools.phase2_operator_process import WorkflowError
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, digest, read_file


def trace_line(value=None):
    return frames.PREFIX+json.dumps(value or {'available': True, 'truncated': False,
        'frames': [{'functionIndex': 12, 'functionOffset': 3, 'moduleOffset': 45}]}).encode()+b'\n'


class PrivateEntryFrames(unittest.TestCase):
    def test_only_two_source_overlays_capture_numbers_and_leave_dwarf_disabled(self):
        originals = {name: read_file(ROOT/name) for name in frames.PATHS}
        with tempfile.TemporaryDirectory() as directory:
            identities, overlays = frames.overlay_sources(ROOT, Path(directory))
            self.assertEqual(set(identities), set(frames.PATHS))
            self.assertEqual(len(overlays), 2)
            engine = read_file(overlays[1][0]).decode()
            self.assertIn('WasmBacktraceDetails::Disable', engine)
            self.assertNotIn('WasmBacktraceDetails::Enable', engine)
            self.assertEqual(engine.replace('wasm_backtrace_max_frames(std::num::NonZeroUsize::new(32))',
                'wasm_backtrace_max_frames(None)').encode(), originals[frames.PATHS[1]])
            observer = read_file(overlays[0][0]).decode()
            self.assertEqual(observer.replace(frames.OBSERVER, '').encode(), originals[frames.PATHS[0]])
            self.assertIn('take(32)', frames.OBSERVER)
            for forbidden in ('func_name', 'module_name', 'to_string', 'format!', 'Debug', 'error:?'):
                self.assertNotIn(forbidden, frames.OBSERVER)
            for name in frames.PATHS:
                self.assertEqual(read_file(ROOT/name), originals[name])
                self.assertEqual(identities[name]['original'], digest(originals[name]))

    def test_numeric_parser_drops_raw_stderr_and_refuses_names_unknown_fields_and_bad_numbers(self):
        expected = {'available': True, 'truncated': False,
            'frames': [{'functionIndex': 12, 'functionOffset': 3, 'moduleOffset': 45}]}
        self.assertEqual(frames.numeric_frames(b'private message /private/source.rs\n'+trace_line(expected)), expected)
        self.assertNotIn('private', json.dumps(expected))
        negatives = [trace_line(expected)*2, b'x'*65537]
        for key, value in (('functionIndex', True), ('functionIndex', -1), ('functionIndex', 2**32),
                           ('functionOffset', 2**53), ('moduleOffset', 'private'), ('function', 'private')):
            changed = deepcopy(expected)
            changed['frames'][0][key] = value
            negatives.append(trace_line(changed))
        changed = deepcopy(expected)
        changed['frames'] *= 33
        negatives.append(trace_line(changed))
        for raw in negatives:
            with self.subTest(bytes=len(raw)), self.assertRaises((WorkflowError, ValueError)):
                frames.numeric_frames(raw)
        empty = {'available': False, 'truncated': False, 'frames': []}
        self.assertEqual(frames.numeric_frames(trace_line(empty)), empty)

    def test_build_command_preserves_user_namespace_and_drops_privileges_before_locked_offline_build(self):
        with tempfile.TemporaryDirectory() as directory:
            _identities, overlays = frames.overlay_sources(ROOT, Path(directory))
            tools = {name: '/usr/bin/'+name for name in ('cargo', 'sudo', 'bwrap', 'setpriv', 'env')}
            context = {'uid': 1001, 'gid': 1001}
            command = frames.build_command(ROOT, overlays, {'PATH': '/tools', 'TMPDIR': '/private'}, tools, context)
            self.assertNotIn('--unshare-user', command)
            self.assertEqual(command.count('--ro-bind'), 2)
            self.assertLess(command.index('/usr/bin/setpriv'), command.index('/usr/bin/cargo'))
            for flag in ('--clear-groups', '--bounding-set=-all', '--inh-caps=-all', '--ambient-caps=-all', '--no-new-privs'):
                self.assertIn(flag, command)
            self.assertNotIn('TMPDIR', command)
            self.assertEqual(command[-10:], ['/usr/bin/cargo', '--config', '.cargo/managed-guest.toml', 'build',
                '--offline', '--locked', '-p', 'latentd', '--bin', 'latentd'])
            with self.assertRaisesRegex(WorkflowError, 'source-set'):
                frames.build_command(ROOT, overlays[:1], {}, tools, context)

    def test_runner_only_workspace_is_entered_after_credentials_and_capabilities_are_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ancestor = root/'runner-only'
            ancestor.mkdir(mode=0o700)
            workspace = ancestor/'checkout'
            workspace.mkdir(mode=0o700)
            for relative in (*frames.PATHS, frames.host.FRAME_PREFLIGHT_SOURCE):
                path = workspace/relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(read_file(ROOT/relative))
            overlays_root = root/'overlays'; overlays_root.mkdir()
            _identities, overlays = frames.overlay_sources(workspace, overlays_root)
            tools = {name: '/usr/bin/'+name for name in ('cargo', 'sudo', 'bwrap', 'setpriv', 'env')}
            command = frames.build_command(workspace, overlays, {'PATH': '/tools'}, tools, {'uid': 1001, 'gid': 1001})
            # bwrap drops requested caps before its chdir. UID0 without DAC
            # override must not traverse a runner-only ancestor before setpriv.
            initial = command.index('--chdir')
            self.assertEqual(command[initial+1], '/')
            drop = command.index('/usr/bin/setpriv')
            enter = command.index('/usr/bin/env')
            self.assertLess(initial, drop)
            self.assertLess(drop, enter)
            self.assertEqual(command[enter+1:enter+3], ['--chdir', str(workspace)])
            for option in ('--reuid', '--regid', '--clear-groups', '--bounding-set=-all',
                           '--inh-caps=-all', '--ambient-caps=-all', '--no-new-privs'):
                self.assertLess(command.index(option), enter)
            self.assertEqual(command[command.index('--reuid')+1], '1001')
            self.assertEqual(command[command.index('--regid')+1], '1001')
            self.assertNotIn('--unshare-user', command)

    def test_replay_checkpoints_single_integer_control_before_failed_retirement_and_keeps_only_numeric_frames(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as patches:
            root = Path(directory)
            host_binary = root/'private-latentd'
            host_binary.write_bytes(b'not-executed')
            client, service, peer, probe = Mock(), Mock(), Mock(), Mock()
            probe.sample.return_value = {}
            peer.line.return_value = {'origins': {'primary': {'host': '127.0.0.1', 'port': 1}}}
            service.buffers = [bytearray(), bytearray(b'private raw error\n'+trace_line())]
            client.call.return_value = {'data': {'operation': {'publication': {'id': 'publication'}}}}
            runtime, authorized = [{'capability': 'runtime'}], [{'capability': 'runtime'}, {'capability': 'http'}]
            row = {'exitCode': 4, 'processReaped': True, 'decoded': None, 'response': {'data': {
                'terminalState': 'guest_trap', 'consumption': {'outboundRequests': 0, 'childCalls': 0, 'effectCount': 0}}}}
            output = root/'node'
            def fence(*_args):
                self.assertEqual(json.loads(read_file(output/'entry.json'))['entry'], row)
                raise WorkflowError('test-retirement-refusal')
            replacements = {'RecordingClient': Mock(return_value=client), 'configuration': Mock(return_value=root/'config'),
                'connect': Mock(return_value=service), 'Probe': Mock(return_value=probe),
                'grants': Mock(return_value=(runtime, authorized)), 'deploy': Mock(return_value={'name': 'route'}),
                'retire_case': fence}
            for name, value in replacements.items():
                patches.enter_context(patch.object(frames.entry.node, name, value))
            patches.enter_context(patch.object(frames, 'Process', return_value=peer))
            invoke = patches.enter_context(patch.object(frames.entry, 'invoke_signature', return_value=row))
            with self.assertRaisesRegex(WorkflowError, 'test-retirement-refusal'):
                frames.replay(root/'original-releases', {'latent': root/'latent', 'latentd': host_binary},
                              output, frames.time.monotonic()+90)
            self.assertIs(replacements['deploy'].call_args.kwargs['grants'], runtime)
            self.assertEqual(invoke.call_count, 1)
            self.assertEqual(invoke.call_args.args[2:], ('integer-control', [], 'entry-integer-control'))
            saved = json.loads(read_file(output/'observation.json'))
            self.assertEqual(saved['entry'], row)
            self.assertEqual(saved['numericFrames'], frames.numeric_frames(trace_line()))
            self.assertNotIn('private raw error', json.dumps(saved))
            self.assertFalse(saved['qualification'])
            self.assertEqual(saved['status'], 'incomplete')
            service.close.assert_called_once()
            peer.close.assert_called_once()

    def test_frozen_component_drift_stops_before_private_compilation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            diagnostic = root/'diagnostic'
            (diagnostic/'without-http/build').mkdir(parents=True)
            component = diagnostic/'without-http/build/component.wasm'
            component.write_bytes(b'original')
            identity = file_identity(component)
            observation = {'status': 'observed', 'qualification': False, 'variants': [{'variant': 'without-http',
                'compileExitCode': 0, 'component': identity, 'node': {'status': 'observed', 'signatures': [{
                    'function': 'integer-control', 'outcome': 'trapped'}]}}]}
            (diagnostic/'observation.json').write_text(json.dumps(observation))
            component.write_bytes(b'changed')
            with patch.object(frames, 'run_bounded_result') as compiler, patch.object(frames, 'replay') as replay:
                record = frames.diagnose(diagnostic, root/'native', root/'private')
            self.assertEqual(record['status'], 'incomplete')
            self.assertEqual(record['stage'], 'inputs')
            self.assertFalse(record['qualification'])
            compiler.assert_not_called()
            replay.assert_not_called()
            self.assertTrue((root/'private/observation.json').is_file())

    def test_private_build_bounds_and_frozen_input_recheck_precede_single_replay(self):
        for tamper in (False, True):
            with self.subTest(tamper=tamper), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                diagnostic = root/'diagnostic'
                (diagnostic/'without-http/build').mkdir(parents=True)
                component = diagnostic/'without-http/build/component.wasm'
                component.write_bytes(b'not-executed-component')
                identity = file_identity(component)
                releases = diagnostic/'without-http/node/releases'
                releases.mkdir(parents=True)
                (releases/'signed-input').write_bytes(b'not-executed-signed-fixture')
                native = root/'native'
                (native/'native-binaries').mkdir(parents=True)
                binaries, identities = {}, {}
                for name, key in frames.entry.NATIVE_NAMES.items():
                    path = native/'native-binaries'/key.replace('/', '-')
                    path.write_bytes(name.encode())
                    binaries[name], identities[name] = path, file_identity(path)
                (native/'qualification.json').write_text(json.dumps({
                    'schemaVersion': 'latent.go-capsule.qualification.v1', 'status': 'passed',
                    'binaries': {key: identities[name] for name, key in frames.entry.NATIVE_NAMES.items()}}))
                entry = {'response': {'data': {'resolvedRevision': {'releaseDigest': identity['sha256']}}}}
                (diagnostic/'observation.json').write_text(json.dumps({'status': 'observed', 'qualification': False,
                    'binaries': identities, 'variants': [{'variant': 'without-http', 'compileExitCode': 0,
                    'component': identity, 'node': {'status': 'observed', 'signatures': [{
                        'function': 'integer-control', 'outcome': 'trapped', 'entry': entry}]}}]}))
                target = root/'target'
                (target/'debug').mkdir(parents=True)
                def compile_private(command, cwd, environment, maximum, output_bound):
                    self.assertEqual(command[-10:], ['/usr/bin/cargo', '--config', '.cargo/managed-guest.toml',
                        'build', '--offline', '--locked', '-p', 'latentd', '--bin', 'latentd'])
                    self.assertEqual(cwd, ROOT)
                    self.assertGreater(maximum, 0)
                    self.assertLessEqual(maximum, 450)
                    self.assertEqual(output_bound, 1048576)
                    self.assertEqual(environment['CARGO_TARGET_DIR'], str(target.resolve()))
                    (target/'debug/latentd').write_bytes(b'not-executed-private-host')
                    if tamper:
                        binaries['latent'].write_bytes(b'changed')
                    preflight = {'uid': 1001, 'gid': 1001, 'sameUserNamespace': True, 'capabilitiesDropped': True,
                        'rootOwnershipPreserved': True, 'temporaryAncestorsAccepted': True}
                    return SimpleNamespace(returncode=0, stdout=b'LSF_GO_DIAG_HOST '+json.dumps(preflight).encode()+b'\n', stderr=b'')
                with patch.dict(os.environ, {'CARGO_TARGET_DIR': str(target)}), \
                        patch.object(frames, 'build_environment', return_value={'PATH': '/tools'}), \
                        patch.object(frames.host, 'frame_host_context', return_value={'uid': 1001, 'gid': 1001}), \
                        patch.object(frames.shutil, 'which', side_effect=lambda name: '/usr/bin/'+name), \
                        patch.object(frames, 'run_bounded_result', side_effect=compile_private), \
                        patch.object(frames, 'replay', return_value={'entry': entry, 'qualification': False}) as replay:
                    if tamper:
                        with self.assertRaisesRegex(WorkflowError, 'original-input-mutated'):
                            frames.diagnose(diagnostic, native, root/'private')
                        replay.assert_not_called()
                        result = json.loads(read_file(root/'private/observation.json'))
                        self.assertFalse(result['frozenBinariesUnchanged'])
                        self.assertEqual(result['status'], 'incomplete')
                    else:
                        result = frames.diagnose(diagnostic, native, root/'private')
                        self.assertEqual(replay.call_count, 1)
                        self.assertEqual(replay.call_args.args[0], releases)
                        self.assertEqual(replay.call_args.args[1]['latent'], binaries['latent'])
                        self.assertEqual(replay.call_args.args[1]['latentd'], root/'private/private-latentd')
                        self.assertEqual(result['status'], 'observed')
                        for key in ('originalSourceUnchanged', 'originalComponentUnchanged',
                                    'signedReleaseUnchanged', 'frozenBinariesUnchanged'):
                            self.assertIs(result[key], True)
                self.assertFalse(result['qualification'])
                self.assertFalse(result['privateBinaryPublished'])

    def test_failed_private_launch_retains_only_closed_preflight_and_launcher_categories(self):
        failure = {'phase': 'temp-ancestors', 'code': 'temporary-mode', 'exception': 'SystemExit'}
        stderr = (b'private error /secret/source token=private-value\n'
            b'bwrap: creating new namespace /secret failed: Operation not permitted\n'
            b'LSF_GO_DIAG_HOST_FAILURE '+json.dumps(failure).encode()+b'\n')
        result = frames.private_build_observation(SimpleNamespace(returncode=1, stdout=b'', stderr=stderr))
        self.assertEqual(result, {'buildExitCode': 1, 'hostPreflight': None, 'compilerErrorCodes': [],
            'launchObservation': {'preflightFailure': failure, 'launcherFamilies': ['bwrap'],
                'launcherCategories': ['namespace-setup', 'permission-denied'], 'rawLauncherOutputRetained': False}})
        self.assertNotIn('private-value', json.dumps(result))
        self.assertNotIn('/secret', json.dumps(result))
        for key in failure:
            changed = {**failure, key: '/secret/private-value'}
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'failure-shape'):
                frames.private_build_observation(SimpleNamespace(returncode=1, stdout=b'',
                    stderr=b'LSF_GO_DIAG_HOST_FAILURE '+json.dumps(changed).encode()+b'\n'))
        for raw in (b'LSF_GO_DIAG_HOST_FAILURE {}\n'*2,
                    b'LSF_GO_DIAG_HOST_FAILURE '+b'x'*513):
            with self.assertRaisesRegex(ValueError, 'failure-shape'):
                frames.private_build_observation(SimpleNamespace(returncode=1, stdout=b'', stderr=raw))

    def test_private_observer_is_last_after_all_acceptance_with_no_binary_or_raw_output_artifact(self):
        model = yaml.safe_load(read_file(ROOT/'.github/workflows/go-guest.yml'))
        job = model['jobs']['upstream-probe']
        self.assertEqual(job['timeout-minutes'], 45)
        steps = job['steps']
        index = next(i for i, step in enumerate(steps) if step.get('name') == 'Observe private numeric frames for the unchanged Go integer entry')
        observer = steps[index]
        self.assertEqual(observer['if'], "${{ !cancelled() && failure() && steps.normal_go_qualification.outcome == 'success' }}")
        self.assertNotIn('continue-on-error', observer)
        self.assertTrue(all('run' not in step for step in steps[index+1:]))
        cache = next(step for step in steps if 'rust-cache@' in step.get('uses', ''))
        self.assertIs(cache['with']['save-if'], False)
        artifacts = steps[index+1]['with']['path']
        selected = [line.strip() for line in artifacts.splitlines() if 'go-entry-private-frames/' in line]
        self.assertEqual(selected, ['${{ runner.temp }}/go-entry-private-frames/observation.json',
            '${{ runner.temp }}/go-entry-private-frames/node/observation.json',
            '${{ runner.temp }}/go-entry-private-frames/node/entry.json'])


if __name__ == '__main__':
    unittest.main()
