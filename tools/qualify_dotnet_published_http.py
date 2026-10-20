"""Capture, compile once and execute ordinary AOT-compatible HTTP libraries."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from tools import application_dependencies as dependencies
from tools import dotnet_catalogue_free_build as staging
from tools import dotnet_published_http_fixture as fixture
from tools import dotnet_published_http_node as node
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.dotnet_dependency_authoring import source_files
from tools.wait_runtime_native_products import native_products, verify_prepared
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, write_json

MATERIALS = ('tools/qualify_dotnet_published_http.py','tools/dotnet_published_http_fixture.py',
    'tools/dotnet_published_http_node.py','tools/dotnet_catalogue_free_build.py',
    fixture.ROOT_SOURCE,fixture.PRIVATE_SOURCE,'tools/sdk_native_products_reader.py','tools/wait_runtime_native_products.py',
    '.github/workflows/dotnet-published-http.yml')


def qualify(native_input, tools, output):
    native_input,tools,output=map(lambda p:p.resolve(),(native_input,tools,output))
    require(ROOT!=output and ROOT not in output.parents
        and all(output!=p and output not in p.parents and p not in output.parents for p in (native_input,tools)),
        'published-dotnet-separated-build-inputs')
    output=fresh(output)
    deadline=time.monotonic()+1800
    materials={n:file_identity(ROOT/n) for n in MATERIALS}
    original_native=verify_prepared(native_input)
    native=native_products(native_input)
    before={n:file_identity(p,512*1024**2) for n,p in native.items()}
    record={'schemaVersion':'latent.dotnet.published-http.qualification.v1','status':'incomplete',
        'qualificationSources':materials,'nativeProducer':original_native,'fullTicketQualification':False}
    stage='normal-project-and-nuget-capture'
    try:
        app=fixture.project(output/'application')
        record['capture']=fixture.install(app,output/'outside',tools)
        write_json(output/'capture.json',record['capture'])
        accepted=dependencies.verify_inputs(app,'dotnet').lock
        captured=inventory(source_files(app))
        stage='catalogue-free-normal-builder'
        staged=output/'staged-recipe'
        selected=staging.stage(ROOT,staged)
        write_json(output/'catalogue-free-source.json',selected)
        def build(destination, approval=None):
            args=[sys.executable,'-I','-S','-B',str(staged/staging.SELF),
                '--project',str(app),'--output',str(destination),'--tools',str(tools),
                '--contracts-tool',str(native['capsule_contracts']),'--packager',str(native['package']),
                '--repository','https://github.com/KirilsTurkins/latent-service-fabric',
                '--expect-source-digest',selected['inventoryDigest']]
            if approval is not None:args+=['--executable-approval',approval]
            result=run_bounded_result(args,staged,build_environment(output),
                timeout_seconds=min(900,deadline-time.monotonic()),max_output_bytes=4*1024**2)
            destination.mkdir(exist_ok=True)
            for name in ('stdout','stderr'):(destination/('compiler.'+name+'.txt')).write_bytes(getattr(result,name))
            write_json(destination/'compiler-command.json',{'argv':args,'exitCode':result.returncode,
                'maximumSeconds':900,'maximumOutputBytes':4*1024**2})
            return result
        stage='exact-unapproved-generator-refusal'
        denied=output/'generator-approval-required'
        refused=build(denied)
        failure=read_json(denied/'BUILD-FAILED.json')
        require(refused.returncode!=0 and failure['stage']=='executable-input-approval'
            and not (denied/'BUILD-COMPLETE.json').exists(),'published-dotnet-generator-ran-without-approval')
        request=read_json(denied/'executable-input-approval-request.json')
        require(request['specification']['network']=='denied'
            and request['specification']['credentials']=='not-inherited'
            and request['specification']['executableInputs'], 'published-dotnet-generator-isolation-required')
        # The controlled qualification fixture approves only its retained exact
        # generator/target closure. Normal builds keep their explicit review step.
        record['generatorApproval']={'identity':request['identity'],'specification':request['specification'],
            'unapprovedBuildRefusedBeforeCompile':True}
        stage='single-native-aot-component'
        artifact=output/'build'
        compiled=build(artifact,request['identity'])
        require(compiled.returncode==0,'published-dotnet-normal-component-build')
        require(staging.verify(staged)==selected and inventory(source_files(app))==captured
            and dependencies.verify_inputs(app,'dotnet').lock==accepted,
            'published-dotnet-captured-or-staged-inputs-mutated')
        require(read_file(artifact/'source-inputs.json')==captured,'published-dotnet-normal-source-observation')
        executable=read_json(artifact/'executable-input-outputs.json',32*1024**2)
        require(executable['approvalIdentity']==request['identity'] and executable['compilerCommandSucceeded'] is True,
                'published-dotnet-exact-generator-output-observation')
        record['generatorOutputs']=file_identity(artifact/'executable-input-outputs.json',32*1024**2)
        record['build']=read_json(artifact/'BUILD-COMPLETE.json')
        record['component']=file_identity(artifact/'component.wasm',64*1024**2)
        stage='signed-library-and-extension-programme'
        execution=node.run(artifact,native,output/'node')
        require(execution['status']=='passed' and len(execution['cases'])==20
            and len(execution['preEntryRefusals'])==2,'published-dotnet-complete-owning-programme')
        record['node']=file_identity(output/'node/qualification.json')
        require(time.monotonic()<deadline and materials=={n:file_identity(ROOT/n) for n in MATERIALS}
            and original_native==verify_prepared(native_input)
            and before=={n:file_identity(p,512*1024**2) for n,p in native.items()}
            and inventory(source_files(app))==captured and staging.verify(staged)==selected,
            'published-dotnet-final-source-native-and-deadline')
        record.update(status='passed',guestExecutions=20,preIoRefusals=2,
            catalogueDataPresent=False,applicationHandlerInjection=False,
            publisherAuthenticated=False,hermetic=False)
        write_json(output/'qualification.json',record)
        return record
    except BaseException:
        record.update(status='failed',stage=stage)
        write_json(output/'FAILED.json',record)
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('native','tools','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    print(qualify(args.native,args.tools,args.output)['status'])
