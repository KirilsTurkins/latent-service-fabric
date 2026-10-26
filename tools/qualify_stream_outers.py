"""Run only the six stream-outer controls; private counter and public budget scopes differ."""
from __future__ import annotations

import argparse
import hashlib
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

BRANCH = 'feat/sdk-736-stream-outers-20261026'
WORKFLOW = '.github/workflows/canonical-stream-outers.yml'
PRIVATE_PREFIX = 'runtime::component::concurrent::futures_and_streams::stream_outer_tests::'
PUBLIC_PREFIX = 'host::native_stream_outer_tests::'
PRIVATE_CASES = tuple(PRIVATE_PREFIX + name for name in (
    'actual_stream_guest_write_refusals_precede_busy_and_transmit_mutation',
    'actual_stream_guest_read_refusals_precede_busy_and_transmit_mutation',
    'actual_stream_guest_write_ready_pending_error_and_none_order',
    'actual_stream_guest_read_ready_pending_error_and_none_order'))
PUBLIC_CASES = tuple(PUBLIC_PREFIX + name for name in (
    'actual_stream_host_ready_refusals_precede_consumer_factory_and_polls',
    'actual_stream_host_ready_pending_ready_and_error_preserve_cleanup'))
FEATURES = ('component-model,component-model-async,cranelift,pooling-allocator,'
    'runtime,std,wit-parser,gc,gc-drc,cache,threads,coredump')
WAT = 'crates/latent-wasmtime/src/host/native-stream-outers.wat'
FIXTURE_ENV = 'LSF_TEST_STREAM_OUTERS_COMPONENT'


def require(value, reason):
    if not value:
        raise ValueError('canonical-stream-outers-' + reason)


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def source_inputs():
    raw = subprocess.check_output(['git', 'ls-files', '-z', '--', *SOURCE_ALLOWLIST],
        cwd=ROOT, timeout=30)
    require(len(raw) <= 2 * 1024**2, 'source-path-bound')
    names = [name for name in raw.decode().split('\0') if name]
    limits = SnapshotLimits()
    require(100 <= len(names) <= limits.max_entries, 'source-count')
    result, total = {}, 0
    for name in names:
        data = read_file(ROOT / name, limits.max_file_bytes)
        total += len(data)
        result[name] = identity(data)
    require(total <= limits.max_total_bytes, 'source-total')
    result[WORKFLOW] = identity(read_file(ROOT / WORKFLOW, 128 * 1024))
    return dict(sorted(result.items()))


def result(raw, case):
    require(case in (*PRIVATE_CASES, *PUBLIC_CASES), 'fixed-case')
    require(len(raw) <= artifacts.MAX_OUTPUT_BYTES, 'case-output-bound')
    require(re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$', raw, re.M)
        == [case.encode()], 'one-exact-success')
    summaries = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; '
        rb'(\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    require(len(summaries) == 1 and summaries[0][:4] == (b'1', b'0', b'0', b'0')
        and int(summaries[0][4]) <= 10000, 'one-executed-no-skip')
    return {'case': case, 'stdout': identity(raw), 'passed': 1, 'failed': 0,
        'ignored': 0, 'filteredOut': int(summaries[0][4]),
        'scope': 'private-canonical-entry-counter-owner' if case in PRIVATE_CASES
            else 'public-original-ActivationBudget'}


def fixture_identity(path):
    require(path.is_file() and not path.is_symlink(), 'fixture-file')
    data = read_file(path, 64 * 1024)
    require(len(data) > 8 and data.startswith(b'\0asm'), 'fixture-wasm')
    return identity(data)


