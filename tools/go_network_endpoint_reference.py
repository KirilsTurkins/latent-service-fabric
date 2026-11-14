"""Exact Go endpoint parser with a pinned original Unicode-folding counterexample.

This source projection uses the standard net parser and does not execute a guest
or any provider. The actual host continues to authorize every connection.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re

from tools.owned_test_process import ProcessFailure, run_owned
from tools.test_run import redact

TESTS = 'tools/tests/fixtures/go_network/endpoint-test.go.txt'
OLD_METHOD_SHA = '6a0acd8754ccace20c21ad1611901b7a934402edb34726a5437e7544ad1e6848'
CASES = ('TestUnicodeAliasRejected', 'TestSupportedASCII', 'TestExistingRefusals',
         'TestASCIIHostLengthBound')


def method(raw: bytes) -> bytes:
    if not isinstance(raw, bytes) or len(raw) > 65536 or b'\r' in raw:
        raise ValueError('go-endpoint-source-bound')
    selected = re.findall(rb'(?ms)^func lsfStreamEndpoint\(address string\) \(string, uint16, error\) \{\n.*?^\}', raw)
    if len(selected) != 1:
        raise ValueError('go-endpoint-method-shape')
    return selected[0]


def projected(raw: bytes) -> bytes:
    return (b'package endpoint\n'
            b'import ("errors"; "net"; "net/netip"; lsfStrconv "strconv"; lsfStrings "strings")\n'
            b'type AddrError = net.AddrError\nvar SplitHostPort = net.SplitHostPort\n'
            b'func lsfStreamUnsupported() error { return errors.ErrUnsupported }\n'
            + method(raw) + b'\n')


def observed(raw: bytes, old: bool) -> list[str]:
    if not isinstance(raw, bytes) or len(raw) > 1024 * 1024:
        raise ValueError('go-endpoint-output-bound')
    passed, failed, packages, messages = [], [], [], []
    for line in raw.splitlines():
        def unique(pairs):
            obj = {}
            for key, value in pairs:
                if key in obj:
                    raise ValueError('go-endpoint-duplicate-field')
                obj[key] = value
            return obj
        row = json.loads(line, object_pairs_hook=unique)
        if not isinstance(row, dict) or row.get('Package') != 'example.invalid/endpoint':
            raise ValueError('go-endpoint-output-package')
        action, case = row.get('Action'), row.get('Test')
        if action not in {'start', 'run', 'output', 'pass', 'fail'} or case is not None and case not in CASES:
            raise ValueError('go-endpoint-unknown-or-skipped')
        if action in {'pass', 'fail'}:
            if case is None:
                packages.append(action)
            else:
                (passed if action == 'pass' else failed).append(case)
        if action == 'output':
            messages.append(row.get('Output', ''))
    if old:
        if (passed or failed != [CASES[0]] or packages != ['fail']
                or not any('non-ASCII endpoint accepted as "k.example":443' in text for text in messages)):
            raise ValueError('go-endpoint-original-counterexample-required')
        return failed
    if passed != list(CASES) or failed or packages != ['pass']:
        raise ValueError('go-endpoint-all-controls-required')
    return passed


def qualify(output: Path, compiler: Path, environment: dict, old: bytes,
            current: bytes, tests: bytes) -> dict:
    if hashlib.sha256(method(old)).hexdigest() != OLD_METHOD_SHA:
        raise ValueError('go-endpoint-counterexample-preimage')
    if not isinstance(tests, bytes) or len(tests) > 65536:
        raise ValueError('go-endpoint-fixture-bound')
    results = {}
    for name, source in (('endpoint-old', old), ('endpoint-current', current)):
        module = output / name
        module.mkdir()
        (module / 'go.mod').write_bytes(b'module example.invalid/endpoint\n\ngo 1.27.4\n')
        (module / 'production.go').write_bytes(projected(source))
        (module / 'endpoint_test.go').write_bytes(tests)
        args = [str(compiler), 'test', '-json', '-timeout=10s', '-count=1']
        if name == 'endpoint-old':
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
        if result.returncode != (1 if name == 'endpoint-old' else 0):
            raise ValueError('go-endpoint-unexpected-command-outcome:' + name)
        results[name] = observed(result.output, name == 'endpoint-old')
    return {'schemaVersion': 'latent.go.endpoint.reference.v1', 'status': 'passed',
            'oldMethodSha256': OLD_METHOD_SHA,
            'currentMethodSha256': hashlib.sha256(method(current)).hexdigest(),
            'fixtureSha256': hashlib.sha256(tests).hexdigest(), 'outcomes': results,
            'evidenceKind': 'exact-method-with-native-go-net-parser',
            'signedGuestExecuted': False, 'liveProviderExecuted': False,
            'kernelAccountingQualified': False}
