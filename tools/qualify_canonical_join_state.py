"""Execute only the four remaining v16 actual host cases after the physical-peak oracle repair."""
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
CANONICAL_PREFIX = 'host::join_state_tests::canonical_'

CANONICAL_LOCAL = {
    'join_state_first_poll_refusal_and_same_budget_fresh_store': (2,),
    'call_future_first_poll_refusal_and_same_budget_fresh_store': (3,),
    'pending_future_first_poll_refusal_and_same_budget_fresh_store': (4,),
    'worker_function_first_poll_refusal_and_same_budget_fresh_store': (5,),
    'completion_queue_node_refusal_and_same_budget_fresh_store': (6,),
    'push_future_queue_node_refusal_and_same_budget_fresh_store': (7,),
    'unordered_initialization_refusal_and_same_budget_fresh_store': (1, 2),
    'unordered_task_first_poll_refusal_and_same_budget_fresh_store': (8,),
}

CANONICAL_CASES = tuple(CANONICAL_PREFIX + name for name in CANONICAL_LOCAL)

MAIN_CASES = (
    'host::native_host_future_tests::actual_host_future_callback_error_is_unchanged_and_its_box_retires',
    'host::native_host_future_tests::actual_host_future_legacy_unaccounted_embedding_keeps_original_scalar_result',
    'host::native_host_future_tests::actual_accessor_spawn_outer_box_refuses_before_run_and_retires_after_pending',
    'host::native_host_future_tests::actual_sync_lower_result_box_refuses_before_poll_and_fresh_budget_reuses',
)
HISTORICAL_405 = {
    'sourceRevision': '405c2e447fc41036e4b7a19ae887f664e050f827',
    'runId': 40305108367, 'jobId': 121512180056,
    'artifactId': 12643330637, 'artifactBytes': 970283,
    'artifactSha256': '96f8916297b3bfd05ce815cc7407b54f430cc315e84fe08f098ba7aa85c3c23e',
    'runConclusion': 'failure',
    'passedCasesNotReexecuted': (
        'runtime::component::concurrent::sync_result::tests::sync_result_refuses_before_value_and_unbuilt_reservation_refunds',
        'runtime::component::concurrent::sync_result::tests::sync_result_overaligned_move_out_refunds_before_returned_value_drop',
        'runtime::component::concurrent::sync_result::tests::sync_result_wrong_type_preserves_envelope_and_abandon_drops_value_before_owner',
        'runtime::component::concurrent::sync_result::tests::sync_result_confirmation_unwind_has_installed_physical_cleanup',
        'runtime::component::concurrent::sync_result::tests::sync_result_destructor_unwind_retains_same_original_charge',
        'runtime::component::concurrent::sync_result::tests::sync_result_zst_and_none_keep_legacy_boxes_without_native_admission',
        'host::native_host_future_tests::actual_host_future_typed_and_dynamic_boxes_retain_original_memory_while_pending',
        'host::native_host_future_tests::actual_host_future_refusal_preserves_original_error_and_fresh_budget_reuse',
        'host::native_host_future_tests::actual_host_future_cancellation_cannot_credit_another_live_store',
    ),
    'failedCase': 'host::native_host_future_tests::actual_host_future_callback_error_is_unchanged_and_its_box_retires',
}


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



def layout_witness(raw):
    queue = re.findall(rb'^LSF_WORK_QUEUE_LAYOUT_V1 bytes=(\d+) align=(\d+)$', raw, re.M)
    join = re.findall(rb'^LSF_JOIN_STATE_LAYOUT_V1 bytes=(\d+)$', raw, re.M)
    headers = re.findall(rb'^LSF_FUTURES_BACKING_LAYOUT_V1 task-bytes=(\d+) task-align=(\d+) '
        rb'ready-queue-bytes=(\d+) ready-queue-align=(\d+)$', raw, re.M)
    require(len(queue) == len(join) == len(headers) == 1, 'four-exact-compiled-layouts')
    size, alignment = map(int, queue[0])
    task, task_alignment, ready, ready_alignment = map(int, headers[0])
    for value, align in ((size, alignment), (task, task_alignment), (ready, ready_alignment)):
        require(1 <= align <= value <= 4096 and align & (align - 1) == 0
            and value % align == 0, 'compiled-layout-shapes')
    require(1 <= int(join[0]) <= 4096, 'compiled-cell-layout')
    return {'queueEntryBytes': size, 'queueEntryAlignment': alignment,
        'joinStateBytes': int(join[0]), 'taskHeaderBytes': task,
        'taskHeaderAlignment': task_alignment, 'readyQueueHeaderBytes': ready,
        'readyQueueHeaderAlignment': ready_alignment}


