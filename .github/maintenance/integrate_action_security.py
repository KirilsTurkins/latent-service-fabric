#!/usr/bin/env python3
"""Integrate independently tested action objects into an existing real worktree."""
from __future__ import annotations
import ast,base64,hashlib,io,json,os,pathlib,pprint,re,shutil,subprocess,zipfile
ROOT=pathlib.Path(os.environ['GITHUB_WORKSPACE'])
WORK=pathlib.Path(os.environ['SECURITY_WORKTREE'])
OUT=pathlib.Path(os.environ['RUNNER_TEMP'])/'action-integration-evidence';OUT.mkdir(exist_ok=True)
PINS={
'cache':('ec176dce9471270c8a9be1289040c0a8fd6aa708','2571c499f8aa6b4db4b4b5632bea291d6be58dc8',43520669136,14081759281,'9cf0599fd0232c8b61f9bf4c26ad662b314c9636a08ae20b155e1f78641c0c4f'),
'deploy-pages':('e249fe4e7520b3d7aa16ef72f45eeb05de6cf4f6','f596449d219e8fe3fe62b26b0a4dfc4fbb89334b',43523076094,14083337324,'198295a9c2e59b458d36ed1452c27e6b165bec70c19cc3217ad889913b9221a7'),
'download-artifact':('dd4ebbadbf12ed34441db2712be7a193490b7fc5','fc27fb5305d2042f110912a9d6a2924a98084389',43523093794,14084640639,'fe64b54751cd45ca551bde6e34d6180eea46747e267167b1fa268109686c3cf8'),
'rust-cache':('38534d49940bc6c6aef1e8dfd45349a99d37f14e','653972653a76770ab9b45cca67e4db8221bed334',43524567232,14084761784,'aefc5b7a2e64440d6ba43554c1a6b5064d7a5358dfada2368f7163df7e5b82ee'),
'setup-dotnet':('258c927924210be905f8908a4be714e5d0daffa8','2382c9e63a3b678b643c7e715d023e7fa42fbbef',43523131630,14084246508,'7599f3c0b77d1fe1fc2554c25d12151a27178c3a210baba8a2280c24409300df'),
'setup-go':('1020042799f722e9ef016bf63106367879587a49','92a5903f5ff2b45e67c517d23c18501025a55a12',43523168939,14083841811,'399e84076473de39784ad27e5ab64cddd3a84b22160f0651286c3a60372fac27'),
'setup-java':('63c7977881fc344a6ed464f7ed5e242aedc8d56c','8aaa4ea8191b36cb3f394e91d099da0d31dc02c2',43523148275,14084750338,'58d98b140e38c507ad5953f6ac5208d1b85673f9d641c03f01d1bbfa0cbcc96e'),
'setup-node':('34275fdec80b5be172c3327cadef76aa2f3b31c6','791d25988f7dc57f537b82342f7af452cd59cd6a',43520897619,14082409632,'67e547bc559ad3b5f82f281c8c13d9237dc073ad50db302bb12569422706820f'),
'setup-python':('164c4cbba5d1b03a046ac8bc25ae695bee0667a8','e0788870ab0f74690a1d3f187ba206c395748aee',43523184991,14083891957,'c8620a56d8edbab6d83d64f1937cd0a1def2581cfa2d99b4e373b347ff6a2f4'),
'setup-zig':('e064b42fa88ad0859d8b54838b44f672ffd5ea7a','adb5ed78414674f693e8fe00982f83df9badcdb3',43523206484,14083113248,'e272b91d67f548019250c07fdb946b0aac543e46fcf6d6eebbccbac4b77ed886'),
'upload-artifact':('d74a697ce553b389f4219545e07c97fb8542c64f','c37718fd4e24a4c372572ce4f21b3969a72ba8dc',43523231069,14083822784,'8ca47a574c616b4adcc1fccc4d3054cd4b223f8180b2861020084117d06504e3')}
PROFILES={'setup-python':'setup-python-minimatch','setup-go':'setup-go-minimatch','setup-java':'setup-java-minimatch','setup-node':'setup-node-minimatch','setup-dotnet':'setup-dotnet-minimatch','rust-cache':'rust-cache-source','deploy-pages':'deploy-pages-source','upload-artifact':'upload-artifact-source','download-artifact':'download-artifact-source'}
def api(path):return json.loads(subprocess.check_output(['gh','api',path],text=True,timeout=120))
def identity(data):return {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'gitBlob':hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()}
def write_json(path,value):path.write_text(json.dumps(value,indent=2)+'\n')
def run(args):return subprocess.check_output(args,cwd=WORK,text=True,timeout=120).strip()
assert not run(['git','status','--porcelain','--untracked-files=no'])
oldhead=run(['git','rev-parse','HEAD'])
actions=json.loads((WORK/'.github/security/actions.json').read_text())
identities={};records={};references={};runtime_maps={};build_urls={}
for name,(base,commit,number,artifact_id,checksum) in PINS.items():
    repo='KirilsTurkins/lsf-'+name;prefix='repos/'+repo
    meta=api(prefix+'/actions/runs/'+str(number))
    assert meta['conclusion']=='success'
    data=subprocess.check_output(['gh','api',prefix+'/actions/artifacts/'+str(artifact_id)+'/zip'],timeout=120)
    assert hashlib.sha256(data).hexdigest()==checksum,(name,'artifact')
    (OUT/(name+'.zip')).write_bytes(data)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        record=json.loads(archive.read('published.json'));log=archive.read('validation.log')
    assert record['repository']==repo and record['base']==base and record['publishedCommit']==commit and record['workflowRun']==number
    commit_info=api(prefix+'/git/commits/'+commit)
    assert [v['sha'] for v in commit_info['parents']]==[base] and commit_info['tree']['sha']==record['tree']
    records[name]=record
    before=repo+'@'+base;after=repo+'@'+commit;references[before]=after
    row=actions['actions'].pop(before);assert row['revision']==base;row['revision']=commit
    for item in row['files']:
        path=WORK/item['snapshot'];original=path.read_bytes();expected=record['files'][item['source']]
        if identity(original)==expected:updated=original
        else:
            value=api(prefix+'/contents/'+item['source']+'?ref='+commit)
            assert value['encoding']=='base64';updated=base64.b64decode(value['content'])
            assert identity(updated)==expected,(name,item['source'])
            path.write_bytes(updated)
        identities[identity(original)['sha256']]=identity(updated)
        item['sha256']=item['source_sha256']=identity(updated)['sha256']
    row['metadata']=dict(next(v for v in row['files'] if v['source']==row['metadata']['source']))
    actions['actions'][after]=row
    if name in PROFILES:
        p=WORK/f'.github/security/actions/{PROFILES[name]}/fork-build.json';old=p.read_bytes();prior=json.loads(old)
        assert prior['publishedRevision']==base
        if name=='rust-cache':paths=['dist/restore/index.js','dist/save/index.js',*sorted(k for k in record['files'] if k.startswith('dist/') and k.endswith('.js') and k not in ('dist/restore/index.js','dist/save/index.js'))]
        elif name=='setup-go':paths=['dist/setup/index.js','dist/cache-save/index.js']
        elif name=='deploy-pages':paths=['dist/index.js']
        elif name in ('upload-artifact','download-artifact'):paths=['dist/index.js','dist/index.js.map']
        elif name=='setup-python':paths=['dist/setup/index.js','dist/cache-save/index.js']
        elif name=='setup-java':paths=['dist/setup/index.js','dist/cleanup/index.js',*sorted(k for k in record['files'] if k.startswith('dist/') and k.endswith('.index.js'))]
        elif name=='setup-node':paths=['dist/setup/index.js','dist/cache-save/index.js']
        else:paths=['dist/setup/index.js','dist/cache-save/index.js']
        runtime_maps[name]={path:record['files'][path] for path in paths}
        text=log.decode();assert 'fixed stop-node malformed-input and ordinary XML controls passed' in text
        tests=re.findall(r'Tests:\s+(\d+) passed, (\d+) total',text);suites=re.findall(r'Test Suites:\s+(\d+) passed, (\d+) total',text)
        assert all(a==b for a,b in tests+suites)
        installed=[]
        for line in text.splitlines():
            if not line.startswith('{'):continue
            try:v=json.loads(line)
            except ValueError:continue
            if isinstance(v,dict) and ('installed' in v.get('kind','') or v.get('kind')=='rust-cache-lock-source-assertion') and v not in installed:installed.append(v)
        assert installed and all(v['sourceCommit']==meta['head_sha'] for v in installed)
        updated={'schema':2,'repository':repo,'publishedRevision':commit,'publishedTree':record['tree'],'base':base,'testedCommit':record['localCommit'],'diagnosticHead':meta['head_sha'],'run':number,'jobConclusion':'success','toolchain':{'node':'24.19.0'},'artifact':{'id':artifact_id,'bytes':len(data),'sha256':checksum},'validationLog':identity(log),'validation':{'sourceControlsPassed':True,'xmlRegressionPassed':True,'unitTests':int(tests[-1][0]) if tests else None,'unitSuites':int(suites[-1][0]) if suites else None},'sourceFiles':{v['source']:record['files'][v['source']] for v in row['files']},'outputs':runtime_maps[name],'installedSourceAssertions':installed,'previousEvidence':prior,'scope':'Exact source/bundle rebuild and finite controls; no signed SDK or release qualification.'}
        write_json(p,updated);identities[identity(old)['sha256']]=identity(p.read_bytes());build_urls[p.relative_to(WORK).as_posix()]='https://github.com/'+repo+'/actions/runs/'+str(number)
