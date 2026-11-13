#!/usr/bin/env python3
"""Prepare, test and export real-history fixes; never change existing refs."""
from __future__ import annotations
import ast,hashlib,io,json,os,pathlib,pprint,re,subprocess,sys,zipfile
ROOT=pathlib.Path(os.environ['GITHUB_WORKSPACE']);TMP=pathlib.Path(os.environ['RUNNER_TEMP']);OUT=TMP/'final-security-evidence';OUT.mkdir(exist_ok=True)
BASE='68bd53e20eeeae109f7816c8e81a1f959158a93b'
HEADS={1852:('feat/typescript-runtime-745',BASE),1931:('fix/typescript-745-activation-resource-ownership','f682c3c8c8ff2fc1ee44df2ed681098e263bd800'),1934:('fix/1852-agent2-abort-engine-audit','5bb73cf78320c3f130d89f47b8ceb48f24abd4ee')}
WORK=TMP/'security-integrated'
REPO='repos/KirilsTurkins/latent-service-fabric'
def run(args,*,cwd=WORK,check=True,capture=False,env=None,timeout=1800):
    if capture:return subprocess.check_output(args,cwd=cwd,text=True,timeout=timeout,env=env).strip()
    return subprocess.run(args,cwd=cwd,check=check,timeout=timeout,env=env)
def raw(args,cwd=WORK):return subprocess.check_output(args,cwd=cwd,timeout=180)
def digest(data):return hashlib.sha256(data).hexdigest()
def write_json(p,v):p.write_text(json.dumps(v,indent=2)+'\n')
def artifact(number,sha):
    data=subprocess.check_output(['gh','api',REPO+'/actions/artifacts/'+str(number)+'/zip'],timeout=120)
    assert digest(data)==sha,(number,'artifact-identity')
    with zipfile.ZipFile(io.BytesIO(data)) as z:return {n:z.read(n) for n in z.namelist() if not n.endswith('/')}
def commit(message,cwd=WORK):
    run(['git','add','-u'],cwd=cwd)
    run(['git','diff','--cached','--check'],cwd=cwd)
    run(['git','-c','user.name=github-actions[bot]','-c','user.email=41898282+github-actions[bot]@users.noreply.github.com','commit','-m',message],cwd=cwd)
    return run(['git','rev-parse','HEAD'],cwd=cwd,capture=True)
MISSING=object()
def merge_json(base,ours,theirs):
    if ours==theirs or theirs==base:return ours
    if ours==base:return theirs
    if all(isinstance(v,dict) for v in (base,ours,theirs)):
        result={}
        for key in dict.fromkeys([*ours,*theirs]):
            value=merge_json(base.get(key,MISSING),ours.get(key,MISSING),theirs.get(key,MISSING))
            if value is not MISSING:result[key]=value
        return result
    if all(isinstance(v,list) for v in (base,ours,theirs)) and len(base)==len(ours)==len(theirs):
        return [merge_json(*v) for v in zip(base,ours,theirs)]
    raise AssertionError('Concurrent semantic edit needs review: '+repr((base,ours,theirs))[:400])
def resolve_json(cwd,path):
    values=[json.loads(raw(['git','show',f':{i}:{path}'],cwd)) for i in (1,2,3)]
    write_json(cwd/path,merge_json(*values));run(['git','add',path],cwd=cwd)
def conflicts(cwd):return run(['git','diff','--name-only','--diff-filter=U'],cwd=cwd,capture=True).splitlines()
def identity(p):
    b=p.read_bytes();return {'bytes':len(b),'sha256':digest(b)}
def log_test(label,args,cwd=WORK,env=None,timeout=1800):
    path=OUT/(label+'.log')
    with path.open('wb') as f:
        p=subprocess.run(args,cwd=cwd,stdout=f,stderr=subprocess.STDOUT,env=env,timeout=timeout)
    print(label,'exit',p.returncode,flush=True)
    if p.returncode:print(path.read_text(errors='replace')[-18000:],flush=True)
    assert p.returncode==0,label

