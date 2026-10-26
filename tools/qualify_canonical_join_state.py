"""Execute six paid-unordered owners, eight canonical cases and six affected normal cases."""
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

BRANCH = 'feat/sdk-736-futures-unordered-20261026'
WORKFLOW = '.github/workflows/canonical-join-state.yml'
PREFIX = 'runtime::component::concurrent::host_futures::tests::'
PRIVATE_CASES = tuple(PREFIX + name for name in (
    'paid_header_exact_layout_refusal_confirmation_and_last_weak_refund',
    'paid_header_raw_token_and_destructor_unwind_retain_same_charge',
    'paid_unordered_escaped_waker_keeps_task_and_last_weak_queue_backing',
    'paid_unordered_prepared_unused_and_wake_publish_make_no_new_admission',
    'paid_unordered_lazy_each_initialization_refusal_and_none_keep_original',
    'paid_unordered_future_unwind_retains_original_queue_and_task_charges',
))
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
# Registration/listing still authenticates this unmodified old upstream case;
# it is NOT reexecuted or credited as a new result in this programme.
UNSELECTED_CANONICAL = CANONICAL_PREFIX + 'upstream_queue_nodes_refuse_before_guest_and_same_budget_fresh_store'
CANONICAL_LISTED = (*CANONICAL_CASES, UNSELECTED_CANONICAL)
MAIN_CASES = (
    'host::native_host_future_tests::actual_host_future_typed_and_dynamic_boxes_retain_original_memory_while_pending',
    'host::native_host_future_tests::actual_host_future_refusal_preserves_original_error_and_fresh_budget_reuse',
    'host::native_host_future_tests::actual_host_future_callback_error_is_unchanged_and_its_box_retires',
    'host::native_context_reply_tests::actual_context_reply_original_refusal_keeps_exact_error_and_fresh_same_grant',
    'host::native_host_future_tests::actual_host_future_cancellation_cannot_credit_another_live_store',
    'host::native_store_tests::actual_cancelled_lift_preserves_store_owners_and_cannot_credit_another_live_store',
)

FEATURES = ('component-model,component-model-async,cranelift,pooling-allocator,'
    'runtime,std,wit-parser,gc,gc-drc,cache,threads,coredump')


