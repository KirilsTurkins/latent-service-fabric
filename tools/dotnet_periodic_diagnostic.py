"""Diagnostic-only private SDK derivation; original periodic oracle remains failed."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

if __package__ in {None, ''}:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import dotnet_catalogue_free_build as staging
from tools import dotnet_managed_capacity_fixture as fixture
from tools import release_preparation_cli_native_products as products
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.dotnet_guest import http_errors
from tools.dotnet_guest.compiler import runtime_inputs
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT,digest,fresh,inventory,read_file,read_json,snapshot,write_json

BASE='7d2c0f793cf4a87594eadd2d82d5798f448be34e'
HANDLER='sdk/dotnet-guest/tools/http-errors/IdleTimerDriver.cs'
CONSOLE='sdk/dotnet-guest/runtime/console/logging.rs'
SNIPPET='tools/fixtures/dotnet-periodic-handler-projection.cs'
STREAM='tools/fixtures/dotnet-periodic-console.rs'
CONTROL='tools/fixtures/dotnet-periodic-handler-control.cs'
ANCHOR=b'        // Preserve the complete original handler, including its FailFast catch.\n'
LOG='latent:log/log@0.1.0'


def codes():
    values=re.findall(rb'    b"([a-z-]+)",',read_file(ROOT/STREAM))
    require(len(values)==37 and len(set(values))==37,'periodic-closed-code-table')
    text=read_file(ROOT/SNIPPET).split(b'string[] diagnosticCodes = [\n',1)[1].split(b'        ];',1)[0]
    require(re.findall(rb'"([a-z-]+)"',text)==values,'periodic-cil-stream-code-table-equality')
    return [value.decode('ascii') for value in values]


def git_files(names):
    names=sorted(names)
    raw=subprocess.check_output(['git','cat-file','--batch'],cwd=ROOT,
        input=''.join(BASE+':'+name+'\n' for name in names).encode(),timeout=30)
    require(len(raw)<=16*1024**2,'periodic-base-preimage-bound');offset=0;result={}
    for name in names:
        end=raw.index(b'\n',offset);oid,kind,count=raw[offset:end].decode().split();count=int(count)
        value=raw[end+1:end+1+count];offset=end+2+count
        require(kind=='blob' and len(value)==count,'periodic-original-git-blob')
        import hashlib
        require(hashlib.sha1(b'blob '+str(count).encode()+b'\0'+value).hexdigest()==oid,'periodic-original-git-object')
        result[name]=value
    require(offset==len(raw),'periodic-original-git-trailing-data');return result


def derive():
    """Called only in the separate, detached diagnostic source checkout."""
    require(ROOT.name=='periodic-source' and (ROOT/'.git').is_file(),'periodic-private-detached-worktree-required')
    sdk={ 'sdk/dotnet-guest/'+name:value for name,value in snapshot(ROOT/'sdk/dotnet-guest').items() }
    original=git_files(sdk)
    require(sdk==original and read_file(ROOT/fixture.SOURCE)==git_files([fixture.SOURCE])[fixture.SOURCE],
        'periodic-exact-original-sdk-and-application')
    codes();before=inventory(sdk)
    handler=original[HANDLER];require(handler.count(ANCHOR)==1,'periodic-original-handler-source-anchor')
    selected={HANDLER:handler.replace(ANCHOR,read_file(ROOT/SNIPPET)+ANCHOR),CONSOLE:read_file(ROOT/STREAM)}
    for name,value in selected.items():(ROOT/name).write_bytes(value)
    after={'sdk/dotnet-guest/'+name:value for name,value in snapshot(ROOT/'sdk/dotnet-guest').items()}
    require(set(after)==set(sdk) and {name for name in sdk if sdk[name]!=after[name]}==set(selected)
        and all(after[name]==value for name,value in selected.items()),'periodic-only-two-selected-sdk-derivations')
    record={'schemaVersion':'latent.dotnet.periodic-diagnostic-source.v1','qualification':False,
        'baseSource':BASE,'originalSdk':json.loads(before),'selectedSdk':json.loads(inventory(after)),
        'derivations':{name:{'original':{'sha256':digest(sdk[name]),'bytes':len(sdk[name])},
            'selected':file_identity(ROOT/name)} for name in selected},
        'codes':codes(),'originalMain':file_identity(ROOT/fixture.SOURCE),
        'originalFailFastPreserved':True,'newConsoleAssemblyReference':'System.Console, Version=10.0.0.0, Culture=neutral, PublicKeyToken=b03f5f7f11d50a3a',
        'newExecutionAuthority':'explicit diagnostic LOG only','originalProductionSourceModified':False}
    write_json(ROOT/'PERIODIC-DIAGNOSTIC-SOURCE.json',record);return record


def controls(tools,output):
    output=fresh(output);source=output/'source';source.mkdir()
    (source/'Program.cs').write_bytes(read_file(ROOT/CONTROL))
    (source/'global.json').write_bytes(read_file(ROOT/'sdk/dotnet-guest/global.json'))
    (source/'Control.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        '<TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings>'
        '<Nullable>enable</Nullable><UseSharedCompilation>false</UseSharedCompilation><NuGetAudit>false</NuGetAudit>'
        '</PropertyGroup><ItemGroup><Reference Include="Mono.Cecil" HintPath="$(LsfCecilPath)" /></ItemGroup></Project>',encoding='utf8')
    before=inventory(snapshot(source));commands=Commands(source,output,build_environment(output),deadline_seconds=300,command_seconds=120)
    dotnet=shutil.which('dotnet',path=commands.environment['PATH']);require(dotnet is not None,'periodic-control-sdk')
    require(commands.run('control-sdk',dotnet,'--version').strip()==b'10.0.100','periodic-control-sdk-pin')
    tool=http_errors.verify_installed(ROOT/'sdk/dotnet-guest',tools)
    commands.run('control-build',dotnet,'build',source/'Control.csproj','-c','Release','--output',output/'bin',
        '--artifacts-path',output/'artifacts','-p:LsfCecilPath='+str(http_errors.cecil_path(tools)),'-nodeReuse:false')
    original=tools/'packages'/http_errors.PACKAGE/'native-hidden/System.Private.CoreLib.dll'
    commands.run('real-handler-rewrite',dotnet,tools/'http-errors/HttpErrors.dll','--managed-task-wait',
        original,output/'derived-CoreLib.dll',output/'rewrite.json')
    commands.run('actual-handler-copy',dotnet,output/'bin/Control.dll','graft',output/'derived-CoreLib.dll',output/'emitted')
    rows=[]
    for code,literal in enumerate(codes(),1):
        for kind,value in (('literal',literal),('wrapped','wrapped:'+literal)):
            raw=commands.run('handler-'+str(code)+'-'+kind,dotnet,output/'emitted/Control.dll','execute',str(code),value)
            require(len(raw)<=1024,'periodic-closed-control-output');rows.append(json.loads(raw))
    for value in ('public-fixture-unknown','writer-fails','success'):
        rows.append(json.loads(commands.run('handler-'+value,dotnet,output/'emitted/Control.dll','execute','0',value)))
    require(len(rows)==77 and all(row['passed'] is True and row['originalExceptionPreserved'] is True
        and row['guestQualified'] is False for row in rows),'periodic-all-actual-handler-controls')
    require(inventory(snapshot(source))==before and http_errors.verify_installed(ROOT/'sdk/dotnet-guest',tools)==tool,
        'periodic-control-inputs-unchanged')
    record={'qualification':False,'actualCopiedHandlers':1,'cases':rows,'source':json.loads(before),
        'tool':tool,'commands':commands.records,'nativeClockQueueAndFailFast':'explicit-test-ports'}
    write_json(output/'controls.json',record);return record


def qualify(native_input,tools,output):
    from tools import dotnet_periodic_diagnostic_node as node
    output=fresh(output);deadline=time.monotonic()+1200
    native_record=products.verify_prepared(native_input);native=products.native_products(native_input)
    selected=read_json(ROOT/'PERIODIC-DIAGNOSTIC-SOURCE.json')
    require(selected['qualification'] is False and selected['baseSource']==BASE,'periodic-source-derivation-required')
    require(json.loads(inventory(snapshot(ROOT/'sdk/dotnet-guest')))=={
        name.removeprefix('sdk/dotnet-guest/'):row for name,row in selected['selectedSdk'].items()},'periodic-selected-sdk-preimages')
    require(read_file(tools/'runtime-inputs.json')==runtime_inputs(ROOT),'periodic-current-derived-runtime-installation')
    selected_runtime=read_file(tools/'runtime-inputs.json')
    selected_tool=http_errors.verify_installed(ROOT/'sdk/dotnet-guest',tools)
    selected_main=file_identity(ROOT/fixture.SOURCE)
    selected_materials={name:file_identity(ROOT/name) for name in (
        SNIPPET,STREAM,CONTROL,'tools/dotnet_periodic_diagnostic.py','tools/dotnet_periodic_diagnostic_node.py')}
    record={'schemaVersion':'latent.dotnet.periodic-diagnostic.v1','qualification':False,'status':'incomplete',
        'diagnosticSource':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'originalFailedSource':BASE,'sourceDerivation':selected,'nativeProducer':native_record,
        'newNativeBuilds':0,'newNativeAotComponents':0,'full17Qualified':False,'diagnosticMaterials':selected_materials}
    stage='actual-handler-controls'
    try:
        record['controls']=controls(tools,output/'handler-controls')
        app=fixture.project(output/'application')
        world=app/'wit/world.wit';raw=read_file(world);require(raw.count(b'world service {')==1,'periodic-world-anchor')
        world.write_bytes(raw.replace(b'world service {',b'world service {\n    import latent:log/log@0.1.0;'))
        folder=app/'wit/deps/log';folder.mkdir();(folder/'package.wit').write_bytes(read_file(ROOT/'wit/platform/log/package.wit'))
        descriptor=read_json(app/'capsule-project.json');require(descriptor['limits']['logBytes']==0,'periodic-original-zero-log')
        descriptor['limits']['logBytes']=1024;(app/'capsule-project.json').write_text(json.dumps(descriptor,indent=2)+'\n',encoding='utf8')
        staged=output/'staged';captured=staging.stage(ROOT,staged);artifact=output/'build';stage='normal-diagnostic-native-aot'
        result=run_bounded_result([sys.executable,'-I','-S','-B',str(staged/staging.SELF),'--project',str(app),
            '--output',str(artifact),'--tools',str(tools),'--contracts-tool',str(native['capsule_contracts']),
            '--packager',str(native['package']),'--repository','https://github.com/KirilsTurkins/latent-service-fabric',
            '--expect-source-digest',captured['inventoryDigest']],staged,build_environment(output),
            timeout_seconds=min(900,deadline-time.monotonic()),max_output_bytes=4*1024**2)
        artifact.mkdir(exist_ok=True)
        for key in ('stdout','stderr'):(artifact/('compiler.'+key+'.txt')).write_bytes(getattr(result,key))
        require(result.returncode==0,'periodic-normal-build-must-succeed');record['newNativeAotComponents']=1
        record['build']=read_json(artifact/'BUILD-COMPLETE.json');stage='diagnostic-periodic-only'
        record['execution']=node.run(artifact,native,output/'node',deadline=deadline)
        require(products.verify_prepared(native_input)==native_record and staging.verify(staged)==captured,
            'periodic-final-native-and-recipe-fences')
        require(json.loads(inventory(snapshot(ROOT/'sdk/dotnet-guest')))=={
            name.removeprefix('sdk/dotnet-guest/'):row for name,row in selected['selectedSdk'].items()}
            and read_file(tools/'runtime-inputs.json')==selected_runtime==runtime_inputs(ROOT)
            and http_errors.verify_installed(ROOT/'sdk/dotnet-guest',tools)==selected_tool
            and file_identity(ROOT/fixture.SOURCE)==selected_main
            and {name:file_identity(ROOT/name) for name in selected_materials}==selected_materials,
            'periodic-final-selected-sdk-runtime-tool-application-and-diagnostic-inputs')
        record['status']='diagnostic-complete';write_json(output/'diagnostic.json',record);return record
    except BaseException:
        record.update(status='failed',stage=stage);write_json(output/'FAILED.json',record);raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=('derive','qualify'))
    for name in ('native','tools','output'):parser.add_argument('--'+name,type=Path)
    args=parser.parse_args()
    if args.mode=='derive':print(derive()['schemaVersion'])
    else:
        require(all(getattr(args,name) is not None for name in ('native','tools','output')),'periodic-explicit-inputs')
        print(qualify(args.native,args.tools,args.output)['status'])