def export(cwd,parents,message):
    tree=run(['git','rev-parse','HEAD^{tree}'],cwd=cwd,capture=True)
    baseline=parents[0];entries=[]
    paths=run(['git','diff','--no-renames','--name-only',baseline,'HEAD'],cwd=cwd,capture=True).splitlines()
    for path in paths:
        record=run(['git','ls-tree','HEAD','--',path],cwd=cwd,capture=True)
        if not record:entries.append({'path':path,'mode':'100644','type':'blob','sha':None});continue
        mode,kind,expected=record.split()[:3];assert kind=='blob'
        data=raw(['git','show','HEAD:'+path],cwd)
        assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==expected
        entries.append({'path':path,'mode':mode,'type':'blob','content':data.decode('utf-8')})
    def api(kind,value):
        p=TMP/'security-api-request.json';write_json(p,value)
        response=json.loads(run(['gh','api','--method','POST',REPO+'/git/'+kind,'--input',str(p)],cwd=cwd,capture=True));p.unlink();return response
    result=api('trees',{'base_tree':run(['git','rev-parse',baseline+'^{tree}'],cwd=cwd,capture=True),'tree':entries})
    assert result['sha']==tree,(result['sha'],tree)
    result=api('commits',{'tree':tree,'parents':parents,'message':message})
    return {'commit':result['sha'],'tree':tree,'testedLocalCommit':run(['git','rev-parse','HEAD'],cwd=cwd,capture=True),'parents':parents}

if sys.argv[1]=='prepare':
    for branch,expected in HEADS.values():
        value=run(['git','ls-remote','--heads','origin','refs/heads/'+branch],cwd=ROOT,capture=True)
        assert value.split()[0]==expected,(branch,value)
        run(['git','fetch','--no-tags','origin',expected],cwd=ROOT)
    run(['git','worktree','add','--detach',str(WORK),BASE],cwd=ROOT)
    # Artifact payload excludes hidden standalone copies, but its complete patch
    # and authenticated Git tree bind all .github postimages as well.
    value=artifact(14084852501,'be222aa479e42cadffd9de4a27dc5b2be074973aaf8b8b219a19b405202dcc6a')
    record=json.loads(value['build.json']);assert record['completed'] is True and record['run']==43524527844 and record['base']==BASE
    p=TMP/'runtime-security.patch';p.write_bytes(value['changes.patch'])
    run(['git','apply','--index','--whitespace=error-all',str(p)])
    assert run(['git','write-tree'],capture=True)==record['tree']=='10ee76eb23e9d3a81f3c9295ff523742be4fb92f'
    commit('fix(security): update rustix and pinned .NET runtime')
    value=artifact(14086445337,'4817939b4b8cfd8372b96b5ceb33fcb08aeccc8fc3b8e1a6b8ec1f3a649a8cc7')
    assert b'generated Go RPC bindings from nine authoritative protobuf sources' in value['validation.log'] and b'checked Go RPC regeneration' in value['validation.log'] and b'ok  ' in value['validation.log']
    (OUT/'go-prerequisite-execution.log').write_bytes(value['validation.log'])
    p=TMP/'go-security.patch';p.write_bytes(value['changes.patch'])
    run(['git','apply','--3way','--index',str(p)],check=False)
    for path in conflicts(WORK):
        if path.endswith('.json'):resolve_json(WORK,path)
        elif path=='tools/toolchain.toml':
            base,ours,theirs=[raw(['git','show',f':{i}:{path}']).decode() for i in (1,2,3)]
            assert theirs==base.replace('1.27.3','1.27.4')
            (WORK/path).write_text(ours.replace('1.27.3','1.27.4'));run(['git','add',path])
        else:raise AssertionError('Unreviewed Go integration conflict: '+path)
    assert not conflicts(WORK)
    # Preserve semantic JSON values while removing inherited CRLF from the
    # one changed reviewed fragment; keep ordinary diff whitespace checks.
    for path in run(['git','diff','--cached','--name-only'],capture=True).splitlines():
        p=WORK/path
        if path.endswith('.json') and b'\r\n' in p.read_bytes():p.write_bytes(p.read_bytes().replace(b'\r\n',b'\n'))
    commit('fix(security): select authenticated Go 1.27.4 compiler')
    environment={**os.environ,'SECURITY_WORKTREE':str(WORK)}
    script=(ROOT/'.github/maintenance/integrate_action_security.py').read_text()
    bad='c8620a56d8edbab6d83d64f1937cd0a1def2581cfa2d99b4e373b347ff6a2f4'
    good='c8620a56d8edbab6d83d64f1937cd0a01def2581cfa2d99b4e373b347ff6a2f4'
    assert script.count(bad)==1;script=script.replace(bad,good)
    driver=TMP/'reviewed-action-integration.py';driver.write_text(script)
    log_test('action-integration',['python3',str(driver)],cwd=ROOT,env=environment)
    run(['git','add','tools/security_action_rebuild.py','tools/tests/test_security_action_rebuild.py','.github/security/actions/xml-security-rebuilds.json'])
    commit('fix(security): pin rebuilt XML-safe action bundles and authenticated evidence')
    write_json(OUT/'prepared.json',{'base':BASE,'worktree':str(WORK),'head':run(['git','rev-parse','HEAD'],capture=True)})
