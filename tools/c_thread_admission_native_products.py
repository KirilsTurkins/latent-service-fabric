"""Immutable three-product admission overlay plus two original f625 products.

No tuple is repinned. Each binary retains its actual compiler source. The
assembled current-input view is a derived record with both original receipts.
"""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import re
import subprocess
import stat
import sys
import urllib.error
import urllib.request
import zipfile

if __package__ in {None,''}:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from tools import c_thread_package_native_products as inherited
from tools.java_replay_materials import api,git_source_identity,NoRedirect,Ranges,REPOSITORY
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT,digest,fresh,read_json,write_json
from tools.sdk_native_products_reader import FrozenNativeProducts,PRODUCTS,_identity,ALLOWED

# Freeze only after the actual successful origin has been independently retained.
SOURCE='f244b81f14abad5d4dc4984cb842aaf1d9076e23'
RUN=39645135536
JOB=119378576823
ARTIFACT={'id': 12367356857, 'size_in_bytes': 61993733, 'digest': 'sha256:e4cb1d108f96e8595bc9941ef5f7fb9dbedca356e08b396bf5f46b8065cc037c'}
RECEIPTS={'native-products.json': {'sha256': 'sha256:f0e8c6b7cae2ee68daff0d46f27de1ed3ebd12ecf1516173ac7e619b6c19cb44', 'bytes': 55570}, 'source-inputs.json': {'sha256': 'sha256:5dba7da494916696f503c9090ed6d0b99c11e72c005b2e54b722feb72bd20f67', 'bytes': 28650}}
WORKFLOW='.github/workflows/c-thread-admission-native.yml'
BRANCH='diag/c-thread-admission-native-20261021'
STAGES=('rust-version','normal-affected-products-build','normal-activation-configuration-controls',
    'closed-c-engine','closed-root-only','normal-defaults','go-provenance-profile-controls')
BUILT=('latent','latentd','examples/capsule_authoring')
INHERITED=('examples/package','examples/capsule_contracts')
CHANGED=('apps/latentd/src/config/derive.rs','apps/latentd/src/config/policy.rs',
    'apps/latentd/src/config/tests/providers/activation_runtime.rs',
    'crates/latent-signing/src/provenance/tests.rs','crates/latent-signing/src/provenance/validate.rs')


def _configuration():
    require(SOURCE!='0'*40,'c-admission-successful-origin-not-yet-frozen')
    return FrozenNativeProducts(source=SOURCE,run=RUN,job=JOB,artifact=ARTIFACT,receipts=RECEIPTS,
        branch=BRANCH,stages=STAGES,event='push',include_protocol=True)


def git_rows(revision,names):
    names=sorted(set(names))
    require(0<len(names)<=256 and all(type(n) is str
        and re.fullmatch(r'[A-Za-z0-9_./@+-]{1,512}',n)
        and all(p not in {'','.','..'} for p in n.split('/')) for n in names),
        'c-admission-bounded-git-material-paths')
    raw=subprocess.run(['git','cat-file','--batch'],cwd=ROOT,
        input=''.join(revision+':'+n+'\n' for n in names).encode(),
        stdout=subprocess.PIPE,check=True,timeout=60).stdout
    require(len(raw)<=8*1024**2,'c-admission-bounded-git-material-batch')
    rows={};at=0;total=0
    for name in names:
        end=raw.index(b'\n',at);header=raw[at:end].decode().split()
        require(len(header)==3 and header[1]=='blob','c-admission-original-git-blob')
        size=int(header[2]);at=end+1
        require(0<size<=1024**2 and at+size<len(raw),'c-admission-original-git-file-bound')
        body=raw[at:at+size];total+=size
        require(hashlib.sha1(b'blob '+str(size).encode()+b'\0'+body).hexdigest()==header[0]
            and raw[at+size:at+size+1]==b'\n' and total<=4*1024**2,
            'c-admission-original-git-body-identity')
        rows[name]={'sha256':digest(body),'bytes':size};at+=size+1
    require(at==len(raw),'c-admission-exact-original-git-batch')
    return rows


