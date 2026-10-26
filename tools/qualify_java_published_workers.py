"""One ordinary published-worker component and twelve normal signed calls."""
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
from tools.build_observation import build_environment, file_identity, resolve_tools
from tools.build_snapshot import SOURCE_ALLOWLIST, SnapshotLimits
from tools.java_guest import compiler_profile_distribution as distribution
from tools.java_guest import retained_fiber_inputs as identities
from tools.native_runtime import files
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json

BRANCH = 'feat/java-published-workers-20261026'
WORKFLOW = '.github/workflows/java-published-workers.yml'
CASE = observed.WORKER_CASE
GRADLE_SHA = 'a17ddd85a26b6a7f5ddb71ff8b05fc5104c0202c6e64782429790c933686c806'
PUBLIC_FILES = ('src/Capsule.java', 'wit/service.wit', 'build/component.wasm',
                'FIBERS-COMPILE.json', 'compiler-inputs.json',
                'library-inputs/receipts/capture.json', 'library-inputs/receipts/java-classpath.json',
                'library-inputs/candidate.json', 'library-inputs/application/java-dependencies.json',
                'library-inputs/application/java-resolved.lock.json',
                'library-inputs/application/latent.dependencies.json',
                'library-inputs/application/latent.dependencies.lock.json')


def need(value, reason):
    if not value:
        raise ValueError('java-published-workers-' + reason)


def sources(commands, names=None):
    if names is None:
        commands.command_seconds = 25
        raw = commands.run('source-paths', 'git', 'ls-files', '-z', '--', *SOURCE_ALLOWLIST)
        need(len(raw) <= 2 * 1024**2, 'source-path-bound')
        names = set(raw.decode().strip('\0').split('\0')) | set(observed.EXTRA_SOURCES) | {WORKFLOW}
    limits = SnapshotLimits()
    need(100 <= len(names) <= limits.max_entries, 'source-count')
    result = {name: identities.identity(read_file(ROOT / name, limits.max_file_bytes))
              for name in sorted(names)}
    need(sum(row['bytes'] for row in result.values()) <= limits.max_total_bytes, 'source-total')
    return result


def java_sources():
    # Existing normal Java authoring input domain, separate from the native tar.
    values = java_capsule_project.authoring_inputs(ROOT)
    need(len(values) <= 4096 and sum(map(len, values.values())) <= 32 * 1024**2,
         'java-source-bound')
    return {name: identities.identity(value) for name, value in values.items()}


