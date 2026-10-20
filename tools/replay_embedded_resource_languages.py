"""Fresh Rust/TypeScript resource greetings with separately authenticated ancestry."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

if __package__ in {None,''}:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from tools.go_entropy_replay_inputs import NoRedirect, Remote
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_embedded_resources import HELPERS, campaign
from tools.qualify_sdk_scratch import package_identity
from tools import replay_go_embedded_resources as native
from tools.rust_capsule_project import ROOT, TEMPLATES, digest, fresh, read_file, read_json, write_json

SPECS = {
    'rust':{
        'artifact':12236803645,'run':39358494292,
        'head':'38fedd53bb8fc366a9078a3182d88cc03cf0835b',
        'name':'rust-scratch-prepared-38fedd53bb8fc366a9078a3182d88cc03cf0835b',
        'archiveBytes':67440658,'archiveDigest':'sha256:940f883666cb2746e1047441752d8a6534ed12c3fa1f4fbb8673c5159bac0b37',
        'prefix':'','normalCalls':27,'physical':24,'idle':6,'capturedDependencies':False,
        'qualification':'sha256:87b5664bcca6db0622e2407bf047f3ed30c1f406008370a4ac2cf7a0655fdb9d',
        'source':'sha256:3677ec116d9e47ca3b96542f274b995dd202ba5ff959e7d642afc510d52fbab6',
        'node':'sha256:7727e47ee556712a6cc111aca7dc5ad750060294839c42a2dfe4d3890bcd59d9'},
    'typescript':{
        'artifact':12222984675,'run':39319524998,
        'head':'02fbe2f9ed5c2cec6f568ebc7cce99216a12631e',
        'compiledMerge':'2cd6bb0d1ca39e3205ef0cf6296170fcab4005fe',
        'name':'typescript-guest-runtime-2cd6bb0d1ca39e3205ef0cf6296170fcab4005fe',
        'archiveBytes':549151088,'archiveDigest':'sha256:c41c91f9bdde135c63b4b410463987c00ea0ec59a29b7a544c2fd0a529165f41',
        'prefix':'_temp/typescript-capsule-dependencies/','normalCalls':30,'physical':27,'idle':9,'capturedDependencies':True,
        'qualification':'sha256:f9aded6b7b0ba702d9ec105d30320a0b2d44c22a2ab090e88e1bc1e813bda778',
        'source':'sha256:593c8dbaa193fc9ed8b3f88ff650975b55abf2b124c2cfeaf0decc534f723b34',
        'node':'sha256:ceaacb9c49b1595ff726aa3139aa7f0a75c03a6f63561602a0e406405191f649'},
}
PUBLIC = frozenset({'BUILD-COMPLETE.json','build-observation.json','source-inputs.json',
    'recipe-inputs.json','package-inputs.json','package-source.json','component.wasm','capsule.json',
    'contracts.json','wit-lock.json','compatibility-report.json','deployment.json',
    'typescript-entropy-selection.json'})
MATERIALS = (*native.MATERIALS,'tools/replay_embedded_resource_languages.py')


def validate_artifact(language, value):
    require(language in SPECS, 'embedded-replay-language')
    spec = SPECS[language]
    require(type(value) is dict and value.get('id') == spec['artifact']
        and value.get('name') == spec['name'] and value.get('size_in_bytes') == spec['archiveBytes']
        and value.get('digest') == spec['archiveDigest'] and value.get('expired') is False
        and value.get('workflow_run',{}).get('id') == spec['run']
        and value['workflow_run'].get('head_sha') == spec['head']
        and value['workflow_run'].get('repository_id') == 1337591365
        and value['workflow_run'].get('head_repository_id') == 1337591365,
        'embedded-replay-pinned-component-producer')
    return {'artifactId':spec['artifact'],'runId':spec['run'],'head':spec['head'],
        'compiledMerge':spec.get('compiledMerge',spec['head']),
        'apiArchiveDigest':spec['archiveDigest'],'apiArchiveBytes':spec['archiveBytes'],
        'completeArchiveHashVerified':False}


def selected(language, name):
    if language not in SPECS or type(name) is not str or '\\' in name or ':' in name \
            or any(part in {'','.','..'} for part in name.split('/')):
        return False
    prefix = SPECS[language]['prefix']
    if not name.startswith(prefix): return False
    relative = name.removeprefix(prefix)
    if relative in {'qualification.json','source-inputs.json','node/workflow.json'}: return True
    for template in TEMPLATES:
        if template == 'greeting': continue
        build = 'builds/'+template+'/'
        if relative.startswith(build):
            suffix = relative.removeprefix(build)
            return suffix in PUBLIC or re.fullmatch(r'wit/(?:[a-z0-9-]+/){0,3}[a-z0-9_.-]+\.wit',suffix) is not None
    return False


def acquire(language, output):
    require(language in SPECS, 'embedded-replay-language')
    output = fresh(output)
    deadline = time.monotonic()+600
    credential = os.environ.get('GH_TOKEN')
    require(type(credential) is str and 0 < len(credential) <= 4096, 'embedded-replay-read-credential')
    endpoint = 'https://api.github.com/repos/KirilsTurkins/latent-service-fabric/actions/artifacts/'+str(SPECS[language]['artifact'])
    headers = {'Authorization':'Bearer '+credential,'Accept':'application/vnd.github+json'}
    with urllib.request.urlopen(urllib.request.Request(endpoint,headers=headers),timeout=30) as response:
        require(response.status == 200, 'embedded-replay-metadata-status')
        raw = response.read(65537)
    require(len(raw) <= 65536, 'embedded-replay-metadata-bound')
    metadata = json.loads(raw)
    origin = validate_artifact(language,metadata)
    try:
        urllib.request.build_opener(NoRedirect).open(urllib.request.Request(endpoint+'/zip',headers=headers),timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'embedded-replay-redirect-required')
        url = error.headers['Location']
    else:
        raise RuntimeError('embedded-replay-redirect-required')
    location = urllib.parse.urlsplit(url)
    require(location.scheme == 'https' and location.hostname is not None and location.username is None
        and (location.hostname.endswith('.blob.core.windows.net') or location.hostname.endswith('.githubusercontent.com')),
        'embedded-replay-public-download-origin')
    del credential,headers
    remote = Remote(url,metadata['size_in_bytes'],maximum_requests=640)
    copied,total = [],0
    with zipfile.ZipFile(remote) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) <= 65536, 'embedded-replay-unique-index')
        entries = [archive.getinfo(name) for name in names if selected(language,name)]
        require(32 <= len(entries) <= 128, 'embedded-replay-public-member-count')
        for entry in entries:
            require(time.monotonic() <= deadline and not entry.is_dir()
                and not stat.S_ISLNK(entry.external_attr >> 16) and not entry.flag_bits & 1
                and 0 < entry.file_size <= 32*1024**2, 'embedded-replay-public-member-bound')
            total += entry.file_size
            require(total <= 64*1024**2, 'embedded-replay-public-total-bound')
            path = output/entry.filename.removeprefix(SPECS[language]['prefix'])
            path.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(entry) as source, path.open('xb') as target:
                written = 0
                while raw := source.read(1024**2):
                    written += len(raw)
                    require(written <= entry.file_size and time.monotonic() <= deadline,
                        'embedded-replay-decompression-bound')
                    target.write(raw)
            require(written == entry.file_size, 'embedded-replay-member-size')
            copied.append({'path':path.relative_to(output).as_posix(),**file_identity(path,32*1024**2)})
    proof = {'schemaVersion':'latent.embedded-resource-inputs.v1','status':'passed','language':language,
        'producer':origin,'publicMembers':copied,'rangeRequests':remote.requests,'networkBytes':remote.network_bytes,
        'completeArchiveDownloaded':False,'nativeExecutablesDownloaded':False,'credentialsRetained':False}
    historical(language,output)
    write_json(output/'acquisition.json',proof)
    return proof


def historical(language, directory):
    require(language in SPECS, 'embedded-replay-language')
    spec = SPECS[language]
    qraw = read_file(directory/'qualification.json',1024**2)
    source = read_file(directory/'source-inputs.json',16*1024**2)
    node_raw = read_file(directory/'node/workflow.json',1024**2)
    require(digest(qraw) == spec['qualification'] and digest(source) == spec['source']
        and digest(node_raw) == spec['node'], 'embedded-replay-original-normal-preimages')
    q,node = json.loads(qraw),json.loads(node_raw)
    require(q.get('schemaVersion') == 'latent.'+language+'-capsule.qualification.v1'
        and q['status'] == node['status'] == 'passed'
        and ('applicationDependencies' in q) == spec['capturedDependencies']
        and q['sourceIdentityDigest'] == spec['source'] and q['node']['receiptDigest'] == spec['node']
        and node['language'] == language and len(node['invocations']) == spec['normalCalls']
        and len(node['samples']) == spec['physical'] and len(node['providerIdle']) == spec['idle']
        and all(row['processReaped'] and row['response']['outcomeKnown'] is True for row in node['invocations'])
        and len({row['activation'] for row in node['invocations']}) == spec['normalCalls']
        and node['nodeShutdown']['reaped'] and node['nodeShutdown']['record']['clean'],
        'embedded-replay-original-normal-programme')
    if spec['capturedDependencies']:
        require(type(q['applicationDependencies']) is dict
            and q['applicationDependencies'].get('developerOwned') == 'outside-qualification-module/1.0.0'
            and q['applicationDependencies'].get('offlineOriginals') == 'unavailable-after-capture',
            'embedded-replay-original-captured-dependency-programme')
    companions,identities = {},{}
    for template in TEMPLATES:
        if template == 'greeting': continue
        location = directory/'builds'/template
        marker = read_json(location/'BUILD-COMPLETE.json')
        require(marker == q['builds'][template], 'embedded-replay-original-companion-marker')
        identities[template] = package_identity(location,marker)
        companions[template] = location
    return companions,{'componentCompiledSource':spec.get('compiledMerge',spec['head']),
        'componentProducerHead':spec['head'],'componentProducerRun':spec['run'],'componentProducerArtifact':spec['artifact'],
        'qualification':file_identity(directory/'qualification.json'),'sourceInputs':file_identity(directory/'source-inputs.json'),
        'node':file_identity(directory/'node/workflow.json'),'companions':identities,
        'normalActivations':[row['activation'] for row in node['invocations']],
        'physicalSamples':spec['physical'],'idleSamples':spec['idle'],
        'originalNormalUsesCapturedDependencies':spec['capturedDependencies'],
        'historicalReceiptRewritten':False,'currentNormalReceiptFabricated':False}


def replay(language, original, normal, metadata, output, *, tools=None):
    origin = native.producer.validate_producer(read_json(metadata,1024**2))
    materials = {name:file_identity(ROOT/name) for name in dict.fromkeys(MATERIALS)}
    binaries,_,native_proof = native.selected(normal)
    companions,component_proof = historical(language,original)
    acquisition = read_json(original/'acquisition.json',1024**2)
    require(acquisition.get('status') == 'passed' and acquisition.get('language') == language
        and acquisition.get('producer',{}).get('artifactId') == SPECS[language]['artifact']
        and acquisition['producer'].get('head') == SPECS[language]['head']
        and acquisition['producer'].get('apiArchiveDigest') == SPECS[language]['archiveDigest']
        and acquisition.get('nativeExecutablesDownloaded') is False
        and acquisition.get('credentialsRetained') is False, 'embedded-replay-acquisition-proof')
    acquisition_identity = file_identity(original/'acquisition.json')
    for path in binaries.values(): path.chmod(0o700)
    ancestry = {**component_proof,'nativeProducer':origin,'nativeNormal':native_proof,
        'componentAcquisition':acquisition_identity,'nativeAndCompanionProducerDiffer':True,
        'currentNativeCompilationClaimed':False}
    result = campaign(language,output,binaries,companions,ancestry,tools=tools)
    require(native.selected(normal)[2] == native_proof and historical(language,original)[1] == component_proof
        and file_identity(original/'acquisition.json') == acquisition_identity
        and materials == {name:file_identity(ROOT/name) for name in materials}, 'embedded-replay-final-input-drift')
    write_json(output/'replay.json',{'status':result['status'],'inherited':ancestry,'materials':materials,
        'qualification':file_identity(output/'qualified.json'),'freshComponents':1,'nativeRebuilt':False,
        'companionComponentsRecompiled':False,'currentNormalReceiptFabricated':False})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--language',choices=tuple(SPECS),required=True)
    parser.add_argument('--acquire',action='store_true')
    for name in ('original','normal-qualification','producer-receipt','output','tools'):
        parser.add_argument('--'+name,type=Path,required=name=='output')
    args = parser.parse_args()
    if args.acquire:
        require(all(value is None for value in (args.original,args.normal_qualification,args.producer_receipt,args.tools)),
            'embedded-replay-acquisition-only')
        print(acquire(args.language,args.output.absolute())['status'])
    else:
        require(args.original is not None and args.normal_qualification is not None and args.producer_receipt is not None,
            'embedded-replay-explicit-provenance-required')
        print(replay(args.language,args.original.resolve(strict=True),args.normal_qualification.resolve(strict=True),
            args.producer_receipt,args.output.absolute(),tools=args.tools)['status'])
