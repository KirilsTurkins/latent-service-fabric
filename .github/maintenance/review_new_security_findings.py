#!/usr/bin/env python3
"""Review six observed non-secret expressions with exact source/scanner binding."""
from __future__ import annotations
import ast,hashlib,json,os,pathlib,re,subprocess,sys,tempfile
from datetime import date,datetime,timezone
ROOT=pathlib.Path(os.environ['RUNNER_TEMP'])/'security-integrated';sys.path.insert(0,str(ROOT))
from tools.security_common import read_file,digest
from tools.security_content import stage_text,scan_secrets
from tools.security_install import verify_tool
from tools.security_findings import load_exceptions
BASE='68bd53e20eeeae109f7816c8e81a1f959158a93b'
assert datetime.now(timezone.utc).date()==date(2026,11,14)
observed={
 'docs/testing/evidence/stream-credential-handoff-2026-11-08.json':{'3f3625c889b4f1f37296ea7bdbb08ac9daddd096b4b65762d63a29901d7262f8','7fa563c4b29a4470a319b2ceb2bdc14516a1244c9f4544cf0f935ae8a6dcce8b'},
 'docs/testing/evidence/stream-credential-handoff-ready-2026-11-08.json':{'0670b003c6f2c89c64320a0376978dab73817b5e4f9855abb211ee59f507ff76','0bbaed15a02968939489f3986dbc7d22d43e83a2c85bd0a30356868fd4accab4'},
 'tools/c_guest/threading.py':{'c283fe4693e5e9a90c8af1e3fda8ff61b782e4d5bbb0198d280ccb8c896958cc'},
 'tools/qualify_c_http_media.py':{'ce2bf2a6c8faf386f12e9cc3e00b377f0abf6165d40263bef12ed82043ce2ac8'}}
checks={}
for name in observed:
    raw=read_file(ROOT,name);assert raw==subprocess.check_output(['git','show',BASE+':'+name],cwd=ROOT)
    if name.endswith('.json'):
        record=json.loads(raw);values=record['pythonSourceGitBlobs'];selected={}
        for key in ['tools/outbound_stream_credential_scenario.py','tools/tests/test_outbound_stream_credential_scenario.py']:
            value=values[key];assert re.fullmatch(r'[0-9a-f]{40}',value)
            # Authenticate that the recorded value addresses actual public Python
            # source bytes in Git, not a value merely labelled as a source digest.
            payload=subprocess.check_output(['git','cat-file','blob',value],cwd=ROOT)
            assert hashlib.sha1(b'blob '+str(len(payload)).encode()+b'\0'+payload).hexdigest()==value
            ast.parse(payload);selected[key]={'gitBlob':value,'bytes':len(payload),'sha256':digest(payload)}
        checks[name]={'kind':'authenticated-public-Python-Git-blobs','objects':selected}
    elif name.endswith('threading.py'):
        module=ast.parse(raw)
        binding=next(n for n in module.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='POLL_LIBC' for t in n.targets))
        values=ast.literal_eval(binding.value);key='lib/libc/include/wasm-wasi-musl/wasi/api.h';assert values[key]=='8cf2859277ea2fc984780a00048686955805fd8a00c7be1d8f916105becf0174'
        consumer=next(n for n in module.body if isinstance(n,ast.FunctionDef) and n.name=='poll_libc_inputs')
        names={n.id for n in ast.walk(consumer) if isinstance(n,ast.Name)}
        assert {'POLL_LIBC','digest','read_file'}<=names
        checks[name]={'kind':'libc-source-SHA256-preimage-check','constant':'POLL_LIBC','consumer':'poll_libc_inputs','path':key,'sha256':values[key]}
    else:
        module=ast.parse(raw)
        calls=[n for n in ast.walk(module) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name) and n.func.value.id=='environment' and n.func.attr=='update']
        call=next(n for n in calls if {k.arg for k in n.keywords}=={'GH_TOKEN','GH_PROMPT_DISABLED'})
        args={k.arg:k.value for k in call.keywords};assert isinstance(args['GH_TOKEN'],ast.Name) and args['GH_TOKEN'].id=='token'
        assert isinstance(args['GH_PROMPT_DISABLED'],ast.Constant) and args['GH_PROMPT_DISABLED'].value=='1'
        assignments=[n for n in ast.walk(module) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='token' for t in n.targets)]
        assert len(assignments)==1 and ast.unparse(assignments[0].value)=="os.environ.get('GH_TOKEN')"
        checks[name]={'kind':'runtime-credential-reference-not-hardcoded-secret','source':'os.environ.get','variable':'token','literal':'GH_PROMPT_DISABLED=1','tokenValueReadOrRecorded':False}
