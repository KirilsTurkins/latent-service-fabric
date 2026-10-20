"""Fixed public AOT input acquisition; never a new compilation observation."""
from __future__ import annotations
import json
import os
from pathlib import Path
import stat
import tempfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from tools.dotnet_resource_recomposition import COMPILED_SOURCE, COMPONENT
from tools.go_entropy_replay_inputs import NoRedirect, Remote
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, snapshot, write_json

RECORDS = {
 'BUILD-COMPLETE.json':{'sha256':'sha256:aeed70ea501ec70b2a13470fe0171404b2d9c5038fcb5d459fbcafc6123a5a86','bytes':4147},
 'build-observation.json':{'sha256':'sha256:b3aa9da0f1f784774a6733d8e81cc4956ed60a000c5dbe85323913b542f98fee','bytes':6433},
 'compatibility-report.json':{'sha256':'sha256:9e73bcde3487a5decc060b09cf50c7845a0a74975a73bd544a336cd3df505c80','bytes':1254},
 'recipe-inputs.json':{'sha256':'sha256:110475c08ffad0586bda481eadf4380d365a6b717f4676a7dd4ce1c794ecdac7','bytes':7638},
 'source-inputs.json':{'sha256':'sha256:9aa8ba1c90ba64ef02ca31a367f9c8d1197fb478786319dd086e22acad0105a0','bytes':17456},
 'component.wasm':COMPONENT,
}
SPECS = {
 'component':{'artifact':12208042991,'name':'dotnet-guest-qualification-bdfbae5e00b4a5842603a86a515601f638e4ad0f',
  'run':39293483999,'head':COMPILED_SOURCE,'bytes':1437991094,
  'digest':'sha256:a7a44a8310ee075f794907db85e5807e092ffb5ea7723776059b0414b9efe8a2'},
 'records':{'artifact':12217781637,'name':'dotnet-console-closed-replay-3f5d19602e7ad9c13e8ab32f086fb8e07c780686',
  'run':39314452672,'head':'3f5d19602e7ad9c13e8ab32f086fb8e07c780686','bytes':466689,
  'digest':'sha256:1013452e1c934c075f6b16daefb2eaf3529b396c9afbf6b2b416a4b1aa70a887'},
}
SEEDS = ('examples/echo-contract/capsule.json','examples/echo-contract/deployment.json')
PACKAGE_INPUTS = {'digest':'sha256:22470ff1ceb04a38c8a58e8a38725e719ba96a219ecc01b29dae15e54311960c','size':1185}


def validate_metadata(kind, value):
 require(kind in SPECS,'dotnet-resource-origin-kind')
 expected=SPECS[kind];run=value.get('workflow_run',{})
 require(value.get('id')==expected['artifact'] and value.get('name')==expected['name']
  and value.get('size_in_bytes')==expected['bytes'] and value.get('digest')==expected['digest']
  and value.get('expired') is False and run.get('id')==expected['run'] and run.get('head_sha')==expected['head']
  and run.get('repository_id')==run.get('head_repository_id')==1337591365,
  'dotnet-resource-fixed-original-artifact')
 return {**expected,'wholeArchiveDigestVerified':False,'wholeArchiveDownloaded':False}


def validate_records(directory):
 require({name:file_identity(directory/name,4*1024**2) for name in RECORDS}==RECORDS,
  'dotnet-resource-original-document-preimage')
 marker=read_json(directory/'BUILD-COMPLETE.json');observed=read_json(directory/'build-observation.json')
 require(marker['componentDigest']==observed['componentDigest']==COMPONENT['sha256']
  and observed['componentSize']==COMPONENT['bytes']
  and marker['observationDigest']==RECORDS['build-observation.json']['sha256']
  and marker['sourceDigest']==RECORDS['source-inputs.json']['sha256']
  and [row for row in observed['materials'] if row['name']=='package-inputs']==[{'name':'package-inputs',**PACKAGE_INPUTS}],
  'dotnet-resource-original-build-bindings')
 return observed


