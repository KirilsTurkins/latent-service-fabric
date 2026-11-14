#!/usr/bin/env python3
"""Prepare and test the observed pin-closure repair on genuine PR histories."""
from __future__ import annotations
import ast, hashlib, json, os, pathlib, re, subprocess, sys, tarfile, tomllib, urllib.request
ROOT=pathlib.Path(os.environ['GITHUB_WORKSPACE']); TMP=pathlib.Path(os.environ['RUNNER_TEMP'])
WORK=TMP/'ts-followup-parent'; OUT=TMP/'ts-followup-evidence'; OUT.mkdir(exist_ok=True)
BASE='9e633f701982ce3345e7ebba0519d48f624f4afd'
HEADS={1852:('feat/typescript-runtime-745',BASE),1931:('fix/typescript-745-activation-resource-ownership','2bdec4779be9791ccdae28aa30f253ceca481c5d'),1934:('fix/1852-agent2-abort-engine-audit','8c6e235274009cbb08c17612749dd85b81f50e8d')}
REPO='repos/KirilsTurkins/latent-service-fabric'
PREIMAGES={
 'docs/development/toolchain.md':'42d518b1bc11b716b2149c075d64669e4afb2279f0409acd72207c31336104f3',
 'docs/development/workflow-action-pins.md':'20a7f33ae6b2e72759698c38db36a49404ff6730d976ce31ba6958864251dfa8',
 'global.json':'486f72cefddf1a313cb040785ac9ac571c86a626ad3fc5a30ebbe609c1ddfd73',
 'sdk/dotnet/README.md':'e27b2984f5581c7067220502c497b0faf882d936db9fbc06d7b9de32bce12a51',
 'sdk/dotnet/validate.py':'14a31113adc8480e498324354092912556cd08e6cf71062b6125686df42b9a92',
 'tools/rust_capsule.lock':'2e4f0734a564f6c12b141d1145109a994f7afc9d99b5d4921054d5820c9967ec',
 'tools/tests/test_go_smtp_tls_runtime.py':'71be10b01462b59d3ab85a124819bdd0e918571a68282ca6a9edabfb87e8d49f',
 'tools/tests/test_security_sdk_graphs.py':'16aa1536cbe6d94938a78ac32e0b0c0a57584dc72d698c40bb7e359cc8c09692',
 'tools/qualify_go_captured_checkpoints.py':'b604712aa917baeebb988128179f0ff3030b7767197fdf459fc321410e56b259',
 'tools/qualify_go_smtp_tls_runtime.py':'9f0a938e596b90b91e59ce3cd866327476e64805edb0c978a7f5fa712ee3fd55',
 'tools/tests/go_checkpoint_goto_reference.py':'ca2bedc2a2de7c4797e3a906034c0c9139fd85ed945adc4db8e4e73abfd497ec',
 'sdk/dotnet/protobuf.lock.json':'7b55e1b506199a4b245112bc0dfc72a155d76ca6bcc8ac1b21cd30987eac86f9'}
def digest(data):return hashlib.sha256(data).hexdigest()
def run(args,*,cwd=WORK,capture=False,env=None):
    if capture:return subprocess.check_output(args,cwd=cwd,env=env,text=True,timeout=600).strip()
    return subprocess.run(args,cwd=cwd,env=env,check=True,timeout=900)
def log(label,args,*,cwd=WORK,env=None):
    with (OUT/(label+'.log')).open('wb') as stream:
        p=subprocess.run(args,cwd=cwd,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=900)
    print(label,'exit',p.returncode,flush=True)
    if p.returncode:print((OUT/(label+'.log')).read_text(errors='replace')[-18000:],flush=True)
    assert p.returncode==0,label
    return (OUT/(label+'.log')).read_text()
def replace(name,before,after):
    p=WORK/name;s=p.read_text();assert s.count(before)==1,(name,'source-boundary',s.count(before));p.write_text(s.replace(before,after))
def commit(message,cwd=WORK):
    run(['git','add','-u'],cwd=cwd);run(['git','diff','--cached','--check'],cwd=cwd)
    run(['git','commit','-m',message],cwd=cwd)
def api(kind,value):
    p=TMP/'ts-followup-request.json';p.write_text(json.dumps(value))
    try:return json.loads(run(['gh','api','--method','POST',REPO+'/git/'+kind,'--input',str(p)],cwd=ROOT,capture=True))
    finally:p.unlink(missing_ok=True)
