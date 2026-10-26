"""Execute four private pending-continuation controls and one actual canonical budget case."""
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

BRANCH = 'feat/sdk-736-pending-box-20261026'
WORKFLOW = '.github/workflows/canonical-join-state.yml'
PREFIX = 'runtime::component::concurrent::pending_future::tests::'
PRIVATE_CASES = tuple(PREFIX + name for name in (
    'pending_future_refuses_before_input_poll_or_factory_and_ready_refunds_unused',
    'pending_future_same_reservation_keeps_pinned_output_until_physical_drop',
    'pending_future_confirmation_unwind_destroys_output_before_refund',
    'pending_future_destructor_unwind_retains_only_original_charge',
))
CANONICAL_CASE = ('host::join_state_tests::'
    'canonical_pending_future_first_poll_refusal_and_same_budget_fresh_store')
FEATURES = ('component-model,component-model-async,cranelift,pooling-allocator,'
    'runtime,std,wit-parser,gc,gc-drc,cache,threads,coredump')


def require(value, reason):
    if not value:
        raise ValueError('canonical-pending-future-' + reason)


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
    # run_bounded_result may spend five additional seconds reaping its child.
    # Reserve that time INSIDE every declared command and overall wall cap.
    commands = Commands(ROOT, logs, environment, deadline_seconds=2395, command_seconds=895)
    receipt = {'schemaVersion': 'lsf.canonical-pending-future.v1', 'status': 'in-progress',
        'sourceRevision': revision, 'privateCases': list(PRIVATE_CASES),
        'canonicalCase': CANONICAL_CASE, 'observations': [], 'fullCostModelQualified': False,
        'fullVendorSuiteExecuted': False, 'fullRuntimeSuiteExecuted': False,
        'signedJavaScriptExecuted': False, 'compilerImplicitInputsAttested': False,
        'hermetic': False, 'scope': 'first_poll exact pending-continuation output Box only; no allocator/RSS, queue-node, WorkerFunction or whole-runtime qualification', 'limits': {'overallSeconds': 2400, 'buildCommandSeconds': 900,
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
            'src/lib.rs', PREFIX + 'pending_future_', frozenset(PRIVATE_CASES), False)
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

        receipt['stage'] = 'build-actual-canonical-control'
        commands.environment = environment
        commands.command_seconds = 895
        stage = 'build-canonical-control'
        ordinal = len(commands.records)
        commands.run(stage, tools['cargo'], 'test', '-p', 'latent-wasmtime', '--locked',
            '--lib', '--no-run', '--message-format=json')
        contract, = [row for row in registry.load()['suites']
            if row['id'] == 'latent-wasmtime.lib.latent-wasmtime']
        require(contract['minimumCases'] == 488 and CANONICAL_CASE in contract['expectedCases']
            and CANONICAL_CASE in contract['expectedIgnored'], 'actual-canonical-contract')
        canonical_suite = artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'latent_wasmtime',
            'src/lib.rs', CANONICAL_CASE, frozenset({CANONICAL_CASE}), True)
        canonical = artifacts.read_inventory(logs / f'logs/{ordinal:02d}-{stage}.stdout.txt',
            ROOT, canonical_suite, target=target)
        receipt['canonicalExecutable'] = file_identity(canonical.executable,
            'latent-wasmtime-canonical-control', 512 * 1024**2)
        commands.environment = runtime_environment(canonical, 'canonical')
        commands.command_seconds = 25
        listed = commands.run('list-one-canonical-control', canonical.executable,
            CANONICAL_CASE, '--exact', '--ignored', '--list')
        require(len(listed) <= artifacts.MAX_LIST_BYTES, 'canonical-list-bound')
        artifacts.validate_listing(listed, canonical_suite)
        receipt['stage'] = CANONICAL_CASE
        commands.command_seconds = 55
        raw = commands.run('execute-one-canonical-control', canonical.executable,
            CANONICAL_CASE, '--exact', '--ignored', '--show-output', '--test-threads=1')
        receipt['observations'].append(result(raw, CANONICAL_CASE))
        require(re.findall(rb'^LSF_PENDING_FUTURE_V1 refusal=memory-bytes requests=4 '
            rb'before-poll=true fresh=42 stores=2$', raw, re.M) == [
            b'LSF_PENDING_FUTURE_V1 refusal=memory-bytes requests=4 before-poll=true fresh=42 stores=2'],
            'actual-fourth-admission-and-same-budget-fresh-store')
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
            executed=[*PRIVATE_CASES, CANONICAL_CASE], ignored=[])
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
