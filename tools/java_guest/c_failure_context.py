"""Explicit public-fixture C failure context; never change compiler acceptance."""
from __future__ import annotations

import json
from pathlib import Path
import re

from tools.dev_workflow import paths
from tools.rust_capsule_project import digest

FIXTURE_SOURCES = ('c/d/l/a/Capsule.c', 'c/j/u/z/GZIPInputStream.c')
PHASE_FIXTURE_SOURCES = (*FIXTURE_SOURCES, 'c/j/u/TimeZone.c')
CHECKPOINT_CLASSES = ('c/d/l/a/Capsule', 'c/j/l/Object', 'c/j/l/Thread', 'c/o/t/r/Fiber',
    'c/d/l/g/r/Activation', 'c/o/a/c/l/c/AtomicSafeInitializer', 'c/o/t/r/EventQueue',
    'c/d/l/g/r/Monitors')
CHECKPOINT_SOURCES = tuple(name + suffix for name in CHECKPOINT_CLASSES for suffix in ('.c', '.h'))
CHECKPOINT_JAVA = 'sha256:2fe6c39a15d8e230838ae709599055cdba156bd8d9058f472c1dc5be469a88e8'
CHECKPOINT_MAX_FILE = 1024 * 1024
CHECKPOINT_MAX_BYTES = 8 * 1024 * 1024

MAX_FILE = 4 * 1024 * 1024
MAX_CONTEXT = 128 * 1024
SCHEMA = 'latent.java.public-fixture-c-context.v1'
REFUSALS = frozenset({'input-invalid', 'outside-generated-root', 'error-bound', 'line-bound',
    'line-invalid', 'function-unavailable', 'declaration-bound', 'no-selected-error', 'byte-bound'})
ERROR = re.compile(r'^([^\r\n]{1,4096}\.c):([1-9][0-9]{0,6}):[1-9][0-9]{0,6}: error:')
FUNCTION = re.compile(r'[A-Za-z_][A-Za-z0-9_* ]{0,512}\([^\r\n]{0,2048}\)\s*\{')
DECLARATION = re.compile(r'\s*(?:(?:volatile|const|unsigned|signed|struct)\s+)*'
    r'(?:void|u?int(?:8|16|32|64)_t|float|double|TeaVM_[A-Za-z0-9_]+)\b[^;\r\n]{1,4096};\s*')


def selection(selected: tuple[str, ...]) -> None:
    if type(selected) is not tuple or selected not in ((), FIXTURE_SOURCES, PHASE_FIXTURE_SOURCES, CHECKPOINT_SOURCES):
        raise ValueError('java-c-failure-context-selection-invalid')


def teavm(compiler, project: Path, selected: tuple[str, ...]) -> str:
    """Keep default commands exact; the explicit public fixture gets a stack."""
    selection(selected)
    return compiler.run('java-to-c', 'gradle', '--no-daemon',
        *(['--offline'] if compiler.offline else []),
        *(['--stacktrace'] if selected else []), 'generateC', cwd=project)


