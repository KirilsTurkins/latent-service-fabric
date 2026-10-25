#!/usr/bin/env python3
"""One normal four-call global Buffer programme; public artifacts are closed."""
from __future__ import annotations
import argparse
import base64
from contextlib import ExitStack
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import sys
import tempfile
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import java_phase_native_products as host, typescript_buffer_globals_fixture as fixture
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.guest_compatibility_context import BUFFER_GLOBAL_MATERIALS, buffer_module
from tools import guest_compatibility_context as context, guest_compatibility_outcomes as outcomes
from tools.native_runtime import files as install_files
from tools.phase2_operator_process import require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.qualify_typescript_buffer import configuration, grants, SERVICE
from tools.qualify_typescript_fetch_runtime import build_evidence as runtime_build_evidence, require_result, retire
from tools.rust_capsule_node import RecordingClient, call, delete_all, deploy, sample, selected_revision
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, write_json
from tools.typescript_guest import buffer_profile, borrow_signed_inputs as inputs
from tools.typescript_guest.build import RECIPE as COMPILER_RECIPE

BRANCH = 'feat/typescript-global-buffer-20261025'
BUILD_PUBLIC = ('BUILD-COMPLETE.json', 'BUILD-FAILED.json', 'build-observation.json', 'source-inputs.json',
    'recipe-inputs.json', 'package-inputs.json', 'package-source.json', 'bindings.json',
    'compiler-containment.json', 'typescript-runtime-selection.json',
    'standard-runtime-selection.json', 'typescript-buffer-selection.json',
    'compatibility-report.json', 'compatibility-context.json', 'component.wasm',
    'application.mjs', 'generated-bindings.js')
PUBLIC_FILES = ('RESULT.json', 'FAILED.json', 'COMMANDS.json', 'INPUTS.json', 'PROJECT-SOURCE.json',
    'BUILD-LOGS.json', 'PUBLIC-MANIFEST.json',
    'INVOCATIONS.json', 'RETIREMENTS.json', 'STARTUP.json', 'SHUTDOWN.json',
    'source-controls.stdout.txt', 'source-controls.stderr.txt',
    'normal-build.stdout.txt', 'normal-build.stderr.txt',
    *(name for name in BUILD_PUBLIC),
    *(f'probe-{name}' for name in (*fixture.SOURCES, 'world.wit')))
RECIPE = tuple(dict.fromkeys((*COMPILER_RECIPE, 'tools/qualify_typescript_buffer_globals.py',
    'tools/typescript_buffer_globals_fixture.py', 'tools/typescript_guest/borrow_signed_inputs.py',
    'tools/java_phase_native_products.py', 'tools/qualify_typescript_buffer.py',
    'tools/qualify_typescript_fetch_runtime.py', 'tools/rust_capsule_node.py',
    'tools/typescript_standard_clock_probe.py', 'tools/native_runtime/files.py',
    'tools/tests/test_typescript_buffer_globals.py', 'tools/tests/test_typescript_buffer_globals_qualification.py',
    '.github/workflows/typescript-buffer-globals.yml',
    *(fixture.FIXTURE+'/'+name for name in (*fixture.SOURCES, 'world.wit')))))


class Deadline:
    def __init__(self):
        raw = os.environ.get('LSF_BUFFER_GLOBAL_STARTED_NS', '')
        require(re.fullmatch(r'[1-9][0-9]{0,19}', raw) is not None, 'buffer-globals-setup-clock')
        elapsed = (time.time_ns() - int(raw)) / 1e9
        require(0 <= elapsed < 1200, 'buffer-globals-aggregate-setup')
        self.end = time.monotonic() + 1200 - elapsed

    def remaining(self, maximum):
        # Keep the original bounded process/node cleanup outside the work slice.
        value = min(maximum, self.end - time.monotonic() - 10)
        require(value > 0, 'buffer-globals-aggregate-deadline')
        return value

    def check(self):
        require(time.monotonic() < self.end, 'buffer-globals-final-deadline')