def acquire(output):
 output=fresh(output);original=fresh(output/'original');deadline=time.monotonic()+480
 credential=os.environ.get('GH_TOKEN');require(type(credential) is str and 0<len(credential)<=4096,'dotnet-resource-read-credential')
 headers={'Authorization':'Bearer '+credential,'Accept':'application/vnd.github+json'};proofs=[]
 for kind,spec in SPECS.items():
  endpoint='https://api.github.com/repos/KirilsTurkins/latent-service-fabric/actions/artifacts/'+str(spec['artifact'])
  with urllib.request.urlopen(urllib.request.Request(endpoint,headers=headers),timeout=30) as response:
   require(response.status==200,'dotnet-resource-metadata-status');raw=response.read(65537)
  require(len(raw)<=65536,'dotnet-resource-metadata-bound');metadata=json.loads(raw);origin=validate_metadata(kind,metadata)
  try:urllib.request.build_opener(NoRedirect).open(urllib.request.Request(endpoint+'/zip',headers=headers),timeout=30)
  except urllib.error.HTTPError as error:
   require(error.code==302,'dotnet-resource-archive-redirect');url=error.headers['Location'];error.close()
  else:raise RuntimeError('dotnet-resource-archive-redirect')
  u=urllib.parse.urlsplit(url)
  require(u.scheme=='https' and not u.username and not u.password and u.hostname is not None
   and (u.hostname.endswith('.blob.core.windows.net') or u.hostname.endswith('.githubusercontent.com')),
   'dotnet-resource-public-download-origin')
  selected={'dotnet-standard-console/build/component.wasm':'component.wasm'} if kind=='component' else {
   'console-closed-replay/build-evidence/original-'+name:name for name in RECORDS if name!='component.wasm'}
  remote=Remote(url,spec['bytes'],maximum_requests=48);members=[]
  with zipfile.ZipFile(remote) as archive:
   names=archive.namelist();require(len(names)==len(set(names))<=32768,'dotnet-resource-unique-original-index')
   for name,destination in selected.items():
    entry=archive.getinfo(name);expected=RECORDS[destination]
    require(not entry.is_dir() and not entry.flag_bits&1 and not stat.S_ISLNK(entry.external_attr>>16)
     and entry.file_size==expected['bytes'] and time.monotonic()<deadline,'dotnet-resource-fixed-member-bound')
    raw=archive.read(entry)
    require({'sha256':digest(raw),'bytes':len(raw)}==expected and time.monotonic()<deadline,'dotnet-resource-fixed-member-preimage')
    (original/destination).write_bytes(raw);members.append({'member':name,'destination':destination,**expected})
  require(remote.network_bytes<=8*1024**2,'dotnet-resource-selected-transfer-bound')
  proofs.append({'producer':origin,'members':members,'rangeRequests':remote.requests,'networkBytes':remote.network_bytes})
 del credential,headers
 validate_records(original)
 proof={'schemaVersion':'latent.dotnet.resource-originals.v1','origins':proofs,'originalRecords':RECORDS,
  'nativeAotCompilationPerformed':False,'nativeExecutablesDownloaded':False,'credentialsRetained':False,'qualification':False}
 write_json(output/'acquisition.json',proof);return original,proof


def original_public_files(original, output, fetch):
 """Only six declared public metadata files and two original recipe seeds."""
 validate_records(original)
 from tools.dotnet_guest.project import create
 from tools.dotnet_standard_console_fixture import declare
 source=read_json(original/'source-inputs.json');recipe=read_json(original/'recipe-inputs.json')
 with tempfile.TemporaryDirectory(prefix='lsf-dotnet-resource-public-') as temp:
  project=create(Path(temp)/'project','greeting');declare(project)
  files={name:raw for name,raw in snapshot(project).items() if name.startswith('wit/') or name=='capsule-project.json'}
 files['vendor/lsf/Cargo.toml']=fetch('Cargo.toml')
 require({name for name in files if name.startswith('wit/')}=={name for name in source if name.startswith('wit/')}
  and len(files)==6,'dotnet-resource-original-public-membership')
 for name,raw in files.items():
  require(source.get(name)=={'digest':digest(raw),'size':len(raw)},'dotnet-resource-original-public-byte')
 seeds={name:fetch(name) for name in SEEDS}
 for name,raw in seeds.items():
  require(recipe.get(name)=={'digest':digest(raw),'size':len(raw)},'dotnet-resource-original-recipe-byte')
 output=fresh(output)
 for name,raw in {**files,**seeds}.items():
  path=output/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
 return files,seeds