with tempfile.TemporaryDirectory(prefix='lsf-source-identity-review-') as tmp:
    scratch=pathlib.Path(tmp);staged=scratch/'source';paths,binary=stage_text(ROOT,staged,sorted(observed));assert binary==0
    findings=scan_secrets(staged,paths,verify_tool('gitleaks',pathlib.Path(os.environ['RUNNER_TEMP'])/'security-tools'),scratch)
assert len(findings)==6
assert {(f.path,f.fingerprint) for f in findings}=={(p,v) for p,values in observed.items() for v in values}
assert all(f.scanner=='gitleaks' and f.finding=='generic-api-key' and f.package=='' for f in findings)
policy=ROOT/'.github/security/exceptions.json';document=json.loads(policy.read_text());assert len(document['exceptions'])==17
for f in sorted(findings):
    document['exceptions'].append({'scanner':f.scanner,'finding':f.finding,'path':f.path,'package':f.package,'fingerprint':f.fingerprint,
     'owner':'KirilsTurkins','created':'2026-11-14','expires':'2026-11-28','review':'https://github.com/KirilsTurkins/latent-service-fabric/pull/1852',
     'rationale':'Coordinating-agent exact re-review on 2026-11-14 under user-authorized CI repair; no human approval claimed. The pinned real scanner reproduced this full-file/location fingerprint on unchanged source. Typed inspection establishes '+checks[f.path]['kind']+'. It is not a hardcoded authentication value. Only this exact rule/path/package/fingerprint is accepted until exclusive 2026-11-28. The rule, scanner, source bytes, adversarial canaries and unmatched-finding refusal remain unchanged. Evidence: docs/evidence/security-source-identity-review-2026-11-14.json.'})
policy.write_text(json.dumps(document,separators=(',',':'))+'\n');load_exceptions(policy.parent)
review={'schema':1,'reviewedAt':datetime.now(timezone.utc).isoformat(),'reviewer':'coordinating automated agent under user-authorized CI repair; not human approval','sourceBase':BASE,'workflowRun':int(os.environ['GITHUB_RUN_ID']),'sourceInspection':checks,'findings':[f.public() for f in sorted(findings)],'sourceIdentities':{p:{'bytes':len(read_file(ROOT,p)),'sha256':digest(read_file(ROOT,p).replace(b'\r\n',b'\n'))} for p in observed},'expiresExclusive':'2026-11-28','scope':'Six exact non-secret expression fingerprints only. No real token is read, recorded or exempted; no dependency advisory is waived.'}
p=ROOT/'docs/evidence/security-source-identity-review-2026-11-14.json';p.write_text(json.dumps(review,indent=2)+'\n')
(pathlib.Path(os.environ['RUNNER_TEMP'])/'final-security-evidence/source-identity-review.json').write_text(json.dumps(review,indent=2)+'\n')
subprocess.run(['git','add','.github/security/exceptions.json',str(p)],cwd=ROOT,check=True)
subprocess.run(['git','diff','--cached','--check'],cwd=ROOT,check=True)
subprocess.run(['git','commit','-m','security: bind six verified non-secret source identity findings'],cwd=ROOT,check=True)
print('Verified four real Python Git blobs, the libc preimage digest consumer and an AST credential-variable expression; reproduced all six exact fingerprints.')
