"""Authenticate the original88b guest and execute only its unchanged64-case plan."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import activation_stack_native_products as native
from tools import rust_wasi_http_runtime_fixture as fixture
from tools import rust_wasi_http_runtime_node as node
from tools import qualify_rust_wasi_http_runtime as original
from tools import rust_wasi_http_inputs as runtime
from tools.activation_stack_native_source import assert_current
from tools.java_replay_materials import api, git_source_identity
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, canonical, digest, fresh, inventory, read_file, read_json, snapshot, write_json

SOURCE='88b3c9c1d305eb8e308a7187600f782163bc6131'
RUN,JOB=39623507324,119302796812
PINS='docs/testing/evidence/rust-wasi-http-runtime-88b-retained.json'
NODE_PATH='tools/rust_wasi_http_runtime_node.py'
CURRENT_NODE={'sha256': 'sha256:ecc8ce33cdfcf709cd32b802b0abada8ed311cf5d0300097e86cca7c004fc25c', 'bytes': 73456}
MATERIALS=('tools/replay_rust_wasi_http_forbidden_runtime.py',PINS,
    '.github/workflows/rust-wasi-http-forbidden-replay.yml',*original.MATERIALS)


def git_files(names):
    names=sorted(set(names))
    require(0<len(names)<=512 and all(type(name) is str
        and re.fullmatch('[A-Za-z0-9_./@+-]{1,512}',name)
        and all(p not in {'','.','..'} for p in name.split('/')) for name in names),
        'rust-http-replay-bounded-original-git-paths')
    raw=subprocess.run(['git','cat-file','--batch'],cwd=ROOT,
        input=''.join(SOURCE+':'+n+'\n' for n in names).encode(),stdout=subprocess.PIPE,
        check=True,timeout=60).stdout
    require(len(raw)<=16*1024**2,'rust-http-replay-original-git-byte-bound')
    result={};at=0
    for name in names:
        end=raw.index(b'\n',at);header=raw[at:end].decode().split()
        require(len(header)==3 and header[1]=='blob','rust-http-replay-original-git-blob')
        size=int(header[2]);at=end+1
        require(0<=size<=4*1024**2 and at+size<len(raw),'rust-http-replay-original-git-file-bound')
        body=raw[at:at+size]
        require(hashlib.sha1(b'blob '+str(size).encode()+b'\0'+body).hexdigest()==header[0]
            and raw[at+size:at+size+1]==b'\n','rust-http-replay-original-git-identity')
        result[name]=body;at+=size+1
    require(at==len(raw),'rust-http-replay-exact-original-git-response')
    return result


def validate_origin(run,job,artifact,pins):
    branch='fix/rust-http-streamed-post-fixture-20261021'
    require(run['id']==RUN and run['head_sha']==SOURCE and run['head_branch']==branch
        and run['event']=='push' and run['path']=='.github/workflows/rust-wasi-http-streamed-post.yml'
        and run['status']=='completed' and run['conclusion']=='failure',
        'rust-http-replay-original-failed-outer-run')
    require(job['id']==JOB and job['run_id']==RUN and job['head_sha']==SOURCE
        and job['status']=='completed' and job['conclusion']=='failure',
        'rust-http-replay-original-failed-owning-job')
    require(all(artifact[k]==v for k,v in pins['artifact'].items()) and artifact['expired'] is False
        and artifact['name']=='rust-wasi-http-runtime-'+SOURCE
        and artifact['workflow_run']['id']==RUN and artifact['workflow_run']['head_sha']==SOURCE
        and artifact['workflow_run']['head_branch']==branch
        and artifact['workflow_run']['repository_id']==artifact['workflow_run']['head_repository_id']==1337591365,
        'rust-http-replay-exact-original-public-artifact')


def source_binding(previous,recipe):
    expected=git_files([*previous,*recipe])
    changes=[]
    for name,row in previous.items():
        body=expected[name]
        require(row=={'sha256':digest(body),'bytes':len(body)},'rust-http-replay-original-executed-source')
    for name,row in recipe.items():
        body=expected[name]
        require(row=={'digest':digest(body),'size':len(body)},'rust-http-replay-original-compiler-recipe')
    for name,body in expected.items():
        current=file_identity(ROOT/name)
        if current=={'sha256':digest(body),'bytes':len(body)}:
            continue
        require(name==NODE_PATH and current==CURRENT_NODE and name not in recipe,
            'rust-http-replay-only-exact-reviewed-reader-delta')
        changes.append({'name':name,'originalCompiledProgrammeReader':{'sha256':digest(body),'bytes':len(body)},
            'currentReader':current,'reason':'exact source-authenticated Waki/Golem HeaderError and ErrorCode formatting plus compact aggregate references; original phases/flags/variants/details/caps retained',
            'guestCompilerOrBackendChanged':False})
    require(len(changes)==1,'rust-http-replay-exact-required-reader-correction')
    return {'originalExecutedMaterials':len(previous),'originalRecipeRows':len(recipe),
        'allOriginalInputsGitExact':True,'currentReaderDelta':changes,
        'originalGuestCompilationSource':SOURCE,'currentGuestCompilationClaimed':False}


def public_wit_identity(raw,source,packaged):
    identity={'digest':digest(raw),'size':len(raw)}
    require(identity==source==packaged,
        'rust-http-replay-public-wit-exact-original-source-and-package-byte-binding')
    return identity


def artifact_inventory(directory):
    # The normal source snapshot ceiling intentionally excludes the 21MiB
    # composer retained in this public artifact. Keep its own finite inventory.
    values={};total=0
    for index,path in enumerate(directory.rglob('*')):
        require(index<2048 and not path.is_symlink(),'rust-http-replay-restored-entry-bound')
        if path.is_dir():continue
        name=path.relative_to(directory).as_posix()
        require(path.is_file() and len(values)<1024 and ':' not in name,
            'rust-http-replay-restored-regular-file')
        row=file_identity(path,32*1024**2);total+=row['bytes']
        require(total<=128*1024**2,'rust-http-replay-restored-total-byte-bound')
        values[name]={'digest':row['sha256'],'size':row['bytes']}
    return values


def restore(restored,output):
    pins=read_json(ROOT/PINS,1024**2)
    require(pins['source']==SOURCE and pins['run']==RUN and pins['job']==JOB and len(pins['members'])==420,
        'rust-http-replay-fixed-origin-inventory')
    before=artifact_inventory(restored)
    require(before==pins['members'],'rust-http-replay-all-original420-member-identities')
    validate_origin(api(f'actions/runs/{RUN}'),api(f'actions/jobs/{JOB}'),
        api(f'actions/artifacts/{pins["artifact"]["id"]}'),pins)
    root=restored/'rust-http-runtime-qualification'
    build=root/'build';failed=read_json(root/'FAILED.json',16*1024**2)
    require(failed['status']=='failed' and failed['source']==SOURCE
        and failed['stage']=='actual-signed-two-client-and-tenant-programme',
        'rust-http-replay-original-compile-pass-runtime-failure')
    binding=source_binding(failed['materials'],read_json(build/'recipe-inputs.json',8*1024**2))
    current=read_json(root/'current-build.json',16*1024**2)
    marker=read_json(build/'BUILD-COMPLETE.json')
    require(current['marker']==marker and marker['packageAssembled'] is True
        and marker['observationDigest']==digest(read_file(build/'build-observation.json'))
        and marker['componentDigest']==digest(read_file(build/'component.wasm',64*1024**2))
        and marker['sourceDigest']==digest(read_file(build/'source-inputs.json'))
        and len(marker['commands'])==34 and all(type(r['exitCode']) is int and r['exitCode']==0
            for r in marker['commands']), 'rust-http-replay-original-successful-compiler-and-marker')
    require(current['component']==file_identity(build/'component.wasm',64*1024**2)
        and current['source']==file_identity(build/'source-inputs.json')
        and current['recipe']==file_identity(build/'recipe-inputs.json')
        and current['observation']==file_identity(build/'build-observation.json'),
        'rust-http-replay-original-observed-identities')
    original.verify_executable_outputs(read_json(build/'executable-input-outputs.json',32*1024**2),
        read_json(build/'executable-input-approval-request.json',8*1024**2),marker['commands'])
    adapter=restored/'rust-http-original/rust-http-current-backend'
    require(all(file_identity(adapter/name,64*1024**2)==row for name,row in pins['backendMaterials'].items())
        and len(pins['backendMaterials'])==7
        and file_identity(build/'rust-http-runtime.json')==pins['backendMaterials']['INSTALL-COMPLETE.json'],
        'rust-http-replay-original-current110-adapter-materials')
    receipt=read_json(build/'rust-http-runtime.json')
    runtime._bounded_record(receipt)
    source_rows=read_json(adapter/'source-inputs.json')
    require(len(source_rows)==receipt['sourceRows']==110
        and digest(read_file(adapter/'source-inputs.json'))==receipt['sourceDigest'],
        'rust-http-replay-original-current110-adapter-source-inventory')
    original_sources=git_files(source_rows)
    require(all(row=={'digest':digest(original_sources[name]),'size':len(original_sources[name])}
        for name,row in source_rows.items()),'rust-http-replay-all110-adapter-producer-git-preimages')
    original.verify_composition(read_json(build/'rust-http-composition.json'),
        read_file(build/'component.wasm',64*1024**2),read_json(build/'rust-http-runtime.json'))
    target=output/'build'
    shutil.copytree(build,target)
    package=read_json(target/'package-source.json')
    sources=read_json(target/'source-inputs.json',8*1024**2)
    packaged=read_json(target/'package-inputs.json',8*1024**2)
    missing=[row['source'] for row in package['layers'] if not (target/row['source']).exists()]
    require(set(missing)=={'wit/world.wit','wit/deps/clock-monotonic/package.wit',
        'wit/deps/http/package.wit','wit/deps/runtime/package.wit'} and len(missing)==4,
        'rust-http-replay-exact-four-public-wit-restorations')
    app,_outside,_specs=fixture.prepare(output/'public-wit-generation','0000000000000000')
    restored_wit={}
    for name in missing:
        raw=read_file(app/name);identity=public_wit_identity(raw,sources[name],packaged[name])
        path=target/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        restored_wit[name]=identity
    files={'package-source.json':read_file(target/'package-source.json')}
    for row in package['layers']:
        files[row['source']]=read_file(target/row['source'],64*1024**2)
    require(inventory(files)==read_file(target/'package-inputs.json',8*1024**2)
        and artifact_inventory(restored)==before,'rust-http-replay-original-package-materials-restored-verbatim')
    return target,{'sourceBinding':binding,'originalOuterConclusion':'failure','originalRun':RUN,
        'originalJob':JOB,'artifact':pins['artifact'],'originalMemberIdentities':420,
        'originalBuildComplete':file_identity(target/'BUILD-COMPLETE.json'),
        'originalComponent':file_identity(target/'component.wasm',64*1024**2),
        'publicWitRestoration':restored_wit,'restorationSource':'unchanged maintained fixture.prepare; no capture or compiler',
        'originalBuildObservationRewritten':False,'originalPackageInputsRewritten':False,
        'originalCompilerSource':SOURCE,'guestCompilationPerformed':False}


def replay(restored,native_directory,output,*,pressure_observation_only=False):
    require(type(pressure_observation_only) is bool,'rust-http-replay-exact-pressure-diagnostic-selection')
    require(sys.platform=='linux' and sys.version_info>=(3,13),'rust-http-replay-linux-python313')
    output=Path(output).absolute();restored=Path(restored).resolve(strict=True)
    native_directory=Path(native_directory).resolve(strict=True)
    require(output!=ROOT and ROOT not in output.parents and output not in ROOT.parents
        and all(p!=output and p not in output.parents and output not in p.parents
            for p in (restored,native_directory)),'rust-http-replay-fresh-separated-output')
    output=fresh(output);deadline=time.monotonic()+1100
    materials={name:file_identity(ROOT/name) for name in dict.fromkeys(MATERIALS)}
    record={'schemaVersion':'latent.rust.wasi-http.node-replay.v1','status':'incomplete','materials':materials,
        'controllerSource':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,timeout=10).decode().strip(),
        'guestComponentsCompiled':0,'nativeProductsBuilt':0,'backendComponentsBuilt':0,'fullTicketQualification':False}
    if pressure_observation_only:
        record.update(qualification=False,signedQualification=False,diagnosticOnly=True)
    stage='authenticate-original-compile-and-restore-public-package-assets'
    try:
        artifact,ancestry=restore(restored,output);record['original']=ancestry
        record['nativeProducer']=native.verify_prepared(native_directory)
        source_proof=assert_current(ROOT)
        require(source_proof['compiledSourceRevision']==native.SOURCE,
            'rust-http-replay-original-native-producer-binding')
        record['nativeSourceCompatibility']=source_proof
        native_inputs=read_json(native_directory/'source-inputs.json')
        record['nativeAuxiliaryCompatibility']=original.native_compatibility(native_inputs['materials'],
            {name:file_identity(ROOT/name) for name in native_inputs['materials']})
        binaries=native.native_products(native_directory)
        for path in binaries.values():path.chmod(0o700)
        write_json(output/'original-compile-and-restoration.json',ancestry)
        stage='original-full64-node-programme'
        result=node.run(artifact,binaries,output/'node',deadline=deadline,
            pressure_observation_only=pressure_observation_only)
        if pressure_observation_only:
            require(result['status']=='diagnostic-completed' and result['qualification'] is False
                and result['diagnosticOnly'] is True and len(result['cases'])==1
                and result['guestExecutions']==result['invocationAttempts']==1,
                'rust-http-replay-pressure-observation-never-qualification')
        else:require(result['status']=='passed' and len(result['cases'])==52
            and result['guestExecutions']==53 and result['invocationAttempts']==64
            and result['preEntryRefusalsCount']==11 and len(result['preEntryRefusals'])==8
            and result['providerAbsence']['status']=='passed' and len(result['providerAbsence']['invocations'])==2,
            'rust-http-replay-every-original-owning-case-required')
        require(record['nativeProducer']==native.verify_prepared(native_directory)
            and source_proof==assert_current(ROOT)
            and materials=={name:file_identity(ROOT/name) for name in materials}
            and time.monotonic()<deadline,'rust-http-replay-final-source-product-and-deadline')
        if pressure_observation_only:
            record.update(status='diagnostic-completed',node=file_identity(output/'node/diagnostic.json',16*1024**2))
            write_json(output/'diagnostic.json',record);return record
        record.update(status='passed',node=file_identity(output/'node/qualification.json',16*1024**2),
            libraryCases=52,guestExecutions=53,invocationAttempts=64,preEntryRefusals=11,signedQualification=True)
        write_json(output/'qualification.json',record);return record
    except BaseException:
        record.update(status='failed',stage=stage)
        try:write_json(output/'FAILED.json',record)
        except OSError:pass
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('original-artifact','native-products','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--pressure-observation-only',action='store_true',
        help='One original Golem capacity call; diagnostic evidence only, never qualification')
    args=parser.parse_args()
    print(replay(args.original_artifact,args.native_products,args.output,
        pressure_observation_only=args.pressure_observation_only)['status'])
