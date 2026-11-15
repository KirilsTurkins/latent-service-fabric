"""Exact active-deadline setter, exercised with ordinary Go time values.

This fixed source projection has no live provider or component execution.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from tools.owned_test_process import ProcessFailure, run_owned
from tools.test_run import redact

TESTS = 'tools/tests/fixtures/go_network/deadline-set-test.go.txt'
BASELINE = '334e6e11854b0d345b278b8cf57e4b03a41cef43'
OLD_SHA = 'fd6f54d3fff31aada600ebdb8fd2c48f0491b9ffba998d80129ac337e14c7396'
CASES = ('TestMixedMonotonicDeadlineRefusal', 'TestSameBasisAndZeroDeadlineRemainAllowed',
         'TestBothDirectionsClosedAndIdleRemainUnchanged', 'TestSyntheticWallStepSeparatesEqualDeadlineBases')
PACKAGE = 'example.invalid/streamdeadline'
STUB = b'''package streamdeadline
import ("errors"; "fmt"; lsfSync "sync"; "time")
var ErrClosed = errors.New("closed")
func lsfStreamUnsupported() error { return errors.ErrUnsupported }
type lsfStreamConn struct {
    mu lsfSync.Mutex
    readDeadline, writeDeadline time.Time
    readBusy, writeBusy, closing bool
}
func (c *lsfStreamConn) opError(op string, err error) error { return fmt.Errorf("%s: %w", op, err) }
'''


def methods(raw: bytes, *, current: bool) -> tuple[bytes, ...]:
    if not isinstance(raw, bytes) or len(raw) > 65536 or b'\r' in raw:
        raise ValueError('go-deadline-set-source-bound')
    setter = re.findall(rb'(?ms)^func \(c \*lsfStreamConn\) setDeadline\(t time.Time, read, write bool\) error \{\n.*?^\}', raw)
    helper = re.findall(rb'(?ms)^func lsfStreamSameDeadline\(a, b time.Time\) bool \{\n.*?^\}', raw)
    if len(setter) != 1 or len(helper) != int(current):
        raise ValueError('go-deadline-set-method-shape')
    return (*helper, setter[0])


def projected(raw: bytes, *, current: bool) -> bytes:
    return STUB + b'\n'.join(methods(raw, current=current)) + b'\n'


def observed(raw: bytes, old: bool) -> list[str]:
    if not isinstance(raw, bytes) or len(raw) > 1024 * 1024:
        raise ValueError('go-deadline-set-output-bound')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('go-deadline-set-duplicate-field')
            value[key] = item
        return value
    passed, failed, packages, messages = [], [], [], []
    for line in raw.splitlines():
        row = json.loads(line, object_pairs_hook=unique)
        if not isinstance(row, dict) or row.get('Package') != PACKAGE:
            raise ValueError('go-deadline-set-package')
        action, case = row.get('Action'), row.get('Test')
        if action not in {'start', 'run', 'output', 'pass', 'fail'} or case is not None and case not in CASES:
            raise ValueError('go-deadline-set-unknown-or-skipped')
        if action in {'pass', 'fail'}:
            if case is None:
                packages.append(action)
            else:
                (passed if action == 'pass' else failed).append(case)
        if action == 'output':
            messages.append(row.get('Output', ''))
    if old:
        if (passed or failed != [CASES[0]] or packages != ['fail']
                or not any('mixed-clock-basis-accepted:' in value for value in messages)):
            raise ValueError('go-deadline-set-old-counterexample-required')
        return failed
    if passed != list(CASES) or failed or packages != ['pass']:
        raise ValueError('go-deadline-set-all-controls-required')
    return passed


def qualify(output: Path, compiler: Path, environment: dict, old: bytes,
            current: bytes, tests: bytes) -> dict:
    old_method = methods(old, current=False)[0]
    if hashlib.sha256(old_method).hexdigest() != OLD_SHA:
        raise ValueError('go-deadline-set-counterexample-preimage')
    if not isinstance(tests, bytes) or len(tests) > 65536:
        raise ValueError('go-deadline-set-fixture-bound')
    results = {}
    for label, source in (('deadline-set-old', old), ('deadline-set-current', current)):
        module = output / label
        module.mkdir()
        (module / 'go.mod').write_bytes(b'module example.invalid/streamdeadline\n\ngo 1.27.4\n')
        (module / 'set.go').write_bytes(projected(source, current=label.endswith('current')))
        (module / 'set_test.go').write_bytes(tests)
        args = [str(compiler), 'test', '-json', '-timeout=10s', '-count=1']
        if label == 'deadline-set-old':
            args += ['-run', '^' + CASES[0] + '$']
        args.append('.')
        def retain(result):
            if result is not None:
                (output / (label + '.stdout.log')).write_bytes(result.output)
                (output / (label + '.stderr.log')).write_bytes(redact(result.stderr.decode('utf-8', 'replace')).encode())
        try:
            result = run_owned(args, cwd=module, env=environment, timeout=120,
                               maximum=1024 * 1024, separate_stderr=True)
        except ProcessFailure as failure:
            retain(failure.result)
            raise
        retain(result)
        if result.returncode != (1 if label.endswith('old') else 0):
            raise ValueError('go-deadline-set-unexpected-command-outcome:' + label)
        results[label] = observed(result.output, label.endswith('old'))
    helper, setter = methods(current, current=True)
    return {'schemaVersion': 'latent.go.network-deadline-set.reference.v1', 'status': 'passed',
            'oldMethodSha256': OLD_SHA, 'currentMethodSha256': hashlib.sha256(setter).hexdigest(),
            'currentHelperSha256': hashlib.sha256(helper).hexdigest(), 'fixtureSha256': hashlib.sha256(tests).hexdigest(),
            'outcomes': results, 'evidenceKind': 'exact-setter-real-Go-time-with-synthetic-wall-step',
            'signedGuestExecuted': False, 'liveProviderExecuted': False}