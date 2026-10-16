"""Runtime overlays preserve pinned sources and separate scheduler from authority."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.go_guest import runtime


def sources():
    return {
        "runtime/lock_futex.go": "func beforeIdle(int64, int64) (*g, bool) { return nil, false }\n",
        "runtime/lock_sema.go": "func beforeIdle(int64, int64) (*g, bool) { return nil, false }\n",
        "runtime/lock_js.go": "func beforeIdle(now, pollUntil int64) (gp *g, otherReady bool) { return nil, false }\n",
        "runtime/lock_wasip1.go": "func beforeIdle(int64, int64) (*g, bool) {\n\treturn nil, false\n}\n",
        "runtime/proc.go": "gp, otherReady := beforeIdle(now, pollUntil)\n",
        "runtime/os_wasip1.go": (
            "//go:wasmimport wasi_snapshot_preview1 clock_time_get\n//go:noescape\n"
            "func clock_time_get(clock_id clockid, precision timestamp, time *timestamp) errno\n"
            "//go:wasmimport wasi_snapshot_preview1 random_get\n//go:noescape\n"
            "func random_get(buf *byte, bufLen size) errno\n"),
        "syscall/fs_wasip1.go": "//go:wasmimport wasi_snapshot_preview1 random_get\n//go:noescape\nfunc random_get(buf *byte, bufLen size) Errno\n",
        "syscall/syscall_wasip1.go": "//go:wasmimport wasi_snapshot_preview1 clock_time_get\n//go:noescape\nfunc clock_time_get(id clockid, precision timestamp, time *timestamp) Errno\n",
    }


class GoRuntimeOverlayTests(unittest.TestCase):
    def test_private_frame_host_context_refuses_local_execution_before_inspecting_privilege(self):
        import os
        from tools import diagnose_go_timer_failure as diagnostic
        for environment in ({}, {'GITHUB_ACTIONS': 'true'}, {'RUNNER_OS': 'Linux'},
                            {'GITHUB_ACTIONS': 'false', 'RUNNER_OS': 'Linux'},
                            {'GITHUB_ACTIONS': 'true', 'RUNNER_OS': 'Windows'}):
            with self.subTest(environment=environment), patch.dict(os.environ, environment, clear=True), \
                    patch.object(os, 'getuid', create=True) as getuid:
                with self.assertRaisesRegex(ValueError, 'hosted-Linux-only'):
                    diagnostic.frame_host_context()
                getuid.assert_not_called()

    def test_private_frame_command_drops_privilege_before_cargo_without_replacing_user_namespace(self):
        from tools import diagnose_go_timer_failure as diagnostic
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preflight = root / diagnostic.FRAME_PREFLIGHT_SOURCE
            preflight.parent.mkdir(parents=True)
            preflight.write_bytes(diagnostic.frame_preflight_source(diagnostic.ROOT).read_bytes())
            overlays = [(root / 'private' / name, root / name) for name in diagnostic.PATHS]
            context = {'uid': 1001, 'gid': 118, 'groups': [118], 'uidMapDigest': 'a' * 64,
                       'root': [0, 0, 0o755]}
            command = diagnostic.frame_command(root, overlays,
                {'PATH': '/controlled', 'HOME': '/home/runner', 'TMPDIR': 'unsafe-output'},
                '/cargo', '/bwrap', '/sudo', '/setpriv', context)
            self.assertEqual(command[:4], ['/sudo', '-n', '--', '/bwrap'])
            self.assertNotIn('--unshare-all', command)
            self.assertNotIn('--unshare-user', command)
            self.assertNotIn('--uid', command)
            self.assertNotIn('--gid', command)
            self.assertNotIn('TMPDIR', command)
            self.assertIn('--clearenv', command)
            self.assertEqual(command[command.index('--cap-drop'):command.index('--cap-drop') + 2],
                             ['--cap-drop', 'ALL'])
            self.assertEqual([command[i + 1] for i, value in enumerate(command) if value == '--cap-add'],
                             ['CAP_SETUID', 'CAP_SETGID', 'CAP_SETPCAP'])
            drop = command.index('/setpriv')
            self.assertEqual(command[drop:drop + 10], ['/setpriv', '--reuid', '1001', '--regid', '118',
                '--clear-groups', '--bounding-set=-all', '--inh-caps=-all', '--ambient-caps=-all', '--no-new-privs'])
            self.assertLess(drop, command.index('/cargo'))
            self.assertEqual(command[drop + 11:drop + 14], ['-I', '-B', str(preflight.resolve())])
            self.assertNotIn('-c', command)
            self.assertEqual(command.count('--ro-bind'), 3)
            self.assertIn('--offline', command)
            self.assertIn('--locked', command)
            with self.assertRaisesRegex(ValueError, 'source-set'):
                diagnostic.frame_command(root, overlays[:-1], {}, '/cargo', '/bwrap', '/sudo', '/setpriv', context)

    def test_private_frame_preflight_source_requires_exact_selected_file_without_fallback(self):
        from tools import diagnose_go_timer_failure as diagnostic
        from tools.go_guest import frame_preflight
        selected = diagnostic.frame_preflight_source(diagnostic.ROOT)
        self.assertEqual(Path(frame_preflight.__file__).resolve(), selected)
        original = selected.read_bytes()
        self.assertEqual('sha256:' + hashlib.sha256(original).hexdigest(), diagnostic.FRAME_PREFLIGHT_DIGEST)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / diagnostic.FRAME_PREFLIGHT_SOURCE
            with self.assertRaisesRegex(ValueError, 'preflight-source'):
                diagnostic.frame_preflight_source(root)
            path.parent.mkdir(parents=True)
            path.write_bytes(original)
            self.assertEqual(diagnostic.frame_preflight_source(root), path.resolve())
            for changed in (original + b'\n# changed', b'x' * 8193):
                with self.subTest(size=len(changed)):
                    path.write_bytes(changed)
                    with self.assertRaisesRegex(ValueError, 'preflight-preimage'):
                        diagnostic.frame_preflight_source(root)

    def test_private_frame_host_preflight_refuses_wrong_credentials_caps_maps_or_temporary_ancestors(self):
        import contextlib
        import io
        import os
        import pathlib
        import stat
        import sys
        from types import SimpleNamespace
        from tools import diagnose_go_timer_failure as diagnostic
        from tools.go_guest import frame_preflight
        mapping = b'0 0 4294967295\n'
        expected = {'uid': 1001, 'gid': 118, 'groups': [118],
                    'uidMapDigest': hashlib.sha256(mapping).hexdigest(), 'root': [0, 0, 0o755]}
        def run(fault=None):
            executed = []
            class Entry:
                def __init__(self, value): self.value = value
                def read_text(self):
                    if fault == 'exception': raise PermissionError('private path and credential must not escape')
                    return '\n'.join(f'{key}:\t{1 if fault == key else 0}' for key in
                        ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb')) + '\nNoNewPrivs:\t' + ('0' if fault == 'privs' else '1')
                def read_bytes(self): return b'changed mapping' if fault == 'mapping' else mapping
                def resolve(self, **kwargs): return self
                @property
                def parents(self): return (Entry('/'),)
                def stat(self):
                    mode = 0o755 if self.value == '/' else (0o777 if fault == 'temporary' else 0o1777)
                    return SimpleNamespace(st_uid=65534 if fault == 'owner' else 0, st_gid=0,
                                           st_mode=stat.S_IFDIR | mode)
            output, errors = io.StringIO(), io.StringIO()
            with patch.object(pathlib, 'Path', Entry), \
                    patch.object(os, 'getuid', return_value=1001, create=True), \
                    patch.object(os, 'geteuid', return_value=0 if fault == 'root' else 1001, create=True), \
                    patch.object(os, 'getgid', return_value=118, create=True), \
                    patch.object(os, 'getegid', return_value=118, create=True), \
                    patch.object(os, 'getgroups', return_value=[0] if fault == 'groups' else [], create=True), \
                    patch.object(os, 'execve', side_effect=lambda *args: executed.append(args)), \
                    patch.object(tempfile, 'gettempdir', return_value='/tmp'), \
                    patch.dict(os.environ, {'TMPDIR': 'unsafe'} if fault == 'environment' else {}, clear=True), \
                    patch.object(sys, 'argv', ['preflight'] if fault == 'missing-arguments' else
                        ['preflight', 'private malformed payload' if fault == 'invalid-arguments' else
                         json.dumps(expected), '/cargo', '--locked']), \
                    contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                if fault:
                    with self.assertRaisesRegex(SystemExit, 'preflight-refused'):
                        frame_preflight.main()
                else:
                    frame_preflight.main()
            self.assertEqual(len(executed), 0 if fault else 1)
            return (output.getvalue() + errors.getvalue()).encode()
        value = diagnostic.frame_host_observation(run())
        self.assertEqual(value['uid'], 1001)
        self.assertTrue(value['sameUserNamespace'])
        for fault in ('root', 'groups', 'CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb',
                      'privs', 'mapping', 'owner', 'temporary', 'environment', 'exception',
                      'missing-arguments', 'invalid-arguments'):
            with self.subTest(fault=fault):
                raw = run(fault)
                self.assertIsNone(diagnostic.frame_host_observation(raw))
                observation = diagnostic.frame_launch_observation(raw)
                self.assertIsNotNone(observation['preflightFailure'])
                self.assertNotIn(b'private path and credential', raw)
                self.assertNotIn(b'private malformed payload', raw)
                if fault == 'exception':
                    self.assertEqual(observation['preflightFailure'],
                        {'phase': 'capsets', 'code': 'exception', 'exception': 'PermissionError'})
                elif fault in ('missing-arguments', 'invalid-arguments'):
                    self.assertEqual(observation['preflightFailure'],
                        {'phase': 'arguments', 'code': 'exception',
                         'exception': 'IndexError' if fault == 'missing-arguments' else 'JSONDecodeError'})
                else:
                    self.assertEqual(observation['preflightFailure']['exception'], 'SystemExit')
        for raw in (b'LSF_GO_DIAG_HOST {}\n', run() * 2,
                    b'LSF_GO_DIAG_HOST ' + b'x' * 1025):
            with self.assertRaises((ValueError, json.JSONDecodeError)):
                diagnostic.frame_host_observation(raw)

    def test_private_frame_launch_observation_exports_only_closed_failure_categories(self):
        from tools import diagnose_go_timer_failure as diagnostic
        private = b'private-host-path credential-value arbitrary-untrusted-output'
        raw = b'\n'.join((b'bwrap: Creating new namespace failed: Operation not permitted ' + private,
            b'/usr/bin/setpriv: setresuid failed: Permission denied ' + private,
            b'sudo: a password is required ' + private,
            b'python3.13: unexpected diagnostic ' + private, private))
        value = diagnostic.frame_launch_observation(raw)
        self.assertEqual(value, {'preflightFailure': None,
            'launcherFamilies': ['bwrap', 'python', 'setpriv', 'sudo'],
            'launcherCategories': ['authentication', 'credential-transition', 'namespace-setup', 'other', 'permission-denied'],
            'rawLauncherOutputRetained': False})
        self.assertNotIn('private-', json.dumps(value))
        self.assertEqual(diagnostic.frame_launch_observation(private)['launcherFamilies'], [])
        for field in ('phase', 'code', 'exception'):
            bad = {'phase': 'capsets', 'code': 'CapBnd', 'exception': 'SystemExit'}
            bad[field] = private.decode()
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'failure-shape'):
                diagnostic.frame_launch_observation(b'LSF_GO_DIAG_HOST_FAILURE ' + json.dumps(bad).encode())
        with self.assertRaisesRegex(ValueError, 'failure-shape'):
            diagnostic.frame_launch_observation(b'LSF_GO_DIAG_HOST_FAILURE {}\n' * 2)
        for scalar in (b'42', b'null', b'[]', b'"private"'):
            with self.subTest(scalar=scalar), self.assertRaisesRegex(ValueError, 'failure-shape'):
                diagnostic.frame_launch_observation(b'LSF_GO_DIAG_HOST_FAILURE ' + scalar)

    def test_terminal_panic_probe_executes_checked_pointer_type_and_decimal_guards(self):
        import shutil
        import subprocess
        from tools.go_guest import panic_probe
        from tools.diagnose_go_timer_failure import leb
        node = shutil.which('node')
        if not node:
            self.skipTest('Node unavailable for isolated Wasm instruction controls')
        rows = panic_probe.reasons()
        self.assertEqual(len(rows), 68)
        self.assertEqual([row['id'] for row in rows], list(range(1, 69)))
        def core(body):
            result = bytearray(b'\0asm\x01\0\0\0')
            for kind, payload in [(1, b'\x01\x60\x01\x7f\x01\x7f'), (3, b'\x01\0'),
                    (5, b'\x01\0\x02'), (6, b'\x01\x7f\x01\x41\x80\x08\x0b'),
                    (7, b'\x02\x05probe\0\0\x06memory\x02\0'), (10, b'\x01' + leb(len(body)) + body)]:
                result.append(kind); result.extend(leb(len(payload))); result.extend(payload)
            return bytes(result)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for bit in range(7):
                (root / f'bit-{bit}.wasm').write_bytes(core(panic_probe.body(bit)))
            for row in rows:
                (root / f'confirm-{row["id"]}.wasm').write_bytes(core(panic_probe.body(0, candidate=row['id'])))
            (root / 'rows.json').write_text(json.dumps(rows), encoding='utf-8')
            result = subprocess.run([node, str(runtime.ROOT / 'tools/tests/fixtures/go_terminal_panic_probe.cjs'), str(root)],
                check=True, capture_output=True, text=True, timeout=30)
            self.assertEqual(json.loads(result.stdout), {'checks': 1705, 'normalComponentExecuted': False})
        for bit in (-1, 7, True, '0'):
            with self.subTest(bit=bit), self.assertRaisesRegex(ValueError, 'bit-bound'):
                panic_probe.body(bit)
        for selected in (0, 69, True):
            with self.subTest(selected=selected), self.assertRaisesRegex(ValueError, 'candidate-bound'):
                panic_probe.body(0, candidate=selected)

    def test_terminal_panic_candidate_requires_separate_confirmation_and_never_exports_payload(self):
        from tools import diagnose_go_timer_failure as diagnostic
        from tools.go_guest import panic_probe
        selected = 1
        row = panic_probe.reasons()[selected - 1]
        terminal = {'publicObservation': {'completedOrdinaryModes': [0, 1, 2, 18, 19, 20]}}
        reason = {'status': 'candidate-supported-by-fresh-confirmation', 'confirmedCandidate': {
            'literalDigest': 'sha256:7ae8886b4fc9611bf0a852f79761ac8976a9cb65002d0eb02542f45c8dfdf7b8'}}
        def probe(*_args, panic_bit=None, panic_id=None, **_options):
            matched = panic_id == selected if panic_id is not None else bool(selected >> panic_bit & 1)
            return {'privateComponentDigest': 'controlled-component', 'compilerErrorCodes': [],
                    'publicObservation': {'nativeCaseStarted': True,
                        'completedOrdinaryModes': terminal['publicObservation']['completedOrdinaryModes'],
                        'trapKinds': ['integer-division-by-zero' if matched else 'unreachable-code']}}, 1
        with tempfile.TemporaryDirectory() as directory, patch.object(diagnostic, 'ordinary_terminal_diagnostic', side_effect=probe):
            value, used = diagnostic.known_panic_diagnostic(None, Path(directory), None, None, None,
                lambda: 1, terminal, reason, 0)
            self.assertEqual(value['status'], 'terminal-panic-family-supported-by-fresh-confirmation')
            self.assertEqual(value['confirmedCandidate'], {key: row[key] for key in ('id', 'patternDigest', 'sources')}
                             | {'containsNumericFields': any('decimal' in x for x in row['segments'])})
            self.assertEqual(used, 8)
            self.assertFalse(value['baselineCauseProven'])
            self.assertFalse(value['bitRunsSameCauseProven'])
            self.assertFalse(value['runtimeOriginProven'])
            self.assertTrue(value['numericBoundsAreDiagnosticOnly'])
            self.assertFalse(value['rawGuestMessageRetained'])
            self.assertFalse(value['rawNumericPayloadRetained'])
            def unconfirmed(*args, **options):
                result, count = probe(*args, **options)
                if options.get('panic_id') is not None:
                    result['publicObservation']['trapKinds'] = ['unreachable-code']
                return result, count
            with patch.object(diagnostic, 'ordinary_terminal_diagnostic', side_effect=unconfirmed):
                second = Path(directory) / 'unconfirmed'; second.mkdir()
                failed, _ = diagnostic.known_panic_diagnostic(None, second, None, None, None,
                    lambda: 1, terminal, reason, 0)
            self.assertEqual(failed['status'], 'candidate-not-confirmed')
            self.assertNotIn('confirmedCandidate', failed)

    def test_terminal_public_metadata_preserves_only_closed_traps_and_exact_completed_modes(self):
        from tools.diagnose_go_timer_failure import terminal_metadata
        self.assertEqual(terminal_metadata(b'private arbitrary panic\nrunning 1 test\n'
            b'go-component-activation-v3 iteration=0 mode=20 consumption=private\n'
            b'guest trapped: unreachable-code\n'),
            {'trapKinds': ['unreachable-code'], 'completedOrdinaryModes': [20], 'nativeCaseStarted': True})
        self.assertEqual(terminal_metadata(b'guest trapped: arbitrary private text\n')['trapKinds'], [])
        for raw in (b'guest trapped: unreachable-code\nguest trapped: memory-out-of-bounds\n',
                    b'go-component-activation-v3 iteration=0 mode=20 consumption=\n' * 33):
            with self.assertRaisesRegex(ValueError, 'classifier-bound'):
                terminal_metadata(raw)

    def test_private_frame_preparation_failure_keeps_ordinary_terminal_record_without_overwriting(self):
        from subprocess import CompletedProcess
        from tools import diagnose_go_timer_failure as diagnostic
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = root / 'fixture'; (fixture / 'build').mkdir(parents=True)
            component = b'actual fixture identity for source-only driver control'
            (fixture / 'build/component.wasm').write_bytes(component)
            record = {'profile': 'go-component-activation-v3', 'fixture': 'timers',
                      'componentDigest': diagnostic.digest(component), 'sourceDigest': 'exact-source'}
            (fixture / 'GO-ACTIVATION-COMPILE.json').write_text(json.dumps(record))
            terminal = {'qualification': False, 'publicObservation': {
                'trapKinds': ['unreachable-code'], 'nativeCaseStarted': False}}
            events = []
            def ordinary(*args):
                events.append('ordinary-native')
                return terminal, 64
            def private(*args):
                events.append('private-source')
                return CompletedProcess([], 101, b'running 1 test\nLSF_GO_DIAG_STAGE entered\n',
                    b'panicked at crates/latent-wasmtime/tests/local_service/fixture.rs:506:14: private')
            with patch.object(diagnostic, 'overlay_sources', return_value=({}, [])), \
                    patch.object(diagnostic, 'frame_host_context', return_value={}), \
                    patch.object(diagnostic, 'frame_command', return_value=['controlled']), \
                    patch.object(diagnostic.shutil, 'which', return_value='/controlled/tool'), \
                    patch.object(diagnostic.sys, 'platform', 'linux'), \
                    patch.object(diagnostic, 'ordinary_terminal_diagnostic', side_effect=ordinary), \
                    patch.object(diagnostic, 'run_bounded_result', side_effect=private):
                output = root / 'output'
                value = diagnostic.diagnose(fixture, output)
            self.assertEqual(events, ['ordinary-native', 'private-source'])
            self.assertEqual(value['terminalDiagnostic'], terminal)
            self.assertEqual(value['privateFramesStatus'], 'not-run-before-guest-invocation')
            self.assertEqual(value['executionMetadata']['stages'], ['entered'])
            self.assertEqual(json.loads((output / 'GO-PRIVATE-FRAMES.json').read_bytes()), value)
            self.assertNotIn('privateFramesStatus', json.loads((output / 'GO-PRIVATE-FRAMES-initial.json').read_bytes()))

    def test_private_wasm_frame_observer_preserves_original_sources_and_bounds_the_overlay(self):
        from tools.diagnose_go_timer_failure import PATHS, overlay_sources
        original = {name: (runtime.ROOT / name).read_bytes() for name in PATHS}
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            identities, overlays = overlay_sources(runtime.ROOT, output)
            self.assertEqual(len(overlays), 3)
            for private, source in overlays:
                self.assertTrue(private.is_relative_to(output))
                self.assertEqual(source.read_bytes(), original[source.relative_to(runtime.ROOT).as_posix()])
                self.assertNotEqual(private.read_bytes(), source.read_bytes())
            observer = (output / 'private-source' / PATHS[0]).read_text()
            self.assertIn('downcast_ref::<wasmtime::WasmBacktrace>()', observer)
            self.assertIn('frames().iter().take(32)', observer)
            self.assertNotIn('format!("{error:?}")', observer)
            self.assertTrue(all(value['originalDigest'] != value['privateDigest'] for value in identities.values()))

    def test_private_frame_output_excludes_native_messages_and_rejects_unbounded_or_unexpected_data(self):
        from tools.diagnose_go_timer_failure import execution_metadata, frames_from_output
        def encode(value):
            return b'LSF_GO_WASM_FRAME ' + json.dumps(value).encode() + b'\n'
        frame = {'function': 'runtime.(*mheap).allocSpan', 'functionIndex': 42,
                 'functionOffset': 12, 'moduleOffset': 1000}
        self.assertEqual(frames_from_output(b'native configuration secret\n' + encode(frame)), [frame])
        invalid = [{**frame, 'nativeError': 'secret'}, {**frame, 'function': 'path with spaces'},
                   {**frame, 'function': 'x' * 161}, {**frame, 'functionIndex': -1},
                   {**frame, 'moduleOffset': 2**64}, {**frame, 'functionOffset': True}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'output-shape'):
                frames_from_output(encode(value))
        with self.assertRaisesRegex(ValueError, 'output-shape'):
            frames_from_output(encode(frame) * 33)
        metadata = execution_metadata(b'private error secret\nLSF_GO_DIAG_STAGE entered\n'
            b'LSF_GO_DIAG_STAGE prepared\nLSF_GO_DIAG_CLASSIFY {"traceAvailable":false,"trapAvailable":true}\n'
            b'panicked at crates/latent-wasmtime/tests/local_service/runtime.rs:253:9: secret\n')
        self.assertEqual(metadata, {'stages': ['entered', 'prepared'],
            'classifiers': [{'traceAvailable': False, 'trapAvailable': True}],
            'panicSourceSites': ['crates/latent-wasmtime/tests/local_service/runtime.rs:253:9'], 'outcomes': []})
        for raw in (b'LSF_GO_DIAG_STAGE prepared\n', b'LSF_GO_DIAG_STAGE entered\n' * 2,
                    b'LSF_GO_DIAG_CLASSIFY {"traceAvailable":false,"trapAvailable":"secret"}\n',
                    b'LSF_GO_DIAG_CLASSIFY {"nativeError":"secret"}\n',
                    b'LSF_GO_DIAG_OUTCOME private error text\n'):
            with self.subTest(metadata=raw), self.assertRaisesRegex(ValueError, 'shape'):
                execution_metadata(raw)

    def test_private_terminal_observer_changes_only_two_known_noreturn_bodies(self):
        from tools.diagnose_go_timer_failure import leb, sections, terminal_component
        def section(kind, value):
            return bytes([kind]) + leb(len(value)) + value
        def name(value):
            raw = value.encode()
            return leb(len(raw)) + raw
        original_bodies = [b'\0\x41\x2a\x0b', b'\0\x41\x2b\x0b', b'\0\x41\x2c\x0b']
        types = section(1, b'\x01\x60\x01\x7f\x01\x7f')
        imports = section(2, b'\0')
        functions = section(3, b'\x03\0\0\0')
        code = section(10, b'\x03' + b''.join(leb(len(raw)) + raw for raw in original_bodies))
        names = b'\x03' + b''.join(leb(index) + name(value) for index, value in
            enumerate(('runtime.throw', 'runtime.fatal', 'normal.effect')))
        custom = section(0, name('name') + b'\x01' + leb(len(names)) + names)
        module = b'\0asm\x01\0\0\0' + types + imports + functions + code + custom
        component = b'\0asm\x0d\0\x01\0' + section(1, module)
        private, record = terminal_component(component)
        self.assertNotEqual(private, component)
        self.assertEqual({row['function'] for row in record['mutations']}, {'runtime.throw', 'runtime.fatal'})
        self.assertFalse(record['importsAndAuthorityChanged'])
        self.assertFalse(record['qualification'])
        private_module = sections(private, private[:8])[0][1]
        rows = sections(private_module, module[:8])
        self.assertEqual([(k, v) for k, v in rows if k != 10],
                         [(k, v) for k, v in sections(module, module[:8]) if k != 10])
        self.assertTrue(dict(rows)[10].endswith(leb(len(original_bodies[-1])) + original_bodies[-1]))
        for invalid in (component[:-1], component.replace(b'runtime.throw', b'unknown.throw'),
                        component + section(1, module)):
            with self.subTest(invalid=invalid[:32]), self.assertRaises(ValueError):
                terminal_component(invalid)
        with self.assertRaisesRegex(ValueError, 'ABI-preimage'):
            terminal_component(component, reason_bit=0)

    def test_terminal_reason_probe_has_pinned_catalog_finite_bits_and_no_message_export(self):
        from tools.diagnose_go_timer_failure import closed_throw_reasons, throw_reason_body
        rows = closed_throw_reasons()
        self.assertEqual(len(rows), 208)
        self.assertEqual([row['id'] for row in rows], list(range(1, 209)))
        self.assertTrue(all(len(bytes.fromhex(row['literalHex'])) <= 256 for row in rows))
        for bit in range(8):
            body = throw_reason_body(rows, bit)
            self.assertLess(len(body), 128 * 1024)
            self.assertTrue(body.endswith(b'\0\x0b'))
        for bit in (-1, 8, True, '0'):
            with self.subTest(bit=bit), self.assertRaisesRegex(ValueError, 'bit-bound'):
                throw_reason_body(rows, bit)
        for candidate in (0, 209, True):
            with self.subTest(candidate=candidate), self.assertRaisesRegex(ValueError, 'candidate-bound'):
                throw_reason_body(rows, 0, candidate=candidate)

    def test_terminal_reason_classification_rejects_unknown_and_divergent_controls(self):
        from tools import diagnose_go_timer_failure as diagnostic
        terminal = {'publicObservation': {'nativeCaseStarted': True,
            'trapKinds': ['unreachable-code'], 'completedOrdinaryModes': [0, 1, 18, 19, 20]}}
        with tempfile.TemporaryDirectory() as temporary:
            for selected in (0, 117):
                def probe(*args, reason_bit=None, reason_id=None, output_limit):
                    self.assertGreater(output_limit, 0)
                    return {'publicObservation': {**terminal['publicObservation'], 'trapKinds': [
                        'integer-division-by-zero' if reason_id == selected or
                            (reason_bit is not None and selected >> reason_bit & 1) else 'unreachable-code']},
                        'privateComponentDigest': f'sha256:controlled-bit-{reason_bit}', 'compilerErrorCodes': []}, 16
                with patch.object(diagnostic, 'ordinary_terminal_diagnostic', side_effect=probe):
                    out = Path(temporary) / str(selected); out.mkdir()
                    record, used = diagnostic.known_throw_diagnostic(None, out, None, None, None,
                        lambda: 1, terminal, 32)
                self.assertEqual(used, 176 if selected else 160)
                self.assertFalse(record['rawGuestMessageRetained'])
                if selected:
                    self.assertEqual(record['status'], 'candidate-supported-by-fresh-confirmation')
                    self.assertEqual(record['confirmedCandidate']['id'], selected)
                    self.assertNotIn('literalHex', record['confirmedCandidate'])
                    self.assertFalse(record['baselineCauseProven'])
                    self.assertFalse(record['bitRunsSameCauseProven'])
                else:
                    self.assertEqual(record['status'], 'unknown-literal')
                    self.assertNotIn('confirmedCandidate', record)
            divergent = {'publicObservation': {**terminal['publicObservation'],
                'completedOrdinaryModes': [0], 'trapKinds': ['unreachable-code']},
                'privateComponentDigest': 'controlled', 'compilerErrorCodes': []}
            with patch.object(diagnostic, 'ordinary_terminal_diagnostic', return_value=(divergent, 16)):
                record, _ = diagnostic.known_throw_diagnostic(None, Path(temporary), None, None,
                    None, lambda: 1, terminal, 0)
            self.assertEqual(record['status'], 'inconclusive-control-divergence')
            self.assertNotIn('confirmedCandidate', record)
            def unconfirmed(*args, reason_bit=None, reason_id=None, output_limit):
                value, count = probe(*args, reason_bit=reason_bit, reason_id=reason_id,
                    output_limit=output_limit)
                if reason_id is not None:
                    value['publicObservation']['trapKinds'] = ['unreachable-code']
                return value, count
            with patch.object(diagnostic, 'ordinary_terminal_diagnostic', side_effect=unconfirmed):
                out = Path(temporary) / 'unconfirmed'; out.mkdir()
                record, _ = diagnostic.known_throw_diagnostic(None, out, None, None,
                    None, lambda: 1, terminal, 0)
            self.assertEqual(record['status'], 'candidate-not-confirmed')
            self.assertNotIn('confirmedCandidate', record)

    def test_private_frame_observer_refuses_drift_before_writing_a_partial_overlay(self):
        from tools.diagnose_go_timer_failure import PATHS, overlay_sources
        with tempfile.TemporaryDirectory() as temporary:
            root, output = Path(temporary) / 'source', Path(temporary) / 'diagnostic'
            for name in PATHS:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((runtime.ROOT / name).read_bytes())
            engine = root / PATHS[1]
            engine.write_text(engine.read_text().replace('wasm_backtrace_max_frames(None)', 'changed_config()'))
            before = {name: (root / name).read_bytes() for name in PATHS}
            with self.assertRaisesRegex(ValueError, 'source-drift'):
                overlay_sources(root, output)
            self.assertFalse(output.exists())
            self.assertEqual({name: (root / name).read_bytes() for name in PATHS}, before)

    def test_activation_dispatcher_rejects_changed_dependency_before_transformation(self):
        from tools.go_guest import activation
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'wit/async/async.go'
            source.parent.mkdir(parents=True)
            source.write_text('package async // substituted dispatcher')
            with self.assertRaisesRegex(ValueError, 'dispatcher-source-drift'):
                activation.async_source(root, runtime.ROOT / 'sdk/go-guest')
            self.assertEqual(source.read_text(), 'package async // substituted dispatcher')

    def test_activation_export_refuses_missing_and_synchronous_entry_before_writing(self):
        from tools.go_guest import activation
        for source in ('package main\nfunc main() {}\n',
                       '//go:wasmexport execute\nfunc execute() { wasm_export_task_return_run() }\n'):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path = root / 'wit_exports.go'
                path.write_text(source)
                with self.assertRaisesRegex(ValueError, 'go-activation-'):
                    activation.exports(root)
                self.assertEqual(path.read_text(), source)

    def test_activation_selection_is_explicit_and_retains_default_profile(self):
        from tools.go_guest import activation
        from tools.go_application_dependencies import selection
        self.assertEqual(selection()['runtimeProfile'], 'go-component-async-v1')
        self.assertEqual(selection({'runtimeProfile': activation.PROFILE})['runtimeProfile'], activation.PROFILE)
        self.assertEqual(selection({'runtimeProfile': activation.CHECKPOINT_PROFILE})['runtimeProfile'], activation.CHECKPOINT_PROFILE)
        with self.assertRaisesRegex(ValueError, 'profile-not-installed'):
            selection({'runtimeProfile': 'unbounded-native-threads'})

    def test_checkpoints_cover_selected_open_modules_but_preserve_dispatcher_and_standard_runtime(self):
        from tools.go_guest import checkpoints
        from tools.rust_capsule_project import digest
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generated, output = root / 'module', root / 'overlay'
            output.mkdir()
            names = ['app/main.go', 'vendor/example.org/arbitrary-worker/worker.go',
                     'vendor/go.bytecodealliance.org/pkg/wit/async/async.go', 'standard/runtime.go']
            paths = [generated / name for name in names]
            for path in paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'package fixture\nfunc Run(){}\n')
            originals = {path: path.read_bytes() for path in paths}
            packages = [{'Dir': str(path.parent), 'GoFiles': [path.name], 'Standard': index == 3}
                        for index, path in enumerate(paths)]
            def execute(label, tool, request, destination):
                selected = json.loads(request.read_bytes())
                self.assertEqual({row['path'] for row in selected}, {str(path) for path in paths[:2]})
                destination.mkdir()
                rows = []
                for index, row in enumerate(selected):
                    adapted = destination / (str(index) + '.go')
                    adapted.write_bytes(originals[Path(row['path'])] + b'// compiler checkpoint\n')
                    rows.append({'path': row['path'], 'adapted': str(adapted), 'sites': [{'line': 2, 'column': 12, 'suspendable': True}],
                                 'upstreamDigest': digest(originals[Path(row['path'])]), 'adaptedDigest': digest(adapted.read_bytes())})
                return json.dumps(rows)
            replacements, records = checkpoints.transform(SimpleNamespace(run=execute), generated, packages, {paths[0]}, output)
            self.assertEqual(set(replacements), {str(path) for path in paths[:2]})
            self.assertEqual(len(records), 2)
            for path, original in originals.items():
                self.assertEqual(path.read_bytes(), original)

    def test_checkpoint_parser_cannot_return_an_unselected_source(self):
        from tools.go_guest import checkpoints
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'module/main.go'
            source.parent.mkdir()
            source.write_text('package fixture\nfunc Run(){}\n')
            compiler = SimpleNamespace(run=lambda *arguments: json.dumps([{'path': str(root / 'foreign.go')}]))
            with self.assertRaisesRegex(ValueError, 'returned-unselected-source'):
                checkpoints.transform(compiler, source.parent,
                    [{'Dir': str(source.parent), 'GoFiles': [source.name]}], {source}, root)

    def fixture(self, root, prepared=True):
        text = sources()
        if prepared:
            runtime.install_scheduler(text)
        original = {name: value.encode() for name, value in text.items()}
        goroot = root / "go"
        for name, data in original.items():
            path = goroot / "src" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        contracts = {name: hashlib.sha256(data).hexdigest() for name, data in original.items()}
        return goroot, original, contracts

    def test_compiler_assembly_preserves_upstream_and_verifies_all_derived_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            goroot, original, upstream = self.fixture(root, prepared=False)
            (goroot / "VERSION").write_text("go1.27.2\n")
            (goroot / "bin").mkdir()
            (goroot / "bin/go").write_bytes(b"pinned-host-compiler")
            patched = sources()
            runtime.install_scheduler(patched)
            expected = {name: hashlib.sha256(text.encode()).hexdigest() for name, text in patched.items()}
            with patch.dict(runtime.UPSTREAM_PREIMAGES, upstream, clear=True), patch.dict(runtime.PREIMAGES, expected, clear=True):
                prepared = runtime.prepare_compiler(goroot, root / "derived")
                runtime.checked_sources(prepared, expected)
                with self.assertRaises(ValueError):
                    runtime.prepare_compiler(goroot, prepared)
            self.assertEqual((prepared / "bin/go").read_bytes(), b"pinned-host-compiler")
            for name, data in original.items():
                self.assertEqual((goroot / "src" / name).read_bytes(), data)

    def test_wrong_compiler_version_and_source_drift_refuse_before_assembly(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            goroot, original, upstream = self.fixture(root, prepared=False)
            (goroot / "VERSION").write_text("go1.27.1\n")
            with patch.dict(runtime.UPSTREAM_PREIMAGES, upstream, clear=True):
                output = root / "wrong-version"
                with self.assertRaisesRegex(ValueError, "version-drift"):
                    runtime.prepare_compiler(goroot, output)
                self.assertFalse(output.exists())
                (goroot / "VERSION").write_text("go1.27.2\n")
                path = goroot / "src/runtime/proc.go"
                path.write_bytes(original["runtime/proc.go"] + b"drift")
                output = root / "wrong-source"
                with self.assertRaisesRegex(ValueError, "source-drift"):
                    runtime.prepare_compiler(goroot, output)
                self.assertFalse(output.exists())

    def test_scheduler_and_lsf_overlays_preserve_sources_and_separate_wasi_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            goroot, original, contracts = self.fixture(root)
            with patch.dict(runtime.PREIMAGES, contracts, clear=True):
                upstream = runtime.scheduler_overlay(goroot, root / "upstream")
                strict = runtime.overlay(goroot, root / "strict")
            upstream_rows = json.loads(upstream.read_text())["Replace"]
            strict_rows = json.loads(strict.read_text())["Replace"]
            self.assertEqual(len(upstream_rows), 5)
            self.assertEqual(len(strict_rows), 8)
            for name in original:
                self.assertEqual((goroot / "src" / name).read_bytes(), original[name])
            os_source = str(goroot / "src/runtime/os_wasip1.go")
            self.assertNotIn(os_source, upstream_rows)
            self.assertNotIn("wasi_snapshot_preview1", Path(strict_rows[os_source]).read_text())
            for name in ("runtime/lock_wasip1.go", "runtime/proc.go"):
                key = str(goroot / "src" / name)
                self.assertEqual(Path(upstream_rows[key]).read_bytes(), Path(strict_rows[key]).read_bytes())
            hook = Path(strict_rows[str(goroot / "src/runtime/lock_wasip1.go")]).read_text()
            self.assertIn("func wasiOnIdle(callback func() bool)", hook)
            self.assertIn("!netWaiters && onIdle()", hook)
            self.assertEqual((goroot / "src/runtime/os_wasip1.go").read_bytes(), original["runtime/os_wasip1.go"])

    def test_each_upstream_source_drift_refuses_before_any_overlay_is_written(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            goroot, original, contracts = self.fixture(root)
            with patch.dict(runtime.PREIMAGES, contracts, clear=True):
                for index, name in enumerate(original):
                    with self.subTest(source=name):
                        path = goroot / "src" / name
                        path.write_bytes(original[name] + b"drift\n")
                        output = root / f"refused-{index}"
                        with self.assertRaisesRegex(ValueError, "go-runtime-source-drift"):
                            runtime.overlay(goroot, output)
                        self.assertFalse(output.exists())
                        path.write_bytes(original[name])

    def test_protected_roots_and_existing_output_refuse_without_modifying_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            goroot, original, contracts = self.fixture(root)
            existing = root / "existing"
            existing.mkdir()
            with patch.dict(runtime.PREIMAGES, contracts, clear=True):
                for output in (goroot, goroot / "overlay", root, existing):
                    with self.subTest(output=output), self.assertRaises(ValueError):
                        runtime.scheduler_overlay(goroot, output)
            for name, data in original.items():
                self.assertEqual((goroot / "src" / name).read_bytes(), data)
