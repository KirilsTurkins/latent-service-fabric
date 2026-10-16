"""Bounded TeaVM compiler observations; no package or execution authority.

Only exact diagnostics emitted by the maintained compiler are recognized. Other
failures retain the original unknown report. A selected classpath entry binds a
native-method observation to original application bytes, never a package name.
"""
from __future__ import annotations

import re
from pathlib import Path

from tools import guest_compatibility as compatibility
from tools.build_snapshot import digest
from tools.rust_capsule_project import decode_json, read_file, write_json

MAX_LOG = 4 * 1024 * 1024
NAME = r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+'
DESCRIPTOR = r'\([A-Za-z0-9_/$;\[\]]{0,1024}\)[A-Za-z0-9_/$;\[\]]{1,1024}'
NATIVE = re.compile(r'Method (' + NAME + r')' + DESCRIPTOR
                    + r' is native but has no org\.teavm\.interop\.Import annotation on it')
MISSING_METHOD = re.compile(r'Method (' + NAME + r')' + DESCRIPTOR + r' was not found')
MISSING_CLASS = re.compile(r'Class (' + NAME + r') was not found')


def findings(raw: bytes, classpath: dict, source: str) -> tuple[list[dict], int]:
    if len(raw) > MAX_LOG:
        raise ValueError('java-compiler-diagnostic-log-bound')
    text = raw.decode('utf-8')
    owners = {}
    for artifact in classpath['artifacts']:
        for entry in artifact['entries']:
            path = entry['path']
            if path.endswith('.class'):
                if path in owners:
                    raise ValueError('java-compiler-diagnostic-ambiguous-classpath')
                owners[path] = artifact['originalDigest']
    observed, seen, omitted = [], set(), 0
    for line in text.splitlines():
        if len(line) > 4096:
            continue
        line = line.strip()
        native, method, cls = NATIVE.fullmatch(line), MISSING_METHOD.fullmatch(line), MISSING_CLASS.fullmatch(line)
        value = None
        if native:
            symbol = native[1]
            owner = owners.get(symbol.rsplit('.', 1)[0].replace('.', '/') + '.class')
            if owner is not None:
                value = compatibility.finding('target-incompatible', 'compile', 'compiler',
                    operation=symbol, symbol=symbol, package_digest=owner,
                    source_digest=source, owner_issue=741)
        elif method or cls:
            symbol = (method or cls)[1]
            if symbol.startswith('java.'):
                value = compatibility.finding('missing-runtime-port', 'compile', 'compiler',
                    operation=symbol, symbol=symbol, source_digest=source, owner_issue=741)
        if value is None:
            continue
        identity = tuple(sorted(value.items()))
        if identity in seen:
            continue
        seen.add(identity)
        if len(observed) < compatibility.MAX_FINDINGS:
            observed.append(value)
        else:
            omitted += 1
    return observed, omitted


def emit(output: Path, stage: str, *, expected_source: bytes | None = None,
         expected_compiler: bytes | None = None, expected_classpath: dict | None = None) -> None:
    """Retain a separate v1 report without replacing any original failure."""
    if stage != 'compile':
        return
    try:
        failure = decode_json(read_file(output / 'BUILD-FAILED.json', 1024 * 1024))
        failed = [row for row in failure['commands'] if row['stage'] == 'java-to-c'
                  and type(row.get('exitCode')) is int and row['exitCode'] != 0]
        if failure['stage'] != 'compile' or len(failed) != 1:
            return
        logs = list((output / 'compiler-logs').glob('*-java-to-c.log'))
        if len(logs) != 1:
            return
        original = compatibility.read(read_file(output / 'compatibility-report.json', compatibility.MAX_BYTES))
        source = read_file(output / 'source-inputs.json', 8 * 1024 * 1024)
        compiler = read_file(output / 'compiler-inputs.json', 8 * 1024 * 1024)
        classpath = decode_json(read_file(output / 'java-classpath.json', 8 * 1024 * 1024))
        if (original['language'] != 'java' or original['sourceDigest'] != digest(source)
                or original['componentDigest'] is not None or source != expected_source
                or compiler != expected_compiler or classpath != expected_classpath):
            raise ValueError('java-compiler-diagnostic-stale-source')
        observed, omitted = findings(read_file(logs[0], MAX_LOG), classpath, digest(source))
        if not observed and not omitted:
            return
        value = compatibility.report('java', digest(source), None, original['runtimeProfile'],
            [{'kind': 'application', 'digest': digest(source)}, {'kind': 'compiler', 'digest': digest(compiler)}],
            [*original['findings'], *observed], omitted=original['omittedFindings'] + omitted)
        write_json(output / 'compatibility-java-compiler-report.json', value)
    except Exception:
        # Diagnostics execute while the original exception is propagating.
        # Missing, changed or unfamiliar evidence cannot mask that exception.
        try:
            write_json(output / 'compatibility-java-compiler-failed.json', {
                'schemaVersion': 'lsf.guest.compatibility.failure.v1', 'status': 'unavailable',
                'authority': 'none', 'reason': 'java-compiler-observation-unavailable-or-stale'})
        except Exception:
            pass
