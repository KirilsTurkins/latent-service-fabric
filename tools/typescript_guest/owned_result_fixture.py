"""Closed actual-component fixture; no production selector or ownership model."""
from pathlib import Path
import shutil
from tools.rust_capsule_project import ROOT, read_file, write_json
from tools.phase3_resource_identity import file_identity

WORLD = 'tests:owned-result/capsule@1.0.0'
CASE_NAMES = (
    'delivered-connection', 'immediate-cancel-same-store-reuse',
    'delayed-returned-cancel-same-store-reuse', 'chunk-cancel-reuse',
    'inactive-none-no-drop', 'intentional-wit-error', 'nested-active-own',
    'pending-cancel-no-result', 'destructor-refusal-quarantine',
    'distinct-resource-types', 'nested-inactive-none',
)
BACKING_CASE_NAMES = (
    'ordinary-empty-list', 'cancelled-empty-list', 'cancelled-nested-backing',
    'cancelled-empty-nested-and-zero-stride', 'ordinary-empty-nested-values',
    'cancelled-mixed-own-and-backing', 'cancelled-active-error-string',
    'mixed-destructor-refusal-count-unobserved',
)
BACKING_RUN = '''
async backingRun(which){
 const before=backingFreeCount();
 if(which===0||which===4){
  const op=start('backing',which,0);const value=await op.promise;
  if(which===0){if(value.length!==0)throw Error('expected-empty-list');}
  else if(value.length!==1||value[0].label!==''||value[0].data.length!==0||
          value[0].zero.length!==2||value[0].zero.some(item=>item.length!==0)||value[0].payload!==undefined)
    throw Error('expected-nested-empty-values');
  await op.borrowReleased;
 }else{
  if(!Number.isInteger(which)||which<1||which>7)throw Error('unknown-backing-case');
  await cancelled('backing',which);
  if(which===7)throw Error('destructor-refusal-was-not-a-trap');
 }
 return [true,backingFreeCount()-before];
}
'''
WIT = '''package tests:owned-result@1.0.0;
interface provider {
  resource connection;
  resource chunk;
  take-connection: async func(mode:u32)->result<option<connection>,u32>;
  take-chunk: async func(mode:u32)->result<option<chunk>,u32>;
  nested: async func(mode:u32)->result<list<option<connection>>,u32>;
}
interface api {run:async func(which:u32)->bool;}
world capsule {import provider;import latent:runtime/activation@0.1.0;import latent:clock/monotonic@0.1.0;import latent:clock/wall@0.1.0;export api;}
'''
APPLICATION = '''import {start,dispose} from 'tests:owned-result/control@1.0.0';
async function delivered(alias,mode=0){const op=start(alias,mode,0);const value=await op.promise;if(value)dispose(value);await op.borrowReleased;}
async function cancelled(alias,mode=0){const op=start(alias,mode,1);let rejected=false;try{await op.promise;}catch(error){if(error!=='activation-runtime-import-cancelled')throw error;rejected=true;}await op.borrowReleased;if(!rejected)throw Error('expected-logical-cancellation');}
export const api={async run(which){
 switch(which){
  case 0:await delivered('connection');break;
  case 1:await cancelled('connection');await delivered('connection');break;
  case 2:await cancelled('connection',1);await delivered('connection');break;
  case 3:await cancelled('chunk');await delivered('chunk');break;
  case 4:await cancelled('connection',2);await delivered('connection');break;
  case 5:{const op=start('connection',3,0);let failed=false;try{await op.promise;}catch(error){failed=error.payload===17;}await op.borrowReleased;if(!failed)throw Error('expected-WIT-error');break;}
  case 6:await cancelled('nested');await delivered('connection');break;
  case 7:{const op=start('connection',4,2);let failed=false;try{await op.promise;}catch(error){failed=error==='activation-runtime-import-cancelled';}await op.borrowReleased;if(!failed)throw Error('expected-no-result-cancel');break;}
  case 8:await cancelled('connection',5);throw Error('destructor-refusal-was-not-a-trap');
  case 9:await delivered('connection');await delivered('chunk');break;
  case 10:await cancelled('nested',2);break;
  default:throw Error('unknown-owned-result-case');
 }
 return true;
}};
'''


