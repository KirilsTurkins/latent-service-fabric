#!/usr/bin/env python3
"""Exact production Write method with explicit deterministic protocol doubles.

This finite Go reference is not an emitted component, TCP/provider installation,
physical-accounting proof or a repeat of the ordinary Go signed programme.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import file_identity
from tools.owned_test_process import ProcessFailure, run_owned
from tools.rust_capsule_project import ROOT, fresh
from tools.test_run import redact

TEMPLATE = 'sdk/go-guest/runtime/net_stream.go.in'
TESTS = 'tools/tests/fixtures/go_network/write-progress-test.go.txt'
BASELINE = '955da9c7465b88541e39b043203abb92782ae26a'
CLOSE_BASELINE = 'fb79a7ab6ea86f53baec78ee341aca075c14a2ef'
CLOSE_SHA = '1e101f7b858125ec9ed85a57ea075722bca02b2bfc5546d2e8db5404abe09cf2'
OLD_SHA = '73caccf7337e69c45e41806f8f22c0d192ee572e13cc150a6bb8f4d8a3e0b4da'
CASES = ('TestCopyCrossesChunkBoundary', 'TestDirectWriteAdvancesOnlyAcceptedBytes',
    'TestErrorKeepsCumulativePrefixAndUncertaintyWithoutRetry', 'TestZeroProgressStopsWithoutSpin',
    'TestAbsoluteDeadlineDoesNotRestartForEachFragment',
    'TestSameDirectionRefusalAndSingleOwnerSurviveAllFragments',
    'TestImpossibleCountsFailClosedBeforeAnotherDispatch',
    'TestEmptyClosedAndHalfClosedPathsKeepAdmissionRules',
    'TestCloseBetweenFragmentsKeepsPrefixAndStopsDispatch')
RECIPE = (TEMPLATE, TESTS, 'tools/qualify_go_write_progress.py',
          'tools/owned_test_process.py', 'tools/build_observation.py', 'tools/test_run.py',
          '.github/workflows/go-write-progress-reference.yml')


def method(raw: bytes) -> bytes:
    if not isinstance(raw, bytes) or len(raw) > 65536 or b'\r' in raw:
        raise ValueError('go-write-method-source-bound')
    if re.findall(rb'(?m)^const lsfStreamMaximumChunk = ([0-9]+)$', raw) != [b'16384']:
        raise ValueError('go-write-original-chunk-bound-required')
    rows = re.findall(rb'(?ms)^func \(c \*lsfStreamConn\) Write\(bytes \[\]byte\) \(int, error\) \{\n.*?^\}', raw)
    if len(rows) != 1:
        raise ValueError('go-write-method-shape')
    return rows[0]


def projected(raw: bytes) -> bytes:
    return b'package streamwrite\nimport ("context"; lsfIO "io")\n' + method(raw) + b'\n'


def observed(raw: bytes, old: bool, *, close: bool = False) -> list[str]:
    if not isinstance(raw, bytes) or len(raw) > 1024 * 1024:
        raise ValueError('go-write-reference-output-bound')
    passed, failed, packages, messages = [], [], [], []
    for line in raw.splitlines():
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError('go-write-reference-duplicate-field')
                value[key] = item
            return value
        row = json.loads(line, object_pairs_hook=unique)
        if not isinstance(row, dict) or row.get('Package') != 'example.invalid/streamwrite':
            raise ValueError('go-write-reference-package')
        action, case = row.get('Action'), row.get('Test')
        if action not in {'start', 'run', 'output', 'pass', 'fail'} or case is not None and case not in CASES:
            raise ValueError('go-write-reference-unknown-or-skipped')
        if action in {'pass', 'fail'}:
            if case is None:
                packages.append(action)
            else:
                (passed if action == 'pass' else failed).append(case)
        if action == 'output':
            messages.append(row.get('Output', ''))
    if old:
        expected = CASES[-1] if close else CASES[0]
        marker = 'close-between-fragments:' if close else 'chunk-boundary-copy: n=16384'
        if passed or failed != [expected] or packages != ['fail'] or not any(marker in v for v in messages):
            raise ValueError('go-write-original-counterexample-required')
        return failed
    if passed != list(CASES) or failed or packages != ['pass']:
        raise ValueError('go-write-all-exact-controls-required')
    return passed


def qualify(output: Path) -> dict:
    output = fresh(output)
    before = {name: (ROOT / name).read_bytes() for name in RECIPE}
    if any(len(raw) > 1024 * 1024 for raw in before.values()):
        raise ValueError('go-write-source-input-bound')
    upstream = subprocess.check_output(['git', 'show', BASELINE + ':' + TEMPLATE], cwd=ROOT, timeout=30)
    if hashlib.sha256(method(upstream)).hexdigest() != OLD_SHA:
        raise ValueError('go-write-counterexample-preimage')
    before_close = subprocess.check_output(['git', 'show', CLOSE_BASELINE + ':' + TEMPLATE], cwd=ROOT, timeout=30)
    if hashlib.sha256(method(before_close)).hexdigest() != CLOSE_SHA:
        raise ValueError('go-write-close-counterexample-preimage')
    record = {'schemaVersion': 'latent.go.write-progress.reference.v1', 'status': 'in-progress',
        'sourceRevision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=30).decode().strip(),
        'baseline': BASELINE, 'oldMethodSha256': OLD_SHA,
        'beforeCloseGuardBaseline': CLOSE_BASELINE, 'beforeCloseGuardMethodSha256': CLOSE_SHA,
        'currentMethodSha256': hashlib.sha256(method(before[TEMPLATE])).hexdigest(),
        'inputs': {name: {'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)} for name, raw in before.items()},
        'evidenceKind': 'exact-method-with-explicit-protocol-doubles',
        'signedGuestExecuted': False, 'normalProviderInstalled': False, 'kernelAccountingQualified': False}
    def save(name):
        (output / name).write_bytes((json.dumps(record, indent=2) + '\n').encode())
    try:
        compiler = shutil.which('go')
        if compiler is None:
            raise ValueError('go-write-reference-compiler-unavailable')
        compiler = Path(compiler).resolve(strict=True)
        identity = file_identity(compiler, 'go')
        version = subprocess.check_output([str(compiler), 'version'], timeout=30).decode().strip()
        if version != 'go version go1.27.2 linux/amd64':
            raise ValueError('go-write-reference-compiler-identity')
        environment = dict(os.environ, GOTOOLCHAIN='local', GOWORK='off', GOENV='off',
            GOOS='linux', GOARCH='amd64', CGO_ENABLED='0', GOPROXY='off', GOSUMDB='off',
            GOMAXPROCS='2', GOCACHE=str(output / 'cache'))
        results = {}
        for name, source in (('old', upstream), ('before-close-guard', before_close), ('current', before[TEMPLATE])):
            module = output / name; module.mkdir()
            (module / 'go.mod').write_bytes(b'module example.invalid/streamwrite\n\ngo 1.27.2\n')
            (module / 'write.go').write_bytes(projected(source))
            (module / 'write_test.go').write_bytes(before[TESTS])
            args = [str(compiler), 'test', '-json', '-timeout=10s', '-count=1']
            if name != 'current':
                args += ['-run', '^' + (CASES[-1] if name == 'before-close-guard' else CASES[0]) + '$']
            args.append('./...')
            def retain(result):
                if result is not None:
                    (output / (name + '.stdout.log')).write_bytes(result.output)
                    (output / (name + '.stderr.log')).write_bytes(redact(result.stderr.decode('utf-8', 'replace')).encode())
            try:
                result = run_owned(args, cwd=module, env=environment, timeout=120,
                    maximum=1024 * 1024, separate_stderr=True)
            except ProcessFailure as failure:
                retain(failure.result)
                raise
            retain(result)
            if result.returncode != (0 if name == 'current' else 1):
                raise ValueError('go-write-reference-unexpected-command-outcome:' + name)
            results[name] = observed(result.output, name != 'current', close=name == 'before-close-guard')
        if before != {name: (ROOT / name).read_bytes() for name in RECIPE} or file_identity(compiler, 'go') != identity:
            raise ValueError('go-write-reference-input-changed')
        record.update(status='passed', sourceUnchanged=True, compiler=identity, compilerVersion=version, outcomes=results)
        save('receipt.json'); return record
    except BaseException:
        record['status'] = 'failed'; save('FAILED.json'); raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(qualify(parser.parse_args().output.resolve())))
