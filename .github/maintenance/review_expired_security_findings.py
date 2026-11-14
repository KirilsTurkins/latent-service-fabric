#!/usr/bin/env python3
"""One-time exact review, never an automatic or wildcard exception extension."""
from __future__ import annotations
from collections import Counter
from datetime import date, datetime, timezone
import hashlib,json,os,pathlib,re,subprocess,sys,tempfile
ROOT=pathlib.Path(os.environ['RUNNER_TEMP'])/'security-integrated'
sys.path.insert(0,str(ROOT))
from tools.security_common import digest, read_file
from tools.security_content import scan_secrets, stage_text
from tools.security_install import verify_tool
from tools.security_selftest import exercise
from tools.security_findings import load_exceptions
BASE='68bd53e20eeeae109f7816c8e81a1f959158a93b'
now=datetime.now(timezone.utc).date()
assert now==date(2026,11,14), 'This explicit review is dated, not a recurring renewal'
policy=ROOT/'.github/security/exceptions.json';before=policy.read_bytes();document=json.loads(before)
entries=document['exceptions'];assert len(entries)==17
paths=sorted({e['path'] for e in entries})
assert Counter(e['path'] for e in entries)=={
 'benchmarks/optimization/kubernetes-comparison/2026-09-11-container-linux-8b0441f/README.md':1,
 'benchmarks/optimization/prepared-cache/2026-09-09-container-linux-7e03a2f/behavior/aggregate.json':14,
 'crates/latent-wasmtime/tests/local_secrets/environment.rs':1,
 'sdk/c-guest/runtime-fixtures/libucl/upstream/src/mum.h':1}
assert all(e['scanner']=='gitleaks' and e['finding']=='generic-api-key' and e['package']=='' and e['created']=='2026-10-31' and e['expires']=='2026-11-14' for e in entries)
for path in paths:
    previous=subprocess.check_output(['git','show',BASE+':'+path],cwd=ROOT)
    assert previous==read_file(ROOT,path), 'Historical exception source changed'
# Inspect the bounded typed fields, without printing any raw match or value.
readme=read_file(ROOT,paths[0]).decode()
assert re.search(r'original 251,787,570B API journal SHA256: `[0-9a-f]{64}`',readme)
aggregate=json.loads(read_file(ROOT,paths[1]));handles=[]
def visit(value,keys=()):
    if isinstance(value,dict):
        for key,item in value.items():
            if key=='prepared_handle':
                assert keys[-1:] == ('direct_execution',)
                assert isinstance(item,str) and len(item)<=256 and re.search(r'[0-9a-f]{64}$',item)
                handles.append(item)
            visit(item,keys+(key,))
    elif isinstance(value,list):
        for item in value:visit(item,keys)
visit(aggregate)
assert len(set(handles))==14
fixture=read_file(ROOT,paths[2]).decode()
assert '.env("LSF_SECRET_TEST_DENIED_215", "must-not-be-selected")' in fixture
assert 'key: "LSF_SECRET_TEST_DENIED_215".into()' in fixture
assert 'Err(SecretError::PermissionDenied)' in fixture
prime=read_file(ROOT,paths[3]).decode()
assert re.search(r'static\s+uint64_t\s+_mum_key_step_prime\s*=\s*0x[0-9a-fA-F]+',prime)
assert prime.count('_mum_key_step_prime')>=2
out=pathlib.Path(os.environ['RUNNER_TEMP'])/'final-security-evidence';out.mkdir(exist_ok=True)
tools=pathlib.Path(os.environ['RUNNER_TEMP'])/'security-tools'
with tempfile.TemporaryDirectory(prefix='lsf-explicit-review-') as tmp:
    scratch=pathlib.Path(tmp)
    staged=scratch/'source';selected,binary=stage_text(ROOT,staged,paths);assert binary==0
    findings=scan_secrets(staged,selected,verify_tool('gitleaks',tools),scratch)
    fields=('scanner','finding','path','package','fingerprint')
    expected={tuple(e[k] for k in fields) for e in entries}
    assert {tuple(getattr(f,k) for k in fields) for f in findings}==expected
    # All full-file/location fingerprints are reproduced before any renewal.
    # Changed text, extra findings, new rules, and real credentials still fail.
    canary_dir=scratch/'canaries';canary_dir.mkdir()
    canaries=exercise(tools,canary_dir);assert canaries['status']=='pass' and len(canaries['canaries'])==8
review={
 'schema':1,'reviewedAt':datetime.now(timezone.utc).isoformat(),'reviewer':'automated coordinating agent under user-authorized CI repair; not human owner approval',
 'sourceBase':BASE,'workflowRun':int(os.environ['GITHUB_RUN_ID']),
 'previousExceptionsSha256':digest(before),'unchangedFingerprints':[f.public() for f in sorted(findings)],
 'unchangedSourceFiles':{p:{'sha256':digest(read_file(ROOT,p).replace(b'\r\n',b'\n')),'bytes':len(read_file(ROOT,p))} for p in paths},
 'typedChecks':['labelled API journal SHA256','fourteen direct_execution prepared-handle digest identities','synthetic denied environment-variable name','public integer MUM hash-mixing prime'],
 'scannerCanaries':canaries,'created':'2026-11-14','expiresExclusive':'2026-11-28',
 'scope':'Same exact seventeen full-content/location fingerprints only. No advisory waiver, scanner rule, source payload, synthetic canary or expiry enforcement is weakened.'}
for e in entries:
    e['created']='2026-11-14';e['expires']='2026-11-28';e['review']='https://github.com/KirilsTurkins/latent-service-fabric/pull/1852'
    kind='labelled API-journal SHA256' if e['path'].endswith('README.md') else 'direct_execution.prepared_handle bounded digest identity' if e['path'].endswith('aggregate.json') else 'synthetic denied environment-variable name, not its separate literal value' if e['path'].endswith('environment.rs') else 'public uint64_t MUM arithmetic hash-mixing prime'
    e['rationale']=('Explicit coordinating-agent re-review on 2026-11-14 under user-authorized CI repair. The pinned real Gitleaks scanner reproduces this exact complete normalized-file/location fingerprint on unchanged source bytes; all eight maintained real-scanner canaries pass with fresh RustSec data. Typed inspection confirms '+kind+', not an authentication secret. Prior reviews remain historical. This same rule/path/package/fingerprint alone is accepted until exclusive 2026-11-28; any changed content or other occurrence remains unwaived. Source-free review evidence is docs/evidence/security-false-positive-review-2026-11-14.json. No human-owner approval is claimed.')
policy.write_text(json.dumps(document,separators=(',',':'))+'\n')
load_exceptions(policy.parent)
receipt=ROOT/'docs/evidence/security-false-positive-review-2026-11-14.json';receipt.parent.mkdir(parents=True,exist_ok=True);receipt.write_text(json.dumps(review,indent=2)+'\n')
(out/'false-positive-review.json').write_text(json.dumps(review,indent=2)+'\n')
subprocess.run(['git','add','.github/security/exceptions.json','docs/evidence/security-false-positive-review-2026-11-14.json'],cwd=ROOT,check=True)
subprocess.run(['git','diff','--cached','--check'],cwd=ROOT,check=True)
subprocess.run(['git','commit','-m','security: re-review exact unchanged synthetic findings through November 28'],cwd=ROOT,check=True)
print('Reproduced seventeen exact historical fingerprints, checked typed non-secret fields, and passed eight real-scanner canaries. No raw matches exported.')
