#!/usr/bin/env python3
"""Build exact maintained-action security successors; never change a branch ref."""
from __future__ import annotations
import argparse, base64, hashlib, json, os, pathlib, re, subprocess, tempfile
ROOT = pathlib.Path.cwd()
OUT = pathlib.Path(os.environ['RUNNER_TEMP']) / 'action-security-evidence'
OUT.mkdir(exist_ok=True)
BASES = {
'cache':'ec176dce9471270c8a9be1289040c0a8fd6aa708',
'deploy-pages':'e249fe4e7520b3d7aa16ef72f45eeb05de6cf4f6',
'download-artifact':'dd4ebbadbf12ed34441db2712be7a193490b7fc5',
'rust-cache':'38534d49940bc6c6aef1e8dfd45349a99d37f14e',
'setup-dotnet':'258c927924210be905f8908a4be714e5d0daffa8',
'setup-go':'1020042799f722e9ef016bf63106367879587a49',
'setup-java':'63c7977881fc344a6ed464f7ed5e242aedc8d56c',
'setup-node':'34275fdec80b5be172c3327cadef76aa2f3b31c6',
'setup-python':'164c4cbba5d1b03a046ac8bc25ae695bee0667a8',
'setup-zig':'e064b42fa88ad0859d8b54838b44f672ffd5ea7a',
'upload-artifact':'d74a697ce553b389f4219545e07c97fb8542c64f',
}
def run(*args, timeout=600):
    return subprocess.check_output(args, text=True, timeout=timeout).strip()
