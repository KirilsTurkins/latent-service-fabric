"""Run the existing twelve signed Java fiber calls without rebuilding their component."""
from __future__ import annotations

import argparse
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
from tools.build_observation import build_environment, file_identity, resolve_tools
from tools.build_snapshot import SOURCE_ALLOWLIST, SnapshotLimits
from tools.java_guest import retained_fiber_inputs as inputs
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json

BRANCH = 'feat/java-retained-fibers-runtime-20261026'
WORKFLOW = '.github/workflows/java-retained-fibers.yml'
CASE = 'runtime::signed_java_threads_spin_join_and_thread_local_use_real_activation_fibers'
WORKER_CASE = 'runtime::signed_java_published_libraries_use_unchanged_default_workers'
JAVA = 'sdk/java-guest/fibers/conformance/'
EXTRA_SOURCES = tuple(JAVA + name + 'Capsule.java' for name in (
    '', 'completable/', 'fiber-io/', 'worker-libraries/', 'timers/')) + tuple(
    'sdk/go-guest/runtime/' + name + '/main.go' for name in (
        'synchronization-conformance', 'managed-idle-conformance', 'published-conformance',
        'initializers-conformance', 'timers-conformance', 'checkpoints-conformance', 'conformance')) + (
    'sdk/rust-standard-runtime/owned-child-fixture/core.wat',
    'sdk/rust-standard-runtime/owned-child-fixture/world.wit')
ZERO_FIELDS = ('liveStores', 'activeReservations', 'brokerCalls', 'brokerSessions',
               'brokerHandles', 'brokerResults', 'brokerBufferBytes')


def need(value, reason):
    if not value:
        raise ValueError('java-retained-runtime-' + reason)


def source_inputs():
    raw = subprocess.check_output(['git', 'ls-files', '-z', '--', *SOURCE_ALLOWLIST],
        cwd=ROOT, timeout=30)
    need(len(raw) <= 2 * 1024**2, 'source-path-bound')
    names = set(raw.decode().strip('\0').split('\0')) | set(EXTRA_SOURCES) | {WORKFLOW}
    limits = SnapshotLimits()
    need(100 <= len(names) <= limits.max_entries, 'source-count')
    result = {name: inputs.identity(read_file(ROOT / name, limits.max_file_bytes))
              for name in sorted(names)}
    need(sum(row['bytes'] for row in result.values()) <= limits.max_total_bytes, 'source-total')
    return result


