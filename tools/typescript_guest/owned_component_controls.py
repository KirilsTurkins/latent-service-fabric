"""One bounded real canonical OWN diagnostic; no signed/provider/full-cost claim."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import sys
import time

from tools.build_observation import build_environment
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT,read_file,fresh,write_json,digest
from tools.typescript_guest.owned_result_controls import Deadline
from tools.typescript_guest.owned_result_component import compile_fixture,select_products
from tools.typescript_guest.owned_result_fixture import CASE_NAMES,frontend_files
from tools.typescript_guest import splicer_build
from tools.typescript_guest import borrow_signed_inputs
from tools.typescript_guest import late_backing_evidence
from tools.typescript_guest.owned_result_controls import emitted_backing_controls

OWNER_SOURCE=borrow_signed_inputs.HEAD
ALLOCATIONS=(1,2,2,2,1,0,2,0,1,2,0)
IMPORTS=(1,2,2,2,2,1,2,1,1,2,1)
MEMORY=128*1024**2
FUEL=1_000_000_000
SOURCE_MODULES=('tools.tests.test_typescript_owned_fixture','tools.tests.test_typescript_owned_component',
                'tools.tests.test_typescript_late_backing_evidence','tools.tests.test_typescript_native_carrier_scheduling')
RECIPE=(
    'tools/qualify_typescript_owned_component.py','tools/typescript_guest/owned_component_controls.py',
    'tools/typescript_guest/owned_result_component.py','tools/typescript_guest/owned_result_fixture.py',
    'tools/typescript_guest/owned_result_fixture.mjs','tools/typescript_guest/compiler.py',
    'tools/typescript_guest/late_backing_evidence.py','tools/tests/test_typescript_late_backing_evidence.py',
    'tools/tests/test_typescript_native_carrier_scheduling.py',
    'tools/typescript_guest/componentize.mjs','tools/typescript_guest/async_waiters.mjs',
    'tools/typescript_guest/import_cancellation.mjs','tools/typescript_guest/resources.mjs',
    'tools/typescript_guest/signed64.mjs','tools/typescript_guest/source_splicer.mjs',
    'tools/typescript_guest/runtime_profile.py','tools/typescript_guest/import_profile.py',
    'tools/typescript_guest/build.py','tools/typescript_guest/bundle.mjs',
    'tools/typescript_guest/standard_global_types.py',
    'tools/typescript_guest/borrow_probe_profile.py',
    'sdk/typescript-guest/probes/borrow-release/outer.wit',
    'sdk/typescript-guest/probes/borrow-release/main.ts',
    'sdk/typescript-guest/probes/borrow-release/world.wit',
    'sdk/typescript-guest/probes/borrow-release/gate.wit',
    'sdk/typescript-guest/probes/borrow-release/private.d.ts',
    'tools/typescript_guest/splicer_input.py','tools/typescript_guest/native_build.py',
    'tools/typescript_guest/owned_result_controls.py','tools/typescript_guest/probe.py',
    'tools/typescript_guest/borrow_signed_inputs.py','tools/java_replay_materials.py',
    'tools/rust_capsule_build.py','tools/rust_capsule_project.py','tools/build_process.py',
    'tools/build_process_linux.py','tools/build_process_signals.py','tools/build_observation.py',
    'tools/captured_compiler_isolation.py','tools/phase3_resource_identity.py',
    'tools/tests/test_typescript_owned_fixture.py','tools/tests/test_typescript_owned_component.py',
    'tools/tests/fixtures/typescript_native_open_binding.json','tools/tests/fixtures/typescript_native_task_state.json',
    'crates/latent-wasmtime/examples/typescript_runtime_probe.rs',
    'crates/latent-wasmtime/examples/typescript_runtime_probe/owned_results.rs',
    'crates/latent-wasmtime/examples/typescript_runtime_probe/owned_results_runtime.rs',
    'crates/latent-wasmtime/examples/typescript_runtime_probe/backing_controls.rs',
    'Cargo.toml','Cargo.lock','rust-toolchain.toml','crates/latent-wasmtime/Cargo.toml',
    '.github/workflows/typescript-owned-component.yml',
    *splicer_build.recipe_paths(),
)


def require(value,reason):
    if not value:raise ValueError(reason)


def setup_deadline()->tuple[Deadline,float]:
    raw=os.environ.get('LSF_OWN_COMPONENT_STARTED_NS','')
    require(re.fullmatch(r'[1-9][0-9]{0,19}',raw) is not None,'canonical-own-setup-clock')
    setup=(time.time_ns()-int(raw))/1_000_000_000
    require(0<=setup<900,'canonical-own-aggregate-setup-deadline')
    return Deadline(900-setup),setup


def rows(raw:bytes)->list[dict]:
    require(len(raw)<=4*1024**2,'canonical-own-output-bound')
    result=[];prefix=[]
    for line in raw.decode().splitlines():
        if line.startswith('{'):result.append(json.loads(line))
        elif line:prefix.append(line)
    require(len(prefix)==2 and prefix[0]=='diagnostic compiler optimization: none'
            and re.fullmatch(r'diagnostic compile millis: [0-9]{1,9}',prefix[1]) is not None,
            'canonical-own-original-probe-prefix')
    require(len(result)==len(CASE_NAMES)==11,'canonical-own-all-eleven-required')
    for which,row in enumerate(result):
        require(type(row) is dict and row.get('schemaVersion')=='latent.typescript.canonical-own-case.v1'
                and type(row.get('case')) is int and row['case']==which and row.get('status')=='passed',
                'canonical-own-exact-case-or-status')
        counters=('allocations','destructorCalls','connectionDestructorCalls','chunkDestructorCalls',
                  'payloadDropsBeforeStoreDrop','payloadDropsAfterStoreDrop','futureStarts','futureDrops',
                  'pendingProviderStarts','matchedImportNativeOwnersBeforeStoreDrop',
                  'matchedImportResultOwnersBeforeStoreDrop','observedImports')
        require(all(type(row.get(key)) is int and 0<=row[key]<=256 for key in counters),
                'canonical-own-counter-shape')
        refused=which==8
        require(row['allocations']==row['destructorCalls']==row['payloadDropsAfterStoreDrop']==ALLOCATIONS[which]
                and row['payloadDropsBeforeStoreDrop']==(0 if refused else ALLOCATIONS[which])
                and row['liveBeforeStoreDrop'] is refused,'canonical-own-actual-payload-retirement')
        require(type(row.get('payloadCapacity')) is int and row['payloadCapacity']==1
                and row.get('sameStorePayloadReuse') is (which in (1,2,3,6,9))
                and row.get('canonicalResourceDropActual') is (ALLOCATIONS[which]>0)
                and row.get('canonicalTableIndexObserved') is False,'canonical-own-reuse-scope')
        require(row['futureStarts']==row['futureDrops'] and row['pendingProviderStarts']==int(which==7)
                and (which!=7 or row['futureStarts']==1),'canonical-own-started-future-drop')
        require(row['observedImports']==IMPORTS[which]
                and row['matchedImportNativeOwnersBeforeStoreDrop']==(2 if refused else 0)
                and row['matchedImportResultOwnersBeforeStoreDrop']==int(refused),
                'canonical-own-original-import-owners-before-store-drop')
        owners=row.get('runtimeOwnersBeforeStoreDrop')
        require(type(owners) is list and len(owners)==7 and all(type(v) is int and 0<=v<=64 for v in owners)
                and (owners[5]>0 and owners[6]>=2 if refused else owners[5]==0),
                'canonical-own-original-ledger-result-state')
        require(type(row.get('peakLinearMemoryBytes')) is int and 0<row['peakLinearMemoryBytes']<=MEMORY
                and type(row.get('fuel')) is int and 0<=row['fuel']<=FUEL,'canonical-own-memory-fuel')
        require(all(row.get(name) is False for name in
                ('nestedBackingStorageQualified','physicalProviderQualified','signedExecution')),
                'canonical-own-closed-qualification-scope')
        require(row['connectionDestructorCalls']+row['chunkDestructorCalls']==row['destructorCalls'],
                'canonical-own-distinct-resource-drop-counts')
        if which==3:require(row['chunkDestructorCalls']==2 and row['connectionDestructorCalls']==0,'canonical-own-chunk-type')
        if which==9:require(row['chunkDestructorCalls']==row['connectionDestructorCalls']==1,'canonical-own-two-types')
    return result


def build(output:Path,tools:Path,prepared:Path,*,profile:str='canonical-own')->dict:
    require(profile in ('canonical-own','late-backing'),'canonical-own-closed-profile')
    late=profile=='late-backing'
    require(sys.platform=='linux' and sys.version_info[:3]==(3,13,5),'canonical-own-pinned-linux-python')
    tools=tools.resolve(strict=True);prepared=prepared.resolve(strict=True);output=output.resolve()
    require(all(output!=path and path not in output.parents and output not in path.parents
                for path in (ROOT,tools,prepared)),'canonical-own-separated-fresh-output')
    deadline,setup=setup_deadline();output=fresh(output)
    environment=build_environment(output)
    environment.update(RUSTUP_TOOLCHAIN='1.97.1',CARGO_BUILD_JOBS='2',CARGO_INCREMENTAL='0',
        CARGO_PROFILE_DEV_DEBUG='0',CARGO_TARGET_DIR=str(output/'cargo-target'),
        LSF_TYPESCRIPT_ACORN=str(tools/'node_modules/acorn/dist/acorn.mjs'))
    commands=Commands(output,output,environment,deadline_seconds=900,command_seconds=600)
    commands.deadline=min(commands.deadline,deadline.end)
    recipe_names=RECIPE+tuple('tools/typescript_guest/'+name for name in frontend_files())
    recipe={name:file_identity(ROOT/name) for name in dict.fromkeys(recipe_names)}
    record={'schemaVersion':'latent.typescript.canonical-own-diagnostic.v1','status':'in-progress',
        'scope':'actual-canonical-resource-drops-and-same-store-capacity-one-payload-reuse',
        'qualification':'unknown','apiSupport':'not-evaluated','signedExecution':False,
        'physicalProviderQualified':False,'wholeCostQualification':False,
        'canonicalTableNumericIndexObserved':False,'nestedBackingStorageQualified':False,'selectedProfile':profile,
        'limits':{'overallSecondsIncludingSetup':900,'commandSeconds':600,'perCaseSeconds':20,
                  'aggregateLinearMemoryBytes':MEMORY,'fuelPerStore':FUEL,'rustJobs':2},
        'setupElapsedSeconds':setup,'recipe':recipe}
    stage='source-and-inputs'
    try:
        source=commands.run('canonical-source-head','git','-C',ROOT,'rev-parse','HEAD').decode().strip()
        tree=commands.run('canonical-source-tree','git','-C',ROOT,'rev-parse','HEAD^{tree}').decode().strip()
        require(not commands.run('canonical-source-clean','git','-C',ROOT,'status','--porcelain').strip(),
                'canonical-own-clean-committed-source')
        require(os.environ.get('GITHUB_SHA')==os.environ.get('GITHUB_WORKFLOW_SHA')==source
                and os.environ.get('GITHUB_REPOSITORY')=='KirilsTurkins/latent-service-fabric'
                and os.environ.get('GITHUB_EVENT_NAME') in ('push','workflow_dispatch')
                and os.environ.get('GITHUB_WORKFLOW_REF')=='KirilsTurkins/latent-service-fabric/.github/workflows/typescript-owned-component.yml@'+os.environ.get('GITHUB_REF',''),
                'canonical-own-actual-owning-workflow')
        record.update(sourceCommit=source,sourceTree=tree)
        require(commands.run('canonical-rust-version','rustc','--version').split()[:2]==[b'rustc',b'1.97.1'],
                'canonical-own-pinned-rust')
        program=("import json,sys,unittest;s=unittest.defaultTestLoader.loadTestsFromNames("+repr(SOURCE_MODULES)+
            ");r=unittest.TextTestRunner(verbosity=2).run(s);print(json.dumps(dict(testsRun=r.testsRun,skipped=len(r.skipped),failures=len(r.failures),errors=len(r.errors))));sys.exit(0 if r.wasSuccessful() else 1)")
        original_seconds=commands.command_seconds
        try:
            commands.command_seconds=min(original_seconds,60)
            result=json.loads(commands.run('canonical-source-controls',sys.executable,'-c',
                "import sys;sys.path.insert(0,"+repr(str(ROOT))+");"+program))
        finally:commands.command_seconds=original_seconds
        require(result=={'testsRun':14,'skipped':0,'failures':0,'errors':0},'canonical-own-all-fourteen-source-controls-required')
        record['sourceControls']=result
        def producer_git(label,*argv):
            require(argv[0]=='git','canonical-own-read-only-producer-git')
            return commands.run(label,'git','-C',ROOT,*argv[1:])
        record['qualifiedInput']=borrow_signed_inputs.verify(prepared,producer_git)
        stage='normal-component-construction'
        component,record['componentBuild']=compile_fixture(prepared,OWNER_SOURCE,tools,output,commands,backing=late)
        stage='normal-original-locked-probe-build'
        lock=file_identity(ROOT/'Cargo.lock')
        commands.run('canonical-probe-build','cargo','build','--locked','--manifest-path',ROOT/'Cargo.toml',
            '--package','latent-wasmtime','--example','typescript_runtime_probe','--jobs','2')
        require(lock==file_identity(ROOT/'Cargo.lock'),'canonical-own-original-cargo-lock-changed')
        probe=output/'cargo-target/debug/examples/typescript_runtime_probe'
        record['probe']=file_identity(probe,256*1024**2)
        stage='actual-eleven-canonical-cases'
        raw=commands.run('canonical-own-cases',probe,component,'none','sdk-owned-results',
                         *(['late-backing'] if late else []))
        record['rows']=rows(raw);record['rawObservation']={'bytes':len(raw),'sha256':digest(raw)}
        if late:
            stage='actual-eight-emitted-core-controls'
            emitted=emitted_backing_controls(prepared/'backing-core-controls')
            original_seconds=commands.command_seconds
            try:
                commands.command_seconds=min(original_seconds,60)
                core_raw=commands.run('actual-backing-core-controls',probe,prepared/'backing-core-controls',
                                      'none','sdk-backing-core')
            finally:commands.command_seconds=original_seconds
            record['backingCoreRows']=late_backing_evidence.core_rows(core_raw,emitted)
            record['emittedBackingControls']=emitted
            record['rawBackingCoreObservation']={'bytes':len(core_raw),'sha256':digest(core_raw)}
            stage='actual-eight-late-backing-cases'
            backing_raw=commands.run('actual-late-backing-cases',probe,component,'none','sdk-late-backing')
            record['backingRows']=late_backing_evidence.backing_rows(backing_raw)
            record['rawBackingObservation']={'bytes':len(backing_raw),'sha256':digest(backing_raw)}
            require(emitted==emitted_backing_controls(prepared/'backing-core-controls'),
                    'canonical-own-emitted-input-mutated')
        stage='final-integrity'
        require(record['probe']==file_identity(probe,256*1024**2),'canonical-own-probe-mutated')
        require(record['componentBuild']['component']==file_identity(component,64*1024**2),'canonical-own-component-mutated')
        require(record['componentBuild']['selectedPrerequisites']==select_products(prepared,OWNER_SOURCE),
                'canonical-own-qualified-input-mutated')
        require(record['qualifiedInput']==borrow_signed_inputs.verify(prepared,producer_git),
                'canonical-own-original-carrier-or-producer-mutated')
        require(recipe=={name:file_identity(ROOT/name) for name in recipe},'canonical-own-source-mutated')
        require(source==commands.run('canonical-final-head','git','-C',ROOT,'rev-parse','HEAD').decode().strip()
                and tree==commands.run('canonical-final-tree','git','-C',ROOT,'rev-parse','HEAD^{tree}').decode().strip()
                and not commands.run('canonical-final-clean','git','-C',ROOT,'status','--porcelain').strip(),
                'canonical-own-checkout-mutated')
        deadline.finish();record.update(status='passed',commands=commands.records,
            canonicalOwnComponentExecuted=True,actualCanonicalResourceDropExecuted=True,
            sameStorePayloadCapacityReuseExecuted=True,
            completeUnliftedResultBackingCleanupExecuted=late,
            limitations=['Standalone explicit runtime/clock/provider diagnostic hosts are not signed node admission.',
                'Original import Result and matched Native tokens are checked before Store Drop; unrelated managed Native and Task lifetimes are reported separately.',
                'Capacity-one payload reuse does not observe the guest canonical table numeric slot.',
                ('Only complete, unlifted host-lowered result backing is checked; delivered/partial-lower/parameter storage, provider physical close and whole cost remain unqualified.'
                 if late else 'Backing allocation release, provider physical close and whole native/runtime cost remain unqualified.')])
        write_json(output/'CANONICAL-OWN.json',record);deadline.finish();return record
    except BaseException as error:
        (output/'CANONICAL-OWN.json').unlink(missing_ok=True)
        record.update(status='failed',stage=stage,reason=str(error)[:2048],commands=commands.records)
        write_json(output/'FAILED.json',record);raise
