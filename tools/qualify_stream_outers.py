"""Fixed stream, cache, consumer, producer and real I/O memory modes; private counters and public budgets stay distinct."""
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


CACHE_CASE = 'tests::test_write_read_cache'
CACHE_MANIFEST = 'crates/vendor/wasmtime-cache/Cargo.toml'
CACHE_FEATURES = FEATURES


def cache_result(raw):
    require(len(raw) <= artifacts.MAX_OUTPUT_BYTES, 'cache-output-bound')
    require(re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$', raw, re.M)
        == [CACHE_CASE.encode()], 'cache-one-exact-success')
    rows = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; '
        rb'(\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    require(len(rows) == 1 and rows[0][:4] == (b'1', b'0', b'0', b'0')
        and int(rows[0][4]) <= 10000, 'cache-one-executed-no-skip')
    return {'case': CACHE_CASE, 'stdout': identity(raw), 'passed': 1,
        'failed': 0, 'ignored': 0, 'filteredOut': int(rows[0][4]),
        'scope': 'published-cache-compressed-write-and-read-source-matched-libtest'}


def cache_compile_packages(path, checked, *, parent):
    raw = read_file(path, artifacts.MAX_INVENTORY_BYTES)
    records = raw.splitlines()
    require(0 < len(records) <= artifacts.MAX_RECORDS, 'cache-cargo-record-bound')
    fixed = checked['cacheSecurityBackport']['fixedRegistryPackages']
    selected, saw_parent, finished = {}, False, False
    for line in records:
        require(len(line) <= artifacts.MAX_LINE_BYTES, 'cache-cargo-line-bound')
        if not line.strip():
            continue
        require(not finished, 'cache-cargo-after-build-finished')
        row = json.loads(line, object_pairs_hook=artifacts.unique_object)
        require(isinstance(row, dict), 'cache-cargo-record-object')
        if row.get('reason') == 'build-finished':
            require(row.get('success') is True, 'cache-cargo-build-success')
            finished = True
            continue
        if row.get('reason') != 'compiler-artifact':
            continue
        target = row.get('target', {})
        package = row.get('package_id', '')
        if parent and target.get('name') == 'wasmtime':
            require(artifacts.absolute_path(target.get('src_path'))
                == ROOT / source.PROVIDER / 'src/lib.rs', 'cache-parent-source')
            require(target.get('kind') == ['lib'] and row.get('profile', {}).get('test') is False,
                'cache-parent-library-check')
            saw_parent = True
        for name, pin in fixed.items():
            if target.get('name') != name.replace('-', '_') or target.get('kind') != ['lib']:
                continue
            expected = 'registry+https://github.com/rust-lang/crates.io-index#' + name + '@' + pin['version']
            require(package == expected and name not in selected, 'cache-actual-registry-package')
            selected[name] = {'packageId': package, 'lockedChecksum': pin['checksum'],
                'targetName': target['name'], 'fresh': row.get('fresh')}
    require(finished and set(selected) == set(fixed) and (saw_parent or not parent),
        'cache-all-fixed-packages-and-parent')
    return selected


def qualify_cache_repair(output, revision):
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
    commands = Commands(ROOT, logs, environment, deadline_seconds=2395, command_seconds=895)
    receipt = {'schemaVersion': 'lsf.wasmtime-cache-security-repair.v1', 'status': 'in-progress',
        'sourceRevision': revision, 'observations': [], 'executed': [],
        'streamControlsExecuted': False, 'fixtureAssembled': False,
        'fullRuntimeSuiteExecuted': False, 'fullVendorSuiteExecuted': False,
        'fullCostModelQualified': False, 'signedGuestExecuted': False,
        'hermetic': False, 'compilerImplicitInputsAttested': False,
        'scope': 'locked standalone parent cache-feature compile check and one upstream cache compressed write/read test only; original fe9 six-control result remains historical',
        'limits': {'overallSeconds': 2400, 'buildCommandSeconds': 900,
            'caseProcessSeconds': 60, 'listProcessSeconds': 30, 'cleanupReserveSeconds': 5},
        'commandLedgerBoundary': 'five supervised check/build/library/list/test commands; pinned-tool resolver probes retain the common parent deadline'}
    try:
        artifacts.require_source(ROOT, revision, environment)
        before = source_inputs()
        receipt['sourceBefore'] = before
        write_json(output / 'source-inputs.json', before)
        checked = source.verify()
        require(checked['nativeCohort'].endswith('-stream-outers-memory-v17-cache-repair')
            and len(checked['cacheSecurityBackport']['files']) == 14, 'fixed-cache-source-cohort')
        receipt['wasmtimeSource'] = checked
        toolchain = tomllib.loads(read_file(ROOT / 'tools/toolchain.toml', 128 * 1024).decode())
        require(toolchain['rust']['toolchain'] == '1.97.1'
            and toolchain['contracts']['wasm-tools'] == '1.254.0', 'normal-tool-pins')
        tools, pins = resolve_tools(toolchain, ROOT, environment, _deadline=commands.deadline)
        receipt['observedTools'] = pins
        environment.update(RUSTC=str(tools['rustc']), RUSTUP_TOOLCHAIN=toolchain['rust']['toolchain'])

        receipt['stage'] = 'parent-cache-feature-check'
        ordinal = len(commands.records)
        commands.run('parent-cache-feature-check', tools['cargo'], 'check',
            '--manifest-path', 'crates/vendor/wasmtime/Cargo.toml', '--locked', '--lib',
            '--no-default-features', '--features', CACHE_FEATURES, '-j2', '--message-format=json')
        receipt['parentCacheCompilePackages'] = cache_compile_packages(
            logs / f'logs/{ordinal:02d}-parent-cache-feature-check.stdout.txt', checked, parent=True)

        receipt['stage'] = 'build-one-cache-libtest'
        ordinal = len(commands.records)
        commands.run('build-one-cache-libtest', tools['cargo'], 'test',
            '--manifest-path', CACHE_MANIFEST, '--locked', '--lib', '--no-run',
            '--message-format=json', '-j2')
        inventory = logs / f'logs/{ordinal:02d}-build-one-cache-libtest.stdout.txt'
        receipt['cacheTestCompilePackages'] = cache_compile_packages(inventory, checked, parent=False)
        suite = artifacts.Suite(CACHE_MANIFEST, 'wasmtime_internal_cache', 'src/lib.rs',
            CACHE_CASE, frozenset((CACHE_CASE,)), True)
        artifact = artifacts.read_inventory(inventory, ROOT, suite, target=ROOT / 'target')
        executable = file_identity(artifact.executable, 'upstream-cache-libtest', 512 * 1024**2)
        receipt['cacheExecutable'] = executable

        def probe(argv, *, cwd, env, timeout, maximum):
            require(argv == ['rustc', '--print', 'target-libdir'] and cwd == ROOT
                and timeout == 30 and maximum == 4096, 'normal-library-probe')
            commands.command_seconds = 25
            commands.environment = env
            raw = commands.run('cache-rust-library-path', tools['rustc'], *argv[1:])
            require(len(raw) <= maximum, 'rust-library-output-bound')
            return 0, raw

        run_env = artifacts.cargo_environment(ROOT, artifact, environment,
            target=ROOT / 'target', execute=probe)
        run_env.pop(FIXTURE_ENV, None)
        commands.environment = run_env
        commands.command_seconds = 25
        receipt['stage'] = 'list-one-cache-roundtrip'
        listed = commands.run('cache-list', artifact.executable, CACHE_CASE, '--exact', '--list')
        require(len(listed) <= artifacts.MAX_LIST_BYTES, 'cache-list-bound')
        artifacts.validate_listing(listed, suite)
        commands.command_seconds = 55
        receipt['stage'] = CACHE_CASE
        raw = commands.run('cache-roundtrip', artifact.executable, CACHE_CASE,
            '--exact', '--show-output', '--test-threads=1')
        receipt['observations'].append(cache_result(raw))
        require(len(commands.records) == 5 and len(receipt['observations']) == 1,
            'cache-five-commands-one-upstream-case')
        require(time.monotonic() < commands.deadline, 'overall-deadline')
        require(source_inputs() == before and source.verify() == checked, 'final-source')
        require(file_identity(artifact.executable, 'upstream-cache-libtest', 512 * 1024**2)
            == executable, 'final-cache-executable')
        require([file_identity(tools[name], name) for name in sorted(tools)] == pins, 'final-tools')
        artifacts.require_source(ROOT, revision, environment)
        require(time.monotonic() < commands.deadline, 'final-deadline')
        receipt.update(status='passed', sourceAfter=before, sourceUnchanged=True,
            executed=[CACHE_CASE], ignored=[])
        write_json(output / 'receipt.json', receipt)
    except BaseException:
        receipt['status'] = 'failed'
        write_json(output / 'FAILED.json', receipt)
        raise
    finally:
        write_json(output / 'commands.json', commands.records)


CONSUMER_BRANCH = 'feat/sdk-736-consumer-cell-20261026'
CONSUMER_PRIVATE_CASES = tuple(PRIVATE_PREFIX + name for name in (
    'consumer_cell_two_admissions_refuse_before_either_allocation_and_abandon_unused',
    'consumer_cell_pinned_value_and_shared_owner_live_through_clones_and_taken_guard',
    'consumer_cell_zst_and_none_preserve_actual_backing_routes',
    'consumer_cell_each_confirmation_unwind_has_physical_cleanup_installed',
    'consumer_cell_destructor_unwind_retains_both_original_uncertain_charges',
))
CONSUMER_PUBLIC_CASES = PUBLIC_CASES


def consumer_result(raw, case):
    require(case in (*CONSUMER_PRIVATE_CASES, *CONSUMER_PUBLIC_CASES), 'fixed-case')
    require(len(raw) <= artifacts.MAX_OUTPUT_BYTES, 'case-output-bound')
    require(re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$', raw, re.M)
        == [case.encode()], 'one-exact-success')
    summaries = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; '
        rb'(\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    require(len(summaries) == 1 and summaries[0][:4] == (b'1', b'0', b'0', b'0')
        and int(summaries[0][4]) <= 10000, 'one-executed-no-skip')
    return {'case': case, 'stdout': identity(raw), 'passed': 1, 'failed': 0,
        'ignored': 0, 'filteredOut': int(summaries[0][4]),
        'scope': 'private-consumer-implementation-counter' if case in CONSUMER_PRIVATE_CASES
            else 'public-original-ActivationBudget'}


def qualify_consumer_cell(output, revision):
    require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
        and os.environ.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric'
        and os.environ.get('GITHUB_REF_NAME') == CONSUMER_BRANCH
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
    receipt = {'schemaVersion': 'lsf.consumer-cell-ownership.v1', 'status': 'in-progress',
        'sourceRevision': revision, 'privateCases': list(CONSUMER_PRIVATE_CASES),
        'publicCases': list(CONSUMER_PUBLIC_CASES), 'observations': [],
        'fullCostModelQualified': False, 'fullRuntimeSuiteExecuted': False,
        'fullVendorSuiteExecuted': False, 'signedGuestExecuted': False,
        'hermetic': False, 'compilerImplicitInputsAttested': False,
        'scope': 'selected consumer pinned value and shared cell: five finite private implementation controls and two affected public HostReady controls; producer, inner factories, buffers, collections and RSS remain unpaid',
        'limits': {'overallSeconds': 2400, 'buildCommandSeconds': 900,
            'caseProcessSeconds': 60,
            'listProcessSeconds': 30, 'cleanupReserveSeconds': 5},
        'publicOriginalBudget': {'memoryBytes': 1024**2, 'cpuFuel': 1_000_000_000,
            'wallTimeMilliseconds': 5000},
        'privateCounterOwner': {'originalActivationBudget': False,
            'guestExecuted': False, 'genericMemoryCeilingClaimed': False},
        'fixtureAssembled': False, 'oldCanonicalCasesExecuted': False,
        'oldStreamProgrammeExecuted': False, 'cacheRoundtripExecuted': False,
        'commandLedgerBoundary': '18 supervised build/library/list/test commands; normal pinned-tool resolver probes retain their existing owner and are not this ledger'}
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
            ('private', CONSUMER_PRIVATE_CASES, (),
             ('test', '--manifest-path', 'crates/vendor/wasmtime/Cargo.toml', '--locked',
              '--lib', '--no-default-features', '--features', FEATURES,
              '--no-run', '--message-format=json'),
             artifacts.Suite('crates/vendor/wasmtime/Cargo.toml', 'wasmtime',
                'src/lib.rs', PRIVATE_PREFIX, frozenset(CONSUMER_PRIVATE_CASES), True)),
            ('public', CONSUMER_PUBLIC_CASES, (),
             ('test', '-p', 'latent-wasmtime', '--locked', '--lib', '--no-run', '--message-format=json'),
             artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'latent_wasmtime',
                'src/lib.rs', PUBLIC_PREFIX, frozenset(CONSUMER_PUBLIC_CASES), True)),
        )
        executables = []
        for label, cases, ignored, argv, suite in targets:
            receipt['stage'] = 'build-' + label
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
            if label == 'public':
                contract, = [row for row in registry.load()['suites']
                    if row['id'] == 'latent-wasmtime.lib.latent-wasmtime']
                require(contract['minimumCases'] == 498
                    and set(cases) <= set(contract['expectedCases'])
                    and not set(cases) & set(contract['expectedIgnored']), 'public-suite-contract')
            commands.environment = run_env
            for index, case in enumerate(cases):
                receipt['stage'] = case
                commands.command_seconds = 25
                listed = commands.run(f'{label}-list-{index}', artifact.executable,
                    case, '--exact', *ignored, '--list')
                require(len(listed) <= artifacts.MAX_LIST_BYTES, 'list-bound')
                artifacts.validate_listing(listed, artifacts.Suite(suite.manifest, suite.target,
                    suite.source, case, frozenset((case,)), True))
                commands.command_seconds = 55
                raw = commands.run(f'{label}-case-{index}', artifact.executable,
                    case, '--exact', *ignored, '--show-output', '--test-threads=1')
                receipt['observations'].append(consumer_result(raw, case))
        require(len(commands.records) == 18 and len(receipt['observations']) == 7,
            'two-builds-two-library-probes-seven-exact-cases')
        require(time.monotonic() < commands.deadline, 'overall-deadline')
        require(source_inputs() == before and source.verify() == checked, 'final-source')
        for path, bound, label in executables:
            require(file_identity(path, label, 512 * 1024**2) == bound, 'final-executable')
        require([file_identity(tools[name], name) for name in sorted(tools)] == pins, 'final-tools')
        artifacts.require_source(ROOT, revision, environment)
        require(time.monotonic() < commands.deadline, 'final-deadline')
        receipt.update(status='passed', sourceAfter=before, sourceUnchanged=True,
            executed=[*CONSUMER_PRIVATE_CASES, *CONSUMER_PUBLIC_CASES], ignored=[])
        write_json(output / 'receipt.json', receipt)
    except BaseException:
        receipt['status'] = 'failed'
        write_json(output / 'FAILED.json', receipt)
        raise
    finally:
        write_json(output / 'commands.json', commands.records)


PRODUCER_BRANCH = 'feat/sdk-736-producer-cell-20261026'
PRODUCER_PRIVATE_CASES = tuple(PRIVATE_PREFIX + name for name in (
    'producer_cell_stream_admission_is_shared_only_and_unused_refunds',
    'producer_cell_pin_clone_send_guard_restore_and_p_then_b_retirement',
    'producer_cell_zst_and_original_none_tuple_remain_distinct',
    'producer_cell_confirmation_and_buffer_default_unwind_install_cleanup_first',
    'producer_cell_destructor_unwind_retains_same_original_guards',
    'producer_cell_real_future_adapter_default_err_restores_original_custody',
))
PRODUCER_NEW_PUBLIC_CASES = tuple(PUBLIC_PREFIX + name for name in (
    'actual_producer_creation_refusals_precede_poll_and_preserve_foreign_store',
    'actual_producer_stream_conversion_reuses_budget_and_preserves_owning_escape',
    'actual_producer_future_any_roundtrip_and_pending_completion_preserve_custody',
))
PRODUCER_PUBLIC_CASES = PRODUCER_NEW_PUBLIC_CASES + PUBLIC_CASES


def producer_result(raw, case):
    require(case in (*PRODUCER_PRIVATE_CASES, *PRODUCER_PUBLIC_CASES), 'fixed-case')
    require(len(raw) <= artifacts.MAX_OUTPUT_BYTES, 'case-output-bound')
    require(re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$', raw, re.M)
        == [case.encode()], 'one-exact-success')
    summaries = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; '
        rb'(\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    require(len(summaries) == 1 and summaries[0][:4] == (b'1', b'0', b'0', b'0')
        and int(summaries[0][4]) <= 10000, 'one-executed-no-skip')
    return {'case': case, 'stdout': identity(raw), 'passed': 1, 'failed': 0,
        'ignored': 0, 'filteredOut': int(summaries[0][4]),
        'scope': 'private-producer-implementation-counter' if case in PRODUCER_PRIVATE_CASES
            else 'public-original-ActivationBudget'}