# The composite points to the actual newly rebuilt upload implementation.
old='28d7597d6f6497a5d34e5ecaa1d97c510ce3556b';new='e6e68b294bf8395e09cb1979426d1b579ef1760d';repo='KirilsTurkins/lsf-upload-pages-artifact'
row=actions['actions'].pop(repo+'@'+old);row['revision']=new
for item in row['files']:
    if item['source']!='action.yml':continue
    p=WORK/item['snapshot'];raw=p.read_bytes().replace(PINS['upload-artifact'][0].encode(),PINS['upload-artifact'][1].encode())
    assert identity(raw)['gitBlob']=='7f7422a6a226eb804e9b6274a20acdb8fe2a222d';p.write_bytes(raw);item['sha256']=item['source_sha256']=identity(raw)['sha256']
row['metadata']=dict(next(x for x in row['files'] if x['source']=='action.yml'));actions['actions'][repo+'@'+new]=row;references[repo+'@'+old]=repo+'@'+new
write_json(WORK/'.github/security/actions.json',actions)
def replace(value):
    if isinstance(value,str):
        for a,b in references.items():value=value.replace(a,b)
        return value
    if isinstance(value,dict):
        result={k:replace(v) for k,v in value.items()}
        if value.get('sha256') in identities:
            for key in ('bytes','sha256','gitBlob'):
                if key in result:result[key]=identities[value['sha256']][key]
        if value.get('snapshot') in build_urls and 'source' in value:result['source']=build_urls[value['snapshot']]
        return result
    if isinstance(value,tuple):
        if len(value)==4 and isinstance(value[0],str) and value[2] in identities:
            v=identities[value[2]];return(value[0],v['bytes'],v['sha256'],v['gitBlob'])
        return tuple(map(replace,value))
    if isinstance(value,list):return list(map(replace,value))
    return value
