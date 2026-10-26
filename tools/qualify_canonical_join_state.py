"""Execute four private queue owners and seven affected/new actual canonical cases."""
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

BRANCH = 'feat/sdk-736-event-queue-20261026'
WORKFLOW = '.github/workflows/canonical-join-state.yml'
PREFIX = 'runtime::component::concurrent::work_queue::tests::'
PRIVATE_CASES = tuple(PREFIX + name for name in (
    'queue_exact_layout_refusal_and_unused_slot_refund_before_effects',
    'queue_fifo_promotion_retention_and_none_keep_original_order',
    'queue_confirmation_unwind_and_value_drop_precede_original_refund',
    'queue_value_unwind_retains_same_node_and_remaining_chain_charges',
))
CANONICAL_PREFIX = 'host::join_state_tests::canonical_'
CANONICAL_LOCAL = {
    'join_state_first_poll_refusal_and_same_budget_fresh_store': (2,),
    'call_future_first_poll_refusal_and_same_budget_fresh_store': (3,),
    'pending_future_first_poll_refusal_and_same_budget_fresh_store': (4,),
    'worker_function_first_poll_refusal_and_same_budget_fresh_store': (5,),
    'completion_queue_node_refusal_and_same_budget_fresh_store': (6,),
    'push_future_queue_node_refusal_and_same_budget_fresh_store': (7,),
    'upstream_queue_nodes_refuse_before_guest_and_same_budget_fresh_store': (1, 2),
}
CANONICAL_CASES = tuple(CANONICAL_PREFIX + name for name in CANONICAL_LOCAL)
FEATURES = ('component-model,component-model-async,cranelift,pooling-allocator,'
    'runtime,std,wit-parser,gc,gc-drc,cache,threads,coredump')


def require(value, reason):
    if not value:
        raise ValueError('canonical-queue-nodes-' + reason)


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
    require(len(queue) == 1 and len(join) == 1, 'two-exact-compiled-layouts')
    size, alignment = map(int, queue[0])
    require(1 <= alignment <= size <= 4096 and alignment & (alignment - 1) == 0
        and size % alignment == 0 and 1 <= int(join[0]) <= 4096, 'compiled-layout-shapes')
    return {'queueEntryBytes': size, 'queueEntryAlignment': alignment,
        'joinStateBytes': int(join[0])}