def public_git_file(name):
 require(name in ('Cargo.toml',*SEEDS),'dotnet-resource-public-source-allowlist')
 url='https://raw.githubusercontent.com/KirilsTurkins/latent-service-fabric/'+COMPILED_SOURCE+'/'+name
 with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'LSF-resource-public-metadata'}),timeout=30) as response:
  require(response.status==200 and response.url==url,'dotnet-resource-public-source-origin');raw=response.read(8193)
 require(0<len(raw)<=8192,'dotnet-resource-public-source-bound');return raw


def reconstruct(original, output, binaries, commands):
 """Bind every old public package byte before any metadata derivation."""
 observed=validate_records(original);output=fresh(output)
 files,seeds=original_public_files(original,output/'public-project',public_git_file)
 project=json.loads(files['capsule-project.json']);input_path=output/'contracts-input.json'
 write_json(input_path,{'world':project['world'],'sources':[{'path':name,'content':raw.decode()}
  for name,raw in files.items() if name.startswith('wit/')]})
 derived=output/'contracts';commands.run('original-public-contracts',binaries['examples/capsule_contracts'],input_path,derived)
 surface=read_json(derived/'surface.json')
 require(set(surface['imports'])=={'latent:clock/monotonic@0.1.0','latent:random/random@0.1.0','latent:log/log@0.1.0'},
  'dotnet-resource-original-authority')
 artifact=fresh(output/'build')
 for name in RECORDS:(artifact/name).write_bytes(read_file(original/name,4*1024**2))
 for name in ('contracts.json','wit-lock.json'):(artifact/name).write_bytes(read_file(derived/name))
 manifest=json.loads(seeds[SEEDS[0]]);manifest['metadata']={'name':project['service'],'tenant':project['tenant']}
 manifest['component']={'digest':COMPONENT['sha256'],'version':project['version'],'world':project['world']}
 manifest['exports']=surface['exports'];manifest['imports']=[{'contract':name,'optional':False} for name in surface['imports']]
 manifest['execution'].update(limits=project['limits'],threading='single-threaded',snapshotEligible=False,fusionEligible=False)
 manifest['compatibility']['minimumFabricVersion']=tomllib.loads(files['vendor/lsf/Cargo.toml'].decode())['workspace']['package']['version']
 write_json(artifact/'capsule.json',manifest)
 layers=[('component.wasm','component','application/wasm'),('capsule.json','capsule-manifest','application/vnd.latent.capsule.manifest.v1+json'),
  ('contracts.json','contracts','application/vnd.latent.contracts.v1+json'),('wit-lock.json','wit-lock','application/vnd.latent.wit-lock.v1+json'),
  ('compatibility-report.json','asset','application/vnd.latent.guest.compatibility.v1+json')]
 for name,raw in files.items():
  if name.startswith('wit/'):
   p=artifact/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);layers.append((name,'asset','text/plain'))
 write_json(artifact/'package-source.json',{'formatVersion':1,'kind':'capsule','name':project['name'],'version':project['version'],
  'entrypoint':'component.wasm','annotations':{},'layers':[{'path':name,'source':name,'role':role,'mediaType':media} for name,role,media in layers]})
 raw=inventory({name:read_file(artifact/name,4*1024**2) for name in ('package-source.json',*(name for name,_,_ in layers))})
 require({'digest':digest(raw),'size':len(raw)}==PACKAGE_INPUTS,'dotnet-resource-original-package-inventory')
 (artifact/'package-inputs.json').write_bytes(raw)
 deployment=json.loads(seeds[SEEDS[1]]);deployment['metadata']={'name':project['name'],'tenant':project['tenant']}
 deployment['spec'].update(service=project['service'],release=COMPONENT['sha256'],grants=[],resources=project['limits'])
 write_json(artifact/'deployment.json',deployment)
 return artifact,{'originalComponent':COMPONENT,'originalRecords':RECORDS,'originalPackageInputs':PACKAGE_INPUTS,
  'publicProject':json.loads(inventory(files)),'publicRecipe':json.loads(inventory(seeds)),'nativeAotCompilationPerformed':False,
  'originalPackageDigestClaimed':False,'publicMetadataAuthenticated':True,'qualification':False}
