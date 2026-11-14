"""Bounded host reference for compiler-selected goto checkpoints; not guest evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
from types import SimpleNamespace

from tools.go_guest import checkpoints

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'tools/tests/fixtures/go-checkpoint-goto'
TRANSFORMER = ROOT / 'sdk/go-guest/runtime/checkpoint_transform.go.in'
GO_SHA256 = 'de0ae3e082ce7599eae4fb69fa2ef1e43b8f31ffd3fce62cdf81930aa9005050'
TAIL = re.compile(rb'//go:linkname ([A-Za-z0-9_]+) runtime\.lsfCheckpoint\nfunc \1\(\)\n'
                  rb'//go:linkname ([A-Za-z0-9_]+) runtime\.lsfUnsupportedCheckpoint\n'
                  rb'//go:nosplit\nfunc \2\(\)\n')
GOTO = re.compile(rb'\n__lsf_checkpoint_[0-9a-f]{16}\(\);\n//line [^\n]*\n(?=goto (?:again|back)\b)')


def run_bounded(command, env, cwd, seconds, expect_timeout=False, expect_failure=False):
    process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = process.communicate()
        if not expect_timeout:
            raise ValueError('go-checkpoint-reference-command-timeout: ' + str(command[0]))
        return None, stdout, stderr
    if expect_timeout or (process.returncode == 0) == expect_failure:
        raise ValueError('go-checkpoint-reference-command-failed: ' + str(command[0]) + ': '
                         + (stdout + stderr)[-4096:].decode(errors='replace'))
    return process.returncode, stdout, stderr


def reference(go):
    go = Path(go).resolve(strict=True)
    if hashlib.sha256(go.read_bytes()).hexdigest() != GO_SHA256:
        raise ValueError('go-checkpoint-reference-compiler-drift')
    app = (FIXTURE / 'application.go.txt').read_bytes()
    dependency = (FIXTURE / 'dependency.go.txt').read_bytes()
    directives = (FIXTURE / 'directives.go.txt').read_bytes()
    intervening = (FIXTURE / 'intervening.go.txt').read_bytes()
    receiver = (FIXTURE / 'receiver.go.txt').read_bytes()
    if max(len(app), len(dependency), len(directives), len(intervening), len(receiver)) > 4096:
        raise ValueError('go-checkpoint-reference-fixture-size')
    env = dict(os.environ, GO111MODULE='off', GOENV='off', GOWORK='off', GOTOOLCHAIN='local',
               GOFLAGS='', GOOS='linux', GOARCH='amd64', CGO_ENABLED='0', GOPROXY='off',
               GOSUMDB='off', GOMAXPROCS='1', GODEBUG='asyncpreemptoff=1')
    env.pop('GOROOT', None)
    with tempfile.TemporaryDirectory(prefix='go-checkpoint-goto-') as temporary:
        root = Path(temporary)
        _, version, _ = run_bounded([str(go), 'version'], env, root, 30)
        if version.strip() != b'go version go1.27.4 linux/amd64':
            raise ValueError('go-checkpoint-reference-version')
        pragma_source = root / 'directives.go'
        pragma_source.write_bytes(directives)
        _, assembly, _ = run_bounded([str(go), 'tool', 'compile', '-S', '-o', os.devnull,
                                      str(pragma_source)], env, root, 30)
        for name, nosplit in (('Plain', False), ('Contiguous', True), ('Blank', True),
                              ('Suffix', True), ('AfterFunc', True), ('After', False),
                              ('TabSuffix', False), ('SpaceTab', True), ('Multiple', True),
                              ('T.BeforeReceiver', True), ('T.Ignored', False)):
            match = re.search(rb'(?m)^<unlinkable>\.' + re.escape(name.encode()) + rb' STEXT([^\n]*)$', assembly)
            if not match or (b'nosplit' in match[1].split()) != nosplit:
                raise ValueError('go-checkpoint-reference-compiler-pragma:' + name)
        pragma_error = root / 'intervening.go'
        pragma_error.write_bytes(intervening)
        _, stdout, stderr = run_bounded([str(go), 'tool', 'compile', '-o', os.devnull,
                                        str(pragma_error)], env, root, 30, expect_failure=True)
        if b'misplaced compiler directive' not in stdout + stderr:
            raise ValueError('go-checkpoint-reference-intervening-declaration')
        receiver_source = root / 'receiver.go'
        receiver_source.write_bytes(receiver)
        _, stdout, stderr = run_bounded([str(go), 'tool', 'compile', '-o', os.devnull,
                                        str(receiver_source)], env, root, 30, expect_failure=True)
        if b'syntax error' not in stdout + stderr or b'misplaced compiler directive' not in stdout + stderr:
            raise ValueError('go-checkpoint-reference-receiver-directive')
        source = root / 'transformer.go'
        source.write_bytes(TRANSFORMER.read_bytes())
        binary = root / 'transformer'
        run_bounded([str(go), 'build', '-p=1', '-o', str(binary), str(source)], env, root, 120)
        pragma_request = root / 'pragma-input.json'
        pragma_request.write_text(json.dumps([{'path': str(pragma_source), 'diagnostic': str(pragma_source)}]))
        _, pragma_result, _ = run_bounded([str(binary), str(pragma_request), str(root / 'pragma-output')], env, root, 30)
        rows = json.loads(pragma_result)
        if (len(rows) != 1 or rows[0]['path'] != str(pragma_source)
                or [site['suspendable'] for site in rows[0]['sites']] !=
                   [True, False, False, False, False, True, True, False, False, False, True]):
            raise ValueError('go-checkpoint-reference-transformer-pragma')
        pragma_request.write_text(json.dumps([{'path': str(receiver_source), 'diagnostic': str(receiver_source)}]))
        run_bounded([str(binary), str(pragma_request), str(root / 'receiver-output')], env, root, 30, expect_failure=True)
        module = root / 'module'
        vendor = module / 'vendor/example.invalid/worker'
        dispatcher = module / 'vendor/go.bytecodealliance.org/pkg/wit/async'
        standard = module / 'standard'
        for directory in (vendor, dispatcher, standard):
            directory.mkdir(parents=True)
        application = module / 'main.go'
        worker = vendor / 'worker.go'
        application.write_bytes(app)
        worker.write_bytes(dependency)
        (dispatcher / 'async.go').write_text('package async\nfunc Dummy(){}\n')
        (standard / 'runtime.go').write_text('package runtime\nfunc Dummy(){}\n')
        (module / 'go.mod').write_text('module example.invalid/app\n\ngo 1.27.4\n\nrequire example.invalid/worker v0.0.0\n')
        (module / 'vendor/modules.txt').write_text('# example.invalid/worker v0.0.0\n## explicit; go 1.27.4\nexample.invalid/worker\n')
        packages = [{'Dir': str(module), 'GoFiles': ['main.go']},
                    {'Dir': str(vendor), 'GoFiles': ['worker.go']},
                    {'Dir': str(dispatcher), 'GoFiles': ['async.go']},
                    {'Dir': str(standard), 'GoFiles': ['runtime.go'], 'Standard': True}]
        output = root / 'selection'
        output.mkdir()

        def compile_selected(label, name, request, destination):
            if (label, name) != ('checkpoint-parser', 'go-checkpoints'):
                raise ValueError('go-checkpoint-reference-unexpected-command')
            return run_bounded([str(binary), str(request), str(destination)], env, root, 30)[1].decode()

        replacements, records = checkpoints.transform(SimpleNamespace(run=compile_selected),
                                                        module, packages, {application}, output)
        if set(replacements) != {str(application), str(worker)} or len(records) != 2:
            raise ValueError('go-checkpoint-reference-selection')
        projected = {}
        for original, expected in ((application, 4), (worker, 1)):
            adapted = Path(replacements[str(original)]).read_bytes()
            tail = list(TAIL.finditer(adapted))
            if len(tail) != 1 or len(GOTO.findall(adapted)) != expected:
                raise ValueError('go-checkpoint-reference-projection-shape')
            match = tail[0]
            stub = (b'var lsfControlCount uint32\nfunc ' + match[1]
                    + b'(){ lsfControlCount++; if lsfControlCount >= 1024 {'
                      b' lsfControlCount=0; runtime.Gosched() } }\nfunc ' + match[2]
                    + b'(){ panic("non-suspendable") }\n')
            host = adapted[:match.start()] + stub + adapted[match.end():]
            without_backedges, count = GOTO.subn(b'', host)
            if count != expected:
                raise ValueError('go-checkpoint-reference-backedge-count')
            projected[str(original)] = (without_backedges, host)
        env.update(GO111MODULE='on')
        outcomes = {}
        for index, label in enumerate(('without-backedges', 'current')):
            replacements = {}
            for number, (original, variants) in enumerate(projected.items()):
                projected_file = root / (label + '-' + str(number) + '.go')
                projected_file.write_bytes(variants[index])
                replacements[original] = str(projected_file)
            overlay = root / (label + '-overlay.json')
            overlay.write_text(json.dumps({'Replace': replacements}))
            program = root / (label + '-program')
            run_bounded([str(go), 'build', '-p=1', '-mod=vendor', '-overlay', str(overlay),
                         '-o', str(program), '.'], env, module, 120)
            outcomes[label] = {}
            for mode in ('app', 'dependency', 'semantics'):
                timeout = label == 'without-backedges' and mode != 'semantics'
                code, stdout, stderr = run_bounded([str(program), mode], env, module, 2, timeout)
                expected = (b'semantic-preserved\n' if mode == 'semantics' else
                            b'worker-entered\n' if timeout else b'worker-entered\nsibling-progress\n')
                if stdout != expected or stderr:
                    raise ValueError('go-checkpoint-reference-unexpected-outcome:' + label + ':' + mode)
                outcomes[label][mode] = ('semantic-preserved' if mode == 'semantics' else
                                         'bounded-starvation' if code is None else 'progress')
        return {'scope': 'fixed-source-native-projection', 'signedGuestExecuted': False,
                'goSha256': GO_SHA256, 'transformerSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                'applicationSha256': hashlib.sha256(app).hexdigest(),
                'dependencySha256': hashlib.sha256(dependency).hexdigest(),
                'directiveSha256': hashlib.sha256(directives).hexdigest(),
                'interveningSha256': hashlib.sha256(intervening).hexdigest(),
                'receiverSha256': hashlib.sha256(receiver).hexdigest(),
                'compilerPragmaAttachment': 'passed', 'outcomes': outcomes}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--go', required=True)
    args = parser.parse_args()
    print(json.dumps(reference(args.go), sort_keys=True))
