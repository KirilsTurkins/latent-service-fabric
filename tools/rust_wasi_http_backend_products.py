"""Authenticate one successful compiled adapter restored by the artifact action.

This is a compiled-backend producer, never native/guest/signed qualification.
The owning workflow restores the fixed artifact; selected executable/material
bytes are independently pinned here before normal Prepared validation or use.
"""
from pathlib import Path

from tools.java_replay_materials import api
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import read_json

SOURCE='a6ec444c8cafe7380f6ae0e08016446ef80a6aba'
RUN=39524005962
JOB=118974299096
ARTIFACT={'id':12311439115,'size_in_bytes':8216300,
    'digest':'sha256:401f84f05f6a8a5ff8cecbf1b0788d0b9f456a92b6a475e4a7c502795556f7a8'}
RECEIPTS={
    'INSTALL-COMPLETE.json':{'sha256':'sha256:15a80a784ef5d79fa8fb51dc43c892bb95e7199e340e7e1c4ac614372fe313f5','bytes':4443},
    'source-inputs.json':{'sha256':'sha256:39fd5a05c6e1edb6a62db5ca8011daea1b93545c57d4df412abc5db98c5d4991','bytes':14791},
}


def validate_origin(run,job,artifact):
    branch='feat/rust-wasi-http-profile-20261021'
    require(run['id']==RUN and run['head_sha']==SOURCE and run['head_branch']==branch
        and run['event']=='push' and run['path']=='.github/workflows/rust-wasi-http-runtime.yml'
        and run['status']=='completed' and run['conclusion']=='success',
        'rust-http-backend-exact-successful-workflow-origin')
    require(job['id']==JOB and job['run_id']==RUN and job['head_sha']==SOURCE
        and job['status']=='completed' and job['conclusion']=='success',
        'rust-http-backend-exact-successful-owning-job')
    require(all(artifact[key]==value for key,value in ARTIFACT.items()) and artifact['expired'] is False
        and artifact['name']=='rust-wasi-http-backend-'+SOURCE
        and artifact['workflow_run']['id']==RUN and artifact['workflow_run']['head_sha']==SOURCE
        and artifact['workflow_run']['head_branch']==branch
        and artifact['workflow_run']['repository_id']==artifact['workflow_run']['head_repository_id']==1337591365,
        'rust-http-backend-exact-public-artifact-origin')
    return {'source':SOURCE,'run':RUN,'job':JOB,'artifact':dict(ARTIFACT),
        'qualification':'compiled-adapter-only','nativeProductsBuilt':False,
        'guestComponentsCompiled':False,'signedQualification':False}


def verify_materials(directory):
    directory=Path(directory).resolve(strict=True)
    require(all(file_identity(directory/name)==value for name,value in RECEIPTS.items()),
        'rust-http-backend-original-receipt-byte-identity')
    receipt=read_json(directory/'INSTALL-COMPLETE.json')
    require(receipt['sourceRows']==110 and receipt['sourceDigest']==RECEIPTS['source-inputs.json']['sha256']
        and receipt['qualification']=='compiled-adapter-only' and receipt['signedQualification'] is False,
        'rust-http-backend-original-producer-scope')
    names={'rust-wasi-http-runtime.wasm','raw-runtime.wasm','reference.wit.json','adapter.wit.json'}
    require(set(receipt['files'])==names,'rust-http-backend-exact-restored-file-set')
    for name,value in receipt['files'].items():
        require(file_identity(directory/name)=={'sha256':value['digest'],'bytes':value['size']}
            and value['name']==name,'rust-http-backend-exact-selected-material')
    wac=directory/'component-composer/wac';value=receipt['tools']['component-composer']
    require(file_identity(wac)=={'sha256':value['digest'],'bytes':value['size']},
        'rust-http-backend-original-pinned-composer')
    return {'receipts':dict(RECEIPTS),'files':receipt['files'],'composer':value,
        'producerReceiptRewritten':False,'newBackendCompilation':False}


def verify(directory):
    # API metadata is public. gh keeps its read token outside compiler children;
    # build_environment constructs the separate closed child environment.
    origin=validate_origin(api(f'actions/runs/{RUN}'),api(f'actions/jobs/{JOB}'),
        api(f'actions/artifacts/{ARTIFACT["id"]}'))
    origin['selectedMaterials']=verify_materials(directory)
    return origin
