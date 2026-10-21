"""One normal v6 component: queue8/9 differential and queue16 lifecycle.

Original v5 recipes/ceilings/receipts retain their identities. This programme
changes only the explicitly versioned guest profile and the independently
selected queue ceiling; tasks and every other original ceiling stay fixed.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

if __package__ in {None,''}:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import go_resource_runtime_fixture as fixture, rust_http_installed_native_products as products
from tools.go_guest.queues import PROFILE
from tools.go_resource_runtime_build import build_evidence
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.qualify_go_resource_runtime import MATERIALS as RESOURCE_MATERIALS
from tools.qualify_sdk_scratch import build_component
from tools.qualify_typescript_resource_runtime import execute
from tools.rust_capsule_project import ROOT, fresh, inventory, snapshot
from tools.run_rust_capsule_workflow import write_workflow_receipt

MATERIALS = (*RESOURCE_MATERIALS, 'tools/qualify_go_queued_work.py','tools/go_queue_node.py',
    'tools/go_guest/queues.py','.github/workflows/go-queued-work.yml')


def qualify(native_directory, output):
    require(sys.platform == 'linux' and sys.version_info >= (3,13), 'Go-queue-linux-python313')
    native_directory = Path(native_directory).resolve(strict=True)
    output = Path(output).absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents
            and output != native_directory and output not in native_directory.parents
            and native_directory not in output.parents, 'Go-queue-separated-owned-inputs')
    native_record = products.verify_prepared(native_directory)
    native = products.native_products(native_directory)
    for path in native.values():path.chmod(0o700)
    output = fresh(output)
    source = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,timeout=10).decode().strip()
    helpers = {name:file_identity(ROOT/name) for name in MATERIALS}
    consumer_native = source_identity(ROOT)
    go = shutil.which('go')
    require(go is not None, 'Go-queue-owned-pinned-compiler-required')
    compiler = file_identity(Path(go).resolve(strict=True),128*1024*1024)
    record = {'schemaVersion':'latent.go.queued-work-qualification.v1','status':'incomplete',
        'source':source,'materials':helpers,'compiledNative':native_record,'consumerNativeSource':consumer_native,
        'compiledNativeSource':products.SOURCE,'consumerNativeCompiledByThisCampaign':False,
        'compiler':compiler,'nativeProductsBuilt':0,'engineRebuilt':False,'guestComponentsCompiled':0,
        'historicalNormalProgrammeRelabelledAsCurrent':False,'fullTicketQualification':False,
        'profile':PROFILE,'queueReservationsPerLogicalGoroutine':1,'reservationLifetime':'through-gdestroy',
        'managedQueueReservations':8,'originalTaskCeiling':16,'programmes':[]}
    stage = 'ordinary-unchanged-transitive-capture'
    try:
        app,record['fixture'] = fixture.project(output/'project',output/'outside',runtime_profile=PROFILE)
        record['capture'] = fixture.capture(app,output/'outside',Path(go).resolve(strict=True))
        before = inventory(snapshot(app))
        binaries = {name if name in ('latent','latentd') else 'examples/'+name:path for name,path in native.items()}
        stage = 'one-fresh-normal-captured-v6-component'
        artifact = build_component('go',app,output/'build',binaries)
        record['guestComponentsCompiled'] = 1
        require((artifact/'source-inputs.json').read_bytes() == before, 'Go-queue-actual-source-capture')
        record['freshBuild'] = build_evidence(artifact,profile=PROFILE)
        for ceiling in (8,9,16):
            stage = 'signed-original-component-queue-' + str(ceiling)
            observed = execute(artifact,native,output/('node-'+str(ceiling)),language='go',go_queue_ceiling=ceiling)
            require(observed['status'] == 'passed', 'Go-queue-real-signed-programme')
            record['programmes'].append({'queueCeiling':ceiling,
                'receipt':file_identity(output/('node-'+str(ceiling))/'qualified.json')})
            write_workflow_receipt(output/'progress.json',record)
        require(inventory(snapshot(app)) == before and products.verify_prepared(native_directory) == native_record
                and source_identity(ROOT) == consumer_native
                and helpers == {name:file_identity(ROOT/name) for name in MATERIALS}
                and file_identity(Path(go).resolve(strict=True),128*1024*1024) == compiler,
                'Go-queue-final-source-compiler-native-identities')
        record.update(status='passed',outcomes=25,signedAndAdmitted=True,sourceOriginalsRemoved=True,
            fullCostMatrixQualified=False,physicalMemoryAccountingQualified=False)
        write_workflow_receipt(output/'qualified.json',record)
        return record
    except BaseException as error:
        record.update(status='failed',stage=stage,errorCategory=type(error).__name__)
        write_workflow_receipt(output/'FAILED.json',record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    print(qualify(args.native,args.output)['status'])