class Public:
    """Only these fixed public names, never private/signing/work recursion."""
    def __init__(self, directory):
        self.root = fresh(directory)
        self.total = 0

    def put(self, name, raw):
        require(name in PUBLIC_FILES and type(raw) is bytes, 'buffer-globals-public-file')
        require(not (self.root/name).exists(), 'buffer-globals-public-file-duplicate')
        self.total += len(raw)
        require(len(raw) <= 64*1024**2 and self.total <= 64*1024**2, 'buffer-globals-public-byte-bound')
        with (self.root/name).open('xb') as stream:
            stream.write(raw)

    def json(self, name, value):
        self.put(name, (json.dumps(value, sort_keys=True, indent=2)+'\n').encode())

    def finish(self):
        rows = {}
        for path in self.root.iterdir():
            require(path.name in PUBLIC_FILES and not path.is_symlink() and path.is_file(),
                'buffer-globals-unexpected-public-file')
            rows[path.name] = file_identity(path, 64*1024**2)
        self.json('PUBLIC-MANIFEST.json', rows)


def collect_build(artifact, public):
    """Only normal unsigned compiler outputs; never signing/node work."""
    logs, total = [], 0
    folder = artifact/'logs'
    if folder.is_dir():
        require(not folder.is_symlink(), 'buffer-globals-build-log-directory')
        for path in sorted(folder.iterdir()):
            require(len(logs) < 128 and re.fullmatch(r'[0-9]{2}-[a-zA-Z0-9_-]{1,80}\.(stdout|stderr)\.txt',path.name),
                'buffer-globals-build-log-name-count')
            raw = read_file(path, 4*1024**2)
            total += len(raw);require(total <= 16*1024**2,'buffer-globals-build-log-byte-bound')
            logs.append({'name':path.name,'bytes':len(raw),'sha256':digest(raw),
                'base64':base64.b64encode(raw).decode('ascii')})
    public.json('BUILD-LOGS.json', logs)
    for name in BUILD_PUBLIC:
        if (artifact/name).is_file():public.put(name,read_file(artifact/name,64*1024**2))


def build_evidence(artifact):
    value = runtime_build_evidence(artifact)
    selected_raw = read_file(artifact/'typescript-buffer-selection.json', 65536)
    selected = buffer_profile.validate_selection(json.loads(selected_raw),
        digest(read_file(ROOT/buffer_profile.BACKEND)), buffer_profile.global_identities(ROOT))
    require(selected['globalBufferInstalled'] is True
        and selected['schemaVersion'] == 'latent.typescript.standard-buffer-selection.v2',
        'buffer-globals-actual-global-selection')
    observation = read_json(artifact/'build-observation.json')
    require([row for row in observation['materials'] if row['name'] == 'typescript-standard-buffer'] == [
        {'name':'typescript-standard-buffer','digest':digest(selected_raw),'size':len(selected_raw)}],
        'buffer-globals-selection-build-material')
    package = read_json(artifact/'package-source.json')
    require([row for row in package['layers'] if row['source'] == 'typescript-buffer-selection.json'] == [{
        'path':'typescript-buffer-selection.json','source':'typescript-buffer-selection.json','role':'asset',
        'mediaType':'application/vnd.latent.typescript.buffer-selection.v2+json'}], 'buffer-globals-signed-selection-asset')
    captured = context.read(read_file(artifact/'compatibility-context.json', 65536))
    module = buffer_module(captured)
    require(module is not None and all(name in module for name in BUFFER_GLOBAL_MATERIALS)
        and captured['qualification'] == 'unknown' and captured['authority'] == 'none',
        'buffer-globals-complete-unknown-context')
    frontend = {'source':digest(read_file(ROOT/'tools/qualify_typescript_buffer_globals.py')),
        'artifacts':{'component':value['component']['sha256']}}
    require(outcomes.from_build(artifact, {'artifacts':{'component':'component.wasm'}}, frontend).context_state == 'observed',
        'buffer-globals-normal-sidecar-recheck')
    complete = read_json(artifact/'BUILD-COMPLETE.json')
    for name in ('typecheck', 'bundle', 'componentize'):
        require(len([row for row in complete['commands'] if row['stage'] == name and row['exitCode'] == 0]) == 1,
            'buffer-globals-normal-'+name)
    return {**value, 'selection':file_identity(artifact/'typescript-buffer-selection.json'),
        'scope':'repository-controlled-global-provision; no-published-package'}