def canonical_markers(raw, case, layouts):
    leaf = case.removeprefix(CANONICAL_PREFIX)
    require(case in CANONICAL_CASES, 'fixed-canonical-case')
    initialization = leaf.startswith('unordered_initialization_')
    scope = 'initialization' if initialization else 'host'
    expected = CANONICAL_LOCAL[leaf]
    rows = re.findall(rb'^LSF_CANONICAL_UNORDERED_SEQUENCE_V1 scope=(host|initialization) '
        rb'local-owner=(\d+) global-request=(\d+) prefix-queue-nodes=(\d+) '
        rb'prefix-shared-headers=(\d+) bytes=(\[[0-9, ]{1,192}\])$', raw, re.M)
    require(sum(line.startswith(b'LSF_CANONICAL_UNORDERED_SEQUENCE_V1 ')
        for line in raw.splitlines()) == len(rows), 'no-unknown-sequence-shape')
    require(len(rows) == len(expected), 'exact-observed-sequence-count')
    require(sum(line.startswith(b'LSF_CANONICAL_UNORDERED_V1 ')
        for line in raw.splitlines()) == len(expected), 'exact-result-marker-count')
    observations = []
    for row, local in zip(rows, expected):
        global_request = local + (2 if initialization else 4)
        shared_prefix = 0 if initialization else 2
        require(row[:5] == (scope.encode(), str(local).encode(), str(global_request).encode(),
            b'2', str(shared_prefix).encode()), 'local-global-owner-identity')
        sizes = json.loads(row[5])
        require(type(sizes) is list and len(sizes) == global_request
            and all(type(value) is int and 1 <= value <= 4096 for value in sizes), 'bounded-observed-layouts')
        require(sizes[:2] == [layouts['queueEntryBytes']] * 2, 'actual-upstream-entries')
        require(sizes[2] == layouts['taskHeaderBytes'], 'actual-stub-header')
        if global_request >= 4:
            require(sizes[3] == layouts['readyQueueHeaderBytes'], 'actual-ready-header')
        if not initialization:
            require(sizes[5] == layouts['joinStateBytes'], 'actual-original-cell-layout')
            if local >= 6:
                require(sizes[9] == layouts['queueEntryBytes'], 'actual-completion-entry-layout')
            if local >= 7:
                require(sizes[10] == layouts['queueEntryBytes'], 'actual-push-future-entry-layout')
            if local == 8:
                require(sizes[11] == layouts['taskHeaderBytes'], 'actual-prepared-task-header')
        marker = (f'LSF_CANONICAL_UNORDERED_V1 scope={scope} refusal=memory-bytes '
            f'local-owner={local} global-request={global_request} prefix-queue-nodes=2 '
            f'prefix-shared-headers={shared_prefix} before-poll=true fresh=42 stores=2').encode()
        require(raw.splitlines().count(marker) == 1, 'exact-refusal-and-same-budget-fresh-marker')
        observations.append({'scope': scope, 'localOwner': local, 'globalRequest': global_request,
            'prefixQueueNodes': 2, 'prefixSharedHeaders': shared_prefix, 'observedBytes': sizes})
    final = b'LSF_CANONICAL_FUTURES_INITIALIZATION_V1 scenarios=2 before-guest=true fresh=42 stores=4'
    require(raw.splitlines().count(final) == int(initialization), 'initialization-before-guest-and-fresh')
    return observations


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
        'sourceRevision': revision, 'privateCases': [],
        'mainCases': list(MAIN_CASES), 'observations': [], 'fullCostModelQualified': False,
        'fullVendorSuiteExecuted': False, 'fullRuntimeSuiteExecuted': False,
        'signedJavaScriptExecuted': False, 'compilerImplicitInputsAttested': False,
        'hermetic': False,
        'scope': 'four remaining actual callback-error/None/Accessor/result-refusal cases only; original guards and exact backing, not transitive results, streams, allocator/RSS or whole runtime',
        'historicalNotReexecuted': 'v15 twenty-control result and nine passed controls of failed405 retain their original sources/receipts',
        'priorV16Attempt': HISTORICAL_405,
        'limits': {'overallSeconds': 2400, 'buildCommandSeconds': 900,
            'caseProcessSeconds': 60, 'listProcessSeconds': 30, 'cleanupReserveSeconds': 5},
        'actualHostBudget': {'cpuFuel': 1_000_000_000, 'memoryBytes': 1024**2,
            'wallTimeMilliseconds': 5000,
            'scope': 'original native_table_tests::budget for accounted host cases; None does not claim this ledger'}}
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

        receipt['stage'] = 'build-four-remaining-actual-host-controls'
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
        # Same already-built root libtest binary, exact four remaining cases only. Each
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
        require(len(commands.records) == 10 and len(receipt['observations']) == 4,
            'exact-bounded-programme-count')
        require(time.monotonic() < commands.deadline, 'overall-deadline')
        require(source_inputs() == before and source.verify() == checked, 'final-source')
        require(file_identity(native.executable, 'latent-wasmtime-actual-host-controls',
            512 * 1024**2) == receipt['nativeExecutable'], 'final-executable')
        require([file_identity(tools[name], name) for name in sorted(tools)] == pins,
            'final-tools')
        artifacts.require_source(ROOT, revision, environment)
        require(time.monotonic() < commands.deadline, 'final-deadline')
        receipt.update(status='passed', sourceAfter=before, sourceUnchanged=True,
            executed=list(MAIN_CASES), ignored=[])
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
