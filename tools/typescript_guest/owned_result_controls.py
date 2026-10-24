"""Fresh normal compiler/engine and actual native OWN-result prerequisites.

This first programme does NOT execute a canonical OWN Component or certify
provider close, table reuse, signed admission or complete native cost.
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
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT,read_file,write_json,fresh,digest
from tools.typescript_guest import activation_engine,native_build,splicer_build,borrow_support,borrow_controls
from tools.typescript_guest.owned_result_library import reconstruct

BASELINE='17b2558bf08f2221657a5d2866b00218fb597d9e'
HEADER='sdk/typescript-guest/activation/native_imports.h'
NATIVE_CASES=borrow_controls.CASES+(
    'retired-import-finally-preserves-cancellation-no-double-ack',
    'resolved-carrier-cancel-preserves-public-rejection-and-fresh-reuse',
)
LIFECYCLE_CASES=(
    'cancelled-immediate-return-requires-disposal','immediate-result-keeps-lift-storage',
    'typed-result-retains-subtask-through-lifting','blocked-cancel-is-requested-only-once',
    'late-return-after-cancel-never-lifts','terminal-cancel-before-result-drop',
)
SOURCE_MODULES=(
    'tools.tests.test_typescript_native_await','tools.tests.test_typescript_native_task_meta',
    'tools.tests.test_typescript_owned_result_source','tools.tests.test_typescript_import_cancellation',
    'tools.tests.test_typescript_owned_library','tools.tests.test_typescript_owned_controls',
    'tools.tests.test_typescript_import_backing_source',
)
SOURCE_CASES=32
BACKING_CORE_CASES=(
    'invalid-active-tag','overflowing-list-range','misaligned-list',
    'zero-size-nonzero-pointer','valid-empty-string','valid-zero-stride-list',
    'nested-invalid-after-valid-child','own-trap-before-container-free',
)
RECIPE=(
    'tools/qualify_typescript_owned_results.py','tools/typescript_guest/owned_result_controls.py',
    'tools/typescript_guest/owned_result_library.py','tools/typescript_guest/borrow_controls.py',
    'tools/typescript_guest/borrow_support.py','tools/typescript_guest/borrow_controls_wasi.mjs',
    'tools/typescript_borrow_retry_inputs.py','tools/java_replay_materials.py',
    'tools/typescript_guest/async_waiters.mjs','tools/typescript_guest/import_cancellation.mjs',
    'sdk/typescript-guest/activation/tests/native_imports.cpp',
    'sdk/typescript-guest/activation/tests/native_import_lifecycle.cpp',
    'tools/tests/fixtures/typescript_record_retirement/jsapi.h',
    'tools/tests/fixtures/typescript_record_retirement/js/TypeDecls.h',
    '.github/workflows/typescript-owned-results.yml','tools/build_process.py',
    'tools/build_process_linux.py','tools/build_process_signals.py','tools/build_observation.py',
    'tools/phase3_resource_identity.py','tools/rust_capsule_project.py',
    'tools/install_guest_bindgen.py','tools/typescript_capsule.py','tools/requirements.lock',
    'tools/build_typescript_native_engine.py',
    *splicer_build.recipe_paths(),
    *activation_engine.engine_input_paths('spidermonkey-activation-promises-clocks-imports-v1'),
    *(name.replace('.','/')+'.py' for name in SOURCE_MODULES),
    'tools/tests/fixtures/typescript_owned_result_compiler.json',
    'tools/tests/fixtures/typescript_normal_library_validation.json',
    'tools/tests/fixtures/typescript_native_open_binding.json',
    'tools/tests/fixtures/typescript_native_task_state.json',
    'tools/tests/fixtures/typescript_import_backing_embedding.json',
)


def require(value,reason):
    if not value:raise ValueError(reason)


class Deadline:
    def __init__(self,seconds=5400):self.end=time.monotonic()+seconds
    def remaining(self,maximum):
        remaining=min(maximum,self.end-time.monotonic())
        require(remaining>0,'own-controls-aggregate-deadline')
        return remaining
    def finish(self):self.remaining(1)

    @classmethod
    def workflow(cls):
        raw=os.environ.get('LSF_OWN_CAMPAIGN_STARTED_NS','')
        require(re.fullmatch(r'[1-9][0-9]{0,19}',raw) is not None,'own-controls-setup-clock-required')
        elapsed=(time.time_ns()-int(raw))/1_000_000_000
        require(0<=elapsed<5400,'own-controls-setup-deadline')
        return cls(5400-elapsed),elapsed


def source_controls(value:dict)->None:
    require(type(value) is dict and set(value)=={'testsRun','skipped','failures','errors'}
            and all(type(item) is int for item in value.values())
            and value=={'testsRun':SOURCE_CASES,'skipped':0,'failures':0,'errors':0},
            'own-controls-source-controls-no-skips')


def rust_cases(raw:bytes)->list[str]:
    names=re.findall(r'^test (lsf_async(?:_splice)?::tests::[A-Za-z0-9_]+) \.\.\. ok$',raw.decode(),re.MULTILINE)
    expected=[]
    for module,file in [('lsf_async','async_import_descriptor.rs'),('lsf_async_splice','async_import_splice.rs')]:
        source=read_file(ROOT/'sdk/typescript-guest/activation'/file).decode()
        expected += [module+'::tests::'+name for name in re.findall(r'#\[test\]\s+fn ([a-zA-Z0-9_]+)\(',source)]
    require(len(expected)==17 and len(names)==len(set(names))==17 and set(names)==set(expected),
            'own-controls-all-seventeen-actual-rust-tests-required')
    require(re.search(r'test result: ok\. 17 passed; 0 failed; 0 ignored;',raw.decode()) is not None,
            'own-controls-rust-summary-or-skips')
    return names


def emitted_backing_controls(directory:Path)->dict:
    """Require the real Rust-emitted closure, never synthesize missing files."""
    require(directory.is_dir() and not directory.is_symlink(),'backing-core-emission-required')
    raw=read_file(directory/'manifest.json',32768)
    rows=json.loads(raw)
    require(type(rows) is list and len(rows)==8,'backing-core-exact-emitted-set')
    names={'manifest.json'};modules=[]
    for which,(name,row) in enumerate(zip(BACKING_CORE_CASES,rows,strict=True)):
        file=f'{which:02}-{name}.wasm';names.add(file)
        require(type(row) is dict and set(row)=={'case','file','bytes','argument','expectedReturn',
                'expectedTrap','expectedDoubleFreeReturns','allocatorEvidence'}
                and row['case']==name and row['file']==file
                and type(row['argument']) is int and row['argument']==32
                and (row['expectedReturn'] is None or type(row['expectedReturn']) is int)
                and row['expectedReturn']==(None if which==7 else int(which in (4,5)))
                and row['expectedTrap'] is (which==7)
                and type(row['expectedDoubleFreeReturns']) is int and row['expectedDoubleFreeReturns']==0
                and row['allocatorEvidence'] is False,'backing-core-emitted-contract')
        path=directory/file
        require(path.is_file() and not path.is_symlink(),'backing-core-original-file-required')
        body=read_file(path,65536)
        require(body.startswith(b'\0asm') and type(row['bytes']) is int and row['bytes']==len(body),
                'backing-core-actual-emitted-module')
        modules.append({'case':name,'file':file,**file_identity(path,65536)})
    require({path.name for path in directory.iterdir()}==names,'backing-core-no-extra-products')
    return {'manifest':file_identity(directory/'manifest.json',32768),'modules':modules,
            'allocatorEvidence':False,'executed':False}


def native_case(row:dict,case:str)->dict:
    require(case in NATIVE_CASES and type(row) is dict and row.get('case')==case
            and type(row.get('status')) is int and row['status']==0
            and row.get('hostcallInGC') is False and row.get('dropOrderValid') is True,
            'own-controls-native-case-failed')
    counters=('subtaskDrops','cancelRequests','exactAckRefusals','importStarts','importLifts',
              'importFinishes','importDisposals','nativeAdmissions','nativeAcknowledgements')
    require(all(type(row.get(name)) is int and 0<=row[name]<=256 for name in counters),
            'own-controls-native-counter-shape')
    keys=('managerBytes','baselineManagerBytes','recordBytes','baselineRecordBytes',
          'recordAlignment','baselineRecordAlignment','observerBytes')
    require(all(type(row.get(name)) is int and 0<row[name]<65536 for name in keys),'own-controls-actual-ABI-required')
    require(row['managerBytes']==row['baselineManagerBytes'] and row['recordBytes']>row['baselineRecordBytes']
            and row['recordBytes']%row['recordAlignment']==0
            and row['baselineRecordBytes']%row['baselineRecordAlignment']==0,'own-controls-own-record-ABI-delta')
    quarantine=case in borrow_controls.REFUSAL_CASES
    require(row.get('expectedQuarantine') is quarantine and type(row.get('owners')) is int
            and 0<=row['owners']<=256 and (row['owners']>0 if quarantine else row['owners']==0),
            'own-controls-original-owner-retention')
    if quarantine:
        ack=case.endswith('-ack')
        require(row.get('recordDestroyed') is True and row.get('observerDestroyed') is True
                and row.get('exactAckRefusals')==(1 if ack else 0)
                and row.get('subtaskDrops')==(1 if ack else 0)
                and row.get('cancelRequests')==(1 if ack else 0),'own-controls-real-refusal-boundary')
    if case==borrow_controls.NORMAL_CASES[0]:
        require(row.get('recordDestroyed') is True and row.get('observerDestroyed') is True
                and row.get('subtaskDrops')==1 and row.get('cancelRequests')==1,'own-controls-original-blocked-drop')
    if case==NATIVE_CASES[-2]:
        require(row.get('importFinishes')==2 and row.get('importLifts')==0 and row.get('subtaskDrops')==1,
                'own-controls-retired-finally-not-exercised')
    if case==NATIVE_CASES[-1]:
        require(row.get('importStarts')==2 and row.get('importLifts')==1 and row.get('importFinishes')==2
                and row.get('importDisposals')==1 and row.get('subtaskDrops')==2,
                'own-controls-resolved-carrier-and-fresh-reuse-not-exercised')
    return {name:row[name] for name in keys}


def lifecycle_case(row:dict,case:str)->None:
    require(case in LIFECYCLE_CASES and type(row) is dict and row.get('case')==case
            and type(row.get('status')) is int and row['status']==0,'own-controls-lifecycle-case')
    counters=('subtaskDrops','joined','resultOwners','nativeOwners','tasks','idleWaits')
    require(all(type(row.get(name)) is int and 0<=row[name]<=256 for name in counters)
            and row['joined']==row['resultOwners']==row['tasks']==0
            # The unchanged reference retains its original initialized
            # readiness-set owner; immediate handle-zero cases create no set.
            and row['nativeOwners']==(0 if case in LIFECYCLE_CASES[:2] else 1),
            'own-controls-lifecycle-retirement')
    require(row['subtaskDrops']==(0 if case in LIFECYCLE_CASES[:2] else 1),
            'own-controls-lifecycle-original-handle-drop')
    require(row['idleWaits']==(1 if case in LIFECYCLE_CASES[2:5] else 0),
            'own-controls-lifecycle-original-readiness')


def workflow_origin(commit:str)->dict:
    names=('GITHUB_REPOSITORY','GITHUB_WORKFLOW_REF','GITHUB_WORKFLOW_SHA','GITHUB_EVENT_NAME',
           'GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_SHA','GITHUB_REF')
    values={name:os.environ.get(name) for name in names}
    require(all(isinstance(value,str) and 0<len(value)<=1024 for value in values.values()),'own-controls-workflow-origin')
    require(values['GITHUB_REPOSITORY']=='KirilsTurkins/latent-service-fabric' and values['GITHUB_SHA']==commit
            and values['GITHUB_WORKFLOW_SHA']==commit and values['GITHUB_EVENT_NAME'] in ('push','workflow_dispatch')
            and values['GITHUB_WORKFLOW_REF']=='KirilsTurkins/latent-service-fabric/.github/workflows/typescript-owned-results.yml@'+values['GITHUB_REF'],
            'own-controls-exact-owning-workflow')
    require(re.fullmatch(r'[1-9][0-9]{0,19}',values['GITHUB_RUN_ID']) is not None
            and re.fullmatch(r'[1-9][0-9]{0,5}',values['GITHUB_RUN_ATTEMPT']) is not None,
            'own-controls-workflow-attempt')
    return values


def build(output:Path,tools:Path,*,wasm_tools='wasm-tools',bindgen='wit-bindgen')->dict:
    require(sys.platform=='linux' and platform.machine() in ('x86_64','AMD64'),'own-controls-linux-x86-64')
    require(sys.version_info[:3]==(3,13,5),'own-controls-pinned-python')
    tools=tools.resolve(strict=True);output=output.resolve()
    require(output!=ROOT and ROOT not in output.parents and output!=tools and tools not in output.parents
            and output not in tools.parents,'own-controls-independent-output')
    output=fresh(output);deadline,setup_seconds=Deadline.workflow();environment=build_environment(output)
    environment.update(CARGO_BUILD_JOBS='2',CARGO_INCREMENTAL='0',RUSTUP_TOOLCHAIN='1.97.1')
    recipe={name:file_identity(ROOT/name) for name in dict.fromkeys(RECIPE)}
    record={'schemaVersion':'latent.typescript.owned-result-prerequisites.v1','status':'in-progress',
        'scope':'fresh-normal-compiler-engine-unit-native-ABI-prerequisites','qualification':'unknown',
        'apiSupport':'not-evaluated','canonicalOwnComponentExecuted':False,'tableReuseQualified':False,
        'signedExecution':False,'physicalProviderQualified':False,'wholeCostQualification':False,
        'setupElapsedSeconds':setup_seconds,
        'recipe':recipe,'limits':{'overallSeconds':5400,'splicerSeconds':900,'rustUnitSeconds':600,
            'engineSeconds':1200,'supportSeconds':300,'diagnosticCompileAndLinkSeconds':120,'nativeCaseSeconds':20,
            'sourceControlSeconds':60,'rustJobs':2,'commandOutputBytes':4*1024**2},'commands':[]}
    def run(label,*arguments,seconds=30,cwd=output,env=None):
        require(re.fullmatch(r'[A-Za-z0-9_-]{1,100}',label) is not None,'own-controls-command-label')
        maximum=deadline.remaining(seconds);command=list(map(str,arguments));began=time.monotonic()
        write_json(output/(label+'.command.json'),{'argv':command,'maximumSeconds':maximum})
        result=run_bounded_result(command,cwd,env or environment,timeout_seconds=maximum,max_output_bytes=4*1024**2)
        for channel in ('stdout','stderr'):(output/(label+'.'+channel+'.log')).write_bytes(getattr(result,channel))
        value={'returncode':result.returncode,'elapsedSeconds':time.monotonic()-began,
               'stdout':{'bytes':len(result.stdout),'sha256':digest(result.stdout)},
               'stderr':{'bytes':len(result.stderr),'sha256':digest(result.stderr)}}
        write_json(output/(label+'.result.json'),value);record['commands'].append({'label':label,**value})
        require(result.returncode==0,'own-controls-command-failed:'+label);deadline.finish();return result.stdout
    stage='source'
    try:
        commit=run('source-commit','git','rev-parse','HEAD',cwd=ROOT).decode().strip()
        tree=run('source-tree','git','rev-parse','HEAD^{tree}',cwd=ROOT).decode().strip()
        require(not run('source-clean','git','status','--porcelain','--untracked-files=normal',cwd=ROOT).strip(),
                'own-controls-committed-clean-source-required')
        record.update(sourceCommit=commit,sourceTree=tree,workflowOrigin=workflow_origin(commit))
        node=shutil.which('node',path=environment['PATH']);require(node is not None,'own-controls-node-required')
        require(run('node-version',node,'--version').strip()==b'v24.19.0','own-controls-pinned-node')
        compiler=splicer_build.compiler_inventory(tools);record['publicCompiler']=compiler
        parser=tools/'node_modules/acorn/dist/acorn.mjs';record['pinnedParser']=file_identity(parser,2*1024**2)
        stage='source-controls'
        program=("import json,sys,unittest; suite=unittest.defaultTestLoader.loadTestsFromNames("+repr(SOURCE_MODULES)+
            ");result=unittest.TextTestRunner(verbosity=2).run(suite);print(json.dumps(dict(testsRun=result.testsRun,skipped=len(result.skipped),failures=len(result.failures),errors=len(result.errors))));sys.exit(0 if result.wasSuccessful() else 1)")
        controls=json.loads(run('pinned-source-controls',sys.executable,'-c',program,seconds=60,cwd=ROOT,
            env=dict(environment,LSF_TYPESCRIPT_ACORN=str(parser))))
        source_controls(controls);record['sourceControls']=controls
        stage='normal-library-reconstruction'
        library,record['libraryReconstruction']=reconstruct(output/'library-inputs',run,deadline.end)
        original_library=native_build.validated_library(library)
        stage='fresh-normal-splicer'
        splicer=output/'splicer'
        run('fresh-splicer',sys.executable,ROOT/'tools/build_typescript_source_splicer.py','--output',splicer,
            '--tools',tools,seconds=900,cwd=ROOT)
        record['splicer']=native_build.source_splicer(splicer)
        stage='actual-rust-unit-tests'
        emitted=output/'backing-core-controls'
        rust_env=dict(environment,CARGO_HOME=str(splicer/'cargo-home'),CARGO_TARGET_DIR=str(splicer/'target'),
                      LSF_BACKING_CORE_CONTROLS=str(emitted))
        raw=run('actual-rust-units','cargo','test','--locked','--color','never','--lib','--package',
            'spidermonkey-embedding-splicer','lsf_async','--','--nocapture',seconds=600,
            cwd=splicer/'source'/('ComponentizeJS-'+activation_engine.COMPONENTIZE_TREE),env=rust_env)
        record['actualRustCases']=rust_cases(raw)
        record['emittedBackingControls']=emitted_backing_controls(emitted)
        stage='fresh-normal-engine'
        engine=output/'engine'
        run('fresh-engine',sys.executable,ROOT/'tools/build_typescript_native_engine.py','--output',engine,
            '--library',library,'--wit-bindgen',bindgen,'--wasm-tools',wasm_tools,
            '--source-splicer-build',splicer,seconds=1200,cwd=ROOT)
        built=json.loads(read_file(engine/'engine-build.json'));require(built['status']=='passed','own-controls-completed-new-engine')
        record['engineProducts']={name:file_identity(engine/name,64*1024**2) for name in
            ('engine.wasm','engine-input.json','engine-build.json','engine-compilation.json','source-derivation.json')}
        stage='normal-maintained-support'
        wasi=library/'wasi-source/wasi-sdk-30.0-x86_64-linux'
        support_record=borrow_support.build(output/'normal-support',wasi,engine,run,environment)
        record['normalSupport']=support_record;support=support_record['products']
        stage='actual-native-compile-and-link'
        includes=output/'control-includes';includes.mkdir()
        baseline=run('pre-own-baseline','git','show',BASELINE+':'+HEADER,cwd=ROOT)
        # Preserve the exact historical source unmodified; the new programme
        # measures its own changed Record instead of waiving the old validator.
        require(b'using ResourceDisposer' not in baseline and b'friend struct ImportBorrowControls;' in baseline,
                'own-controls-pre-own-baseline-required')
        (includes/'borrow-baseline-native-imports.h').write_bytes(baseline)
        record['baseline']={'commit':BASELINE,'path':HEADER,'bytes':len(baseline),'sha256':digest(baseline)}
        native=output/'own-controls.wasm';obj=output/'own-controls.o';native_deadline=min(deadline.end,time.monotonic()+120)
        phases=[];record['diagnosticPhases']=phases
        def phase(label,*argv):borrow_controls.diagnostic_phase(label,argv,run=run,deadline=native_deadline,output=output,phases=phases)
        phase('own-compile-controls',wasi/'bin/clang++','-std=c++20','-O0','-fno-sized-deallocation',
            '-DSTATIC_JS_API','-DJS_STANDALONE','-DLSF_TYPESCRIPT_BORROW_CONTROLS=1','-DLSF_TYPESCRIPT_OWNED_RESULT_CONTROLS=1',
            '-I'+str(engine/'spidermonkey/include'),'-I'+str(engine/'jobs-generated'),'-I'+str(engine/'clocks-generated'),
            '-I'+str(ROOT/'sdk/typescript-guest/activation'),'-I'+str(includes),
            '-include',engine/'spidermonkey/include/js-confdefs.h','-c',ROOT/'sdk/typescript-guest/activation/tests/native_imports.cpp','-o',obj)
        phase('own-link-controls',wasi/'bin/clang++','-O0',obj,engine/'spidermonkey/libspidermonkey.a',
            support['library'],support['wrapper'],*support['emulation'].values(),'-Wl,--lto-O0','-Wl,--strip-debug',
            '-Wl,--wrap=_ZdlPv','-Wl,-z,stack-size=8388608','-Wl,--max-memory=268435456','-o',native)
        # Closed projection of the maintained opaque-JS fixture. This executes
        # actual lifecycle/readiness C++ with explicit canonical/broker doubles;
        # it does not execute JS or establish component/runtime qualification.
        stubs=output/'lifecycle-includes';(stubs/'js').mkdir(parents=True)
        original=read_file(ROOT/'tools/tests/fixtures/typescript_record_retirement/jsapi.h')
        anchor=b'inline void JS_ReportErrorASCII(JSContext*, const char*) {}'
        require(original.count(anchor)==1,'own-controls-lifecycle-stub-preimage')
        (stubs/'jsapi.h').write_bytes(original.replace(anchor,
            b'bool JS_IsExceptionPending(JSContext*);\nvoid JS_ReportErrorASCII(JSContext*,const char*,...);'))
        (stubs/'js/TypeDecls.h').write_bytes(read_file(ROOT/'tools/tests/fixtures/typescript_record_retirement/js/TypeDecls.h'))
        lifecycle=output/'own-lifecycle.wasm'
        phase('own-compile-lifecycle',wasi/'bin/clang++','-std=c++20','-O0',
            '-I'+str(stubs),'-I'+str(engine/'jobs-generated'),
            ROOT/'sdk/typescript-guest/activation/tests/native_import_lifecycle.cpp','-o',lifecycle)
        require(time.monotonic()<native_deadline,'own-controls-diagnostic-final-deadline')
        run('validate-native-core',wasm_tools,'validate',native)
        run('validate-lifecycle-core',wasm_tools,'validate',lifecycle)
        record['lifecycleCore']=file_identity(lifecycle,4*1024**2)
        record['lifecycleStub']={name:file_identity(stubs/name) for name in ('jsapi.h','js/TypeDecls.h')}
        record['nativeCore']=file_identity(native,64*1024**2);record['nativeRows']=[];abi=None
        stage='actual-native-cases'
        for case in NATIVE_CASES:
            row=json.loads(run(case,node,ROOT/'tools/typescript_guest/borrow_controls_wasi.mjs',native,case,seconds=20))
            actual=native_case(row,case);require(abi is None or abi==actual,'own-controls-inconsistent-actual-ABI')
            abi=actual;record['nativeRows'].append(row)
        record['actualWasm32ABI']=abi
        record['lifecycleRows']=[]
        for case in LIFECYCLE_CASES:
            row=json.loads(run(case,node,ROOT/'tools/typescript_guest/borrow_controls_wasi.mjs',lifecycle,case,seconds=20))
            lifecycle_case(row,case);record['lifecycleRows'].append(row)
        stage='final-integrity'
        require(support_record['library']==file_identity(Path(support['library']),64*1024**2)
            and support_record['wrapper']==file_identity(Path(support['wrapper']),1024**2)
            and support_record['wasiEmulation']=={name:file_identity(Path(path),32*1024**2)
                for name,path in support['emulation'].items()},'own-controls-normal-support-changed')
        require(native_build.validated_library(library)[:3]==original_library[:3],'own-controls-library-changed')
        require(record['splicer']==native_build.source_splicer(splicer),'own-controls-new-splicer-changed')
        require(record['engineProducts']=={name:file_identity(engine/name,64*1024**2) for name in record['engineProducts']},
                'own-controls-new-engine-changed')
        require(record['publicCompiler']==splicer_build.compiler_inventory(tools),'own-controls-public-tools-changed')
        require(record['pinnedParser']==file_identity(parser,2*1024**2),'own-controls-parser-changed')
        require(recipe=={name:file_identity(ROOT/name) for name in recipe},'own-controls-source-changed')
        require(run('final-source-commit','git','rev-parse','HEAD',cwd=ROOT).decode().strip()==commit
            and run('final-source-tree','git','rev-parse','HEAD^{tree}',cwd=ROOT).decode().strip()==tree
            and not run('final-source-clean','git','status','--porcelain','--untracked-files=normal',cwd=ROOT).strip(),
            'own-controls-checkout-changed')
        deadline.finish();record.update(status='passed',freshSplicerBuildCount=1,freshEngineBuildCount=1,machBuildCount=0,
            limitations=['Canonical OWN component/disposer execution and table reuse remain unexecuted.',
                'Native broker/canonical intrinsics in the C++ diagnostic are explicit fixture doubles.',
                'The lifecycle reference additionally uses opaque-JS fixture headers; it executes no JavaScript.',
                'Actual Wasm32 ABI delta does not certify whole native/runtime/provider cost.'])
        write_json(output/'OWN-RESULTS.json',record);deadline.finish();return record
    except BaseException as error:
        (output/'OWN-RESULTS.json').unlink(missing_ok=True)
        record.update(status='failed',stage=stage,reason=str(error)[:2048])
        write_json(output/'FAILED.json',record);raise