def export(cwd,parents,message):
    entries=[]
    for path in run(['git','diff','--no-renames','--name-only',parents[0],'HEAD'],cwd=cwd,capture=True).splitlines():
        mode,kind,sha=run(['git','ls-tree','HEAD','--',path],cwd=cwd,capture=True).split()[:3];assert kind=='blob'
        data=subprocess.check_output(['git','show','HEAD:'+path],cwd=cwd)
        assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==sha
        entries.append({'path':path,'mode':mode,'type':'blob','content':data.decode()})
    expected=run(['git','rev-parse','HEAD^{tree}'],cwd=cwd,capture=True)
    tree=api('trees',{'base_tree':run(['git','rev-parse',parents[0]+'^{tree}'],cwd=cwd,capture=True),'tree':entries})['sha'];assert tree==expected
    sha=api('commits',{'tree':tree,'parents':parents,'message':message})['sha']
    return {'commit':sha,'tree':tree,'parents':parents,'testedLocalCommit':run(['git','rev-parse','HEAD'],cwd=cwd,capture=True)}
if sys.argv[1]=='prepare':
    for branch,expected in HEADS.values():
        assert run(['git','ls-remote','--heads','origin','refs/heads/'+branch],cwd=ROOT,capture=True).split()[0]==expected,(branch,'head-moved')
        run(['git','fetch','--no-tags','origin',expected],cwd=ROOT)
    run(['git','worktree','add','--detach',str(WORK),BASE],cwd=ROOT)
    for name,expected in PREIMAGES.items():assert digest((WORK/name).read_bytes())==expected,(name,'preimage')
    replace('global.json','8.0.427','8.0.428')
    replace('sdk/dotnet/validate.py','SDK_VERSION = "8.0.427"','SDK_VERSION = "8.0.428"')
    replace('sdk/dotnet/validate.py','RUNTIME_VERSION = "8.0.33"','RUNTIME_VERSION = "8.0.34"')
    replace('sdk/dotnet/README.md','SDK 8.0.427, runtime 8.0.33','SDK 8.0.428, runtime 8.0.34')
    replace('docs/development/toolchain.md','1.27.3 / 24.19.0 / 7.0.2 / 8.0.427','1.27.4 / 24.19.0 / 7.0.2 / 8.0.428')
    replace('tools/rust_capsule.lock','name = "rustix"\nversion = "1.1.5"','name = "rustix"\nversion = "1.1.6"')
    replace('tools/rust_capsule.lock','891efababe418670775f199f0d233d84843c227a0949a883ce15b37c78d6629d','e5e76742e5294153d4dde1207dbec5bdd81eef6fabdc0d2118babadabfd858aa')
    p=WORK/'docs/development/workflow-action-pins.md';text=p.read_text()
    selected=json.loads((WORK/'.github/security/actions.json').read_text())['actions']
    revisions={key.split('@')[0]:value['revision'] for key,value in selected.items()}
    lines=[]
    for line in text.splitlines(True):
        match=re.match(r'\| `([^`]+)` \|',line)
        if match and match[1] in revisions:
            line,n=re.subn(r'`[0-9a-f]{40}`(?= \|\s*$)','`'+revisions[match[1]]+'`',line);assert n==1
        lines.append(line)
    p.write_text(''.join(lines))
    replace('docs/development/workflow-action-pins.md','The current security forks were reviewed on **2026-10-30**. They extend the pins introduced for Phase 3 issue #281.',
        'The table reflects the selected security graph after the **2026-11-14** repair.\nThe XML dependency rebuild records in\n[xml-security-rebuilds.json](../../.github/security/actions/xml-security-rebuilds.json)\nbind the repaired executable bundles to their source inputs. These updates extend\nthe 2026-10-30 security forks and the pins introduced for Phase 3 issue #281.')
    # Authenticate the selected distribution before deriving its executable pins.
    pins=json.loads((WORK/'sdk/go-guest/toolchain.lock.json').read_text())['go'];assert pins['version']=='go1.27.4'
    item=pins['linuxAmd64'];archive=TMP/'ts-followup-go.tar.gz'
    assert item=={'url':'https://dl.google.com/go/go1.27.4.linux-amd64.tar.gz','sha256':'7226736c2339719cda28fbf3a54d71aa63bcefe376e98cef00034268dab24840'}
    with urllib.request.urlopen(item['url'],timeout=90) as stream:data=stream.read(70680824)
    assert len(data)==70680823 and digest(data)==item['sha256'],'go-archive-identity';archive.write_bytes(data)
    destination=TMP/'ts-followup-go';destination.mkdir()
    with tarfile.open(archive,'r:gz') as tar:tar.extractall(destination,filter='data')
    go=destination/'go/bin/go';raw=go.read_bytes();new=digest(raw)
    old='5f5eb6d0b2fb6aa0bb5d5f8c5f1c944e0de955c925f0111af92a9d8f79680b5b';assert new!=old
    for name in ('tools/tests/go_checkpoint_goto_reference.py','tools/qualify_go_captured_checkpoints.py','tools/qualify_go_smtp_tls_runtime.py'):replace(name,old,new)
    replace('tools/qualify_go_captured_checkpoints.py',"'size': 17164222", "'size': "+str(len(raw)))
    assert run([str(go),'version'],cwd=TMP,capture=True)=='go version go1.27.4 linux/amd64'
    record={'archive':item,'archiveBytes':len(data),'goSha256':new,'goBytes':len(raw),'version':'go1.27.4'}
    (OUT/'go-compiler-identity.json').write_text(json.dumps(record,indent=2)+'\n')
    replace('tools/tests/test_go_smtp_tls_runtime.py',"        self.assertEqual(runtime.REFERENCE_GO_SHA,\n                         '"+old+"')", "        from tools import qualify_go_captured_checkpoints as captured\n        from tools.tests import go_checkpoint_goto_reference as goto\n        self.assertEqual(runtime.REFERENCE_GO_SHA, goto.GO_SHA256)\n        self.assertEqual(captured.GO_IDENTITY['digest'], 'sha256:' + runtime.REFERENCE_GO_SHA)")
    addition='''    def test_dotnet_host_selectors_and_generation_use_the_selected_toolchain(self):
        import ast
        import tomllib
        import xml.etree.ElementTree as xml
        root = Path(__file__).resolve().parents[2]
        sdk = tomllib.loads((root / 'tools/toolchain.toml').read_text())['sdk']['dotnet']
        for name in ('global.json', 'sdk/dotnet/global.json'):
            with self.subTest(selector=name):
                self.assertEqual(json.loads((root / name).read_text())['sdk'],
                                 {'version': sdk, 'rollForward': 'disable'})
        module = ast.parse((root / 'sdk/dotnet/validate.py').read_text())
        pins = {target.id: ast.literal_eval(node.value)
                for node in module.body if isinstance(node, ast.Assign)
                for target in node.targets if isinstance(target, ast.Name)
                and target.id in {'SDK_VERSION', 'RUNTIME_VERSION'}}
        self.assertEqual(pins['SDK_VERSION'], sdk)
        generation = json.loads((root / 'sdk/dotnet/protobuf.lock.json').read_text())
        self.assertEqual(generation['sdkVersion'], sdk)
        self.assertEqual(generation['runtimeVersion'], pins['RUNTIME_VERSION'])
        project = xml.parse(root / 'sdk/dotnet/Latent.Sdk.Transport/Latent.Sdk.Transport.csproj')
        self.assertEqual(project.findtext('./PropertyGroup/RuntimeFrameworkVersion'),
                         pins['RUNTIME_VERSION'])

'''
    replace('tools/tests/test_security_sdk_graphs.py','class SdkGraphTests(unittest.TestCase):\n','class SdkGraphTests(unittest.TestCase):\n'+addition)
    print(json.dumps(record),flush=True)
