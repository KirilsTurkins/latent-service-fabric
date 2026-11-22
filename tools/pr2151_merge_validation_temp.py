import base64, hashlib, json, os, pathlib, subprocess, sys, zlib
ROOT=pathlib.Path.cwd()
sys.path.insert(0, str(ROOT))
OUT=pathlib.Path(os.environ['RUNNER_TEMP'])/'pr2151-integration'
OUT.mkdir()
HEAD='f881e760dfb527e341b2b43b60d99f217ad2d8ae'
OLD='8f87f81f8c987f8f39f34bec693c8cb3e08ecb75'
DEV='5569a03df63cac133146eee2680223ea3a1a3dc7'
PAYLOAD=os.environ['RESOLUTION_PAYLOAD']
def git(*args, check=True):
    p=subprocess.run(['git',*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=240)
    if check and p.returncode: raise RuntimeError(p.stderr.decode(errors='replace')[-8000:])
    return p

def text(*args): return git(*args).stdout.decode().strip()
def blob(data): return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
def source(ref,path): return git('show',ref+':'+path).stdout
def retain_conflicts(label, paths):
    (OUT/(label+'.json')).write_text(json.dumps(sorted(paths)))
    for path in paths:
        dest=OUT/label/path; dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(pathlib.Path(path).read_bytes())
assert text('rev-parse','HEAD')==HEAD
assert not text('status','--porcelain')
git('config','user.name','LSF integration validation')
git('config','user.email','noreply@github.com')
for ref in (OLD,DEV,'3aabc54bf09040919f4b306f0009b5bcc1b5fb88','2023c55ee1f7a72fe8b022487a131834f9c23954'):
    git('fetch','--no-tags','origin',ref)
assert text('merge-base',HEAD,OLD)=='57d4a349dbb70c2511be1cd15f41e5915d6ba5b9'
initial=git('merge','--no-commit','--no-ff',OLD,check=False)
assert initial.returncode in (0,1), initial.stderr.decode()
conflicts=set(text('diff','--name-only','--diff-filter=U').splitlines())
retain_conflicts('initial-conflicts',conflicts)
owner='sdk/java-guest/fibers/conformance/shutdown-now/OwnerControl.java'
if owner in conflicts:
    original=source(HEAD,owner)
    assert original==source(OLD,owner), 'Independent shutdown ownership changes require review'
    assert blob(original)=='eca8bc976613d3bc55f1810770e1d47b8fbd0319'
    pathlib.Path(owner).write_bytes(original); git('add','--',owner)
    conflicts.remove(owner)
allowed={'sdk/typescript-guest/activation/native_engine.cpp','sdk/typescript-guest/activation/native_objects.h','tools/java_guest/date_link_guard.py','tools/java_guest/enum_guard.py','tools/tests/test_local_tests.py','tools/tests/test_typescript_event_ownership.py','tools/typescript_guest/event_engine.py'}
print('Initial conflicts:',sorted(conflicts),flush=True)
assert conflicts<=allowed, sorted(conflicts-allowed)
entries=json.loads(zlib.decompress(base64.b64decode(PAYLOAD)))
resolved={}
for item in entries:
    path=item['path']; pp=pathlib.PurePosixPath(path)
    assert not pp.is_absolute() and '..' not in pp.parts and '.git' not in pp.parts
    raw=source(item['ref'],path)
    assert blob(raw)==item['preimage'], ('preimage',path)
    lines=raw.decode().splitlines(True)
    for start,end,replacement in reversed(item['edits']): lines[start:end]=replacement
    result=''.join(lines).encode()
    assert blob(result)==item['postimage'], ('postimage',path)
    resolved[path]=result
    pathlib.Path(path).parent.mkdir(parents=True,exist_ok=True)
    pathlib.Path(path).write_bytes(result)
git('add','--',*resolved)
assert not text('diff','--name-only','--diff-filter=U')
git('diff','--cached','--check')
first_tree=text('write-tree')
intermediate=text('commit-tree',first_tree,'-p',HEAD,'-p',OLD,'-m','Local-only reviewed resolution scaffold')
# This is a disposable runner checkout; the scaffold is never published.
git('reset','--hard',intermediate)
second=git('merge','--no-commit','--no-ff',DEV,check=False)
assert second.returncode in (0,1), second.stderr.decode()
conflicts=set(text('diff','--name-only','--diff-filter=U').splitlines())
retain_conflicts('new-conflicts',conflicts)
print('New #2163 conflicts:',sorted(conflicts),flush=True)
for path in sorted(conflicts):
    if path in ('tools/tests/test_java_enum_guard.py','tools/tests/test_java_date_link_guard.py'):
        # The newly merged branch copied these tests from the same security
        # parent. Keep the reviewed exception-header setup and 64 KiB checks.
        assert source(DEV,path)==source('7c830598ca437279a8eead344aae5945bffb5bcf',path), ('new Java changes',path)
        pathlib.Path(path).write_bytes(resolved[path]); git('add','--',path)
    elif path=='tools/tests/test_local_tests.py' and source(DEV,path)==source(HEAD,path):
        pathlib.Path(path).write_bytes(resolved[path]); git('add','--',path)
remaining=text('diff','--name-only','--diff-filter=U').splitlines()
if remaining: raise RuntimeError('Unreviewed new conflicts: '+', '.join(remaining))
ours=['sdk/java-guest/fibers/dev/latent/guest/runtime/concurrent/ManagedExecutor.java','sdk/java-guest/fibers/conformance/shutdown-now/Capsule.java',owner,'sdk/java-guest/fibers/conformance/shutdown-now/Main.java','tools/java_guest/field_read_patch.py','tools/java_guest/coroutine_patch.py','tools/java_standard_http_library.py','tools/qualify_java_dependency_suite.py']
theirs=['sdk/typescript-guest/probes/fetch-runtime/main.ts','sdk/typescript-guest/activation/runtime-globals.d.ts','tools/java_guest/exception_slots.py','Cargo.lock','crates/vendor/wasmtime/Cargo.toml','crates/vendor/wasmtime/UPSTREAM.latent.json','tools/typescript_guest/source_splicer.mjs','tools/typescript_guest/componentize.mjs']
for ref,paths in ((HEAD,ours),(DEV,theirs)):
    for path in paths: assert pathlib.Path(path).read_bytes()==source(ref,path), ('protected source changed',path)
for path in text('diff','--name-only',OLD,DEV).splitlines():
    if 'dotnet' in path:
        assert pathlib.Path(path).read_bytes()==source(DEV,path), ('dotnet integration drift',path)
git('diff','--cached','--check')
(OUT/'candidate.patch').write_bytes(git('diff','--cached','--binary',DEV).stdout)
from tools.ci_python_policy import require_no_new_controls
for path in text('diff','--cached','--name-only','--diff-filter=AM',DEV).splitlines():
    if pathlib.Path(path).name.startswith('test_') and path.endswith('.py'):
        previous=git('show',DEV+':'+path,check=False)
        require_no_new_controls(previous.stdout.decode() if previous.returncode==0 else '',pathlib.Path(path).read_text())
print('No new Python suppression controls',flush=True)
tree=text('write-tree')
(OUT/'candidate-tree.txt').write_text(tree+'\n')
(OUT/'resolved-files.json').write_text(json.dumps({p:blob(pathlib.Path(p).read_bytes()) for p in resolved},indent=2)+'\n')
(OUT/'parents.json').write_text(json.dumps({'head':HEAD,'development':DEV,'tree':tree})+'\n')
print('Candidate tree:',tree,flush=True)