def validate_overlay(record,snapshot,native,old_native,original_materials,materials,changes):
    fields={'schemaVersion','sourceRevision','nativeSource','materials','profile','inheritedProducts',
        'productsBuilt','signedQualification','guestCompiled','backendCompiled','builtProductIdentities',
        'focusedControlsPassed','status','compiler','commands','products','nativeSourceAfter',
        'materialsAfter','elapsedSeconds'}
    require(type(record) is dict and set(record)==fields
        and record['schemaVersion']=='latent.sdk.native-product-overlay.v1'
        and record['status']=='passed' and record['sourceRevision']==SOURCE
        and record['nativeSource']==record['nativeSourceAfter']==native
        and record['materials']==record['materialsAfter']==materials
        and record['profile']=='normal-managed-guest-default-features'
        and record['signedQualification'] is False and record['guestCompiled'] is False
        and record['backendCompiled'] is False and record['focusedControlsPassed'] is True,
        'c-admission-exact-qualified-producer-not-guest')
    require(record['inheritedProducts']=={'sourceRevision':inherited.SOURCE,'nativeSource':old_native,
            'keys':list(INHERITED)} and record['productsBuilt']==list(BUILT)
        and type(record['products']) is dict and set(record['products'])==set(BUILT)
        and record['builtProductIdentities']==record['products']
        and all(_identity(row) for row in record['products'].values()),
        'c-admission-three-built-two-original-products')
    require(snapshot=={'native':native,'inheritedNativeSource':old_native,
            'inheritedRevision':inherited.SOURCE,'reviewedNativeChanges':changes,
            'allOtherNativeFilesByteExact':3320,'materials':materials}
        and set(native)==set(old_native)=={'sha256','files','bytes','scope','hermetic','implicitCompilerInputs'}
        and native['files']==old_native['files']==3325
        and native['scope']==old_native['scope']=='explicit-apps-crates-rust-sdk-workloads-and-workspace-inputs'
        and native['hermetic'] is False and old_native['hermetic'] is False
        and native['implicitCompilerInputs']==old_native['implicitCompilerInputs']=='not-attested'
        and type(snapshot['allOtherNativeFilesByteExact']) is int
        and set(original_materials)<=set(materials) and len(original_materials)==134
        and all(materials[n]==row for n,row in original_materials.items()),
        'c-admission-exact-current-input-view-and-f625-relationship')
    require(type(record['compiler']) is str and record['compiler'].startswith('rustc 1.97.1 (')
        and type(record['elapsedSeconds']) in (int,float) and math.isfinite(record['elapsedSeconds'])
        and 0<=record['elapsedSeconds']<=1320,'c-admission-original-compiler-and-total-bound')
    commands=record['commands']
    require(type(commands) is list and len(commands)==len(STAGES),'c-admission-exact-seven-commands')
    for row,stage in zip(commands,STAGES):
        require(type(row) is dict and set(row)=={'stage','exitCode','seconds'}
            and row['stage']==stage and type(row['exitCode']) is int and row['exitCode']==0
            and type(row['seconds']) in (int,float) and math.isfinite(row['seconds'])
            and 0<=row['seconds']<=1320,'c-admission-exact-successful-command')
    require(sum(row['seconds'] for row in commands)<=1320.001,'c-admission-original-total-command-bound')


def verify_overlay(prepared):
    config=_configuration();config.receipt_preimages(prepared)
    record=read_json(prepared/'native-products.json');snapshot=read_json(prepared/'source-inputs.json')
    native,old_native=git_source_identity(SOURCE),git_source_identity(inherited.SOURCE)
    require(old_native=={'sha256':'sha256:598ed59a0797ac24c006fe47162d74672b7a603669192e7019a83eced0a98d14',
        'files':3325,'bytes':26393594,'scope':'explicit-apps-crates-rust-sdk-workloads-and-workspace-inputs',
        'hermetic':False,'implicitCompilerInputs':'not-attested'},'c-admission-fixed-original-f625-source')
    paths=subprocess.check_output(['git','diff','--name-only',inherited.SOURCE,SOURCE,'--',
        'apps','crates','sdk/rust','tools/optimization-workloads','Cargo.toml','Cargo.lock',
        'rust-toolchain.toml','.cargo/config.toml'],cwd=ROOT,timeout=30).decode().splitlines()
    require(paths==list(CHANGED),'c-admission-only-reviewed-five-native-source-changes')
    old,new=git_rows(inherited.SOURCE,CHANGED),git_rows(SOURCE,CHANGED)
    changes={n:{'inherited':old[n],'compiled':new[n]} for n in CHANGED}
    original_materials=inherited.READER._git_materials()
    materials=git_rows(SOURCE,snapshot['materials'])
    validate_overlay(record,snapshot,native,old_native,original_materials,materials,changes)
    return record,snapshot,original_materials


