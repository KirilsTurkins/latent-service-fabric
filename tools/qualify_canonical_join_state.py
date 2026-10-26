"""Execute six sync-result owners and seven actual outer/result/None host cases."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import tomllib

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import ci_rust_artifacts as artifacts, ci_suite_inventory as registry
from tools import host_codec_wasmtime as source
from tools.build_observation import build_environment, file_identity, resolve_tools
from tools.build_snapshot import SOURCE_ALLOWLIST, SnapshotLimits
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json

BRANCH = 'feat/sdk-736-legacy-host-futures-20261026'
WORKFLOW = '.github/workflows/canonical-join-state.yml'
PREFIX = 'runtime::component::concurrent::sync_result::tests::'
PRIVATE_CASES = tuple(PREFIX + name for name in (
    'sync_result_refuses_before_value_and_unbuilt_reservation_refunds',
    'sync_result_overaligned_move_out_refunds_before_returned_value_drop',
    'sync_result_wrong_type_preserves_envelope_and_abandon_drops_value_before_owner',
    'sync_result_confirmation_unwind_has_installed_physical_cleanup',
    'sync_result_destructor_unwind_retains_same_original_charge',
    'sync_result_zst_and_none_keep_legacy_boxes_without_native_admission',
))
MAIN_CASES = tuple('host::native_host_future_tests::' + name for name in (
    'actual_host_future_typed_and_dynamic_boxes_retain_original_memory_while_pending',
    'actual_host_future_refusal_preserves_original_error_and_fresh_budget_reuse',
    'actual_host_future_cancellation_cannot_credit_another_live_store',
    'actual_host_future_callback_error_is_unchanged_and_its_box_retires',
    'actual_host_future_legacy_unaccounted_embedding_keeps_original_scalar_result',
    'actual_accessor_spawn_outer_box_refuses_before_run_and_retires_after_pending',
    'actual_sync_lower_result_box_refuses_before_poll_and_fresh_budget_reuses',
))

FEATURES = ('component-model,component-model-async,cranelift,pooling-allocator,'
    'runtime,std,wit-parser,gc,gc-drc,cache,threads,coredump')


def require(value, reason):
    if not value:
        raise ValueError('canonical-sync-result-' + reason)


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def source_inputs():
    names = subprocess.check_output(['git', 'ls-files', '-z', '--', *SOURCE_ALLOWLIST],
        cwd=ROOT, timeout=30)
    require(len(names) <= 2 * 1024**2, 'source-path-bound')
    names = [name for name in names.decode().split('\0') if name]
    limits = SnapshotLimits()
    require(100 <= len(names) <= limits.max_entries, 'source-count')
    result, total = {}, 0
    for name in names:
        raw = read_file(ROOT / name, limits.max_file_bytes)
        total += len(raw)
        result[name] = identity(raw)
    require(total <= limits.max_total_bytes, 'source-total')
    result[WORKFLOW] = identity(read_file(ROOT / WORKFLOW, 128 * 1024))
    return dict(sorted(result.items()))


def result(raw, case):
    require(len(raw) <= artifacts.MAX_OUTPUT_BYTES, 'case-output-bound')
    require(re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$', raw, re.M)
        == [case.encode()], 'one-exact-success')
    summaries = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; '
        rb'(\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    require(len(summaries) == 1 and summaries[0][:4] == (b'1', b'0', b'0', b'0')
        and int(summaries[0][4]) <= 10000, 'one-executed-no-skip')
    return {'case': case, 'stdout': identity(raw),
        'passed': 1, 'failed': 0, 'ignored': 0,
        'filteredOut': int(summaries[0][4])}



def qualify(output, revision):
    require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
        and os.environ.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric'
        and os.environ.get('GITHUB_REF_NAME') == BRANCH
        and os.environ.get('GITHUB_EVENT_NAME') == 'push', 'one-exact-hosted-push')
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
        'owned-output')
    output = fresh(output)
    environment = build_environment(output)
    target = ROOT / 'target'
    environment.update(CARGO_TARGET_DIR=str(target), CARGO_INCREMENTAL='0',
        CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0',
        CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true', CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',
        CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true', CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
    logs = output / 'commands'
    logs.mkdir()
    # Five seconds of existing process reaping stay INSIDE every declared cap.
    commands = Commands(ROOT, logs, environment, deadline_seconds=2395, command_seconds=895)
    receipt = {'schemaVersion': 'lsf.canonical-outer-sync-result.v1', 'status': 'in-progress',
        'sourceRevision': revision, 'privateCases': list(PRIVATE_CASES),
        'mainCases': list(MAIN_CASES), 'observations': [], 'fullCostModelQualified': False,
        'fullVendorSuiteExecuted': False, 'fullRuntimeSuiteExecuted': False,
        'signedJavaScriptExecuted': False, 'compilerImplicitInputsAttested': False,
        'hermetic': False,
        'scope': 'six new private sync-result owners plus seven actual sync-lower/Accessor/None cases; original guards and exact backing only, not transitive results, streams, allocator/RSS or whole runtime',
        'historicalNotReexecuted': 'v15 twenty-control qualification retains its original source and receipt',
        'limits': {'overallSeconds': 2400, 'buildCommandSeconds': 900,
            'caseProcessSeconds': 60, 'listProcessSeconds': 30, 'cleanupReserveSeconds': 5},
        'actualHostBudget': {'cpuFuel': 1_000_000_000, 'memoryBytes': 1024**2,
            'wallTimeMilliseconds': 5000,
            'scope': 'original native_table_tests::budget for accounted host cases; private probes and None do not claim this ledger'}}
    try:
        artifacts.require_source(ROOT, revision, environment)
        before = source_inputs()
        receipt['sourceBefore'] = before
        write_json(output / 'source-inputs.json', before)
        checked = source.verify()
        receipt['wasmtimeSource'] = checked
        toolchain = tomllib.loads(read_file(ROOT / 'tools/toolchain.toml', 128 * 1024).decode())
        require(toolchain['rust']['toolchain'] == '1.97.1'
            and toolchain['contracts']['wasm-tools'] == '1.254.0', 'normal-tool-pins')
        tools, pins = resolve_tools(toolchain, ROOT, environment)
        receipt['observedTools'] = pins
        environment.update(RUSTC=str(tools['rustc']), RUSTUP_TOOLCHAIN=toolchain['rust']['toolchain'])

        def runtime_environment(artifact, label):
            def probe(argv, *, cwd, env, timeout, maximum):
                require(argv == ['rustc', '--print', 'target-libdir'] and cwd == ROOT
                    and timeout == 30 and maximum == 4096, 'normal-library-probe')
                commands.command_seconds = 25
                commands.environment = env
                raw = commands.run(label + '-rust-library-path', tools['rustc'], *argv[1:])
                require(len(raw) <= maximum, 'rust-library-output-bound')
                return 0, raw
            return artifacts.cargo_environment(ROOT, artifact, environment,
                target=target, execute=probe)

        receipt['stage'] = 'build-six-sync-result-controls'
        commands.command_seconds = 895
        commands.run('build-private-controls', tools['cargo'], 'test', '--manifest-path',
            'crates/vendor/wasmtime/Cargo.toml', '--locked', '--lib', '--no-default-features',
            '--features', FEATURES, '--no-run', '--message-format=json')
        private_suite = artifacts.Suite('crates/vendor/wasmtime/Cargo.toml', 'wasmtime',
            'src/lib.rs', PREFIX, frozenset(PRIVATE_CASES), False)
        private = artifacts.read_inventory(logs / 'logs/00-build-private-controls.stdout.txt',
            ROOT, private_suite, target=target)
        receipt['privateExecutable'] = file_identity(private.executable, 'wasmtime-private-controls',
            512 * 1024**2)
        commands.environment = runtime_environment(private, 'private')
        commands.command_seconds = 25
        listed = commands.run('list-six-private-controls', private.executable,
            private_suite.filter, '--list')
        require(len(listed) <= artifacts.MAX_LIST_BYTES, 'private-list-bound')
        artifacts.validate_listing(listed, private_suite)
        for index, case in enumerate(PRIVATE_CASES):
            receipt['stage'] = case
            commands.command_seconds = 55
            raw = commands.run('private-case-' + str(index), private.executable, case,
                '--exact', '--show-output', '--test-threads=1')
            receipt['observations'].append(result(raw, case))

        receipt['stage'] = 'build-seven-actual-host-controls'
        commands.environment = environment
        commands.command_seconds = 895
        stage = 'build-actual-host-controls'
        ordinal = len(commands.records)
        commands.run(stage, tools['cargo'], 'test', '-p', 'latent-wasmtime', '--locked',
            '--lib', '--no-run', '--message-format=json')
        contract, = [row for row in registry.load()['suites']
            if row['id'] == 'latent-wasmtime.lib.latent-wasmtime']
        require(contract['minimumCases'] == 496
            and set(MAIN_CASES) <= set(contract['expectedCases'])
            and not set(MAIN_CASES) & set(contract['expectedIgnored']), 'actual-host-contract')
        native_suite = artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'latent_wasmtime',
            'src/lib.rs', 'host::native_host_future_tests::', frozenset(MAIN_CASES), True)
        native = artifacts.read_inventory(logs / f'logs/{ordinal:02d}-{stage}.stdout.txt',
            ROOT, native_suite, target=target)
        receipt['nativeExecutable'] = file_identity(native.executable,
            'latent-wasmtime-actual-host-controls', 512 * 1024**2)
        commands.environment = runtime_environment(native, 'native')
        # Same already-built root libtest binary, exact seven cases only. Each
        # independent listing refuses a missing/ignored/renamed control.
        for index, case in enumerate(MAIN_CASES):
            receipt['stage'] = case
            commands.command_seconds = 25
            listed = commands.run('list-main-case-' + str(index), native.executable,
                case, '--exact', '--list')
            require(len(listed) <= artifacts.MAX_LIST_BYTES, 'main-list-bound')
            suite = artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'latent_wasmtime',
                'src/lib.rs', case, frozenset((case,)), True)
            artifacts.validate_listing(listed, suite)
            commands.command_seconds = 55
            raw = commands.run('main-case-' + str(index), native.executable,
                case, '--exact', '--show-output', '--test-threads=1')
            receipt['observations'].append(result(raw, case))
        require(len(commands.records) == 25 and len(receipt['observations']) == 13,
            'exact-bounded-programme-count')
        require(time.monotonic() < commands.deadline, 'overall-deadline')
        require(source_inputs() == before and source.verify() == checked, 'final-source')
        require(file_identity(private.executable, 'wasmtime-private-controls', 512 * 1024**2)
            == receipt['privateExecutable'] and file_identity(native.executable,
                'latent-wasmtime-actual-host-controls', 512 * 1024**2)
            == receipt['nativeExecutable'], 'final-executables')
        require([file_identity(tools[name], name) for name in sorted(tools)] == pins,
            'final-tools')
        artifacts.require_source(ROOT, revision, environment)
        require(time.monotonic() < commands.deadline, 'final-deadline')
        receipt.update(status='passed', sourceAfter=before, sourceUnchanged=True,
            executed=[*PRIVATE_CASES, *MAIN_CASES], ignored=[])
        write_json(output / 'receipt.json', receipt)
    except BaseException:
        receipt['status'] = 'failed'
        write_json(output / 'FAILED.json', receipt)
        raise
    finally:
        write_json(output / 'commands.json', commands.records)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    args = parser.parse_args()
    qualify(args.output.resolve(), args.source_commit)
