"""Exact Go half-close/owner projections and a pinned native TCP reference.

The provider and canonical-call boundaries are explicit doubles. This is not a
signed guest, a real provider run, or proof of physical socket retirement.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from tools.owned_test_process import ProcessFailure, run_owned
from tools.test_run import redact

BASELINE = '3d5a9ce80509ca0a5d185156ce88ef988b939653'
OLD_TEMPLATE_SHA = '25e8713902930a8b258645671b71a374668fc2e8d62d99e698b94a20cd279c80'
TESTS = 'tools/tests/fixtures/go_network/half-close-test.go.txt'
SDK = 'sdk/go-guest/capabilities/network.go.in'
OWNER = 'sdk/go-guest/capabilities/network-owner.go.in'
CASES = ('TestExpiredDeadlineStillHalfCloses', 'TestFutureDeadlineDoesNotCancelShutdown',
         'TestHalfClosePreservesClosedAndOverlapRules',
         'TestHalfCloseFailureIsNotReplayed',
         'TestProviderStopIsNotRelabeledOrRetried',
         'TestHalfCloseKeepsWriteOwnerAndReadIndependent',
         'TestCloseCancelsAndWaitsForOriginalBorrow',
         'TestPinnedNativeTCPHalfCloseIgnoresWriteDeadline')

PATTERNS = (
    rb'(?ms)^func \(c \*lsfStreamConn\) opError\(op string, err error\) error \{\n.*?^\}',
    rb'(?ms)^func lsfStreamTimeout\(deadline time.Time\) \(lsfWit.Option\[uint32\], error\) \{\n.*?^\}',
    rb'(?ms)^func \(c \*lsfStreamConn\) begin\(write bool\) \(lsfWit.Option\[uint32\], func\(\), error\) \{\n.*?^\}',
    rb'(?ms)^func \(c \*lsfStreamConn\) CloseWrite\(\) error \{\n.*?^\}',
    rb'(?ms)^func \(c \*lsfStreamConn\) Close\(\) error \{\n.*?^\}',
    rb'(?ms)^func \(c \*lsfStreamConn\) setDeadline\(t time.Time, read, write bool\) error \{\n.*?^\}',
)
SDK_PATTERNS = (
    rb'(?ms)^func \(c \*Connection\) ShutdownContext\(ctx context.Context, how ShutdownMode\) wit.Result\[Observation, StreamError\] \{\n.*?^\}',
    rb'(?ms)^func \(c \*Connection\) CloseContext\(ctx context.Context\) wit.Result\[Observation, StreamError\] \{\n.*?^\}',
)

WIT = b'''package wit
type Option[T any] struct { Value T; Present bool }
func None[T any]() Option[T] { return Option[T]{} }
func Some[T any](x T) Option[T] { return Option[T]{Value:x, Present:true} }
type Result[T,E any] struct { Value T; Failure E; Failed bool }
func Ok[T,E any](v T) Result[T,E] { return Result[T,E]{Value:v} }
func Err[T,E any](e E) Result[T,E] { return Result[T,E]{Failure:e, Failed:true} }
func (r Result[T,E]) IsErr() bool { return r.Failed }
func (r Result[T,E]) Err() E { return r.Failure }
'''

RAW = b'''package raw
import ("context"; "sync/atomic"; wit "example.invalid/halfclose/wit")
type ShutdownMode = uint8
const ShutdownModeSend ShutdownMode = 0
type Observation struct{}
type StreamError struct { Code uint8; MayHaveApplied bool }
const (
 ErrorCodeUnsupported uint8 = iota + 1
 ErrorCodeInvalidState
 ErrorCodeInvalidInput
 ErrorCodeTimeout
 ErrorCodeCancelled
 ErrorCodeUncertain
)
type Connection struct {
 OnShutdown func(context.Context, ShutdownMode) wit.Result[Observation,StreamError]
 OnClose func(context.Context) wit.Result[Observation,StreamError]
 Drops atomic.Int32
}
func (c *Connection) Drop() { c.Drops.Add(1) }
func ShutdownContext(ctx context.Context,c *Connection,how ShutdownMode) wit.Result[Observation,StreamError] { return c.OnShutdown(ctx,how) }
func CloseContext(ctx context.Context,c *Connection) wit.Result[Observation,StreamError] { return c.OnClose(ctx) }
'''

NETWORK = b'''package network
import ("context"; wit "example.invalid/halfclose/wit"; raw "example.invalid/halfclose/raw")
type ShutdownMode = raw.ShutdownMode
const ShutdownModeSend = raw.ShutdownModeSend
type Observation = raw.Observation
type StreamError = raw.StreamError
const (
 ErrorCodeUnsupported = raw.ErrorCodeUnsupported
 ErrorCodeInvalidState = raw.ErrorCodeInvalidState
 ErrorCodeInvalidInput = raw.ErrorCodeInvalidInput
 ErrorCodeTimeout = raw.ErrorCodeTimeout
 ErrorCodeCancelled = raw.ErrorCodeCancelled
 ErrorCodeUncertain = raw.ErrorCodeUncertain
)
type Connection struct { owner *connectionOwner[*raw.Connection] }
func TestConnection(c *raw.Connection) *Connection { return &Connection{newConnectionOwner(c)} }
func (c *Connection) TestBorrowRead() (context.Context, func(), bool) {
 _, child, release, ok := c.owner.borrow(context.Background(), streamRead)
 return child, release, ok
}
'''


def methods(raw: bytes, patterns: tuple[bytes, ...]) -> tuple[bytes, ...]:
    if not isinstance(raw, bytes) or len(raw) > 65536 or b'\r' in raw:
        raise ValueError('go-half-close-source-bound')
    selected = []
    for pattern in patterns:
        matches = re.findall(pattern, raw)
        if len(matches) != 1:
            raise ValueError('go-half-close-method-shape')
        selected.append(matches[0])
    return tuple(selected)


def projected(raw: bytes) -> bytes:
    return (b'package halfclose\n'
            b'import ("context"; lsfOS "os"; "time"; '
            b'lsfWit "example.invalid/halfclose/wit"; '
            b'lsfNetwork "example.invalid/halfclose/network")\n'
            + b'\n\n'.join(methods(raw, PATTERNS)) + b'\n')


def projected_sdk(raw: bytes) -> bytes:
    return NETWORK + b'\n' + b'\n\n'.join(methods(raw, SDK_PATTERNS)) + b'\n'


def observed(raw: bytes, old: bool) -> list[str]:
    if not isinstance(raw, bytes) or len(raw) > 1024 * 1024:
        raise ValueError('go-half-close-output-bound')
    passed, failed, packages, messages = [], [], [], []
    for line in raw.splitlines():
        def unique(pairs):
            obj = {}
            for key, value in pairs:
                if key in obj:
                    raise ValueError('go-half-close-duplicate-field')
                obj[key] = value
            return obj
        row = json.loads(line, object_pairs_hook=unique)
        if not isinstance(row, dict) or row.get('Package') != 'example.invalid/halfclose':
            raise ValueError('go-half-close-package')
        action, case = row.get('Action'), row.get('Test')
        if action not in {'start', 'run', 'output', 'pass', 'fail'} or case is not None and case not in CASES:
            raise ValueError('go-half-close-unknown-or-skipped')
        if action in {'pass', 'fail'}:
            if case is None:
                packages.append(action)
            else:
                (passed if action == 'pass' else failed).append(case)
        if action == 'output':
            messages.append(row.get('Output', ''))
    if old:
        if (passed or failed != [CASES[0]] or packages != ['fail']
                or not any('expired-half-close: err=closewrite: i/o timeout calls=0 shut=false' in text for text in messages)):
            raise ValueError('go-half-close-original-counterexample-required')
        return failed
    if passed != list(CASES) or failed or packages != ['pass']:
        raise ValueError('go-half-close-all-controls-required')
    return passed


def qualify(output: Path, compiler: Path, environment: dict, old: bytes,
            current: bytes, sdk: bytes, owner: bytes, tests: bytes) -> dict:
    if hashlib.sha256(old).hexdigest() != OLD_TEMPLATE_SHA:
        raise ValueError('go-half-close-counterexample-preimage')
    if not isinstance(tests, bytes) or len(tests) > 65536:
        raise ValueError('go-half-close-fixture-bound')
    if not isinstance(owner, bytes) or len(owner) > 65536 or not owner.startswith(b'// This private owner'):
        raise ValueError('go-half-close-owner-bound')
    results = {}
    for name, source in (('half-close-old', old), ('half-close-current', current)):
        module = output / name
        module.mkdir()
        (module / 'go.mod').write_bytes(b'module example.invalid/halfclose\n\ngo 1.27.3\n')
        (module / 'production.go').write_bytes(projected(source))
        (module / 'half_close_test.go').write_bytes(tests)
        for directory in ('wit', 'raw', 'network'):
            (module / directory).mkdir()
        (module / 'wit/option.go').write_bytes(WIT)
        (module / 'raw/raw.go').write_bytes(RAW)
        (module / 'network/connection.go').write_bytes(projected_sdk(sdk))
        (module / 'network/owner.go').write_bytes(owner)
        args = [str(compiler), 'test', '-json', '-timeout=10s', '-count=1']
        if name == 'half-close-old':
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
        if result.returncode != (1 if name == 'half-close-old' else 0):
            raise ValueError('go-half-close-unexpected-command-outcome:' + name)
        results[name] = observed(result.output, name == 'half-close-old')
    return {'schemaVersion': 'latent.go.half-close.reference.v1', 'status': 'passed',
            'oldTemplateSha256': OLD_TEMPLATE_SHA,
            'currentTemplateSha256': hashlib.sha256(current).hexdigest(),
            'sdkSha256': hashlib.sha256(sdk).hexdigest(),
            'ownerSha256': hashlib.sha256(owner).hexdigest(),
            'fixtureSha256': hashlib.sha256(tests).hexdigest(), 'outcomes': results,
            'evidenceKind': 'exact-adapter-and-sdk-owner-with-canonical-double-and-native-loopback',
            'signedGuestExecuted': False, 'liveProviderExecuted': False,
            'kernelAccountingQualified': False}
