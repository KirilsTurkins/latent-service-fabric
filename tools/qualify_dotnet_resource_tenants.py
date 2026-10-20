"""Recompose retained public CLR cores, then sign/admit the finite tenant packet."""
from __future__ import annotations
import argparse
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

if __package__ in {None,''}:
 sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment, file_identity as material
from tools import dotnet_resource_originals as originals, dotnet_resource_recomposition as metadata
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_resource_tenants import qualify
from tools.resource_tenant_inputs import native_products, original_build
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, read_file, read_json, write_json
from tools.run_rust_capsule_workflow import write_workflow_receipt

MATERIALS=('tools/qualify_dotnet_resource_tenants.py','tools/dotnet_resource_originals.py',
 'tools/dotnet_resource_recomposition.py','tools/dotnet_guest/closed_io.py',
 'tools/dotnet_guest/internal_io.py','tools/dotnet_guest/composer.py','tools/dotnet_guest/compatibility.py')
VERSIONS=(b'wasm-tools 1.254.0',b'wasm-tools 1.254.0 (bb58fdf91 2026-07-20)')


def run(native, producer, output):
 require(sys.platform=='linux' and sys.version_info>=(3,13),'dotnet-resource-Linux-Python313')
 binaries,native_proof=native_products(native,producer)
 for path in binaries.values():path.chmod(0o700)
 output=fresh(output)
 materials={name:file_identity(ROOT/name) for name in MATERIALS}
 source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,timeout=10).decode().strip()
 require(re.fullmatch('[0-9a-f]{40}',source) is not None,'dotnet-resource-metadata-source')
 record={'schemaVersion':'latent.dotnet.resource-tenant-recomposition.v1','status':'incomplete',
  'metadataRecipeSource':source,'originalAotProducerHead':originals.COMPILED_SOURCE,
  'nativeAotCompilationPerformed':False,'nativeProductsBuilt':0,'guestComponentMetadataDerivations':1,
  'native':native_proof,'materials':materials,'publisherAuthenticated':False,'fullTicketQualification':False}
 stage='fixed-public-original-acquisition'
 try:
  original,record['originalAcquisition']=originals.acquire(output/'originals')
  commands=Commands(ROOT,fresh(output/'commands'),build_environment(output),deadline_seconds=1000,command_seconds=180)
  wasm=shutil.which('wasm-tools');require(wasm is not None,'dotnet-resource-pinned-codec-required')
  wasm=Path(wasm).resolve(strict=True)
  require(commands.run('metadata-codec-version',wasm,'--version').strip() in VERSIONS,'dotnet-resource-pinned-codec-version')
  compiler=SimpleNamespace(wasm=wasm,commands=commands,run=commands.run,sdk=ROOT/'sdk/dotnet-guest',
   generated_materials=[],isolation=None)
  stage='original-public-package-inventory'
  artifact,record['originalPublicPackage']=originals.reconstruct(original,output/'public-original',binaries,commands)
  stage='actual-production-closed-graph-and-core-equivalence'
  started,monotonic=int(time.time()),time.monotonic()
  component,record['metadataDerivation']=metadata.derive(artifact/'component.wasm',read_json(artifact/'build-observation.json'),
   output/'metadata',compiler,source)
  stage='fresh-metadata-only-observation'
  marker=metadata.publish_build(artifact,component,record['metadataDerivation'],output/'build-evidence',commands,source,
   started=started,elapsed=time.monotonic()-monotonic,current_materials=(material(wasm,'wasm-tools'),
    material(compiler.wac,'component-composer'),material(binaries['examples/package'],'packager'),
    material(binaries['examples/capsule_contracts'],'contracts-tool')))
  require(marker['nativeAotCompilation'] is False
   and next(row for row in read_json(artifact/'build-observation.json')['materials']
    if row['name']=='metadata-only-no-native-aot-compilation')['digest']==file_identity(output/'build-evidence/derivation.json')['sha256'],
   'dotnet-resource-metadata-only-material-required')
  stage='normal-fresh-package-validation'
  commands.run('metadata-normal-package',binaries['examples/package'],'build',artifact/'package-source.json',artifact,artifact/'package')
  commands.run('metadata-normal-package-inspect',binaries['examples/package'],'inspect',artifact/'package')
  expected={field:file_identity(artifact/name,16*1024**2) for field,name in (
   ('component','component.wasm'),('buildComplete','BUILD-COMPLETE.json'),
   ('buildObservation','build-observation.json'),('sourceInputs','source-inputs.json'))}
  record['freshMetadataBuild']=original_build(artifact,'dotnet',expected)
  stage='normal-sign-admit-two-tenant-programme'
  observed=qualify('dotnet',artifact,expected,native,producer,output/'coupled')
  require(observed['status']=='passed' and materials=={name:file_identity(ROOT/name) for name in MATERIALS}
   and native_proof==native_products(native,producer)[1]
   and subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,timeout=10).decode().strip()==source,
   'dotnet-resource-final-current-recipe-and-historical-products')
  record.update(status='passed',coupledReceipt=file_identity(output/'coupled/qualified.json'),commands=commands.records)
  write_workflow_receipt(output/'qualified.json',record);return record
 except BaseException as error:
  guard=error.args[0] if error.args and type(error.args[0]) is str and re.fullmatch(r'dotnet-resource-[A-Za-z0-9-]{1,120}',error.args[0]) else None
  record.update(status='failed',stage=stage,errorCategory=type(error).__name__,guard=guard)
  write_workflow_receipt(output/'FAILED.json',record);raise


if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__)
 for name in ('native','native-producer','output'):parser.add_argument('--'+name,type=Path,required=True)
 arguments=parser.parse_args()
 print(run(arguments.native.resolve(strict=True),read_json(arguments.native_producer),arguments.output.absolute())['status'])
