"""Store only the validated candidate objects; never mutate any branch."""
from pathlib import Path
import os, json, subprocess, hashlib, base64, urllib.request
root = Path.cwd()
parent = '1d81c35ca6b206bafba113b6214de09bc6781bdb'
base_tree = '1e5d2f29ba8689a526049314a5e1322e5c271a67'
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
subprocess.run(['git','add','--',*sorted(allowed)],check=True)
changed = subprocess.check_output(['git','diff','--cached','--name-only']).decode().splitlines()
assert set(changed) == allowed and len(changed) == 34
assert all(not (root / n).is_symlink() for n in changed)
expected = subprocess.check_output(['git','write-tree']).decode().strip()
endpoint = 'https://api.github.com/repos/KirilsTurkins/latent-service-fabric/git/'
def post(path, value):
    request = urllib.request.Request(endpoint + path, json.dumps(value).encode(), method='POST', headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json','Content-Type':'application/json','X-GitHub-Api-Version':'2022-11-28'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)
entries = []
for name in changed:
    raw = (root / name).read_bytes(); assert len(raw) <= 2 * 1024 * 1024
    sha = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    result = post('blobs', {'content':base64.b64encode(raw).decode(),'encoding':'base64'})
    assert result['sha'] == sha
    entries.append({'path':name,'mode':'100644','type':'blob','sha':sha})
result = post('trees', {'base_tree':base_tree,'tree':entries}); assert result['sha'] == expected
result = post('commits', {'message':'fix(rust-http): authenticate the corrected source graph and maintain retirement regressions','tree':expected,'parents':[parent]})
assert result['tree']['sha'] == expected and [p['sha'] for p in result['parents']] == [parent]
out = Path(os.environ['RUNNER_TEMP']) / 'pr1657-final'
(out / 'candidate.json').write_text(json.dumps({'commit':result['sha'],'tree':expected,'parent':parent,'files':entries,'branchMoved':False}, indent=2)+'\n')
with open(os.environ['GITHUB_ENV'],'a') as stream:
    stream.write('FINAL_HEAD='+result['sha']+'\n')
print(json.dumps({'candidateCommit':result['sha'],'candidateTree':expected,'branchMoved':False}))