def assignment(path,key,transform):
    text=path.read_text();node=next(n for n in ast.parse(text).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==key for t in n.targets))
    value=transform(ast.literal_eval(node.value));lines=text.splitlines(True);lines[node.lineno-1:node.end_lineno]=[key+' = '+pprint.pformat(value,width=110,sort_dicts=False)+'\n'];path.write_text(''.join(lines))
for path in (WORK/'.github/security').glob('*.json'):
    if path.name=='actions.json':continue
    old=json.loads(path.read_text());updated=replace(old)
    if updated!=old:write_json(path,updated)
mods={'security_setup_go':'setup-go','security_rust_cache':'rust-cache','security_upload_artifact':'upload-artifact','security_download_artifact':'download-artifact','security_deploy_pages':'deploy-pages','security_dotnet_minimatch':'setup-dotnet','security_npm_sources':None}
for module,name in mods.items():
    path=WORK/'tools'/f'{module}.py';tree=ast.parse(path.read_text())
    for node in tree.body:
        if not isinstance(node,ast.Assign) or len(node.targets)!=1 or not isinstance(node.targets[0],ast.Name):continue
        try:ast.literal_eval(node.value)
        except (ValueError,TypeError):continue
        assignment(path,node.targets[0].id,replace)
    if name:
        def runtimes(old):
            values=runtime_maps[name]
            return {key:{'source':row['source'],**values[row['source']]} for key,row in old.items()} if module=='security_dotnet_minimatch' else values
        assignment(path,'RUNTIME',runtimes)