def invocation_identity(row, requested, revision, seen):
    """Bind the original public CLI receipt, not its requested-ID wrapper."""
    data = row['response']['data']
    actual = data.get('activationId')
    require(type(actual) is str and actual == requested and actual not in seen,
        'buffer-globals-actual-distinct-activation')
    pin = data.get('resolvedRevision')
    require(type(pin) is dict and set(pin) == set(revision)
        and all(type(pin[key]) is str and pin[key] == value for key,value in revision.items()),
        'buffer-globals-actual-published-revision')
    seen.add(actual)


def execute(artifact, native, work, deadline, public, run):
    signed = work/'signed'
    run('normal-signing', str(native['capsule_authoring']), 'demo-sign', str(signed), str(artifact), seconds=30)
    for name in ('client', 'node'):
        (work/name).mkdir(mode=0o700)
    rows, retirement = [], []
    with owned_cancellation() as cancellation, ExitStack() as cleanup:
        client = RecordingClient(native['latent'], work/'client', cancellation,
            deadline.end-10, evidence=work/'private-controls', invocation_timeout_millis=120000,
            control_timeout_millis=125000)
        config = configuration(work/'node', signed)
        settings = read_json(config)
        # A distinct closed programme uses the already approved Socket reference
        # funding; the old pure-Buffer programme's 16/16/64 remains unchanged.
        settings['providers']['activationRuntime']['limits'] = dict(fixture.REFERENCE)
        config.write_bytes((json.dumps(settings, indent=2)+'\n').encode())
        deadline.remaining(30)
        node = connect(client, native['latentd'], work/'node', config, 'examples', 0)
        cleanup.callback(node.close)
        probe = Probe(node, file_identity(native['latentd']))
        startup = {'actualStartup':node.startup_record, 'ownedProcess':probe.identity,
            'configuration':file_identity(config), 'operatorConfiguredRuntimeLimits':dict(fixture.REFERENCE),
            'applicationLimits':dict(fixture.LIMITS),'nodeGlobalCpuFuelCeiling':settings['execution']['maximumCpuFuel'],
            'internalFactoryOrStoreIdentities':'unobserved', 'sameBackendBasis':'one-owned-node-process'}
        public.json('STARTUP.json', startup)
        source = signed/'my-greeting'
        published = client.call('release', 'publish-package', source/'package',
            '--evidence', source/'evidence/index.json', '--operation-id', 'global-buffer-publish', '--expected-generation', '0')
        require(published['outcomeKnown'] is True, 'buffer-globals-known-publication')
        publication = published['data']['operation']['publication']['id']
        target = deploy(client, source/'deployment.json', publication, grants=grants(client, node, publication))
        require(target['service'] == SERVICE and target['budget'] == fixture.LIMITS,
            'buffer-globals-original-effective-budget')
        revision, seen = selected_revision(client, target), set()
        try:
            for mode, name in enumerate(fixture.CASES):
                deadline.remaining(120)
                activation = 'global-buffer-'+name
                row = call(client, target, 'typescript-buffer-globals', 'run', [mode], activation)
                rows.append({'case':name,'mode':mode,'invocation':row})
                invocation_identity(row, activation, revision, seen)
                require_result(row, 'global-buffer:'+str(mode)+':pass|fresh=1', 0)
                used = row['response']['data']['consumption']
                require(0 < int(used['cpuFuel']) <= fixture.LIMITS['cpuFuel']
                    and 0 < int(used['peakMemoryBytes']) <= fixture.LIMITS['memoryBytes']
                    and int(used['logBytes']) == 0, 'buffer-globals-original-consumption')
                retire(client, probe, target, work, name)
                # retire()'s last existing read is the original provider-usage
                # observation. Retain it without another RPC or a model row.
                usage=read_json(client.evidence/f'{client.calls:03}.json')['data']['nodeUsage']
                require(not usage['unavailable'] and all(key in usage['counters']
                    and int(usage['counters'][key])==0 for key in ACTIVE_COUNTERS),'buffer-globals-retained-active-counters')
                retirement.append({'case':name,'nodeSample':read_json(work/('after-'+name+'.json')),
                    'providerUsage':usage})
                deadline.check()
            require(len(seen) == 4, 'buffer-globals-four-distinct-actual-activations')
            delete_all(client, [target['name']])
            deleted = sample(client, probe, 'global-buffer-after-delete', 0)
            stop(client, node)
            shutdown = stopped_record(node)
            require(shutdown['reaped'] and shutdown['record']['clean'], 'buffer-globals-clean-shutdown')
            public.json('SHUTDOWN.json', {'afterDelete':deleted,'shutdown':shutdown})
            return {'publication':publication,'deployment':target,'resolvedRevision':revision,'cases':len(rows),
                'sameBackend':True,'freshStateWitness':'source-controlled counter=1 and original initializer bytes per call',
                'referenceFunding':dict(fixture.REFERENCE)}
        finally:
            public.json('INVOCATIONS.json', rows)
            public.json('RETIREMENTS.json', retirement)