def frontend_files()->tuple[str,...]:
    names=('componentize.mjs','signed64.mjs','resources.mjs','source_splicer.mjs',
           'async_waiters.mjs','import_cancellation.mjs','owned_result_fixture.mjs')
    raw=read_file(ROOT/'tools/typescript_guest/componentize.mjs')
    optional=(
        b"import { borrowProbeBindings, borrowProbeProfile } from './borrow_probe.mjs';",
        b"import { borrowProbeBindings, borrowProbeProfile, borrowProbeSpliceCapture } from './borrow_probe.mjs';",
    )
    if b"from './borrow_probe.mjs'" in raw:
        if sum(raw.count(value) for value in optional)!=1 or raw.count(b"from './borrow_probe.mjs'")!=1:
            raise ValueError('owned-fixture-normal-borrow-helper-import-drift')
        names+=('borrow_probe.mjs',)
    return names


def prepare(output: Path, *, backing: bool = False) -> dict:
    """Derive a separate fixture frontend; normal compiler bytes stay intact."""
    output.mkdir(exist_ok=False)
    if type(backing) is not bool:raise ValueError('owned-fixture-backing-mode-must-be-boolean')
    world, application = WIT, APPLICATION
    if backing:
        world=world.replace('  resource chunk;\n',
            '  resource chunk;\n  record cell {label:string,data:list<u16>,zero:list<tuple<>>,payload:option<connection>}\n'
            '  backing: async func(mode:u32)->result<list<cell>,string>;\n',1)
        world=world.replace('interface api {run:async func(which:u32)->bool;}',
            'interface api {run:async func(which:u32)->bool;backing-run:async func(which:u32)->tuple<bool,u32>;}')
        application=application.replace("import {start,dispose}","import {start,dispose,backingFreeCount}",1)
        application=application.replace('\n}};\n','\n},'+BACKING_RUN+'};\n',1)
    (output/'world.wit').write_text(world)
    dependencies=output/'deps';dependencies.mkdir()
    for name in ('activation-runtime','clock'):shutil.copytree(ROOT/'wit/platform'/name,dependencies/name)
    (output/'application.js').write_text(application)
    recipe=output/'recipe';recipe.mkdir()
    names=frontend_files()
    for name in names:shutil.copyfile(ROOT/'tools/typescript_guest'/name,recipe/name)
    path=recipe/'componentize.mjs';raw=read_file(path)
    anchor=b"import { borrowReleaseHandoff } from './import_cancellation.mjs';"
    call=b'      generatedBindings = borrowReleaseHandoff(generatedBindings, parseBindings);'
    if raw.count(anchor)!=1 or raw.count(call)!=1:raise ValueError('owned-fixture-normal-frontend-drift')
    derived=raw.replace(anchor,anchor+b"\nimport {ownedResultFixtureBindings} from './owned_result_fixture.mjs';",1)
    derived=derived.replace(call,b'      generatedBindings = ownedResultFixtureBindings(generatedBindings, parseBindings'+
                            (b', true' if backing else b'')+b');',1)
    path.write_bytes(derived)
    record={'scope':'compiler-only-owned-result-fixture','normalFrontend':file_identity(ROOT/'tools/typescript_guest/componentize.mjs'),
            'fixtureFrontend':file_identity(path),'world':file_identity(output/'world.wit'),
            'application':file_identity(output/'application.js'),'cases':list(CASE_NAMES),
            'fixtureRecipe':{name:file_identity(recipe/name) for name in names},
            'runtimePumpPatched':False,'canonicalIntrinsicsMocked':False,'signedExecution':False}
    if backing:record['backingCases']=list(BACKING_CASE_NAMES)
    write_json(output/'fixture.json',record)
    return record