elif sys.argv[1]=='generate':
    # Two fresh generations, semantic/transport execution and package signature
    # verification run before accepting any new generation metadata.
    text=log('dotnet-regeneration',[sys.executable,'sdk/dotnet/validate.py','--print-generation'])
    actual=json.loads(text);path=WORK/'sdk/dotnet/protobuf.lock.json';previous=json.loads(path.read_text())
    expected={**previous,'sdkVersion':'8.0.428','runtimeVersion':'8.0.34'}
    assert actual==expected,'dotnet-generated-output-or-tool-change-needs-review'
    replace('sdk/dotnet/protobuf.lock.json','8.0.427','8.0.428');replace('sdk/dotnet/protobuf.lock.json','8.0.33','8.0.34')
    (OUT/'dotnet-generated.json').write_text(json.dumps(actual,indent=2)+'\n')
    log('dotnet-check',[sys.executable,'sdk/dotnet/validate.py','--check'])
elif sys.argv[1]=='test':
    go=TMP/'ts-followup-go/go/bin/go'
    log('go-native-checkpoint-reference',[sys.executable,'-m','tools.tests.go_checkpoint_goto_reference','--go',str(go)])
    modules=['test_rust_capsule_authoring','test_rust_application_dependencies','test_cross_origin_native_schema','test_cross_origin_native_workflow','test_security_sdk_graphs','test_go_captured_checkpoints','test_go_smtp_tls_runtime','test_sdk_scratch_fixture','test_ci_contracts']
    log('focused-python',[sys.executable,'-m','unittest',*('tools.tests.'+n for n in modules),'-v'])
    log('repository-validator',[sys.executable,'tools/validate_repository.py'])
    log('rust-locked-closure',[sys.executable,'-c',"from pathlib import Path;import os,subprocess,tempfile;from tools.rust_capsule_project import create;\nwith tempfile.TemporaryDirectory(prefix='lsf-rust-locked-') as t:\n p=create(Path(t)/'app','greeting');subprocess.run(['cargo','metadata','--locked','--format-version','1'],cwd=p,check=True,stdout=subprocess.DEVNULL);print('Created standalone greeting; complete locked dependency resolution passed')"])
    run(['git','diff','--check'])
    record={'schema':1,'parent':BASE,'workflowRun':int(os.environ['GITHUB_RUN_ID']),'go':json.loads((OUT/'go-compiler-identity.json').read_text()),'dotnet':{'sdk':'8.0.428','runtime':'8.0.34','generations':4,'generatedSourceAndToolHashesUnchanged':True},'scope':'Repair current SDK selection, reference compiler identities, standalone Rust lock and current action-pin guide. No assertions, security scanners, budgets or lock enforcement relaxed. Finite host/reference tests do not promote TypeScript runtime qualification.'}
    evidence=WORK/'docs/evidence/ci-toolchain-pin-closure-2026-11-14.json';evidence.write_text(json.dumps(record,indent=2)+'\n')
    run(['git','add',str(evidence)])
    commit('fix(ci): synchronize SDK selectors and authenticated compiler pins')
    (OUT/'parent.patch').write_bytes(subprocess.check_output(['git','diff','--binary',BASE,'HEAD'],cwd=WORK))