def observations(raw, *, worker=False):
    need(type(worker) is bool, 'closed-observation-selection')
    case = WORKER_CASE if worker else CASE
    fixture = 'java-worker-libraries' if worker else 'java-fibers'
    profile = b'teavm-activation-fibers-io-v1' if worker else b'teavm-activation-fibers-v1'
    need(len(raw) <= artifacts.MAX_OUTPUT_BYTES, 'output-bound')
    need(re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$', raw, re.M) == [case.encode()], 'exact-case')
    summaries = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; '
        rb'(\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    need(summaries == [(b'1', b'0', b'0', b'0', b'51')], 'one-executed-no-skip')
    setup = re.findall(rb'^' + profile + rb' signed-preparation-setup-micros=(\d+) '
        rb'stores-created=0 guest-activations=0$', raw, re.M)
    need(len(setup) == 1, 'normal-preparation')
    rows = [json.loads(line, object_pairs_hook=registry.unique_object)
            for line in re.findall(rb'^LSF_JAVA_RETAINED=(\{[^\r\n]*\})$', raw, re.M)]
    need(len(rows) == 12, 'twelve-calls')
    created = 0
    for index, row in enumerate(rows):
        iteration, mode = divmod(index, 4)
        expected_id = f'{fixture}-{iteration}-{mode}'
        need(type(row) is dict and set(row) == {*ZERO_FIELDS, 'activationId', 'iteration', 'mode',
            'value', 'cpuFuel', 'reportedPeakMemoryBytes', 'storesBefore', 'storesCreated'}, 'row-fields')
        need(row['activationId'] == expected_id and row['iteration'] == iteration
            and row['mode'] == mode and row['value'] == 42, 'actual-id-mode-value')
        need(all(type(value) is int and 0 <= value <= 2**64 - 1
            for key, value in row.items() if key != 'activationId'), 'numeric-fields')
        need(0 < row['cpuFuel'] <= 10_000_000_000
            and 0 < row['reportedPeakMemoryBytes'] <= 64 * 1024**2, 'original-budget')
        need(row['storesBefore'] == created and row['storesCreated'] > created, 'fresh-stores')
        need(all(row[field] == 0 for field in ZERO_FIELDS), 'actual-idle-counters')
        created = row['storesCreated']
    return {'case': case, 'passed': 1, 'failed': 0, 'ignored': 0, 'filteredOut': 51,
            'setupMicroseconds': int(setup[0]), 'calls': rows, 'stdout': inputs.identity(raw)}


def qualify(output, revision):
    need(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
        and os.environ.get('GITHUB_REPOSITORY') == inputs.REPOSITORY
        and os.environ.get('GITHUB_REF_NAME') == BRANCH
        and os.environ.get('GITHUB_EVENT_NAME') == 'push'
        and os.environ.get('GITHUB_SHA') == revision
        and os.environ.get('GITHUB_WORKFLOW_SHA') == revision
        and os.environ.get('GITHUB_WORKSPACE') == str(ROOT)
        and os.environ.get('GITHUB_WORKFLOW_REF') == inputs.REPOSITORY + '/'
            + WORKFLOW + '@refs/heads/' + BRANCH, 'fixed-hosted-push')
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
    # Five seconds of process cleanup are inside every declared wall cap.
    commands = Commands(ROOT, logs, environment, deadline_seconds=2395, command_seconds=895)
    receipt = {'schemaVersion': 'lsf.java-retained-fibers.v1', 'status': 'in-progress',
        'sourceRevision': revision, 'case': CASE, 'javaComponentRecompiled': False,
        'llvmBuilt': False, 'nativeHarnessBuilt': False, 'fullJavaProfileQualified': False,
        'fullCostModelQualified': False, 'hermetic': False,
        'compilerImplicitInputsAttested': False,
        'limits': {'overallSeconds': 2400, 'buildCommandSeconds': 900,
            'caseProcessSeconds': 1800, 'listProcessSeconds': 30, 'cleanupReserveSeconds': 5},
        'activationLimits': {'cpuFuel': 10_000_000_000, 'memoryBytes': 64 * 1024**2,
            'wallTimeMilliseconds': 120000, 'outboundRequests': 0, 'cells': 1,
            'tasks': 5, 'executors': 3, 'queuedWork': 8, 'waits': 8, 'timers': 2,
            'results': 8, 'nativeOwners': 2}}
    try:
        artifacts.require_source(ROOT, revision, environment)
        before = source_inputs()
        receipt['sourceBefore'] = before
        write_json(output / 'source-inputs.json', before)
        receipt['stage'] = 'authenticate-retained-component'
        prepared = fresh(output / 'private-inputs')
        receipt['componentOrigin'] = inputs.acquire(prepared, commands.deadline, os.environ.get('GH_TOKEN', ''))
        receipt['componentInputs'] = inputs.FILES
        receipt['stage'] = 'three-pure-input-controls'
        commands.command_seconds = 25
        commands.environment = {**environment, 'LSF_JAVA_RETAINED_ARCHIVE': str(prepared / 'public-component.zip')}
        commands.run('input-controls', sys.executable, '-B', '-m', 'unittest', '-v',
            'tools.tests.test_java_retained_fibers')
        control_output = read_file(logs / 'logs/00-input-controls.stderr.txt', 128 * 1024)
        need(re.search(rb'^Ran 3 tests in [0-9.]+s\r?$', control_output, re.M)
            and re.search(rb'^OK\r?$', control_output, re.M)
            and b'skipped' not in control_output, 'three-controls-no-skip')
        receipt['sourceControls'] = {'passed': 3, 'skipped': 0, 'stderr': inputs.identity(control_output)}
        toolchain = tomllib.loads(read_file(ROOT / 'tools/toolchain.toml', 128 * 1024).decode())
        need(toolchain['rust']['toolchain'] == '1.97.1'
            and toolchain['contracts']['wasm-tools'] == '1.254.0', 'normal-tool-pins')
        tools, pins = resolve_tools(toolchain, ROOT, environment, _deadline=commands.deadline)
        receipt['observedTools'] = pins
        environment.update(RUSTC=str(tools['rustc']), RUSTUP_TOOLCHAIN=toolchain['rust']['toolchain'])
        receipt['stage'] = 'build-source-matched-harness'
        commands.environment = environment
        commands.command_seconds = 895
        commands.run('build-harness', tools['cargo'], '--config', '.cargo/managed-guest.toml',
            'test', '--locked', '-p', 'latent-wasmtime', '--test', 'local_service',
            '--no-run', '--message-format=json')
        contract, = [row for row in registry.load()['suites']
            if row['id'] == 'latent-wasmtime.test.local-service']
        need(contract['minimumCases'] == 52 and CASE in contract['expectedCases']
            and CASE in contract['expectedIgnored'], 'existing-case-contract')
        suite = artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'local_service',
            'tests/local_service.rs', CASE, frozenset({CASE}), True, kind='test')
        artifact = artifacts.read_inventory(logs / 'logs/01-build-harness.stdout.txt', ROOT, suite, target=target)
        receipt.update(nativeHarnessBuilt=True, executable=file_identity(artifact.executable,
            'local-service-java-retained', 512 * 1024**2))

        def probe(argv, *, cwd, env, timeout, maximum):
            need(argv == ['rustc', '--print', 'target-libdir'] and cwd == ROOT
                and timeout == 30 and maximum == 4096, 'normal-library-probe')
            commands.command_seconds = 25
            commands.environment = env
            raw = commands.run('rust-library-path', tools['rustc'], *argv[1:])
            need(len(raw) <= maximum, 'library-path-bound')
            return 0, raw

        commands.environment = artifacts.cargo_environment(ROOT, artifact, environment, target=target, execute=probe)
        commands.environment.update(LSF_GUEST_SDK_LANGUAGE='java', LSF_JAVA_FIBER_FIXTURE=str(prepared))
        commands.command_seconds = 25
        listed = commands.run('list-exact-case', artifact.executable, CASE, '--exact', '--ignored', '--list')
        need(len(listed) <= artifacts.MAX_LIST_BYTES, 'list-bound')
        artifacts.validate_listing(listed, suite)
        receipt['stage'] = 'execute-twelve-original-calls'
        commands.command_seconds = 1795
        raw = commands.run('execute-exact-case', artifact.executable, CASE, '--exact', '--ignored',
            '--show-output', '--test-threads=1')
        receipt['observation'] = observations(raw)
        inputs.recheck(prepared)
        need(source_inputs() == before, 'final-source')
        need(file_identity(artifact.executable, 'local-service-java-retained', 512 * 1024**2)
            == receipt['executable'], 'final-executable')
        need([file_identity(tools[name], name) for name in sorted(tools)] == pins, 'final-tools')
        artifacts.require_source(ROOT, revision, environment)
        need(time.monotonic() < commands.deadline, 'final-deadline')
        receipt.update(status='passed', sourceAfter=before, sourceUnchanged=True)
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