def qualify_producer_cell(output, revision):
    require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
        and os.environ.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric'
        and os.environ.get('GITHUB_REF_NAME') == PRODUCER_BRANCH
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
    receipt = {'schemaVersion': 'lsf.producer-cell-ownership.v1', 'status': 'in-progress',
        'sourceRevision': revision, 'privateCases': list(PRODUCER_PRIVATE_CASES),
        'publicCases': list(PRODUCER_PUBLIC_CASES), 'observations': [],
        'fullCostModelQualified': False, 'fullRuntimeSuiteExecuted': False,
        'fullVendorSuiteExecuted': False, 'signedGuestExecuted': False,
        'hermetic': False, 'compilerImplicitInputsAttested': False,
        'scope': 'selected producer shared cell and closed Future local-adapter body: six finite private implementation, three new public and two affected existing public controls; general stream P Boxes, inner factories, buffers, collections and RSS remain unpaid',
        'limits': {'overallSeconds': 2400, 'buildCommandSeconds': 900,
            'caseProcessSeconds': 60,
            'listProcessSeconds': 30, 'cleanupReserveSeconds': 5},
        'publicOriginalBudget': {'memoryBytes': 1024**2, 'cpuFuel': 1_000_000_000,
            'wallTimeMilliseconds': 5000},
        'privateCounterOwner': {'originalActivationBudget': False,
            'guestExecuted': False, 'genericMemoryCeilingClaimed': False,
            'oneRealFutureStoreInstrumentationCeilingBytes': 64 * 1024**2,
            'installedFuelClaimed': False},
        'fixtureAssembled': False, 'oldCanonicalCasesExecuted': False,
        'oldStreamProgrammeExecuted': False, 'cacheRoundtripExecuted': False, 'oldConsumerPrivateCasesExecuted': False,
        'affectedExistingPublicCases': list(PUBLIC_CASES),
        'commandLedgerBoundary': '26 supervised build/library/list/test commands; normal pinned-tool resolver probes retain their existing owner and are not this ledger'}
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
            ('private', PRODUCER_PRIVATE_CASES, (),
             ('test', '--manifest-path', 'crates/vendor/wasmtime/Cargo.toml', '--locked',
              '--lib', '--no-default-features', '--features', FEATURES,
              '--no-run', '--message-format=json'),
             artifacts.Suite('crates/vendor/wasmtime/Cargo.toml', 'wasmtime',
                'src/lib.rs', PRIVATE_PREFIX, frozenset(PRODUCER_PRIVATE_CASES), True)),
            ('public', PRODUCER_PUBLIC_CASES, (),
             ('test', '-p', 'latent-wasmtime', '--locked', '--lib', '--no-run', '--message-format=json'),
             artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'latent_wasmtime',
                'src/lib.rs', PUBLIC_PREFIX, frozenset(PRODUCER_PUBLIC_CASES), True)),
        )
        executables = []
        for label, cases, ignored, argv, suite in targets:
            receipt['stage'] = 'build-' + label
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
            if label == 'public':
                contract, = [row for row in registry.load()['suites']
                    if row['id'] == 'latent-wasmtime.lib.latent-wasmtime']
                require(contract['minimumCases'] == 501
                    and set(cases) <= set(contract['expectedCases'])
                    and not set(cases) & set(contract['expectedIgnored']), 'public-suite-contract')
            commands.environment = run_env
            for index, case in enumerate(cases):
                receipt['stage'] = case
                commands.command_seconds = 25
                listed = commands.run(f'{label}-list-{index}', artifact.executable,
                    case, '--exact', *ignored, '--list')
                require(len(listed) <= artifacts.MAX_LIST_BYTES, 'list-bound')
                artifacts.validate_listing(listed, artifacts.Suite(suite.manifest, suite.target,
                    suite.source, case, frozenset((case,)), True))
                commands.command_seconds = 55
                raw = commands.run(f'{label}-case-{index}', artifact.executable,
                    case, '--exact', *ignored, '--show-output', '--test-threads=1')
                receipt['observations'].append(producer_result(raw, case))
        require(len(commands.records) == 26 and len(receipt['observations']) == 11,
            'two-builds-two-library-probes-eleven-exact-cases')
        require(time.monotonic() < commands.deadline, 'overall-deadline')
        require(source_inputs() == before and source.verify() == checked, 'final-source')
        for path, bound, label in executables:
            require(file_identity(path, label, 512 * 1024**2) == bound, 'final-executable')
        require([file_identity(tools[name], name) for name in sorted(tools)] == pins, 'final-tools')
        artifacts.require_source(ROOT, revision, environment)
        require(time.monotonic() < commands.deadline, 'final-deadline')
        receipt.update(status='passed', sourceAfter=before, sourceUnchanged=True,
            executed=[*PRODUCER_PRIVATE_CASES, *PRODUCER_PUBLIC_CASES], ignored=[])
        write_json(output / 'receipt.json', receipt)
    except BaseException:
        receipt['status'] = 'failed'
        write_json(output / 'FAILED.json', receipt)
        raise
    finally:
        write_json(output / 'commands.json', commands.records)


FACTORY_BRANCH = 'feat/sdk-736-producer-factories-20261026'
FACTORY_PRIVATE_CASES = tuple(PRIVATE_PREFIX + name for name in (
    'producer_factory_capture_destructor_unwind_retains_original_guard',
    'producer_factory_confirmation_and_borrowed_call_keep_physical_owner',
    'producer_factory_pair_admission_precedes_builders_and_unused_refunds',
    'producer_factory_zst_legacy_and_returned_future_owners_are_distinct',
    'producer_cell_real_future_adapter_default_err_restores_original_custody',
))
FACTORY_PUBLIC_CASES = tuple(PUBLIC_PREFIX + name for name in (
    'actual_producer_factory_conversion_and_pending_lifetime_preserve_budget',
    'actual_producer_factory_refusals_precede_transmit_factory_and_polls',
    'actual_producer_stream_conversion_reuses_budget_and_preserves_owning_escape',
    'actual_producer_future_any_roundtrip_and_pending_completion_preserve_custody',
))
FACTORY_AFFECTED_PRIVATE_CASES = FACTORY_PRIVATE_CASES[-1:]
FACTORY_AFFECTED_PUBLIC_CASES = FACTORY_PUBLIC_CASES[-2:]


def factory_result(raw, case):
    require(case in (*FACTORY_PRIVATE_CASES, *FACTORY_PUBLIC_CASES), 'fixed-case')
    require(len(raw) <= artifacts.MAX_OUTPUT_BYTES, 'case-output-bound')
    require(re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$', raw, re.M)
        == [case.encode()], 'one-exact-success')
    summaries = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; '
        rb'(\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    require(len(summaries) == 1 and summaries[0][:4] == (b'1', b'0', b'0', b'0')
        and int(summaries[0][4]) <= 10000, 'one-executed-no-skip')
    return {'case': case, 'stdout': identity(raw), 'passed': 1, 'failed': 0,
        'ignored': 0, 'filteredOut': int(summaries[0][4]),
        'scope': 'private-producer-factory-implementation-counter' if case in FACTORY_PRIVATE_CASES
            else 'public-original-ActivationBudget'}


def qualify_producer_factories(output, revision):
    require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
        and os.environ.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric'
        and os.environ.get('GITHUB_REF_NAME') == FACTORY_BRANCH
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
    receipt = {'schemaVersion': 'lsf.producer-factory-ownership.v1', 'status': 'in-progress',
        'sourceRevision': revision, 'privateCases': list(FACTORY_PRIVATE_CASES),
        'publicCases': list(FACTORY_PUBLIC_CASES), 'observations': [],
        'fullCostModelQualified': False, 'fullRuntimeSuiteExecuted': False,
        'fullVendorSuiteExecuted': False, 'signedGuestExecuted': False,
        'hermetic': False, 'compilerImplicitInputsAttested': False,
        'scope': 'selected concrete producer produce/conversion factory Boxes: four new private and two new public controls plus only three affected existing count controls; general P bodies, Buffer heaps, consumer factories, returned inner futures and RSS remain unpaid',
        'limits': {'overallSeconds': 2400, 'buildCommandSeconds': 900,
            'caseProcessSeconds': 60,
            'listProcessSeconds': 30, 'cleanupReserveSeconds': 5},
        'publicOriginalBudget': {'memoryBytes': 1024**2, 'cpuFuel': 1_000_000_000,
            'wallTimeMilliseconds': 5000},
        'privateCounterOwner': {'originalActivationBudget': False,
            'guestExecuted': False, 'genericMemoryCeilingClaimed': False,
            'oneRealFutureStoreInstrumentationCeilingBytes': 64 * 1024**2,
            'installedFuelClaimed': False},
        'fixtureAssembled': False, 'oldCanonicalCasesExecuted': False,
        'oldStreamProgrammeExecuted': False, 'cacheRoundtripExecuted': False, 'oldConsumerPrivateCasesExecuted': False,
        'oldProducerProgrammeExecuted': False,
        'affectedExistingPrivateCases': list(FACTORY_AFFECTED_PRIVATE_CASES),
        'affectedExistingPublicCases': list(FACTORY_AFFECTED_PUBLIC_CASES),
        'commandLedgerBoundary': '22 supervised build/library/list/test commands; normal pinned-tool resolver probes retain their existing owner and are not this ledger'}
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
            ('private', FACTORY_PRIVATE_CASES, (),
             ('test', '--manifest-path', 'crates/vendor/wasmtime/Cargo.toml', '--locked',
              '--lib', '--no-default-features', '--features', FEATURES,
              '--no-run', '--message-format=json'),
             artifacts.Suite('crates/vendor/wasmtime/Cargo.toml', 'wasmtime',
                'src/lib.rs', PRIVATE_PREFIX, frozenset(FACTORY_PRIVATE_CASES), True)),
            ('public', FACTORY_PUBLIC_CASES, (),
             ('test', '-p', 'latent-wasmtime', '--locked', '--lib', '--no-run', '--message-format=json'),
             artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'latent_wasmtime',
                'src/lib.rs', PUBLIC_PREFIX, frozenset(FACTORY_PUBLIC_CASES), True)),
        )
        executables = []
        for label, cases, ignored, argv, suite in targets:
            receipt['stage'] = 'build-' + label
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
            if label == 'public':
                contract, = [row for row in registry.load()['suites']
                    if row['id'] == 'latent-wasmtime.lib.latent-wasmtime']
                require(contract['minimumCases'] == 503
                    and set(cases) <= set(contract['expectedCases'])
                    and not set(cases) & set(contract['expectedIgnored']), 'public-suite-contract')
            commands.environment = run_env
            for index, case in enumerate(cases):
                receipt['stage'] = case
                commands.command_seconds = 25
                listed = commands.run(f'{label}-list-{index}', artifact.executable,
                    case, '--exact', *ignored, '--list')
                require(len(listed) <= artifacts.MAX_LIST_BYTES, 'list-bound')
                artifacts.validate_listing(listed, artifacts.Suite(suite.manifest, suite.target,
                    suite.source, case, frozenset((case,)), True))
                commands.command_seconds = 55
                raw = commands.run(f'{label}-case-{index}', artifact.executable,
                    case, '--exact', *ignored, '--show-output', '--test-threads=1')
                receipt['observations'].append(factory_result(raw, case))
        require(len(commands.records) == 22 and len(receipt['observations']) == 9,
            'two-builds-two-library-probes-nine-exact-cases')
        require(time.monotonic() < commands.deadline, 'overall-deadline')
        require(source_inputs() == before and source.verify() == checked, 'final-source')
        for path, bound, label in executables:
            require(file_identity(path, label, 512 * 1024**2) == bound, 'final-executable')
        require([file_identity(tools[name], name) for name in sorted(tools)] == pins, 'final-tools')
        artifacts.require_source(ROOT, revision, environment)
        require(time.monotonic() < commands.deadline, 'final-deadline')
        receipt.update(status='passed', sourceAfter=before, sourceUnchanged=True,
            executed=[*FACTORY_PRIVATE_CASES, *FACTORY_PUBLIC_CASES], ignored=[])
        write_json(output / 'receipt.json', receipt)
    except BaseException:
        receipt['status'] = 'failed'
        write_json(output / 'FAILED.json', receipt)
        raise
    finally:
        write_json(output / 'commands.json', commands.records)


IO_BRANCH = 'feat/sdk-736-io-operation-native-20261026'
IO_PREFIX = 'broker::io::tests::'
IO_CASES = tuple(IO_PREFIX + name for name in (
    'native_operation_preparation_refuses_each_backing_without_dispatch_or_node_leak',
    'native_operation_running_buffer_and_last_weak_keep_full_backing_paid',
    'native_running_box_cleanup_is_physical_first_and_unwind_conservative',
    'all_limit_dimensions_have_finite_hard_ceilings',
    'partial_consumers_retain_capacity_and_original_activation_after_close',
))
IO_NEW_CASES = IO_CASES[:3]


def io_operation_result(raw, case):
    require(case in IO_CASES, 'fixed-case')
    require(len(raw) <= artifacts.MAX_OUTPUT_BYTES, 'case-output-bound')
    require(re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$', raw, re.M)
        == [case.encode()], 'one-exact-success')
    summaries = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; '
        rb'(\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    require(len(summaries) == 1 and summaries[0][:4] == (b'1', b'0', b'0', b'0')
        and int(summaries[0][4]) <= 10000, 'one-executed-no-skip')
    return {'case': case, 'stdout': identity(raw), 'passed': 1, 'failed': 0,
        'ignored': 0, 'filteredOut': int(summaries[0][4]),
        'scope': ('original-Phase3-memory-broker-unit' if case in IO_NEW_CASES
            else 'node-compiled-layout-unit' if case == IO_CASES[3]
            else 'legacy-Phase1-IO-reference')}


def qualify_io_operations(output, revision):
    require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
        and os.environ.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric'
        and os.environ.get('GITHUB_REF_NAME') == IO_BRANCH
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
    receipt = {'schemaVersion': 'lsf.io-operation-native.v1', 'status': 'in-progress',
        'sourceRevision': revision, 'selectedCases': list(IO_CASES), 'observations': [],
        'newCases': list(IO_NEW_CASES), 'affectedLayoutCase': IO_CASES[3],
        'phase1ReferenceCase': IO_CASES[4],
        'fullCostModelQualified': False, 'fullRuntimeSuiteExecuted': False,
        'fullVendorSuiteExecuted': False, 'signedGuestExecuted': False,
        'wasmtimeExecuted': False, 'engineOrComponentCompiled': False,
        'hermetic': False, 'compilerImplicitInputsAttested': False,
        'scope': 'actual I/O Operation shared backing and running ProviderCall Box; full Arc/billing stays paid through final Weak; node2048 quota remains logical; request/scratch/transfer/future/transitive backing remains separate',
        'limits': {'overallSeconds': 2400, 'buildCommandSeconds': 900,
            'caseProcessSeconds': 60, 'listProcessSeconds': 30, 'cleanupReserveSeconds': 5},
        'newControlBudgetFixture': {'memoryBytes': 1024**2, 'cpuFuelGrant': 100_000,
            'wallTimeGrantMilliseconds': 30_000, 'installedEngineFuel': False,
            'guestExecuted': False, 'genericHostOrRSSCeilingClaimed': False},
        'fixtureAssembled': False, 'oldCanonicalCasesExecuted': False,
        'oldStreamProgrammeExecuted': False, 'oldProducerProgrammeExecuted': False,
        'cacheRoundtripExecuted': False,
        'commandLedgerBoundary': '12 supervised build/library/list/test commands; normal pinned-tool resolver probes retain their existing owner and are not this ledger'}
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
            ('io', IO_CASES, (),
             ('test', '-p', 'latent-capabilities', '--locked', '--lib', '--all-features',
              '--no-run', '--message-format=json'),
             artifacts.Suite('crates/latent-capabilities/Cargo.toml', 'latent_capabilities',
                'src/lib.rs', IO_PREFIX, frozenset(IO_CASES), True)),
        )
        executables = []
        for label, cases, ignored, argv, suite in targets:
            receipt['stage'] = 'build-' + label
            commands.environment = environment
            commands.command_seconds = 895
            ordinal = len(commands.records)
            commands.run('build-' + label, tools['cargo'], *argv)
            artifact = artifacts.read_inventory(logs / f'logs/{ordinal:02d}-build-{label}.stdout.txt',
                ROOT, suite, target=ROOT / 'target')
            executable = file_identity(artifact.executable, label + '-native-backing-controls', 512 * 1024**2)
            receipt[label + 'Executable'] = executable
            executables.append((artifact.executable, executable, label + '-native-backing-controls'))
            run_env = runtime_environment(artifact, label)
            run_env.pop(FIXTURE_ENV, None)
            if label == 'io':
                contract, = [row for row in registry.load()['suites']
                    if row['id'] == 'latent-capabilities.lib.latent-capabilities']
                require(contract['minimumCases'] == 214
                    and set(cases) <= set(contract['expectedCases'])
                    and not set(cases) & set(contract['expectedIgnored']), 'normal-io-suite-contract')
            commands.environment = run_env
            for index, case in enumerate(cases):
                receipt['stage'] = case
                commands.command_seconds = 25
                listed = commands.run(f'{label}-list-{index}', artifact.executable,
                    case, '--exact', *ignored, '--list')
                require(len(listed) <= artifacts.MAX_LIST_BYTES, 'list-bound')
                artifacts.validate_listing(listed, artifacts.Suite(suite.manifest, suite.target,
                    suite.source, case, frozenset((case,)), True))
                commands.command_seconds = 55
                raw = commands.run(f'{label}-case-{index}', artifact.executable,
                    case, '--exact', *ignored, '--show-output', '--test-threads=1')
                receipt['observations'].append(io_operation_result(raw, case))
        require(len(commands.records) == 12 and len(receipt['observations']) == 5,
            'one-build-one-library-probe-five-exact-cases')
        require(time.monotonic() < commands.deadline, 'overall-deadline')
        require(source_inputs() == before and source.verify() == checked, 'final-source')
        for path, bound, label in executables:
            require(file_identity(path, label, 512 * 1024**2) == bound, 'final-executable')
        require([file_identity(tools[name], name) for name in sorted(tools)] == pins, 'final-tools')
        artifacts.require_source(ROOT, revision, environment)
        require(time.monotonic() < commands.deadline, 'final-deadline')
        receipt.update(status='passed', sourceAfter=before, sourceUnchanged=True,
            executed=list(IO_CASES), ignored=[])
        write_json(output / 'receipt.json', receipt)
    except BaseException:
        receipt['status'] = 'failed'
        write_json(output / 'FAILED.json', receipt)
        raise
    finally:
        write_json(output / 'commands.json', commands.records)


