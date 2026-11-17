"""Same-run, source-bound signed borrow probe; no historical receipt is rewritten."""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import sys
import time

from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, snapshot, write_json
from tools.typescript_guest import activation_engine, borrow_probe_profile as profile, native_build, runtime_profile
from tools.typescript_guest.borrow_signed_controls import Deadline, RECIPE as HISTORICAL_RECIPE, TARGET, TEST, records
from tools.typescript_guest.compiler import Compiler
from tools.typescript_guest.project import create

RECIPE = tuple(dict.fromkeys((*HISTORICAL_RECIPE,
    'tools/qualify_typescript_borrow_current.py',
    'tools/typescript_guest/borrow_current_controls.py',
    'tools/tests/test_typescript_borrow_current.py',
    'crates/latent-wasmtime/tests/typescript_import_borrow_release/current_source.rs',
    '.github/workflows/typescript-guest.yml')))
ENGINE_FILES = ('engine.wasm', 'engine-input.json', 'engine-build.json',
                'engine-compilation.json', 'source-derivation.json')
SCOPE = 'same-workflow-source-bound-import-engine'


def require_source_controls(value):
    require(type(value) is dict and set(value) == {'testsRun', 'skipped', 'failures', 'errors'}
            and all(type(item) is int for item in value.values())
            and value['testsRun'] >= 15 and value['skipped'] == value['failures'] == value['errors'] == 0,
            'borrow-current-source-controls-no-skips')


