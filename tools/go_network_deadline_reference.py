"""Exact Go timeout function with explicit clock and provider stand-ins.

This bounded reference is not a live provider, component or signed execution.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re

from tools.owned_test_process import ProcessFailure, run_owned
from tools.test_run import redact

TESTS = 'tools/tests/fixtures/go_network/deadline-test.go.txt'
MATERIALS = ('crates/latent-streams/src/config.rs', 'crates/latent-streams/src/provider.rs',
             'crates/latent-streams/src/connection.rs', 'sdk/go-guest/capabilities/network.go.in',
             'tools/go_guest/network_context.py')
OLD_SHA = '0a35e175a43532dcfb779665cc479f131d964f2e1d92b7e9ce3a09adef81a608'
CASES = ('TestLongDeadlineEntersProviderWithAcceptedArgument',
         'TestNoDeadlineAndExpiredDeadline', 'TestCeilingAndProviderMaximum',
         'TestProviderModelRetainsNarrowerOriginalDeadline')
OPTION = b'''package wit

type Option[T any] struct { Value T; Present bool }
func None[T any]() Option[T] { return Option[T]{} }
func Some[T any](value T) Option[T] { return Option[T]{Value: value, Present: true} }
'''
CLOCK = b'''package faketime

type Duration = int64
type Time struct { Remaining Duration; Empty bool }
const Millisecond = 1000000
func (value Time) IsZero() bool { return value.Empty }
func Until(value Time) Duration { return value.Remaining }
'''


def method(raw: bytes) -> bytes:
    if not isinstance(raw, bytes) or len(raw) > 65536 or b'\r' in raw:
        raise ValueError('go-network-deadline-source-bound')
    rows = re.findall(rb'(?ms)^func lsfStreamTimeout\(deadline time.Time\) \(lsfWit.Option\[uint32\], error\) \{\n.*?^\}', raw)
    if len(rows) != 1:
        raise ValueError('go-network-deadline-method-shape')
    return rows[0]


def projected(raw: bytes) -> bytes:
    return (b'package streamdeadline\n'
            b'import (time "example.invalid/streamdeadline/faketime"; '
            b'lsfWit "example.invalid/streamdeadline/wit"; lsfOS "os"; "errors")\n'
            b'func lsfStreamUnsupported() error { return errors.New("unsupported") }\n'
            + method(raw) + b'\n')


def observed(raw: bytes, old: bool) -> list[str]:
    if not isinstance(raw, bytes) or len(raw) > 1024 * 1024:
        raise ValueError('go-network-deadline-output-bound')
    passed, failed, packages, messages = [], [], [], []
    for line in raw.splitlines():
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError('go-network-deadline-duplicate-field')
                value[key] = item
            return value
        row = json.loads(line, object_pairs_hook=unique)
        if not isinstance(row, dict) or row.get('Package') != 'example.invalid/streamdeadline':
            raise ValueError('go-network-deadline-package')
        action, case = row.get('Action'), row.get('Test')
        if action not in {'start', 'run', 'output', 'pass', 'fail'} or case is not None and case not in CASES:
            raise ValueError('go-network-deadline-unknown-or-skipped')
        if action in {'pass', 'fail'}:
            if case is None:
                packages.append(action)
            else:
                (passed if action == 'pass' else failed).append(case)
        if action == 'output':
            messages.append(row.get('Output', ''))
    if old:
        if (passed or failed != [CASES[0]] or packages != ['fail']
                or not any('provider-timeout-argument-rejected: value=11000' in value for value in messages)):
            raise ValueError('go-network-deadline-old-counterexample-required')
        return failed
    if passed != list(CASES) or failed or packages != ['pass']:
        raise ValueError('go-network-deadline-all-controls-required')
    return passed


def contract(template: bytes, materials: dict[str, bytes]) -> None:
    """Fail closed if the selected provider or unchanged context port drifts."""
    if set(materials) != set(MATERIALS) or any(not isinstance(v, bytes) or len(v) > 1024 * 1024 for v in materials.values()):
        raise ValueError('go-network-deadline-materials')
    config = materials[MATERIALS[0]]
    provider = materials[MATERIALS[1]]
    connection = materials[MATERIALS[2]]
    facade = materials[MATERIALS[3]]
    context = materials[MATERIALS[4]]
    # A plain-TCP readiness observation may use zero without retiring the
    # connection. Reads/writes still reject zero and retain the same original,
    # idle and requested deadline minimum; this is not a larger I/O budget.
    required = ((config, b'self.limits.absolute_timeout_millis > 10_000'),
                (provider, b'let original = session.deadline()?;'),
                (provider, b'self.inner.config.limits.absolute_timeout_millis'),
                (provider, b'if timeout == 0 || timeout > 10_000'),
                (provider, b'deadline = deadline.min(now + Duration::from_millis(u64::from(timeout)));'),
                (connection, b'deadline: deadline.min(validity),'),
                (connection, b'if timeout.is_some_and(|value| value > 10_000 || (value == 0 && direction != 2))'),
                (connection, b'let mut deadline = self.deadline.min(state.last_progress + self.idle);'),
                (connection, b'let observation = direction == 2 && !socket.host_tls() && !socket.protected_owner();'),
                (connection, b'let requested = timeout.map(|value| now + Duration::from_millis(u64::from(value)));'),
                (connection, b'if !observation {\n            if let Some(requested) = requested {\n                deadline = deadline.min(requested);'),
                (facade, b'r := raw.ConnectContext(ctx, request)'),
                (context, b'witAsync.SubtaskWaitContext(ctx, uint32('))
    if any(source.count(marker) != 1 for source, marker in required):
        raise ValueError('go-network-deadline-provider-or-context-drift')
    dial = re.findall(rb'(?ms)^func lsfStreamDial\(ctx context.Context, d \*Dialer, network, address string\) \(Conn, error\) \{\n.*?^\}', template)
    if (len(dial) != 1 or b'if err := ctx.Err(); err != nil' not in dial[0]
            or b'lsfNetwork.ConnectContext(ctx,' not in dial[0]):
        raise ValueError('go-network-deadline-dial-context-drift')


def qualify(output: Path, compiler: Path, environment: dict, old: bytes,
            current: bytes, tests: bytes) -> dict:
    old_hash = hashlib.sha256(method(old)).hexdigest()
    if old_hash != OLD_SHA:
        raise ValueError('go-network-deadline-counterexample-preimage')
    if not isinstance(tests, bytes) or len(tests) > 65536:
        raise ValueError('go-network-deadline-fixture-bound')
    results = {}
    for name, source in (('deadline-old', old), ('deadline-current', current)):
        module = output / name
        module.mkdir()
        (module / 'go.mod').write_bytes(b'module example.invalid/streamdeadline\n\ngo 1.27.3\n')
        (module / 'deadline.go').write_bytes(projected(source))
        (module / 'deadline_test.go').write_bytes(tests)
        (module / 'wit').mkdir()
        (module / 'wit/option.go').write_bytes(OPTION)
        (module / 'faketime').mkdir()
        (module / 'faketime/time.go').write_bytes(CLOCK)
        args = [str(compiler), 'test', '-json', '-timeout=10s', '-count=1']
        if name == 'deadline-old':
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
        if result.returncode != (1 if name == 'deadline-old' else 0):
            raise ValueError('go-network-deadline-unexpected-command-outcome:' + name)
        results[name] = observed(result.output, name == 'deadline-old')
    return {'schemaVersion': 'latent.go.network-deadline.reference.v1', 'status': 'passed',
            'oldMethodSha256': old_hash, 'currentMethodSha256': hashlib.sha256(method(current)).hexdigest(),
            'fixtureSha256': hashlib.sha256(tests).hexdigest(), 'outcomes': results,
            'evidenceKind': 'exact-method-with-clock-and-provider-doubles',
            'signedGuestExecuted': False, 'liveProviderExecuted': False,
            'exactWallClockDeadlineGuaranteed': False}
