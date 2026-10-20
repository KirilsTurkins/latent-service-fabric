"""One fresh normal C23 resource component when old public signer inputs are absent."""
from __future__ import annotations
import argparse
from pathlib import Path
import shutil
import sys

if __package__ in {None,''}:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from tools.application_dependencies import verify_inputs
from tools.c_capsule_project import create
from tools.c_compiled_resource_fixture import prepare as capture
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_resource_tenants import qualify
from tools.resource_tenant_inputs import native_products, original_build
from tools.rust_capsule_project import ROOT, fresh, inventory, read_file, read_json, snapshot, write_json

ANCESTRY = {'run':39272444227,'job':118128004400,'artifact':12196069156,
    'archiveBytes':8718449,'archiveDigest':'sha256:20c21e8922c3a3f191179a162b88cb507a5f139fe1ebde87248d69fb6b1de042',
    'componentDigest':'sha256:bb5c7cd50e88c9d1ed33adf754711104484fee1074050bc0d8bcb7699b8d9b25',
    'originalCompilerObservationRetained':False,'oldObservationReconstructed':False}


def build_component(output, binaries):
    from tools.c_capsule_build import build
    output = fresh(output)
    material_names = ('tools/resource_tenant_fresh_c.py','tools/c_compiled_resource_fixture.py',
        'tools/c_capsule_project.py','tools/c_capsule_build.py')
    materials = {name:file_identity(ROOT/name) for name in material_names}
    application = create(output/'application','greeting')
    captured = capture(application)
    verified = verify_inputs(application,'c')
    require(verified is not None and captured['originalsRemoved'] is True,
        'resource-tenant-C-originals-must-be-removed-after-capture')
    before = inventory(snapshot(application))
    selected = {name:shutil.which(name) for name in ('zig','wit-bindgen','wasm-tools')}
    require(all(selected.values()),'resource-tenant-C-pinned-tools-required')
    artifact = build(application,output/'build',binaries['examples/capsule_contracts'],
        binaries['examples/package'],'https://github.com/KirilsTurkins/latent-service-fabric',
        installed={name:Path(value).resolve(strict=True) for name,value in selected.items()})
    require(read_file(artifact/'source-inputs.json',16*1024**2) == before
        and inventory(snapshot(application)) == before
        and verify_inputs(application,'c').identity == verified.identity
        and materials == {name:file_identity(ROOT/name) for name in material_names},
        'resource-tenant-C-fresh-compile-source-or-closure-changed')
    expected = {key:file_identity(artifact/name,64*1024**2) for key,name in (
        ('component','component.wasm'),('buildComplete','BUILD-COMPLETE.json'),
        ('buildObservation','build-observation.json'),('sourceInputs','source-inputs.json'))}
    proof = {'operation':'fresh-normal-captured-C23-guest-build','guestComponentsCompiled':1,
        'nativeProductsBuilt':0,'normalBaselineRepeated':False,'oldCompilerObservationBackfilled':False,
        'historicalFiniteAncestry':ANCESTRY,'materials':materials,'capture':captured,'capturedInputIdentity':verified.identity,
        'freshBuild':original_build(artifact,'c',expected)}
    write_json(output/'fresh-build.json',proof)
    return artifact,expected,proof


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('native','native-producer','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    arguments = parser.parse_args()
    producer = read_json(arguments.native_producer)
    binaries,native_proof = native_products(arguments.native.resolve(strict=True),producer)
    for path in binaries.values():path.chmod(0o700)
    base = fresh(arguments.output.absolute())
    artifact,expected,build = build_component(base/'fresh-C',binaries)
    result = qualify('c',artifact,expected,arguments.native,producer,base/'coupled')
    write_json(base/'qualified.json',{'schemaVersion':'latent.resource.tenant-C-fresh.v1',
        'status':'passed','build':build,'native':native_proof,
        'coupledReceipt':file_identity(base/'coupled/qualified.json'),'fullTicketQualification':False})
    print(result['status'])
