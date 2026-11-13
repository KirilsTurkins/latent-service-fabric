#!/usr/bin/env python3
"""Prepare native dependency security updates on exact history; export no refs."""
from __future__ import annotations
import ast, base64, difflib, hashlib, io, json, os, pathlib, re, subprocess, sys, tarfile, urllib.request
ROOT=pathlib.Path.cwd()
OUT=pathlib.Path(os.environ['RUNNER_TEMP'])/'native-security-evidence';OUT.mkdir(exist_ok=True)
BASE='68bd53e20eeeae109f7816c8e81a1f959158a93b'
GO_SHA='7226736c2339719cda28fbf3a54d71aa63bcefe376e98cef00034268dab24840'
def run(args,cwd=ROOT,timeout=1200):
    return subprocess.check_output(args,cwd=cwd,text=True,timeout=timeout).strip()
def checked(name,args,cwd=ROOT,timeout=1200):
    with (OUT/(name+'.log')).open('wb') as f:
        p=subprocess.run(args,cwd=cwd,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
    if p.returncode:
        print((OUT/(name+'.log')).read_text(errors='replace')[-20000:]);raise RuntimeError(name)
    return {'name':name,'command':args,'exit':0,'sha256':hashlib.sha256((OUT/(name+'.log')).read_bytes()).hexdigest()}
def identity(raw):return {'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
def rewrite(path,old,new):
    data=path.read_bytes();target=data.replace(old.encode(),new.encode())
    if target!=data:path.write_bytes(target)
def assign(source,name,value):
    tree=ast.parse(source)
    nodes=[n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in n.targets)]
    assert len(nodes)==1,name
    node=nodes[0];lines=source.splitlines(keepends=True)
    lines[node.lineno-1:node.end_lineno]=[f'{name} = '+json.dumps(value,indent=4)+'\n']
    return ''.join(lines)
def prepare():
    assert run(['git','rev-parse','HEAD'])==BASE
    files=run(['git','ls-files']).splitlines();before={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files if (ROOT/p).is_file()}
    changed_pins=[]
    for name in files:
        p=ROOT/name
        if name.startswith('crates/') and '/vendor/' not in name and p.name=='Cargo.toml':
            data=p.read_text();updated=re.sub(r'(rustix\s*=\s*\{[^\n]*version\s*=\s*\")=1\.1\.5(\")',r'\g<1>=1.1.6\2',data)
            updated=re.sub(r'(rustix\s*=\s*\")=1\.1\.5(\")',r'\g<1>=1.1.6\2',updated)
            if updated!=data:p.write_text(updated);changed_pins.append(name)
    assert len(changed_pins)>=10,changed_pins
    checks=[]
    for label,manifest,version in [('workspace','Cargo.toml','1.1.5'),('native-fixture','tools/native-fixture/Cargo.toml','1.1.5'),('wasmtime','crates/vendor/wasmtime/Cargo.toml','1.1.4'),('cache','crates/vendor/wasmtime-cache/Cargo.toml','1.1.4')]:
        checks.append(checked(label+'-resolve',['cargo','update','--manifest-path',manifest,'-p','rustix@'+version,'--precise','1.1.6']))
    # Reconstruct only the lock portion against the immutable upstream archive.
    vendor=ROOT/'crates/vendor/wasmtime';record_path=vendor/'UPSTREAM.latent.json';record=json.loads(record_path.read_text())
    with urllib.request.urlopen(record['registryArchive'],timeout=120) as r: archive=r.read(20*1024*1024)
    assert hashlib.sha256(archive).hexdigest()==record['registrySha256']
    with tarfile.open(fileobj=io.BytesIO(archive),mode='r:gz') as t: original=t.extractfile('wasmtime-48.0.8/Cargo.lock').read()
    row=next(x for x in record['originalFiles'] if x['path']=='Cargo.lock');assert identity(original)=={'sha256':row['sha256'],'bytes':row['bytes']}
    patch=vendor/'latent-dynamic-memory.patch';old_patch=patch.read_text();assert old_patch.startswith('--- a/Cargo.lock\n')
    end=old_patch.index('\n--- a/',1)+1
    diff=''.join(difflib.unified_diff(original.decode().splitlines(True),(vendor/'Cargo.lock').read_text().splitlines(True),fromfile='a/Cargo.lock',tofile='b/Cargo.lock',n=record['patchContextLines']))
    patch.write_text(diff+old_patch[end:])
    record['cacheSecurityBackport']['postimages']['Cargo.lock']=identity((ROOT/'crates/vendor/wasmtime-cache/Cargo.lock').read_bytes())
    record_path.write_text(json.dumps(record,indent=2)+'\n')
    control=ROOT/'tools/host_codec_wasmtime.py';source=control.read_text();tree=ast.parse(source)
    post=ast.literal_eval(next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='POSTIMAGES' for t in n.targets)))
    for name in ('Cargo.lock','latent-dynamic-memory.patch'):post[name]=identity((vendor/name).read_bytes())
    source=assign(source,'POSTIMAGES',post);source=assign(source,'RECORD_SHA256',hashlib.sha256(record_path.read_bytes()).hexdigest());control.write_text(source)
    # Current supported SDK/toolchain inputs, not historical qualification artifacts.
    for name in files:
        p=ROOT/name
        live=(name.startswith(('tools/','.github/workflows/','sdk/go/','sdk/go-guest/','sdk/dotnet/')) and p.suffix in {'.py','.json','.toml','.yml','.mod','.csproj'})
        if not live or '/fixtures/' in name or name.startswith('tools/security_'):continue
        if name in {'sdk/go-guest/toolchain.lock.json'} or p.suffix!='.json' or name.startswith(('tools/ci/contracts/','sdk/go/','sdk/go-guest/runtime-deps/','sdk/dotnet/')):
            for old,new in [('1.27.3','1.27.4'),('65efbc80fdc1fa2cd2631cad5b481777a68e8725f34e89f50fc6ac714e379b40',GO_SHA),('70588678','70680823'),('8.0.427','8.0.428'),('8.0.33','8.0.34')]:rewrite(p,old,new)
    for name in ('sdk/go/README.md','sdk/dotnet/README.md'):
        for old,new in [('1.27.3','1.27.4'),('8.0.427','8.0.428'),('8.0.33','8.0.34')]:rewrite(ROOT/name,old,new)
    p=ROOT/'sdk/go-guest/README.md';rewrite(p,'This profile uses pinned upstream Go 1.27.3','This profile uses pinned upstream Go 1.27.4')
    # The earlier audit keeps its historical source attribution. Record the new exact inputs separately.
    policy_path=ROOT/'.github/security/inventory.json';policy=json.loads(policy_path.read_text())
    for item in policy['manifests']:
        path=ROOT/item['path']
        if item['kind']=='nuget-locked' and item['path'].startswith('sdk/dotnet/'):
            if 'manifest_sha256' in item:item['manifest_sha256']=hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
        if item['kind']=='go-locked' and item.get('lock') and (ROOT/item['lock']).exists():
            lock_path=ROOT/item['lock'];lock=json.loads(lock_path.read_text())
            if lock.get('goVersion')=='1.27.3':lock['goVersion']='1.27.4'
            if lock.get('goVersion')=='1.27.4':
                lock['manifestSha256']=hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest();lock_path.write_text(json.dumps(lock,indent=2)+'\n')
        for row in item.get('configuration',[]):
            if row['path']=='sdk/dotnet/global.json':row['sha256']=hashlib.sha256((ROOT/row['path']).read_bytes()).hexdigest()
        if item.get('kind')=='no-external-packages' and item['path'].endswith('go.mod') and 'sha256' in item:item['sha256']=hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
    # Standard-library-only conformance input has a closed non-manifest record.
    for item in policy['non_manifest_modules']:
        path=item.get('path')
        if path and path.endswith('go.mod') and before.get(path)!=hashlib.sha256((ROOT/path).read_bytes()).hexdigest():
            for key in ('sha256','manifest_sha256'):
                if key in item:item[key]=hashlib.sha256((ROOT/path).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
    policy_path.write_text(json.dumps(policy,indent=2,sort_keys=True)+'\n')
    (OUT/'patch.patch').write_text(run(['git','diff','--binary'])+'\n')
    (OUT/'checks.json').write_text(json.dumps(checks,indent=2)+'\n')
    print('Native upgrade prepared; all remote refs are unchanged.')
def validate():
    checks=json.loads((OUT/'checks.json').read_text())
    checks.append(checked('source-and-sdk-controls',[sys.executable,'-m','unittest','tools.tests.test_host_codec_wasmtime','tools.tests.test_security_sdk_graphs','tools.tests.test_go_runtime_overlay','tools.tests.test_go_native_authoring','tools.tests.test_go_application_dependencies','-v']))
    checks.append(checked('native-sdk-dotnet',[sys.executable,'sdk/dotnet/validate.py','--check'],timeout=1500))
    checks.append(checked('native-sdk-go-lock',[sys.executable,'sdk/go/dependencies.py','--check']))
    checks.append(checked('native-sdk-go',['go','test','./...'],cwd=ROOT/'sdk/go'))
    checks.append(checked('native-wasmtime-store',['cargo','test','-p','latent-wasmtime','--lib','backend::store','--locked'],timeout=1800))
    (OUT/'checks.json').write_text(json.dumps(checks,indent=2)+'\n')
    (OUT/'patch.patch').write_text(run(['git','diff','--binary'])+'\n')
    print('Native upgrade targeted validation passed; not a full workspace or signed-guest result.')
if __name__=='__main__':globals()[sys.argv[1]]()
