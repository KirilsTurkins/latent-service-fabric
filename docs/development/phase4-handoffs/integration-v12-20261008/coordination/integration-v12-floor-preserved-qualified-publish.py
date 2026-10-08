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
   old='511d5687f360258d05469cd2593de4d6f2556cf1',head='44754a7b9de0b41c456bcbbf31797b0cd47b0814',
   source='integration-v12-current823-restored-aot-floor-source-v9',native='integration-v12-current823-development0cd-native-v8',
   nativeHead='eafeb0f3046ddd5756258a37940a1d6cfd69f04a'),
 828:dict(root='lf-p4-pr828-current-java-union-v12',branch='feat/phase4-http-409',
   old='6f0a8e82299aa0a1224dee293aaa8a4db7f3a7d9',head='6f03062bc9131e477d09639fa9e77e7f84103d57',
   source='integration-v12-current828-restored-aot-floor-source-v9',native='integration-v12-current828-development0cd-native-v8',
   nativeHead='237fb3edc4ee39d17e361d69e88b43be2d5ea4f8'),
}[pr]
root=Path(r'C:\Users\turkins\Desktop')/cfg['root'];repo='KirilsTurkins/latent-service-fabric'
env=dict(os.environ,GODEBUG='http2client=0')
def git(*args):return subprocess.check_output(['git','-C',str(root),*args],env=env,text=True).strip()
def gh(*args):return subprocess.check_output(['gh',*args],env=env)
assert git('rev-parse','HEAD')==cfg['head'] and not git('status','--porcelain')
proofs=[]
for job,head in ((cfg['source'],cfg['head']),(cfg['native'],cfg['nativeHead'])):
    raw=(coord/job/'receipt.json').read_bytes();receipt=json.loads(raw)
    assert receipt['head']==head and receipt['passed'] and receipt['sourceClean']
    assert receipt['sourceHeadUnchanged'] and receipt['originalProcessReaped']
    proofs.append(dict(job=job,actualHead=head,sha256=hashlib.sha256(raw).hexdigest()))
floor=json.loads((coord/'integration-v12-union-review/current-aot-only-fixed-native-source-closure.json').read_text())
record=next(row for row in floor if row['pr']==pr)
assert record['current']==cfg['head'] and record['productionSourceNativeClosureUnchanged']
website=json.loads((coord/'integration-v12-union-review/current9f-website-only-native-source-closure.json').read_text())
current=next(row for row in website if row['pr']==pr)
assert current['parentNativeAndSourceHead']==cfg['nativeHead'] and current['currentMainDescendant']==record['parent']
if pr==828:
    aot_path=coord/'integration-v12-current-http-original-aot-floor-native-v9/receipt.json'
    aot=json.loads(aot_path.read_bytes())
    assert aot['head']==cfg['head'] and aot['passed'] and aot['originalProcessReaped'] and aot['sourceClean']
    assert 'AOT sandbox: 12 unprivileged real-entry probes and exact-policy syscall probe passed' in (
        aot_path.parent/'step-1.log').read_text()
    proofs.append(dict(job=aot_path.parent.name,actualHead=cfg['head'],sha256=hashlib.sha256(aot_path.read_bytes()).hexdigest()))
remote=json.loads(gh('api',f'repos/{repo}/pulls/{pr}'))
assert remote['state']=='open' and remote['head']['ref']==cfg['branch'] and remote['head']['sha']==cfg['old']
subprocess.run(['git','-C',str(root),'merge-base','--is-ancestor',cfg['old'],cfg['head']],check=True,env=env)
subprocess.run(['git','-C',str(root),'merge-base','--is-ancestor','9f7aab58400d446f451964dc492b34dc46d09f14',cfg['head']],check=True,env=env)
addition='''

The current development merge preserves the historical AOT sandbox minimum of one, its original custom harness, all twelve real-entry probes and the exact-policy syscall success marker. No source case, ignore, resource bound, workflow command or fixture is removed. The final source gates pass with all current-main Java diagnostic cases included. Rust runtime and strict lint receipts retain their actual pre-website/floor-only source heads; their production source closure is unchanged. Browser/full hosted CI and full signed guest acceptance remain pending.
'''
if pr==828: addition+='The restored current AOT gate was executed: all twelve unprivileged entry probes and the original exact-policy syscall probe passed. The current-main runtime check passed all registered Node/Wire/daemon cases and the two original strict lint selections.\n'
body=coord/f'integration-v12-union-review/pr{pr}-current9f-floor-preserved-body.md'
body.write_text((remote.get('body') or '')+addition,encoding='utf8',newline='\n')
guard=json.loads(gh('api',f'repos/{repo}/pulls/{pr}'));assert guard['head']['sha']==cfg['old']
subprocess.run(['git','-C',str(root),'push','origin','HEAD:refs/heads/'+cfg['branch']],check=True,env=env)
assert git('ls-remote','origin','refs/heads/'+cfg['branch']).split()[0]==cfg['head']
gh('pr','edit',str(pr),'--repo',repo,'--body-file',str(body))
value=dict(at=datetime.now(timezone.utc).isoformat(),pr=pr,oldHead=cfg['old'],newHead=cfg['head'],
    normalPush=True,remoteVerified=True,proofs=proofs,currentMain='9f7aab58400d446f451964dc492b34dc46d09f14',
    preservedHistoricalAotMinimum=1,fullCi=False,issuesClosed=[],worktreesDeleted=[])
(coord/f'integration-v12-union-review/pr{pr}-current9f-floor-preserved-publication-v9.json').write_text(json.dumps(value,indent=2)+'\n')
print(json.dumps(value))
