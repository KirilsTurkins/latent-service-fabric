#!/usr/bin/env python3
"""Build a fixed action at its selected parent; export exact objects, never refs."""
from __future__ import annotations
import base64, hashlib, json, os, pathlib, re, subprocess, sys
ROOT = pathlib.Path(os.environ['GITHUB_WORKSPACE'])
OUT = pathlib.Path(os.environ['RUNNER_TEMP']) / 'xml-repair-evidence'
OUT.mkdir(exist_ok=True)
BASE = os.environ['REVIEWED_BASE']
REPO = os.environ['GITHUB_REPOSITORY']
WORK = pathlib.Path(os.environ['RUNNER_TEMP']) / 'xml-repair-work'
def run(args, *, capture=False, cwd=WORK):
    return subprocess.check_output(args, cwd=cwd, text=True).strip() if capture else subprocess.run(args, cwd=cwd, check=True, timeout=1500)
def write_json(p, value):
    p.write_text(json.dumps(value, indent=2) + '\n')
def api(endpoint, value):
    request = OUT / 'api-request.json'
    write_json(request, value)
    try:
        return json.loads(run(['gh','api','--method','POST',f'repos/{REPO}/git/{endpoint}','--input',str(request)], capture=True))
    finally:
        request.unlink(missing_ok=True)
def identity(p):
    raw=p.read_bytes()
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'gitBlob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}
if sys.argv[1] == 'build':
    assert re.fullmatch(r'[0-9a-f]{40}', BASE)
    subprocess.run(['git','fetch','--no-tags','origin',BASE], cwd=ROOT, check=True)
    subprocess.run(['git','worktree','add','--detach',str(WORK),BASE], cwd=ROOT, check=True)
    assert run(['git','rev-parse','HEAD'], capture=True)==BASE
    package = WORK/'package.json'
    manifest=json.loads(package.read_text())
    oldlock=json.loads((WORK/'package-lock.json').read_text())
    original=identity(package)
    overrides=manifest.setdefault('overrides',{})
    if 'fast-xml-parser' in overrides:
        del overrides['fast-xml-parser']
    overrides['fast-xml-parser@5']='5.12.0'
    write_json(package,manifest)
    run(['npm','install','--package-lock-only','--ignore-scripts','--no-audit','--no-fund'])
    lock=json.loads((WORK/'package-lock.json').read_text())
    selected=[(p,row) for p,row in lock['packages'].items() if p.endswith('/fast-xml-parser')]
    assert selected and all(row['version']=='5.12.0' for _,row in selected), selected
    # Refresh the exact lock identity, retaining alias/duplicate protections.
    verifier=WORK/'.lsf-source/verify-rust-cache-lock.mjs'
    if verifier.exists():
        text=verifier.read_text()
        text,count=re.subn(r"const expectedLockSha256 = '[0-9a-f]{64}'", "const expectedLockSha256 = '"+identity(WORK/'package-lock.json')['sha256']+"'",text)
        assert count==1
        verifier.write_text(text)
    run(['npm','ci','--ignore-scripts','--no-audit','--no-fund'])
    if 'test:security-source' in manifest['scripts']:
        run(['npm','run','test:security-source'])
    if REPO.endswith('/lsf-upload-artifact'):
        run(['node','--test','.lsf-source/upload-source.test.mjs'])
    build='prepare' if REPO.endswith('/lsf-deploy-pages') else 'release' if REPO.endswith(('/lsf-upload-artifact','/lsf-download-artifact')) else 'build'
    run(['npm','run',build])
    if REPO.endswith('/lsf-rust-cache'):
        run(['npx','--no-install','linefix','dist'])
    # Runtime controls execute the installed registry package rather than a mock.
    for path,_ in selected:
        package_path=WORK/path
        test = OUT/('stop-node-'+str(len(list(OUT.glob('stop-node-*.cjs'))))+'.cjs')
        test.write_text("const assert=require('node:assert/strict');\nconst {XMLParser}=require("+json.dumps(str(package_path))+ ");\n"
          "assert.deepEqual(new XMLParser().parse('<r><v>12</v></r>'),{r:{v:12}});\n"
          "const parser=new XMLParser({stopNodes:['stop']});\n"
          "assert.equal(parser.parse('<stop><a>value</a></stop>').stop,'<a>value</a>');\n"
          "for (const n of [1000,10000,100000]) assert.throws(()=>parser.parse('<stop>'+'<a '.repeat(n)));\n"
          "console.log('fixed stop-node malformed-input and ordinary XML controls passed');\n")
        subprocess.run(['node',str(test)],cwd=WORK,check=True,timeout=10)
    if 'test' in manifest['scripts']:
        command=['npm','test']
        if 'jest' in manifest['scripts']['test']: command += ['--','--runInBand']
        run(command)
    changes=[]
    for path in sorted(set(oldlock['packages']) | set(lock['packages'])):
        old=oldlock['packages'].get(path); new=lock['packages'].get(path)
        if old != new:
            changes.append({'path':path,'before':old,'after':new})
    write_json(OUT/'dependency-changes.json',changes)
    run(['git','add','package.json','package-lock.json','dist'])
    if verifier.exists(): run(['git','add','.lsf-source/verify-rust-cache-lock.mjs'])
    status=run(['git','diff','--name-only'],capture=True)
    assert not status, 'Unexpected unstaged tracked changes: '+status
    paths=run(['git','diff','--cached','--name-only'],capture=True).splitlines()
    assert all(p in ['package.json','package-lock.json','.lsf-source/verify-rust-cache-lock.mjs'] or p.startswith('dist/') for p in paths), paths
    run(['git','diff','--cached','--check'])
    run(['git','-c','user.name=github-actions[bot]','-c','user.email=41898282+github-actions[bot]@users.noreply.github.com','commit','-m','fix(security): rebuild action with fast-xml-parser 5.12.0'])
    receipt={'repository':REPO,'base':BASE,'localCommit':run(['git','rev-parse','HEAD'],capture=True),'tree':run(['git','rev-parse','HEAD^{tree}'],capture=True),'workflowRun':int(os.environ['GITHUB_RUN_ID']),'selectedFastXmlParser':[p for p,_ in selected], 'files':{p:identity(WORK/p) for p in run(['git','ls-files'],capture=True).splitlines() if (WORK/p).is_file()},'commandsCompleted':True}
    write_json(OUT/'build.json',receipt)
    (OUT/'changes.patch').write_text(run(['git','diff','--binary',BASE,'HEAD'],capture=True)+'\n')
