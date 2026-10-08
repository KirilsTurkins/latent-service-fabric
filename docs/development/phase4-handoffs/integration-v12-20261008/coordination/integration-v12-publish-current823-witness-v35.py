from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import subprocess

coord=Path(__file__).resolve().parent
tree=Path(r'C:\Users\turkins\Desktop\lf-p4-pr823-witness-vector-v35')
repo='KirilsTurkins/latent-service-fabric'
head='1417e360a96954ce8abcc845024e7b7ff0eccb99'
parent='76307dbbe24b51fb8b1316c4fbf7047914759a51'
branch='feat/phase4-state-runtime-718'
env=dict(os.environ,GODEBUG='http2client=0')
source=coord/'integration-v12-current823-witness-source-v35'
raw=(source/'receipt.json').read_bytes()
assert hashlib.sha256(raw).hexdigest()=='02bc45f676d84b8dfcf66ac33980c407bbcbf318d670e3f58dbbc7049bfb7622'
receipt=json.loads(raw)
assert receipt['head']==head and all(receipt[k] for k in ['passed','sourceClean','sourceHeadUnchanged','originalProcessReaped'])
assert len(receipt['steps'])==7
for row in receipt['steps']:
    data=(source/row['log']).read_bytes()
    assert hashlib.sha256(data).hexdigest()==row['sha256'] and len(data)==row['bytes']
def git(*args):
    return subprocess.check_output(['git',*args],cwd=tree,text=True).strip()
assert git('rev-parse','HEAD')==head and not git('status','--porcelain')
subprocess.run(['git','merge-base','--is-ancestor',parent,head],cwd=tree,check=True)
live=json.loads(subprocess.check_output(['gh','pr','view','823','--repo',repo,'--json','headRefOid,headRefName,state,baseRefName'],env=env))
assert live==dict(baseRefName='development',headRefName=branch,headRefOid=parent,state='OPEN')
assert git('ls-remote','origin','refs/heads/'+branch).split()[0]==parent
body=('The daemon composes installed transactions, queries, original-result recovery and effect management with its existing state, policy, clock, dispatcher and native owners. Current development21c is integrated, with original tests, deadlines, quotas, ignores and AOT floor preserved. Tracks #718, #387, #388 and #400.\n\n'
      'The Java bridge now includes both directions of the captured transaction witness. One shared witness fixture exercises all six maintained client projections, including full-width integers and optional presence. Every previous fixture and assertion remains; current totals are78 shared fixtures, Java61 successful protobuf cases plus the original contradictory refusal, and62 .NET-selected protobuf cases.\n\n'
      'Exact current Linux Source7 passes374 tests with one original Windows skip plus12 profile cases, all13 generator checks, locked31.1 Node descriptor, Java bridge, metadata, formatting and repository/coverage gates. Previous native Signing58/Node116/Wire195/daemon282, six Java compiler captures and Windows .NET61/569/77 receipts retain their original source heads. Current Java Gradle540, new fixture execution in all languages, signed public guest/provider/restore/browser workflows and full current CI remain pending; this PR does not establish complete ticket acceptance.\n')
body_path=coord/'integration-v12-union-review/pr823-current-witness-body-v35.md'
body_path.write_text(body,encoding='utf8',newline='\n')
subprocess.run(['git','push','origin',head+':refs/heads/'+branch],cwd=tree,env=env,check=True)
assert git('ls-remote','origin','refs/heads/'+branch).split()[0]==head
subprocess.run(['gh','pr','edit','823','--repo',repo,'--body-file',str(body_path)],env=env,check=True)
final=json.loads(subprocess.check_output(['gh','pr','view','823','--repo',repo,'--json','headRefOid,body,state'],env=env))
assert final['headRefOid']==head and final['state']=='OPEN'
assert final['body'].replace('\r\n','\n').strip()==body.strip()
proof=dict(at=datetime.now(timezone.utc).isoformat(),pr=823,oldHead=parent,head=head,
    normalPush=True,remoteVerified=True,forcePush=False,sourceReceiptSha256=hashlib.sha256(raw).hexdigest(),
    allSevenLogsAuthenticated=True,sourceProcessesReaped=True,allOldAssertionsPreserved=True,
    currentSharedFixtures78=True,actualNativeExecuted=False,completeCI=False,issueClosed=False)
(coord/'integration-v12-union-review/pr823-witness-source-qualified-publication-v35.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof))