def require(value, reason):
    if not value:
        raise ValueError('canonical-unordered-backing-' + reason)


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
    # run_bounded_result may spend five additional seconds reaping its child.
    # Reserve that time INSIDE every declared command and overall wall cap.
    commands = Commands(ROOT, logs, environment, deadline_seconds=2395, command_seconds=895)
    receipt = {'schemaVersion': 'lsf.canonical-unordered-backing.v1', 'status': 'in-progress',
        'sourceRevision': revision, 'privateCases': list(PRIVATE_CASES),
        'canonicalCases': list(CANONICAL_CASES), 'listedButNotExecuted': [UNSELECTED_CANONICAL],
        'mainCases': list(MAIN_CASES), 'observations': [], 'fullCostModelQualified': False,
        'fullVendorSuiteExecuted': False, 'fullRuntimeSuiteExecuted': False,
        'signedJavaScriptExecuted': False, 'compilerImplicitInputsAttested': False,
        'hermetic': False, 'scope': 'private sized unordered task/stub/ready backing through last weak; six new private, eight canonical and six affected normal cases; exact before-effect owners only, not allocator/RSS, Legacy Boxes, other collections, transitive backing or whole runtime', 'limits': {'overallSeconds': 2400, 'buildCommandSeconds': 900,
            'caseProcessSeconds': 60, 'listProcessSeconds': 30,
            'cleanupReserveSeconds': 5},
        'activationLimits': {'cpuFuel': 1_000_000_000, 'memoryBytes': 64 * 1024**2,
            'wallTimeMilliseconds': 120_000}}
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
            # Reuse the normal artifact loader while retaining its bounded Rust
            # target-libdir probe in this SAME overall command owner.
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

        receipt['stage'] = 'build-six-private-controls'
        commands.command_seconds = 895
        commands.run('build-private-controls', tools['cargo'], 'test', '--manifest-path',
            'crates/vendor/wasmtime/Cargo.toml', '--locked', '--lib', '--no-default-features',
            '--features', FEATURES, '--no-run', '--message-format=json')
        private_suite = artifacts.Suite('crates/vendor/wasmtime/Cargo.toml', 'wasmtime',
            'src/lib.rs', PREFIX + 'paid_', frozenset(PRIVATE_CASES), False)
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
            if index == 4:
                layouts = layout_witness(raw)
                receipt['compiledLayouts'] = layouts

        receipt['stage'] = 'build-actual-canonical-control'
        commands.environment = environment
        commands.command_seconds = 895
        stage = 'build-canonical-control'
        ordinal = len(commands.records)
        commands.run(stage, tools['cargo'], 'test', '-p', 'latent-wasmtime', '--locked',
            '--lib', '--no-run', '--message-format=json')
        contract, = [row for row in registry.load()['suites']
            if row['id'] == 'latent-wasmtime.lib.latent-wasmtime']
        require(contract['minimumCases'] == 494
            and set(CANONICAL_LISTED) <= set(contract['expectedCases'])
            and set(CANONICAL_LISTED) <= set(contract['expectedIgnored'])
            and set(MAIN_CASES) <= set(contract['expectedCases'])
            and not set(MAIN_CASES) & set(contract['expectedIgnored']), 'actual-canonical-contract')
        canonical_suite = artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'latent_wasmtime',
            'src/lib.rs', CANONICAL_PREFIX, frozenset(CANONICAL_LISTED), True)
        canonical = artifacts.read_inventory(logs / f'logs/{ordinal:02d}-{stage}.stdout.txt',
            ROOT, canonical_suite, target=target)
        receipt['canonicalExecutable'] = file_identity(canonical.executable,
            'latent-wasmtime-canonical-control', 512 * 1024**2)
        commands.environment = runtime_environment(canonical, 'canonical')
        commands.environment.update(LSF_TEST_WORK_QUEUE_LAYOUT=str(layouts['queueEntryBytes']),
            LSF_TEST_JOIN_STATE_LAYOUT=str(layouts['joinStateBytes']),
            LSF_TEST_FUTURES_TASK_LAYOUT=str(layouts['taskHeaderBytes']),
            LSF_TEST_FUTURES_READY_LAYOUT=str(layouts['readyQueueHeaderBytes']))
        commands.command_seconds = 25
        listed = commands.run('list-nine-known-canonical-controls', canonical.executable,
            CANONICAL_PREFIX, '--ignored', '--list')
        require(len(listed) <= artifacts.MAX_LIST_BYTES, 'canonical-list-bound')
        artifacts.validate_listing(listed, canonical_suite)
        for index, case in enumerate(CANONICAL_CASES):
            receipt['stage'] = case
            commands.command_seconds = 55
            raw = commands.run('canonical-case-' + str(index), canonical.executable,
                case, '--exact', '--ignored', '--show-output', '--test-threads=1')
            observation = result(raw, case)
            observation['admissions'] = canonical_markers(raw, case, layouts)
            receipt['observations'].append(observation)
        # SAME already-built native libtest binary. These six existing cases
        # have source-affected cold/warm allocation premises, so execute them;
        # no additional Cargo build or unrelated old programme is selected.
        for index, case in enumerate(MAIN_CASES):
            receipt['stage'] = case
            commands.command_seconds = 25
            listed = commands.run('list-main-case-' + str(index), canonical.executable,
                case, '--exact', '--list')
            require(len(listed) <= artifacts.MAX_LIST_BYTES, 'main-list-bound')
            suite = artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'latent_wasmtime',
                'src/lib.rs', case, frozenset((case,)), True)
            artifacts.validate_listing(listed, suite)
            commands.command_seconds = 55
            raw = commands.run('main-case-' + str(index), canonical.executable,
                case, '--exact', '--show-output', '--test-threads=1')
            receipt['observations'].append(result(raw, case))
        require(time.monotonic() < commands.deadline, 'overall-deadline')
        require(source_inputs() == before and source.verify() == checked, 'final-source')
        require(file_identity(private.executable, 'wasmtime-private-controls', 512 * 1024**2)
            == receipt['privateExecutable'] and file_identity(canonical.executable,
                'latent-wasmtime-canonical-control', 512 * 1024**2)
            == receipt['canonicalExecutable'], 'final-executables')
        require([file_identity(tools[name], name) for name in sorted(tools)] == pins,
            'final-tools')
        artifacts.require_source(ROOT, revision, environment)
        require(time.monotonic() < commands.deadline, 'final-deadline')
        receipt.update(status='passed', sourceAfter=before, sourceUnchanged=True,
            executed=[*PRIVATE_CASES, *CANONICAL_CASES, *MAIN_CASES], ignored=[])
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
