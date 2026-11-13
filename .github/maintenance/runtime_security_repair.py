#!/usr/bin/env python3
"""Prepare targeted dependency repairs on genuine history; never update refs."""
from __future__ import annotations
import ast, base64, difflib, hashlib, io, json, os, pathlib, re, subprocess, sys, tarfile, tomllib, urllib.request
REPO='KirilsTurkins/latent-service-fabric'
BASE='68bd53e20eeeae109f7816c8e81a1f959158a93b'
ROOT=pathlib.Path(os.environ['GITHUB_WORKSPACE'])
TMP=pathlib.Path(os.environ['RUNNER_TEMP'])
WORK=TMP/'runtime-security-work'
OUT=TMP/'runtime-security-evidence'
OUT.mkdir(exist_ok=True)
def run(args, *, cwd=WORK, capture=False):
    if capture: return subprocess.check_output(args,cwd=cwd,text=True,timeout=1200).strip()
    subprocess.run(args,cwd=cwd,check=True,timeout=1800)
def sha(raw): return hashlib.sha256(raw).hexdigest()
def identity(raw): return {'sha256':sha(raw),'bytes':len(raw)}
def write_json(path,value): path.write_text(json.dumps(value,indent=2)+'\n')
def fetch(url):
    with urllib.request.urlopen(url,timeout=90) as r: return r.read(32*1024*1024)
def api(endpoint,value):
    request=OUT/'request.json';write_json(request,value)
    try: return json.loads(run(['gh','api','--method','POST',f'repos/{REPO}/git/{endpoint}','--input',str(request)],capture=True))
    finally: request.unlink(missing_ok=True)
def replace_checked(path,before,after):
    text=path.read_text();assert before in text, str(path)
    path.write_text(text.replace(before,after))
def rust_repair():
    locks=['Cargo.lock','crates/vendor/wasmtime/Cargo.lock','crates/vendor/wasmtime-cache/Cargo.lock','tools/native-fixture/Cargo.lock']
    before={p:(WORK/p).read_bytes() for p in locks}
    for p in locks:
        manifest=p.removesuffix('Cargo.lock')+'Cargo.toml'
        old=tomllib.loads(before[p].decode())
        selected=[r for r in old['package'] if r['name']=='rustix' and r['version'].startswith('1.')]
        assert len(selected)==1 and selected[0]['version'] in ('1.1.4','1.1.5')
        run(['cargo','update','--manifest-path',manifest,'-p','rustix@'+selected[0]['version'],'--precise','1.1.6'])
        after=tomllib.loads((WORK/p).read_text())
        without=lambda value:[r for r in value['package'] if r['name']!='rustix']
        assert without(old)==without(after), 'Unexpected dependency changes: '+p
        fixed=[r for r in after['package'] if r['name']=='rustix' and r['version'].startswith('1.')]
        assert len(fixed)==1 and fixed[0]['version']=='1.1.6'
    vendor=WORK/'crates/vendor/wasmtime';record_path=vendor/'UPSTREAM.latent.json'
    record=json.loads(record_path.read_text());original_record=record_path.read_bytes()
    raw=fetch(record['registryArchive']);assert sha(raw)==record['registrySha256']
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
        original=archive.extractfile('wasmtime-48.0.8/Cargo.lock').read()
    assert identity(original)==next({'sha256':r['sha256'],'bytes':r['bytes']} for r in record['originalFiles'] if r['path']=='Cargo.lock')
    patch=vendor/'latent-dynamic-memory.patch';text=patch.read_text()
    old=''.join(difflib.unified_diff(original.decode().splitlines(True),before[locks[1]].decode().splitlines(True),fromfile='a/Cargo.lock',tofile='b/Cargo.lock',n=record['patchContextLines']))
    assert text.startswith(old+'--- a/Cargo.toml\n'), 'Unexpected cumulative lock patch shape'
    new=''.join(difflib.unified_diff(original.decode().splitlines(True),(vendor/'Cargo.lock').read_text().splitlines(True),fromfile='a/Cargo.lock',tofile='b/Cargo.lock',n=record['patchContextLines']))
    patch.write_text(new+text[len(old):])
    record['cacheSecurityBackport']['postimages']['Cargo.lock']=identity((WORK/locks[2]).read_bytes())
    write_json(record_path,record)
    verifier=WORK/'tools/host_codec_wasmtime.py';source=verifier.read_text();tree=ast.parse(source)
    declaration=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='POSTIMAGES' for t in n.targets))
    value=ast.literal_eval(declaration.value)
    for p in ['Cargo.lock','latent-dynamic-memory.patch']: value[p]=identity((vendor/p).read_bytes())
    lines=source.splitlines(True)
    lines[declaration.lineno-1:declaration.end_lineno]=['POSTIMAGES = '+json.dumps(value,indent=4)+'\n']
    source=''.join(lines)
    assert sha(original_record) in source
    source=source.replace(sha(original_record),sha(record_path.read_bytes()))
    verifier.write_text(source)
    write_json(OUT/'rust-lock-changes.json',{p:{'before':identity(before[p]),'after':identity((WORK/p).read_bytes())} for p in locks})