def collect(generated: Path, log: bytes, selected: tuple[str, ...]) -> dict:
    """Read only fixed generated public sources through anchored regular readers."""
    selection(selected)
    if selected not in (FIXTURE_SOURCES, PHASE_FIXTURE_SOURCES) or len(log) > MAX_FILE:
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
        end = next((index for index in range(error + 1, len(lines)) if FUNCTION.fullmatch(lines[index])), len(lines))
        symbols = tuple(dict.fromkeys(re.findall(r'\bteavm_local_[0-9]+\b', lines[error])))
        references = [index for index in range(start, end)
            if symbols and re.search(r'\b(?:' + '|'.join(map(re.escape, symbols)) + r')\b', lines[index])]
        rows.append({'path': relative, 'sourceDigest': digest(raw), 'sourceBytes': len(raw),
            'errorLine': error + 1, 'function': {'line': start + 1, 'text': lines[start]},
            'declarations': declarations,
            'symbols': list(symbols), 'referenceCount': len(references),
            'omittedReferences': max(0, len(references) - 128),
            'references': [{'line': index + 1, 'text': lines[index]} for index in references[:128]],
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


def refusal(error: Exception) -> str:
    code = error.args[0] if len(error.args) == 1 and type(error.args[0]) is str else ''
    selected = code.removeprefix('java-c-failure-context-')
    if code.startswith('java-c-failure-context-') and selected in REFUSALS:
        return selected
    if code in {'file-byte-limit', 'source-file-unavailable-or-unsafe', 'single-link-regular-file-required',
                'reparse-point-rejected', 'source-changed-during-read', 'windows-protected-open-failed',
                'reparse-or-file-type-rejected'}:
        return 'file-unavailable-or-unsafe'
    if isinstance(error, UnicodeError):
        return 'encoding'
    return 'unavailable'


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
                except Exception as error:
                    result = {'schemaVersion': SCHEMA, 'status': 'unavailable', 'stage': 'c-to-wasm',
                              'publicFixtureOnly': True, 'reason': 'bounded-selected-context-unavailable',
                              'refusal': refusal(error)}
                raw = encoded(result)
                if compiler.retained_bytes + len(raw) > 16 * 1024 * 1024:
                    raise ValueError('java-c-failure-context-total-bound')
                paths.write_new(compiler.directory / (str(ordinal) + '-c-to-wasm-context.command.json'), raw)
                compiler.retained_bytes += len(raw)
            except Exception:
                pass
        raise


def retain_component_inputs(compiler, source: Path, output: Path, selected: tuple[str, ...]) -> None:
    """Retain only explicitly selected fixed public compiler outputs.

    Runs before the owned temporary cleanup without replacing an original
    exception. Historical phase selection retains only failed assembly inputs;
    the byte-exact checkpoint fixture retains eight adapted C/header pairs.
    The separate output bounds never extend the original 16 MiB log cap.
    """
    if type(selected) is tuple and selected == CHECKPOINT_SOURCES:
        try:
            # Only this byte-exact public diagnostic fixture can select the
            # closed eight-class projection. The read occurs after adapt and
            # the real clang attempt, before the original temporary cleanup.
            if compiler is None or not any(row.get('stage') == 'c-to-wasm' for row in compiler.records):
                raise ValueError('checkpoint-generated-before-adapt')
            fixture = paths.read(source, 'project/src/main/java/dev/latent/app/Capsule.java', CHECKPOINT_MAX_FILE)
            if digest(fixture) != CHECKPOINT_JAVA:
                raise ValueError('checkpoint-generated-fixture-mismatch')
            generated = source / 'project/build/teavm-c/c'
            payloads, total = {}, 0
            for name in CHECKPOINT_SOURCES:
                raw = paths.read(generated, name, CHECKPOINT_MAX_FILE)
                total += len(raw)
                if total > CHECKPOINT_MAX_BYTES or b'\0' in raw:
                    raise ValueError('checkpoint-generated-byte-bound')
                raw.decode('utf-8')
                payloads[name] = raw
            # Publish nothing until every fixed source and bound is checked.
            target = output / 'checkpoint-generated'
            target.mkdir()
            for name, raw in payloads.items():
                destination = target / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                paths.write_new(destination, raw)
            paths.write_new(output / 'checkpoint-generated.json', encoded({
                'schemaVersion': 'latent.java.checkpoint-generated-c.v1', 'status': 'retained',
                'qualification': False, 'publicFixtureOnly': True, 'afterPlatformAdapt': True,
                'fixtureDigest': CHECKPOINT_JAVA, 'capture': 'after-original-clang-attempt-before-temporary-cleanup',
                'files': {name: {'sha256': digest(raw), 'bytes': len(raw)} for name, raw in payloads.items()},
                'fileLimitBytes': CHECKPOINT_MAX_FILE, 'totalLimitBytes': CHECKPOINT_MAX_BYTES,
                'bytes': total, 'compilerAcceptanceChanged': False, 'logLimitBytesUnchanged': 16*1024*1024}))
        except BaseException:
            try:
                paths.write_new(output / 'checkpoint-generated-refused.json', encoded({
                    'schemaVersion': 'latent.java.checkpoint-generated-c.v1', 'status': 'unavailable',
                    'qualification': False, 'reason': 'fixed-public-generated-inputs-unavailable-or-unsafe'}))
            except BaseException:
                pass
        return
    try:
        if type(selected) is not tuple or selected != PHASE_FIXTURE_SOURCES or compiler is None:
            return
        records = compiler.records
        if (not records or records[-1].get('stage') != 'component-new'
                or type(records[-1].get('exitCode')) is not int or records[-1]['exitCode'] == 0):
            return
        limits = {'core.wasm': 64*1024*1024, 'closed-runtime.wasm': 4*1024*1024}
        # Validate BOTH anchored inputs before publishing either one. No source
        # tree, generated C, private directory or neighbouring file is captured.
        raw = {name: paths.read(source, name, maximum) for name, maximum in limits.items()}
        if any(not value.startswith(b'\0asm\x01\0\0\0') for value in raw.values()):
            raise ValueError('java-component-input-magic')
        target = output/'component-inputs'
        target.mkdir()
        identities = {}
        for name, value in raw.items():
            paths.write_new(target/name, value)
            identities[name] = {'sha256': digest(value), 'bytes': len(value)}
        record = {'schemaVersion': 'latent.java.public-fixture-component-inputs.v1',
            'status': 'retained', 'qualification': False, 'publicFixtureOnly': True,
            'failedStage': 'component-new', 'inputs': identities, 'limits': limits,
            'logLimitBytesUnchanged': 16*1024*1024}
        paths.write_new(output/'component-inputs.json', encoded(record))
    except BaseException:
        try:
            paths.write_new(output/'component-inputs-refused.json', encoded({
                'schemaVersion': 'latent.java.public-fixture-component-inputs.v1',
                'status': 'unavailable', 'qualification': False,
                'reason': 'fixed-assembly-inputs-unavailable-or-unsafe'}))
        except BaseException:
            pass