def qualify(output, revision):
    require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
        and os.environ.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric'
        and os.environ.get('GITHUB_REF_NAME') == BRANCH
        and os.environ.get('GITHUB_EVENT_NAME') == 'push', 'one-exact-hosted-push')
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
        'owned-output')
    output = fresh(output)
    environment = build_environment(output)
    environment.pop(FIXTURE_ENV, None)
    environment.update(CARGO_TARGET_DIR=str(ROOT / 'target'), CARGO_INCREMENTAL='0',
        CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0',
        CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true', CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',
        CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true', CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
    logs = output / 'commands'
    logs.mkdir()
    # Existing five-second reaping reserve remains inside declared caps.
    commands = Commands(ROOT, logs, environment, deadline_seconds=2395, command_seconds=895)
    receipt = {'schemaVersion': 'lsf.canonical-stream-outers.v1', 'status': 'in-progress',
        'sourceRevision': revision, 'privateCases': list(PRIVATE_CASES),
        'publicCases': list(PUBLIC_CASES), 'observations': [],
        'fullCostModelQualified': False, 'fullRuntimeSuiteExecuted': False,
        'fullVendorSuiteExecuted': False, 'signedGuestExecuted': False,
        'hermetic': False, 'compilerImplicitInputsAttested': False,
        'scope': 'three prepared stream outer layouts and six finite entry/ownership controls; inner factories, consumer Arc, buffers, tables, transitive backing and RSS remain unpaid',
        'limits': {'overallSeconds': 2400, 'buildCommandSeconds': 900,
            'parseCommandSeconds': 60, 'caseProcessSeconds': 60,
            'listProcessSeconds': 30, 'cleanupReserveSeconds': 5},
        'publicOriginalBudget': {'memoryBytes': 1024**2, 'cpuFuel': 1_000_000_000,
            'wallTimeMilliseconds': 5000},
        'privateCounterOwner': {'payloadCeilingBytes': 64 * 1024**2,
            'installedFuel': 1_000_000_000, 'wallCeilingSeconds': 120,
            'originalActivationBudget': False},
        'commandLedgerBoundary': '17 supervised parse/build/library/list/test commands; normal pinned-tool resolver probes retain their existing owner and are not this ledger'}
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
        tools, pins = resolve_tools(toolchain, ROOT, environment, _deadline=commands.deadline)
        receipt['observedTools'] = pins
        environment.update(RUSTC=str(tools['rustc']), RUSTUP_TOOLCHAIN=toolchain['rust']['toolchain'])
        fixture_dir = output / 'fixtures'
        fixture_dir.mkdir()
        fixture = fixture_dir / 'native-stream-outers.wasm'
        require(ROOT not in fixture.parents, 'fixture-outside-source')
        receipt['stage'] = 'parse-one-fixed-canonical-fixture'
        commands.command_seconds = 55
        commands.run('parse-one-fixed-fixture', tools['wasm-tools'], 'parse', ROOT / WAT,
            '-o', fixture)
        bound_fixture = fixture_identity(fixture)
        receipt['fixture'] = {'wat': before[WAT], 'component': bound_fixture,
            'outputScope': 'private owning RunnerTemp only', 'retainedPath': 'fixtures/native-stream-outers.wasm'}

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
                target=ROOT / 'target', execute=probe)

        targets = (
            ('private', PRIVATE_CASES, ('--ignored',),
             ('test', '--manifest-path', 'crates/vendor/wasmtime/Cargo.toml', '--locked',
              '--lib', '--no-default-features', '--features', FEATURES,
              '--no-run', '--message-format=json'),
             artifacts.Suite('crates/vendor/wasmtime/Cargo.toml', 'wasmtime',
                'src/lib.rs', PRIVATE_PREFIX, frozenset(PRIVATE_CASES), True)),
            ('public', PUBLIC_CASES, (),
             ('test', '-p', 'latent-wasmtime', '--locked', '--lib', '--no-run', '--message-format=json'),
             artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'latent_wasmtime',
                'src/lib.rs', PUBLIC_PREFIX, frozenset(PUBLIC_CASES), True)),
        )
        executables = []
        for label, cases, ignored, argv, suite in targets:
            receipt['stage'] = 'build-' + label
            require(fixture_identity(fixture) == bound_fixture, 'fixture-before-build')
            commands.environment = environment
            commands.command_seconds = 895
            ordinal = len(commands.records)
            commands.run('build-' + label, tools['cargo'], *argv)
            artifact = artifacts.read_inventory(logs / f'logs/{ordinal:02d}-build-{label}.stdout.txt',
                ROOT, suite, target=ROOT / 'target')
            executable = file_identity(artifact.executable, label + '-stream-controls', 512 * 1024**2)
            receipt[label + 'Executable'] = executable
            executables.append((artifact.executable, executable, label + '-stream-controls'))
            run_env = runtime_environment(artifact, label)
            run_env.pop(FIXTURE_ENV, None)
            if label == 'private':
                run_env[FIXTURE_ENV] = str(fixture)
            else:
                contract, = [row for row in registry.load()['suites']
                    if row['id'] == 'latent-wasmtime.lib.latent-wasmtime']
                require(contract['minimumCases'] == 498
                    and set(cases) <= set(contract['expectedCases'])
                    and not set(cases) & set(contract['expectedIgnored']), 'public-suite-contract')
            commands.environment = run_env
            for index, case in enumerate(cases):
                receipt['stage'] = case
                require(fixture_identity(fixture) == bound_fixture, 'fixture-before-case')
                commands.command_seconds = 25
                listed = commands.run(f'{label}-list-{index}', artifact.executable,
                    case, '--exact', *ignored, '--list')
                require(len(listed) <= artifacts.MAX_LIST_BYTES, 'list-bound')
                artifacts.validate_listing(listed, artifacts.Suite(suite.manifest, suite.target,
                    suite.source, case, frozenset((case,)), True))
                commands.command_seconds = 55
                raw = commands.run(f'{label}-case-{index}', artifact.executable,
                    case, '--exact', *ignored, '--show-output', '--test-threads=1')
                receipt['observations'].append(result(raw, case))
                require(fixture_identity(fixture) == bound_fixture, 'fixture-after-case')
        require(len(commands.records) == 17 and len(receipt['observations']) == 6,
            'one-parse-two-builds-six-exact-cases')
        require(time.monotonic() < commands.deadline, 'overall-deadline')
        require(source_inputs() == before and source.verify() == checked, 'final-source')
        for path, bound, label in executables:
            require(file_identity(path, label, 512 * 1024**2) == bound, 'final-executable')
        require(fixture_identity(fixture) == bound_fixture, 'final-fixture')
        require([file_identity(tools[name], name) for name in sorted(tools)] == pins, 'final-tools')
        artifacts.require_source(ROOT, revision, environment)
        require(time.monotonic() < commands.deadline, 'final-deadline')
        receipt.update(status='passed', sourceAfter=before, sourceUnchanged=True,
            executed=[*PRIVATE_CASES, *PUBLIC_CASES], ignored=[])
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