def retain(prepared, output):
    """Closed public products only; no private Maven/SDK/key directory upload."""
    result = {}
    for name in PUBLIC_FILES:
        source = prepared / name
        if source.is_file():
            maximum = 64 * 1024**2 if name.endswith('.wasm') else 8 * 1024**2
            raw = read_file(source, maximum)
            target = output / 'component' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            result['component/' + name] = identities.identity(raw)
    captured = prepared / 'library-inputs/receipts/capture.json'
    if captured.is_file():
        report = json.loads(read_file(captured, 8 * 1024**2))
        java_fiber_library_inputs.check(prepared / 'library-inputs', report)
        accepted = java_fiber_library_inputs.verify_inputs(prepared / 'library-inputs/application', 'java')
        need(accepted is not None and len(report['selectedJars']) == 2, 'retained-library-closure')
        artifacts_by_id = {row['id']: row for row in accepted.lock['artifacts']
                           if row['id'] in java_fiber_library_inputs.LIBRARIES}
        need(set(artifacts_by_id) == set(java_fiber_library_inputs.LIBRARIES), 'retained-library-set')
        for index, row in enumerate(report['selectedJars']):
            original = prepared / 'library-inputs/offline-inputs' / artifacts_by_id[row['id']]['mount']
            selected = prepared / f'library-inputs/selected-application-jars/{index:04d}.jar'
            for kind, source, digest in (('original', original, row['originalDigest']),
                                         ('selected', selected, row['selectedDigest'])):
                raw = read_file(source, 64 * 1024**2)
                identity = identities.identity(raw)
                need('sha256:' + identity['sha256'] == digest, 'retained-library-digest')
                name = f'libraries/{index}.{kind}.jar'
                target = output / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
                result[name] = identity
    compiler = prepared / 'compiler'
    # The normal compiler's own top-level public command metadata and logs.
    selected = sorted([*compiler.glob('*.command.json'), *compiler.glob('*.log')])
    need(len(selected) <= 256, 'compiler-log-count')
    total = 0
    for source in selected:
        raw = read_file(source, 16 * 1024**2)
        total += len(raw)
        need(total <= 64 * 1024**2, 'compiler-log-total')
        target = output / 'compiler' / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        result['compiler/' + source.name] = identities.identity(raw)
    return result


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
    receipt = {'schemaVersion': 'lsf.java-published-workers.v1', 'status': 'in-progress',
        'sourceRevision': revision, 'case': CASE, 'javaComponentRecompiled': False,
        'llvmBuilt': False, 'nativeHarnessBuilt': False, 'fullJavaProfileQualified': False,
        'fullCostModelQualified': False, 'hermetic': False, 'compilerImplicitInputsAttested': False,
        'limits': {'overallSeconds': 2400, 'cleanupReserveSeconds': 5,
            'compilerAggregateSeconds': 1200, 'compilerCommandSeconds': 600,
            'nativeBuildSeconds': 900, 'caseProcessSeconds': 1800, 'listProcessSeconds': 30,
            'sourceControlSeconds': 60},
        'libraries': java_fiber_library_inputs.LIBRARIES,
        'scope': 'unchanged ordinary library factories with explicit finite runtime-wait callbacks; '
            'no application executor injection, published timer client or complete profile claim'}
    private = None
    prepared = None
    old_path = os.environ.get('PATH', '')
    try:
        artifacts.require_source(ROOT, revision, environment)
        before, java_before = sources(commands), java_sources()
        receipt.update(sourceBefore=before, javaSourceBefore=java_before)
        write_json(output / 'source-inputs.json', {'native': before, 'java': java_before})
        private = Path(tempfile.mkdtemp(prefix='latent-java-workers.', dir='/tmp'))
        private.chmod(0o700)
        with files.directory(private, owners={0, os.geteuid()}):
            pass  # Original installer ancestry/ACL policy, before component cost.
        receipt['stage'] = 'focused-source-controls'
        commands.command_seconds = 55
        commands.run('source-controls', sys.executable, '-B', '-m', 'unittest', '-v',
            'tools.tests.test_java_published_workers')
        raw = read_file(logs / 'logs/01-source-controls.stderr.txt', 128 * 1024)
        need(re.search(rb'^Ran 4 tests in [0-9.]+s\r?$', raw, re.M)
            and re.search(rb'^OK\r?$', raw, re.M) and b'skipped' not in raw, 'four-controls-no-skip')
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
        receipt['stage'] = 'normal-worker-component-and-reference'
        prepared = private / 'worker'
        qualify_java_fibers.prepare(prepared, sdk, gradle=str(private / 'gradle-9.1.0/bin/gradle'),
            fixture='worker-libraries', _deadline=commands.deadline)
        report = json.loads(read_file(prepared / 'FIBERS-COMPILE.json', 8 * 1024**2))
        need(report['status'] == 'component-built-unqualified' and report['qualification'] == 'pending'
            and report['nodeExecution'] == 'not-run' and report['fixture'] == 'worker-libraries'
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
        need(contract['minimumCases'] == 52 and CASE in contract['expectedCases']
            and CASE in contract['expectedIgnored'], 'existing-case-contract')
        suite = artifacts.Suite('crates/latent-wasmtime/Cargo.toml', 'local_service',
            'tests/local_service.rs', CASE, frozenset({CASE}), True, kind='test')
        artifact = artifacts.read_inventory(logs / f'logs/{build_index:02d}-build-harness.stdout.txt',
            ROOT, suite, target=target)
        receipt.update(nativeHarnessBuilt=True, executable=file_identity(artifact.executable,
            'local-service-java-published-workers', 512 * 1024**2))

        def probe(argv, *, cwd, env, timeout, maximum):
            need(argv == ['rustc', '--print', 'target-libdir'] and cwd == ROOT
                and timeout == 30 and maximum == 4096, 'normal-library-probe')
            commands.command_seconds, commands.environment = 25, env
            raw = commands.run('rust-library-path', tools['rustc'], *argv[1:])
            need(len(raw) <= maximum, 'library-path-bound')
            return 0, raw

        commands.environment = artifacts.cargo_environment(ROOT, artifact, environment, target=target, execute=probe)
        commands.environment.update(LSF_GUEST_SDK_LANGUAGE='java',
            LSF_JAVA_WORKER_LIBRARIES_FIXTURE=str(prepared))
        commands.command_seconds = 25
        listed = commands.run('list-exact-case', artifact.executable, CASE, '--exact', '--ignored', '--list')
        need(len(listed) <= artifacts.MAX_LIST_BYTES, 'list-bound')
        artifacts.validate_listing(listed, suite)
        receipt['stage'] = 'twelve-signed-worker-calls'
        commands.command_seconds = 1795
        raw = commands.run('execute-exact-case', artifact.executable, CASE, '--exact', '--ignored',
            '--show-output', '--test-threads=1')
        receipt['observation'] = observed.observations(raw, worker=True)
        java_fiber_library_inputs.check(prepared / 'library-inputs', report['libraries'])
        need(sources(commands, before) == before and java_sources() == java_before, 'final-source')
        need(file_identity(artifact.executable, 'local-service-java-published-workers', 512 * 1024**2)
            == receipt['executable'], 'final-executable')
        need([file_identity(tools[name], name) for name in sorted(tools)] == pins, 'final-tools')
        artifacts.require_source(ROOT, revision, environment)
        need(time.monotonic() < commands.deadline, 'final-deadline')
        receipt.update(status='passed', sourceAfter=before, javaSourceAfter=java_before, sourceUnchanged=True)
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
                    raise ValueError('java-published-workers-final-deadline')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    args = parser.parse_args()
    qualify(args.output.resolve(), args.source_commit)
