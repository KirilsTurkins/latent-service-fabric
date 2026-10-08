from datetime import datetime, timezone
from pathlib import Path
import json
import os
import subprocess

coord=Path(__file__).resolve().parent
repo=Path(r'C:\Users\turkins\Desktop\latent-fabric')
env=dict(os.environ,GODEBUG='http2client=0')
rows=json.loads((coord/'integration-v12-preservation-owned-inventory-v42.json').read_bytes())
assert len(rows)==44 and all(r['exists'] and not r['status'] and not r['unmerged'] for r in rows)
def git(*args):
    return subprocess.check_output(['git',*args],cwd=repo,env=env,text=True).strip()
remote=dict((ref,head) for head,ref in (line.split() for line in git('ls-remote','--heads','origin').splitlines()))
refspecs=[]
for row in rows:
    name=Path(row['worktree']).name
    ref='refs/heads/checkpoint/phase4-cleanup-20261008/integration/'+name
    assert ref not in remote or remote[ref]==row['HEAD'], 'immutable checkpoint collision: '+ref
    row['checkpointRef']=ref
    row['remoteUrl']='https://github.com/KirilsTurkins/latent-service-fabric/tree/'+ref.removeprefix('refs/heads/')
    if ref not in remote:
        refspecs.append(row['HEAD']+':'+ref)
if refspecs:
    subprocess.run(['git','push','origin',*refspecs],cwd=repo,env=env,check=True)
final=dict((ref,head) for head,ref in (line.split() for line in git('ls-remote','--heads','origin','refs/heads/checkpoint/phase4-cleanup-20261008/integration/*').splitlines()))
targets={'currentCollector':'1fcc6d0fa6ec8e19c3ffc11ca02dd9242d0a10e6',
 'published823AtStop':'1417e360a96954ce8abcc845024e7b7ff0eccb99',
 'published828AtStop':'1b7a8073f9ec7b354a4dd00a365deb1c4094e3aa',
 'published808AtStop':'9d9f1f3586e203d16733a05782a1785b6c7b7789',
 'published791AtStop':'a129773f52c4fc15c59b4ce62b52744a233cd4cd'}
for row in rows:
    assert final[row['checkpointRef']]==row['HEAD']
    row['remoteVerified']=True
    row['containedByHeads']=[name for name,head in targets.items() if subprocess.run(
        ['git','merge-base','--is-ancestor',row['HEAD'],head],cwd=repo,capture_output=True).returncode==0]
proof=dict(at=datetime.now(timezone.utc).isoformat(),owner='/root/phase4_current_integration_v12',
    preservationOnly=True,ownedTreeCount=len(rows),dirtyCount=0,unmergedCount=0,
    allRemoteVerified=True,noActiveValidationJobs=True,rows=rows,
    recommendedDraft=dict(branch='test/phase4-current-query-witness-union-v39',
        head=targets['currentCollector'],title='WIP: qualify signed Java query and unresolved recovery workflows',
        issues=[718,388,400,398,399,409],parentPRs=[823,828],
        sourcePassed=True,actualSignedQueryPassed=False,actualFirstQuery503=True))
(coord/'integration-v12-preservation-verified-v42.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(dict(count=len(rows),allRemoteVerified=True,dirtyCount=0,
    nonAncestorNames=[Path(r['worktree']).name for r in rows if not r['containedByHeads']],
    recommendedDraft=proof['recommendedDraft'])))