IO_GRAPH_BRANCH = 'feat/sdk-736-io-graph-native-20261026'
IO_GRAPH_CASES = (
    'broker::io::future::tests::provider_future_refuses_before_builder_and_refunds_unused_preparation',
    'broker::io::future::tests::provider_future_pin_and_physical_first_cleanup_keep_original_charge',
    'broker::io::future::tests::provider_future_early_failure_is_inline_and_consumed_once',
    'broker::io::tests::native_owned_buffer_refuses_before_allocation_and_partial_result_keeps_credit',
    'broker::io::stream::native_tests::native_ring_preparation_is_atomic_and_delivered_chunks_keep_lifetime',
    'broker::io::transfer::native_tests::native_transfer_factory_is_prepaid_and_confirms_only_actual_capacity',
    'broker::pools::admission::native_tests::native_request_preparation_and_last_weak_keep_original_backing',
    'broker::io::tests::partial_consumers_retain_capacity_and_original_activation_after_close',
)
IO_GRAPH_NEW_CASES = IO_GRAPH_CASES[:-1]
IO_GRAPH_CHECK_ARGS = ('check', '--locked', '--tests', '--all-features',
    '-p', 'latent-http', '-p', 'latent-blobs', '-p', 'latent-streams',
    '-p', 'latent-wasmtime', '-p', 'latentd', '--message-format=json')
IO_GRAPH_CHECK_TARGETS = (
    ('crates/latent-http/Cargo.toml', 'latent_http', 'src/lib.rs'),
    ('crates/latent-blobs/Cargo.toml', 'latent_blobs', 'src/lib.rs'),
    ('crates/latent-streams/Cargo.toml', 'latent_streams', 'src/lib.rs'),
    ('crates/latent-wasmtime/Cargo.toml', 'latent_wasmtime', 'src/lib.rs'),
    ('apps/latentd/Cargo.toml', 'latentd', 'src/lib_root.rs'),
)


def io_graph_result(raw, case):
    require(case in IO_GRAPH_CASES, 'fixed-case')
    require(len(raw) <= artifacts.MAX_OUTPUT_BYTES, 'case-output-bound')
    require(re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$', raw, re.M)
        == [case.encode()], 'one-exact-success')
    summaries = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; '
        rb'(\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    require(len(summaries) == 1 and summaries[0][:4] == (b'1', b'0', b'0', b'0')
        and int(summaries[0][4]) <= 10000, 'one-executed-no-skip')
    return {'case': case, 'stdout': identity(raw), 'passed': 1, 'failed': 0,
        'ignored': 0, 'filteredOut': int(summaries[0][4]),
        'scope': ('exact-layout-provider-future-backing-instrument-control'
            if case in IO_GRAPH_CASES[:2] else 'allocation-free-provider-refusal-control'
            if case == IO_GRAPH_CASES[2] else 'legacy-Phase1-IO-reference'
            if case == IO_GRAPH_CASES[-1] else 'original-Phase3-broker-owned-graph-control')}


def io_graph_check_result(raw):
    require(len(raw) <= artifacts.MAX_INVENTORY_BYTES, 'integration-inventory-bound')
    expected = {str((ROOT / manifest).resolve()): (target, source_path)
        for manifest, target, source_path in IO_GRAPH_CHECK_TARGETS}
    seen, finished = {}, False
    lines = raw.splitlines()
    require(0 < len(lines) <= artifacts.MAX_RECORDS, 'integration-record-bound')
    for line in lines:
        require(len(line) <= artifacts.MAX_LINE_BYTES, 'integration-line-bound')
        if not line.strip():
            continue
        require(not finished, 'integration-after-finished')
        value = json.loads(line, object_pairs_hook=artifacts.unique_object)
        require(isinstance(value, dict), 'integration-record')
        if value.get('reason') == 'build-finished':
            require(value.get('success') is True, 'integration-check-success')
            finished = True
        elif value.get('reason') == 'compiler-artifact':
            manifest = value.get('manifest_path')
            require(isinstance(manifest, str) and len(manifest) <= 4096,
                'integration-manifest')
            manifest = str(Path(manifest).resolve())
            if manifest not in expected:
                continue
            target, profile = value.get('target'), value.get('profile')
            require(isinstance(target, dict) and isinstance(profile, dict),
                'integration-target')
            name, source_path = expected[manifest]
            if target.get('kind') != ['lib'] or profile.get('test') is not True:
                continue
            source_name, features = target.get('src_path'), value.get('features')
            require(isinstance(source_name, str) and len(source_name) <= 4096
                and isinstance(features, list) and len(features) <= 256
                and all(isinstance(feature, str) and len(feature) <= 256
                    for feature in features), 'integration-source-features')
            require(target.get('name') == name and
                Path(source_name).resolve() ==
                    (Path(manifest).parent / source_path).resolve(), 'integration-owner')
            require(value.get('executable') is None, 'check-not-test-executable')
            require(manifest not in seen, 'duplicate-integration-owner')
            seen[manifest] = {'manifest': str(Path(manifest).relative_to(ROOT)),
                'target': name, 'source': source_path, 'libtestTypechecked': True,
                'features': features}
    require(finished and set(seen) == set(expected), 'complete-integration-check')
    return [seen[str((ROOT / manifest).resolve())]
        for manifest, _, _ in IO_GRAPH_CHECK_TARGETS]


def qualify_io_graph(output, revision):
    require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
        and os.environ.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric'
        and os.environ.get('GITHUB_REF_NAME') == IO_GRAPH_BRANCH
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
    receipt = {'schemaVersion': 'lsf.io-reachable-graph.v1', 'status': 'in-progress',
        'sourceRevision': revision, 'selectedCases': list(IO_GRAPH_CASES), 'observations': [],
        'newCases': list(IO_GRAPH_NEW_CASES),
        'phase1ReferenceCase': IO_GRAPH_CASES[-1],
        'fullCostModelQualified': False, 'fullRuntimeSuiteExecuted': False,
        'fullVendorSuiteExecuted': False, 'signedGuestExecuted': False,
        'wasmtimeExecuted': False, 'engineOrComponentExecuted': False,
        'guestComponentCompiled': False, 'cargoCheckBuildScriptsMayCompileHostDependencies': True,
        'hermetic': False, 'compilerImplicitInputsAttested': False,
        'scope': 'actual broker-owned buffers/ring/transfer/Request backing and typed provider future Box; full original-budget physical lifetime; logical node ceilings stay separate; naked copied Vec/imported memory/transitive resource heaps and node-shared tenant backing remain open',
        'limits': {'overallSeconds': 2400, 'buildCommandSeconds': 900,
            'caseProcessSeconds': 60, 'listProcessSeconds': 30, 'cleanupReserveSeconds': 5},
        'newControlBudgetFixtures': {
            'providerFutureBackingControls': {'cases': list(IO_GRAPH_CASES[:2]),
                'memoryBytes': 'actual Layout<F>+64 or one byte less',
                'cpuFuelGrant': 1_000_000_000, 'wallTimeGrantMilliseconds': 5_000},
            'inlineFailureControl': {'case': IO_GRAPH_CASES[2],
                'activationBudgetCreated': False, 'memoryBytes': None,
                'cpuFuelGrant': None, 'wallTimeGrantMilliseconds': None},
            'brokerGraphControls': {'memoryBytes': 1024**2, 'cpuFuelGrant': 100_000,
                'wallTimeGrantMilliseconds': 30_000},
            'installedEngineFuel': False, 'guestExecuted': False,
            'genericHostOrRSSCeilingClaimed': False},
        'integrationCheck': {'executed': False, 'kind': 'Cargo CHECK --tests typecheck and build scripts; no test or engine execution',
            'argv': list(IO_GRAPH_CHECK_ARGS)},
        'fixtureAssembled': False, 'oldCanonicalCasesExecuted': False,
        'oldStreamProgrammeExecuted': False, 'oldProducerProgrammeExecuted': False,
        'cacheRoundtripExecuted': False,
        'commandLedgerBoundary': '19 supervised integration-check/build/library/list/test commands; normal pinned-tool resolver probes retain their existing owner and are not this ledger'}
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

        receipt['stage'] = 'provider-integration-check'
        commands.environment = environment
        commands.command_seconds = 895
        check_ordinal = len(commands.records)
        commands.run('provider-integration-check', tools['cargo'], *IO_GRAPH_CHECK_ARGS)
        check_raw = read_file(logs / f'logs/{check_ordinal:02d}-provider-integration-check.stdout.txt',
            artifacts.MAX_INVENTORY_BYTES)
        receipt['integrationCheck'].update(executed=True,
            inventory=io_graph_check_result(check_raw), stdout=identity(check_raw))

        targets = (
            ('io', IO_GRAPH_CASES, (),
             ('test', '-p', 'latent-capabilities', '--locked', '--lib', '--all-features',
              '--no-run', '--message-format=json'),
             artifacts.Suite('crates/latent-capabilities/Cargo.toml', 'latent_capabilities',
                'src/lib.rs', 'broker::', frozenset(IO_GRAPH_CASES), True)),
        )
        executables = []
        for label, cases, ignored, argv, suite in targets:
            receipt['stage'] = 'build-' + label
            commands.environment = environment
            commands.command_seconds = 895
            ordinal = len(commands.records)
            commands.run('build-' + label, tools['cargo'], *argv)
            artifact = artifacts.read_inventory(logs / f'logs/{ordinal:02d}-build-{label}.stdout.txt',
                ROOT, suite, target=ROOT / 'target')
            executable = file_identity(artifact.executable, label + '-native-backing-controls', 512 * 1024**2)
            receipt[label + 'Executable'] = executable
            executables.append((artifact.executable, executable, label + '-native-backing-controls'))
            run_env = runtime_environment(artifact, label)
            run_env.pop(FIXTURE_ENV, None)
            if label == 'io':
                contract, = [row for row in registry.load()['suites']
                    if row['id'] == 'latent-capabilities.lib.latent-capabilities']
                require(contract['minimumCases'] == 221
                    and set(cases) <= set(contract['expectedCases'])
                    and not set(cases) & set(contract['expectedIgnored']), 'normal-io-suite-contract')
            commands.environment = run_env
            for index, case in enumerate(cases):
                receipt['stage'] = case
                commands.command_seconds = 25
                listed = commands.run(f'{label}-list-{index}', artifact.executable,
                    case, '--exact', *ignored, '--list')
                require(len(listed) <= artifacts.MAX_LIST_BYTES, 'list-bound')
                artifacts.validate_listing(listed, artifacts.Suite(suite.manifest, suite.target,
                    suite.source, case, frozenset((case,)), True))
                commands.command_seconds = 55
                raw = commands.run(f'{label}-case-{index}', artifact.executable,
                    case, '--exact', *ignored, '--show-output', '--test-threads=1')
                receipt['observations'].append(io_graph_result(raw, case))
        require(len(commands.records) == 19 and len(receipt['observations']) == 8,
            'one-check-one-build-one-library-probe-eight-exact-cases')
        require(time.monotonic() < commands.deadline, 'overall-deadline')
        require(source_inputs() == before and source.verify() == checked, 'final-source')
        for path, bound, label in executables:
            require(file_identity(path, label, 512 * 1024**2) == bound, 'final-executable')
        require([file_identity(tools[name], name) for name in sorted(tools)] == pins, 'final-tools')
        artifacts.require_source(ROOT, revision, environment)
        require(time.monotonic() < commands.deadline, 'final-deadline')
        receipt.update(status='passed', sourceAfter=before, sourceUnchanged=True,
            executed=list(IO_GRAPH_CASES), ignored=[])
        write_json(output / 'receipt.json', receipt)
    except BaseException:
        receipt['status'] = 'failed'
        write_json(output / 'FAILED.json', receipt)
        raise
    finally:
        write_json(output / 'commands.json', commands.records)


IO_COPY_BRANCH = 'feat/sdk-736-owned-stream-copy-20261027'
IO_COPY_CAP_PREFIX = 'broker::io::transfer::native_tests::'
IO_COPY_CAP_CASES = tuple(IO_COPY_CAP_PREFIX + name for name in (
    'native_output_copy_is_affine_and_outlives_source_chunk_and_call',
    'native_transfer_factory_is_prepaid_and_confirms_only_actual_capacity'))
IO_COPY_MANAGED_CASE = 'resource_guest_drains_chunks_and_trailers_then_reclaims_all_owners'
IO_COPY_CASES = (*IO_COPY_CAP_CASES, IO_COPY_MANAGED_CASE)
IO_COPY_NEW_CASES = IO_COPY_CAP_CASES[:1]
IO_COPY_CHECK_ARGS = ('check', '--locked', '--tests', '--all-features',
    '-p', 'latent-streams', '--message-format=json')
IO_COPY_CHECK_TARGETS = (
    ('crates/latent-streams/Cargo.toml', 'latent_streams', 'src/lib.rs'),
)
# None may select language budgets, external capsules, or alternate components.
# The managed fixture assembles its ordinary original source component itself.
IO_COPY_FORBIDDEN_FIXTURE_ENV = ('LSF_GUEST_SDK_LANGUAGE', 'LSF_GUEST_CAPSULES',
    'LSF_GENERIC_COMPONENT', 'LSF_GENERIC_FIXTURES', FIXTURE_ENV)


def require_io_copy_environment(environment):
    require(all(name not in environment for name in IO_COPY_FORBIDDEN_FIXTURE_ENV),
        'normal-copy-fixture-environment')


def io_copy_environment(environment):
    for name in IO_COPY_FORBIDDEN_FIXTURE_ENV:
        environment.pop(name, None)
    require_io_copy_environment(environment)
    return environment


def io_copy_result(raw, case):
    require(case in IO_COPY_CASES, 'fixed-case')
    require(len(raw) <= artifacts.MAX_OUTPUT_BYTES, 'case-output-bound')
    require(re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$', raw, re.M)
        == [case.encode()], 'one-exact-success')
    summaries = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; '
        rb'(\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    require(len(summaries) == 1 and summaries[0][:4] == (b'1', b'0', b'0', b'0')
        and int(summaries[0][4]) <= 10000, 'one-executed-no-skip')
    return {'case': case, 'stdout': identity(raw), 'passed': 1, 'failed': 0,
        'ignored': 0, 'filteredOut': int(summaries[0][4]),
        'scope': ('original-Phase3-affine-copy-owner-control' if case in IO_COPY_NEW_CASES
            else 'affected-original-Phase3-transfer-capacity-control' if case in IO_COPY_CAP_CASES
            else 'managed-component-streaming-http-lowering')}


def io_copy_check_result(raw):
    require(len(raw) <= artifacts.MAX_INVENTORY_BYTES, 'integration-inventory-bound')
    expected = {str((ROOT / manifest).resolve()): (target, source_path)
        for manifest, target, source_path in IO_COPY_CHECK_TARGETS}
    seen, finished = {}, False
    lines = raw.splitlines()
    require(0 < len(lines) <= artifacts.MAX_RECORDS, 'integration-record-bound')
    for line in lines:
        require(len(line) <= artifacts.MAX_LINE_BYTES, 'integration-line-bound')
        if not line.strip():
            continue
        require(not finished, 'integration-after-finished')
        value = json.loads(line, object_pairs_hook=artifacts.unique_object)
        require(isinstance(value, dict), 'integration-record')
        if value.get('reason') == 'build-finished':
            require(value.get('success') is True, 'integration-check-success')
            finished = True
        elif value.get('reason') == 'compiler-artifact':
            manifest = value.get('manifest_path')
            require(isinstance(manifest, str) and len(manifest) <= 4096,
                'integration-manifest')
            manifest = str(Path(manifest).resolve())
            if manifest not in expected:
                continue
            target, profile = value.get('target'), value.get('profile')
            require(isinstance(target, dict) and isinstance(profile, dict),
                'integration-target')
            name, source_path = expected[manifest]
            if target.get('kind') != ['lib'] or profile.get('test') is not True:
                continue
            source_name, features = target.get('src_path'), value.get('features')
            require(isinstance(source_name, str) and len(source_name) <= 4096
                and isinstance(features, list) and len(features) <= 256
                and all(isinstance(feature, str) and len(feature) <= 256
                    for feature in features), 'integration-source-features')
            require(target.get('name') == name and
                Path(source_name).resolve() ==
                    (Path(manifest).parent / source_path).resolve(), 'integration-owner')
            require(value.get('executable') is None, 'check-not-test-executable')
            require(manifest not in seen, 'duplicate-integration-owner')
            seen[manifest] = {'manifest': str(Path(manifest).relative_to(ROOT)),
                'target': name, 'source': source_path, 'libtestTypechecked': True,
                'features': features}
    require(finished and set(seen) == set(expected), 'complete-integration-check')
    return [seen[str((ROOT / manifest).resolve())]
        for manifest, _, _ in IO_COPY_CHECK_TARGETS]


