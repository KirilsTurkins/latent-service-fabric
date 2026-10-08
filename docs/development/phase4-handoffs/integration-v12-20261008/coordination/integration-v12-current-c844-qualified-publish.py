from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

coord=Path(__file__).resolve().parent
pr=int(sys.argv[1]);assert pr in (823,828)
cfg={
 823:dict(root='lf-p4-current-java-bd4-union-v12',branch='feat/phase4-state-runtime-718',
   old='44754a7b9de0b41c456bcbbf31797b0cd47b0814',head='0a0dc2818946111c8657e6b681ecef1f9f3fafab',count=374),
 828:dict(root='lf-p4-pr828-current-java-union-v12',branch='feat/phase4-http-409',
   old='6f0a8e82299aa0a1224dee293aaa8a4db7f3a7d9',head='7bc6e42254ef94c2b0248ad174d1e959aefc10e2',count=375),
}[pr]
root=Path(r'C:\Users\turkins\Desktop')/cfg['root'];repo='KirilsTurkins/latent-service-fabric'
env=dict(os.environ,GODEBUG='http2client=0')
def git(*args):return subprocess.check_output(['git','-C',str(root),*args],env=env,text=True).strip()
def gh(*args):return subprocess.check_output(['gh',*args],env=env)
assert git('rev-parse','HEAD')==cfg['head'] and not git('status','--porcelain')
proofs=[]
for lane in ('source',):
    job=f'integration-v12-current{pr}-developmentc844-{lane}-v10'
    raw=(coord/job/'receipt.json').read_bytes();receipt=json.loads(raw)
    assert receipt['head']==cfg['head'] and receipt['passed'] and receipt['sourceClean']
    assert receipt['sourceHeadUnchanged'] and receipt['originalProcessReaped']
    proofs.append(dict(job=job,actualHead=receipt['head'],steps=len(receipt['steps']),sha256=hashlib.sha256(raw).hexdigest()))
if pr==823:
    path=coord/'integration-v12-union-review/pr823-c844-original-native-qualified-proof-v11.json'
    raw=path.read_bytes();native=json.loads(raw)
    assert native['head']==cfg['head'] and native['requiredScopedNativeGatesPassed'] and native['actualSourceCleanAllProcessesReaped']
    assert not native['originalRawDiagnosticPassed'] and not native['extraSigningOnlyStrictGatePassed']
    proofs.append(dict(scopedProof=str(path),actualHead=native['head'],sha256=hashlib.sha256(raw).hexdigest()))
else:
    job='integration-v12-current828-developmentc844-native-v11'
    raw=(coord/job/'receipt.json').read_bytes();receipt=json.loads(raw)
    assert receipt['head']==cfg['head'] and receipt['passed'] and receipt['sourceClean']
    assert receipt['sourceHeadUnchanged'] and receipt['originalProcessReaped']
    proofs.append(dict(job=job,actualHead=receipt['head'],steps=len(receipt['steps']),sha256=hashlib.sha256(raw).hexdigest()))
subprocess.run(['git','-C',str(root),'merge-base','--is-ancestor','c84473ec9868fc496486f864afe52f1b7105329f',cfg['head']],check=True,env=env)
catalog=json.loads(subprocess.check_output(['git','-C',str(root),'show',cfg['head']+':tools/ci/suites.json']))
assert next(row for row in catalog['suites'] if row['id']=='latent-wasmtime.test.aot-sandbox')['minimumCases']==1
assert next(row for row in catalog['suites'] if row['id']=='latent-signing.lib.latent-signing')['minimumCases']==58
remote=json.loads(gh('api',f'repos/{repo}/pulls/{pr}'))
assert remote['state']=='open' and remote['head']['ref']==cfg['branch'] and remote['head']['sha']==cfg['old']
subprocess.run(['git','-C',str(root),'merge-base','--is-ancestor',cfg['old'],cfg['head']],check=True,env=env)
addition=f'''

Development `c84473ec` is integrated, including concurrent signing-currentness readers and the six new shared-reader, exclusive-writer and poisoned-owner schedules. Both parents' source cases, ignore state, prerequisites and workflow commands are retained, and the historical custom AOT sandbox minimum remains one. Exact current-head Linux source gates pass ({cfg['count']} cases, one original Windows skip); native validation passes all58 signing cases, ordinary signing Clippy, the original selected strict lint gate and all current Wire/Node/daemon library cases. The extra signing-only strict probe retained four pre-existing lint diagnostics and is not reported as passed. Full hosted CI, browser and signed public guest workflow acceptance remain pending.
'''
if pr==823:
    addition+='The current Java recovery world explicitly retains the maintained clock imports and matching recipe digest required by the runtime adapter. The failed C-stage attempt is preserved; all six current Java components still need a fresh source-paired compiler campaign.\n'
body=coord/f'integration-v12-union-review/pr{pr}-current-c844-qualified-body.md'
body.write_text((remote.get('body') or '')+addition,encoding='utf8',newline='\n')
guard=json.loads(gh('api',f'repos/{repo}/pulls/{pr}'));assert guard['head']['sha']==cfg['old']
subprocess.run(['git','-C',str(root),'push','origin','HEAD:refs/heads/'+cfg['branch']],check=True,env=env)
assert git('ls-remote','origin','refs/heads/'+cfg['branch']).split()[0]==cfg['head']
gh('pr','edit',str(pr),'--repo',repo,'--body-file',str(body))
record=dict(at=datetime.now(timezone.utc).isoformat(),pr=pr,oldHead=cfg['old'],newHead=cfg['head'],
    normalPush=True,remoteVerified=True,currentMain='c84473ec9868fc496486f864afe52f1b7105329f',
    proofs=proofs,preservedHistoricalCustomAotMinimum=1,fullCi=False,issuesClosed=[],worktreesDeleted=[])
(coord/f'integration-v12-union-review/pr{pr}-current-c844-normal-publication-v10.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record))
