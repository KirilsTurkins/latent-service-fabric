"""Retain the validated source and a local test commit; no remote Git writes."""
from pathlib import Path
import os, json, subprocess, hashlib
root = Path.cwd()
parent = '1d81c35ca6b206bafba113b6214de09bc6781bdb'
development = '9ad0b456609ad32c3d9fd932673d99e8c39453ff'
assert subprocess.check_output(['git','rev-parse','HEAD']).decode().strip() == parent
allowed = {
'.github/workflows/rust-combined-host-diagnostic.yml', '.github/workflows/rust-combined-signed-witness.yml', '.github/workflows/rust-wasi-http-runtime.yml',
'crates/latent-component-threading/src/rust_component.rs', 'crates/latent-component-threading/src/rust_original_delta.rs', 'crates/latent-packaging/src/semantics/wasm/tests.rs', 'crates/latent-wasmtime/src/component_threading.rs',
'docs/testing/rust-combined-http-diagnostic.md', 'docs/testing/rust-http-callback-pump.md', 'sdk/wasi-http-runtime/README.md',
 'tools/ci/contracts/workflows/rust-combined-host-diagnostic.yml/jobs/diagnostic.json', 'tools/ci/contracts/workflows/rust-combined-signed-witness.yml/jobs/signed-witness.json', 'tools/ci/contracts/workflows/rust-wasi-http-runtime.yml/jobs/standard-backend.json',
 'tools/rust_combined_http_materials.py', 'tools/rust_thread_http_combined_node.py', 'tools/rust_thread_http_combined_package.py', 'tools/tests/test_rust_thread_http_combined_node.py', 'tools/toolchain-smoke/examples/rust_http_pump_control.rs'}
folder = 'crates/latent-component-threading/src/rust_catalogue/combined-corrected-v1/'
assets = {'combined-original-core.wasm','combined-preview-component.wasm','combined-preview-shell.bin','combined-final-component.wasm','combined-final-prefix.bin','combined-final-suffix.bin','combined-original-producers.bin','combined-encoded-producers.bin','combined-original-delta.bin','origin.json','compiler-control.json',*[f'combined-wit-{i}.bin' for i in range(5)]}
allowed |= {folder + n for n in assets}
merge = {
'crates/latent-commit/src/atomic/tests.rs': '0bf9ffe95f680e39be1fc7dd889f9b72544d865c',
'crates/latent-commit/src/atomic/tests/supported_formats.rs': '1dde1295b0f92bd6047f54cc5627f90537af66ac',
'crates/latent-commit/src/atomic/writer.rs': '84b2ac74263de6a8766666aaf48968571b863815',
'crates/latent-node/src/transaction_runtime/factory/admission.rs': 'b71046ef579112b9e55c08b2518933ab5a479b83',
'crates/latent-node/src/transaction_runtime/factory/pre_host_conflict/tests.rs': '13d92a2c8a1855c4336062b56ad6413ca3b1947a'}
for name, sha in merge.items():
    raw = (root / name).read_bytes()
    assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == sha
allowed |= set(merge)
subprocess.run(['git','add','--',*sorted(allowed)],check=True)
changed = subprocess.check_output(['git','diff','--cached','--name-only']).decode().splitlines()
assert set(changed) == allowed and len(changed) == 39
assert all(not (root / n).is_symlink() for n in changed)
expected = subprocess.check_output(['git','write-tree']).decode().strip()
entries=[]
for name in changed:
    raw=(root/name).read_bytes(); assert len(raw)<=2*1024*1024
    sha=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    entries.append({'path':name,'mode':'100644','type':'blob','sha':sha})
subprocess.run(['git','config','user.name','Kirils Turkins'],check=True)
subprocess.run(['git','config','user.email','turkinskirils@gmail.com'],check=True)
commit=subprocess.check_output(['git','commit-tree',expected,'-p',parent,'-p',development,'-m','Authenticate corrected combined source and incorporate current development']).decode().strip()
out=Path(os.environ['RUNNER_TEMP'])/'pr1657-final'
(out/'candidate.json').write_text(json.dumps({'commit':commit,'tree':expected,'parents':[parent,development],'baseTree':'1e5d2f29ba8689a526049314a5e1322e5c271a67','files':entries,'branchMoved':False,'remoteCommitCreated':False},indent=2)+'\n')
(out/'source.patch').write_bytes(subprocess.check_output(['git','diff','--cached','--binary']))
(out/'source-tree.txt').write_bytes(subprocess.check_output(['git','ls-tree','-r',commit]))
subprocess.run(['git','archive','--format=tar.gz','-o',str(out/'source.tar.gz'),commit,*changed],check=True)
subprocess.run(['git','reset','--hard',commit],check=True)
assert not subprocess.check_output(['git','status','--porcelain']).strip()
with open(os.environ['GITHUB_ENV'],'a') as stream: stream.write('FINAL_HEAD='+commit+'\n')
print(json.dumps({'localTestCommit':commit,'candidateTree':expected,'remoteWrites':False}))