def qualify_io_copy(output, revision):
    require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
        and os.environ.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric'
        and os.environ.get('GITHUB_REF_NAME') == IO_COPY_BRANCH
        and os.environ.get('GITHUB_EVENT_NAME') == 'push', 'one-exact-hosted-push')
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
        'owned-output')
    output = fresh(output)
    environment = io_copy_environment(build_environment(output))
    environment.update(CARGO_TARGET_DIR=str(ROOT / 'target'), CARGO_INCREMENTAL='0',
        CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0',
        CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true', CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',
        CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true', CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
    logs = output / 'commands'
    logs.mkdir()
    # Existing five-second reaping reserve remains inside declared caps.
    commands = Commands(ROOT, logs, environment, deadline_seconds=2395, command_seconds=895)
    receipt = {'schemaVersion': 'lsf.owned-stream-copy.v1', 'status': 'in-progress',
        'sourceRevision': revision, 'selectedCases': list(IO_COPY_CASES), 'observations': [],
        'newCases': list(IO_COPY_NEW_CASES), 'affectedTransferCase': IO_COPY_CAP_CASES[1],
        'managedComponentCase': IO_COPY_MANAGED_CASE,
        'fullCostModelQualified': False, 'fullRuntimeSuiteExecuted': False,
        'fullVendorSuiteExecuted': False, 'signedRealNodeGuestExecuted': False,
        'wasmtimeExecuted': False, 'guestComponentCompiled': False,
        'fixtureAssembled': False, 'managedFixtureState': 'not-started',
        'cargoCheckAndBuildMayRunHostBuildScripts': True,
        'managedCaseReallyAssemblesCompilesAndExecutesComponent': True,
        'hermetic': False, 'compilerImplicitInputsAttested': False,
        'scope': 'one actual immutable paid stream copy through networking/HTTP canonical lowering, last shared Slot retirement and final output payload cleanup; arbitrary later caller copies, Blob copies, imported memory, transitive heaps and kernel owners remain separate',
        'limits': {'overallSeconds': 2400, 'buildCommandSeconds': 900,
            'caseProcessSeconds': 60, 'listProcessSeconds': 30, 'cleanupReserveSeconds': 5},
        'budgetFixtures': {
            'brokerCases': {'memoryBytes': 1024**2, 'cpuFuelGrant': 100_000,
                'wallTimeGrantMilliseconds': 30_000, 'engineFuelInstalled': False},
            'managedComponentCase': {'memoryBytes': 16 * 1024**2,
                'cpuFuelGrant': 1_000_000_000_000, 'wallTimeGrantMilliseconds': 5_000,
                'sdkLanguageOverridePermitted': False},
            'genericHostOrRSSCeilingClaimed': False},
        'externalFixtureInputsAbsent': list(IO_COPY_FORBIDDEN_FIXTURE_ENV),
        'integrationCheck': {'executed': False,
            'kind': 'Cargo CHECK --tests typecheck/build scripts for changed stream consumers; no test execution',
            'argv': list(IO_COPY_CHECK_ARGS)},
        'oldCanonicalCasesExecuted': False, 'oldStreamProgrammeExecuted': False,
        'oldProducerProgrammeExecuted': False, 'oldEightGraphProgrammeExecuted': False,
        'cacheRoundtripExecuted': False, 'sdkGuestCompilerInvoked': False,
        'commandLedgerBoundary': '11 supervised check/build/library/list/test commands and22 raw channels; normal pinned-tool resolver probes retain their existing owner and are not this ledger'}
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
        def runtime_environment(artifact, label):
            def probe(argv, *, cwd, env, timeout, maximum):
                require(argv == ['rustc', '--print', 'target-libdir'] and cwd == ROOT
                    and timeout == 30 and maximum == 4096, 'normal-library-probe')
                commands.command_seconds = 25
                require_io_copy_environment(env)
                commands.environment = env
                raw = commands.run(label + '-rust-library-path', tools['rustc'], *argv[1:])
                require(len(raw) <= maximum, 'rust-library-output-bound')
                return 0, raw
            return artifacts.cargo_environment(ROOT, artifact, environment,
                target=ROOT / 'target', execute=probe)

        receipt['stage'] = 'provider-integration-check'
        require_io_copy_environment(environment)
        commands.environment = environment
        commands.command_seconds = 895
        check_ordinal = len(commands.records)
        commands.run('provider-integration-check', tools['cargo'], *IO_COPY_CHECK_ARGS)
        check_raw = read_file(logs / f'logs/{check_ordinal:02d}-provider-integration-check.stdout.txt',
            artifacts.MAX_INVENTORY_BYTES)
        receipt['integrationCheck'].update(executed=True,
            inventory=io_copy_check_result(check_raw), stdout=identity(check_raw))

        targets = (
            ('copy', IO_COPY_CAP_CASES, (),
             ('test', '-p', 'latent-capabilities', '--locked', '--lib', '--all-features',
              '--no-run', '--message-format=json'),
             artifacts.Suite('crates/latent-capabilities/Cargo.toml', 'latent_capabilities',
                'src/lib.rs', IO_COPY_CAP_PREFIX, frozenset(IO_COPY_CAP_CASES), True)),
            ('managed', (IO_COPY_MANAGED_CASE,), (),
             ('test', '-p', 'latent-wasmtime', '--locked', '--test', 'streaming_http',
              '--all-features', '--no-run', '--message-format=json'),
             artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'streaming_http',
                'tests/streaming_http.rs', IO_COPY_MANAGED_CASE,
                frozenset((IO_COPY_MANAGED_CASE,)), True, kind='test')),
        )
        executables = []
        for label, cases, ignored, argv, suite in targets:
            receipt['stage'] = 'build-' + label
            require_io_copy_environment(environment)
            commands.environment = environment
            commands.command_seconds = 895
            ordinal = len(commands.records)
            commands.run('build-' + label, tools['cargo'], *argv)
            artifact = artifacts.read_inventory(logs / f'logs/{ordinal:02d}-build-{label}.stdout.txt',
                ROOT, suite, target=ROOT / 'target')
            executable = file_identity(artifact.executable, label + '-native-backing-controls', 512 * 1024**2)
            receipt[label + 'Executable'] = executable
            executables.append((artifact.executable, executable, label + '-native-backing-controls'))
            run_env = runtime_environment(artifact, label)
            run_env = io_copy_environment(run_env)
            if label == 'copy':
                contract, = [row for row in registry.load()['suites']
                    if row['id'] == 'latent-capabilities.lib.latent-capabilities']
                require(contract['minimumCases'] == 222
                    and set(cases) <= set(contract['expectedCases'])
                    and not set(cases) & set(contract['expectedIgnored']), 'normal-io-suite-contract')
            else:
                contract, = [row for row in registry.load()['suites']
                    if row['id'] == 'latent-wasmtime.test.streaming-http']
                require(contract['minimumCases'] == 14
                    and set(cases) <= set(contract['expectedCases'])
                    and not set(cases) & set(contract['expectedIgnored']), 'normal-managed-suite-contract')
            require_io_copy_environment(run_env)
            commands.environment = run_env
            for index, case in enumerate(cases):
                receipt['stage'] = case
                commands.command_seconds = 25
                listed = commands.run(f'{label}-list-{index}', artifact.executable,
                    case, '--exact', *ignored, '--list')
                require(len(listed) <= artifacts.MAX_LIST_BYTES, 'list-bound')
                artifacts.validate_listing(listed, artifacts.Suite(suite.manifest, suite.target,
                    suite.source, case, frozenset((case,)), True))
                commands.command_seconds = 55
                if label == 'managed':
                    receipt.update(managedFixtureState='started-outcome-pending',
                        wasmtimeExecuted=None, guestComponentCompiled=None, fixtureAssembled=None)
                require_io_copy_environment(commands.environment)
                raw = commands.run(f'{label}-case-{index}', artifact.executable,
                    case, '--exact', *ignored, '--show-output', '--test-threads=1')
                receipt['observations'].append(io_copy_result(raw, case))
                if label == 'managed':
                    receipt.update(managedFixtureState='passed', wasmtimeExecuted=True,
                        guestComponentCompiled=True, fixtureAssembled=True)
        require(len(commands.records) == 11 and len(receipt['observations']) == 3,
            'one-check-two-builds-two-library-probes-three-exact-cases')
        require(time.monotonic() < commands.deadline, 'overall-deadline')
        require(source_inputs() == before and source.verify() == checked, 'final-source')
        for path, bound, label in executables:
            require(file_identity(path, label, 512 * 1024**2) == bound, 'final-executable')
        require([file_identity(tools[name], name) for name in sorted(tools)] == pins, 'final-tools')
        artifacts.require_source(ROOT, revision, environment)
        require_io_copy_environment(environment)
        require_io_copy_environment(commands.environment)
        require(time.monotonic() < commands.deadline, 'final-deadline')
        receipt.update(status='passed', sourceAfter=before, sourceUnchanged=True,
            executed=list(IO_COPY_CASES), ignored=[])
        write_json(output / 'receipt.json', receipt)
    except BaseException:
        receipt['status'] = 'failed'
        write_json(output / 'FAILED.json', receipt)
        raise
    finally:
        write_json(output / 'commands.json', commands.records)


BLOB_COPY_BRANCH = 'feat/sdk-736-blob-copy-native-20261027'
BLOB_COPY_CAP_PREFIX = 'broker::pools::admission::native_tests::'
BLOB_COPY_CAP_CASES = tuple(BLOB_COPY_CAP_PREFIX + name for name in (
    'native_blob_copy_is_affine_and_retains_source_or_copy_until_last_use',
    'native_blob_copy_refuses_original_budget_and_foreign_operation_before_copy',
    'native_blob_copy_rejects_swapped_pool_call_request_and_io_identity'))
BLOB_COPY_MANAGED_CASE = 'guest_writes_seals_and_reads_exact_bounded_chunks'
BLOB_COPY_CASES = (*BLOB_COPY_CAP_CASES, BLOB_COPY_MANAGED_CASE)
BLOB_COPY_NEW_CASES = BLOB_COPY_CAP_CASES
BLOB_COPY_CHECK_ARGS = ('check', '--locked', '--tests', '--all-features',
    '-p', 'latent-blobs', '-p', 'latent-wasmtime', '--message-format=json')
BLOB_COPY_CHECK_TARGETS = (
    ('crates/latent-blobs/Cargo.toml', 'latent_blobs', 'src/lib.rs'),
    ('crates/latent-wasmtime/Cargo.toml', 'latent_wasmtime', 'src/lib.rs'),
)
# None may select language budgets, external capsules, or alternate components.
# The managed fixture assembles its ordinary original source component itself.
BLOB_COPY_FORBIDDEN_FIXTURE_ENV = ('LSF_GUEST_SDK_LANGUAGE', 'LSF_GUEST_CAPSULES',
    'LSF_GENERIC_COMPONENT', 'LSF_GENERIC_FIXTURES', FIXTURE_ENV)


def blob_copy_result(raw, case):
    require(case in BLOB_COPY_CASES, 'fixed-case')
    require(len(raw) <= artifacts.MAX_OUTPUT_BYTES, 'case-output-bound')
    require(re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$', raw, re.M)
        == [case.encode()], 'one-exact-success')
    summaries = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; '
        rb'(\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    require(len(summaries) == 1 and summaries[0][:4] == (b'1', b'0', b'0', b'0')
        and int(summaries[0][4]) <= 10000, 'one-executed-no-skip')
    return {'case': case, 'stdout': identity(raw), 'passed': 1, 'failed': 0,
        'ignored': 0, 'filteredOut': int(summaries[0][4]),
        'scope': ('original-Phase3-affine-blob-copy-and-pooled-request-control'
            if case in BLOB_COPY_CAP_CASES else 'managed-component-local-blob-chunk-lowering')}


def blob_copy_check_result(raw):
    require(len(raw) <= artifacts.MAX_INVENTORY_BYTES, 'integration-inventory-bound')
    expected = {str((ROOT / manifest).resolve()): (target, source_path)
        for manifest, target, source_path in BLOB_COPY_CHECK_TARGETS}
    seen, finished = {}, False
    lines = raw.splitlines()
    require(0 < len(lines) <= artifacts.MAX_RECORDS, 'integration-record-bound')
    for line in lines:
        require(len(line) <= artifacts.MAX_LINE_BYTES, 'integration-line-bound')
        if not line.strip():
            continue
        require(not finished, 'integration-after-finished')
        value = json.loads(line, object_pairs_hook=artifacts.unique_object)
        require(isinstance(value, dict), 'integration-record')
        if value.get('reason') == 'build-finished':
            require(value.get('success') is True, 'integration-check-success')
            finished = True
        elif value.get('reason') == 'compiler-artifact':
            manifest = value.get('manifest_path')
            require(isinstance(manifest, str) and len(manifest) <= 4096,
                'integration-manifest')
            manifest = str(Path(manifest).resolve())
            if manifest not in expected:
                continue
            target, profile = value.get('target'), value.get('profile')
            require(isinstance(target, dict) and isinstance(profile, dict),
                'integration-target')
            name, source_path = expected[manifest]
            if target.get('kind') != ['lib'] or profile.get('test') is not True:
                continue
            source_name, features = target.get('src_path'), value.get('features')
            require(isinstance(source_name, str) and len(source_name) <= 4096
                and isinstance(features, list) and len(features) <= 256
                and all(isinstance(feature, str) and len(feature) <= 256
                    for feature in features), 'integration-source-features')
            require(target.get('name') == name and
                Path(source_name).resolve() ==
                    (Path(manifest).parent / source_path).resolve(), 'integration-owner')
            require(value.get('executable') is None, 'check-not-test-executable')
            require(manifest not in seen, 'duplicate-integration-owner')
            seen[manifest] = {'manifest': str(Path(manifest).relative_to(ROOT)),
                'target': name, 'source': source_path, 'libtestTypechecked': True,
                'features': features}
    require(finished and set(seen) == set(expected), 'complete-integration-check')
    return [seen[str((ROOT / manifest).resolve())]
        for manifest, _, _ in BLOB_COPY_CHECK_TARGETS]