elif sys.argv[1]=='validate':
    log_test('security-controls',['python3','-c',"import unittest; s=unittest.defaultTestLoader.discover('tools/tests',pattern='test_security*.py');r=unittest.TextTestRunner(verbosity=2).run(s);raise SystemExit(not r.wasSuccessful() or bool(r.skipped))"])
    log_test('ci-contract-controls',['python3','-m','unittest','tools.tests.test_ci_contracts','tools.tests.test_ci_suite_discovery','tools.tests.test_go_zero_clock','-v'])
    log_test('vendor-source-controls',['python3','-m','unittest','tools.tests.test_host_codec_wasmtime','-v'])
    for mode in ('rustsec','dependencies'):
        log_test('parent-'+mode,['python3','tools/security_scan.py',mode,'--repo',str(WORK),'--tools',str(TMP/'security-tools'),'--scratch',str(TMP/'security-scan')])
    assert not run(['git','status','--porcelain','--untracked-files=normal'])
elif sys.argv[1]=='publish-objects':
    parent=export(WORK,[BASE],'fix(security): update vulnerable runtime and executable action dependencies')
    parent.update(pr=1852,branch=HEADS[1852][0],expectedHead=BASE)
    write_json(OUT/'parent.json',parent);print(json.dumps(parent),flush=True)
    for number in (1931,1934):
        branch,expected=HEADS[number];child=TMP/('security-'+str(number))
        run(['git','worktree','add','--detach',str(child),expected],cwd=ROOT)
        run(['git','merge','--no-ff','--no-commit',run(['git','rev-parse','HEAD'],capture=True)],cwd=child,check=False)
        unresolved=conflicts(child)
        if number==1931:
            patch='crates/vendor/wasmtime/latent-dynamic-memory.patch'
            if patch in unresolved:
                def pieces(raw):
                    text=raw.decode();parts=re.split(r'(?m)(?=^--- a/)',text);assert parts[0]==''
                    return {part.splitlines()[0][6:]:part for part in parts[1:]}
                base,ours,theirs=[pieces(raw(['git','show',f':{i}:{patch}'],child)) for i in (1,2,3)]
                merged=merge_json(base,ours,theirs);(child/patch).write_text(''.join(merged.values()));run(['git','add',patch],cwd=child)
            for path in conflicts(child):
                if path.endswith('.json'):resolve_json(child,path)
                elif path=='tools/host_codec_wasmtime.py':
                    original=raw(['git','show',expected+':'+path],child).decode();(child/path).write_text(original);run(['git','add',path],cwd=child)
                else:raise AssertionError('Unreviewed ownership conflict: '+path)
            path=child/'tools/host_codec_wasmtime.py';text=path.read_text();tree=ast.parse(text)
            record=child/'crates/vendor/wasmtime/UPSTREAM.latent.json'
            node=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='RECORD_SHA256' for t in n.targets))
            old=ast.literal_eval(node.value);assert text.count(old)==1;text=text.replace(old,digest(record.read_bytes()))
            tree=ast.parse(text);node=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='POSTIMAGES' for t in n.targets));value=ast.literal_eval(node.value)
            for source in ('Cargo.lock','latent-dynamic-memory.patch'):value[source]=identity(child/'crates/vendor/wasmtime'/source)
            lines=text.splitlines(True);lines[node.lineno-1:node.end_lineno]=['POSTIMAGES = '+pprint.pformat(value,width=110,sort_dicts=False)+'\n'];path.write_text(''.join(lines));run(['git','add',str(path)],cwd=child)
        assert not conflicts(child),(number,conflicts(child))
        commit('merge: retain TypeScript fixes with current security dependencies',cwd=child)
        log_test(str(number)+'-source',['python3','-m','unittest','tools.tests.test_host_codec_wasmtime','-v'],cwd=child)
        if number==1931:log_test('1931-store',['cargo','test','-p','latent-wasmtime','--lib','backend::store','--locked'],cwd=child)
        else:log_test('1934-native',['python3','-m','unittest','tools.tests.test_typescript_event_ownership','tools.tests.test_typescript_abort_any_ownership','tools.tests.test_typescript_record_retirement','-v'],cwd=child)
        value=export(child,[expected,parent['commit']],'merge: restack TypeScript ownership fixes onto the validated security repair')
        value.update(pr=number,branch=branch,expectedHead=expected);write_json(OUT/(str(number)+'.json'),value);print(json.dumps(value),flush=True)
else:raise SystemExit('expected prepare, validate or publish-objects')
