#!/usr/bin/env python3
"""Failure-only Wasm frame observer in private source overlays; never qualification."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.rust_capsule_project import ROOT, digest, write_json

CASE = 'signed_standard_timers_contexts_and_rearm_keep_original_heap_owners'
REASONS = 'tools/go_guest/terminal_reasons.json'
REASONS_DIGEST = 'sha256:ec8b59ada82aab3b1f55bb6b89a510f558d184b2e98a4081531976bff34589fb'
THROW_BODY_DIGEST = 'sha256:c049e89b86db59031835024047342eaaa3008b47897e6c42c40255f641fe6a3d'
PATHS = ('crates/latent-wasmtime/src/containment.rs', 'crates/latent-wasmtime/src/config/engine.rs',
         'crates/latent-wasmtime/tests/local_service/runtime/go.rs')


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Go-private-frame-observer-source-drift')
    return text.replace(old, new)


def overlay_sources(root: Path, output: Path) -> tuple[dict, list[tuple[Path, Path]]]:
    originals = {name: (root / name).read_bytes() for name in PATHS}
    changed = {}
    text = originals[PATHS[0]].decode()
    begin = text.index('pub(crate) fn classify_runtime_error(')
    signature = ') -> Result<GuestOutcome, PlatformError> {'
    offset = text.index(signature, begin) + len(signature)
    observer = '''
    // Private failure-only copy: export numeric Wasm offsets and bounded symbols.
    eprintln!("LSF_GO_DIAG_CLASSIFY {}", serde_json::json!({
        "traceAvailable": error.downcast_ref::<wasmtime::WasmBacktrace>().is_some(),
        "trapAvailable": error.downcast_ref::<wasmtime::Trap>().is_some()
    }));
    if let Some(trace) = error.downcast_ref::<wasmtime::WasmBacktrace>() {
        for frame in trace.frames().iter().take(32) {
            let function: String = frame.func_name().unwrap_or("").chars()
                .filter(|ch| ch.is_ascii_alphanumeric() || "_.$:*()<>[]/+-".contains(*ch)).take(160).collect();
            eprintln!("LSF_GO_WASM_FRAME {}", serde_json::json!({
                "function": function, "functionIndex": frame.func_index(),
                "functionOffset": frame.func_offset(), "moduleOffset": frame.module_offset()
            }));
        }
    }
'''
    changed[PATHS[0]] = text[:offset] + observer + text[offset:]
    text = originals[PATHS[1]].decode()
    text = once(text, 'WasmBacktraceDetails::Disable', 'WasmBacktraceDetails::Enable')
    changed[PATHS[1]] = once(text, 'wasm_backtrace_max_frames(None)',
                           'wasm_backtrace_max_frames(std::num::NonZeroUsize::new(32))')
    text = originals[PATHS[2]].decode()
    begin = text.index('async fn ' + CASE + '() {')
    end = text.index('\nasync fn prepare_checkpoint_fixture(', begin)
    focused = '''async fn ''' + CASE + '''() {
    eprintln!("LSF_GO_DIAG_STAGE entered");
    assert_eq!(std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(), Ok("go"));
    let root = tempfile::tempdir().unwrap();
    let f = prepare_checkpoint_fixture(root.path(), "LSF_GO_TIMER_FIXTURE", "go-component-activation-v3").await;
    eprintln!("LSF_GO_DIAG_STAGE prepared");
    let receipt = f.manager.start(f.request("private-go-gc-frame-diagnostic", 9)).unwrap().await;
    eprintln!("LSF_GO_DIAG_STAGE invoked");
    let kind = if let ActivationOutcome::Failed { error, .. } = &receipt.outcome {
        ["memory-out-of-bounds", "unreachable-code", "integer-division-by-zero"].into_iter()
            .find(|candidate| error.details.iter().any(|detail|
                detail.kind == "activation.guest-trap-kind"
                && detail.fields.get("kind").is_some_and(|kind| kind.as_str() == *candidate)))
            .unwrap_or("other-failure")
    } else { "other-outcome" };
    eprintln!("LSF_GO_DIAG_OUTCOME {kind}");
    f.idle().await;
    eprintln!("LSF_GO_DIAG_STAGE idle");
    assert!(matches!(receipt.outcome, ActivationOutcome::Succeeded(_)), "private GC diagnostic trapped");
}
'''
    changed[PATHS[2]] = text[:begin] + focused + text[end:]
    overlays, identities = [], {}
    for name, before in originals.items():
        private = output / 'private-source' / name
        private.parent.mkdir(parents=True, exist_ok=True)
        private.write_text(changed[name], encoding='utf-8')
        identities[name] = {'originalDigest': digest(before), 'privateDigest': digest(private.read_bytes())}
        overlays.append((private, root / name))
    return identities, overlays


def frames_from_output(data: bytes) -> list[dict]:
    frames = []
    for line in data.decode('utf-8', errors='replace').splitlines():
        if not line.startswith('LSF_GO_WASM_FRAME '):
            continue
        value = json.loads(line[len('LSF_GO_WASM_FRAME '):])
        if (not isinstance(value, dict) or set(value) != {'function', 'functionIndex', 'functionOffset', 'moduleOffset'}
                or not isinstance(value['function'], str)
                or re.fullmatch(r'[A-Za-z0-9_.$:*()<>\[\]/+\-]{0,160}', value['function']) is None
                or type(value['functionIndex']) is not int or not 0 <= value['functionIndex'] < 2**32
                or any(value[key] is not None and (type(value[key]) is not int or not 0 <= value[key] < 2**64)
                       for key in ('functionOffset', 'moduleOffset')) or len(frames) >= 32):
            raise ValueError('Go-private-frame-observer-output-shape')
        frames.append(value)
    return frames


def execution_metadata(data: bytes) -> dict:
    lines = data.decode('utf-8', errors='replace').splitlines()
    stages = [line.removeprefix('LSF_GO_DIAG_STAGE ') for line in lines
              if line.startswith('LSF_GO_DIAG_STAGE ')]
    require_stages = ('entered', 'prepared', 'invoked', 'idle')
    if stages != list(require_stages[:len(stages)]) or len(stages) > 4:
        raise ValueError('Go-private-frame-observer-stage-shape')
    classifiers = []
    for line in lines:
        if not line.startswith('LSF_GO_DIAG_CLASSIFY '):
            continue
        value = json.loads(line.removeprefix('LSF_GO_DIAG_CLASSIFY '))
        if (set(value) != {'traceAvailable', 'trapAvailable'}
                or any(type(item) is not bool for item in value.values()) or len(classifiers) >= 4):
            raise ValueError('Go-private-frame-observer-classifier-shape')
        classifiers.append(value)
    # Source sites alone distinguish fixture/preparation assertions from guest
    # execution. No panic message, native backtrace or private config is retained.
    sites = sorted(set(re.findall(r'crates/[A-Za-z0-9_/.-]{1,180}\.rs:[0-9]{1,6}:[0-9]{1,6}',
                                 data.decode('utf-8', errors='replace'))))[:8]
    outcomes = [line.removeprefix('LSF_GO_DIAG_OUTCOME ') for line in lines
                if line.startswith('LSF_GO_DIAG_OUTCOME ')]
    if len(outcomes) > 1 or any(value not in {'memory-out-of-bounds', 'unreachable-code',
            'integer-division-by-zero', 'other-failure', 'other-outcome'} for value in outcomes):
        raise ValueError('Go-private-frame-observer-outcome-shape')
    return {'stages': stages, 'classifiers': classifiers, 'panicSourceSites': sites, 'outcomes': outcomes}


def u32(raw: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for index in range(5):
        if offset >= len(raw):
            break
        byte = raw[offset]; offset += 1
        value |= (byte & 127) << (7 * index)
        if byte < 128 and value < 2**32:
            return value, offset
    raise ValueError('Go-private-terminal-wasm-integer')


def leb(value: int) -> bytes:
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128); value >>= 7
    result.append(value)
    return bytes(result)


def sections(raw: bytes, header: bytes):
    if not raw.startswith(header) or len(raw) > 16 * 1024 * 1024:
        raise ValueError('Go-private-terminal-wasm-header-or-bound')
    offset, rows = 8, []
    while offset < len(raw):
        kind = raw[offset]; size, begin = u32(raw, offset + 1)
        end = begin + size
        if end > len(raw) or len(rows) >= 128:
            raise ValueError('Go-private-terminal-wasm-section-bound')
        rows.append((kind, raw[begin:end])); offset = end
    return rows


def name(raw: bytes, offset: int) -> tuple[str, int]:
    size, offset = u32(raw, offset)
    if size > 512 or offset + size > len(raw):
        raise ValueError('Go-private-terminal-wasm-name-bound')
    return raw[offset:offset + size].decode('utf-8'), offset + size


def closed_throw_reasons() -> list[dict]:
    with (ROOT / REASONS).open('rb') as stream:
        raw = stream.read(128 * 1024 + 1)
    if len(raw) > 128 * 1024 or digest(raw) != REASONS_DIGEST:
        raise ValueError('Go-private-throw-catalog-preimage')
    record = json.loads(raw)
    rows = record['reasons']
    if (record['schemaVersion'] != 'latent.go.closed-throw-literals.v1'
            or record['goVersion'] != '1.27.2' or not 1 <= len(rows) <= 256):
        raise ValueError('Go-private-throw-catalog-shape')
    for index, row in enumerate(rows, 1):
        value = bytes.fromhex(row['literalHex'])
        if (row['id'] != index or not 1 <= len(value) <= 256
                or digest(value) != row['literalDigest'] or not row['sources']):
            raise ValueError('Go-private-throw-literal-shape')
    if len({row['literalHex'] for row in rows}) != len(rows):
        raise ValueError('Go-private-throw-duplicate-literal')
    return rows


def signed_leb(value: int) -> bytes:
    result = bytearray()
    while True:
        byte = value & 127
        value >>= 7
        if (value == 0 and not byte & 64) or (value == -1 and byte & 64):
            result.append(byte)
            return bytes(result)
        result.append(byte | 128)


def throw_reason_body(rows: list[dict], bit: int, *, candidate: int | None = None) -> bytes:
    if type(bit) is not int or not 0 <= bit < len(rows).bit_length():
        raise ValueError('Go-private-throw-bit-bound')
    if candidate is not None and (type(candidate) is not int or not 1 <= candidate <= len(rows)):
        raise ValueError('Go-private-throw-candidate-bound')
    # The exact authenticated throw body below establishes Go's wasm ABI:
    # global0=SP, incoming string pointer at SP+8 and length at SP+16.
    # Only terminal behavior changes. Every path still traps without returning.
    code = bytearray(b'\x01\x02\x7f')  # two i32 locals, after the PC parameter
    code += b'\x23\0\x29\x03\x08\xa7\x21\x01'  # pointer -> local1
    code += b'\x23\0\x29\x03\x10\xa7\x21\x02'  # length -> local2
    code += b'\x23\0\x29\x03\x08\x20\x01\xad\x51'  # no pointer truncation
    code += b'\x23\0\x29\x03\x10\x42' + signed_leb(256) + b'\x58\x71'
    code += b'\x20\x01\xad\x20\x02\xad\x7c\x3f\0\xad\x42\x10\x86\x58\x71'
    code += b'\x45\x04\x40\0\x0b'  # invalid range -> unknown terminal trap
    for row in rows:
        if (candidate is not None and row['id'] != candidate) or (candidate is None and not row['id'] >> bit & 1):
            continue
        value = bytes.fromhex(row['literalHex'])
        code += b'\x20\x02\x41' + signed_leb(len(value)) + b'\x46\x04\x40'
        comparisons = []
        offset = 0
        while offset + 8 <= len(value):
            chunk = int.from_bytes(value[offset:offset + 8], 'little', signed=True)
            comparisons.append(b'\x20\x01\x29\0' + leb(offset) + b'\x42' + signed_leb(chunk) + b'\x51')
            offset += 8
        while offset < len(value):
            comparisons.append(b'\x20\x01\x2d\0' + leb(offset) + b'\x41' + signed_leb(value[offset]) + b'\x46')
            offset += 1
        code += comparisons[0]
        for comparison in comparisons[1:]:
            code += comparison + b'\x71'
        code += b'\x04\x40\x41\0\x41\0\x6e\x1a\0\x0b\x0b'
    code += b'\0\x0b'  # unmatched / zero bit -> unreachable, never resume
    return bytes(code)


def terminal_component(original: bytes, *, reason_bit: int | None = None,
                       reason_id: int | None = None) -> tuple[bytes, dict]:
    """Replace only two named noreturn Go terminal paths, never normal effects."""
    component = sections(original, b'\0asm\x0d\0\x01\0')
    replacements = {'runtime.throw': b'\0\0\x0b',  # no locals; unreachable; end
                    'runtime.fatal': b'\0\x41\0\x41\0\x6e\x1a\0\x0b'}  # u32 div zero
    if reason_bit is not None and reason_id is not None:
        raise ValueError('Go-private-throw-ambiguous-probe')
    if reason_bit is not None or reason_id is not None:
        replacements['runtime.throw'] = throw_reason_body(closed_throw_reasons(),
            reason_bit if reason_bit is not None else 0, candidate=reason_id)
        # A fatal path during the reason probe has a distinct closed classifier.
        replacements['runtime.fatal'] = (b'\0\x41' + signed_leb(-2147483648)
                                         + b'\x41\x7f\x6d\x1a\0\x0b')
    result, changed = bytearray(original[:8]), []
    for kind, payload in component:
        if kind == 1:
            module = sections(payload, b'\0asm\x01\0\0\0')
            names, imported, imports = {}, None, None
            for section, body in module:
                if section == 2:
                    imports = body
                if section != 0:
                    continue
                label, offset = name(body, 0)
                if label != 'name':
                    continue
                while offset < len(body):
                    sub = body[offset]; size, start = u32(body, offset + 1); end = start + size
                    if end > len(body):
                        raise ValueError('Go-private-terminal-name-section')
                    if sub == 1:
                        count, cursor = u32(body, start)
                        if count > 8192:
                            raise ValueError('Go-private-terminal-function-name-count')
                        for _ in range(count):
                            index, cursor = u32(body, cursor); label, cursor = name(body, cursor)
                            if label in replacements:
                                if label in names:
                                    raise ValueError('Go-private-terminal-duplicate-name')
                                names[label] = index
                        if cursor != end:
                            raise ValueError('Go-private-terminal-function-name-tail')
                    offset = end
            if names:
                if imports is not None:
                    imported, offset = u32(imports, 0)
                    for _ in range(imported):
                        _, offset = name(imports, offset); _, offset = name(imports, offset)
                        if offset >= len(imports) or imports[offset] != 0:
                            raise ValueError('Go-private-terminal-only-function-imports')
                        _, offset = u32(imports, offset + 1)
                    if offset != len(imports):
                        raise ValueError('Go-private-terminal-import-tail')
                if set(names) != set(replacements) or imported is None or changed:
                    raise ValueError('Go-private-terminal-functions-not-unique')
                output = bytearray(payload[:8]); saw_code = False
                for section, body in module:
                    if section == 10:
                        saw_code = True
                        count, offset = u32(body, 0)
                        if count > 8192:
                            raise ValueError('Go-private-terminal-code-count')
                        code = bytearray(leb(count))
                        for index in range(count):
                            size, offset = u32(body, offset); end = offset + size
                            if end > len(body):
                                raise ValueError('Go-private-terminal-code-body')
                            before = body[offset:end]; after = before
                            for label, target in names.items():
                                if target == imported + index:
                                    if ((reason_bit is not None or reason_id is not None) and label == 'runtime.throw'
                                            and digest(before) != THROW_BODY_DIGEST):
                                        raise ValueError('Go-private-throw-ABI-preimage')
                                    after = replacements[label]
                                    changed.append({'function': label, 'functionIndex': target,
                                        'originalBodyDigest': digest(before), 'privateBodyDigest': digest(after)})
                            code.extend(leb(len(after))); code.extend(after); offset = end
                        if offset != len(body):
                            raise ValueError('Go-private-terminal-code-tail')
                        body = bytes(code)
                    output.append(section); output.extend(leb(len(body))); output.extend(body)
                if not saw_code or len(changed) != 2:
                    raise ValueError('Go-private-terminal-code-missing')
                payload = bytes(output)
        result.append(kind); result.extend(leb(len(payload))); result.extend(payload)
    if len(changed) != 2:
        raise ValueError('Go-private-terminal-no-runtime-functions')
    derived = bytes(result)
    return derived, {'originalComponentDigest': digest(original), 'privateComponentDigest': digest(derived),
                     'mutations': changed, 'normalFunctionBodiesPreserved': True,
                     'importsAndAuthorityChanged': False, 'qualification': False}


def terminal_metadata(output: bytes) -> dict:
    # Only the public, closed trap classifier and reviewed mode markers are
    # retained. Native panic messages, errors and backtraces are never exported.
    kinds = sorted(set(re.findall(rb'guest trapped: (memory-out-of-bounds|unreachable-code|integer-division-by-zero|integer-overflow)', output)))
    modes = [int(value) for value in re.findall(rb'go-component-activation-v3 iteration=0 mode=([0-9]{1,2}) consumption=', output)]
    if len(kinds) > 1 or len(modes) > 32:
        raise ValueError('Go-private-terminal-public-classifier-bound')
    return {'trapKinds': [value.decode() for value in kinds], 'completedOrdinaryModes': modes,
            'nativeCaseStarted': bool(re.search(rb'(?m)^running 1 test\r?$', output))}


def ordinary_terminal_diagnostic(fixture, output, record, environment, cargo, remaining_seconds,
                                 *, reason_bit=None, reason_id=None, output_limit=1024 * 1024):
    original = (fixture / 'build/component.wasm').read_bytes()
    derived, mutations = terminal_component(original, reason_bit=reason_bit, reason_id=reason_id)
    suffix = (f'-confirm-{reason_id}' if reason_id is not None
              else '' if reason_bit is None else f'-bit-{reason_bit}')
    private = output / ('terminal-fixture' + suffix)
    for name in ('src/main.go', 'wit/world.wit'):
        target = private / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((fixture / name).read_bytes())
    (private / 'build').mkdir()
    binary = private / 'build/component.wasm'
    binary.write_bytes(derived)
    write_json(private / 'GO-ACTIVATION-COMPILE.json',
               {**record, 'componentDigest': digest(derived), 'failureOnlyTerminalMutation': mutations})
    validator = shutil.which('wasm-tools')
    if not validator:
        raise ValueError('Go-private-terminal-validator-missing')
    # Match the ordinary native fixture's existing OS ownership environment.
    # In particular, do not place a durable policy directory under the build
    # output or a remapped user namespace merely to inspect a guest failure.
    native_environment = dict(environment)
    for name in ('TEMP', 'TMP', 'TMPDIR'):
        native_environment.pop(name, None)
    native_environment['LSF_GO_TIMER_FIXTURE'] = str(private)
    validated = run_bounded_result([validator, 'validate', '--features', 'all', str(binary)],
        ROOT, native_environment, remaining_seconds(), output_limit)
    used = len(validated.stdout) + len(validated.stderr)
    if validated.returncode != 0 or used >= output_limit:
        raise ValueError('Go-private-terminal-derived-component-invalid')
    command = [cargo, '--config', '.cargo/managed-guest.toml', 'test', '--offline', '--locked',
               '-p', 'latent-wasmtime', '--test', 'local_service', 'runtime::go::' + CASE,
               '--', '--ignored', '--exact', '--nocapture']
    result = run_bounded_result(command, ROOT, native_environment, remaining_seconds(), output_limit - used)
    used += len(result.stdout) + len(result.stderr)
    receipt = {**mutations, 'scope': 'failure-only-terminal-component-on-ordinary-native-harness',
        'privateHostSourceOverlay': False, 'exitCode': result.returncode,
        'publicObservation': terminal_metadata(result.stderr + b'\n' + result.stdout),
        'compilerErrorCodes': sorted(set(code.decode() for code in re.findall(rb'error\[(E[0-9]{4})\]', result.stderr)))[:16],
        'acceptanceFailure': 'unchanged', 'rawNativeBacktraceRetained': False}
    if (fixture / 'build/component.wasm').read_bytes() != original:
        raise ValueError('Go-private-terminal-original-component-mutated')
    write_json(output / ('GO-PRIVATE-TERMINAL' + suffix + '.json'), receipt)
    return receipt, used


def known_throw_diagnostic(fixture, output, record, environment, cargo, remaining_seconds, terminal, used):
    rows = closed_throw_reasons()
    observation = terminal['publicObservation']
    result = {'scope': 'failure-only-closed-runtime-literal-comparison', 'qualification': False,
              'catalogDigest': REASONS_DIGEST, 'throwAbiBodyDigest': THROW_BODY_DIGEST,
              'rawGuestMessageRetained': False, 'acceptanceFailure': 'unchanged', 'bits': [],
              'baselineCauseProven': False, 'bitRunsSameCauseProven': False,
              'independentCallerEvidenceRequired': True}
    if not observation['nativeCaseStarted'] or observation['trapKinds'] != ['unreachable-code']:
        result['status'] = 'not-the-known-throw-terminal'
        return result, used
    selected = 0
    for bit in range(len(rows).bit_length()):
        if used >= 1024 * 1024:
            raise ValueError('Go-private-throw-diagnostic-output-budget')
        probe, count = ordinary_terminal_diagnostic(fixture, output, record, environment, cargo,
            remaining_seconds, reason_bit=bit, output_limit=1024 * 1024 - used)
        used += count
        public = probe['publicObservation']
        kinds = public['trapKinds']
        result['bits'].append({'bit': bit, 'componentDigest': probe['privateComponentDigest'],
                               'trapKinds': kinds, 'nativeCaseStarted': public['nativeCaseStarted']})
        if (not public['nativeCaseStarted'] or probe['compilerErrorCodes']
                or public['completedOrdinaryModes'] != observation['completedOrdinaryModes']
                or kinds not in (['unreachable-code'], ['integer-division-by-zero'])):
            result['status'] = 'inconclusive-control-divergence'
            break
        if kinds == ['integer-division-by-zero']:
            selected |= 1 << bit
    else:
        result['status'] = 'candidate-selected' if 1 <= selected <= len(rows) else 'unknown-literal'
        if result['status'] == 'candidate-selected':
            # Separate exact full-literal confirmation prevents mixed bit
            # observations from assigning a reason during a nondeterministic race.
            if used >= 1024 * 1024:
                raise ValueError('Go-private-throw-diagnostic-output-budget')
            probe, count = ordinary_terminal_diagnostic(fixture, output, record, environment, cargo,
                remaining_seconds, reason_id=selected, output_limit=1024 * 1024 - used)
            used += count
            public = probe['publicObservation']
            result['confirmation'] = {'componentDigest': probe['privateComponentDigest'],
                'trapKinds': public['trapKinds'], 'nativeCaseStarted': public['nativeCaseStarted']}
            if (not public['nativeCaseStarted'] or probe['compilerErrorCodes']
                    or public['completedOrdinaryModes'] != observation['completedOrdinaryModes']
                    or public['trapKinds'] != ['integer-division-by-zero']):
                result['status'] = 'candidate-not-confirmed'
            else:
                row = rows[selected - 1]
                result['status'] = 'candidate-supported-by-fresh-confirmation'
                result['confirmedCandidate'] = {key: row[key] for key in ('id', 'literalDigest', 'sources')}
    write_json(output / 'GO-PRIVATE-THROW-REASON.json', result)
    return result, used


def diagnose(fixture: Path, output: Path) -> dict:
    deadline = time.monotonic() + 600
    def remaining_seconds():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('Go-private-terminal-diagnostic-budget-exhausted')
        return remaining
    recipe = Path(__file__).read_bytes()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    fixture = fixture.resolve(strict=True)
    record = json.loads((fixture / 'GO-ACTIVATION-COMPILE.json').read_bytes())
    component = fixture / 'build/component.wasm'
    if (record['profile'] != 'go-component-activation-v3' or record['fixture'] != 'timers'
            or record['componentDigest'] != digest(component.read_bytes())):
        raise ValueError('Go-private-frame-observer-component-identity')
    identities, overlays = overlay_sources(ROOT, output)
    sandbox, cargo = shutil.which('bwrap'), shutil.which('cargo')
    if not sandbox or not cargo or sys.platform != 'linux':
        raise ValueError('Go-private-frame-observer-requires-Linux-existing-tools')
    # Read-only file binds give only this process a private source view at the
    # original cache paths. Production files are never rewritten or copied in
    # full, and registry/dependency compilation is reused. This job never saves
    # the subsequently diagnostic target cache, nor runs acceptance after it.
    command = [sandbox, '--unshare-all', '--die-with-parent', '--new-session', '--bind', '/', '/',
               '--proc', '/proc', '--dev', '/dev']
    for private, original in overlays:
        command += ['--ro-bind', str(private), str(original)]
    command += ['--chdir', str(ROOT), cargo, '--config', '.cargo/managed-guest.toml', 'test',
                '--offline', '--locked', '-p', 'latent-wasmtime', '--test', 'local_service',
                'runtime::go::' + CASE, '--', '--ignored', '--exact', '--nocapture']
    environment = build_environment(output)
    environment.update(LSF_GUEST_SDK_LANGUAGE='go', LSF_GO_TIMER_FIXTURE=str(fixture),
        CARGO_INCREMENTAL='0', CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0',
        CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true', CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',
        CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true', CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
    for key in ('CARGO_TARGET_DIR',):
        if key in os.environ:
            environment[key] = os.environ[key]
    terminal, used = ordinary_terminal_diagnostic(fixture, output, record, environment, cargo, remaining_seconds)
    reason, used = known_throw_diagnostic(fixture, output, record, environment, cargo,
                                         remaining_seconds, terminal, used)
    if used >= 1024 * 1024:
        raise ValueError('Go-private-terminal-diagnostic-output-budget-exhausted')
    result = run_bounded_result(command, ROOT, environment, remaining_seconds(), 1024 * 1024 - used)
    frames = frames_from_output(result.stderr + b'\n' + result.stdout)
    for name, identity in identities.items():
        if digest((ROOT / name).read_bytes()) != identity['originalDigest']:
            raise ValueError('Go-private-frame-observer-original-source-mutated')
    if digest(component.read_bytes()) != record['componentDigest']:
        raise ValueError('Go-private-frame-observer-component-mutated')
    if Path(__file__).read_bytes() != recipe:
        raise ValueError('Go-private-terminal-recipe-mutated')
    observation = {'formatVersion': 1, 'qualification': False, 'scope': 'failure-only-private-source-overlay',
        'observerRecipeDigest': digest(recipe),
        'mode': 9, 'componentDigest': record['componentDigest'], 'sourceDigest': record['sourceDigest'],
        'preparedRecordDigest': digest((fixture / 'GO-ACTIVATION-COMPILE.json').read_bytes()),
        'sourceOverlays': identities, 'originalSourceUnchanged': True, 'diagnosticExitCode': result.returncode,
        'nativeCaseStarted': bool(re.search(rb'(?m)^running 1 test\r?$', result.stdout)),
        'compilerErrorCodes': sorted(set(code.decode() for code in re.findall(rb'error\[(E[0-9]{4})\]', result.stderr)))[:16],
        'executionMetadata': execution_metadata(result.stderr + b'\n' + result.stdout),
        'frames': frames, 'rawNativeBacktraceRetained': False, 'acceptanceFailure': 'unchanged',
        'terminalDiagnostic': terminal, 'throwReasonDiagnostic': reason}
    write_json(output / 'GO-PRIVATE-FRAMES-initial.json', observation)
    if 'invoked' not in observation['executionMetadata']['stages']:
        observation['privateFramesStatus'] = 'not-run-before-guest-invocation'
        write_json(output / 'GO-PRIVATE-FRAMES.json', observation)
        return observation
    if Path(__file__).read_bytes() != recipe:
        raise ValueError('Go-private-terminal-recipe-mutated')
    write_json(output / 'GO-PRIVATE-FRAMES.json', observation)
    return observation


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(diagnose(args.fixture, args.output)))