def qualify_blob_copy(output, revision):
    require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
        and os.environ.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric'
        and os.environ.get('GITHUB_REF_NAME') == BLOB_COPY_BRANCH
        and os.environ.get('GITHUB_EVENT_NAME') == 'push', 'one-exact-hosted-push')
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
        'owned-output')
    output = fresh(output)
    environment = io_copy_environment(build_environment(output))
    environment.update(CARGO_TARGET_DIR=str(ROOT / 'target'), CARGO_INCREMENTAL='0',
        CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0',
        CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true', CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',
        CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true', CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
    logs = output / 'commands'
    logs.mkdir()
    # Existing five-second reaping reserve remains inside declared caps.
    commands = Commands(ROOT, logs, environment, deadline_seconds=2395, command_seconds=895)
    receipt = {'schemaVersion': 'lsf.owned-blob-copy.v1', 'status': 'in-progress',
        'sourceRevision': revision, 'selectedCases': list(BLOB_COPY_CASES), 'observations': [],
        'newCases': list(BLOB_COPY_NEW_CASES), 'oldTransferCasesExecuted': False,
        'managedComponentCase': BLOB_COPY_MANAGED_CASE,
        'fullCostModelQualified': False, 'fullRuntimeSuiteExecuted': False,
        'fullVendorSuiteExecuted': False, 'signedRealNodeGuestExecuted': False,
        'wasmtimeExecuted': False, 'guestComponentCompiled': False,
        'fixtureAssembled': False, 'managedFixtureState': 'not-started',
        'cargoCheckAndBuildMayRunHostBuildScripts': True,
        'managedCaseReallyAssemblesCompilesAndExecutesComponent': True,
        'hermetic': False, 'compilerImplicitInputsAttested': False,
        'scope': 'one actual immutable prepaid Blob copy through canonical lowering, exact operation/request/copy identity and either source/copy last-use retirement; arbitrary later caller copies, imported memory, transitive heaps and kernel owners remain separate',
        'limits': {'overallSeconds': 2400, 'buildCommandSeconds': 900,
            'caseProcessSeconds': 60, 'listProcessSeconds': 30, 'cleanupReserveSeconds': 5},
        'budgetFixtures': {
            'brokerCases': {'memoryBytes': 1024**2, 'cpuFuelGrant': 100_000,
                'wallTimeGrantMilliseconds': 30_000, 'engineFuelInstalled': False},
            'managedComponentCase': {'memoryBytes': 16 * 1024**2,
                'cpuFuelGrant': 1_000_000_000_000, 'wallTimeGrantMilliseconds': 5_000,
                'sdkLanguageOverridePermitted': False},
            'genericHostOrRSSCeilingClaimed': False},
        'externalFixtureInputsAbsent': list(BLOB_COPY_FORBIDDEN_FIXTURE_ENV),
        'integrationCheck': {'executed': False,
            'kind': 'Cargo CHECK --tests/all-features for actual local+S3 providers and installed Wasmtime consumers; no test execution',
            'argv': list(BLOB_COPY_CHECK_ARGS)},
        'oldCanonicalCasesExecuted': False, 'oldStreamProgrammeExecuted': False,
        'oldProducerProgrammeExecuted': False, 'oldEightGraphProgrammeExecuted': False, 'oldThreeCopyProgrammeExecuted': False,
        'cacheRoundtripExecuted': False, 'sdkGuestCompilerInvoked': False,
        'commandLedgerBoundary': '13 supervised check/build/library/list/test commands and26 raw channels; normal pinned-tool resolver probes retain their existing owner and are not this ledger'}
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
        def runtime_environment(artifact, label):
            def probe(argv, *, cwd, env, timeout, maximum):
                require(argv == ['rustc', '--print', 'target-libdir'] and cwd == ROOT
                    and timeout == 30 and maximum == 4096, 'normal-library-probe')
                commands.command_seconds = 25
                require_io_copy_environment(env)
                commands.environment = env
                raw = commands.run(label + '-rust-library-path', tools['rustc'], *argv[1:])
                require(len(raw) <= maximum, 'rust-library-output-bound')
                return 0, raw
            return artifacts.cargo_environment(ROOT, artifact, environment,
                target=ROOT / 'target', execute=probe)

        receipt['stage'] = 'provider-integration-check'
        require_io_copy_environment(environment)
        commands.environment = environment
        commands.command_seconds = 895
        check_ordinal = len(commands.records)
        commands.run('provider-integration-check', tools['cargo'], *BLOB_COPY_CHECK_ARGS)
        check_raw = read_file(logs / f'logs/{check_ordinal:02d}-provider-integration-check.stdout.txt',
            artifacts.MAX_INVENTORY_BYTES)
        receipt['integrationCheck'].update(executed=True,
            inventory=blob_copy_check_result(check_raw), stdout=identity(check_raw))

        targets = (
            ('copy', BLOB_COPY_CAP_CASES, (),
             ('test', '-p', 'latent-capabilities', '--locked', '--lib', '--all-features',
              '--no-run', '--message-format=json'),
             artifacts.Suite('crates/latent-capabilities/Cargo.toml', 'latent_capabilities',
                'src/lib.rs', BLOB_COPY_CAP_PREFIX, frozenset(BLOB_COPY_CAP_CASES), True)),
            ('managed', (BLOB_COPY_MANAGED_CASE,), (),
             ('test', '-p', 'latent-wasmtime', '--locked', '--test', 'local_blobs',
              '--all-features', '--no-run', '--message-format=json'),
             artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'local_blobs',
                'tests/local_blobs.rs', BLOB_COPY_MANAGED_CASE,
                frozenset((BLOB_COPY_MANAGED_CASE,)), True, kind='test')),
        )
        executables = []
        for label, cases, ignored, argv, suite in targets:
            receipt['stage'] = 'build-' + label
            require_io_copy_environment(environment)
            commands.environment = environment
            commands.command_seconds = 895
            ordinal = len(commands.records)
            commands.run('build-' + label, tools['cargo'], *argv)
            artifact = artifacts.read_inventory(logs / f'logs/{ordinal:02d}-build-{label}.stdout.txt',
                ROOT, suite, target=ROOT / 'target')
            executable = file_identity(artifact.executable, label + '-native-backing-controls', 512 * 1024**2)
            receipt[label + 'Executable'] = executable
            executables.append((artifact.executable, executable, label + '-native-backing-controls'))
            run_env = runtime_environment(artifact, label)
            run_env = io_copy_environment(run_env)
            if label == 'copy':
                contract, = [row for row in registry.load()['suites']
                    if row['id'] == 'latent-capabilities.lib.latent-capabilities']
                require(contract['minimumCases'] == 225
                    and set(cases) <= set(contract['expectedCases'])
                    and not set(cases) & set(contract['expectedIgnored']), 'normal-io-suite-contract')
            else:
                contract, = [row for row in registry.load()['suites']
                    if row['id'] == 'latent-wasmtime.test.local-blobs']
                require(contract['minimumCases'] == 10
                    and set(cases) <= set(contract['expectedCases'])
                    and not set(cases) & set(contract['expectedIgnored']), 'normal-managed-suite-contract')
            require_io_copy_environment(run_env)
            commands.environment = run_env
            for index, case in enumerate(cases):
                receipt['stage'] = case
                commands.command_seconds = 25
                listed = commands.run(f'{label}-list-{index}', artifact.executable,
                    case, '--exact', *ignored, '--list')
                require(len(listed) <= artifacts.MAX_LIST_BYTES, 'list-bound')
                artifacts.validate_listing(listed, artifacts.Suite(suite.manifest, suite.target,
                    suite.source, case, frozenset((case,)), True))
                commands.command_seconds = 55
                if label == 'managed':
                    receipt.update(managedFixtureState='started-outcome-pending',
                        wasmtimeExecuted=None, guestComponentCompiled=None, fixtureAssembled=None)
                require_io_copy_environment(commands.environment)
                raw = commands.run(f'{label}-case-{index}', artifact.executable,
                    case, '--exact', *ignored, '--show-output', '--test-threads=1')
                receipt['observations'].append(blob_copy_result(raw, case))
                if label == 'managed':
                    receipt.update(managedFixtureState='passed', wasmtimeExecuted=True,
                        guestComponentCompiled=True, fixtureAssembled=True)
        require(len(commands.records) == 13 and len(receipt['observations']) == 4,
            'one-check-two-builds-two-library-probes-four-exact-cases')
        require(time.monotonic() < commands.deadline, 'overall-deadline')
        require(source_inputs() == before and source.verify() == checked, 'final-source')
        for path, bound, label in executables:
            require(file_identity(path, label, 512 * 1024**2) == bound, 'final-executable')
        require([file_identity(tools[name], name) for name in sorted(tools)] == pins, 'final-tools')
        artifacts.require_source(ROOT, revision, environment)
        require_io_copy_environment(environment)
        require_io_copy_environment(commands.environment)
        require(time.monotonic() < commands.deadline, 'final-deadline')
        receipt.update(status='passed', sourceAfter=before, sourceUnchanged=True,
            executed=list(BLOB_COPY_CASES), ignored=[])
        write_json(output / 'receipt.json', receipt)
    except BaseException:
        receipt['status'] = 'failed'
        write_json(output / 'FAILED.json', receipt)
        raise
    finally:
        write_json(output / 'commands.json', commands.records)


BLOB_INPUT_BRANCH = 'feat/sdk-736-blob-input-native-20261027'
BLOB_INPUT_CAP_PREFIX = 'broker::pools::admission::native_tests::'
BLOB_INPUT_CAP_CASES = tuple(BLOB_INPUT_CAP_PREFIX + name for name in (
    'native_blob_input_bridge_refuses_original_budget_before_materialization',
    'native_blob_input_bridge_keeps_credit_through_real_worker_observer_cancel',
    'native_blob_input_bridge_owns_borrowed_bytes_and_empty_range_without_escape'))
BLOB_INPUT_MANAGED_CASE = 'guest_writes_seals_and_reads_exact_bounded_chunks'
BLOB_INPUT_CASES = (*BLOB_INPUT_CAP_CASES, BLOB_INPUT_MANAGED_CASE)
BLOB_INPUT_NEW_CASES = BLOB_INPUT_CAP_CASES
BLOB_INPUT_CHECK_ARGS = ('check', '--locked', '--tests', '--all-features',
    '-p', 'latent-blobs', '-p', 'latent-wasmtime', '--message-format=json')
BLOB_INPUT_CHECK_TARGETS = (
    ('crates/latent-blobs/Cargo.toml', 'latent_blobs', 'src/lib.rs'),
    ('crates/latent-wasmtime/Cargo.toml', 'latent_wasmtime', 'src/lib.rs'),
)
# None may select language budgets, external capsules, or alternate components.
# The managed fixture assembles its ordinary original source component itself.
BLOB_INPUT_FORBIDDEN_FIXTURE_ENV = ('LSF_GUEST_SDK_LANGUAGE', 'LSF_GUEST_CAPSULES',
    'LSF_GENERIC_COMPONENT', 'LSF_GENERIC_FIXTURES', FIXTURE_ENV)


def blob_input_result(raw, case):
    require(case in BLOB_INPUT_CASES, 'fixed-case')
    require(len(raw) <= artifacts.MAX_OUTPUT_BYTES, 'case-output-bound')
    require(re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$', raw, re.M)
        == [case.encode()], 'one-exact-success')
    summaries = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; '
        rb'(\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    require(len(summaries) == 1 and summaries[0][:4] == (b'1', b'0', b'0', b'0')
        and int(summaries[0][4]) <= 10000, 'one-executed-no-skip')
    return {'case': case, 'stdout': identity(raw), 'passed': 1, 'failed': 0,
        'ignored': 0, 'filteredOut': int(summaries[0][4]),
        'scope': ('original-Phase3-prepaid-blob-input-bridge-control'
            if case in BLOB_INPUT_CAP_CASES else 'managed-component-local-blob-input-and-readback')}


def blob_input_check_result(raw):
    require(len(raw) <= artifacts.MAX_INVENTORY_BYTES, 'integration-inventory-bound')
    expected = {str((ROOT / manifest).resolve()): (target, source_path)
        for manifest, target, source_path in BLOB_INPUT_CHECK_TARGETS}
    seen, finished = {}, False
    lines = raw.splitlines()
    require(0 < len(lines) <= artifacts.MAX_RECORDS, 'integration-record-bound')
    for line in lines:
        require(len(line) <= artifacts.MAX_LINE_BYTES, 'integration-line-bound')
        if not line.strip():
            continue
        require(not finished, 'integration-after-finished')
        value = json.loads(line, object_pairs_hook=artifacts.unique_object)
        require(isinstance(value, dict), 'integration-record')
        if value.get('reason') == 'build-finished':
            require(value.get('success') is True, 'integration-check-success')
            finished = True
        elif value.get('reason') == 'compiler-artifact':
            manifest = value.get('manifest_path')
            require(isinstance(manifest, str) and len(manifest) <= 4096,
                'integration-manifest')
            manifest = str(Path(manifest).resolve())
            if manifest not in expected:
                continue
            target, profile = value.get('target'), value.get('profile')
            require(isinstance(target, dict) and isinstance(profile, dict),
                'integration-target')
            name, source_path = expected[manifest]
            if target.get('kind') != ['lib'] or profile.get('test') is not True:
                continue
            source_name, features = target.get('src_path'), value.get('features')
            require(isinstance(source_name, str) and len(source_name) <= 4096
                and isinstance(features, list) and len(features) <= 256
                and all(isinstance(feature, str) and len(feature) <= 256
                    for feature in features), 'integration-source-features')
            require(target.get('name') == name and
                Path(source_name).resolve() ==
                    (Path(manifest).parent / source_path).resolve(), 'integration-owner')
            require(value.get('executable') is None, 'check-not-test-executable')
            require(manifest not in seen, 'duplicate-integration-owner')
            seen[manifest] = {'manifest': str(Path(manifest).relative_to(ROOT)),
                'target': name, 'source': source_path, 'libtestTypechecked': True,
                'features': features}
    require(finished and set(seen) == set(expected), 'complete-integration-check')
    return [seen[str((ROOT / manifest).resolve())]
        for manifest, _, _ in BLOB_INPUT_CHECK_TARGETS]


def qualify_blob_input(output, revision):
    require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
        and os.environ.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric'
        and os.environ.get('GITHUB_REF_NAME') == BLOB_INPUT_BRANCH
        and os.environ.get('GITHUB_EVENT_NAME') == 'push', 'one-exact-hosted-push')
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
        'owned-output')
    output = fresh(output)
    environment = io_copy_environment(build_environment(output))
    environment.update(CARGO_TARGET_DIR=str(ROOT / 'target'), CARGO_INCREMENTAL='0',
        CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0',
        CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true', CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',
        CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true', CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
    logs = output / 'commands'
    logs.mkdir()
    # Existing five-second reaping reserve remains inside declared caps.
    commands = Commands(ROOT, logs, environment, deadline_seconds=2395, command_seconds=895)
    receipt = {'schemaVersion': 'lsf.owned-blob-input.v1', 'status': 'in-progress',
        'sourceRevision': revision, 'selectedCases': list(BLOB_INPUT_CASES), 'observations': [],
        'newCases': list(BLOB_INPUT_NEW_CASES), 'oldTransferCasesExecuted': False, 'oldBlobOutputNativeCasesExecuted': False,
        'managedComponentCase': BLOB_INPUT_MANAGED_CASE,
        'fullCostModelQualified': False, 'fullRuntimeSuiteExecuted': False,
        'fullVendorSuiteExecuted': False, 'signedRealNodeGuestExecuted': False,
        'wasmtimeExecuted': False, 'guestComponentCompiled': False,
        'fixtureAssembled': False, 'managedFixtureState': 'not-started',
        'cargoCheckAndBuildMayRunHostBuildScripts': True,
        'managedCaseReallyAssemblesCompilesAndExecutesComponent': True,
        'hermetic': False, 'compilerImplicitInputsAttested': False,
        'scope': 'borrowed Blob write ingress through the original admission-owned IoBuffer before materialization, actual worker cancellation retention and original request retirement; caller-preallocated Vec API, HTTP strings/body, transitive ProtocolPages/heaps and kernel owners remain separate',
        'limits': {'overallSeconds': 2400, 'buildCommandSeconds': 900,
            'caseProcessSeconds': 60, 'listProcessSeconds': 30, 'cleanupReserveSeconds': 5},
        'budgetFixtures': {
            'brokerCases': {'memoryBytes': 1024**2, 'cpuFuelGrant': 100_000,
                'wallTimeGrantMilliseconds': 30_000, 'engineFuelInstalled': False},
            'managedComponentCase': {'memoryBytes': 16 * 1024**2,
                'cpuFuelGrant': 1_000_000_000_000, 'wallTimeGrantMilliseconds': 5_000,
                'sdkLanguageOverridePermitted': False},
            'genericHostOrRSSCeilingClaimed': False},
        'externalFixtureInputsAbsent': list(BLOB_INPUT_FORBIDDEN_FIXTURE_ENV),
        'integrationCheck': {'executed': False,
            'kind': 'Cargo CHECK --tests/all-features for actual local+S3 providers and installed Wasmtime consumers; no test execution',
            'argv': list(BLOB_INPUT_CHECK_ARGS)},
        'oldCanonicalCasesExecuted': False, 'oldStreamProgrammeExecuted': False,
        'oldProducerProgrammeExecuted': False, 'oldEightGraphProgrammeExecuted': False, 'oldThreeCopyProgrammeExecuted': False,
        'cacheRoundtripExecuted': False, 'sdkGuestCompilerInvoked': False,
        'commandLedgerBoundary': '13 supervised check/build/library/list/test commands and26 raw channels; normal pinned-tool resolver probes retain their existing owner and are not this ledger'}
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
        def runtime_environment(artifact, label):
            def probe(argv, *, cwd, env, timeout, maximum):
                require(argv == ['rustc', '--print', 'target-libdir'] and cwd == ROOT
                    and timeout == 30 and maximum == 4096, 'normal-library-probe')
                commands.command_seconds = 25
                require_io_copy_environment(env)
                commands.environment = env
                raw = commands.run(label + '-rust-library-path', tools['rustc'], *argv[1:])
                require(len(raw) <= maximum, 'rust-library-output-bound')
                return 0, raw
            return artifacts.cargo_environment(ROOT, artifact, environment,
                target=ROOT / 'target', execute=probe)

        receipt['stage'] = 'provider-integration-check'
        require_io_copy_environment(environment)
        commands.environment = environment
        commands.command_seconds = 895
        check_ordinal = len(commands.records)
        commands.run('provider-integration-check', tools['cargo'], *BLOB_INPUT_CHECK_ARGS)
        check_raw = read_file(logs / f'logs/{check_ordinal:02d}-provider-integration-check.stdout.txt',
            artifacts.MAX_INVENTORY_BYTES)
        receipt['integrationCheck'].update(executed=True,
            inventory=blob_input_check_result(check_raw), stdout=identity(check_raw))

        targets = (
            ('copy', BLOB_INPUT_CAP_CASES, (),
             ('test', '-p', 'latent-capabilities', '--locked', '--lib', '--all-features',
              '--no-run', '--message-format=json'),
             artifacts.Suite('crates/latent-capabilities/Cargo.toml', 'latent_capabilities',
                'src/lib.rs', BLOB_INPUT_CAP_PREFIX, frozenset(BLOB_INPUT_CAP_CASES), True)),
            ('managed', (BLOB_INPUT_MANAGED_CASE,), (),
             ('test', '-p', 'latent-wasmtime', '--locked', '--test', 'local_blobs',
              '--all-features', '--no-run', '--message-format=json'),
             artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'local_blobs',
                'tests/local_blobs.rs', BLOB_INPUT_MANAGED_CASE,
                frozenset((BLOB_INPUT_MANAGED_CASE,)), True, kind='test')),
        )
        executables = []
        for label, cases, ignored, argv, suite in targets:
            receipt['stage'] = 'build-' + label
            require_io_copy_environment(environment)
            commands.environment = environment
            commands.command_seconds = 895
            ordinal = len(commands.records)
            commands.run('build-' + label, tools['cargo'], *argv)
            artifact = artifacts.read_inventory(logs / f'logs/{ordinal:02d}-build-{label}.stdout.txt',
                ROOT, suite, target=ROOT / 'target')
            executable = file_identity(artifact.executable, label + '-native-backing-controls', 512 * 1024**2)
            receipt[label + 'Executable'] = executable
            executables.append((artifact.executable, executable, label + '-native-backing-controls'))
            run_env = runtime_environment(artifact, label)
            run_env = io_copy_environment(run_env)
            if label == 'copy':
                contract, = [row for row in registry.load()['suites']
                    if row['id'] == 'latent-capabilities.lib.latent-capabilities']
                require(contract['minimumCases'] == 228
                    and set(cases) <= set(contract['expectedCases'])
                    and not set(cases) & set(contract['expectedIgnored']), 'normal-io-suite-contract')
            else:
                contract, = [row for row in registry.load()['suites']
                    if row['id'] == 'latent-wasmtime.test.local-blobs']
                require(contract['minimumCases'] == 10
                    and set(cases) <= set(contract['expectedCases'])
                    and not set(cases) & set(contract['expectedIgnored']), 'normal-managed-suite-contract')
            require_io_copy_environment(run_env)
            commands.environment = run_env
            for index, case in enumerate(cases):
                receipt['stage'] = case
                commands.command_seconds = 25
                listed = commands.run(f'{label}-list-{index}', artifact.executable,
                    case, '--exact', *ignored, '--list')
                require(len(listed) <= artifacts.MAX_LIST_BYTES, 'list-bound')
                artifacts.validate_listing(listed, artifacts.Suite(suite.manifest, suite.target,
                    suite.source, case, frozenset((case,)), True))
                commands.command_seconds = 55
                if label == 'managed':
                    receipt.update(managedFixtureState='started-outcome-pending',
                        wasmtimeExecuted=None, guestComponentCompiled=None, fixtureAssembled=None)
                require_io_copy_environment(commands.environment)
                raw = commands.run(f'{label}-case-{index}', artifact.executable,
                    case, '--exact', *ignored, '--show-output', '--test-threads=1')
                receipt['observations'].append(blob_input_result(raw, case))
                if label == 'managed':
                    receipt.update(managedFixtureState='passed', wasmtimeExecuted=True,
                        guestComponentCompiled=True, fixtureAssembled=True)
        require(len(commands.records) == 13 and len(receipt['observations']) == 4,
            'one-check-two-builds-two-library-probes-four-exact-cases')
        require(time.monotonic() < commands.deadline, 'overall-deadline')
        require(source_inputs() == before and source.verify() == checked, 'final-source')
        for path, bound, label in executables:
            require(file_identity(path, label, 512 * 1024**2) == bound, 'final-executable')
        require([file_identity(tools[name], name) for name in sorted(tools)] == pins, 'final-tools')
        artifacts.require_source(ROOT, revision, environment)
        require_io_copy_environment(environment)
        require_io_copy_environment(commands.environment)
        require(time.monotonic() < commands.deadline, 'final-deadline')
        receipt.update(status='passed', sourceAfter=before, sourceUnchanged=True,
            executed=list(BLOB_INPUT_CASES), ignored=[])
        write_json(output / 'receipt.json', receipt)
    except BaseException:
        receipt['status'] = 'failed'
        write_json(output / 'FAILED.json', receipt)
        raise
    finally:
        write_json(output / 'commands.json', commands.records)


