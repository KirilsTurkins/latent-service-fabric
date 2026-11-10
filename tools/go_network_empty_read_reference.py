"""Exact Go Read projection with a real loopback TCP reference.

The adapter cases use explicit provider doubles. They are not a signed guest,
a real provider run, or proof of kernel resource retirement.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re

from tools.owned_test_process import ProcessFailure, run_owned
from tools.test_run import redact

TESTS = 'tools/tests/fixtures/go_network/empty-read-test.go.txt'
BASELINE = '06630acd4514f47fa28697d31bece9b3524fea1d'
OLD_TEMPLATE_SHA = 'b9bae58761ea31b2ea182a2359c283862417277a8078f2b2c317e103ff0e5498'
CASES = ('TestZeroReadExpiredNoDispatch', 'TestZeroReadEOFNoDispatch',
         'TestZeroReadClosedAndBusyKeepProfileRules',
         'TestNonemptyExpiredStillRefusesBeforeDispatch',
         'TestNonemptyReadPreservesProviderPathAndEOF',
         'TestPinnedNativeTCPZeroReadDeadlineEOFAndClose')
OPTION = b"""package wit
type Option[T any] struct { Value T; Present bool }
func None[T any]() Option[T] { return Option[T]{} }
func Some[T any](x T) Option[T] { return Option[T]{Value:x, Present:true} }
"""
PATTERNS = (
    rb'(?ms)^func \(c \*lsfStreamConn\) opError\(op string, err error\) error \{\n.*?^\}',
    rb'(?ms)^func lsfStreamTimeout\(deadline time.Time\) \(lsfWit.Option\[uint32\], error\) \{\n.*?^\}',
    rb'(?ms)^func \(c \*lsfStreamConn\) begin\(write bool\) \(lsfWit.Option\[uint32\], func\(\), error\) \{\n.*?^\}',
    rb'(?ms)^func \(c \*lsfStreamConn\) Read\(bytes \[\]byte\) \(int, error\) \{\n.*?^\}',
)


def methods(raw: bytes) -> tuple[bytes, ...]:
    if not isinstance(raw, bytes) or len(raw) > 65536 or b'\r' in raw:
        raise ValueError('go-empty-read-source-bound')
    if re.findall(rb'(?m)^const lsfStreamMaximumChunk = ([0-9]+)$', raw) != [b'16384']:
        raise ValueError('go-empty-read-original-chunk-bound')
    selected = []
    for pattern in PATTERNS:
        matches = re.findall(pattern, raw)
        if len(matches) != 1:
            raise ValueError('go-empty-read-method-shape')
        selected.append(matches[0])
    return tuple(selected)


def projected(raw: bytes) -> bytes:
    return (b'package emptyread\n'
            b'import ("context"; lsfIO "io"; lsfOS "os"; "time"; '
            b'lsfWit "example.invalid/emptyread/wit")\n'
            b'const lsfStreamMaximumChunk = 16384\n\n'
            + b'\n\n'.join(methods(raw)) + b'\n')


def observed(raw: bytes, old: bool) -> list[str]:
    if not isinstance(raw, bytes) or len(raw) > 1024 * 1024:
        raise ValueError('go-empty-read-output-bound')
    passed, failed, packages, messages = [], [], [], []
    for line in raw.splitlines():
        def unique(pairs):
            obj = {}
            for key, value in pairs:
                if key in obj:
                    raise ValueError('go-empty-read-duplicate-field')
                obj[key] = value
            return obj
        row = json.loads(line, object_pairs_hook=unique)
        if not isinstance(row, dict) or row.get('Package') != 'example.invalid/emptyread':
            raise ValueError('go-empty-read-package')
        action, case = row.get('Action'), row.get('Test')
        if action not in {'start', 'run', 'output', 'pass', 'fail'} or case is not None and case not in CASES:
            raise ValueError('go-empty-read-unknown-or-skipped')
        if action in {'pass', 'fail'}:
            if case is None:
                packages.append(action)
            else:
                (passed if action == 'pass' else failed).append(case)
        if action == 'output':
            messages.append(row.get('Output', ''))
    if old:
        if (passed or failed != [CASES[0]] or packages != ['fail']
                or not any('empty-expired: n=0 err=read: i/o timeout calls=0 busy=false' in text for text in messages)):
            raise ValueError('go-empty-read-original-counterexample-required')
        return failed
    if passed != list(CASES) or failed or packages != ['pass']:
        raise ValueError('go-empty-read-all-controls-required')
    return passed


def qualify(output: Path, compiler: Path, environment: dict, old: bytes,
            current: bytes, tests: bytes) -> dict:
    if hashlib.sha256(old).hexdigest() != OLD_TEMPLATE_SHA:
        raise ValueError('go-empty-read-counterexample-preimage')
    if not isinstance(tests, bytes) or len(tests) > 65536:
        raise ValueError('go-empty-read-fixture-bound')
    results = {}
    for name, source in (('empty-read-old', old), ('empty-read-current', current)):
        module = output / name
        module.mkdir()
        (module / 'go.mod').write_bytes(b'module example.invalid/emptyread\n\ngo 1.27.3\n')
        (module / 'production.go').write_bytes(projected(source))
        (module / 'empty_read_test.go').write_bytes(tests)
        (module / 'wit').mkdir()
        (module / 'wit/option.go').write_bytes(OPTION)
        args = [str(compiler), 'test', '-json', '-timeout=10s', '-count=1']
        if name == 'empty-read-old':
            args += ['-run', '^' + CASES[0] + '$']
        args.append('.')
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
        if result.returncode != (1 if name == 'empty-read-old' else 0):
            raise ValueError('go-empty-read-unexpected-command-outcome:' + name)
        results[name] = observed(result.output, name == 'empty-read-old')
    return {'schemaVersion': 'latent.go.empty-read.reference.v1', 'status': 'passed',
            'oldTemplateSha256': OLD_TEMPLATE_SHA,
            'currentTemplateSha256': hashlib.sha256(current).hexdigest(),
            'fixtureSha256': hashlib.sha256(tests).hexdigest(), 'outcomes': results,
            'evidenceKind': 'exact-method-with-provider-doubles-and-native-loopback',
            'signedGuestExecuted': False, 'liveProviderExecuted': False,
            'kernelAccountingQualified': False}