def qualify(tools, output):
    require(sys.platform == 'linux' and platform.machine() in ('x86_64','AMD64')
        and sys.version_info[:3] == (3,13,5), 'buffer-globals-pinned-host')
    tools, output = Path(tools).resolve(strict=True), Path(output).resolve()
    require(ROOT not in output.parents and output != ROOT and output not in ROOT.parents
        and tools not in output.parents and output not in tools.parents and tools != output,
        'buffer-globals-separated-public-output')
    require(os.environ.get('GITHUB_REF') == 'refs/heads/'+BRANCH
        and os.environ.get('GITHUB_EVENT_NAME') == 'push'
        and os.environ.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric', 'buffer-globals-owning-origin')
    deadline, public = Deadline(), Public(output)
    commands, stage = [], 'source'
    record = {'schemaVersion':'latent.typescript.global-buffer-signed.v1','status':'in-progress',
        'engineBuildCount':0,'libraryBuildCount':0,'nativeBuildCount':0,'guestComponentBuildCount':0,
        'wholeCostQualification':False,'physicalKernelRetirement':False,'productionEnablement':False,
        'wholeAC5':False,'wholeAC7':False,'publishedLibraryQualification':False}
    recipe = {name:file_identity(ROOT/name) for name in RECIPE}
    private = tempfile.TemporaryDirectory(prefix='lsf-global-buffer-', dir='/tmp')
    with private as temporary:
        work = Path(temporary)
        environment = build_environment(work)
        def run(label, *argv, seconds=60, env=None):
            require(len(commands) < 384 and re.fullmatch('[a-zA-Z0-9_-]{1,100}', label) is not None,
                'buffer-globals-command-count-label')
            maximum = deadline.remaining(seconds)
            began = time.monotonic()
            result = run_bounded_result(list(map(str,argv)), ROOT, env or environment,
                timeout_seconds=maximum, max_output_bytes=4*1024**2)
            row = {'label':label,'maximumSeconds':maximum,'returncode':result.returncode,
                'elapsedSeconds':time.monotonic()-began,
                **{name:{'bytes':len(getattr(result,name)),'sha256':digest(getattr(result,name))}
                   for name in ('stdout','stderr')}}
            commands.append(row)
            # Only public compiler/control channels are copied. Signing and
            # acquisition channels retain hashes, never private stdout/stderr.
            if label in ('source-controls','normal-build'):
                for name in ('stdout','stderr'):public.put(label+'.'+name+'.txt',getattr(result,name))
            require(result.returncode == 0, 'buffer-globals-command-failed:'+label)
            deadline.check()
            return result.stdout
        try:
            stage='normal-private-root-preflight'
            require(stat.S_IMODE(work.stat().st_mode)==0o700, 'buffer-globals-private-root-mode')
            # Normal installer policy, full ancestry and ACL checks; no repair/waiver.
            with install_files.directory(work, owners={0, os.geteuid()}):
                pass
            record['normalInstallerPreflight']='passed-unchanged-policy'
            stage='source'
            commit = run('source-commit','git','rev-parse','HEAD').decode().strip()
            tree = run('source-tree','git','rev-parse','HEAD^{tree}').decode().strip()
            require(os.environ.get('GITHUB_SHA') == commit and re.fullmatch('[0-9a-f]{40}',commit) is not None
                and os.environ.get('GITHUB_RUN_ATTEMPT') == '1'
                and re.fullmatch('[1-9][0-9]{0,19}',os.environ.get('GITHUB_RUN_ID','')) is not None
                and not run('source-clean','git','status','--porcelain').strip(), 'buffer-globals-exact-clean-source')
            record.update(sourceCommit=commit,sourceTree=tree,workflowOrigin={key:os.environ[key]
                for key in ('GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_SHA','GITHUB_REF','GITHUB_EVENT_NAME')},recipe=recipe)
            stage='pinned-source-controls'
            code="import unittest,json,sys;s=unittest.defaultTestLoader.loadTestsFromNames(['tools.tests.test_typescript_buffer_globals','tools.tests.test_typescript_buffer_globals_qualification']);r=unittest.TextTestRunner(verbosity=2).run(s);print(json.dumps(dict(testsRun=r.testsRun,skipped=len(r.skipped),failures=len(r.failures),errors=len(r.errors))));sys.exit(0 if r.wasSuccessful() else 1)"
            controls=json.loads(run('source-controls',sys.executable,'-B','-c',code,seconds=60,
                env={**environment,'LSF_TYPESCRIPT_FRONTEND':str(tools)}))
            require(controls == {'testsRun':8,'skipped':0,'failures':0,'errors':0}
                and all(type(value) is int for value in controls.values()),'buffer-globals-eight-no-skips')
            record['sourceControls']=controls
            stage='normal-inputs'
            token=os.environ.get('GH_TOKEN');require(type(token) is str and 0<len(token)<=4096,'buffer-globals-read-token')
            acquisition_environment={**environment,'GH_TOKEN':token}
            run('compiler-inputs',sys.executable,'-B','-c',
                'from pathlib import Path;import sys;from tools.typescript_guest.borrow_signed_inputs import prepare;prepare(Path(sys.argv[1]))',
                work/'compiler',seconds=240,env=acquisition_environment)
            run('native-inputs',sys.executable,'-B','tools/java_phase_native_products.py','--output',work/'native',seconds=240,env=acquisition_environment)
            compiler=work/'compiler/products';native_root=work/'native'
            original_compiler=inputs.verify(compiler,run);original_native=host.verify_prepared(native_root)
            native=host.native_products(native_root)
            public.json('INPUTS.json',{'compiler':original_compiler,'native':original_native})
            stage='normal-project'
            app=fixture.project(work/'project');source=inventory(fixture.verify(app))
            public.put('PROJECT-SOURCE.json',source)
            for name in (*fixture.SOURCES,'world.wit'):public.put('probe-'+name,read_file(ROOT/fixture.FIXTURE/name))
            artifact=work/'build'
            stage='normal-isolated-build'
            try:
                run('normal-build',sys.executable,'-B','tools/typescript_capsule.py','build',app,'--output',artifact,
                    '--tools',tools,'--repository','https://github.com/KirilsTurkins/latent-service-fabric',
                    '--contracts-tool',native['capsule_contracts'],'--packager',native['package'],
                    '--runtime-engine',compiler/'engine/engine.wasm','--runtime-engine-receipt',compiler/'engine/engine-input.json',
                    '--runtime-splicer',compiler/'splicer/splicer','--runtime-splicer-receipt',compiler/'splicer/splicer-input.json',seconds=420)
            finally:
                collect_build(artifact,public)
            original_build=build_evidence(artifact);record.update(build=original_build,guestComponentBuildCount=1)
            stage='four-signed-cases'
            record['execution']=execute(artifact,native,work,deadline,public,run)
            stage='final-fences'
            require(original_build==build_evidence(artifact) and source==inventory(fixture.verify(app))
                and original_compiler==inputs.verify(compiler,run) and original_native==host.verify_prepared(native_root)
                and recipe=={name:file_identity(ROOT/name) for name in recipe}
                and run('final-commit','git','rev-parse','HEAD').decode().strip()==commit
                and run('final-tree','git','rev-parse','HEAD^{tree}').decode().strip()==tree
                and not run('final-clean','git','status','--porcelain').strip(), 'buffer-globals-final-original-inputs')
            stage='normal-private-root-cleanup'
            private.cleanup()
            require(not work.exists(), 'buffer-globals-private-root-not-removed')
            deadline.check();record.update(status='passed',signedAndAdmitted=True,privateWorkRemoved=True)
            public.json('RESULT.json',record)
            return record
        except BaseException as error:
            public.json('FAILED.json',dict(record,status='failed',stage=stage,errorCategory=type(error).__name__))
            raise
        finally:
            public.json('COMMANDS.json',commands)
            public.finish()


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(qualify(args.tools,args.output)))