HTTP_INPUT_BRANCH = 'feat/sdk-736-http-input-native-20261027'
HTTP_INPUT_NATIVE_PREFIX = 'tests::ownership::'
HTTP_INPUT_NATIVE_CASES = tuple(HTTP_INPUT_NATIVE_PREFIX + name for name in (
    'native_http_ingress_refuses_before_materialization_and_unpolled_cancel_returns_credit',
    'native_http_ingress_rejects_equal_grant_foreign_session_before_body_copy',
    'native_http_ingress_bytes_and_driver_token_keep_original_credit_until_actual_last_drop',
    'native_http_ingress_one_slot_redirect_retires_hop_without_retagging_credit',
    'native_http_ingress_pending_real_driver_cancellation_retires_original_credit',
    'native_http_ingress_nested_header_limit_refuses_without_payload_copy'))
HTTP_INPUT_LEGACY_CASE = HTTP_INPUT_NATIVE_PREFIX + 'shared_idle_connection_owns_no_activation_and_reuses_the_real_socket'
HTTP_INPUT_API_CASES = (
    'canonical_utf8_view_uses_same_store_for_all_encodings_and_exact_destinations',
    'canonical_utf8_view_rejects_foreign_store_without_poisoning_original')
HTTP_INPUT_MANAGED_CASE = 'real_guest_executes_every_method_and_reclaims_the_same_warm_cell'
HTTP_INPUT_CASES = (*HTTP_INPUT_NATIVE_CASES, HTTP_INPUT_LEGACY_CASE, *HTTP_INPUT_API_CASES, HTTP_INPUT_MANAGED_CASE)
HTTP_INPUT_NEW_CASES = (*HTTP_INPUT_NATIVE_CASES, *HTTP_INPUT_API_CASES)
HTTP_INPUT_FORBIDDEN_FIXTURE_ENV = IO_COPY_FORBIDDEN_FIXTURE_ENV
HTTP_INPUT_API_MARKERS = {
    HTTP_INPUT_API_CASES[0]: b'http-utf8-view forms=4 empty=1 malformed=1 unaligned=1 oob=1 exact=4 short=4 long=4 fresh=1',
    HTTP_INPUT_API_CASES[1]: b'http-utf8-view wrong-store=refused original-store=fresh',
}


def http_input_result(raw, case):
    require(case in HTTP_INPUT_CASES, 'fixed-case')
    require(len(raw) <= artifacts.MAX_OUTPUT_BYTES, 'case-output-bound')
    require(re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$', raw, re.M)
        == [case.encode()], 'one-exact-success')
    summaries = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; '
        rb'(\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    require(len(summaries) == 1 and summaries[0][:4] == (b'1', b'0', b'0', b'0')
        and int(summaries[0][4]) <= 10000, 'one-executed-no-skip')
    scope = ('original-Phase3-HTTP-ingress-control' if case in HTTP_INPUT_NATIVE_CASES else
        'unchanged-Phase3-preallocated-HTTP-API-reference' if case == HTTP_INPUT_LEGACY_CASE else
        'actual-public-canonical-utf8-view-isolated-Store-no-ActivationBudget' if case in HTTP_INPUT_API_CASES else
        'installed-canonical-HTTP-all-seven-methods-original-Store-cleanup')
    markers = re.findall(rb'^(http-utf8-view [^\r\n]+)$', raw, re.M)
    require(markers == ([HTTP_INPUT_API_MARKERS[case]] if case in HTTP_INPUT_API_MARKERS else []),
        'actual-api-marker')
    return {'case': case, 'stdout': identity(raw), 'passed': 1, 'failed': 0,
        'ignored': 0, 'filteredOut': int(summaries[0][4]), 'scope': scope,
        'apiMarker': markers[0].decode() if markers else None}


def qualify_http_input(output, revision):
    require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
        and os.environ.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric'
        and os.environ.get('GITHUB_REF_NAME') == HTTP_INPUT_BRANCH
        and os.environ.get('GITHUB_EVENT_NAME') == 'push', 'one-exact-hosted-push')
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
        'owned-output')
    output = fresh(output)
    environment = io_copy_environment(build_environment(output))
    environment.update(CARGO_TARGET_DIR=str(ROOT / 'target'), CARGO_INCREMENTAL='0',
        CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0',
        CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true', CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',
        CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true', CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
    logs = output / 'commands'
    logs.mkdir()
    # Existing five-second reaping reserve remains inside declared caps.
    commands = Commands(ROOT, logs, environment, deadline_seconds=2395, command_seconds=895)
    receipt = {'schemaVersion': 'lsf.owned-http-input.v1', 'status': 'in-progress',
        'sourceRevision': revision, 'selectedCases': list(HTTP_INPUT_CASES), 'observations': [],
        'newCases': list(HTTP_INPUT_NEW_CASES), 'oldTransferCasesExecuted': False, 'oldBlobOutputNativeCasesExecuted': False, 'oldBlobInputProgrammeExecuted': False,
        'privateVendorUnitTestsExecuted': False, 'fullHttpSuiteExecuted': False,
        'managedComponentCase': HTTP_INPUT_MANAGED_CASE,
        'directApiCasesStarted': [], 'directApiCasesPassed': [],
        'legacyReferenceCase': HTTP_INPUT_LEGACY_CASE, 'legacyReferenceProfile': 'Phase3-preallocated-API-not-Phase1',
        'fullCostModelQualified': False, 'fullRuntimeSuiteExecuted': False,
        'fullVendorSuiteExecuted': False, 'signedRealNodeGuestExecuted': False,
        'wasmtimeExecuted': False, 'guestComponentCompiled': False,
        'managedFixtureAssembled': False, 'managedFixtureState': 'not-started',
        'cargoBuildMayRunHostBuildScripts': True,
        'managedCaseReallyAssemblesCompilesAndExecutesComponent': True,
        'hermetic': False, 'compilerImplicitInputsAttested': False,
        'scope': 'original-session HTTP ingress exact prepayment, current-hop strong owner and immutable native-credit token through Bytes/driver/redirect; actual canonical utf8_view API and one unchanged preallocated request reference; parser/redirect/wire/Bytes internal/control/TLS/transitive costs stay separate',
        'limits': {'overallSeconds': 2400, 'buildCommandSeconds': 900,
            'caseProcessSeconds': 60, 'listProcessSeconds': 30, 'cleanupReserveSeconds': 5},
        'budgetFixtures': {
            'httpAndLegacyCases': {'memoryBytes': 1024**2, 'cpuFuelGrant': 100_000,
                'wallTimeGrantMilliseconds': 5_000, 'engineFuelInstalled': False},
            'managedComponentCase': {'memoryBytes': 16 * 1024**2,
                'cpuFuelGrant': 1_000_000_000_000, 'wallTimeGrantMilliseconds': 5_000,
                'sdkLanguageOverridePermitted': False},
            'directApiCases': {'activationBudgetInstalled': False, 'linearMemoryLimiterBytes': 65536,
                'coreInstanceLimit': 1, 'memoryLimit': 1, 'engineFuelInstalled': 100_000,
                'hostcallFuel': 65536, 'outputStorage': 'fixed-stack-slices', 'RSSOrCompilerCostClaimed': False},
            'genericHostOrRSSCeilingClaimed': False},
        'externalFixtureInputsAbsent': list(HTTP_INPUT_FORBIDDEN_FIXTURE_ENV),
        'oldCanonicalCasesExecuted': False, 'oldStreamProgrammeExecuted': False,
        'oldProducerProgrammeExecuted': False, 'oldEightGraphProgrammeExecuted': False, 'oldThreeCopyProgrammeExecuted': False,
        'cacheRoundtripExecuted': False, 'sdkGuestCompilerInvoked': False,
        'commandLedgerBoundary': '24 supervised build/library/list/test commands and48 raw channels; normal pinned-tool resolver probes retain their existing owner and are not this ledger'}
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
        def runtime_environment(artifact, label):
            def probe(argv, *, cwd, env, timeout, maximum):
                require(argv == ['rustc', '--print', 'target-libdir'] and cwd == ROOT
                    and timeout == 30 and maximum == 4096, 'normal-library-probe')
                commands.command_seconds = 25
                require_io_copy_environment(env)
                commands.environment = env
                raw = commands.run(label + '-rust-library-path', tools['rustc'], *argv[1:])
                require(len(raw) <= maximum, 'rust-library-output-bound')
                return 0, raw
            return artifacts.cargo_environment(ROOT, artifact, environment,
                target=ROOT / 'target', execute=probe)

        targets = (
            ('http', (*HTTP_INPUT_NATIVE_CASES, HTTP_INPUT_LEGACY_CASE), (),
             ('test', '-p', 'latent-http', '--locked', '--lib', '--all-features',
              '--no-run', '--message-format=json'),
             artifacts.Suite('crates/latent-http/Cargo.toml', 'latent_http',
                'src/lib.rs', 'tests::ownership::', frozenset((*HTTP_INPUT_NATIVE_CASES, HTTP_INPUT_LEGACY_CASE)), True)),
            ('managed', (*HTTP_INPUT_API_CASES, HTTP_INPUT_MANAGED_CASE), (),
             ('test', '-p', 'latent-wasmtime', '--locked', '--test', 'http',
              '--all-features', '--no-run', '--message-format=json'),
             artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'http',
                'tests/http.rs', '', frozenset((*HTTP_INPUT_API_CASES, HTTP_INPUT_MANAGED_CASE)), True, kind='test')),
        )
        executables = []
        for label, cases, ignored, argv, suite in targets:
            receipt['stage'] = 'build-' + label
            require_io_copy_environment(environment)
            commands.environment = environment
            commands.command_seconds = 895
            ordinal = len(commands.records)
            commands.run('build-' + label, tools['cargo'], *argv)
            artifact = artifacts.read_inventory(logs / f'logs/{ordinal:02d}-build-{label}.stdout.txt',
                ROOT, suite, target=ROOT / 'target')
            executable = file_identity(artifact.executable, label + '-native-backing-controls', 512 * 1024**2)
            receipt[label + 'Executable'] = executable
            executables.append((artifact.executable, executable, label + '-native-backing-controls'))
            run_env = runtime_environment(artifact, label)
            run_env = io_copy_environment(run_env)
            if label == 'http':
                contract, = [row for row in registry.load()['suites']
                    if row['id'] == 'latent-http.lib.latent-http']
                require(contract['minimumCases'] == 86
                    and set(cases) <= set(contract['expectedCases'])
                    and not set(cases) & set(contract['expectedIgnored']), 'normal-io-suite-contract')
            else:
                contract, = [row for row in registry.load()['suites']
                    if row['id'] == 'latent-wasmtime.test.http']
                require(contract['minimumCases'] == 7
                    and set(cases) <= set(contract['expectedCases'])
                    and not set(cases) & set(contract['expectedIgnored']), 'normal-managed-suite-contract')
            require_io_copy_environment(run_env)
            commands.environment = run_env
            for index, case in enumerate(cases):
                receipt['stage'] = case
                commands.command_seconds = 25
                listed = commands.run(f'{label}-list-{index}', artifact.executable,
                    case, '--exact', *ignored, '--list')
                require(len(listed) <= artifacts.MAX_LIST_BYTES, 'list-bound')
                artifacts.validate_listing(listed, artifacts.Suite(suite.manifest, suite.target,
                    suite.source, case, frozenset((case,)), True))
                commands.command_seconds = 55
                if case == HTTP_INPUT_MANAGED_CASE:
                    receipt['managedFixtureState'] = 'started-outcome-pending'
                    receipt['managedFixtureAssembled'] = None
                if case in HTTP_INPUT_API_CASES:
                    receipt['directApiCasesStarted'].append(case)
                if label == 'managed':
                    for key in ('wasmtimeExecuted', 'guestComponentCompiled'):
                        if receipt[key] is not True:
                            receipt[key] = None
                require_io_copy_environment(commands.environment)
                raw = commands.run(f'{label}-case-{index}', artifact.executable,
                    case, '--exact', *ignored, '--show-output', '--test-threads=1')
                receipt['observations'].append(http_input_result(raw, case))
                if label == 'managed':
                    receipt.update(wasmtimeExecuted=True, guestComponentCompiled=True)
                if case in HTTP_INPUT_API_CASES:
                    receipt['directApiCasesPassed'].append(case)
                if case == HTTP_INPUT_MANAGED_CASE:
                    receipt.update(managedFixtureState='passed', managedFixtureAssembled=True)
        require(len(commands.records) == 24 and len(receipt['observations']) == 10,
            'two-builds-two-library-probes-ten-exact-cases')
        require(time.monotonic() < commands.deadline, 'overall-deadline')
        require(source_inputs() == before and source.verify() == checked, 'final-source')
        for path, bound, label in executables:
            require(file_identity(path, label, 512 * 1024**2) == bound, 'final-executable')
        require([file_identity(tools[name], name) for name in sorted(tools)] == pins, 'final-tools')
        artifacts.require_source(ROOT, revision, environment)
        require_io_copy_environment(environment)
        require_io_copy_environment(commands.environment)
        require(time.monotonic() < commands.deadline, 'final-deadline')
        receipt.update(status='passed', sourceAfter=before, sourceUnchanged=True,
            executed=list(HTTP_INPUT_CASES), ignored=[])
        write_json(output / 'receipt.json', receipt)
    except BaseException:
        receipt['status'] = 'failed'
        write_json(output / 'FAILED.json', receipt)
        raise
    finally:
        write_json(output / 'commands.json', commands.records)


