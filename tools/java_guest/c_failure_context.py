"""Explicit public-fixture C failure context; never change compiler acceptance."""
from __future__ import annotations

import json
from pathlib import Path
import re

from tools.dev_workflow import paths
from tools.rust_capsule_project import digest

FIXTURE_SOURCES = ('d/l/a/Capsule.c', 'j/u/z/GZIPInputStream.c')
MAX_FILE = 4 * 1024 * 1024
MAX_CONTEXT = 128 * 1024
SCHEMA = 'latent.java.public-fixture-c-context.v1'
ERROR = re.compile(r'^([^\r\n]{1,4096}\.c):([1-9][0-9]{0,6}):[1-9][0-9]{0,6}: error:')
FUNCTION = re.compile(r'[A-Za-z_][A-Za-z0-9_* ]{0,512}\([^\r\n]{0,2048}\)\s*\{')
DECLARATION = re.compile(r'\s*(?:(?:volatile|const|unsigned|signed|struct)\s+)*'
    r'(?:void|u?int(?:8|16|32|64)_t|float|double|TeaVM_[A-Za-z0-9_]+)\b[^;\r\n]{1,4096};\s*')


def selection(selected: tuple[str, ...]) -> None:
    if type(selected) is not tuple or selected not in ((), FIXTURE_SOURCES):
        raise ValueError('java-c-failure-context-selection-invalid')


def collect(generated: Path, log: bytes, selected: tuple[str, ...]) -> dict:
    """Read only fixed generated public sources through anchored regular readers."""
    selection(selected)
    if selected != FIXTURE_SOURCES or len(log) > MAX_FILE:
        raise ValueError('java-c-failure-context-input-invalid')
    paths.absolute(generated)
    rows, files = [], {}
    for line in log.decode('utf-8').splitlines():
        match = ERROR.match(line)
        if match is None:
            continue
        candidate = Path(match[1])
        if not candidate.is_absolute() or not candidate.is_relative_to(generated):
            raise ValueError('java-c-failure-context-outside-generated-root')
        relative = candidate.relative_to(generated).as_posix()
        if relative not in selected:
            continue
        if len(rows) >= 4:
            raise ValueError('java-c-failure-context-error-bound')
        if relative not in files:
            raw = paths.read(generated, relative, MAX_FILE)
            lines = raw.decode('utf-8').splitlines()
            if b'\0' in raw or any(len(value.encode('utf-8')) > 4096 for value in lines):
                raise ValueError('java-c-failure-context-line-bound')
            files[relative] = (raw, lines)
        raw, lines = files[relative]
        error = int(match[2]) - 1
        if not 0 <= error < len(lines):
            raise ValueError('java-c-failure-context-line-invalid')
        starts = [index for index in range(max(0, error - 4096), error + 1)
                  if FUNCTION.fullmatch(lines[index])]
        if not starts:
            raise ValueError('java-c-failure-context-function-unavailable')
        start = starts[-1]
        declarations = [{'line': index + 1, 'text': lines[index]}
            for index in range(start + 1, error + 1)
            if DECLARATION.fullmatch(lines[index])]
        if len(declarations) > 64:
            raise ValueError('java-c-failure-context-declaration-bound')
        rows.append({'path': relative, 'sourceDigest': digest(raw), 'sourceBytes': len(raw),
            'errorLine': error + 1, 'function': {'line': start + 1, 'text': lines[start]},
            'declarations': declarations,
            'context': [{'line': index + 1, 'text': lines[index]}
                        for index in range(max(start, error - 64), min(len(lines), error + 65))]})
    if not rows:
        raise ValueError('java-c-failure-context-no-selected-error')
    result = {'schemaVersion': SCHEMA, 'status': 'observed', 'stage': 'c-to-wasm',
              'publicFixtureOnly': True, 'logDigest': digest(log), 'errors': rows}
    if len(encoded(result)) > MAX_CONTEXT:
        raise ValueError('java-c-failure-context-byte-bound')
    return result


def encoded(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')) + '\n').encode('utf-8')


def run(compiler, generated: Path, selected: tuple[str, ...], *arguments) -> str:
    """Observe only failed clang; the original exception and command stay intact."""
    selection(selected)
    try:
        return compiler.run('c-to-wasm', 'clang', *arguments)
    except Exception:
        if selected:
            try:
                ordinal = len(compiler.records) - 1
                record = compiler.records[ordinal]
                if ordinal < 0 or record['stage'] != 'c-to-wasm':
                    raise ValueError('java-c-failure-context-stage-invalid')
                try:
                    log = paths.read(compiler.directory, str(ordinal) + '-c-to-wasm.log', MAX_FILE)
                    result = collect(generated, log, selected)
                except Exception:
                    result = {'schemaVersion': SCHEMA, 'status': 'unavailable', 'stage': 'c-to-wasm',
                              'publicFixtureOnly': True, 'reason': 'bounded-selected-context-unavailable'}
                raw = encoded(result)
                if compiler.retained_bytes + len(raw) > 16 * 1024 * 1024:
                    raise ValueError('java-c-failure-context-total-bound')
                paths.write_new(compiler.directory / (str(ordinal) + '-c-to-wasm-context.command.json'), raw)
                compiler.retained_bytes += len(raw)
            except Exception:
                pass
        raise
