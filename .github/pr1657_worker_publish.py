"""Store only the reviewed candidate objects; never update any repository ref."""
from pathlib import Path
import hashlib, json, os, re, subprocess, urllib.request
REPO='KirilsTurkins/latent-service-fabric'
BASE='6994c4c4c7f0bb40aa405d804e47850a2dd60081'
TREE='0d219305a502dec958fc2d0374cd11235e78b913'
assert os.environ['GITHUB_REPOSITORY']==REPO
assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()==BASE
out=Path(os.environ['RUNNER_TEMP'])/'pr1657-worker-stage'
paths=json.loads((out/'paths.json').read_bytes())
allowed={'crates/latent-wasmtime/src/backend.rs','crates/latent-wasmtime/src/host/runtime.rs','crates/latent-wasmtime/src/native_stacks.rs','crates/latent-wasmtime/src/native_stacks/workers.rs','crates/latent-wasmtime/src/native_stacks/combined.rs','crates/latent-wasmtime/src/native_stacks/tests.rs','crates/latent-wasmtime/src/native_stacks/tests/combined.rs','docs/testing/rust-combined-http-diagnostic.md','.github/workflows/rust-combined-host-diagnostic.yml','tools/ci/contracts/workflows/rust-combined-host-diagnostic.yml/jobs/diagnostic.json'}
assert len(paths)==len(allowed) and set(paths)==allowed
changed=set(subprocess.check_output(['git','diff','--name-only'],text=True).splitlines())|set(subprocess.check_output(['git','ls-files','--others','--exclude-standard'],text=True).splitlines())
assert changed==allowed,(changed-allowed,allowed-changed)
def post(suffix,value):
 raw=json.dumps(value).encode();assert len(raw)<512*1024
 request=urllib.request.Request('https://api.github.com/repos/'+REPO+'/git/'+suffix,data=raw,method='POST',headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json','Content-Type':'application/json','User-Agent':'LSF-reviewed-candidate-objects'})
 with urllib.request.urlopen(request,timeout=30) as response:
  assert response.status==201
  body=response.read(2*1024*1024+1);assert len(body)<=2*1024*1024
 result=json.loads(body);assert re.fullmatch('[0-9a-f]{40}',result['sha']);return result['sha']
subprocess.run(['git','add','--',*sorted(paths)],check=True)
expected=subprocess.check_output(['git','write-tree'],text=True).strip()
records=[];elements=[]
for name in sorted(paths):
 p=Path(name);assert p.is_file() and not p.is_symlink();raw=p.read_bytes();assert len(raw)<128*1024
 sha=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
 actual=post('blobs',{'content':raw.decode('utf-8'),'encoding':'utf-8'});assert actual==sha
 elements.append({'path':name,'mode':'100644','type':'blob','sha':sha})
 records.append({'path':name,'gitBlob':sha,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
tree=post('trees',{'base_tree':TREE,'tree':elements});assert tree==expected
commit=post('commits',{'message':'Admit fixed combined HTTP workers under the original authenticated stack owner','tree':tree,'parents':[BASE]})
(out/'candidate.json').write_text(json.dumps({'sourceCommit':commit,'tree':tree,'parent':BASE,'files':records,'refsUpdated':False},indent=2)+'\n')
(out/'candidate.patch').write_bytes(subprocess.check_output(['git','diff','--cached','--binary']))
subprocess.run(['git','fetch','--no-tags','--depth=1','origin',commit],check=True)
subprocess.run(['git','checkout','--detach',commit],check=True)
assert not subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],text=True).strip()
print('source candidate',commit,'tree',tree,'no refs updated')