HTTP_METADATA_BRANCH = 'feat/sdk-736-http-metadata-native-20261027'
HTTP_METADATA_SEMANTIC_CASES = tuple('tests::ownership::' + name for name in (
    'borrowed_http_target_validation_preserves_descriptor_and_destination_semantics',
    'typed_http_digest_iterator_preserves_original_framing_and_bounds'))
HTTP_METADATA_REDIRECT_CASE = 'tests::ownership::native_http_ingress_one_slot_redirect_retires_hop_without_retagging_credit'
HTTP_METADATA_MANAGED_CASE = 'real_guest_executes_every_method_and_reclaims_the_same_warm_cell'
HTTP_METADATA_HTTP_CASES = (*HTTP_METADATA_SEMANTIC_CASES, HTTP_METADATA_REDIRECT_CASE)
HTTP_METADATA_CASES = (*HTTP_METADATA_HTTP_CASES, HTTP_METADATA_MANAGED_CASE)
HTTP_METADATA_SOURCE_PATHS = (
    'crates/latent-capabilities/src/broker/audit.rs',
    'crates/latent-policy/src/capability/resources.rs',
    'crates/latent-http/src/destination.rs',
    'crates/latent-http/src/execute/request.rs',
    'crates/latent-http/src/tests/ownership.rs')


def http_metadata_result(raw, case):
    require(case in HTTP_METADATA_CASES, 'fixed-case')
    require(len(raw) <= artifacts.MAX_OUTPUT_BYTES, 'case-output-bound')
    require(re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$', raw, re.M)
        == [case.encode()], 'one-exact-success')
    summaries = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; '
        rb'(\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    require(len(summaries) == 1 and summaries[0][:4] == (b'1', b'0', b'0', b'0')
        and int(summaries[0][4]) <= 10000, 'one-executed-no-skip')
    require(not re.findall(rb'^(http-utf8-view [^\r\n]+)$', raw, re.M), 'no-old-api-programme-marker')
    scope = ('ordinary-host-grammar-and-digest-semantics-no-ActivationBudget' if case in HTTP_METADATA_SEMANTIC_CASES else
        'unchanged-original-Phase3-one-slot-redirect' if case == HTTP_METADATA_REDIRECT_CASE else
        'installed-canonical-HTTP-all-seven-methods-original-Store-cleanup')
    return {'case': case, 'stdout': identity(raw), 'passed': 1, 'failed': 0,
        'ignored': 0, 'filteredOut': int(summaries[0][4]), 'scope': scope}


def qualify_http_metadata(output, revision):
    require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
        and os.environ.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric'
        and os.environ.get('GITHUB_REF_NAME') == HTTP_METADATA_BRANCH
        and os.environ.get('GITHUB_EVENT_NAME') == 'push', 'one-exact-hosted-push')
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
        'owned-output')
    output = fresh(output)
    environment = io_copy_environment(build_environment(output))
    environment.update(CARGO_TARGET_DIR=str(ROOT / 'target'), CARGO_INCREMENTAL='0',
        CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0',
        CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true', CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',
        CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true', CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
    logs = output / 'commands'
    logs.mkdir()
    # Existing five-second reaping reserve remains inside declared caps.
    commands = Commands(ROOT, logs, environment, deadline_seconds=2395, command_seconds=895)
    receipt = {'schemaVersion': 'lsf.owned-http-typed-metadata.v1', 'status': 'in-progress',
        'sourceRevision': revision, 'selectedCases': list(HTTP_METADATA_CASES), 'observations': [],
        'semanticCasesStarted': [], 'semanticCasesPassed': [],
        'newCases': list(HTTP_METADATA_SEMANTIC_CASES),
        'redirectReferenceCase': HTTP_METADATA_REDIRECT_CASE,
        'managedComponentCase': HTTP_METADATA_MANAGED_CASE,
        'fullCostModelQualified': False, 'fullHttpSuiteExecuted': False, 'fullRuntimeSuiteExecuted': False,
        'fullVendorSuiteExecuted': False, 'signedRealNodeGuestExecuted': False,
        'wasmtimeExecuted': False, 'guestComponentCompiled': False,
        'managedFixtureAssembled': False, 'managedFixtureState': 'not-started',
        'cargoBuildMayRunHostBuildScripts': True,
        'managedCaseReallyAssemblesCompilesAndExecutesComponent': True,
        'hermetic': False, 'compilerImplicitInputsAttested': False,
        'scope': 'remove source-owned HTTP policy JSON roundtrip and digest collection; borrowed target grammar is not authority; opaque Url/IDNA/IP formatter/origin/redirect/wire/control/TLS/transitive allocations remain separate',
        'limits': {'overallSeconds': 2400, 'buildCommandSeconds': 900,
            'caseProcessSeconds': 60, 'listProcessSeconds': 30, 'cleanupReserveSeconds': 5},
        'budgetFixtures': {
            'semanticCases': {'activationBudgetInstalled': False,
                'scope': 'ordinary-host-grammar/golden-digest/bounds-not-memory-or-RSS-qualification',
                'engineExecuted': False},
            'redirectReferenceCase': {'memoryBytes': 1024**2, 'cpuFuelGrant': 100_000,
                'wallTimeGrantMilliseconds': 5_000, 'engineFuelInstalled': False},
            'managedComponentCase': {'memoryBytes': 16 * 1024**2,
                'cpuFuelGrant': 1_000_000_000_000, 'wallTimeGrantMilliseconds': 5_000,
                'sdkLanguageOverridePermitted': False},
            'genericHostOrRSSCeilingClaimed': False},
        'externalFixtureInputsAbsent': list(IO_COPY_FORBIDDEN_FIXTURE_ENV),
        'oldHttpInputTenCaseProgrammeExecuted': False,
        'oldPublicWasmStringApiCasesExecuted': False,
        'oldCanonicalCasesExecuted': False, 'oldStreamProgrammeExecuted': False,
        'oldProducerProgrammeExecuted': False, 'oldEightGraphProgrammeExecuted': False,
        'oldThreeCopyProgrammeExecuted': False, 'oldBlobOutputNativeCasesExecuted': False,
        'oldBlobInputProgrammeExecuted': False, 'privateVendorUnitTestsExecuted': False,
        'cacheRoundtripExecuted': False, 'sdkGuestCompilerInvoked': False,
        'commandLedgerBoundary': '12 supervised build/library/list/test commands and24 raw channels; normal pinned-tool resolver probes retain their existing owner and are not this ledger'}
    try:
        artifacts.require_source(ROOT, revision, environment)
        before = source_inputs()
        receipt['sourceBefore'] = before
        receipt['typedMetadataSourceFiles'] = {path: identity(read_file(ROOT / path, 4 * 1024**2))
            for path in HTTP_METADATA_SOURCE_PATHS}
        write_json(output / 'source-inputs.json', before)
        checked = source.verify()
        receipt['wasmtimeSource'] = checked
        toolchain = tomllib.loads(read_file(ROOT / 'tools/toolchain.toml', 128 * 1024).decode())
        require(toolchain['rust']['toolchain'] == '1.97.1'
            and toolchain['contracts']['wasm-tools'] == '1.254.0', 'normal-tool-pins')
        tools, pins = resolve_tools(toolchain, ROOT, environment, _deadline=commands.deadline)
        receipt['observedTools'] = pins
        environment.update(RUSTC=str(tools['rustc']), RUSTUP_TOOLCHAIN=toolchain['rust']['toolchain'])
        def runtime_environment(artifact, label):
            def probe(argv, *, cwd, env, timeout, maximum):
                require(argv == ['rustc', '--print', 'target-libdir'] and cwd == ROOT
                    and timeout == 30 and maximum == 4096, 'normal-library-probe')
                commands.command_seconds = 25
                require_io_copy_environment(env)
                commands.environment = env
                raw = commands.run(label + '-rust-library-path', tools['rustc'], *argv[1:])
                require(len(raw) <= maximum, 'rust-library-output-bound')
                return 0, raw
            return artifacts.cargo_environment(ROOT, artifact, environment,
                target=ROOT / 'target', execute=probe)

        targets = (
            ('http', HTTP_METADATA_HTTP_CASES, (),
             ('test', '-p', 'latent-http', '--locked', '--lib', '--all-features',
              '--no-run', '--message-format=json'),
             artifacts.Suite('crates/latent-http/Cargo.toml', 'latent_http',
                'src/lib.rs', 'tests::ownership::', frozenset(HTTP_METADATA_HTTP_CASES), True)),
            ('managed', (HTTP_METADATA_MANAGED_CASE,), (),
             ('test', '-p', 'latent-wasmtime', '--locked', '--test', 'http',
              '--all-features', '--no-run', '--message-format=json'),
             artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'http',
                'tests/http.rs', '', frozenset((HTTP_METADATA_MANAGED_CASE,)), True, kind='test')),
        )
        executables = []
        for label, cases, ignored, argv, suite in targets:
            receipt['stage'] = 'build-' + label
            require_io_copy_environment(environment)
            commands.environment = environment
            commands.command_seconds = 895
            ordinal = len(commands.records)
            commands.run('build-' + label, tools['cargo'], *argv)
            artifact = artifacts.read_inventory(logs / f'logs/{ordinal:02d}-build-{label}.stdout.txt',
                ROOT, suite, target=ROOT / 'target')
            executable = file_identity(artifact.executable, label + '-native-backing-controls', 512 * 1024**2)
            receipt[label + 'Executable'] = executable
            executables.append((artifact.executable, executable, label + '-native-backing-controls'))
            run_env = runtime_environment(artifact, label)
            run_env = io_copy_environment(run_env)
            if label == 'http':
                contract, = [row for row in registry.load()['suites']
                    if row['id'] == 'latent-http.lib.latent-http']
                require(contract['minimumCases'] == 86
                    and set(cases) <= set(contract['expectedCases'])
                    and not set(cases) & set(contract['expectedIgnored']), 'normal-io-suite-contract')
            else:
                contract, = [row for row in registry.load()['suites']
                    if row['id'] == 'latent-wasmtime.test.http']
                require(contract['minimumCases'] == 7
                    and set(cases) <= set(contract['expectedCases'])
                    and not set(cases) & set(contract['expectedIgnored']), 'normal-managed-suite-contract')
            require_io_copy_environment(run_env)
            commands.environment = run_env
            for index, case in enumerate(cases):
                receipt['stage'] = case
                commands.command_seconds = 25
                listed = commands.run(f'{label}-list-{index}', artifact.executable,
                    case, '--exact', *ignored, '--list')
                require(len(listed) <= artifacts.MAX_LIST_BYTES, 'list-bound')
                artifacts.validate_listing(listed, artifacts.Suite(suite.manifest, suite.target,
                    suite.source, case, frozenset((case,)), True))
                commands.command_seconds = 55
                if case == HTTP_METADATA_MANAGED_CASE:
                    receipt['managedFixtureState'] = 'started-outcome-pending'
                    receipt['managedFixtureAssembled'] = None
                if case in HTTP_METADATA_SEMANTIC_CASES:
                    receipt['semanticCasesStarted'].append(case)
                if label == 'managed':
                    for key in ('wasmtimeExecuted', 'guestComponentCompiled'):
                        if receipt[key] is not True:
                            receipt[key] = None
                require_io_copy_environment(commands.environment)
                raw = commands.run(f'{label}-case-{index}', artifact.executable,
                    case, '--exact', *ignored, '--show-output', '--test-threads=1')
                receipt['observations'].append(http_metadata_result(raw, case))
                if label == 'managed':
                    receipt.update(wasmtimeExecuted=True, guestComponentCompiled=True)
                if case in HTTP_METADATA_SEMANTIC_CASES:
                    receipt['semanticCasesPassed'].append(case)
                if case == HTTP_METADATA_MANAGED_CASE:
                    receipt.update(managedFixtureState='passed', managedFixtureAssembled=True)
        require(len(commands.records) == 12 and len(receipt['observations']) == 4,
            'two-builds-two-library-probes-four-exact-cases')
        require(time.monotonic() < commands.deadline, 'overall-deadline')
        require(source_inputs() == before and source.verify() == checked, 'final-source')
        for path, bound, label in executables:
            require(file_identity(path, label, 512 * 1024**2) == bound, 'final-executable')
        require([file_identity(tools[name], name) for name in sorted(tools)] == pins, 'final-tools')
        artifacts.require_source(ROOT, revision, environment)
        require_io_copy_environment(environment)
        require_io_copy_environment(commands.environment)
        require(time.monotonic() < commands.deadline, 'final-deadline')
        receipt.update(status='passed', sourceAfter=before, sourceUnchanged=True,
            executed=list(HTTP_METADATA_CASES), ignored=[])
        write_json(output / 'receipt.json', receipt)
    except BaseException:
        receipt['status'] = 'failed'
        write_json(output / 'FAILED.json', receipt)
        raise
    finally:
        write_json(output / 'commands.json', commands.records)


HTTP_IP_FORMAT_BRANCH = 'feat/sdk-736-http-ip-format-20261027'
HTTP_IP_FORMAT_PREFIX = 'capability::resources::stream_tests::'
HTTP_IP_FORMAT_NEW_CASES = tuple(HTTP_IP_FORMAT_PREFIX + name for name in (
    'canonical_ip_stack_spelling_preserves_original_display_and_host_gates',
    'canonical_ip_fixed_writer_refuses_whole_overflowing_chunks'))
HTTP_IP_FORMAT_POLICY_CASES = (*HTTP_IP_FORMAT_NEW_CASES,
    HTTP_IP_FORMAT_PREFIX + 'malformed_ambiguous_and_wildcard_endpoints_fail_closed')
HTTP_IP_FORMAT_HTTP_CASES = ('tests::ownership::borrowed_http_target_validation_preserves_descriptor_and_destination_semantics',)
HTTP_IP_FORMAT_CASES = (*HTTP_IP_FORMAT_POLICY_CASES, *HTTP_IP_FORMAT_HTTP_CASES)
HTTP_IP_FORMAT_SOURCE_PATHS = (
    'crates/latent-policy/src/capability/resources.rs',
    'crates/latent-http/src/tests/ownership.rs')


def http_ip_format_result(raw, case):
    require(case in HTTP_IP_FORMAT_CASES, 'fixed-case')
    require(len(raw) <= artifacts.MAX_OUTPUT_BYTES, 'case-output-bound')
    require(re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$', raw, re.M)
        == [case.encode()], 'one-exact-success')
    summaries = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; '
        rb'(\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    require(len(summaries) == 1 and summaries[0][:4] == (b'1', b'0', b'0', b'0')
        and int(summaries[0][4]) <= 10000, 'one-executed-no-skip')
    require(not re.findall(rb'^(http-utf8-view [^\r\n]+)$', raw, re.M), 'no-old-api-programme-marker')
    return {'case': case, 'stdout': identity(raw), 'passed': 1, 'failed': 0,
        'ignored': 0, 'filteredOut': int(summaries[0][4]),
        'scope': 'ordinary-host-IP-display-and-target-grammar-bounds-no-ActivationBudget'}