path=WORK/'tools/security_npm_sources.py'
for const,name in [('MINIMATCH_RUNTIME','setup-python'),('JAVA_MINIMATCH_RUNTIME','setup-java'),('NODE_MINIMATCH_RUNTIME','setup-node')]:
    assignment(path,const,lambda old,n=name:{key:{'source':row['source'],**runtime_maps[n][row['source']]} for key,row in old.items()})
# Byte-authentication and source reconstruction remain in their original callers.
for module in mods:
    path=WORK/'tools'/f'{module}.py';text=path.read_text();text=text.replace('from tools.security_common import','from tools.security_action_rebuild import verify_rebuild\nfrom tools.security_common import',1)
    if module=='security_setup_go':a=text.index('    build = decode_json(mini["build"])');b=text.index('    graph_guard(owner, lock)',a);text=text[:a]+'    build = decode_json(mini["build"])\n    verify_rebuild(repo, build, REFERENCE, RUNTIME)\n'+text[b:]
    elif module=='security_rust_cache':a=text.index('    build = decode_json(mini["build"])');b=text.index('    require(decode_json(inputs["package.json"])',a);text=text[:a]+'    build = decode_json(mini["build"])\n    verify_rebuild(repo, build, REFERENCE, RUNTIME)\n'+text[b:]
    elif module in ('security_upload_artifact','security_download_artifact'):
        a=text.index('    build = decode_json(_read(repo, BUILD))');b=text.index('    if fetch_runtime is None:',a);text=text[:a]+'    build = decode_json(_read(repo, BUILD))\n    verify_rebuild(repo, build, REFERENCE, RUNTIME)\n'+text[b:]
    elif module=='security_deploy_pages':a=text.index('    build = decode_json(_read(repo, BUILD))');b=text.index('\n\ndef graph_guard',a);text=text[:a]+'    build = decode_json(_read(repo, BUILD))\n    verify_rebuild(repo, build, REFERENCE, RUNTIME)\n    return inputs'+text[b:]
    elif module=='security_dotnet_minimatch':a=text.index('    build = decode_json(material["build"])');b=text.index('    return policy, material',a);text=text[:a]+'    build = decode_json(material["build"])\n    verify_rebuild(repo, build, REFERENCE, RUNTIME)\n'+text[b:]
    else:
        for decl,nextfunc,ref,runtime in [('build = decode_json(material["build"])','\n\ndef _source_entries','MINIMATCH_REFERENCE','MINIMATCH_RUNTIME'),("build = decode_json(material['build'])",'\n\ndef verify_java_action','JAVA_MINIMATCH_REFERENCE','JAVA_MINIMATCH_RUNTIME'),("build = decode_json(material['build'])",'\n\ndef verify_node_action','NODE_MINIMATCH_REFERENCE','NODE_MINIMATCH_RUNTIME')]:
            start=0 if ref=='MINIMATCH_REFERENCE' else text.index('def _'+('java' if ref.startswith('JAVA') else 'node')+'_minimatch_material')
            a=text.index('    '+decl,start);b=text.index(nextfunc,a);text=text[:a]+'    '+decl+'\n    verify_rebuild(repo, build, '+ref+', '+runtime+')\n    return policy, material\n'+text[b:]
    path.write_text(text)
