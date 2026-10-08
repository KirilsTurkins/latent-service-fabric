from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import subprocess

coord=Path(__file__).resolve().parent
root=Path(r'C:\Users\turkins\Desktop\lf-p4-current-public-effect-union-v12')
repo='KirilsTurkins/latent-service-fabric'
branch='feat/phase4-state-runtime-718'
expected='291f6f13da92aa675b5caa955b26e2c27f395d05'
head='27d32ea9780784cab5cb1a14aee8b2fb4a46cb03'
env=dict(os.environ,GODEBUG='http2client=0')
def git(*args):
    return subprocess.check_output(['git','-C',str(root),*args],env=env,text=True).strip()
def gh(*args):
    return subprocess.check_output(['gh',*args],env=env)
assert git('rev-parse','HEAD')==head and not git('status','--porcelain')
proofs=[]
for job in ('integration-v12-effect-current-provider-facts-source-v4','integration-v12-current-public-effect-native-v4'):
    path=coord/job/'receipt.json';raw=path.read_bytes();receipt=json.loads(raw)
    assert receipt['head']==head and receipt['passed'] and receipt['sourceClean']
    assert receipt['sourceHeadUnchanged'] and receipt['originalProcessReaped']
    proofs.append(dict(job=job,steps=len(receipt['steps']),sha256=hashlib.sha256(raw).hexdigest()))
assert proofs[0]['steps']==7 and proofs[1]['steps']==6
remote=json.loads(gh('api',f'repos/{repo}/pulls/823'))
assert remote['head']['sha']==expected and remote['head']['ref']==branch and remote['state']=='open'
subprocess.run(['git','-C',str(root),'merge-base','--is-ancestor',expected,head],check=True,env=env)
addition='''

Effect status and bounded history now use the installed recovery owner and the original authenticated caller, namespace, publication and current inspect-effect decisions. The reader verifies the committed command/effect link, retained payload digest and actual durable management receipt before exposing status. Provider confirmation and administrator termination remain separate, and historical attempt receipts retain their original facts. Response ownership keeps the original native reservation and read view through physical release and rechecks authorization before delivery.

The exact effect-reader head passes seven source gates (344 tests, one existing Windows skip), actual producer management schedules, both new effect-read/history cases, the full current Wire/Node/daemon libraries, ordinary library Clippy and the original selected strict lint gate. Real public signed-node qualification and the full management scope of #400 remain pending. Prior compiler/signing receipts retain their original source identities.
'''
body_path=coord/'integration-v12-union-review/pr823-current-effect-qualified-body.md'
body_path.write_text((remote.get('body') or '')+addition,encoding='utf8',newline='\n')
guard=json.loads(gh('api',f'repos/{repo}/pulls/823'))
assert guard['head']['sha']==expected and guard['state']=='open'
subprocess.run(['git','-C',str(root),'push','origin',f'HEAD:refs/heads/{branch}'],check=True,env=env)
assert git('ls-remote','origin',f'refs/heads/{branch}').split()[0]==head
gh('pr','edit','823','--repo',repo,'--body-file',str(body_path))
value=dict(at=datetime.now(timezone.utc).isoformat(),pr=823,oldHead=expected,newHead=head,
    normalPush=True,remoteVerified=True,proofs=proofs,fullCi=False,issueClosed=False,worktreeDeleted=False)
(coord/'integration-v12-union-review/pr823-current-effect-normal-publication-v4.json').write_text(json.dumps(value,indent=2)+'\n')
print(json.dumps(value))