def qualify_http_ip_format(output, revision):
    require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
        and os.environ.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric'
        and os.environ.get('GITHUB_REF_NAME') == HTTP_IP_FORMAT_BRANCH
        and os.environ.get('GITHUB_EVENT_NAME') == 'push', 'one-exact-hosted-push')
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
        'owned-output')
    output = fresh(output)
    environment = io_copy_environment(build_environment(output))
    environment.update(CARGO_TARGET_DIR=str(ROOT / 'target'), CARGO_INCREMENTAL='0',
        CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0',
        CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true', CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',
        CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true', CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
    logs = output / 'commands'
    logs.mkdir()
    # The original five-second reaping reserve remains inside every cap.
    commands = Commands(ROOT, logs, environment, deadline_seconds=2395, command_seconds=895)
    receipt = {'schemaVersion': 'lsf.owned-http-ip-format.v1', 'status': 'in-progress',
        'sourceRevision': revision, 'selectedCases': list(HTTP_IP_FORMAT_CASES), 'observations': [],
        'casesStarted': [], 'casesPassed': [], 'newCases': list(HTTP_IP_FORMAT_NEW_CASES),
        'unchangedReferenceCases': [HTTP_IP_FORMAT_POLICY_CASES[-1], *HTTP_IP_FORMAT_HTTP_CASES],
        'fullCostModelQualified': False, 'fullHttpSuiteExecuted': False, 'fullRuntimeSuiteExecuted': False,
        'fullVendorSuiteExecuted': False, 'signedRealNodeGuestExecuted': False,
        'wasmtimeExecuted': False, 'guestComponentCompiled': False,
        'fixtureAssembled': False, 'cargoBuildMayRunHostBuildScripts': True,
        'hermetic': False, 'compilerImplicitInputsAttested': False,
        'scope': 'remove the canonical_host IP comparison String with the original default Display and exact byte equality in a bounded39-byte private writer; domain/stream authority gates unchanged; opaque Url/parser/origin/redirect/wire/control/TLS/transitive and complete stack/native costs remain open',
        'limits': {'overallSeconds': 2400, 'buildCommandSeconds': 900,
            'caseProcessSeconds': 60, 'listProcessSeconds': 30, 'cleanupReserveSeconds': 5},
        'budgetFixtures': {'allFourOrdinaryControls': {'activationBudgetInstalled': False,
            'scope': 'IP-display/target-grammar/stack-writer-bounds-not-memory-or-RSS-qualification',
            'engineExecuted': False}, 'genericHostOrRSSCeilingClaimed': False},
        'canonicalIpDisplayCapacityBytes': 39,
        'externalFixtureInputsAbsent': list(IO_COPY_FORBIDDEN_FIXTURE_ENV),
        'oldHttpMetadataFourCaseProgrammeExecuted': False,
        'oldHttpInputTenCaseProgrammeExecuted': False,
        'oldPublicWasmStringApiCasesExecuted': False,
        'oldCanonicalCasesExecuted': False, 'oldStreamProgrammeExecuted': False,
        'oldProducerProgrammeExecuted': False, 'oldEightGraphProgrammeExecuted': False,
        'oldThreeCopyProgrammeExecuted': False, 'oldBlobOutputNativeCasesExecuted': False,
        'oldBlobInputProgrammeExecuted': False, 'privateVendorUnitTestsExecuted': False,
        'cacheRoundtripExecuted': False, 'sdkGuestCompilerInvoked': False,
        'commandLedgerBoundary': '12 supervised build/library/list/test commands and24 raw channels; normal pinned-tool resolver probes retain their existing owner and are not this ledger'}
    try:
        artifacts.require_source(ROOT, revision, environment)
        before = source_inputs()
        receipt['sourceBefore'] = before
        receipt['canonicalIpSourceFiles'] = {path: identity(read_file(ROOT / path, 4 * 1024**2))
            for path in HTTP_IP_FORMAT_SOURCE_PATHS}
        write_json(output / 'source-inputs.json', before)
        checked = source.verify()
        receipt['wasmtimeSource'] = checked
        toolchain = tomllib.loads(read_file(ROOT / 'tools/toolchain.toml', 128 * 1024).decode())
        require(toolchain['rust']['toolchain'] == '1.97.1'
            and toolchain['contracts']['wasm-tools'] == '1.254.0', 'normal-tool-pins')
        tools, pins = resolve_tools(toolchain, ROOT, environment, _deadline=commands.deadline)
        receipt['observedTools'] = pins
        environment.update(RUSTC=str(tools['rustc']), RUSTUP_TOOLCHAIN=toolchain['rust']['toolchain'])
        def runtime_environment(artifact, label):
            def probe(argv, *, cwd, env, timeout, maximum):
                require(argv == ['rustc', '--print', 'target-libdir'] and cwd == ROOT
                    and timeout == 30 and maximum == 4096, 'normal-library-probe')
                commands.command_seconds = 25
                require_io_copy_environment(env)
                commands.environment = env
                raw = commands.run(label + '-rust-library-path', tools['rustc'], *argv[1:])
                require(len(raw) <= maximum, 'rust-library-output-bound')
                return 0, raw
            return artifacts.cargo_environment(ROOT, artifact, environment,
                target=ROOT / 'target', execute=probe)

        targets = (
            ('policy', HTTP_IP_FORMAT_POLICY_CASES,
             ('test', '-p', 'latent-policy', '--locked', '--lib', '--all-features',
              '--no-run', '--message-format=json'),
             artifacts.Suite('crates/latent-policy/Cargo.toml', 'latent_policy',
                'src/lib.rs', HTTP_IP_FORMAT_PREFIX, frozenset(HTTP_IP_FORMAT_POLICY_CASES), True),
             'latent-policy.lib.latent-policy', 157),
            ('http', HTTP_IP_FORMAT_HTTP_CASES,
             ('test', '-p', 'latent-http', '--locked', '--lib', '--all-features',
              '--no-run', '--message-format=json'),
             artifacts.Suite('crates/latent-http/Cargo.toml', 'latent_http',
                'src/lib.rs', 'tests::ownership::', frozenset(HTTP_IP_FORMAT_HTTP_CASES), True),
             'latent-http.lib.latent-http', 86),
        )
        executables = []
        for label, cases, argv, suite, suite_id, minimum in targets:
            receipt['stage'] = 'build-' + label
            require_io_copy_environment(environment)
            commands.environment = environment
            commands.command_seconds = 895
            ordinal = len(commands.records)
            commands.run('build-' + label, tools['cargo'], *argv)
            artifact = artifacts.read_inventory(logs / f'logs/{ordinal:02d}-build-{label}.stdout.txt',
                ROOT, suite, target=ROOT / 'target')
            executable = file_identity(artifact.executable, label + '-ip-format-controls', 512 * 1024**2)
            receipt[label + 'Executable'] = executable
            executables.append((artifact.executable, executable, label + '-ip-format-controls'))
            run_env = io_copy_environment(runtime_environment(artifact, label))
            contract, = [row for row in registry.load()['suites'] if row['id'] == suite_id]
            require(contract['minimumCases'] == minimum
                and set(cases) <= set(contract['expectedCases'])
                and not set(cases) & set(contract['expectedIgnored']), 'normal-IP-suite-contract')
            require_io_copy_environment(run_env)
            commands.environment = run_env
            for index, case in enumerate(cases):
                receipt['stage'] = case
                commands.command_seconds = 25
                listed = commands.run(f'{label}-list-{index}', artifact.executable,
                    case, '--exact', '--list')
                require(len(listed) <= artifacts.MAX_LIST_BYTES, 'list-bound')
                artifacts.validate_listing(listed, artifacts.Suite(suite.manifest, suite.target,
                    suite.source, case, frozenset((case,)), True))
                commands.command_seconds = 55
                receipt['casesStarted'].append(case)
                require_io_copy_environment(commands.environment)
                raw = commands.run(f'{label}-case-{index}', artifact.executable,
                    case, '--exact', '--show-output', '--test-threads=1')
                receipt['observations'].append(http_ip_format_result(raw, case))
                receipt['casesPassed'].append(case)
        require(len(commands.records) == 12 and len(receipt['observations']) == 4,
            'two-builds-two-library-probes-four-exact-cases')
        require(time.monotonic() < commands.deadline, 'overall-deadline')
        require(source_inputs() == before and source.verify() == checked, 'final-source')
        for path, bound, label in executables:
            require(file_identity(path, label, 512 * 1024**2) == bound, 'final-executable')
        require([file_identity(tools[name], name) for name in sorted(tools)] == pins, 'final-tools')
        artifacts.require_source(ROOT, revision, environment)
        require_io_copy_environment(environment)
        require_io_copy_environment(commands.environment)
        require(time.monotonic() < commands.deadline, 'final-deadline')
        receipt.update(status='passed', sourceAfter=before, sourceUnchanged=True,
            executed=list(HTTP_IP_FORMAT_CASES), ignored=[])
        write_json(output / 'receipt.json', receipt)
    except BaseException:
        receipt['status'] = 'failed'
        write_json(output / 'FAILED.json', receipt)
        raise
    finally:
        write_json(output / 'commands.json', commands.records)


LIFT_RESULT_BRANCH = 'feat/sdk-745-lift-result-memory-20261028'
LIFT_RESULT_PREFIX = 'runtime::component::concurrent::lift_result_memory_tests::'
LIFT_RESULT_CASES = tuple(LIFT_RESULT_PREFIX + name for name in (
    'exact_layout_preserves_sixteen_values_and_caller_retptr_without_growth',
    'original_refusal_returns_before_confirmation_and_preserves_source',
    'backing_owner_retires_on_return_error_and_unwind',
    'empty_and_unaccounted_callers_preserve_value_shapes'))


def lift_result_result(raw, case):
    require(case in LIFT_RESULT_CASES and len(raw) <= artifacts.MAX_OUTPUT_BYTES,
        'lift-result-case-bound')
    require(re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$', raw, re.M)
        == [case.encode()], 'lift-result-one-exact-success')
    summaries = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; '
        rb'(\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    require(len(summaries) == 1 and summaries[0][:4] == (b'1', b'0', b'0', b'0')
        and int(summaries[0][4]) <= 10000, 'lift-result-one-executed-no-skip')
    return {'case': case, 'stdout': identity(raw), 'passed': 1, 'failed': 0,
        'ignored': 0, 'filteredOut': int(summaries[0][4]),
        'scope': 'private-typed-buffer-counter-owner'}


def qualify_lift_result_memory(output, revision):
    require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
        and os.environ.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric'
        and os.environ.get('GITHUB_REF_NAME') == LIFT_RESULT_BRANCH
        and os.environ.get('GITHUB_EVENT_NAME') == 'push', 'lift-result-one-exact-hosted-push')
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
        'lift-result-owned-output')
    output = fresh(output)
    environment = build_environment(output)
    environment.pop(FIXTURE_ENV, None)
    environment.update(CARGO_TARGET_DIR=str(ROOT / 'target'), CARGO_INCREMENTAL='0',
        CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0',
        CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true', CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',
        CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true', CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
    logs = output / 'commands'
    logs.mkdir()
    # One original five-second cleanup reserve, inside the 1320-second owner.
    commands = Commands(ROOT, logs, environment, deadline_seconds=1315, command_seconds=1195)
    receipt = {'schemaVersion': 'lsf.lift-result-memory.v1', 'status': 'in-progress',
        'sourceRevision': revision, 'privateCases': list(LIFT_RESULT_CASES),
        'casesStarted': [], 'casesPassed': [], 'observations': [],
        'fullCostModelQualified': False, 'fullRuntimeSuiteExecuted': False,
        'fullVendorSuiteExecuted': False, 'signedGuestExecuted': False,
        'originalActivationBudgetQualified': False, 'wholeAc5Qualified': False,
        'paramsAndClosureQualified': False, 'hermetic': False,
        'compilerImplicitInputsAttested': False,
        'limits': {'overallSeconds': 1320, 'buildCommandSeconds': 1200,
            'caseProcessSeconds': 60, 'listProcessSeconds': 30, 'cleanupReserveSeconds': 5},
        'scope': 'only fused LiftResult typed buffer; private counter controls, not original grant/RSS/full cost',
        'commandLedgerBoundary': 'fourteen supervised Git/build/library/list/test commands; five normal pinned-tool resolver probes retain their existing owner and share the same absolute deadline'}
    def metadata(stage, *argv):
        old_seconds, old_environment = commands.command_seconds, commands.environment
        try:
            commands.command_seconds = 25
            commands.environment = environment
            return commands.run(stage, 'git', '-c', 'core.fsmonitor=false', *argv)
        finally:
            commands.command_seconds, commands.environment = old_seconds, old_environment
    def current_revision(stage):
        require(re.fullmatch(r'[0-9a-fA-F]{40}|[0-9a-fA-F]{64}', revision) is not None,
            'lift-result-missing-source-commit')
        raw = metadata(stage, '-c', 'gc.auto=0', 'rev-parse', '--verify', 'HEAD')
        require(len(raw) <= 256 and raw.strip().decode('ascii') == revision.lower(),
            'lift-result-source-checkout-mismatch')
    def current_inputs(stage):
        raw = metadata(stage, 'ls-files', '-z', '--', *SOURCE_ALLOWLIST)
        require(len(raw) <= 2 * 1024**2, 'source-path-bound')
        names = [name for name in raw.decode().split('\0') if name]
        limits = SnapshotLimits()
        require(100 <= len(names) <= limits.max_entries, 'source-count')
        result, total = {}, 0
        for name in names:
            require(time.monotonic() < commands.deadline, 'lift-result-source-hash-deadline')
            data = read_file(ROOT / name, limits.max_file_bytes)
            total += len(data)
            result[name] = identity(data)
        require(total <= limits.max_total_bytes, 'source-total')
        result[WORKFLOW] = identity(read_file(ROOT / WORKFLOW, 128 * 1024))
        return dict(sorted(result.items()))
    try:
        current_revision('source-revision-before')
        before = current_inputs('source-paths-before')
        receipt['sourceBefore'] = before
        write_json(output / 'source-inputs.json', before)
        checked = source.verify()
        receipt['wasmtimeSource'] = checked
        toolchain = tomllib.loads(read_file(ROOT / 'tools/toolchain.toml', 128 * 1024).decode())
        require(toolchain['rust']['toolchain'] == '1.97.1'
            and toolchain['contracts']['wasm-tools'] == '1.254.0', 'lift-result-normal-tool-pins')
        tools, pins = resolve_tools(toolchain, ROOT, environment, _deadline=commands.deadline)
        receipt['observedTools'] = pins
        environment.update(RUSTC=str(tools['rustc']), RUSTUP_TOOLCHAIN=toolchain['rust']['toolchain'])
        suite = artifacts.Suite('crates/vendor/wasmtime/Cargo.toml', 'wasmtime',
            'src/lib.rs', LIFT_RESULT_PREFIX, frozenset(LIFT_RESULT_CASES), True)
        receipt['stage'] = 'build-private'
        ordinal = len(commands.records)
        commands.run('build-private', tools['cargo'], 'test', '--manifest-path',
            suite.manifest, '--locked', '--lib', '--no-default-features', '--features',
            FEATURES, '--no-run', '--message-format=json')
        artifact = artifacts.read_inventory(logs / f'logs/{ordinal:02d}-build-private.stdout.txt',
            ROOT, suite, target=ROOT / 'target')
        executable = file_identity(artifact.executable, 'lift-result-controls', 512 * 1024**2)
        receipt['privateExecutable'] = executable
        def probe(argv, *, cwd, env, timeout, maximum):
            require(argv == ['rustc', '--print', 'target-libdir'] and cwd == ROOT
                and timeout == 30 and maximum == 4096, 'lift-result-normal-library-probe')
            commands.command_seconds = 25
            commands.environment = env
            raw = commands.run('private-rust-library-path', tools['rustc'], *argv[1:])
            require(len(raw) <= maximum, 'lift-result-rust-library-bound')
            return 0, raw
        commands.environment = artifacts.cargo_environment(ROOT, artifact, environment,
            target=ROOT / 'target', execute=probe)
        for index, case in enumerate(LIFT_RESULT_CASES):
            receipt['stage'] = case
            commands.command_seconds = 25
            listed = commands.run(f'private-list-{index}', artifact.executable, case, '--exact', '--list')
            require(len(listed) <= artifacts.MAX_LIST_BYTES, 'lift-result-list-bound')
            artifacts.validate_listing(listed, artifacts.Suite(suite.manifest, suite.target,
                suite.source, case, frozenset((case,)), True))
            commands.command_seconds = 55
            receipt['casesStarted'].append(case)
            raw = commands.run(f'private-case-{index}', artifact.executable, case,
                '--exact', '--show-output', '--test-threads=1')
            receipt['observations'].append(lift_result_result(raw, case))
            receipt['casesPassed'].append(case)
        require(len(receipt['observations']) == 4, 'lift-result-four-exact-cases')
        require(time.monotonic() < commands.deadline, 'lift-result-overall-deadline')
        require(current_inputs('source-paths-after') == before and source.verify() == checked,
            'lift-result-final-source')
        require(file_identity(artifact.executable, 'lift-result-controls', 512 * 1024**2)
            == executable, 'lift-result-final-executable')
        require([file_identity(tools[name], name) for name in sorted(tools)] == pins,
            'lift-result-final-tools')
        current_revision('source-revision-after')
        require(len(commands.records) == 14, 'lift-result-four-git-one-build-one-library-eight-cases')
        require(time.monotonic() < commands.deadline, 'lift-result-final-deadline')
        receipt.update(status='passed', sourceAfter=before, sourceUnchanged=True,
            executed=list(LIFT_RESULT_CASES), ignored=[])
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
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--cache-repair', action='store_true')
    modes.add_argument('--consumer-cell', action='store_true')
    modes.add_argument('--producer-cell', action='store_true')
    modes.add_argument('--producer-factories', action='store_true')
    modes.add_argument('--io-operations', action='store_true')
    modes.add_argument('--io-graph', action='store_true')
    modes.add_argument('--io-copy', action='store_true')
    modes.add_argument('--blob-copy', action='store_true')
    modes.add_argument('--blob-input', action='store_true')
    modes.add_argument('--http-input', action='store_true')
    modes.add_argument('--http-metadata', action='store_true')
    modes.add_argument('--http-ip-format', action='store_true')
    modes.add_argument('--lift-result-memory', action='store_true')
    args = parser.parse_args()
    if args.lift_result_memory:
        qualify_lift_result_memory(args.output.resolve(), args.source_commit)
    elif args.http_ip_format:
        qualify_http_ip_format(args.output.resolve(), args.source_commit)
    elif args.http_metadata:
        qualify_http_metadata(args.output.resolve(), args.source_commit)
    elif args.http_input:
        qualify_http_input(args.output.resolve(), args.source_commit)
    elif args.blob_input:
        qualify_blob_input(args.output.resolve(), args.source_commit)
    elif args.blob_copy:
        qualify_blob_copy(args.output.resolve(), args.source_commit)
    elif args.io_copy:
        qualify_io_copy(args.output.resolve(), args.source_commit)
    elif args.io_graph:
        qualify_io_graph(args.output.resolve(), args.source_commit)
    elif args.io_operations:
        qualify_io_operations(args.output.resolve(), args.source_commit)
    elif args.producer_factories:
        qualify_producer_factories(args.output.resolve(), args.source_commit)
    elif args.producer_cell:
        qualify_producer_cell(args.output.resolve(), args.source_commit)
    elif args.consumer_cell:
        qualify_consumer_cell(args.output.resolve(), args.source_commit)
    elif args.cache_repair:
        qualify_cache_repair(args.output.resolve(), args.source_commit)
    else:
        qualify(args.output.resolve(), args.source_commit)