elif sys.argv[1] == 'upload':
    receipt=json.loads((OUT/'build.json').read_text())
    assert receipt['base']==BASE and receipt['repository']==REPO
    tree=[]
    for path in run(['git','diff','--name-only',BASE,'HEAD'],capture=True).splitlines():
        p=WORK/path
        if not p.exists():
            tree.append({'path':path,'mode':'100644','type':'blob','sha':None});continue
        raw=p.read_bytes()
        sha=api('blobs',{'encoding':'base64','content':base64.b64encode(raw).decode()})['sha']
        assert sha==identity(p)['gitBlob']
        mode=run(['git','ls-files','--stage','--',path],capture=True).split()[0]
        tree.append({'path':path,'mode':mode,'type':'blob','sha':sha})
    created=api('trees',{'base_tree':run(['git','rev-parse',BASE+'^{tree}'],capture=True),'tree':tree})
    assert created['sha']==receipt['tree']
    commit=api('commits',{'message':'fix(security): rebuild action with fast-xml-parser 5.12.0','tree':created['sha'],'parents':[BASE]})
    receipt['publishedCommit']=commit['sha']
    write_json(OUT/'published.json',receipt)
    print(json.dumps({'repository':REPO,'base':BASE,'commit':commit['sha'],'tree':created['sha'],'run':receipt['workflowRun']}))
else:
    raise SystemExit('expected build or upload')
