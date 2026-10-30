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
    'crates/latent-wasmtime/tests/typescript_import_borrow_release/node_net.rs',
    'sdk/typescript-guest/probes/node-net/main.ts',
    'sdk/typescript-guest/probes/node-net/world.wit',
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


def qualify(tools, material_directory, output, *, programme='borrow', prepared_native=None):
    if programme == 'node-net':
        return qualify_node_net(tools, material_directory, output, prepared_native)
    require(programme == 'borrow' and prepared_native is None, 'closed-signed-stream-programme')
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


NET_PREFIX = 'sdk/typescript-guest/probes/node-net/'
NET_WORLD = 'tenant-a:typescript-node-net/service@1.0.0'
NET_TEST = 'signed_normal_node_net_socket_uses_original_stream_owners_and_close_events'
NET_INPUTS = {'src/main.ts': NET_PREFIX+'main.ts', 'wit/world.wit': NET_PREFIX+'world.wit',
              'wit/deps/network/package.wit': 'wit/platform/network/package.wit'}
NET_LIMITS = {'cpuFuel':1_000_000_000,'memoryBytes':134217728,'wallTimeLimitMillis':120000,
    'logBytes':0,'outboundRequests':8,'childCalls':0,'effectCount':0,'blobReadBytes':0,
    'blobWriteBytes':0,'stateReadBytes':0,'stateWriteBytes':0}
NET_RUNTIME_LIMITS = {'tasks':32,'executors':2,'queuedWork':32,'waits':8,'timers':8,'results':8,'native':128}
NET_REFERENCE_PROFILE = 'node-net-reference-t32-q32-n128-v1'
NET_RUNTIME_CONFIGURATION = ('RuntimeLimits { tasks: 32, executors: 2, queued_work: 32, waits: 8, '
    'timers: 8, results: 8, native_owners: 128 }')
NET_CASES = (('node-net-echo',0),('node-net-sibling',1),('node-net-denied',2),
             ('node-net-destroy',3),('node-net-unclosed',4),('node-net-fresh',0),
             ('node-net-published-granted',5),('node-net-published-denied',6))
NET_RECIPE = tuple(dict.fromkeys((*RECIPE, *NET_INPUTS.values(),
    'tools/typescript_net_client_fixture.py', 'tools/typescript_application_dependencies.py',
    'tools/typescript_dependency_authoring.py', 'tools/application_dependencies.py',
    'tools/application_dependency_store.py', 'tools/typescript_registry_tls.py',
    NET_PREFIX+'application-native-lock.json',
    'crates/latent-wasmtime/tests/typescript_import_borrow_release/node_net.rs',
    'tools/java_phase_native_products.py', 'tools/tests/test_typescript_node_net.py',
    'tools/tests/fixtures/typescript_node_net_generated.json',
    'tools/guest_compatibility_outcomes.py', 'tools/dev_workflow/node_diagnostics.py')))


def node_net_project(directory):
    from tools.typescript_guest.project import validate
    source = create(directory, 'greeting', 'caller', runtime_profile=IMPORT_PROFILE)
    for name, maintained in NET_INPUTS.items():
        path = source/name; path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(read_file(ROOT/maintained))
    value = json.loads(read_file(source/'capsule-project.json'))
    value.update(tenant='tenant-a',service='caller',world=NET_WORLD,limits=dict(NET_LIMITS))
    (source/'capsule-project.json').write_bytes((json.dumps(value,indent=2)+'\n').encode())
    lock = json.loads(read_file(source/'sdk-lock.json'))
    lock['template'] = {'name':'typescript-node-net','sourceDigest':digest(read_file(source/'src/main.ts')),
                        'witDigest':digest(read_file(source/'wit/world.wit'))}
    (source/'sdk-lock.json').write_bytes((json.dumps(lock,indent=2)+'\n').encode())
    validate(snapshot(source)); verify_node_net_project(source)
    return source


