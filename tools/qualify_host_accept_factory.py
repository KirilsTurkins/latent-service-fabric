"""Run the finite consumer poll-factory ownership controls on one hosted push."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import re
import sys
import time
import tomllib

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import ci_rust_artifacts as artifacts, ci_suite_inventory as registry
from tools import host_codec_wasmtime as source, qualify_stream_outers as common
from tools.build_observation import build_environment, file_identity, resolve_tools
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json

BRANCH = 'feat/sdk-745-host-accept-factory-20261105'
WORKFLOW = '.github/workflows/host-accept-factory.yml'
PRIVATE_NEW = tuple(common.PRIVATE_PREFIX + name for name in (
    'host_accept_refusal_preserves_the_original_transmit_and_can_resume',
    'host_accept_factory_admits_before_invocation_and_releases_after_drop',
    'host_accept_factory_confirmation_unwind_and_uncertain_drop_preserve_ownership',
    'host_accept_factory_none_keeps_literal_box_and_no_reservation'))
PRIVATE_ORIGINAL = (common.PRIVATE_CASES[0],)
PUBLIC = common.PUBLIC_CASES
CASES = (*PRIVATE_NEW, *PRIVATE_ORIGINAL, *PUBLIC)


def require(value, reason):
    if not value:
        raise ValueError('host-accept-factory-' + reason)


def case_result(raw, case):
    require(case in CASES and len(raw) <= artifacts.MAX_OUTPUT_BYTES, 'case-and-output')
    matches = re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$', raw, re.M)
    require(matches == [case.encode()], 'one-exact-success')
    summary = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; '
        rb'(\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    require(len(summary) == 1 and summary[0][:4] == (b'1', b'0', b'0', b'0')
        and int(summary[0][4]) <= 10000, 'one-executed-no-skip')
    return {'case': case, 'stdout': common.identity(raw), 'passed': 1, 'failed': 0,
        'ignored': 0, 'filteredOut': int(summary[0][4]),
        'scope': ('private-counter-inline-component' if case in PRIVATE_ORIGINAL
            else 'private-counter-helper' if case in PRIVATE_NEW else 'public-original-ActivationBudget')}


def inputs():
    values = common.source_inputs()
    values[WORKFLOW] = common.identity(read_file(ROOT / WORKFLOW, 128 * 1024))
    return dict(sorted(values.items()))


def qualify(output, revision):
    require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
        and os.environ.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric'
        and os.environ.get('GITHUB_REF_NAME') == BRANCH and os.environ.get('GITHUB_EVENT_NAME') == 'push',
        'exact-hosted-push')
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents, 'owned-output')
    output = fresh(output)
    environment = build_environment(output)
    environment.pop(common.FIXTURE_ENV, None)
    environment.update(CARGO_TARGET_DIR=str(ROOT / 'target'), CARGO_INCREMENTAL='0',
        CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0',
        CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true', CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',
        CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true', CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
    logs = output / 'commands'; logs.mkdir()
    commands = Commands(ROOT, logs, environment, deadline_seconds=2395, command_seconds=895)
    receipt = {'schemaVersion': 'lsf.host-accept-factory.v1', 'status': 'in-progress',
        'sourceRevision': revision, 'cases': list(CASES), 'observations': [],
        'scope': 'one HostToHost accept factory; returned futures and HostToHost buffers remain unpaid',
        'fullCostModelQualified': False, 'fullRuntimeSuiteExecuted': False,
        'fullVendorSuiteExecuted': False, 'signedGuestExecuted': False,
        'hermetic': False, 'compilerImplicitInputsAttested': False,
        'publicOriginalBudget': {'memoryBytes': 1024**2, 'cpuFuel': 1_000_000_000, 'wallTimeMilliseconds': 5000},
        'privateCounterOwner': {'originalActivationBudget': False,
            'guestScope': 'only the selected inline-component case if executed; no signed SDK guest'},
        'limits': {'overallSeconds': 2400, 'buildCommandSeconds': 900,
            'caseProcessSeconds': 60, 'listProcessSeconds': 30, 'cleanupReserveSeconds': 5}}
    try:
        artifacts.require_source(ROOT, revision, environment)
        before = inputs(); receipt['sourceBefore'] = before
        write_json(output / 'source-inputs.json', before)
        checked = source.verify(); receipt['wasmtimeSource'] = checked
        toolchain = tomllib.loads(read_file(ROOT / 'tools/toolchain.toml', 128 * 1024).decode())
        require(toolchain['rust']['toolchain'] == '1.97.1'
            and toolchain['contracts']['wasm-tools'] == '1.254.0', 'normal-tool-pins')
        tools, pins = resolve_tools(toolchain, ROOT, environment, _deadline=commands.deadline)
        receipt['observedTools'] = pins
        environment.update(RUSTC=str(tools['rustc']), RUSTUP_TOOLCHAIN=toolchain['rust']['toolchain'])
        fixture_dir = output / 'fixtures'; fixture_dir.mkdir()
        fixture = fixture_dir / 'native-stream-outers.wasm'
        commands.command_seconds = 55
        commands.run('parse-fixed-fixture', tools['wasm-tools'], 'parse', ROOT / common.WAT, '-o', fixture)
        bound_fixture = common.fixture_identity(fixture)
        receipt['fixture'] = {'wat': before[common.WAT], 'component': bound_fixture}

        def runtime_environment(artifact, label):
            def probe(argv, *, cwd, env, timeout, maximum):
                require(argv == ['rustc', '--print', 'target-libdir'] and cwd == ROOT
                    and timeout == 30 and maximum == 4096, 'normal-library-probe')
                commands.command_seconds = 25; commands.environment = env
                raw = commands.run(label + '-rust-library-path', tools['rustc'], *argv[1:])
                require(len(raw) <= maximum, 'rust-library-output-bound')
                return 0, raw
            return artifacts.cargo_environment(ROOT, artifact, environment,
                target=ROOT / 'target', execute=probe)

        targets = (
            ('private', (*PRIVATE_NEW, *PRIVATE_ORIGINAL),
             ('test', '--manifest-path', 'crates/vendor/wasmtime/Cargo.toml', '--locked', '--lib',
              '--no-default-features', '--features', common.FEATURES, '--no-run', '--message-format=json'),
             artifacts.Suite('crates/vendor/wasmtime/Cargo.toml', 'wasmtime', 'src/lib.rs',
                common.PRIVATE_PREFIX, frozenset((*PRIVATE_NEW, *PRIVATE_ORIGINAL)), True)),
            ('public', PUBLIC, ('test', '-p', 'latent-wasmtime', '--locked', '--lib', '--no-run',
                '--message-format=json'), artifacts.Suite('crates/latent-wasmtime/Cargo.toml',
                'latent_wasmtime', 'src/lib.rs', common.PUBLIC_PREFIX, frozenset(PUBLIC), True)),
        )
        executables = []
        for label, cases, argv, suite in targets:
            receipt['stage'] = 'build-' + label
            require(common.fixture_identity(fixture) == bound_fixture, 'fixture-before-build')
            commands.environment = environment; commands.command_seconds = 895
            ordinal = len(commands.records); commands.run('build-' + label, tools['cargo'], *argv)
            artifact = artifacts.read_inventory(logs / f'logs/{ordinal:02d}-build-{label}.stdout.txt',
                ROOT, suite, target=ROOT / 'target')
            executable = file_identity(artifact.executable, label + '-consumer-controls', 512 * 1024**2)
            receipt[label + 'Executable'] = executable
            executables.append((artifact.executable, executable, label + '-consumer-controls'))
            run_env = runtime_environment(artifact, label); run_env.pop(common.FIXTURE_ENV, None)
            if label == 'private':
                run_env[common.FIXTURE_ENV] = str(fixture)
            else:
                contract, = [row for row in registry.load()['suites'] if row['id'] == 'latent-wasmtime.lib.latent-wasmtime']
                require(not set(cases) & set(contract['expectedIgnored']), 'public-suite-contract')
            commands.environment = run_env
            for index, case in enumerate(cases):
                receipt['stage'] = case
                require(common.fixture_identity(fixture) == bound_fixture, 'fixture-before-case')
                ignored = ('--ignored',) if case in PRIVATE_ORIGINAL else ()
                commands.command_seconds = 25
                listed = commands.run(f'{label}-list-{index}', artifact.executable, case, '--exact', *ignored, '--list')
                require(len(listed) <= artifacts.MAX_LIST_BYTES, 'list-bound')
                artifacts.validate_listing(listed, artifacts.Suite(suite.manifest, suite.target, suite.source,
                    case, frozenset((case,)), True))
                commands.command_seconds = 55
                raw = commands.run(f'{label}-case-{index}', artifact.executable, case, '--exact', *ignored,
                    '--show-output', '--test-threads=1')
                receipt['observations'].append(case_result(raw, case))
                require(common.fixture_identity(fixture) == bound_fixture, 'fixture-after-case')
        require(len(commands.records) == 19 and len(receipt['observations']) == len(CASES) == 7,
            'one-fixture-two-builds-seven-cases')
        require(time.monotonic() < commands.deadline and inputs() == before and source.verify() == checked, 'final-source')
        for path, bound, label in executables:
            require(file_identity(path, label, 512 * 1024**2) == bound, 'final-executable')
        require(common.fixture_identity(fixture) == bound_fixture
            and [file_identity(tools[name], name) for name in sorted(tools)] == pins, 'final-fixture-and-tools')
        artifacts.require_source(ROOT, revision, environment)
        require(time.monotonic() < commands.deadline, 'final-deadline')
        receipt.update(status='passed', sourceAfter=before, sourceUnchanged=True, executed=list(CASES), ignored=[])
        write_json(output / 'receipt.json', receipt)
    except BaseException:
        receipt['status'] = 'failed'; write_json(output / 'FAILED.json', receipt); raise
    finally:
        write_json(output / 'commands.json', commands.records)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    qualify(args.output.resolve(), args.source_commit)