elif sys.argv[1]=='export':
    parent=export(WORK,[BASE],'fix(ci): synchronize SDK selectors and authenticated compiler pins')
    parent.update(pr=1852,branch=HEADS[1852][0],expectedHead=BASE)
    (OUT/'1852.json').write_text(json.dumps(parent,indent=2)+'\n');print(json.dumps(parent),flush=True)
    for number in (1931,1934):
        branch,expected=HEADS[number];child=TMP/('ts-followup-'+str(number))
        run(['git','worktree','add','--detach',str(child),expected],cwd=ROOT)
        run(['git','merge','--no-ff','--no-commit',run(['git','rev-parse','HEAD'],capture=True)],cwd=child)
        assert not run(['git','diff','--name-only','--diff-filter=U'],cwd=child,capture=True)
        commit('merge: restack TypeScript fixes onto CI pin-closure repair',cwd=child)
        log(str(number)+'-source',[sys.executable,'-m','unittest','tools.tests.test_host_codec_wasmtime','tools.tests.test_security_sdk_graphs.SdkGraphTests.test_dotnet_host_selectors_and_generation_use_the_selected_toolchain','-v'],cwd=child)
        if number==1934:log('1934-ownership',[sys.executable,'-m','unittest','tools.tests.test_typescript_event_ownership','tools.tests.test_typescript_abort_any_ownership','tools.tests.test_typescript_record_retirement','-v'],cwd=child)
        value=export(child,[expected,parent['commit']],'merge: restack TypeScript fixes onto tested CI pin-closure repair')
        value.update(pr=number,branch=branch,expectedHead=expected);(OUT/(str(number)+'.json')).write_text(json.dumps(value,indent=2)+'\n');print(json.dumps(value),flush=True)
else:raise SystemExit('expected prepare, generate, test or export')
