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

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.rust_capsule_project import ROOT, digest, write_json

CASE = 'signed_standard_timers_contexts_and_rearm_keep_original_heap_owners'
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
    assert_eq!(std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(), Ok("go"));
    let root = tempfile::tempdir().unwrap();
    let f = prepare_checkpoint_fixture(root.path(), "LSF_GO_TIMER_FIXTURE", "go-component-activation-v3").await;
    let receipt = f.manager.start(f.request("private-go-gc-frame-diagnostic", 9)).unwrap().await;
    f.idle().await;
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


def diagnose(fixture: Path, output: Path) -> dict:
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
    result = run_bounded_result(command, ROOT, environment, 600, 1024 * 1024)
    frames = frames_from_output(result.stderr + b'\n' + result.stdout)
    for name, identity in identities.items():
        if digest((ROOT / name).read_bytes()) != identity['originalDigest']:
            raise ValueError('Go-private-frame-observer-original-source-mutated')
    if digest(component.read_bytes()) != record['componentDigest']:
        raise ValueError('Go-private-frame-observer-component-mutated')
    observation = {'formatVersion': 1, 'qualification': False, 'scope': 'failure-only-private-source-overlay',
        'mode': 9, 'componentDigest': record['componentDigest'], 'sourceDigest': record['sourceDigest'],
        'preparedRecordDigest': digest((fixture / 'GO-ACTIVATION-COMPILE.json').read_bytes()),
        'sourceOverlays': identities, 'originalSourceUnchanged': True, 'diagnosticExitCode': result.returncode,
        'nativeCaseStarted': bool(re.search(rb'(?m)^running 1 test\r?$', result.stdout)),
        'compilerErrorCodes': sorted(set(code.decode() for code in re.findall(rb'error\[(E[0-9]{4})\]', result.stderr)))[:16],
        'frames': frames, 'rawNativeBacktraceRetained': False, 'acceptanceFailure': 'unchanged'}
    write_json(output / 'GO-PRIVATE-FRAMES.json', observation)
    return observation


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(diagnose(args.fixture, args.output)))
