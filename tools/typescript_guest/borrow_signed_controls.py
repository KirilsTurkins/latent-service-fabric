"""One fresh private probe component and one finite signed logical-reference test.

No native engine/library/compiler build occurs here. Original successful OWN
prerequisites must pass the unchanged normal source validators first.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import time
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, read_file, write_json, fresh, digest, inventory, snapshot
from tools.typescript_guest import activation_engine, borrow_probe_profile as profile, borrow_signed_inputs as inputs
from tools.typescript_guest.build import RECIPE as COMPILER_RECIPE
from tools.typescript_guest.compiler import Compiler
from tools.typescript_guest.project import create
from tools.typescript_guest.runtime_profile import IMPORT_PROFILE

TEST = 'signed_borrow_release_preserves_original_socket_until_consuming_close_and_root_retirement'
TARGET = 'typescript_import_borrow_release'
RECIPE = tuple(dict.fromkeys((*COMPILER_RECIPE, *profile.RECIPE,
    'tools/qualify_typescript_borrow_signed.py', 'tools/typescript_guest/borrow_signed_controls.py',
    'tools/typescript_guest/borrow_signed_inputs.py', 'tools/java_replay_materials.py',
    '.github/workflows/typescript-borrow-signed.yml', 'Cargo.toml', 'Cargo.lock', 'rust-toolchain.toml',
    'crates/latent-wasmtime/Cargo.toml',
    'crates/latent-wasmtime/src/lib.rs', 'crates/latent-wasmtime/src/backend.rs',
    'crates/latent-wasmtime/src/containment.rs', 'crates/latent-wasmtime/src/development_trap_observer.rs',
    'crates/latent-wasmtime/src/development_borrow_admission.rs', 'crates/latent-wasmtime/src/host.rs',
    'crates/latent-wasmtime/src/host/runtime.rs',
    'crates/latent-wasmtime/src/config.rs', 'crates/latent-wasmtime/src/config/engine.rs',
    'crates/latent-wasmtime/src/config/profile.rs',
    'crates/latent-wasmtime/tests/typescript_import_borrow_release.rs',
    'crates/latent-wasmtime/tests/typescript_import_borrow_release/gate.rs',
    'crates/latent-wasmtime/tests/typescript_import_borrow_release/composition.rs',
    'crates/latent-wasmtime/tests/local_service/packages.rs',
    'crates/latent-wasmtime/tests/local_service/fixture.rs',
    'crates/latent-wasmtime/tests/guest_sdk/package.rs',
    'crates/latent-packaging/tests/fixtures/host.rs',
    'tools/tests/test_typescript_borrow_probe_profile.py',
    'tools/tests/test_typescript_native_carrier_scheduling.py',
    'tools/tests/test_typescript_borrow_signed_inputs.py')))


class Deadline:
    def __init__(self):
        raw = os.environ.get('LSF_BORROW_SIGNED_STARTED_NS', '')
        require(re.fullmatch(r'[1-9][0-9]{0,19}', raw) is not None, 'borrow-signed-setup-clock-required')
        elapsed = (time.time_ns() - int(raw)) / 1_000_000_000
        require(0 <= elapsed < 4500, 'borrow-signed-setup-deadline')
        self.end = time.monotonic() + 4500 - elapsed
        self.setup = elapsed
    def remaining(self, maximum):
        value = min(maximum, self.end - time.monotonic())
        require(value > 0, 'borrow-signed-aggregate-deadline')
        return value
    def finish(self): self.remaining(1)


def records(raw):
    values = []
    for line in raw.decode().splitlines():
        for kind in ('COMPOSITION', 'OWNER', 'CASE', 'COMPLETE'):
            prefix = 'TYPESCRIPT_BORROW_' + kind + ' '
            raw_line = line.removeprefix('test ' + TEST + ' ... ')
            if raw_line.startswith(prefix): values.append({'kind': kind, 'value': json.loads(raw_line[len(prefix):])})
    cases = [row['value'] for row in values if row['kind'] == 'CASE']
    expected = {'normal-copy-dispose': 3, 'logical-cancel-before-borrow-release': 0,
        'root-trap-with-held-borrow': 1, 'fresh-after-trap': 3,
        'root-deadline-with-held-borrow': 2, 'fresh-after-deadline': 3}
    require(len(cases) == len(expected) and {row['case']: row['mode'] for row in cases} == expected
            and all(row['kernelRetirementQualified'] is False and row['productionProviderInstalled'] is False
                and type(row['consumedOutboundRequests']) is int and 0 <= row['consumedOutboundRequests'] <= 8
                and row['plannedNetworkWitDispatches'] == (5 if row['mode'] == 3 else 8)
                and row['status'] == ('succeeded' if row['mode'] in (0,3) else 'intended-platform-failure')
                for row in cases), 'borrow-signed-six-actual-cases')
    complete = [row['value'] for row in values if row['kind'] == 'COMPLETE']
    require(complete == [{'semanticCases': 4, 'freshAfterFailure': 2,
        'kernelRetirementQualified': False, 'wholeCostQualification': False, 'productionEnablement': False}],
        'borrow-signed-actual-complete-record')
    require(len([row for row in values if row['kind'] == 'COMPOSITION']) == 1
            and len([row for row in values if row['kind'] == 'OWNER']) >= 10,
            'borrow-signed-actual-composition-owner-records')
    return values


def qualify(tools, material_directory, output):
    require(sys.platform == 'linux' and platform.machine() in ('x86_64', 'AMD64')
            and sys.version_info[:3] == (3,13,5), 'borrow-signed-linux-pinned-python')
    tools, material_directory = map(lambda path: path.resolve(strict=True), (tools, material_directory))
    output = output.resolve()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents
            and all(output != path and output not in path.parents and path not in output.parents
                    for path in (tools, material_directory)), 'borrow-signed-separated-output')
    output = fresh(output)
    deadline = Deadline()
    environment = build_environment(output)
    environment.update(CARGO_BUILD_JOBS='2', CARGO_INCREMENTAL='0', RUSTUP_TOOLCHAIN='1.97.1',
        CARGO_HOME=str(output/'cargo-home'), CARGO_TARGET_DIR=str(output/'cargo-target'),
        CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0')
    recipe = {name: file_identity(ROOT/name) for name in RECIPE}
    record = {'schemaVersion': 'latent.typescript.borrow-signed.v1', 'status': 'in-progress',
        'scope': 'signed-canonical-borrow-release-logical-reference', 'recipe': recipe,
        'setupElapsedSeconds': deadline.setup, 'engineBuildCount': 0, 'libraryBuildCount': 0,
        'guestComponentBuildCount': 0, 'semanticCases': 4, 'freshAfterFailure': 2,
        'kernelRetirementQualified': False, 'wholeCostQualification': False, 'productionEnablement': False,
        'limits': {'overallSeconds': 4500, 'guestCompileSeconds': 900, 'hostBuildSeconds': 1800,
            'signedTestSeconds': 600, 'rustJobs': 2, 'outboundRequests': 8, 'streamChunks': 4}, 'commands': []}
    command_directory = output/'commands'; command_directory.mkdir()
    retained = 0
    def run(label, *arguments, cwd=ROOT, env=None, seconds=60):
        nonlocal retained
        require(re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', label) is not None, 'borrow-signed-command-label')
        ordinal = len(record['commands']); prefix = command_directory/f'{ordinal:03d}-{label}'
        maximum = deadline.remaining(seconds); began = time.monotonic()
        argv = list(map(str, arguments))
        write_json(prefix.with_suffix('.command.json'), {'argv': argv, 'maximumSeconds': maximum})
        result = run_bounded_result(argv, cwd, env or environment, timeout_seconds=maximum, max_output_bytes=4*1024**2)
        retained += len(result.stdout) + len(result.stderr)
        require(retained <= 32*1024**2, 'borrow-signed-total-diagnostic-bound')
        for channel in ('stdout','stderr'): prefix.with_suffix('.'+channel+'.log').write_bytes(getattr(result, channel))
        row = {'label': label, 'returncode': result.returncode, 'elapsedSeconds': time.monotonic()-began,
            'stdout': {'bytes': len(result.stdout), 'sha256': digest(result.stdout)},
            'stderr': {'bytes': len(result.stderr), 'sha256': digest(result.stderr)}}
        write_json(prefix.with_suffix('.result.json'), row); record['commands'].append(row)
        require(result.returncode == 0, 'borrow-signed-command-failed:'+label)
        deadline.finish(); return result.stdout
    stage = 'source'
    try:
        commit = run('source-commit', 'git', 'rev-parse', 'HEAD').decode().strip()
        tree = run('source-tree', 'git', 'rev-parse', 'HEAD^{tree}').decode().strip()
        require(not run('source-clean', 'git', 'status', '--porcelain', '--untracked-files=normal').strip(),
                'borrow-signed-clean-committed-source-required')
        require(os.environ.get('GITHUB_SHA') == commit and os.environ.get('GITHUB_EVENT_NAME') == 'push'
                and os.environ.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric'
                and re.fullmatch(r'[1-9][0-9]{0,19}', os.environ.get('GITHUB_RUN_ID','')) is not None
                and os.environ.get('GITHUB_RUN_ATTEMPT') == '1'
                and os.environ.get('GITHUB_REF') == 'refs/heads/feat/typescript-borrow-release-probe-20261024'
                and os.environ.get('GITHUB_WORKFLOW_REF') == 'KirilsTurkins/latent-service-fabric/.github/workflows/typescript-borrow-signed.yml@refs/heads/feat/typescript-borrow-release-probe-20261024',
                'borrow-signed-fixed-workflow-origin')
        record.update(sourceCommit=commit, sourceTree=tree, workflowOrigin={name: os.environ[name]
            for name in ('GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_SHA','GITHUB_EVENT_NAME','GITHUB_REPOSITORY','GITHUB_REF','GITHUB_WORKFLOW_REF')})
        stage = 'actual-no-skip-source-controls'
        program = ("import unittest,json,sys;s=unittest.defaultTestLoader.loadTestsFromName('tools.tests.test_typescript_borrow_probe_profile');"
            "r=unittest.TextTestRunner(verbosity=2).run(s);print(json.dumps(dict(testsRun=r.testsRun,skipped=len(r.skipped),failures=len(r.failures),errors=len(r.errors))));sys.exit(0 if r.wasSuccessful() else 1)")
        controls = json.loads(run('source-controls',sys.executable,'-c',program))
        require(controls == {'testsRun':5,'skipped':0,'failures':0,'errors':0}
                and all(type(value) is int for value in controls.values()), 'borrow-signed-all-five-controls-no-skips')
        record['sourceControls'] = controls
        parser = tools/'node_modules/acorn/dist/acorn.mjs'
        require(parser.is_file() and not parser.is_symlink(), 'borrow-signed-pinned-carrier-parser-required')
        carrier_program = program.replace('tools.tests.test_typescript_borrow_probe_profile',
                                          'tools.tests.test_typescript_native_carrier_scheduling')
        carrier_controls = json.loads(run('native-carrier-source-controls', sys.executable, '-c', carrier_program,
            env={**environment, 'LSF_TYPESCRIPT_ACORN': str(parser)}))
        require(carrier_controls == {'testsRun':4,'skipped':0,'failures':0,'errors':0}
                and all(type(value) is int for value in carrier_controls.values()),
                'borrow-signed-all-four-carrier-controls-no-skips')
        record['nativeCarrierSourceControls'] = carrier_controls
        record['nativeCarrierParser'] = file_identity(parser)
        stage = 'actual-successful-normal-inputs'
        original_inputs = inputs.verify(material_directory, run)
        record['originalPrerequisites'] = original_inputs
        prepared = output/'prepared'; prepared.mkdir()
        source = create(prepared/'project', 'greeting', 'typescript-borrow-probe', runtime_profile=IMPORT_PROFILE)
        for name, maintained in profile.INPUTS.items():
            path = source/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(read_file(ROOT/maintained))
        profile.validate(profile.PROFILE, source, profile.WORLD, IMPORT_PROFILE, None)
        captured = {name: read_file(source/name, 256*1024) for name in profile.INPUTS}
        vendor = snapshot(source/'vendor')
        engine, splicer = material_directory/'engine', material_directory/'splicer'
        isolated = prepared  # The normal captured workspace owns both project and build.
        guest_deadline = time.monotonic()+900
        class CompilerCommands:
            def __init__(self): self.root, self.environment = source, environment
            def run(self, label, *arguments):
                remaining = guest_deadline-time.monotonic()
                require(remaining > 0,'borrow-signed-guest-compile-deadline')
                return run(label, *arguments, cwd=self.root, seconds=remaining)
        stage = 'one-normal-compiler-probe'
        compiler = Compiler(tools, CompilerCommands(),
            {name: read_file(ROOT/'sdk/typescript-guest/tools'/name) for name in ('package.json','package-lock.json')},
            isolated_workspace=isolated, runtime_profile=IMPORT_PROFILE,
            engine=engine/'engine.wasm', engine_receipt=engine/'engine-input.json',
            splicer=splicer/'splicer', splicer_receipt=splicer/'splicer-input.json')
        component, bindings = compiler.compile(source, profile.WORLD, prepared/'build', diagnostic_profile=profile.PROFILE)
        compiler.check_unchanged()
        require(captured == {name: read_file(source/name,256*1024) for name in profile.INPUTS}
                and vendor == snapshot(source/'vendor'), 'borrow-signed-original-capture-changed')
        retained_own = prepared/'engine-qualification'; retained_own.mkdir()
        (retained_own/inputs.RECEIPT).write_bytes(read_file(material_directory/inputs.RECEIPT,4*1024**2))
        # Harness consumes these same source bytes; compiler-generated files stay separate.
        for name in profile.INPUTS:
            path = prepared/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(captured[name])
        own = json.loads(read_file(material_directory/inputs.RECEIPT,4*1024**2))
        write_json(prepared/'compiler-inputs.json', compiler.before)
        observation = {'schemaVersion':'latent.typescript.borrow-probe-compile.v1',
            'status':'passed','profile':profile.PROFILE,'sourceUnchanged':True,
            'engineQualificationStatus':'passed','ownResultsDigest':digest(read_file(material_directory/inputs.RECEIPT,4*1024**2)),
            'engineSourceCommit':own['sourceCommit'],'engineInputDigest':own['engineProducts']['engine-input.json']['sha256'],
            'sourceDigest':digest(captured['src/main.ts']),'sourceInputs':json.loads(inventory(captured)),
            'rawComponentDigest':digest(read_file(component,32*1024**2)), 'rawComponent':file_identity(component,32*1024**2),
            'bindings':bindings,'runtimeMaterials':compiler.runtime_materials(),
            'compilerInputs':file_identity(prepared/'compiler-inputs.json',8*1024**2),'recipe':recipe,'sourceCommit':commit,'sourceTree':tree,
            'enginePrerequisiteScope':inputs.SCOPE,'canonicalSignedExecution':'not-yet-run'}
        write_json(prepared/'BORROW-COMPILE.json', observation)
        record['guestComponentBuildCount'] = 1; record['rawCompile'] = file_identity(prepared/'BORROW-COMPILE.json',16*1024**2)
        stage = 'one-owning-host-build'
        host_started = time.monotonic()
        run('host-build','cargo','test','--locked','-p','latent-wasmtime','--features','development-test-host',
            '--test',TARGET,'--no-run',seconds=1800)
        host_remaining = 1800 - (time.monotonic() - host_started)
        require(host_remaining > 0, 'borrow-signed-aggregate-host-build-deadline')
        controls = run('host-trap-observer-controls','cargo','test','--locked','-p','latent-wasmtime',
            '--features','development-test-host','--lib','development_trap_observer::tests::',
            '--','--nocapture','--test-threads=1',seconds=host_remaining)
        require(re.search(r'test result: ok\. 3 passed; 0 failed; 0 ignored;',controls.decode()) is not None,
                'borrow-signed-three-real-observer-controls')
        require(time.monotonic() - host_started < 1800, 'borrow-signed-aggregate-host-build-deadline')
        admission_remaining = 1800 - (time.monotonic() - host_started)
        require(admission_remaining > 0, 'borrow-signed-aggregate-host-build-deadline')
        admission_controls = run('host-admission-observer-controls', 'cargo', 'test', '--locked',
            '-p', 'latent-wasmtime', '--features', 'development-test-host', '--lib',
            'development_borrow_admission::tests::', '--', '--nocapture', '--test-threads=1',
            seconds=admission_remaining)
        require(re.search(r'test result: ok\. 2 passed; 0 failed; 0 ignored;', admission_controls.decode()) is not None,
                'borrow-signed-two-real-admission-controls')
        require(time.monotonic() - host_started < 1800, 'borrow-signed-aggregate-host-build-deadline')
        stage = 'six-signed-activations'
        signed_env = dict(environment,LSF_GUEST_SDK_LANGUAGE='typescript',LSF_TYPESCRIPT_BORROW_FIXTURE=str(prepared))
        raw = run('signed-borrow','cargo','test','--locked','-p','latent-wasmtime','--features','development-test-host',
            '--test',TARGET,TEST,'--','--ignored','--exact','--nocapture','--test-threads=1',env=signed_env,seconds=600)
        record['actualRows'] = records(raw)
        require(re.search(r'test result: ok\. 1 passed; 0 failed; 0 ignored;',raw.decode()) is not None,
                'borrow-signed-one-real-test-summary')
        stage = 'final-immutable-rechecks'
        compiler.check_unchanged()
        require(original_inputs == inputs.verify(material_directory,run)
                and captured == {name:read_file(source/name,256*1024) for name in profile.INPUTS}
                and vendor == snapshot(source/'vendor')
                and recipe == {name:file_identity(ROOT/name) for name in recipe}
                and run('final-commit','git','rev-parse','HEAD').decode().strip() == commit
                and run('final-tree','git','rev-parse','HEAD^{tree}').decode().strip() == tree
                and not run('final-clean','git','status','--porcelain','--untracked-files=normal').strip(),
                'borrow-signed-source-products-changed')
        record.update(status='passed',signedAndAdmitted=True)
        deadline.finish(); write_json(output/'BORROW-SIGNED.json',record); deadline.finish(); return record
    except BaseException as error:
        record.update(status='failed',stage=stage,errorCategory=type(error).__name__)
        (output/'BORROW-SIGNED.json').unlink(missing_ok=True)
        write_json(output/'FAILED.json',record); raise