def verify_node_net_project(source):
    from tools.typescript_guest.project import validate
    files = snapshot(source); project, _lock, _pins = validate(files)
    require(project['name']=='caller' and project['tenant']=='tenant-a' and project['service']=='caller'
            and project['world']==NET_WORLD and project['runtimeProfile']==IMPORT_PROFILE
            and json.dumps(project['limits'],sort_keys=True)==json.dumps(NET_LIMITS,sort_keys=True),
            'node-net-exact-normal-project')
    selected = {name for name in files if name.startswith(('src/','wit/'))}
    require(selected == set(NET_INPUTS) and all(files[name]==read_file(ROOT/path)
            for name,path in NET_INPUTS.items()), 'node-net-exact-ordinary-source')
    require('gate' not in files['wit/world.wit'].decode() and 'lsf:' not in files['src/main.ts'].decode(),
            'node-net-no-gate-or-private-application-import')
    return files


def node_net_records(raw):
    from tools.dev_workflow import node_diagnostics
    cases = []
    for line in raw.decode().splitlines():
        line = line.removeprefix('test '+NET_TEST+' ... ')
        if line.startswith('TYPESCRIPT_NODE_NET_CASE '):
            cases.append(json.loads(line.removeprefix('TYPESCRIPT_NODE_NET_CASE ')))
    require(len(cases)==8 and [(row.get('case'),row.get('mode')) for row in cases]==list(NET_CASES),
            'node-net-eight-exact-actual-cases')
    def owner_sample(value, held, count=None):
        if type(value) is not dict or type(value.get('stream')) is not dict or type(value.get('io')) is not dict:
            return False
        stream, io = value['stream'], value['io']
        expected = (2 if held else 0) if count is None else count
        if not all(type(stream.get(key)) is int and stream[key]==expected
                   for key in ('owners','connections','pendingOperations','retainedChunks')):
            return False
        if not all(type(value.get(key)) is int and value[key]==bound for key,bound in (
            ('poolConnections',expected),('liveStores',1 if held else 0),
            ('activeActivations',1 if held else 0),('queuedActivations',0))):
            return False
        if value.get('kernelRetirementQualified') is not False:
            return False
        if held:
            return (type(io.get('stagedBytes')) is int and io['stagedBytes']==32768*expected
                and type(io.get('buffers')) is int and io['buffers']==2*expected
                and all(type(io.get(key)) is int and io[key]>=expected for key in ('calls','streams')))
        return (type(value.get('liveInstances')) is int and value['liveInstances']==0
            and type(value.get('poolRunningRequests')) is int and value['poolRunningRequests']==0
            and all(type(io.get(key)) is int and io[key]==0 for key in (
                'calls','running','queued','stagedBytes','resultBytes','buffers','streams','metadataBytes')))

    def public_trap(value):
        if type(value) is not dict or set(value)!={'kind','code','phase','message'}:
            return False
        kind, code, phase = value['kind'], value['code'], value['phase']
        return (kind in ('runtime-error','unreachable-code') and node_diagnostics.valid_trap_kind(kind,code,phase)
            and phase in (None,'call-and-postreturn')
            and value['message']==('guest execution failed' if kind=='runtime-error' else 'guest trapped: unreachable-code'))

    # These are source-authenticated owning observations, not guest-provided authority.
    # Exact limits cannot be replaced by another profile, booleans, or extra fields.
    reference = cases[0].get('referenceProfile')
    require(type(reference) is dict and set(reference)=={
        'name','runtimeLimits','activationRuntimeProfile','runtimeLimitsConfiguration','preparation'}
        and reference.get('name')==NET_REFERENCE_PROFILE
        and reference.get('activationRuntimeProfile')=='activation-owned-v1'
        and reference.get('runtimeLimitsConfiguration')==NET_RUNTIME_CONFIGURATION
        and type(reference.get('runtimeLimits')) is dict
        and json.dumps(reference['runtimeLimits'],sort_keys=True,allow_nan=False)==json.dumps(NET_RUNTIME_LIMITS,sort_keys=True),
        'node-net-exact-declared-reference-profile')
    preparation = reference.get('preparation')
    require(type(preparation) is dict and set(preparation)=={'backend','release','publication','componentDigest',
        'engineConfigurationDigest','engineVersion','targetTriple','cpuFeatureSet'}
        and preparation.get('backend')=='wasmtime-component-phase-1'
        and preparation.get('engineVersion')=='48.0.7'
        and preparation.get('targetTriple')=='x86_64-unknown-linux-gnu'
        and preparation.get('cpuFeatureSet')=='host-baseline'
        and all(type(preparation.get(k)) is str and re.fullmatch(pattern,preparation[k]) is not None
                for k,pattern in (('engineConfigurationDigest',r'blake3:[0-9a-f]{64}'),
                    ('release',r'sha256:[0-9a-f]{64}'),('componentDigest',r'sha256:[0-9a-f]{64}'),
                    ('publication',r'publication:sha256:[0-9a-f]{64}')))
        and preparation['release']==preparation['componentDigest'],
        'node-net-original-preparation-identity')
    for index,row in enumerate(cases):
        require(json.dumps(row.get('referenceProfile'),sort_keys=True,allow_nan=False)
                ==json.dumps(reference,sort_keys=True,allow_nan=False), 'node-net-same-actual-profile')
        require(type(row.get('mode')) is int and row.get('index')==index and type(row['index']) is int
                and row.get('status')==('failed-with-unclosed-stream-owners' if row['mode']==4 else 'succeeded')
                and row.get('sameBackend') is True and row.get('kernelRetirementQualified') is False
                and row.get('grantFuel')==NET_LIMITS['cpuFuel'] and type(row['grantFuel']) is int
                and row.get('outboundCeiling')==8 and type(row['outboundCeiling']) is int
                and row.get('grantMemoryBytes')==NET_LIMITS['memoryBytes'] and type(row['grantMemoryBytes']) is int
                and row.get('grantWallTimeMillis')==NET_LIMITS['wallTimeLimitMillis'] and type(row['grantWallTimeMillis']) is int
                and row.get('publicErrorCode')==('guest-trap' if row['mode']==4 else 'none')
                and (public_trap(row.get('publicTrap')) if row['mode']==4 else row.get('publicTrap') is None)
                and row.get('originalFailureCause')==('unknown' if row['mode']==4 else 'not-applicable')
                and row.get('guardAttribution')==('source-only' if row['mode']==4 else 'not-applicable')
                and row.get('recordedAdmissionRefusal') is False and owner_sample(row.get('postRoot'),False)
                and (row.get('outboundRequests')==(1 if row['mode']==5 else 0) if row['mode'] in (5,6) else True)
                and (owner_sample(row.get('heldOwnerBeforePermit'),True) if row['mode'] in (1,3,4)
                     else row.get('heldOwnerBeforePermit') is None)
                and (owner_sample(row.get('acceptedCloseBeforeEOF'),True,1) if row['mode']==5
                     else row.get('acceptedCloseBeforeEOF') is None)
                and row.get('controlPeerEOF') is (row['mode'] in (1,3,4))
                and row.get('primaryReleasedAfterObservation') is (row['mode']==4)
                and all(type(row.get(key)) is int and 0<=row[key]<=bound for key,bound in (
                    ('outboundRequests',8),('cpuFuel',NET_LIMITS['cpuFuel']),('peakMemoryBytes',NET_LIMITS['memoryBytes']))),
                'node-net-actual-case-budgets-or-attribution')
    complete = [json.loads(line.removeprefix('TYPESCRIPT_NODE_NET_COMPLETE '))
        for line in raw.decode().splitlines() if line.startswith('TYPESCRIPT_NODE_NET_COMPLETE ')]
    expected_complete=[{'cases':8,'guestComponents':1,'gateComponent':False,'wholeAC7':False,
        'wholeCostQualification':False,'productionEnablement':False,'referenceProfile':reference}]
    require(json.dumps(complete,sort_keys=True,allow_nan=False)==json.dumps(expected_complete,sort_keys=True,allow_nan=False),
            'node-net-actual-complete')
    require('test result: ok. 1 passed; 0 failed; 0 ignored;' in raw.decode(), 'node-net-one-actual-test')
    return cases