def official_overlay():
    _configuration()
    run,job=api(f'actions/runs/{RUN}'),api(f'actions/jobs/{JOB}')
    require(run['id']==RUN and run['head_sha']==SOURCE and run['path']==WORKFLOW
        and run['head_branch']==BRANCH and run['event']=='push'
        and run['status']=='completed' and run['conclusion']=='success'
        and job['id']==JOB and job['run_id']==RUN and job['head_sha']==SOURCE
        and job['name']=='Build three affected products and check normal configuration and provenance'
        and job['status']=='completed' and job['conclusion']=='success',
        'c-admission-official-completed-overlay-origin')
    listing=api(f'actions/runs/{RUN}/artifacts?per_page=100')
    require(listing['total_count']==len(listing['artifacts'])<=100,'c-admission-no-artifact-pagination')
    selected=[a for a in listing['artifacts'] if a['name']=='c-thread-admission-native-'+SOURCE]
    require(len(selected)==1,'c-admission-one-original-overlay-artifact')
    artifact=selected[0]
    require(all(artifact[k]==v for k,v in ARTIFACT.items()) and artifact['expired'] is False
        and artifact['workflow_run']['id']==RUN and artifact['workflow_run']['head_sha']==SOURCE
        and artifact['workflow_run']['head_branch']==BRANCH
        and artifact['workflow_run']['repository_id']==artifact['workflow_run']['head_repository_id']==1337591365,
        'c-admission-exact-public-overlay-artifact')
    return artifact


def download(artifact,reader,output,products):
    output=fresh(output)
    token=os.environ.get('GH_TOKEN');require(bool(token),'c-admission-explicit-artifact-token')
    request=urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{artifact["id"]}/zip',
        headers={'Authorization':'Bearer '+token})
    try:urllib.request.build_opener(NoRedirect).open(request,timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code==302,'c-admission-original-official-redirect');url=error.headers['Location']
    else:raise ValueError('c-admission-official-redirect-required')
    require(url.startswith('https://'),'c-admission-https-artifact-only')
    remote=Ranges(url,artifact['size_in_bytes']);selected={}
    with zipfile.ZipFile(remote) as archive:
        names=archive.namelist();require(len(names)<=20000 and len(names)==len(set(names)),
            'c-admission-finite-archive-index')
        members=['native-products.json','source-inputs.json',
            *['native-binaries/'+n.replace('/','-') for n in products]]
        # Validate every fixed selected member before extracting any payload.
        for name in members:
            row=archive.getinfo(name)
            require(0<row.file_size<=ALLOWED[name] and not row.is_dir()
                and stat.S_IFMT(row.external_attr>>16) in (0,stat.S_IFREG),
                'c-admission-fixed-selected-member-bound')
            selected[name]={'bytes':row.file_size,'compressedBytes':row.compress_size}
        for name in members:reader.extract(archive,name,output/name)
    return {'artifact':artifact['id'],'archiveDigest':artifact['digest'],
        'wholeArchiveRetained':False,'archiveDigestVerification':'official-metadata-only-selected-members-hash-verified',
        'fixedMembersPreflighted':selected,'rangeBytes':remote.transferred,'rangeRequests':remote.requests}


def assembled(overlay,original,auxiliary):
    products={**original['products'],**overlay['products']}
    attribution={n:{'sourceRevision':SOURCE if n in BUILT else inherited.SOURCE,
        'nativeSource':overlay['nativeSource'] if n in BUILT else original['source'],
        'identity':products[n]} for n in PRODUCTS}
    source={'schemaVersion':'latent.sdk.composite-native-inputs.v1','native':overlay['nativeSource'],
        'materials':auxiliary,'perProductCompilation':attribution,
        'currentSourceDoesNotReattributeInheritedProducts':True}
    record={'schemaVersion':'latent.sdk.composite-native-products.v1','products':products,
        'perProductCompilation':attribution,'productsBuilt':list(BUILT),'productsInherited':list(INHERITED),
        'currentSourceRevision':SOURCE,'inheritedSourceRevision':inherited.SOURCE,
        'signedQualification':False,'guestComponentsCompiled':False}
    return record,source


