"""Fixed stream, cache, consumer and producer modes; private counters and public budgets stay distinct."""
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


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--cache-repair', action='store_true')
    modes.add_argument('--consumer-cell', action='store_true')
    modes.add_argument('--producer-cell', action='store_true')
    args = parser.parse_args()
    if args.producer_cell:
        qualify_producer_cell(args.output.resolve(), args.source_commit)
    elif args.consumer_cell:
        qualify_consumer_cell(args.output.resolve(), args.source_commit)
    elif args.cache_repair:
        qualify_cache_repair(args.output.resolve(), args.source_commit)
    else:
        qualify(args.output.resolve(), args.source_commit)