def dotnet_repair():
    projects=[]
    for p in sorted((WORK/'sdk/dotnet').rglob('*.csproj')):
        text=p.read_text()
        if '<RuntimeFrameworkVersion>8.0.33</RuntimeFrameworkVersion>' in text:
            p.write_text(text.replace('<RuntimeFrameworkVersion>8.0.33</RuntimeFrameworkVersion>','<RuntimeFrameworkVersion>8.0.34</RuntimeFrameworkVersion>'));projects.append(p)
    assert len(projects)==9
    replace_checked(WORK/'sdk/dotnet/global.json','8.0.427','8.0.428')
    replace_checked(WORK/'tools/toolchain.toml','dotnet = "8.0.427"','dotnet = "8.0.428"')
    # Only active workflow/tool declarations and their review fragments change.
    selected=[*(WORK/'.github/workflows').glob('*.yml'),*(WORK/'tools').rglob('*.py'),*(WORK/'tools/ci/contracts').rglob('*.json')]
    for p in selected:
        text=p.read_text()
        if '8.0.427' in text: p.write_text(text.replace('8.0.427','8.0.428'))
    test=WORK/'tools/tests/test_security_sdk_graphs.py'
    replace_checked(test,'8.0.33','8.0.34')
    inventory=WORK/'.github/security/inventory.json';data=json.loads(inventory.read_text())
    for row in data['manifests']:
        path=WORK/row['path']
        if path in projects: row['manifest_sha256']=sha(path.read_bytes())
        config=row.get('configuration',[])
        if isinstance(config,list):
            for item in config:
                if item.get('path')=='sdk/dotnet/global.json': item['sha256']=sha((WORK/item['path']).read_bytes())
    write_json(inventory,data)
    return projects
if sys.argv[1]=='build':
    run(['git','fetch','--no-tags','origin',BASE],cwd=ROOT)
    run(['git','worktree','add','--detach',str(WORK),BASE],cwd=ROOT)
    rust_repair();projects=dotnet_repair()
    # Review only changed delegated owners, retaining the exact existing boundaries.
    changed=run(['git','diff','--name-only'],capture=True).splitlines()
    for p in (WORK/'tools/ci/contracts').rglob('*.json'):
        text=p.read_text();updated=text
        for path in changed:
            if path.startswith('tools/ci/contracts/'): continue
            old=subprocess.check_output(['git','show',BASE+':'+path],cwd=WORK)
            new=(WORK/path).read_bytes()
            if sha(old) in updated: updated=updated.replace(sha(old),sha(new))
        if updated!=text:p.write_text(updated)
    run(['python3','-m','unittest','tools.tests.test_host_codec_wasmtime','tools.tests.test_security_sdk_graphs','tools.tests.test_ci_contracts','-v'])
    run(['cargo','test','-p','latent-wasmtime','--lib','backend::store','--locked'])
    run(['cargo','test','-p','latent-component-threading','--lib','--all-features','--locked'])
    assert run(['dotnet','--version'],cwd=WORK/'sdk/dotnet',capture=True)=='8.0.428'
    for p in projects:
        run(['dotnet','restore',str(p),'--configfile',str(WORK/'sdk/dotnet/nuget.transport.config'),'--locked-mode'],cwd=WORK/'sdk/dotnet')
    run(['dotnet','run','--project','Latent.Sdk.Transport.Tests/Latent.Sdk.Transport.Tests.csproj','--configuration','Release','--no-restore'],cwd=WORK/'sdk/dotnet')
    # A locked restore must not rewrite the NuGet dependency graph.
    assert not any(p.endswith('packages.lock.json') for p in run(['git','diff','--name-only'],capture=True).splitlines())
    run(['git','diff','--check']);run(['git','add','-u'])
    run(['git','-c','user.name=github-actions[bot]','-c','user.email=41898282+github-actions[bot]@users.noreply.github.com','commit','-m','fix(security): update rustix and pinned .NET 8 runtime'])
    write_json(OUT/'build.json',{'base':BASE,'tree':run(['git','rev-parse','HEAD^{tree}'],capture=True),'localCommit':run(['git','rev-parse','HEAD'],capture=True),'run':int(os.environ['GITHUB_RUN_ID']),'completed':True})
elif sys.argv[1]=='upload':
    receipt=json.loads((OUT/'build.json').read_text());assert receipt['base']==BASE
    entries=[]
    for path in run(['git','diff','--name-only',BASE,'HEAD'],capture=True).splitlines():
        data=(WORK/path).read_bytes();blob=api('blobs',{'content':base64.b64encode(data).decode(),'encoding':'base64'})['sha']
        assert blob==hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        entries.append({'path':path,'mode':run(['git','ls-files','--stage','--',path],capture=True).split()[0],'type':'blob','sha':blob})
    tree=api('trees',{'base_tree':run(['git','rev-parse',BASE+'^{tree}'],capture=True),'tree':entries})['sha'];assert tree==receipt['tree']
    receipt['commit']=api('commits',{'tree':tree,'parents':[BASE],'message':'fix(security): update rustix and pinned .NET 8 runtime'})['sha']
    write_json(OUT/'published.json',receipt);print(json.dumps(receipt))
elif sys.argv[1]=='collect':
    if WORK.is_dir():
        patch=subprocess.check_output(['git','diff','--binary',BASE],cwd=WORK)
        (OUT/'changes.patch').write_bytes(patch)
        for path in run(['git','diff','--name-only',BASE],capture=True).splitlines():
            p=WORK/path
            if p.is_file():
                target=OUT/'files'/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(p.read_bytes())
else: raise SystemExit('expected build/upload/collect')
