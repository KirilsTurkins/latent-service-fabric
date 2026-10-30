"""One unchanged published TimedSemaphore component and sixteen normal signed calls."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import tomllib

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import ci_rust_artifacts as artifacts, ci_suite_inventory as registry
from tools import java_capsule_project, java_fiber_library_inputs, qualify_java_fibers
from tools import qualify_java_retained_fibers as observed
from tools import qualify_java_published_workers as workers
from tools.build_observation import build_environment, file_identity, resolve_tools
from tools.build_snapshot import SOURCE_ALLOWLIST, SnapshotLimits
from tools.java_guest import compiler_profile_distribution as distribution
from tools.java_guest import retained_fiber_inputs as identities
from tools.native_runtime import files
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json

BRANCH = 'feat/java-scheduled-executor-20261026'
WORKFLOW = '.github/workflows/java-scheduled-library.yml'
CASE = observed.WORKER_CASE
GRADLE_SHA = workers.GRADLE_SHA
java_sources = workers.java_sources
retain = workers.retain


def need(value, reason):
    if not value:
        raise ValueError('java-scheduled-library-' + reason)


def sources(commands, names=None):
    return observed.source_domains(commands, 'scheduled', names)


def observations(raw, filtered=51):
    case = CASE
    fixture = 'java-scheduled-libraries'
    profile = b'teavm-activation-fibers-v1'
    need(len(raw) <= artifacts.MAX_OUTPUT_BYTES, 'output-bound')
    need(re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$', raw, re.M) == [case.encode()], 'exact-case')
    summaries = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; '
        rb'(\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    need(summaries == [(b'1', b'0', b'0', b'0', str(filtered).encode())], 'one-executed-no-skip')
    setup = re.findall(rb'^' + profile + rb' signed-preparation-setup-micros=(\d+) '
        rb'stores-created=0 guest-activations=0$', raw, re.M)
    need(len(setup) == 1, 'normal-preparation')
    rows = [json.loads(line, object_pairs_hook=registry.unique_object)
            for line in re.findall(rb'^LSF_JAVA_RETAINED=(\{[^\r\n]*\})$', raw, re.M)]
    need(len(rows) == 16, 'sixteen-calls')
    created = 0
    for index, row in enumerate(rows):
        iteration, mode = divmod(index, 8)
        expected_id = f'{fixture}-{iteration}-{mode}'
        need(type(row) is dict and set(row) == {*observed.ZERO_FIELDS, 'activationId', 'iteration', 'mode',
            'value', 'cpuFuel', 'reportedPeakMemoryBytes', 'storesBefore', 'storesCreated'}, 'row-fields')
        need(row['activationId'] == expected_id and row['iteration'] == iteration
            and row['mode'] == mode and row['value'] == 42, 'actual-id-mode-value')
        need(all(type(value) is int and 0 <= value <= 2**64 - 1
            for key, value in row.items() if key != 'activationId'), 'numeric-fields')
        need(0 < row['cpuFuel'] <= 10_000_000_000
            and 0 < row['reportedPeakMemoryBytes'] <= 64 * 1024**2, 'original-budget')
        need(row['storesBefore'] == created and row['storesCreated'] > created, 'fresh-stores')
        need(all(row[field] == 0 for field in observed.ZERO_FIELDS), 'actual-idle-counters')
        created = row['storesCreated']
    return {'case': case, 'passed': 1, 'failed': 0, 'ignored': 0, 'filteredOut': filtered,
            'setupMicroseconds': int(setup[0]), 'calls': rows, 'stdout': identities.identity(raw)}


def qualify(output, revision):
    need(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
        and os.environ.get('GITHUB_REPOSITORY') == identities.REPOSITORY
        and os.environ.get('GITHUB_REF_NAME') == BRANCH
        and os.environ.get('GITHUB_EVENT_NAME') == 'push'
        and os.environ.get('GITHUB_SHA') == revision
        and os.environ.get('GITHUB_WORKFLOW_SHA') == revision
        and os.environ.get('GITHUB_WORKSPACE') == str(ROOT)
        and os.environ.get('GITHUB_WORKFLOW_REF') == identities.REPOSITORY + '/'
            + WORKFLOW + '@refs/heads/' + BRANCH, 'fixed-hosted-push')
    need('LSF_JAVA_WORKER_LIBRARIES_FIXTURE' not in os.environ, 'exclusive-fixture-selector')
    need(output != ROOT and ROOT not in output.parents and output not in ROOT.parents, 'owned-output')
    output = fresh(output)
    environment = build_environment(output)
    target = ROOT / 'target'
    environment.update(CARGO_TARGET_DIR=str(target), CARGO_INCREMENTAL='0',
        CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0',
        CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true', CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',
        CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true', CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
    logs = output / 'commands'
    logs.mkdir()
    commands = Commands(ROOT, logs, environment, deadline_seconds=2395, command_seconds=895)
    receipt = {'schemaVersion': 'lsf.java-scheduled-library.v1', 'status': 'in-progress',
        'sourceRevision': revision, 'case': CASE, 'javaComponentRecompiled': False,
        'llvmBuilt': False, 'nativeHarnessBuilt': False, 'fullJavaProfileQualified': False,
        'fullCostModelQualified': False, 'hermetic': False, 'compilerImplicitInputsAttested': False,
        'limits': {'overallSeconds': 2400, 'cleanupReserveSeconds': 5,
            'compilerAggregateSeconds': 1200, 'compilerCommandSeconds': 600,
            'nativeBuildSeconds': 900, 'caseProcessSeconds': 1800, 'listProcessSeconds': 30,
            'sourceControlSeconds': 60},
        'libraries': java_fiber_library_inputs.LIBRARIES,
        'scope': 'twelve unchanged Commons TimedSemaphore default-factory calls plus four '
            'source-controlled default-CompletableFuture/rejection calls; no executor injection or full scheduler API claim'}
    private = None
    prepared = None
    old_path = os.environ.get('PATH', '')
    try:
        observed.require_source(commands, revision, 'source-head-before')
        before, java_before = sources(commands), java_sources()
        receipt.update(sourceBefore=before['native'], supplementarySourceBefore=before['supplementary'],
            javaSourceBefore=java_before)
        write_json(output / 'source-inputs.json', {**before, 'java': java_before})
        private = Path(tempfile.mkdtemp(prefix='latent-java-scheduled.', dir='/tmp'))
        private.chmod(0o700)
        with files.directory(private, owners={0, os.geteuid()}):
            pass  # Original installer ancestry/ACL policy, before component cost.
        receipt['stage'] = 'focused-source-controls'
        commands.command_seconds = 55
        control_index = len(commands.records)
        commands.run('source-controls', sys.executable, '-B', '-m', 'unittest', '-v',
            'tools.tests.test_java_scheduled_library.ScheduledLibraryOwnership')
        raw = read_file(logs / f'logs/{control_index:02d}-source-controls.stderr.txt', 128 * 1024)
        need(re.findall(rb'^Ran (\d+) tests in [0-9.]+s\r?$', raw, re.M) == [b'4']
            and re.findall(rb'^(OK)\r?$', raw, re.M) == [b'OK']
            and raw.rstrip().endswith(b'OK'), 'four-controls-no-skip')
        receipt['sourceControls'] = {'passed': 4, 'skipped': 0, 'stderr': identities.identity(raw)}
        receipt['stage'] = 'normal-pinned-tools'
        commands.command_seconds = 175
        archive = private / 'gradle.zip'
        commands.run('gradle-download', 'curl', '--fail', '--location', '--proto', '=https',
            '--max-time', '175', '--output', archive,
            'https://services.gradle.org/distributions/gradle-9.1.0-bin.zip')
        gradle_identity = identities.identity(read_file(archive, 160 * 1024**2))
        need(gradle_identity['sha256'] == GRADLE_SHA, 'gradle-identity')
        commands.command_seconds = 25
        commands.run('gradle-unpack', 'unzip', '-q', archive, '-d', private)
        commands.command_seconds = 85
        commands.run('wit-bindgen-install', sys.executable, '-B',
            ROOT / 'tools/install_guest_bindgen.py', private / 'bindgen')
        os.environ['PATH'] = os.pathsep.join((str(private / 'gradle-9.1.0/bin'),
            str(private / 'bindgen'), old_path))
        environment['PATH'] = os.environ['PATH']
        receipt['gradle'] = gradle_identity
        receipt['stage'] = 'normal-installed-compiler-product'
        distribution.acquire(private / 'compiler-inputs', os.environ.get('GH_TOKEN', ''),
            _deadline=commands.deadline)
        sdk = distribution.product(private / 'compiler-inputs', private / 'product',
            output / 'normal-product.json', _deadline=commands.deadline)
        receipt['stage'] = 'normal-scheduled-component-and-reference'
        prepared = private / 'scheduled'
        qualify_java_fibers.prepare(prepared, sdk, gradle=str(private / 'gradle-9.1.0/bin/gradle'),
            fixture='scheduled-library', _deadline=commands.deadline)
        report = json.loads(read_file(prepared / 'FIBERS-COMPILE.json', 8 * 1024**2))
        need(report['status'] == 'component-built-unqualified' and report['qualification'] == 'pending'
            and report['nodeExecution'] == 'not-run' and report['fixture'] == 'scheduled-library'
            and report['libraries']['originalLibraries'] == java_fiber_library_inputs.LIBRARIES,
            'normal-unmodified-component')
        receipt['componentDigest'] = report['componentDigest']
        receipt['javaComponentRecompiled'] = True
        toolchain = tomllib.loads(read_file(ROOT / 'tools/toolchain.toml', 128 * 1024).decode())
        need(toolchain['rust']['toolchain'] == '1.97.1'
            and toolchain['contracts']['wasm-tools'] == '1.254.0', 'normal-tool-pins')
        tools, pins = resolve_tools(toolchain, ROOT, environment, _deadline=commands.deadline)
        environment.update(RUSTC=str(tools['rustc']), RUSTUP_TOOLCHAIN=toolchain['rust']['toolchain'])
        receipt['observedTools'] = pins
        receipt['stage'] = 'build-source-matched-native-harness'
        commands.environment, commands.command_seconds = environment, 895
        build_index = len(commands.records)
        commands.run('build-harness', tools['cargo'], '--config', '.cargo/managed-guest.toml',
            'test', '--locked', '-p', 'latent-wasmtime', '--test', 'local_service',
            '--no-run', '--message-format=json')
        contract, = [row for row in registry.load()['suites']
            if row['id'] == 'latent-wasmtime.test.local-service']
        need(contract['minimumCases'] == len(contract['expectedCases']) and CASE in contract['expectedCases']
            and CASE in contract['expectedIgnored'], 'existing-case-contract')
        suite = artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'local_service',
            'tests/local_service.rs', CASE, frozenset({CASE}), True, kind='test')
        artifact = artifacts.read_inventory(logs / f'logs/{build_index:02d}-build-harness.stdout.txt',
            ROOT, suite, target=target)
        receipt.update(nativeHarnessBuilt=True, executable=file_identity(artifact.executable,
            'local-service-java-scheduled-library', 512 * 1024**2))

        def probe(argv, *, cwd, env, timeout, maximum):
            need(argv == ['rustc', '--print', 'target-libdir'] and cwd == ROOT
                and timeout == 30 and maximum == 4096, 'normal-library-probe')
            commands.command_seconds, commands.environment = 25, env
            raw = commands.run('rust-library-path', tools['rustc'], *argv[1:])
            need(len(raw) <= maximum, 'library-path-bound')
            return 0, raw

        commands.environment = artifacts.cargo_environment(ROOT, artifact, environment, target=target, execute=probe)
        commands.environment.update(LSF_GUEST_SDK_LANGUAGE='java',
            LSF_JAVA_SCHEDULED_LIBRARIES_FIXTURE=str(prepared))
        commands.command_seconds = 25
        listed = commands.run('list-exact-case', artifact.executable, CASE, '--exact', '--ignored', '--list')
        need(len(listed) <= artifacts.MAX_LIST_BYTES, 'list-bound')
        artifacts.validate_listing(listed, suite)
        receipt['stage'] = 'sixteen-signed-scheduled-library-calls'
        commands.command_seconds = 1795
        raw = commands.run('execute-exact-case', artifact.executable, CASE, '--exact', '--ignored',
            '--show-output', '--test-threads=1')
        receipt['observation'] = observations(raw, filtered=len(contract['expectedCases']) - 1)
        java_fiber_library_inputs.check(prepared / 'library-inputs', report['libraries'])
        need(sources(commands, before['native']) == before and java_sources() == java_before, 'final-source')
        need(file_identity(artifact.executable, 'local-service-java-scheduled-library', 512 * 1024**2)
            == receipt['executable'], 'final-executable')
        need([file_identity(tools[name], name) for name in sorted(tools)] == pins, 'final-tools')
        observed.require_source(commands, revision, 'source-head-after')
        need(time.monotonic() < commands.deadline, 'final-deadline')
        receipt.update(status='passed', sourceAfter=before['native'],
            supplementarySourceAfter=before['supplementary'], javaSourceAfter=java_before, sourceUnchanged=True)
    except BaseException:
        receipt['status'] = 'failed'
        raise
    finally:
        os.environ['PATH'] = old_path
        original_failure = sys.exc_info()[0] is not None
        try:
            if prepared is not None:
                receipt['publicProducts'] = retain(prepared, output)
        except BaseException:
            receipt.update(status='failed', publicRetentionFailed=True)
            if not original_failure:
                raise
        finally:
            try:
                if private is not None:
                    shutil.rmtree(private)
                    receipt['privateRootRemoved'] = not private.exists()
            except BaseException:
                receipt.update(status='failed', privateCleanupFailed=True)
                if not original_failure:
                    raise
            finally:
                if time.monotonic() >= commands.deadline:
                    receipt.update(status='failed', finalDeadlineExceeded=True)
                write_json(output / 'receipt.json' if receipt['status'] == 'passed' else output / 'FAILED.json', receipt)
                write_json(output / 'commands.json', commands.records)
                if receipt.get('finalDeadlineExceeded') and not original_failure:
                    raise ValueError('java-scheduled-library-final-deadline')



SHUTDOWN_BRANCH = 'feat/java-cf-shutdown-now-20261028'
SHUTDOWN_CASE = 'runtime::signed_java_shutdown_now_withdraws_only_unstarted_callbacks'
FUTURE_BRANCH = 'feat/java-future-queue-20261028'
FUTURE_CASE = 'runtime::signed_java_future_tasks_retain_result_ownership_across_queue_copies'



def shutdown_sources(commands, names=None):
    return observed.source_domains(commands, 'scheduled', names)


def shutdown_observations(raw, filtered):
    """Read only the four current normal signed activations, never source-ledger credit."""
    need(type(filtered) is int and filtered >= 0, 'shutdown-registry-count')
    need(len(raw) <= artifacts.MAX_OUTPUT_BYTES, 'shutdown-output-bound')
    need(re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$', raw, re.M) ==
        [SHUTDOWN_CASE.encode()], 'shutdown-exact-case')
    need(re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; '
        rb'(\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M) ==
        [(b'1', b'0', b'0', b'0', str(filtered).encode())], 'shutdown-one-executed-no-skip')
    setup = re.findall(rb'^teavm-activation-fibers-v1 signed-preparation-setup-micros=(\d+) '
        rb'stores-created=0 guest-activations=0$', raw, re.M)
    need(len(setup) == 1, 'shutdown-normal-preparation')
    rows = [json.loads(line, object_pairs_hook=registry.unique_object)
        for line in re.findall(rb'^LSF_JAVA_RETAINED=(\{[^\r\n]*\})$', raw, re.M)]
    need(len(rows) == 4, 'shutdown-four-calls')
    created = 0
    for mode, row in enumerate(rows):
        need(type(row) is dict and set(row) == {*observed.ZERO_FIELDS, 'activationId', 'iteration',
            'mode', 'value', 'cpuFuel', 'reportedPeakMemoryBytes', 'storesBefore', 'storesCreated'},
            'shutdown-row-fields')
        need(row['activationId'] == f'java-shutdown-now-0-{mode}' and row['iteration'] == 0
            and row['mode'] == mode and row['value'] == 42, 'shutdown-id-mode-value')
        need(all(type(value) is int and 0 <= value <= 2**64 - 1 for key, value in row.items()
            if key != 'activationId'), 'shutdown-numeric-fields')
        need(0 < row['cpuFuel'] <= 10_000_000_000 and
            0 < row['reportedPeakMemoryBytes'] <= 64 * 1024**2, 'shutdown-original-budget')
        need(row['storesBefore'] == created and row['storesCreated'] > created,
            'shutdown-fresh-stores')
        need(all(row[field] == 0 for field in observed.ZERO_FIELDS), 'shutdown-physical-idle')
        created = row['storesCreated']
    return {'case': SHUTDOWN_CASE, 'passed': 1, 'failed': 0, 'ignored': 0,
        'filteredOut': filtered, 'setupMicroseconds': int(setup[0]), 'calls': rows,
        'stdout': identities.identity(raw)}



def future_observations(raw, filtered):
    """Read only the four current normal signed activations, never source-ledger credit."""
    need(type(filtered) is int and filtered >= 0, 'future-queue-registry-count')
    need(len(raw) <= artifacts.MAX_OUTPUT_BYTES, 'future-queue-output-bound')
    need(re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$', raw, re.M) ==
        [FUTURE_CASE.encode()], 'future-queue-exact-case')
    need(re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; '
        rb'(\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M) ==
        [(b'1', b'0', b'0', b'0', str(filtered).encode())], 'future-queue-one-executed-no-skip')
    setup = re.findall(rb'^teavm-activation-fibers-v1 signed-preparation-setup-micros=(\d+) '
        rb'stores-created=0 guest-activations=0$', raw, re.M)
    need(len(setup) == 1, 'future-queue-normal-preparation')
    rows = [json.loads(line, object_pairs_hook=registry.unique_object)
        for line in re.findall(rb'^LSF_JAVA_RETAINED=(\{[^\r\n]*\})$', raw, re.M)]
    need(len(rows) == 4, 'future-queue-four-calls')
    created = 0
    for mode, row in enumerate(rows):
        need(type(row) is dict and set(row) == {*observed.ZERO_FIELDS, 'activationId', 'iteration',
            'mode', 'value', 'cpuFuel', 'reportedPeakMemoryBytes', 'storesBefore', 'storesCreated'},
            'future-queue-row-fields')
        need(row['activationId'] == f'java-future-queue-0-{mode}' and row['iteration'] == 0
            and row['mode'] == mode and row['value'] == 42, 'future-queue-id-mode-value')
        need(all(type(value) is int and 0 <= value <= 2**64 - 1 for key, value in row.items()
            if key != 'activationId'), 'future-queue-numeric-fields')
        need(0 < row['cpuFuel'] <= 10_000_000_000 and
            0 < row['reportedPeakMemoryBytes'] <= 64 * 1024**2, 'future-queue-original-budget')
        need(row['storesBefore'] == created and row['storesCreated'] > created,
            'future-queue-fresh-stores')
        need(all(row[field] == 0 for field in observed.ZERO_FIELDS), 'future-queue-physical-idle')
        created = row['storesCreated']
    return {'case': FUTURE_CASE, 'passed': 1, 'failed': 0, 'ignored': 0,
        'filteredOut': filtered, 'setupMicroseconds': int(setup[0]), 'calls': rows,
        'stdout': identities.identity(raw)}


def qualify_shutdown(output, revision, *, future_queue=False):
    need(type(future_queue) is bool, 'closed-future-queue-selection')
    branch = FUTURE_BRANCH if future_queue else SHUTDOWN_BRANCH
    case = FUTURE_CASE if future_queue else SHUTDOWN_CASE
    fixture = 'future-queue' if future_queue else 'shutdown-now'
    need(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
        and os.environ.get('GITHUB_REPOSITORY') == identities.REPOSITORY
        and os.environ.get('GITHUB_REF_NAME') == branch
        and os.environ.get('GITHUB_EVENT_NAME') == 'push'
        and os.environ.get('GITHUB_SHA') == revision and os.environ.get('GITHUB_WORKFLOW_SHA') == revision
        and os.environ.get('GITHUB_WORKSPACE') == str(ROOT)
        and os.environ.get('GITHUB_WORKFLOW_REF') == identities.REPOSITORY + '/' + WORKFLOW
            + '@refs/heads/' + branch, 'shutdown-fixed-hosted-push')
    need(not any(key.startswith('LSF_JAVA_') and key.endswith('_FIXTURE') for key in os.environ),
        'shutdown-exclusive-fixture-selector')
    need(re.fullmatch('[0-9a-f]{40}', revision), 'shutdown-source-revision')
    need(output != ROOT and ROOT not in output.parents and output not in ROOT.parents, 'owned-output')
    end = time.monotonic() + 1320
    output = fresh(output)
    environment = build_environment(output)
    target = ROOT / 'target'
    environment.update(CARGO_TARGET_DIR=str(target), CARGO_INCREMENTAL='0', CARGO_BUILD_JOBS='2',
        CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0',
        CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true', CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',
        CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true', CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
    logs = output / 'commands'; logs.mkdir()
    commands = Commands(ROOT, logs, environment, deadline_seconds=1315, command_seconds=25)
    commands.deadline = end - 5
    receipt = {'schemaVersion': 'lsf.java-future-queue.v1' if future_queue else 'lsf.java-cf-shutdown-now.v1', 'status': 'in-progress',
        'sourceRevision': revision, 'case': case, 'javaComponentRecompiled': False,
        'nativeHarnessBuilt': False, 'llvmBuilt': False, 'fullJavaProfileQualified': False,
        'fullCostModelQualified': False, 'hermetic': False, 'compilerImplicitInputsAttested': False,
        'limits': {'overallSeconds': 1320, 'cleanupReserveSeconds': 5, 'maximumCommandSeconds': 1200,
            'compilerAggregateSeconds': 1200, 'compilerCommandSeconds': 595,
            'nativeBuildSeconds': 895, 'caseProcessSeconds': 480, 'calls': 4, 'jobs': 2, 'runtimeResults': 1 if future_queue else 8},
        'prerequisites': 'existing pinned runner JDK/Rust/wasm-tools and dependency-cache actions; '
            'owner deadline includes normal compiler acquisition, Gradle/bindgen, component and native builds, '
            'four calls, retention and cleanup; no claim that runner provisioning is inside this clock'}
    if future_queue:
        receipt.update(referenceJdkResults=[41, 42, 42, 42], signedExpectedResults=[42, 42, 42, 42],
            scope='One Result is held by the remaining accepted FutureTask copy; the second Result is refused before callback entry. '
                'The unbounded reference JDK accepts that second task. This is a bounded cost distinction, not equal resource ceilings.')
    private = prepared = None
    old_path = os.environ.get('PATH', '')
    tools = None
    def current_source(stage):
        commands.command_seconds = 25
        need(commands.run(stage, 'git', '-c', 'core.fsmonitor=false', '-c', 'gc.auto=0',
            'rev-parse', '--verify', 'HEAD').strip() == revision.encode(), 'shutdown-current-source')
    try:
        current_source('source-head-before')
        before, java_before = shutdown_sources(commands), java_sources()
        receipt.update(sourceBefore=before['native'], supplementarySourceBefore=before['supplementary'],
            javaSourceBefore=java_before)
        write_json(output / 'source-inputs.json', {**before, 'java': java_before})
        private = Path(tempfile.mkdtemp(prefix='latent-java-shutdown.', dir='/tmp')); private.chmod(0o700)
        with files.directory(private, owners={0, os.geteuid()}): pass
        receipt['stage'] = 'normal-pinned-tools'
        commands.command_seconds = 175
        archive = private / 'gradle.zip'
        commands.run('gradle-download', 'curl', '--fail', '--location', '--proto', '=https',
            '--max-time', '175', '--output', archive,
            'https://services.gradle.org/distributions/gradle-9.1.0-bin.zip')
        receipt['gradle'] = identities.identity(read_file(archive, 160 * 1024**2))
        need(receipt['gradle']['sha256'] == GRADLE_SHA, 'gradle-identity')
        commands.command_seconds = 25
        commands.run('gradle-unpack', 'unzip', '-q', archive, '-d', private)
        commands.command_seconds = 85
        commands.run('wit-bindgen-install', sys.executable, '-B', ROOT / 'tools/install_guest_bindgen.py',
            private / 'bindgen')
        os.environ['PATH'] = os.pathsep.join((str(private / 'gradle-9.1.0/bin'), str(private / 'bindgen'), old_path))
        environment['PATH'] = os.environ['PATH']
        receipt['stage'] = 'normal-installed-compiler-product'
        distribution.acquire(private / 'compiler-inputs', os.environ.get('GH_TOKEN', ''), _deadline=commands.deadline)
        sdk = distribution.product(private / 'compiler-inputs', private / 'product',
            output / 'normal-product.json', _deadline=commands.deadline)
        receipt['stage'] = 'normal-shutdown-component-and-reference'
        prepared = private / fixture
        qualify_java_fibers.prepare(prepared, sdk, gradle=str(private / 'gradle-9.1.0/bin/gradle'),
            fixture=fixture, _deadline=end)
        report = json.loads(read_file(prepared / 'FIBERS-COMPILE.json', 8 * 1024**2))
        need(report['status'] == 'component-built-unqualified' and report['qualification'] == 'pending'
            and report['nodeExecution'] == 'not-run' and report['fixture'] == fixture, 'shutdown-component')
        receipt.update(componentDigest=report['componentDigest'], javaComponentRecompiled=True)
        toolchain = tomllib.loads(read_file(ROOT / 'tools/toolchain.toml', 128 * 1024).decode())
        need(toolchain['rust']['toolchain'] == '1.97.1' and toolchain['contracts']['wasm-tools'] == '1.254.0', 'normal-tool-pins')
        tools, pins = resolve_tools(toolchain, ROOT, environment, _deadline=commands.deadline)
        environment.update(RUSTC=str(tools['rustc']), RUSTUP_TOOLCHAIN=toolchain['rust']['toolchain'])
        receipt['observedTools'] = pins
        receipt['stage'] = 'source-matched-native-harness'
        commands.environment, commands.command_seconds = environment, 895
        build_index = len(commands.records)
        commands.run('build-harness', tools['cargo'], '--config', '.cargo/managed-guest.toml', 'test',
            '--locked', '-p', 'latent-wasmtime', '--test', 'local_service', '--no-run', '--message-format=json')
        contract, = [row for row in registry.load()['suites'] if row['id'] == 'latent-wasmtime.test.local-service']
        need(contract['minimumCases'] == len(contract['expectedCases']) and
            case in contract['expectedIgnored'], 'shutdown-registered-case')
        suite = artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'local_service',
            'tests/local_service.rs', case, frozenset({case}), True, kind='test')
        artifact = artifacts.read_inventory(logs / f'logs/{build_index:02d}-build-harness.stdout.txt', ROOT, suite, target=target)
        receipt.update(nativeHarnessBuilt=True, executable=file_identity(artifact.executable, 'local-service-java-shutdown-now', 512 * 1024**2))
        def probe(argv, *, cwd, env, timeout, maximum):
            need(argv == ['rustc', '--print', 'target-libdir'] and cwd == ROOT and timeout == 30 and maximum == 4096, 'normal-library-probe')
            commands.command_seconds, commands.environment = 25, env
            raw = commands.run('rust-library-path', tools['rustc'], *argv[1:])
            need(len(raw) <= maximum, 'library-path-bound')
            return 0, raw
        commands.environment = artifacts.cargo_environment(ROOT, artifact, environment, target=target, execute=probe)
        commands.environment.update(LSF_GUEST_SDK_LANGUAGE='java')
        commands.environment['LSF_JAVA_FUTURE_QUEUE_FIXTURE' if future_queue else 'LSF_JAVA_SHUTDOWN_NOW_FIXTURE'] = str(prepared)
        commands.command_seconds = 25
        listed = commands.run('list-exact-case', artifact.executable, case, '--exact', '--ignored', '--list')
        need(len(listed) <= artifacts.MAX_LIST_BYTES, 'list-bound'); artifacts.validate_listing(listed, suite)
        receipt['stage'] = 'four-signed-shutdown-now-calls'
        commands.command_seconds = 480
        raw = commands.run('execute-exact-case', artifact.executable, case, '--exact', '--ignored', '--show-output', '--test-threads=1')
        receipt['observation'] = (future_observations if future_queue else shutdown_observations)(raw, len(contract['expectedCases']) - 1)
        need(shutdown_sources(commands, before['native']) == before and java_sources() == java_before, 'final-source')
        need(file_identity(artifact.executable, 'local-service-java-shutdown-now', 512 * 1024**2) == receipt['executable'], 'final-executable')
        need([file_identity(tools[name], name) for name in sorted(tools)] == pins, 'final-tools')
        current_source('source-head-after')
        need(time.monotonic() < commands.deadline, 'shutdown-final-deadline')
        receipt.update(status='passed', sourceAfter=before['native'],
            supplementarySourceAfter=before['supplementary'], javaSourceAfter=java_before, sourceUnchanged=True)
    except BaseException:
        receipt['status'] = 'failed'
        raise
    finally:
        os.environ['PATH'] = old_path
        failed = sys.exc_info()[0] is not None
        try:
            if prepared is not None: receipt['publicProducts'] = retain(prepared, output)
        except BaseException:
            receipt.update(status='failed', publicRetentionFailed=True)
            if not failed: raise
        finally:
            try:
                if private is not None:
                    commands.deadline, commands.command_seconds = end, 5
                    commands.run('cleanup', sys.executable, '-B', '-c',
                        'import shutil,sys; shutil.rmtree(sys.argv[1])', str(private))
                    receipt['privateRootRemoved'] = not private.exists()
            except BaseException:
                receipt.update(status='failed', privateCleanupFailed=True)
                if not failed: raise
            finally:
                if time.monotonic() >= end: receipt.update(status='failed', finalDeadlineExceeded=True)
                write_json(output / ('receipt.json' if receipt['status'] == 'passed' else 'FAILED.json'), receipt)
                write_json(output / 'commands.json', commands.records)
                if receipt.get('finalDeadlineExceeded') and not failed: raise ValueError('java-shutdown-now-final-deadline')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--shutdown-now', action='store_true')
    modes.add_argument('--future-queue', action='store_true')
    args = parser.parse_args()
    if args.future_queue: qualify_shutdown(args.output.resolve(), args.source_commit, future_queue=True)
    else: (qualify_shutdown if args.shutdown_now else qualify)(args.output.resolve(), args.source_commit)
