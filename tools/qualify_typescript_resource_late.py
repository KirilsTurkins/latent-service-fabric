"""One normal TypeScript component; six signed resource late/fresh outcomes."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

if __package__ in {None,''}:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from tools import c_thread_native_products as products
from tools import qualify_typescript_resource_runtime as base
from tools import typescript_resource_late as late
from tools import typescript_resource_runtime_fixture as fixture
from tools import typescript_resource_runtime_inputs as compiler_inputs
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.rust_capsule_project import ROOT, fresh, inventory, snapshot
from tools.run_rust_capsule_workflow import write_workflow_receipt
from tools.typescript_guest.build import build

MATERIALS = tuple(dict.fromkeys((*base.MATERIALS,'tools/qualify_typescript_resource_late.py',
    'tools/typescript_resource_late.py','tools/c_thread_native_products.py',
    'tools/sdk_native_products_reader.py','.github/workflows/typescript-resource-late.yml')))


def qualify(native_directory, compiler_directory, tools, output):
    require(sys.platform == 'linux' and sys.version_info >= (3,13),'resource-ts-late-linux-python313')
    native_directory,compiler_directory,tools = (Path(p).resolve(strict=True)
        for p in (native_directory,compiler_directory,tools))
    output = Path(output).absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents
        and all(output != p and output not in p.parents and p not in output.parents
            for p in (native_directory,compiler_directory,tools)), 'resource-ts-late-separated-inputs')
    native_record = products.verify_prepared(native_directory)
    compiler_record = compiler_inputs.verify(compiler_directory)
    native = products.native_products(native_directory)
    for path in native.values():path.chmod(0o700)
    output = fresh(output)
    source = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,timeout=10).decode().strip()
    materials = {name:file_identity(ROOT/name) for name in MATERIALS}
    consumer_native = source_identity(ROOT)
    accounting = late.accounting_sources(products.SOURCE)
    record = {'schemaVersion':'latent.typescript.resource-late-qualification.v1','status':'incomplete',
        'source':source,'materials':materials,'compiledNative':native_record,
        'compiledNativeSource':products.SOURCE,'consumerNativeSource':consumer_native,
        'compilerInputs':compiler_record,'nativeProductsBuilt':0,'engineRebuilt':False,
        'guestComponentsCompiled':0,'fullTicketQualification':False,
        'frozenLogAccountingSources':accounting,'cryptographicEntropyClaimed':False}
    stage = 'ordinary-outside-transitive-capture'
    try:
        app,record['fixture'] = fixture.project(output/'project',output/'outside',late_completion=True)
        record['capture'] = fixture.capture(app,output/'outside')
        before = inventory(snapshot(app))
        stage = 'one-fresh-normal-component-build'
        artifact = build(app,output/'build',native['capsule_contracts'],native['package'],
            'https://github.com/KirilsTurkins/latent-service-fabric',tools=tools,
            runtime_engine=compiler_directory/'engine/engine.wasm',
            runtime_engine_receipt=compiler_directory/'engine/engine-input.json',
            runtime_splicer=compiler_directory/'splicer/splicer',
            runtime_splicer_receipt=compiler_directory/'splicer/splicer-input.json')
        record['guestComponentsCompiled'] = 1
        require((artifact/'source-inputs.json').read_bytes() == before,'resource-ts-late-source-capture')
        record['freshBuild'] = base.build_evidence(artifact)
        stage = 'signed-two-tenant-late-facility-programme'
        observed = base.execute(artifact,native,output/'node',late_completion=True)
        require(observed['status'] == 'passed' and inventory(snapshot(app)) == before
            and products.verify_prepared(native_directory) == native_record
            and compiler_inputs.verify(compiler_directory) == compiler_record
            and source_identity(ROOT) == consumer_native
            and materials == {name:file_identity(ROOT/name) for name in MATERIALS}
            and accounting == late.accounting_sources(products.SOURCE),
            'resource-ts-late-final-source-compiler-native-fences')
        record.update(status='passed',nodeReceipt=file_identity(output/'node/qualified.json'),
            outcomes=6,signedAndAdmitted=True,sourceOriginalsRemoved=True,
            lateCompletionProgramme='accepted-setTimeout-clear-during-callback-facilities-v1')
        write_workflow_receipt(output/'qualified.json',record)
        return record
    except BaseException as error:
        record.update(status='failed',stage=stage,errorCategory=type(error).__name__)
        write_workflow_receipt(output/'FAILED.json',record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('native','compiler','tools','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args = parser.parse_args()
    print(qualify(args.native,args.compiler,args.tools,args.output)['status'])