# Active workflow refs and expected guarded command fragments rotate together.
for path in [*(WORK/'.github/workflows').glob('*.yml'),*(WORK/'tools').rglob('*.py'),*(WORK/'tools/ci/contracts').rglob('*.json')]:
    text=path.read_text();updated=replace(text)
    if text!=updated:path.write_text(updated)
# Keep old immutable inverse outputs; only its selected input changes.
p=WORK/'tools/tests/test_sdk_scratch_qualification.py';text=p.read_text()
for old,new in references.items():
    repo,oldsha=old.rsplit('@',1);newsha=new.rsplit('@',1)[1]
    text=text.replace("('"+repo+"', '"+oldsha+"',", "('"+repo+"', '"+newsha+"',")
p.write_text(text)
for p in (WORK/'tools/tests').glob('test_security_*.py'):
    text=p.read_text()
    for base,new,_,_,_ in PINS.values():
        for size in (8,40):
            text=text.replace('.replace("'+base[:size]+'",','.replace("'+new[:size]+'",').replace(".replace('"+base[:size]+"',",".replace('"+new[:size]+"',")
        text=text.replace("revision = '"+base+"'", "revision = '"+new+"'")
    p.write_text(text)
p=WORK/'tools/security_actions.py';text=p.read_text()
for name in ('setup-java','setup-node'):text=text.replace(PINS[name][0],PINS[name][1])
p.write_text(text)
p=WORK/'tools/tests/test_security_deploy_pages.py';p.write_text(p.read_text().replace('build["bundles"] = identities','build["outputs"] = identities'))
p=WORK/'tools/tests/test_security_dotnet_minimatch_action.py';text=p.read_text();a=text.index('        payloads = copy.deepcopy(');b=text.index('        policy_path = ',a);text=text[:a]+text[b:];text=text.replace("        build['artifact']['payloads'] = payloads", "        build['outputs'] = {row['source']: {key: row[key] for key in ('bytes', 'sha256', 'gitBlob')}\n                            for row in runtime_policy.values()}").replace(", ('ARTIFACT_PAYLOADS', payloads)","");p.write_text(text)
for name,variable,module in [('minimatch-action-source-repairs','MINIMATCH_RUNTIME','security_npm_sources'),('minimatch-java-action-source-repairs','JAVA_MINIMATCH_RUNTIME','security_npm_sources'),('minimatch-node-action-source-repairs','NODE_MINIMATCH_RUNTIME','security_npm_sources'),('minimatch-dotnet-action-source-repairs','RUNTIME','security_dotnet_minimatch')]:
    node=next(n for n in ast.parse((WORK/'tools'/f'{module}.py').read_text()).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==variable for t in n.targets));p=WORK/f'.github/security/{name}.json';value=json.loads(p.read_text());value['runtime']=ast.literal_eval(node.value);write_json(p,value)
for path in ['tools/security_action_rebuild.py','tools/tests/test_security_action_rebuild.py']:
    shutil.copyfile(ROOT/path,WORK/path)
# Reviewed fingerprints follow only actually changed delegated inputs.
changes=run(['git','diff','--name-only']).splitlines();hashes={}
for name in changes:
    if name.startswith('tools/ci/contracts/'):continue
    old=subprocess.check_output(['git','show',oldhead+':'+name],cwd=WORK);hashes[hashlib.sha256(old).hexdigest()]=identity((WORK/name).read_bytes())['sha256']
for p in (WORK/'tools/ci/contracts').rglob('*.json'):
    text=p.read_text();updated=text
    for a,b in hashes.items():updated=updated.replace(a,b)
    if updated!=text:p.write_text(updated)
write_json(WORK/'.github/security/actions/xml-security-rebuilds.json',{'schema':1,'scope':'Rebuilt source and bundles, not release or signed SDK qualification.','actions':[{key:record[key] for key in ('repository','base','publishedCommit','tree','workflowRun')} for record in records.values()]})
print('Integrated eleven authenticated executable action rebuilds and the nested Pages upload pin.')
