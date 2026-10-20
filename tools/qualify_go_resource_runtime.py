"""One fresh ordinary Go resource/goroutine component on authenticated V7 products."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

if __package__ in {None,''}:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import go_resource_runtime_fixture as fixture, wasmtime_48_0_7_native_products as products
from tools.java_replay_materials import git_source_identity
from tools.go_resource_runtime_build import build_evidence
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.qualify_sdk_scratch import build_component
from tools.qualify_typescript_resource_runtime import execute, MATERIALS as SHARED_MATERIALS
from tools.rust_capsule_project import ROOT, fresh, inventory, snapshot
from tools.run_rust_capsule_workflow import write_workflow_receipt

MATERIALS=(*SHARED_MATERIALS,'tools/qualify_go_resource_runtime.py','tools/go_resource_runtime_build.py',
    'tools/go_resource_runtime_fixture.py','tools/go_node_stop_probe.py',
    'tools/wasmtime_48_0_7_native_products.py','tools/sdk_native_products_reader.py',
    '.github/workflows/go-resource-runtime.yml')


def qualify(native_directory,output):
    require(sys.platform=='linux' and sys.version_info>=(3,13),'resource-Go-linux-python313')
    native_directory=Path(native_directory).resolve(strict=True);output=Path(output).absolute()
    require(output!=ROOT and ROOT not in output.parents and output not in ROOT.parents
        and output!=native_directory and output not in native_directory.parents and native_directory not in output.parents,
        'resource-Go-separated-owned-inputs')
    native_record=products.verify_prepared(native_directory);native=products.native_products(native_directory)
    for path in native.values():path.chmod(0o700)
    output=fresh(output);source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,timeout=10).decode().strip()
    helpers={name:file_identity(ROOT/name) for name in MATERIALS};consumer_native=source_identity(ROOT)
    require(consumer_native==git_source_identity(products.SOURCE),
            'resource-Go-current-native-source-must-match-producer')
    go=shutil.which('go');require(go is not None,'resource-Go-owned-pinned-compiler-required')
    compiler=file_identity(Path(go).resolve(strict=True),128*1024*1024)
    record={'schemaVersion':'latent.go.resource-runtime-qualification.v1','status':'incomplete',
        'source':source,'materials':helpers,'compiledNative':native_record,'consumerNativeSource':consumer_native,
        'compiler':compiler,'nativeProductsBuilt':0,'engineRebuilt':False,'guestComponentsCompiled':0,
        'historicalNormalProgrammeRelabelledAsCurrent':False,'fullTicketQualification':False}
    stage='ordinary-outside-transitive-Go-capture'
    try:
        app,record['fixture']=fixture.project(output/'project',output/'outside')
        record['capture']=fixture.capture(app,output/'outside',Path(go).resolve(strict=True))
        before=inventory(snapshot(app));binaries={name if name in ('latent','latentd') else 'examples/'+name:path
                                                for name,path in native.items()}
        stage='fresh-normal-captured-Go-v5-component'
        artifact=build_component('go',app,output/'build',binaries)
        record['guestComponentsCompiled']=1
        require((artifact/'source-inputs.json').read_bytes()==before,'resource-Go-actual-source-capture-mismatch')
        record['freshBuild']=build_evidence(artifact)
        stage='signed-two-tenant-resource-goroutine-timer-programme'
        observed=execute(artifact,native,output/'node',language='go')
        require(observed['status']=='passed' and inventory(snapshot(app))==before
            and products.verify_prepared(native_directory)==native_record
            and source_identity(ROOT)==consumer_native
            and helpers=={name:file_identity(ROOT/name) for name in MATERIALS}
            and file_identity(Path(go).resolve(strict=True),128*1024*1024)==compiler,
            'resource-Go-final-source-compiler-and-native-identities')
        record.update(status='passed',nodeReceipt=file_identity(output/'node/qualified.json'),outcomes=13,
            signedAndAdmitted=True,sourceOriginalsRemoved=True)
        write_workflow_receipt(output/'qualified.json',record);return record
    except BaseException as error:
        record.update(status='failed',stage=stage,errorCategory=type(error).__name__)
        write_workflow_receipt(output/'FAILED.json',record);raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(qualify(args.native,args.output)['status'])
