#!/usr/bin/env python3
"""Update the active Go compiler and verify the existing private source overlay."""
from __future__ import annotations
import base64,hashlib,json,os,pathlib,subprocess,sys
REPO='KirilsTurkins/latent-service-fabric'
BASE='68bd53e20eeeae109f7816c8e81a1f959158a93b'
ROOT=pathlib.Path(os.environ['GITHUB_WORKSPACE']);TMP=pathlib.Path(os.environ['RUNNER_TEMP'])
WORK=TMP/'go-security-work';OUT=TMP/'go-security-evidence';OUT.mkdir(exist_ok=True)
OLD_SHA='65efbc80fdc1fa2cd2631cad5b481777a68e8725f34e89f50fc6ac714e379b40'
NEW_SHA='7226736c2339719cda28fbf3a54d71aa63bcefe376e98cef00034268dab24840'
def run(args,*,cwd=WORK,capture=False,env=None):
    if capture:return subprocess.check_output(args,cwd=cwd,text=True,timeout=1500,env=env).strip()
    subprocess.run(args,cwd=cwd,check=True,timeout=1800,env=env)
def digest(b):return hashlib.sha256(b).hexdigest()
def write_json(p,v):p.write_text(json.dumps(v,indent=2)+'\n')
def api(endpoint,value):
    p=OUT/'request.json';write_json(p,value)
    try:return json.loads(run(['gh','api','--method','POST',f'repos/{REPO}/git/{endpoint}','--input',str(p)],capture=True))
    finally:p.unlink(missing_ok=True)
if sys.argv[1]=='build':
    run(['git','fetch','--no-tags','origin',BASE],cwd=ROOT)
    run(['git','worktree','add','--detach',str(WORK),BASE],cwd=ROOT)
    tracked=run(['git','ls-files'],capture=True).splitlines();changed={}
    for name in tracked:
        allowed=(name.startswith('.github/workflows/') and name.endswith('.yml') or name.startswith('tools/') and name.endswith('.py') or name.startswith('tools/ci/contracts/') and name.endswith('.json') or name.startswith('sdk/go') and name.endswith(('go.mod','toolchain.lock.json','dependencies.lock.json')) or name=='.github/security/graphs/published-smtp/dependencies.lock.json' or name=='tools/toolchain.toml')
        if not allowed:continue
        path=WORK/name;old=path.read_bytes();text=old.decode()
        updated=text.replace('1.27.3','1.27.4').replace(OLD_SHA,NEW_SHA)
        if name=='tools/dev_go_distribution.py':updated=updated.replace('"maximum": 70588678','"maximum": 70680823')
        if updated!=text:path.write_text(updated);changed[name]=(digest(old),digest(path.read_bytes()))
    modules={'sdk/go/dependencies.lock.json':'sdk/go','sdk/go-guest/runtime-deps/dependencies.lock.json':'sdk/go-guest/runtime-deps','.github/security/graphs/published-smtp/dependencies.lock.json':'sdk/go-guest/runtime/published-smtp-conformance'}
    for lock,directory in modules.items():
        p=WORK/lock;j=json.loads(p.read_text());assert j['goVersion']=='1.27.4'
        j['manifestSha256']=digest((WORK/directory/'go.mod').read_bytes())
        assert j['sumSha256']==digest((WORK/directory/'go.sum').read_bytes())
        write_json(p,j)
    for p in (WORK/'tools/ci/contracts').rglob('*.json'):
        old=p.read_text();text=old
        for name,(pre,post) in changed.items():
            if not name.startswith('tools/ci/contracts/'):text=text.replace(pre,post)
        if old!=text:p.write_text(text)
    compiler=TMP/'go-distribution/go';assert (compiler/'VERSION').read_text().splitlines()[0]=='go1.27.4'
    assert digest((TMP/'go-security.tar.gz').read_bytes())==NEW_SHA
    environment={**os.environ,'PATH':str(compiler/'bin')+os.pathsep+os.environ['PATH'],'GOTOOLCHAIN':'local','GOROOT':str(compiler)}
    assert 'go1.27.4' in run(['go','version'],env=environment,capture=True)
    # Verify every old source preimage and every transformed postimage unchanged.
    run(['python3','-c',"from pathlib import Path;from tools.go_guest.runtime import prepare_compiler;prepare_compiler(Path("+repr(str(compiler))+"),Path("+repr(str(TMP/'go-private-compiler'))+"));print('Actual 1.27.4 source preimages and private overlay postimages verified')"])
    names=[p.removesuffix('.py').replace('/','.') for p in tracked if p.startswith('tools/tests/test_go_') and p.endswith('.py')]
    run(['python3','-c','import unittest; names='+repr(names)+'; suite=unittest.defaultTestLoader.loadTestsFromNames(names); result=unittest.TextTestRunner(verbosity=2).run(suite); raise SystemExit(not result.wasSuccessful() or bool(result.skipped))'],env=environment)
    run(['python3','-m','unittest','tools.tests.test_security_sdk_graphs','tools.tests.test_ci_contracts','-v'],env=environment)
    run(['go','test','-mod=readonly','./...'],cwd=WORK/'sdk/go',env=environment)
    for directory in modules.values():
        run(['go','list','-mod=readonly','-m','all'],cwd=WORK/directory,env=environment)
    assert not any(p.endswith('go.sum') for p in run(['git','diff','--name-only'],capture=True).splitlines())
    run(['git','diff','--check']);run(['git','add','-u'])
    run(['git','-c','user.name=github-actions[bot]','-c','user.email=41898282+github-actions[bot]@users.noreply.github.com','commit','-m','fix(security): select authenticated Go 1.27.4 compiler'])
    write_json(OUT/'build.json',{'base':BASE,'tree':run(['git','rev-parse','HEAD^{tree}'],capture=True),'localCommit':run(['git','rev-parse','HEAD'],capture=True),'run':int(os.environ['GITHUB_RUN_ID']),'completed':True})
elif sys.argv[1]=='upload':
    receipt=json.loads((OUT/'build.json').read_text());assert receipt['base']==BASE;entries=[]
    for path in run(['git','diff','--name-only',BASE,'HEAD'],capture=True).splitlines():
        data=(WORK/path).read_bytes();blob=api('blobs',{'content':base64.b64encode(data).decode(),'encoding':'base64'})['sha']
        assert blob==hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        entries.append({'path':path,'mode':run(['git','ls-files','--stage','--',path],capture=True).split()[0],'type':'blob','sha':blob})
    tree=api('trees',{'base_tree':run(['git','rev-parse',BASE+'^{tree}'],capture=True),'tree':entries})['sha'];assert tree==receipt['tree']
    receipt['commit']=api('commits',{'tree':tree,'parents':[BASE],'message':'fix(security): select authenticated Go 1.27.4 compiler'})['sha']
    write_json(OUT/'published.json',receipt);print(json.dumps(receipt))
elif sys.argv[1]=='collect':
    if WORK.is_dir():
        (OUT/'changes.patch').write_bytes(subprocess.check_output(['git','diff','--binary',BASE],cwd=WORK))
        for path in run(['git','diff','--name-only',BASE],capture=True).splitlines():
            p=WORK/path
            if p.is_file():
                target=OUT/'files'/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(p.read_bytes())
else:raise SystemExit('expected build/upload/collect')
