"""Publish the already reviewed existing PR only after exact local gates pass."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import subprocess

coord=Path(__file__).resolve().parent
root=Path(r'C:\Users\turkins\Desktop\lf-p4-pr828-current-java-union-v12')
repo='KirilsTurkins/latent-service-fabric'
branch='feat/phase4-http-409'
expected='ed2254f1c7300ec11cbf827c4e1ed9fe364e8776'
head='6f0a8e82299aa0a1224dee293aaa8a4db7f3a7d9'
env=dict(os.environ,GODEBUG='http2client=0')
def git(*args):
    return subprocess.check_output(['git','-C',str(root),*args],env=env,text=True).strip()
def gh(*args):
    return subprocess.check_output(['gh',*args],env=env)
assert git('rev-parse','HEAD')==head and not git('status','--porcelain')
proofs=[]
for job in ('integration-v12-http-current-java-output-source-v3','integration-v12-http-current-java-native-v3'):
    path=coord/job/'receipt.json'; raw=path.read_bytes(); receipt=json.loads(raw)
    assert receipt['head']==head and receipt['passed'] and receipt['sourceClean']
    assert receipt['sourceHeadUnchanged'] and receipt['originalProcessReaped']
    proofs.append(dict(job=job,sha256=hashlib.sha256(raw).hexdigest(),steps=len(receipt['steps'])))
assert proofs[0]['steps']==7 and proofs[1]['steps']==10
remote=json.loads(gh('api',f'repos/{repo}/pulls/828'))
assert remote['state']=='open' and remote['head']['ref']==branch and remote['head']['sha']==expected
subprocess.run(['git','-C',str(root),'merge-base','--is-ancestor',expected,head],check=True,env=env)
body=remote.get('body') or ''
addition='''

Current integration retains the installed recovery, policy and Java packaging work from #823 together with this branch's shared HTTP owner, native capacity, TLS and cleanup checks. All source cases, ignores, minimum counts and workflow commands from both parents are retained. Native inspection uses the existing bounded response encoder and requires actual runtime thread retirement.

The exact integrated head passes all seven Linux source gates (345 tests, one existing Windows skip), the eight existing native runtime/lookup/accounting gates, and the added original packaging strict lint and nine native signer tests. The previously compiled Java material keeps its original compiler source identity. Signed guest/node campaigns, hosted full CI and the complete #409 acceptance criteria remain pending; this change does not close the issue.
'''
body_path=coord/'integration-v12-union-review/pr828-current-java-qualified-body.md'
body_path.write_text(body+addition,encoding='utf8',newline='\n')
guard=json.loads(gh('api',f'repos/{repo}/pulls/828'))
assert guard['head']['sha']==expected and guard['state']=='open'
subprocess.run(['git','-C',str(root),'push','origin',f'HEAD:refs/heads/{branch}'],check=True,env=env)
actual=git('ls-remote','origin',f'refs/heads/{branch}').split()[0]
assert actual==head
gh('pr','edit','828','--repo',repo,'--body-file',str(body_path))
record=dict(at=datetime.now(timezone.utc).isoformat(),pr=828,oldHead=expected,newHead=head,
    normalPush=True,remoteVerified=True,proofs=proofs,fullCi=False,issueClosed=False,worktreeDeleted=False)
(coord/'integration-v12-union-review/pr828-current-java-normal-publication-v3.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record))
