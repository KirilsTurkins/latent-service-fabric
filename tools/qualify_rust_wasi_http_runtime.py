"""One current captured ordinary two-client guest, normal signing and real HTTP.

The immutable native producer is authenticated independently of the selected
unlinked frontend/guest recipe. No compiler receipt is rebound to that producer.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import re
from pathlib import Path
import secrets
import subprocess
import sys
import time
import tomllib

if __package__ in {None,''}:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from tools import rust_wasi_http_runtime_fixture as fixture, rust_wasi_http_runtime_node as node
from tools import rust_wasi_http_inputs as runtime
from tools import rust_wasi_http_backend_products as backend
from tools.application_dependencies import verify_inputs
from tools.build_observation import build_environment, resolve_tools
from tools.java_replay_materials import git_source_identity
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_rust_capsules import source_identity
from tools.qualify_rust_wasi_http_inputs import execution_request
from tools.rust_capsule_build import RECIPE, build
from tools.rust_capsule_project import ROOT, canonical, digest, fresh, inventory, read_file, read_json, snapshot, write_json
from tools.rust_wasi_http_profile import AUTHORITY, PROFILE
from tools.dotnet_guest.internal_io import core_modules

NATIVE_SOURCE='6fd19eab2c224fc31481d03de5008de4d3e4429e'
# Only this unlinked frontend was extended for explicit standard-WASI composition.
# Original compiled native3318 and every other auxiliary/API/WIT byte stay exact.
# These are reviewed byte pairs, never a pathname-only or arbitrary-hash waiver.
FRONTEND={
    'tools/rust_capsule_build.py':(
        {'sha256':'sha256:a00cb2afce425556cc0a9a776c5a23f757c3012f3440eda6c0e1cc709e0a2948','bytes':45923},
        {'sha256':'sha256:ab843105bee16373938d1f68f24a60bcdf4326e2ea21bf0c5d48794c4e77ba48','bytes':47118}),
}
MATERIALS=('tools/qualify_rust_wasi_http_runtime.py','tools/rust_wasi_http_runtime_fixture.py',
    'tools/rust_wasi_http_fixture.py','tools/rust_wasi_http_runtime_node.py','tools/qualify_rust_wasi_http_inputs.py',
    'tools/release_preparation_cli_native_products.py','tools/sdk_native_products_reader.py',
    'tools/rust_wasi_http_backend_products.py',
    'tools/java_replay_materials.py','tools/qualify_rust_capsules.py',
    'tools/install_guest_bindgen.py','tools/toolchain.toml',*node.MATERIALS)


def native_compatibility(original,current):
    require(type(original) is dict and len(original)==134 and set(current)==set(original),
        'rust-http-exact-original-native-auxiliary-set')
    changes=[]
    for name,previous in original.items():
        selected=current[name]
        if previous==selected:continue
        require(name in FRONTEND and (previous,selected)==FRONTEND[name],
            'rust-http-unreviewed-native-auxiliary-change')
        changes.append({'name':name,'compiledProducerInput':previous,'currentUnlinkedFrontend':selected,
            'linkedIntoNativeProducts':False,'reason':'explicit maintained standard-WASI runtime selection/composition'})
    require(set(row['name'] for row in changes)==set(FRONTEND),
        'rust-http-exact-reviewed-selected-frontend-required')
    return {'compiledNativeSourceUnchanged':True,'auxiliaryRows':134,
        'unchangedAuxiliaryRows':134-len(changes),'unlinkedFrontendChanges':changes,
        'allAuxiliaryRowsCurrentAtProducerCompilation':False}


def verify_composition(record,component,adapter):
    require(record['schemaVersion']=='latent.rust.http.exact-composition.v1'
        and record['profile']==PROFILE and record['publicGraphUnchanged'] is True
        and record['librarySourceRewritten'] is False and record['signedExecutionQualification'] is False
        and record['selectedComponentDigest']==digest(component)
        and record['explicitAsyncPublicContract']==[{'interface':'examples:greeting/api@1.0.0',
            'function':'greet','kind':'async-freestanding'}]
        and record['compilerRootRustBindingsAsync'] is False
        and record['forwardingRootApplicationImportsExact'] is True
        and record['imports']==sorted(AUTHORITY) and record['exports']==['examples:greeting/api@1.0.0'],
        'rust-http-normal-compiler-owned-root-and-private-drain')
    app=record['internalIo'];root=record['privateDrain']
    require(app['root'] is False and root['root'] is True
        and all(item['coreBytesUnchanged'] is True and item['publicApplicationGraphUnchanged'] is True
            and item['runtimeQualification'] is False for item in (app,root))
        and type(record['originalCoreModulesRetained']) is int
        and record['originalCoreModulesRetained']==len(app['cores'])>0,
        'rust-http-exact-internal-projection-core-proof')
    actual=Counter((digest(body),len(body)) for body in core_modules(component))
    # WAC may reuse one identical core definition across composed namespaces.
    # Preserve each original namespace's own multiset, not an invented sum of
    # otherwise identical definitions across those independent namespaces.
    required=Counter((row['sha256'],row['bytes']) for row in app['cores'])
    required |= Counter((row['sha256'],row['bytes']) for row in root['cores'])
    required |= Counter((row['digest'],row['size']) for row in adapter['cores'])
    require(not (required-actual),'rust-http-all-original-app-root-adapter-cores-required')


def catalogue_inputs(source,recipe,installed_sdk):
    require(type(source) is dict and type(recipe) is dict and source and recipe
        and all(type(name) is str and name and '\\' not in name and not name.startswith('/')
            and all(part not in {'','.','..'} for part in name.split('/'))
            for names in (source,recipe) for name in names),'rust-http-real-observed-input-name-sets')
    require(type(installed_sdk) is dict and installed_sdk
        and {'vendor/lsf/'+name for name in installed_sdk}=={n for n in source if n.startswith('vendor/lsf/')}
        and all(source['vendor/lsf/'+name]==value for name,value in installed_sdk.items()),
        'rust-http-full-actual-captured-sdk-manifest-required')
    def catalogue(name):
        return any(part in {'compatibility-catalogue','catalogue.json'} for part in name.split('/'))
    observed=[{'origin':kind,'name':name} for kind,names in (('captured-source',source),('recipe',recipe))
        for name in sorted(names) if catalogue(name)]
    require(not observed,'rust-http-catalogue-data-is-not-an-application-or-recipe-input')
    return {'scope':'actual captured application/SDK source and full selected recipe; repository publication data is not removed',
        'sourceInputNames':sorted(source),'recipeInputNames':sorted(recipe),
        'sdkInputNames':{'captured-source':sorted('vendor/lsf/'+n for n in installed_sdk),
            'recipe':[n for n in sorted(recipe) if n.startswith('sdk/')]},
        'sdkLockInput':source['sdk-lock.json'],
        'catalogueDataInputs':observed,'repositoryPublicationDataDeleted':False,
        'proof':'complete actual source-inputs.json and recipe-inputs.json names, both bound to current bytes'}


def verify_executable_outputs(outputs, approval, commands):
    from tools.rust_capsule_build import MAX_EXECUTABLE_OUTPUT_BYTES, MAX_EXECUTABLE_OUTPUT_FILES
    require(type(outputs) is dict and set(outputs)=={'formatVersion','approvalIdentity','cleanup','hermetic','outputs'}
        and type(outputs['formatVersion']) is int and outputs['formatVersion']==1
        and outputs['approvalIdentity']==approval['identity']
        and outputs['cleanup']=='namespace-and-owned-process-reaped' and outputs['hermetic'] is False,
        'rust-http-real-executable-output-receipt')
    rows=outputs['outputs']
    require(type(rows) is dict and 0<len(rows)<=MAX_EXECUTABLE_OUTPUT_FILES,
        'rust-http-executable-output-file-bound')
    total=0
    for name,row in rows.items():
        require(type(name) is str and 0<len(name)<=4096 and '\\' not in name
            and all(part not in {'','.','..'} for part in name.split('/'))
            and type(row) is dict and set(row)=={'digest','size'}
            and type(row['digest']) is str and re.fullmatch('sha256:[0-9a-f]{64}',row['digest']) is not None
            and type(row['size']) is int and 0<=row['size']<=MAX_EXECUTABLE_OUTPUT_BYTES,
            'rust-http-executable-output-identity')
        total+=row['size']
        require(total<=MAX_EXECUTABLE_OUTPUT_BYTES,'rust-http-executable-output-byte-bound')
    require(type(commands) is list and all(type(row) is dict for row in commands),
        'rust-http-original-compiler-command-records')
    actual=[row for row in commands if row.get('stage')=='compile']
    require(len(actual)==1 and type(actual[0].get('exitCode')) is int and actual[0]['exitCode']==0,
        'rust-http-original-compiler-command-success')


def verify_build(artifact,app,captured,approval,prepared):
    require(read_file(artifact/'source-inputs.json')==captured
        and inventory(snapshot(app))==captured and verify_inputs(app,'rust') is not None,
        'rust-http-exact-current-captured-application')
    marker=read_json(artifact/'BUILD-COMPLETE.json')
    require(marker['observationDigest']==digest(read_file(artifact/'build-observation.json')),
        'rust-http-normal-build-observation-marker')
    outputs=read_json(artifact/'executable-input-outputs.json',32*1024**2)
    verify_executable_outputs(outputs,approval,marker['commands'])
    require(read_json(artifact/'executable-input-approval-request.json',8*1024**2)==approval,
        'rust-http-retained-executable-approval-changed')
    recipe=read_json(artifact/'recipe-inputs.json',8*1024**2)
    selected=runtime.consumer_files()
    require(selected.keys()<=recipe.keys() and all(recipe[name]=={'digest':digest(body),'size':len(body)}
        for name,body in selected.items()),'rust-http-all-current-selected-consumer-recipe')
    for name,value in recipe.items():
        body=read_file(ROOT/name)
        require(value=={'digest':digest(body),'size':len(body)},'rust-http-normal-recipe-source-drift')
    capsule=read_json(artifact/'capsule.json')
    require(capsule['metadata']=={'name':'examples/'+fixture.SERVICE,'tenant':'examples'}
        and capsule['exports']==['examples:greeting/api@1.0.0']
        and {r['contract'] for r in capsule['imports']}==AUTHORITY
        and len(capsule['imports'])==3 and all(r['optional'] is False for r in capsule['imports']),
        'rust-http-exact-public-contract-and-declared-authority')
    require(read_file(artifact/'rust-http-runtime.json')==prepared.material(),
        'rust-http-original-compiled-adapter-material-not-rebound')
    composition=read_json(artifact/'rust-http-composition.json')
    verify_composition(composition,read_file(artifact/'component.wasm',64*1024**2),prepared.value)
    require(read_json(artifact/'cargo-inputs.json')['networkResolution'] is False,
        'rust-http-normal-offline-captured-cargo-required')
    return {'marker':marker,'observation':file_identity(artifact/'build-observation.json'),
        'catalogueInputs':catalogue_inputs(json.loads(captured),recipe,read_json(app/'sdk-lock.json')['sdk']),
        'source':file_identity(artifact/'source-inputs.json'),'recipe':file_identity(artifact/'recipe-inputs.json'),
        'composition':composition,'component':file_identity(artifact/'component.wasm',64*1024**2)}


def qualify(native_directory,adapter_directory,output):
    # This one owning lane uses actual emitted guest code. Refuse on Windows
    # before fresh output, executable approval or any tool/network operation.
    require(sys.platform=='linux' and sys.version_info>=(3,13),'rust-http-runtime-linux-python313')
    from tools import release_preparation_cli_native_products as products
    require(products.SOURCE==NATIVE_SOURCE,'rust-http-exact-current-native-producer')
    native_directory=Path(native_directory).resolve(strict=True)
    adapter_directory=Path(adapter_directory).resolve(strict=True)
    output=Path(output).absolute()
    require(ROOT!=output and ROOT not in output.parents and output not in ROOT.parents
        and all(output!=p and output not in p.parents and p not in output.parents
            for p in (native_directory,adapter_directory)),'rust-http-separated-owned-output')
    output=fresh(output);deadline=time.monotonic()+1100
    original_native=products.verify_prepared(native_directory)
    binaries=products.native_products(native_directory)
    for path in binaries.values():path.chmod(0o700)
    before=source_identity(ROOT)
    require(before==git_source_identity(products.SOURCE),'rust-http-original-3318-native-source')
    original_inputs=read_json(native_directory/'source-inputs.json')
    require(original_inputs['native']==before,'rust-http-authenticated-compiled-native-identity')
    aux_current={name:file_identity(ROOT/name) for name in original_inputs['materials']}
    compatibility=native_compatibility(original_inputs['materials'],aux_current)
    adapter_origin=backend.verify(adapter_directory)
    (adapter_directory/'component-composer/wac').chmod(0o700)
    tools,_identities=resolve_tools(tomllib.loads(read_file(ROOT/'tools/toolchain.toml').decode()),ROOT,build_environment(output))
    prepared=runtime.Prepared(adapter_directory,tools['rustc'],tools['wasm-tools'])
    names=dict.fromkeys((*RECIPE,*MATERIALS,*runtime.consumer_files()))
    materials={name:file_identity(ROOT/name) for name in names}
    native_files={name:file_identity(path,512*1024**2) for name,path in binaries.items()}
    record={'schemaVersion':'latent.rust.wasi-http.runtime-qualification.v1','status':'incomplete',
        'source':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,timeout=10).decode().strip(),
        'nativeProducer':original_native,'compiledNativeSource':before,'nativeAuxiliaryCompatibility':compatibility,
        'materials':materials,'nativeProducts':native_files,'adapterProducer':prepared.value,
        'adapterProducerOrigin':adapter_origin,
        'freshApplicationComponentsCompiled':0,'nativeProductsBuilt':0,'libraryCodePatched':False,
        'applicationTransportInjected':False,'fullTicketQualification':False}
    stage='normal-unseen-two-client-source-capture'
    try:
        app,outside,specs=fixture.prepare(output/'source',secrets.token_hex(8))
        record['capture']=fixture.capture(app,outside,specs,tools['cargo'])
        write_json(output/'capture.json',record['capture'])
        captured=inventory(snapshot(app));record['capturedSourceDigest']=digest(captured)
        arguments=(binaries['capsule_contracts'],binaries['package'],
            'https://github.com/KirilsTurkins/latent-service-fabric')
        denied=output/'approval-required';stage='exact-unapproved-executable-refusal'
        try:build(app,denied,*arguments,offline=True,http_runtime=adapter_directory)
        except ValueError:approval=execution_request(denied,app)
        else:raise ValueError('rust-http-unapproved-executable-closure-ran')
        require(len(approval['specification']['executableInputs'])==16,
            'rust-http-exact-captured-16-executable-inputs')
        record['executableApproval']=approval
        stage='one-fresh-offline-ordinary-guest-with-compiler-root'
        artifact=build(app,output/'build',*arguments,offline=True,
            executable_approval=approval['identity'],http_runtime=adapter_directory)
        record['build']=verify_build(artifact,app,captured,approval,prepared)
        record['freshApplicationComponentsCompiled']=1
        write_json(output/'current-build.json',record['build'])
        stage='actual-signed-two-client-and-tenant-programme'
        execution=node.run(artifact,binaries,output/'node',deadline=deadline)
        require(execution['status']=='passed' and len(execution['cases'])==52
            and len(execution['preEntryRefusals'])==8 and execution['providerAbsence']['status']=='passed'
            and len(execution['providerAbsence']['invocations'])==2
            and execution['guestExecutions']==53 and execution['invocationAttempts']==64
            and execution['preEntryRefusalsCount']==11,'rust-http-all-original-owning-cases-required')
        record['node']=file_identity(output/'node/qualification.json',16*1024**2)
        prepared.check()
        require(original_native==products.verify_prepared(native_directory)
            and before==source_identity(ROOT) and aux_current=={n:file_identity(ROOT/n) for n in aux_current}
            and native_files=={n:file_identity(p,512*1024**2) for n,p in binaries.items()}
            and materials=={n:file_identity(ROOT/n) for n in materials}
            and inventory(snapshot(app))==captured and time.monotonic()<deadline,
            'rust-http-final-original-native-current-guest-and-recipe')
        record.update(status='passed',ordinaryLibraryCases=52,guestExecutions=53,invocationAttempts=64,preEntryRefusals=11,
            publisherAuthenticated=False,hermetic=False,signedQualification=True)
        write_json(output/'qualification.json',record);return record
    except BaseException:
        record.update(status='failed',stage=stage)
        try:write_json(output/'FAILED.json',record)
        except OSError:pass
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-products',type=Path,required=True)
    parser.add_argument('--http-runtime',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(qualify(args.native_products,args.http_runtime,args.output)['status'])