def qualify_node_net(tools, material_directory, output, prepared_native):
    """The existing owner, one normal build, one exact test in its SAME target."""
    from tools import java_phase_native_products as host
    from tools.typescript_guest import net_profile
    from tools import typescript_net_client_fixture as client
    from tools.typescript_guest.build import build
    from tools import guest_compatibility_context as context, guest_compatibility_outcomes as outcomes
    require(sys.platform=='linux' and platform.machine() in ('x86_64','AMD64')
            and sys.version_info[:3]==(3,13,5), 'node-net-pinned-host')
    require(prepared_native is not None, 'node-net-fixed-native-gate-required')
    tools, material_directory, prepared_native = [Path(p).resolve(strict=True)
        for p in (tools,material_directory,prepared_native)]
    output=Path(output).resolve()
    require(output!=ROOT and ROOT not in output.parents and output not in ROOT.parents
            and all(output!=p and output not in p.parents and p not in output.parents
                    for p in (tools,material_directory,prepared_native)), 'node-net-separated-output')
    output=fresh(output); deadline=Deadline()
    environment=build_environment(output)
    environment.update(CARGO_BUILD_JOBS='2',CARGO_INCREMENTAL='0',RUSTUP_TOOLCHAIN='1.97.1',
        CARGO_HOME=str(output/'cargo-home'),CARGO_TARGET_DIR=str(output/'cargo-target'),
        CARGO_PROFILE_DEV_DEBUG='0',CARGO_PROFILE_TEST_DEBUG='0')
    recipe={name:file_identity(ROOT/name) for name in NET_RECIPE}
    record={'schemaVersion':'latent.typescript.node-net-signed.v1','status':'in-progress','recipe':recipe,
        'declaredReferenceProfile':{'name':NET_REFERENCE_PROFILE,'runtimeLimits':NET_RUNTIME_LIMITS},
        'engineBuildCount':0,'libraryBuildCount':0,'guestComponentBuildCount':0,'gateComponent':False,
        'wholeAC7':False,'wholeCostQualification':False,'productionEnablement':False,'commands':[]}
    commands=output/'commands';commands.mkdir(); retained=0
    def run(label,*args,cwd=ROOT,env=None,seconds=60):
        nonlocal retained
        require(re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',label) is not None,'node-net-command-label')
        maximum=deadline.remaining(seconds); before=time.monotonic(); argv=list(map(str,args))
        prefix=commands/f'{len(record["commands"]):03d}-{label}'
        write_json(prefix.with_suffix('.command.json'),{'argv':argv,'maximumSeconds':maximum})
        result=run_bounded_result(argv,cwd,env or environment,timeout_seconds=maximum,max_output_bytes=4*1024**2)
        retained+=len(result.stdout)+len(result.stderr);require(retained<=32*1024**2,'node-net-raw-log-bound')
        for channel in ('stdout','stderr'):prefix.with_suffix('.'+channel+'.log').write_bytes(getattr(result,channel))
        row={'label':label,'returncode':result.returncode,'elapsedSeconds':time.monotonic()-before,
            **{channel:{'bytes':len(getattr(result,channel)),'sha256':digest(getattr(result,channel))}
               for channel in ('stdout','stderr')}}
        write_json(prefix.with_suffix('.result.json'),row);record['commands'].append(row)
        require(result.returncode==0,'node-net-command-failed:'+label);deadline.finish();return result.stdout
    stage='source'
    try:
        commit=run('source-commit','git','rev-parse','HEAD').decode().strip()
        tree=run('source-tree','git','rev-parse','HEAD^{tree}').decode().strip()
        require(not run('source-clean','git','status','--porcelain','--untracked-files=normal').strip(), 'node-net-clean-source')
        branch='refs/heads/feat/typescript-accepted-close-20261025'
        require(os.environ.get('GITHUB_SHA')==commit and os.environ.get('GITHUB_EVENT_NAME')=='push'
            and os.environ.get('GITHUB_REPOSITORY')=='KirilsTurkins/latent-service-fabric'
            and re.fullmatch(r'[1-9][0-9]{0,19}',os.environ.get('GITHUB_RUN_ID','')) is not None
            and os.environ.get('GITHUB_RUN_ATTEMPT')=='1' and os.environ.get('GITHUB_REF')==branch
            and os.environ.get('GITHUB_WORKFLOW_REF')=='KirilsTurkins/latent-service-fabric/.github/workflows/typescript-borrow-signed.yml@'+branch,
            'node-net-fixed-owning-origin')
        record.update(sourceCommit=commit,sourceTree=tree,workflowOrigin={k:os.environ[k] for k in (
            'GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_SHA','GITHUB_EVENT_NAME','GITHUB_REPOSITORY','GITHUB_REF','GITHUB_WORKFLOW_REF')})
        stage='normal-input-gates'
        original_inputs=inputs.verify(material_directory,run);original_native=host.verify_prepared(prepared_native)
        binaries=host.native_products(prepared_native)
        require(set(binaries)=={'latent','latentd','capsule_contracts','package','capsule_authoring'},'node-net-original-five-products')
        record.update(originalPrerequisites=original_inputs,originalNativeCLI=original_native)
        prepared=output/'prepared';prepared.mkdir();source=node_net_project(prepared/'project')
        stage='normal-published-client-capture'
        dependency=client.capture(source)
        record['publishedClient']=dependency
        source_before=inventory(snapshot(source))
        stage='no-skip-pinned-source-controls'
        parser=tools/'node_modules/acorn/dist/acorn.mjs';require(parser.is_file() and not parser.is_symlink(),'node-net-pinned-parser')
        program="import unittest,json,sys;s=unittest.defaultTestLoader.loadTestsFromName('tools.tests.test_typescript_node_net');r=unittest.TextTestRunner(verbosity=2).run(s);print(json.dumps(dict(testsRun=r.testsRun,skipped=len(r.skipped),failures=len(r.failures),errors=len(r.errors))));sys.exit(0 if r.wasSuccessful() else 1)"
        controls=json.loads(run('normal-source-controls',sys.executable,'-c',program,
            env={**environment,'LSF_TYPESCRIPT_FRONTEND':str(tools)},seconds=60))
        require(controls=={'testsRun':30,'skipped':0,'failures':0,'errors':0}
                and all(type(v) is int for v in controls.values()),'node-net-all-thirty-no-skips')
        record['sourceControls']=controls
        stage='one-normal-build-and-package'
        artifact=build(source,prepared/'typescript-node-net-service',binaries['capsule_contracts'],binaries['package'],
            'https://github.com/KirilsTurkins/latent-service-fabric',tools=tools,
            runtime_engine=material_directory/'engine/engine.wasm',runtime_engine_receipt=material_directory/'engine/engine-input.json',
            runtime_splicer=material_directory/'splicer/splicer',runtime_splicer_receipt=material_directory/'splicer/splicer-input.json')
        record['guestComponentBuildCount']=1
        record['publishedClientBuild']=client.build_evidence(artifact,dependency)
        selection_raw=read_file(artifact/'typescript-net-selection.json',65536)
        observed=json.loads(read_file(artifact/'build-observation.json',65536))
        require([row for row in observed['materials'] if row['name']=='typescript-standard-net']==[
            {'name':'typescript-standard-net','digest':digest(selection_raw),'size':len(selection_raw)}],'node-net-normal-observed-material')
        package_source=json.loads(read_file(artifact/'package-source.json',65536))
        require([row for row in package_source['layers'] if row['source']=='typescript-net-selection.json']==[
            {'path':'typescript-net-selection.json','source':'typescript-net-selection.json','role':'asset',
             'mediaType':'application/vnd.latent.typescript.net-selection.v1+json'}],'node-net-normal-asset')
        selected_context=context.read(read_file(artifact/'compatibility-context.json',65536))
        require(context.net_module(selected_context) is not None and selected_context['qualification']=='unknown','node-net-bound-unknown-context')
        receipt={'source':digest(read_file(ROOT/'tools/qualify_typescript_borrow_signed.py')),'artifacts':{'component':digest(read_file(artifact/'component.wasm',64*1024**2))}}
        require(outcomes.from_build(artifact,{'artifacts':{'component':'component.wasm'}},receipt).context_state=='observed',
                'node-net-normal-outcome-sidecar-reader')
        completed=json.loads(read_file(artifact/'BUILD-COMPLETE.json',65536))
        require(all(len([row for row in completed['commands'] if row['stage']==name and row['exitCode']==0])==1
            for name in ('typecheck','bundle','componentize')),'node-net-one-real-compiler-path')
        graph=json.loads(read_file(artifact/'bindings.json',8*1024**2))
        require('tests:typescript-import-borrow-gate' not in json.dumps(graph)
                and 'tests:typescript-import-borrow-gate' not in read_file(artifact/'surface.json',1024**2).decode(),
                'node-net-no-gate-product')
        record.update(normalBuild=file_identity(artifact/'BUILD-COMPLETE.json'),selection=file_identity(artifact/'typescript-net-selection.json'),
            component=file_identity(artifact/'component.wasm',64*1024**2))
        stage='one-existing-host-target'
        host_started=time.monotonic()
        run('host-build','cargo','test','--locked','-p','latent-wasmtime','--features','development-test-host','--test',TARGET,'--no-run',seconds=1800)
        remaining=1800-(time.monotonic()-host_started);require(remaining>0,'node-net-host-aggregate')
        raw=run('host-new-closed-case-control','cargo','test','--locked','-p','latent-wasmtime','--features','development-test-host','--lib',
            'development_borrow_admission::tests::normal_socket_cases_keep_distinct_closed_indices_and_original_opt_in','--','--exact','--nocapture',seconds=remaining)
        require('test result: ok. 1 passed; 0 failed; 0 ignored;' in raw.decode(),'node-net-actual-one-new-host-control')
        stage='eight-normal-signed-activations'
        raw=run('signed-node-net','cargo','test','--locked','-p','latent-wasmtime','--features','development-test-host','--test',TARGET,NET_TEST,
            '--','--ignored','--exact','--nocapture','--test-threads=1',seconds=600,
            env={**environment,'LSF_GUEST_SDK_LANGUAGE':'typescript','LSF_TYPESCRIPT_BORROW_FIXTURE':str(prepared),'LSF_GUEST_CAPSULES':str(prepared)})
        record['actualCases']=node_net_records(raw)
        record['referenceProfile']=record['actualCases'][0]['referenceProfile']
        require(record['referenceProfile']['preparation']['componentDigest']==record['component']['sha256'],
                'node-net-prepared-component-matches-normal-build')
        stage='final-original-rechecks'
        require(source_before==inventory(verify_node_net_project(source)) and dependency==client.provenance(source)
            and recipe=={n:file_identity(ROOT/n) for n in recipe}
            and original_inputs==inputs.verify(material_directory,run) and original_native==host.verify_prepared(prepared_native)
            and run('final-commit','git','rev-parse','HEAD').decode().strip()==commit
            and run('final-tree','git','rev-parse','HEAD^{tree}').decode().strip()==tree
            and not run('final-clean','git','status','--porcelain','--untracked-files=normal').strip(),'node-net-original-inputs-changed')
        deadline.finish();record.update(status='passed',signedAndAdmitted=True)
        write_json(output/'NODE-NET-SIGNED.json',record);deadline.finish();return record
    except BaseException as error:
        record.update(status='failed',stage=stage,errorCategory=type(error).__name__)
        (output/'NODE-NET-SIGNED.json').unlink(missing_ok=True);write_json(output/'FAILED.json',record);raise
