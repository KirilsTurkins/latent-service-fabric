"""Actual observer/parser controls; no LLVM, Java or guest execution."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.build_process import BuildProcessError, MAX_OUTPUT_BYTES, run_bounded_result
from tools.java_guest import public_wineh as observer, wineh_ir, wineh_filter
from tools.java_guest.compiler import Compiler
from tools.java_guest.fiber_component_inputs import retain as retain_inputs
from tools.rust_capsule_project import ROOT, canonical


def printed(before, after):
    return (f'*** IR Dump Before {wineh_ir.PASS} ***\n'
        f'define ptr @{wineh_ir.FUNCTION}() {{\n{before}\n}}\n'
        f'*** IR Dump After {wineh_ir.PASS} ***\n'
        f'define ptr @{wineh_ir.FUNCTION}() {{\n{after}\n}}\n').encode()


IR = printed('entry:\n  %x = phi i32 [ 1, %a ], [ 2, %b ]\n  ret ptr null',
    'entry:\n  %slot = alloca i32\n  store volatile i32 1, ptr %slot\n'
    '  %x = load volatile i32, ptr %slot\n  ret ptr null')


class JavaPublicWinEH(unittest.TestCase):
    def populate(self, root):
        for name, source in (
                ('src/Capsule.java', 'sdk/java-guest/fibers/conformance/Capsule.java'),
                ('build/project/src/main/java/Capsule.java', 'sdk/java-guest/fibers/conformance/Capsule.java'),
                ('wit/service.wit', 'sdk/java-guest/fibers/conformance/service.wit'),
                ('build/wit/service.wit', 'sdk/java-guest/fibers/conformance/service.wit')):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / source).read_bytes())
        # These three literal escaped basenames are present in the retained
        # actual38f Capsule.c includes; ordinary synthetic names missed them.
        for name in ('all.c', 'c/d/l/a/Capsule.c', 'c/d/l/a/Capsule.h',
                'c/j/u/WeakHashMap@dEntry.h', 'c/d/l/a/Capsule@drun@dlambda@d_1_0.h',
                'c/j/l/Object@dMonitor.h'):
            target = root / 'build/project/build/teavm-c/c' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'/* bounded source fixture, never compiled */\n')
        (root / 'build/bindings').mkdir()
        (root / 'build/bindings/bridge.h').write_bytes(b'/* original header */')
        for name in ('core.wasm', 'closed-runtime.wasm'):
            (root / 'build' / name).write_bytes(b'\0asm\x01\0\0\0original')
        compiler = object.__new__(observer.PublicWinEHCompiler)
        compiler.directory = root / 'compiler'
        compiler.directory.mkdir()
        compiler.sdk = ROOT / 'sdk/java-guest'
        compiler.paths = {'clang': root / 'wasi/bin/clang'}
        compiler.environment = {'PATH': 'fixed-test-context'}
        compiler.compiler_inputs = b'original inventory'
        compiler.original_sdk = {'runtime/native.h': b'original sdk input'}
        compiler.tool_roots = {name: root / ('test-' + name) for name in ('wasi-sdk', 'jdk', 'gradle')}
        compiler.check_unchanged = lambda: None
        compiler.records = []
        return compiler

    def admit(self, compiler):
        command = observer.expected_command(compiler, compiler.directory.parent)
        source = {'repository': 'KirilsTurkins/latent-service-fabric', 'revision': 'a' * 40}
        with patch.object(observer, 'hosted_source', return_value=source), \
                patch.object(Compiler, 'run', return_value='original result') as original:
            self.assertEqual(compiler.run('c-to-wasm', 'clang', *command[1:]), 'original result')
        original.assert_called_once_with('c-to-wasm', 'clang', *command[1:], cwd=None)
        row = {'stage': 'c-to-wasm', 'exitCode': 0, 'seconds': 1.25, 'command': command}
        failed = {'stage': 'component-new', 'exitCode': 1, 'command': ['wasm-tools',
            'component', 'new', str(compiler.directory.parent / 'build/core.wasm'), '--adapt',
            'wasi_snapshot_preview1=' + str(compiler.directory.parent / 'build/closed-runtime.wasm'),
            '-o', str(compiler.directory.parent / 'build/component.wasm')]}
        compiler.records = [row, {'stage': 'closed-runtime', 'exitCode': 0}, failed]
        (compiler.directory / '0-c-to-wasm.command.json').write_bytes(canonical(row))
        (compiler.directory / '2-component-new.command.json').write_bytes(canonical(failed))
        retain_inputs(compiler, compiler.directory.parent)
        return source

    def filter_response(self, root, source, *, incomplete=False):
        raw = (root / 'build/wineh-observer/request.json').read_bytes()
        ticket = json.loads(raw)
        value = {'schemaVersion': observer.FILTER_SCHEMA, 'status': 'incomplete' if incomplete else 'observed',
            'qualification': False, 'ticketDigest': observer.digest(raw).removeprefix('sha256:'),
            'sourceCommit': source['revision'], 'diagnosticCommandDigest': observer.digest(canonical(ticket['diagnosticCommand'])),
            'childStarted': True, 'childExitCode': 0, 'stdoutBytes': 0, 'stdoutDigest': observer.digest(b''),
            'stderrBytes': len(IR), 'stderrDigest': observer.digest(IR),
            'rawTransitMaximum': observer.RAW_TRANSIT_BUDGET, 'pipeEOFComplete': True,
            'observation': wineh_ir.observe(IR)}
        if incomplete:
            value.update(reason='print-incomplete', refusalStage='collect')
        return subprocess.CompletedProcess([], 1 if incomplete else 0, canonical(value), b'')

    def test_synthetic_pinned_print_text_is_counted_and_unknown_formats_refuse(self):
        good = wineh_ir.observe(IR)
        self.assertEqual(good['status'], 'observed')
        self.assertEqual(good['snapshots']['before']['phiIncoming'], 2)
        self.assertEqual(good['snapshots']['before']['blocks'], 1)
        self.assertEqual(good['delta']['phi'], -1)
        self.assertEqual(good['delta']['alloca'], 1)
        self.assertEqual(good['delta']['store'], 1)
        self.assertEqual(good['snapshots']['after']['volatileStore'], 1)
        self.assertEqual(good['snapshots']['after']['volatileLoad'], 1)
        self.assertLessEqual(len(canonical(good['samples'])), 16 * 1024)
        for step in (1, 7, 16 * 1024):
            counter = wineh_ir.Counter()
            for offset in range(0, len(IR), step):
                self.assertTrue(counter.feed(IR[offset:offset + step]))
            self.assertEqual(counter.finish(), good)
        unicode_prefix = '; split UTF8: é\n'.encode() + IR
        counter = wineh_ir.Counter()
        for byte in unicode_prefix:
            self.assertTrue(counter.feed(bytes([byte])))
        self.assertEqual(counter.finish()['streamDigest'], observer.digest(unicode_prefix))
        overlong = b';' + ('é' * (wineh_ir.MAX_LINE // 2)).encode() + b'\n' + IR
        self.assertEqual(wineh_ir.observe(overlong)['reason'], 'line-limit')
        for invalid in (b'', IR + IR, IR[:-2], IR.replace(b'pools()', b'private()'),
                IR.replace(b'win-eh-prepare', b'other-pass'), IR.replace(b'alloca', b'unknown'),
                IR + b'\xff', IR.replace(b'  ret ptr null', b'x' * (256 * 1024 + 1), 1)):
            with self.subTest(digest=observer.digest(invalid)):
                self.assertEqual(wineh_ir.observe(invalid)['status'], 'incomplete')

    def test_real_hosted_context_guards_and_named_source_identities(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            compiler = self.populate(root)
            for name in observer.MAINTAINED:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / name).read_bytes())
            environment = {'GITHUB_REPOSITORY': 'KirilsTurkins/latent-service-fabric',
                'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_WORKSPACE': str(root),
                'GITHUB_SHA': 'a' * 40, 'GITHUB_WORKFLOW_REF':
                'KirilsTurkins/latent-service-fabric/.github/workflows/java-guest-feasibility.yml@refs/heads/test'}
            git_result = subprocess.CompletedProcess([], 0, b'a' * 40 + b'\n', b'')
            with patch.object(observer, 'ROOT', root), \
                    patch.object(observer.shutil, 'which', return_value='fixed-git'), \
                    patch.object(observer, 'run_bounded_result', return_value=git_result) as execute:
                with patch.dict(os.environ, environment, clear=True):
                    actual = observer.hosted_source(compiler)
                self.assertEqual(actual['revision'], 'a' * 40)
                self.assertEqual(set(actual['maintainedFiles']), set(observer.MAINTAINED))
                execute.assert_called_once_with(
                    ['fixed-git', '--no-lazy-fetch', 'rev-parse', '--verify', 'HEAD'], root,
                    compiler.environment, timeout_seconds=5, max_output_bytes=4096)
                for key, invalid in (
                        ('GITHUB_REPOSITORY', 'other/repo'), ('GITHUB_EVENT_NAME', 'push'),
                        ('GITHUB_WORKSPACE', str(root / 'other')), ('GITHUB_SHA', 'not-a-revision'),
                        ('GITHUB_WORKFLOW_REF', environment['GITHUB_WORKFLOW_REF'].replace('java-guest', 'other'))):
                    execute.reset_mock()
                    with self.subTest(field=key), patch.dict(os.environ, {**environment, key: invalid}, clear=True):
                        with self.assertRaises(ValueError):
                            observer.hosted_source(compiler)
                    execute.assert_not_called()
                with patch.dict(os.environ, environment, clear=True):
                    execute.return_value = subprocess.CompletedProcess([], 0, b'b' * 40 + b'\n', b'')
                    with self.assertRaises(ValueError):
                        observer.hosted_source(compiler)
                    execute.return_value = git_result
                    (root / observer.MAINTAINED[0]).write_bytes(b'changed maintained observer')
                    changed = observer.hosted_source(compiler)
                self.assertNotEqual(changed['maintainedFiles'], actual['maintainedFiles'])

    def test_real_admission_replay_uses_original_argv_and_separate_output_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            compiler = self.populate(root)
            source = self.admit(compiler)
            generated = compiler.public_wineh['inputs']['trees']['generated']
            self.assertTrue({'c/j/u/WeakHashMap@dEntry.h',
                'c/d/l/a/Capsule@drun@dlambda@d_1_0.h', 'c/j/l/Object@dMonitor.h'} <= set(generated))
            with self.assertRaisesRegex(ValueError, 'nonportable project path'):
                observer.snapshot(root / 'build/project/build/teavm-c/c')
            with self.assertRaisesRegex(ValueError, 'absolute-owned-path-required'):
                observer.generated_inventory(root / 'build/project/build/teavm-c/c/..')
            originals = canonical(compiler.records)
            receipt = (compiler.directory / '0-c-to-wasm.command.json').read_bytes()
            with patch.object(observer, 'hosted_source', return_value=source), \
                    patch.object(observer, 'run_bounded_result', side_effect=lambda *a, **k:
                        self.filter_response(root, source)) as execute:
                observer.retain(compiler, root)
            argv, cwd, environment = execute.call_args.args
            ticket_raw = (root / 'build/wineh-observer/request.json').read_bytes()
            ticket = json.loads(ticket_raw)
            self.assertEqual(argv, [str(Path(sys.executable).resolve()), '-I', '-B',
                str(ROOT / 'tools/java_guest/wineh_filter.py'), str(root), observer.digest(ticket_raw).removeprefix('sha256:')])
            self.assertEqual(ticket['diagnosticCommand'][:-7], compiler.records[0]['command'][:-1])
            self.assertEqual(ticket['diagnosticCommand'][-6:], list(observer.PRINT_FLAGS))
            self.assertEqual(ticket['diagnosticCommand'][-7], str(root / 'build/wineh-observer/core.wasm'))
            self.assertEqual((cwd, environment), (compiler.directory, compiler.environment))
            self.assertEqual(execute.call_args.kwargs,
                {'timeout_seconds': 600, 'max_output_bytes': MAX_OUTPUT_BYTES})
            result = json.loads((root / 'build/component-inputs/public-wineh.json').read_bytes())
            self.assertEqual(result['status'], 'observed')
            self.assertFalse(result['qualification'])
            self.assertFalse(result['rawIRRetained'])
            self.assertEqual(canonical(compiler.records), originals)
            self.assertEqual((compiler.directory / '0-c-to-wasm.command.json').read_bytes(), receipt)
            self.assertEqual((root / 'build/core.wasm').read_bytes(), b'\0asm\x01\0\0\0original')
            self.assertEqual(set(p.name for p in (root / 'build/component-inputs').iterdir()),
                {'record.json', 'core.wasm', 'closed-runtime.wasm', 'Capsule.c',
                 'generated-c.json', 'public-wineh.json'})

    def test_changed_real_materials_or_command_receipt_refuse_before_execution(self):
        for kind in ('generated', 'header', 'binding', 'environment', 'tool', 'receipt', 'java', 'wit',
                     'core', 'unsafe-name', 'directory-link', 'generated-target', 'binding-target',
                     'after-incomplete'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                compiler = self.populate(root)
                source = self.admit(compiler)
                selected = {'generated': 'build/project/build/teavm-c/c/all.c',
                    'header': 'build/project/build/teavm-c/c/c/d/l/a/Capsule.h',
                    'binding': 'build/bindings/bridge.h', 'java': 'src/Capsule.java',
                    'wit': 'wit/service.wit', 'receipt': 'compiler/0-c-to-wasm.command.json',
                    'core': 'build/core.wasm'}
                if kind in selected:
                    (root / selected[kind]).write_bytes(b'changed-after-original-clang')
                elif kind == 'environment':
                    compiler.environment['PATH'] = 'changed'
                elif kind == 'tool':
                    def changed():
                        raise ValueError('original compiler closure changed')
                    compiler.check_unchanged = changed
                elif kind == 'unsafe-name':
                    (root / 'build/project/build/teavm-c/c/unadmitted!header.h').write_bytes(b'unknown name')
                elif kind == 'directory-link':
                    original = root / 'outside-generated'
                    original.mkdir()
                    (original / 'secret.h').write_bytes(b'must never follow this link')
                    link = root / 'build/project/build/teavm-c/c/linked'
                    if os.name == 'nt':
                        # An actual junction/reparse traversal on Windows does
                        # not require the unavailable symlink privilege.
                        import _winapi
                        _winapi.CreateJunction(str(original), str(link))
                    else:
                        link.symlink_to(original, target_is_directory=True)
                elif kind in {'generated-target', 'binding-target'}:
                    parent = (root / 'build/project/build/teavm-c/c' if kind == 'generated-target'
                              else root / 'build/bindings')
                    header = parent / 'target/changed.h'
                    header.parent.mkdir()
                    header.write_bytes(b'must be identified or refused, never ignored')
                def incomplete_with_change(*args, **kwargs):
                    (root / 'build/project/build/teavm-c/c/all.c').write_bytes(b'changed during completed filter')
                    return self.filter_response(root, source, incomplete=True)
                with patch.object(observer, 'hosted_source', return_value=source), \
                        patch.object(observer, 'run_bounded_result',
                            side_effect=incomplete_with_change if kind == 'after-incomplete' else None) as execute:
                    observer.retain(compiler, root)
                if kind == 'after-incomplete':
                    execute.assert_called_once()
                else:
                    execute.assert_not_called()
                result = json.loads((root / 'build/component-inputs/public-wineh.json').read_bytes())
                self.assertEqual(result['status'], 'incomplete')
                self.assertIn(result['refusalStage'], ('command-receipt', 'original-capture',
                    'pre-replay-identity', 'post-replay-identity'))
                if kind == 'unsafe-name':
                    self.assertEqual(result['reason'], 'generated-path')
                elif kind == 'generated-target':
                    self.assertEqual(result['reason'], 'original-inputs-changed')
                elif kind == 'binding-target':
                    self.assertEqual(result['reason'], 'bindings-root-exclusion')
                elif kind == 'after-incomplete':
                    self.assertEqual(result['reason'], 'diagnostic-inputs-changed')
                    self.assertNotIn('postReplayIdentitiesVerified', result)

    def test_sealed_ticket_checks_actual_files_and_rejects_retargeting(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            compiler = self.populate(root)
            compiler.tool_roots = {'wasi-sdk': root / 'wasi-sdk-29.0-x86_64-linux',
                                   'jdk': root / 'jdk', 'gradle': root / 'gradle'}
            for folder in compiler.tool_roots.values():
                folder.mkdir()
                (folder / 'input').write_bytes(b'actual bounded control bytes; never executed')
            wasi = compiler.tool_roots['wasi-sdk']
            (wasi / 'bin').mkdir()
            (wasi / 'bin/clang-21').write_bytes(b'not executable; admission control only')
            (wasi / 'VERSION').write_text('29.0\nwasi-libc: ac020b86fd44\nllvm: 222fc11f2b8f\n'
                'llvm-version: 21.1.4\nconfig: f992bcc08219\n', encoding='utf-8')
            compiler.paths['clang'] = wasi / 'bin/clang-21'
            compiler.compiler_inputs = observer.tool_inventory(compiler.tool_roots)
            compiler.original_sdk = observer.sdk_snapshot(ROOT / 'sdk/java-guest')
            self.admit(compiler)
            source = {'repository': 'KirilsTurkins/latent-service-fabric', 'revision': 'a' * 40,
                'event': 'workflow_dispatch', 'workflowRef':
                'KirilsTurkins/latent-service-fabric/.github/workflows/java-guest-feasibility.yml@refs/heads/test',
                'maintainedFiles': {name: dict(zip(('sha256', 'bytes'),
                    observer.paths.digest_file(ROOT, name, 4 * 1024 * 1024))) for name in observer.MAINTAINED}}
            compiler.public_wineh['source'] = source
            diagnostic = root / 'build/wineh-observer'
            diagnostic.mkdir()
            pair = json.loads((root / 'build/component-inputs/record.json').read_bytes())['inputs']
            command = [*compiler.records[0]['command'][:-1], str(diagnostic / 'core.wasm'), *observer.PRINT_FLAGS]
            sealed = observer.write_ticket(compiler, root, compiler.public_wineh,
                compiler.records[0], 0, pair, command)
            request = diagnostic / 'request.json'
            original = request.read_bytes()
            admitted = observer.load_ticket(root, sealed, compiler.environment)
            self.assertEqual(admitted['diagnosticCommand'], command)
            for kind in ('digest', 'extra-argv', 'source', 'successful-assembly', 'tool', 'environment'):
                with self.subTest(kind=kind):
                    request.write_bytes(original)
                    value = json.loads(original)
                    expected = sealed
                    environment = dict(compiler.environment)
                    tool = wasi / 'bin/clang-21'
                    tool.write_bytes(b'not executable; admission control only')
                    if kind == 'digest':
                        request.write_bytes(original + b' ')
                    elif kind == 'extra-argv':
                        value['diagnosticCommand'].append('--unreviewed-command')
                    elif kind == 'source':
                        value['source']['maintainedFiles'][observer.MAINTAINED[0]]['sha256'] = 'sha256:' + '0' * 64
                    elif kind == 'successful-assembly':
                        value['failureCommand']['exitCode'] = 0
                    elif kind == 'tool':
                        tool.write_bytes(b'changed tool bytes')
                    elif kind == 'environment':
                        environment['EXTRA_UNREVIEWED'] = 'value'
                    if kind in {'extra-argv', 'source', 'successful-assembly'}:
                        raw = canonical(value)
                        request.write_bytes(raw)
                        expected = observer.digest(raw).removeprefix('sha256:')
                    with patch.object(wineh_filter.subprocess, 'Popen') as spawn:
                        with self.assertRaises(ValueError):
                            observer.load_ticket(root, expected, environment)
                    spawn.assert_not_called()

    def test_actual_owned_pipe_collector_and_abort_cleanup(self):
        for mode, reason in (('success', None), ('nonzero', 'child-exit'),
                ('raw-limit', 'raw-transit-limit'), ('line-limit', 'print-incomplete'),
                ('deadline', 'filter-deadline'), ('held-pipe', 'pipe-eof')):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                (root / 'control.txt').write_bytes(IR)
                result = run_bounded_result([sys.executable, '-B',
                    str(ROOT / 'tools/tests/fixtures/java_wineh_filter_control.py'), str(root), mode],
                    ROOT, dict(os.environ), timeout_seconds=5, max_output_bytes=64 * 1024)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertEqual(result.stderr, b'')
                q = json.loads(result.stdout)
                if os.name != 'nt':
                    self.assertEqual(q['leaderGroup'], q['ownerLeaderPid'])
                    self.assertEqual(q['childGroup'], q['ownerLeaderPid'])
                if reason is None:
                    self.assertEqual(q['status'], 'observed')
                    self.assertTrue(q['pipeEOFComplete'])
                    self.assertEqual(q['observation'], wineh_ir.observe(IR))
                else:
                    self.assertEqual((q['status'], q['reason']), ('incomplete', reason))
                if mode == 'raw-limit':
                    self.assertLessEqual(q['stdoutBytes'] + q['stderrBytes'], 128)
                if mode in {'deadline', 'held-pipe'}:
                    # Deliberate delayed side effects cannot happen after the
                    # original owner returned its positive cleanup result.
                    time.sleep(1.1)
                    self.assertFalse((root / 'late-side-effect').exists())

    def test_admission_and_bounded_capture_failures_preserve_original_exception(self):
        with tempfile.TemporaryDirectory() as temporary:
            compiler = self.populate(Path(temporary).resolve())
            original = RuntimeError('original compiler exception')
            command = observer.expected_command(compiler, compiler.directory.parent)
            with patch.object(observer, 'hosted_source', side_effect=ValueError('not hosted')), \
                    patch.object(Compiler, 'run', side_effect=original) as original_run:
                with self.assertRaises(RuntimeError) as caught:
                    compiler.run('c-to-wasm', 'clang', *command[1:])
            self.assertIs(caught.exception, original)
            original_run.assert_called_once_with('c-to-wasm', 'clang', *command[1:], cwd=None)
            self.assertIsNone(compiler.public_wineh)
            self.assertEqual(compiler.public_wineh_refusal,
                {'refusalStage': 'admission-host', 'reason': 'unavailable-or-unsafe'})
        for reason in ('command-output-limit', 'command-deadline', 'process-cleanup'):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                compiler = self.populate(root)
                source = self.admit(compiler)
                original = RuntimeError('original assembly failure')
                with patch.object(observer, 'hosted_source', return_value=source), \
                        patch.object(observer, 'run_bounded_result', side_effect=BuildProcessError(reason)):
                    with self.assertRaises(RuntimeError) as caught:
                        try:
                            raise original
                        finally:
                            observer.retain(compiler, root)
                self.assertIs(caught.exception, original)
                result = json.loads((root / 'build/component-inputs/public-wineh.json').read_bytes())
                self.assertEqual((result['status'], result['reason']), ('incomplete', reason))
                self.assertEqual(result['refusalStage'], 'replay')


if __name__ == '__main__':
    unittest.main()