def canonical_markers(raw, case, layouts):
    leaf = case.removeprefix(CANONICAL_PREFIX)
    require(case in CANONICAL_CASES, 'fixed-canonical-case')
    upstream = leaf.startswith('upstream_')
    scope = 'upstream' if upstream else 'host'
    expected = CANONICAL_LOCAL[leaf]
    rows = re.findall(rb'^LSF_CANONICAL_QUEUE_SEQUENCE_V1 scope=(host|upstream) '
        rb'local-owner=(\d+) global-request=(\d+) prefix-queue-nodes=(\d+) '
        rb'bytes=(\[[0-9, ]{1,192}\])$', raw, re.M)
    require(len(rows) == len(expected), 'exact-observed-sequence-count')
    observations = []
    for row, local in zip(rows, expected):
        global_request = local if upstream else local + 2
        prefix = 0 if upstream else 2
        require(row[:4] == (scope.encode(), str(local).encode(),
            str(global_request).encode(), str(prefix).encode()), 'local-global-owner-identity')
        sizes = json.loads(row[4])
        require(isinstance(sizes, list) and len(sizes) == global_request
            and all(type(size) is int and 1 <= size <= 4096 for size in sizes), 'bounded-observed-layouts')
        require(sizes[:min(2, global_request)]
            == [layouts['queueEntryBytes']] * min(2, global_request), 'actual-upstream-entry-layouts')
        if not upstream:
            require(sizes[3] == layouts['joinStateBytes'], 'actual-original-cell-layout')
            if local >= 6:
                require(sizes[7] == layouts['queueEntryBytes'], 'actual-completion-entry-layout')
            if local == 7:
                require(sizes[8] == layouts['queueEntryBytes'], 'actual-push-future-entry-layout')
        marker = (f'LSF_CANONICAL_QUEUE_V1 scope={scope} refusal=memory-bytes '
            f'local-owner={local} global-request={global_request} prefix-queue-nodes={prefix} '
            'before-poll=true fresh=42 stores=2').encode()
        require(raw.splitlines().count(marker) == 1, 'exact-refusal-and-same-budget-fresh-marker')
        observations.append({'scope': scope, 'localOwner': local,
            'globalRequest': global_request, 'prefixQueueNodes': prefix, 'observedBytes': sizes})
    final = b'LSF_CANONICAL_UPSTREAM_QUEUE_V1 scenarios=2 before-guest=true fresh=42 stores=4'
    require(raw.splitlines().count(final) == int(upstream), 'upstream-before-guest-cleanup-and-fresh')
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
    receipt = {'schemaVersion': 'lsf.canonical-queue-nodes.v1', 'status': 'in-progress',
        'sourceRevision': revision, 'privateCases': list(PRIVATE_CASES),
        'canonicalCases': list(CANONICAL_CASES), 'observations': [], 'fullCostModelQualified': False,
        'fullVendorSuiteExecuted': False, 'fullRuntimeSuiteExecuted': False,
        'signedJavaScriptExecuted': False, 'compilerImplicitInputsAttested': False,
        'hermetic': False, 'scope': 'exact scheduler queue nodes with pre-effect preparation and same-node transfer; four private and seven affected/new actual cases only; not allocator/RSS, FuturesUnordered nodes, other collections, transitive backing, Legacy stream closure Box or whole-runtime qualification', 'limits': {'overallSeconds': 2400, 'buildCommandSeconds': 900,
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

        receipt['stage'] = 'build-four-private-controls'
        commands.command_seconds = 895
        commands.run('build-private-controls', tools['cargo'], 'test', '--manifest-path',
            'crates/vendor/wasmtime/Cargo.toml', '--locked', '--lib', '--no-default-features',
            '--features', FEATURES, '--no-run', '--message-format=json')
        private_suite = artifacts.Suite('crates/vendor/wasmtime/Cargo.toml', 'wasmtime',
            'src/lib.rs', PREFIX + 'queue_', frozenset(PRIVATE_CASES), False)
        private = artifacts.read_inventory(logs / 'logs/00-build-private-controls.stdout.txt',
            ROOT, private_suite, target=target)
        receipt['privateExecutable'] = file_identity(private.executable, 'wasmtime-private-controls',
            512 * 1024**2)
        commands.environment = runtime_environment(private, 'private')
        commands.command_seconds = 25
        listed = commands.run('list-four-private-controls', private.executable,
            private_suite.filter, '--list')
        require(len(listed) <= artifacts.MAX_LIST_BYTES, 'private-list-bound')
        artifacts.validate_listing(listed, private_suite)
        for index, case in enumerate(PRIVATE_CASES):
            receipt['stage'] = case
            commands.command_seconds = 55
            raw = commands.run('private-case-' + str(index), private.executable, case,
                '--exact', '--show-output', '--test-threads=1')
            receipt['observations'].append(result(raw, case))
            if index == 0:
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
        require(contract['minimumCases'] == 492
            and set(CANONICAL_CASES) <= set(contract['expectedCases'])
            and set(CANONICAL_CASES) <= set(contract['expectedIgnored']), 'actual-canonical-contract')
        canonical_suite = artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'latent_wasmtime',
            'src/lib.rs', CANONICAL_PREFIX, frozenset(CANONICAL_CASES), True)
        canonical = artifacts.read_inventory(logs / f'logs/{ordinal:02d}-{stage}.stdout.txt',
            ROOT, canonical_suite, target=target)
        receipt['canonicalExecutable'] = file_identity(canonical.executable,
            'latent-wasmtime-canonical-control', 512 * 1024**2)
        commands.environment = runtime_environment(canonical, 'canonical')
        commands.environment.update(LSF_TEST_WORK_QUEUE_LAYOUT=str(layouts['queueEntryBytes']),
            LSF_TEST_JOIN_STATE_LAYOUT=str(layouts['joinStateBytes']))
        commands.command_seconds = 25
        listed = commands.run('list-seven-canonical-controls', canonical.executable,
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
            executed=[*PRIVATE_CASES, *CANONICAL_CASES], ignored=[])
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