def workflow_origin(environment, commit):
    names = ('GITHUB_REPOSITORY', 'GITHUB_WORKFLOW_REF', 'GITHUB_WORKFLOW_SHA',
             'GITHUB_EVENT_NAME', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_SHA', 'GITHUB_REF')
    values = {name: environment.get(name) for name in names}
    require(re.fullmatch(r'[0-9a-f]{40}', commit) is not None
            and values['GITHUB_REPOSITORY'] == 'KirilsTurkins/latent-service-fabric'
            and values['GITHUB_EVENT_NAME'] == 'workflow_dispatch'
            and values['GITHUB_REF'] == 'refs/heads/development'
            and values['GITHUB_SHA'] == commit and values['GITHUB_WORKFLOW_SHA'] == commit
            and values['GITHUB_RUN_ATTEMPT'] == '1'
            and re.fullmatch(r'[1-9][0-9]{0,19}', values['GITHUB_RUN_ID'] or '') is not None
            and values['GITHUB_WORKFLOW_REF'] ==
                'KirilsTurkins/latent-service-fabric/.github/workflows/typescript-guest.yml@refs/heads/development',
            'borrow-current-exact-development-workflow-origin')
    return values


def source_products(engine, splicer):
    """Validate original build outputs against current source and each other."""
    identities = {name: file_identity(engine/name, 64*1024**2) for name in ENGINE_FILES}
    splicer_identity = native_build.source_splicer(splicer)
    core = read_file(engine/'engine.wasm', 64*1024**2)
    envelope = json.loads(read_file(engine/'engine-input.json', 65536))
    sdk = {name: read_file(ROOT/name) for name in activation_engine.engine_input_paths(runtime_profile.IMPORT_PROFILE)}
    runtime_profile.validate_engine(envelope, core, sdk,
        read_file(ROOT/'wit/platform/activation-runtime/package.wit'), profile=runtime_profile.IMPORT_PROFILE)
    build = json.loads(read_file(engine/'engine-build.json', 4*1024**2))
    compilation = json.loads(read_file(engine/'engine-compilation.json', 4*1024**2))
    expected_compilation = dict(build)
    expected_compilation.pop('input', None)
    expected_compilation['status'] = 'core-compiled'
    recipe = ('tools/build_typescript_native_engine.py', 'tools/typescript_guest/native_build.py',
              *activation_engine.engine_input_paths(runtime_profile.IMPORT_PROFILE))
    require(core.startswith(b'\0asm\x01\0\0\0')
            and build.get('schemaVersion') == 'latent.typescript.native-engine-source-build.v1'
            and build.get('status') == 'passed' and build.get('scope') == 'normal-cmake-engine-compile-only'
            and build.get('qualification') == 'unknown' and build.get('apiSupport') == 'not-evaluated'
            and build.get('signedExecution') == 'not-run'
            and build.get('recipe') == {name: file_identity(ROOT/name) for name in recipe}
            and build.get('engine') == identities['engine.wasm']
            and build.get('input') == identities['engine-input.json']
            and compilation == expected_compilation
            and build.get('sourceSplicer') == splicer_identity
            and envelope['compilerSplicerInputDigest'] == splicer_identity['inputDigest']
            and envelope['buildReceiptDigest'] == identities['engine-compilation.json']['sha256']
            and envelope['sourceDerivationDigest'] == identities['source-derivation.json']['sha256'],
            'borrow-current-original-engine-splicer-and-recipe')
    return {'engineProducts': identities, 'splicer': splicer_identity}


def qualify(tools, engine, splicer, output):
    require(sys.platform == 'linux' and platform.machine() in ('x86_64', 'AMD64')
            and sys.version_info[:3] == (3, 13, 5), 'borrow-current-linux-pinned-python')
    tools, engine, splicer = (path.resolve(strict=True) for path in (tools, engine, splicer))
    output = output.resolve()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents
            and all(output != path and output not in path.parents and path not in output.parents
                    for path in (tools, engine, splicer)), 'borrow-current-separated-output')
    output = fresh(output)
    deadline = Deadline()
    environment = build_environment(output)
    environment.update(CARGO_BUILD_JOBS='2', CARGO_INCREMENTAL='0', RUSTUP_TOOLCHAIN='1.97.1',
        CARGO_HOME=str(output/'cargo-home'), CARGO_TARGET_DIR=str(output/'cargo-target'),
        CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0')
    recipe = {name: file_identity(ROOT/name) for name in RECIPE}
    record = {'schemaVersion': 'latent.typescript.borrow-current-signed.v1', 'status': 'in-progress',
        'scope': 'signed-canonical-borrow-release-logical-reference',
        'enginePrerequisiteScope': SCOPE, 'engineQualification': 'unknown',
        'kernelRetirementQualified': False, 'wholeCostQualification': False,
        'productionEnablement': False, 'taskSettlementRefusalQualified': False,
        'guestComponentBuildCount': 0, 'recipe': recipe, 'commands': []}
    commands = output/'commands'
    commands.mkdir()
    retained = 0

    def run(label, *arguments, cwd=ROOT, env=None, seconds=60):
        nonlocal retained
        require(re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', label) is not None
                and len(record['commands']) < 128, 'borrow-current-command-bound')
        prefix = commands/f"{len(record['commands']):03d}-{label}"
        maximum = deadline.remaining(seconds)
        argv = list(map(str, arguments))
        write_json(prefix.with_suffix('.command.json'), {'argv': argv, 'maximumSeconds': maximum})
        began = time.monotonic()
        result = run_bounded_result(argv, cwd, env or environment, timeout_seconds=maximum, max_output_bytes=4*1024**2)
        retained += len(result.stdout) + len(result.stderr)
        require(retained <= 32*1024**2, 'borrow-current-total-diagnostic-bound')
        for channel in ('stdout', 'stderr'):
            prefix.with_suffix('.'+channel+'.log').write_bytes(getattr(result, channel))
        row = {'label': label, 'returncode': result.returncode, 'elapsedSeconds': time.monotonic()-began,
            'stdout': {'bytes': len(result.stdout), 'sha256': digest(result.stdout)},
            'stderr': {'bytes': len(result.stderr), 'sha256': digest(result.stderr)}}
        write_json(prefix.with_suffix('.result.json'), row)
        record['commands'].append(row)
        require(result.returncode == 0, 'borrow-current-command-failed:'+label)
        deadline.finish()
        return result.stdout

    stage = 'source'
    try:
        commit = run('source-commit', 'git', 'rev-parse', 'HEAD').decode().strip()
        tree = run('source-tree', 'git', 'rev-parse', 'HEAD^{tree}').decode().strip()
        require(re.fullmatch(r'[0-9a-f]{40}', tree) is not None
                and not run('source-clean', 'git', 'status', '--porcelain', '--untracked-files=normal').strip(),
                'borrow-current-clean-committed-source')
        origin = workflow_origin(os.environ, commit)
        record.update(sourceCommit=commit, sourceTree=tree, workflowOrigin=origin)
        stage = 'source-controls'
        program = ("import unittest,json,sys;"
            "s=unittest.defaultTestLoader.loadTestsFromNames(["
            "'tools.tests.test_typescript_borrow_current',"
            "'tools.tests.test_typescript_borrow_signed_inputs',"
            "'tools.tests.test_typescript_borrow_probe_profile']);"
            "r=unittest.TextTestRunner(verbosity=2).run(s);"
            "print(json.dumps(dict(testsRun=r.testsRun,skipped=len(r.skipped),"
            "failures=len(r.failures),errors=len(r.errors))));"
            "sys.exit(0 if r.wasSuccessful() else 1)")
        controls = json.loads(run('source-controls', sys.executable, '-c', program))
        require_source_controls(controls)
        record['sourceControls'] = controls
        stage = 'source-bound-engine-and-splicer'
        products = source_products(engine, splicer)
        proof = {'schemaVersion': 'latent.typescript.borrow-current-engine.v1', 'status': 'source-built',
            'scope': SCOPE, 'qualification': 'unknown', 'apiSupport': 'not-evaluated',
            'sourceCommit': commit, 'sourceTree': tree, 'workflowOrigin': origin, **products}
        prepared = output/'prepared'
        prepared.mkdir()
        qualification = prepared/'engine-qualification'
        qualification.mkdir()
        for name in ENGINE_FILES[1:]:
            (qualification/name).write_bytes(read_file(engine/name, 4*1024**2))
        (qualification/'splicer-input.json').write_bytes(read_file(splicer/'splicer-input.json', 65536))
        write_json(qualification/'CURRENT-ENGINE.json', proof)
        stage = 'one-normal-compiler-probe'
        source = create(prepared/'project', 'greeting', 'typescript-borrow-probe',
                        runtime_profile=runtime_profile.IMPORT_PROFILE)
        for name, maintained in profile.INPUTS.items():
            path = source/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(read_file(ROOT/maintained))
        profile.validate(profile.PROFILE, source, profile.WORLD, runtime_profile.IMPORT_PROFILE, None)
        captured = {name: read_file(source/name, 256*1024) for name in profile.INPUTS}
        vendor = snapshot(source/'vendor')
        guest_deadline = time.monotonic()+900

        class CompilerCommands:
            def __init__(self):
                self.root, self.environment = source, environment
            def run(self, label, *arguments):
                remaining = guest_deadline-time.monotonic()
                require(remaining > 0, 'borrow-current-guest-compile-deadline')
                return run(label, *arguments, cwd=self.root, seconds=remaining)

        compiler = Compiler(tools, CompilerCommands(),
            {name: read_file(ROOT/'sdk/typescript-guest/tools'/name) for name in ('package.json', 'package-lock.json')},
            isolated_workspace=prepared, runtime_profile=runtime_profile.IMPORT_PROFILE,
            engine=engine/'engine.wasm', engine_receipt=engine/'engine-input.json',
            splicer=splicer/'splicer', splicer_receipt=splicer/'splicer-input.json')
        component, bindings = compiler.compile(source, profile.WORLD, prepared/'build', diagnostic_profile=profile.PROFILE)
        compiler.check_unchanged()
        require(captured == {name: read_file(source/name, 256*1024) for name in profile.INPUTS}
                and vendor == snapshot(source/'vendor'), 'borrow-current-captured-source-changed')
        for name in profile.INPUTS:
            path = prepared/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(captured[name])
        write_json(prepared/'compiler-inputs.json', compiler.before)
        observation = {'schemaVersion': 'latent.typescript.borrow-probe-compile.v2',
            'status': 'passed', 'profile': profile.PROFILE, 'sourceUnchanged': True,
            'engineQualificationStatus': 'unknown', 'engineEvidenceDigest': digest(read_file(qualification/'CURRENT-ENGINE.json')),
            'engineSourceCommit': commit, 'engineInputDigest': products['engineProducts']['engine-input.json']['sha256'],
            'sourceDigest': digest(captured['src/main.ts']), 'sourceInputs': json.loads(inventory(captured)),
            'rawComponentDigest': digest(read_file(component, 32*1024**2)),
            'rawComponent': file_identity(component, 32*1024**2), 'bindings': bindings,
            'runtimeMaterials': compiler.runtime_materials(),
            'compilerInputs': file_identity(prepared/'compiler-inputs.json', 8*1024**2),
            'recipe': recipe, 'sourceCommit': commit, 'sourceTree': tree,
            'enginePrerequisiteScope': SCOPE, 'canonicalSignedExecution': 'not-yet-run'}
        write_json(prepared/'BORROW-COMPILE.json', observation)
        record['guestComponentBuildCount'] = 1
        stage = 'one-owning-host-build'
        run('host-build', 'cargo', 'test', '--locked', '-p', 'latent-wasmtime',
            '--features', 'development-test-host', '--test', TARGET, '--no-run', seconds=1800)
        stage = 'six-signed-activations'
        signed_env = dict(environment, LSF_GUEST_SDK_LANGUAGE='typescript',
                          LSF_TYPESCRIPT_BORROW_FIXTURE=str(prepared),
                          GITHUB_SHA=commit, GITHUB_RUN_ID=origin['GITHUB_RUN_ID'])
        raw = run('signed-borrow', 'cargo', 'test', '--locked', '-p', 'latent-wasmtime',
            '--features', 'development-test-host', '--test', TARGET, TEST,
            '--', '--ignored', '--exact', '--nocapture', '--test-threads=1', env=signed_env, seconds=600)
        record['actualRows'] = records(raw)
        require(re.search(r'test result: ok\. 1 passed; 0 failed; 0 ignored;', raw.decode()) is not None,
                'borrow-current-one-real-test-summary')
        stage = 'final-immutable-rechecks'
        compiler.check_unchanged()
        require(products == source_products(engine, splicer)
                and captured == {name: read_file(source/name, 256*1024) for name in profile.INPUTS}
                and vendor == snapshot(source/'vendor')
                and recipe == {name: file_identity(ROOT/name) for name in recipe}
                and run('final-commit', 'git', 'rev-parse', 'HEAD').decode().strip() == commit
                and run('final-tree', 'git', 'rev-parse', 'HEAD^{tree}').decode().strip() == tree
                and not run('final-clean', 'git', 'status', '--porcelain', '--untracked-files=normal').strip(),
                'borrow-current-source-products-changed')
        record.update(status='passed', signedAndAdmitted=True)
        deadline.finish()
        write_json(output/'BORROW-SIGNED-CURRENT.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__)
        (output/'BORROW-SIGNED-CURRENT.json').unlink(missing_ok=True)
        write_json(output/'FAILED.json', record)
        raise