def verify_prepared(prepared):
    prepared=Path(prepared)
    overlay,snapshot,auxiliary=verify_overlay(prepared/'overlay')
    inherited.READER.receipt_preimages(prepared/'inherited')
    original=read_json(prepared/'inherited/native-products.json')
    original_snapshot=read_json(prepared/'inherited/source-inputs.json')
    inherited.READER.validate_record(original,original_snapshot,git_source_identity(inherited.SOURCE),auxiliary)
    record,source=assembled(overlay,original,auxiliary)
    require(read_json(prepared/'native-products.json')==record
        and read_json(prepared/'source-inputs.json')==source,'c-admission-exact-derived-composite-records')
    for name,row in record['products'].items():
        require(file_identity(prepared/'native'/name.replace('/','-'),512*1024**2)==row,
            'c-admission-actual-product-identity')
    retained=read_json(prepared/'retrieval.json')
    require(retained['schemaVersion']=='latent.sdk.composite-native-retrieval.v1'
        and retained['currentSourceRevision']==SOURCE and retained['inheritedSourceRevision']==inherited.SOURCE
        and retained['producerRun']==RUN and retained['producerJob']==JOB
        and retained['overlayReceipts']==RECEIPTS and retained['inheritedReceipts']==inherited.RECEIPTS
        and retained['perProductCompilation']==record['perProductCompilation']
        and retained['overlayOrigin']['artifact']==ARTIFACT['id']
        and retained['overlayOrigin']['archiveDigest']==ARTIFACT['digest']
        and retained['inheritedOrigin']['artifact']==inherited.ARTIFACT['id']
        and retained['inheritedOrigin']['archiveDigest']==inherited.ARTIFACT['digest']
        and retained['signedQualification'] is False,'c-admission-frozen-composite-retrieval')
    return retained


def native_products(prepared):
    return inherited.READER.native_products(Path(prepared))


def prepare(output):
    require(sys.platform=='linux','c-admission-linux-products-only')
    output=fresh(Path(output))
    overlay_origin=download(official_overlay(),_configuration(),output/'overlay',BUILT)
    overlay,snapshot,auxiliary=verify_overlay(output/'overlay')
    inherited_origin=download(inherited.READER._official_artifact(),inherited.READER,output/'inherited',INHERITED)
    inherited.READER.receipt_preimages(output/'inherited')
    original=read_json(output/'inherited/native-products.json')
    inherited.READER.validate_record(original,read_json(output/'inherited/source-inputs.json'),
        git_source_identity(inherited.SOURCE),auxiliary)
    record,source=assembled(overlay,original,auxiliary)
    for name in PRODUCTS:
        directory=output/('overlay' if name in BUILT else 'inherited')
        raw=directory/'native-binaries'/name.replace('/','-');target=output/'native'/name.replace('/','-')
        target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        require(file_identity(raw,512*1024**2)==record['products'][name],
            'c-admission-before-copy-original-binary')
        # Copy only selected authenticated files; every output has one source.
        import shutil
        shutil.copyfile(raw,target);target.chmod(0o700)
        require(file_identity(raw,512*1024**2)==file_identity(target,512*1024**2)==record['products'][name],
            'c-admission-copy-original-binary-unchanged')
    write_json(output/'native-products.json',record);write_json(output/'source-inputs.json',source)
    result={'schemaVersion':'latent.sdk.composite-native-retrieval.v1','currentSourceRevision':SOURCE,
        'inheritedSourceRevision':inherited.SOURCE,'producerRun':RUN,'producerJob':JOB,
        'overlayReceipts':RECEIPTS,'inheritedReceipts':inherited.RECEIPTS,
        'perProductCompilation':record['perProductCompilation'],
        'overlayOrigin':overlay_origin,'inheritedOrigin':inherited_origin,'signedQualification':False}
    write_json(output/'retrieval.json',result)
    require(verify_prepared(output)==result,'c-admission-final-composite-recheck')
    return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    prepare(parser.parse_args().output)