def ident(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'gitBlob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}
def logrun(name, args, timeout=900):
    with (OUT/(name+'.log')).open('wb') as out:
        p = subprocess.run(args, stdout=out, stderr=subprocess.STDOUT, timeout=timeout)
    if p.returncode:
        print((OUT/(name+'.log')).read_text(errors='replace')[-16000:])
        raise RuntimeError(f'{name} failed with {p.returncode}')
    return {'command':args,'exit':p.returncode,'log':ident((OUT/(name+'.log')).read_bytes())}
def package_sources():
    result = {}
    for p in ROOT.glob('node_modules/**/package.json'):
        if any(x in {'.cache','.bin'} for x in p.parts): continue
        try: v=json.loads(p.read_text())
        except (ValueError,OSError): continue
        if v.get('name') in {'deepmerge','minimatch','glob','fast-xml-parser'}:
            files={q.relative_to(p.parent).as_posix():ident(q.read_bytes())
                   for q in p.parent.rglob('*') if q.is_file() and 'node_modules' not in q.relative_to(p.parent).parts}
            result[p.parent.relative_to(ROOT).as_posix()]={'name':v['name'],'version':v['version'],'files':files}
    return result
PROBE = r'''
import {readFileSync,writeFileSync,cpSync,mkdtempSync,rmSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const source=resolve('node_modules/fast-xml-parser');
const temp=mkdtempSync(resolve('node_modules/.lsf-fastxml-'));
try {
  cpSync(source,temp,{recursive:true});
  const p=join(temp,'src/xmlparser/OrderedObjParser.js');
  let text=readFileSync(p,'utf8');
  const marker=/function readTagExp\([^\n]*\)\s*\{/g;
  assert.equal([...text.matchAll(marker)].length,1,'unexpected parser scan shape');
  text=text.replace(marker, m=>m+'globalThis.__lsfTagScans++;');
  writeFileSync(p,text);
  const {XMLParser}=await import(pathToFileURL(join(temp,'src/fxp.js')));
  const observations=[];
  for (const size of [32,64,128]) {
    globalThis.__lsfTagScans=0;
    assert.throws(()=>new XMLParser({stopNodes:['stop']}).parse('<stop>'+'<a '.repeat(size)));
    observations.push({size,scans:globalThis.__lsfTagScans});
  }
  if (process.argv[2]==='fixed') {
    assert.ok(observations.every(x=>x.scans<=3),'unterminated stop-node scan must be bounded');
    assert.equal(new XMLParser({stopNodes:['stop']}).parse('<stop><a>text</a></stop>').stop,'<a>text</a>');
    assert.equal(new XMLParser({stopNodes:['stop']}).parse('<stop>hello &amp; goodbye</stop>').stop,'hello &amp; goodbye');
  } else assert.ok(observations.every(x=>x.scans>=x.size),'baseline must reproduce repeated scans');
  console.log(JSON.stringify({phase:process.argv[2],observations}));
} finally {rmSync(temp,{recursive:true,force:true});}
'''
def prepare(role):
    base=BASES[role]
    assert os.environ['GITHUB_REPOSITORY']=='KirilsTurkins/lsf-'+role
    assert run('git','rev-parse','HEAD')==base
    before={p:ident((ROOT/p).read_bytes()) for p in run('git','ls-files').splitlines() if (ROOT/p).is_file()}
    checks=[]
    checks.append(logrun('baseline-ci',['npm','ci','--ignore-scripts','--no-audit','--no-fund']))
    probe=OUT/'fastxml-probe.mjs';probe.write_text(PROBE)
    checks.append(logrun('baseline-parser',['node',str(probe),'original']))
    old_lock=json.loads((ROOT/'package-lock.json').read_text())
    manifest=json.loads((ROOT/'package.json').read_text())
    direct=False
    for section in ('dependencies','devDependencies','optionalDependencies'):
        if 'fast-xml-parser' in manifest.get(section,{}):
            manifest[section]['fast-xml-parser']='5.12.0';direct=True
    overrides=manifest.setdefault('overrides',{})
    for key in list(overrides):
        if key=='fast-xml-parser' or key.startswith('fast-xml-parser@'): del overrides[key]
    overrides['fast-xml-parser']='$fast-xml-parser' if direct else '5.12.0'
    (ROOT/'package.json').write_text(json.dumps(manifest,indent=2)+'\n')
    checks.append(logrun('resolve',['npm','install','--package-lock-only','--ignore-scripts','--no-audit','--no-fund']))
    lock=json.loads((ROOT/'package-lock.json').read_text())
    xml=[v for p,v in lock['packages'].items() if p.endswith('node_modules/fast-xml-parser')]
    assert xml and all(v['version']=='5.12.0' for v in xml)
    # Previously repaired tarball dependencies cannot be changed by resolution.
    for path,value in old_lock['packages'].items():
        if str(value.get('resolved','')).startswith('file:'):
            assert lock['packages'].get(path)==value,(path,'repaired package changed')
    if role=='rust-cache':
        old=before['package-lock.json']['sha256'];new=ident((ROOT/'package-lock.json').read_bytes())['sha256']
        for name in ('verify-rust-cache-lock.mjs','rust-cache-lock.test.mjs'):
            p=ROOT/'.lsf-source'/name;text=p.read_text();assert text.count(old)==1
            p.write_text(text.replace(old,new))
    checks.append(logrun('fixed-ci',['npm','ci','--ignore-scripts','--no-audit','--no-fund']))
    checks.append(logrun('fixed-parser',['node',str(probe),'fixed']))
    scripts=manifest.get('scripts',{})
    if role=='deploy-pages':
        checks.append(logrun('prepare',['npm','run','prepare']))
    elif role=='rust-cache':
        checks.append(logrun('prepare',['npm','run','prepare']))
    else:
        checks.append(logrun('build',['npm','run','build']))
        if role in {'upload-artifact','download-artifact'}:
            checks.append(logrun('release',['npm','run','release']))
    if 'test:security-source' in scripts:
        checks.append(logrun('source-controls',['npm','run','test:security-source']))
    if role=='upload-artifact':
        checks.append(logrun('source-controls',['node','--test','.lsf-source/upload-source.test.mjs']))
    if 'test' in scripts:
        args=['npm','test']
        if 'jest' in scripts['test'] and '--runInBand' not in scripts['test']:args+=['--','--runInBand']
        checks.append(logrun('tests',args))
    installed=package_sources()
    # Capture only intended outputs, never generated tools, caches or the temporary workflow.
    allowed=['package.json','package-lock.json','dist']
    if role=='rust-cache': allowed+=['.lsf-source/verify-rust-cache-lock.mjs','.lsf-source/rust-cache-lock.test.mjs']
    run('git','reset','--quiet')
    run('git','add','-f','--',*allowed)
    changed=run('git','diff','--cached','--name-only').splitlines()
    assert changed and all(p in allowed or p.startswith('dist/') for p in changed)
    (OUT/'change.patch').write_text(run('git','diff','--cached','--binary')+'\n')
    tree=run('git','write-tree')
    entries=[]
    for line in run('git','diff','--cached','--raw','--no-abbrev').splitlines():
        meta,path=line.split('\t');items=meta.split();mode=items[1];sha=items[3]
        entries.append({'path':path,'mode':items[0][1:] if mode=='000000' else mode,'type':'blob','sha':None if set(sha)=={'0'} else sha})
    runtime={p:ident((ROOT/p).read_bytes()) for p in run('git','ls-files','dist').splitlines() if (ROOT/p).is_file()}
    inputs={p:ident((ROOT/p).read_bytes()) for p in run('git','ls-files').splitlines()
            if p in {'package.json','package-lock.json','action.yml','restore/action.yml','save/action.yml'} or p.startswith('.lsf-source/')}
    for path in inputs:
        p=OUT/'inputs'/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/path).read_bytes())
    receipt={'schema':1,'repository':os.environ['GITHUB_REPOSITORY'],'base':base,'tree':tree,
             'workflowHead':os.environ['GITHUB_SHA'],'run':int(os.environ['GITHUB_RUN_ID']),
             'node':run('node','--version'),'npm':run('npm','--version'),
             'inputs':inputs,'runtime':runtime,'installed':installed,'checks':checks,'changes':entries,
             'baseInputs':{p:before[p] for p in inputs if p in before}}
    (OUT/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'role':role,'tree':tree,'checks':len(checks),'changedFiles':len(changed)}))
def export(role):
    receipt=json.loads((OUT/'receipt.json').read_text());repo=receipt['repository']
    assert repo==os.environ['GITHUB_REPOSITORY']=='KirilsTurkins/lsf-'+role
    def api(endpoint,payload):
        p=subprocess.run(['gh','api','--method','POST',f'repos/{repo}/git/{endpoint}','--input','-'],
                         input=json.dumps(payload),text=True,capture_output=True,timeout=120,check=True)
        return json.loads(p.stdout)
    for item in receipt['changes']:
        if item['sha']:
            raw=subprocess.check_output(['git','cat-file','blob',item['sha']]);assert ident(raw)['gitBlob']==item['sha']
            got=api('blobs',{'encoding':'base64','content':base64.b64encode(raw).decode()})
            assert got['sha']==item['sha']
    tree=api('trees',{'base_tree':run('git','rev-parse',receipt['base']+'^{tree}'),'tree':receipt['changes']})
    assert tree['sha']==receipt['tree']
    commit=api('commits',{'tree':tree['sha'],'parents':[receipt['base']],
             'message':'fix(security): rebuild maintained action with fast-xml-parser 5.12.0'})
    receipt['commit']=commit['sha'];(OUT/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'repository':repo,'commit':commit['sha'],'tree':tree['sha'],'branchRefsChanged':False}))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['prepare','export']);p.add_argument('role',choices=BASES)
    a=p.parse_args();globals()[a.phase](a.role)
