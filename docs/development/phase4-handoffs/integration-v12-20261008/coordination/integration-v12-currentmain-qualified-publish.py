from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

coord=Path(__file__).resolve().parent
pr=int(sys.argv[1]);assert pr in (823,828)
configuration={
 823:dict(root='lf-p4-current-java-bd4-union-v12',branch='feat/phase4-state-runtime-718',
          expected='27d32ea9780784cab5cb1a14aee8b2fb4a46cb03',head='511d5687f360258d05469cd2593de4d6f2556cf1',proofHead='eafeb0f3046ddd5756258a37940a1d6cfd69f04a',
          source='integration-v12-current823-development0cd-source-v8',native='integration-v12-current823-development0cd-native-v8',
          counts=374),
 828:dict(root='lf-p4-pr828-current-java-union-v12',branch='feat/phase4-http-409',
          expected='6f0a8e82299aa0a1224dee293aaa8a4db7f3a7d9',head='f0322bb74085cc452cc7c9885a08b89ab218d290',proofHead='237fb3edc4ee39d17e361d69e88b43be2d5ea4f8',
          source='integration-v12-current828-development0cd-source-v8',native='integration-v12-current828-development0cd-native-v8',
          counts=375),
}[pr]
root=Path(r'C:\Users\turkins\Desktop')/configuration['root']
repo='KirilsTurkins/latent-service-fabric';env=dict(os.environ,GODEBUG='http2client=0')
def git(*args):return subprocess.check_output(['git','-C',str(root),*args],env=env,text=True).strip()
def gh(*args):return subprocess.check_output(['gh',*args],env=env)
assert git('rev-parse','HEAD')==configuration['head'] and not git('status','--porcelain')
proofs=[]
for job in (configuration['source'],configuration['native']):
    path=coord/job/'receipt.json';raw=path.read_bytes();receipt=json.loads(raw)
    assert receipt['head']==configuration['proofHead'] and receipt['passed'] and receipt['sourceClean']
    assert receipt['sourceHeadUnchanged'] and receipt['originalProcessReaped']
    proofs.append(dict(job=job,steps=len(receipt['steps']),sha256=hashlib.sha256(raw).hexdigest()))
closures=json.loads((coord/'integration-v12-union-review/current9f-website-only-native-source-closure.json').read_text())
closure=next(row for row in closures if row['pr']==pr)
assert closure['parentNativeAndSourceHead']==configuration['proofHead'] and closure['currentMainDescendant']==configuration['head']
assert git('diff','--name-only',configuration['proofHead'],configuration['head'])=='website/scripts/test-discovery.mjs'
remote=json.loads(gh('api',f'repos/{repo}/pulls/{pr}'))
assert remote['state']=='open' and remote['head']['ref']==configuration['branch'] and remote['head']['sha']==configuration['expected']
subprocess.run(['git','-C',str(root),'merge-base','--is-ancestor','9f7aab58400d446f451964dc492b34dc46d09f14',configuration['head']],check=True,env=env)
subprocess.run(['git','-C',str(root),'merge-base','--is-ancestor',configuration['expected'],configuration['head']],check=True,env=env)
addition=f'''

Development `9f7aab58` is integrated while retaining both parents' source cases, minimum counts, ignores, prerequisites and workflow controls. The two new Node identity/projection cases remain registered and are exercised by the native check on `{configuration['proofHead'][:8]}`. All seven Linux source gates pass on that parent ({configuration['counts']} tests, one existing Windows skip), and its native runtime and original strict lint checks pass. The final main merge changes only the website discovery script; Rust, SDK, generator and lock trees are byte-identical, and the receipts keep their actual source heads. Browser discovery, full hosted CI and signed public-workflow acceptance remain pending.
'''
if pr==823:
    addition+='The explicit Java recovery world now retains the maintained runtime clock declarations required by the TeaVM adapter; declaring them supplies no runtime grant. Fresh actual compilation of all six current Java variants is still required after the preserved failed C-stage attempt. Startup failure observation keeps the actual original error and bounded producer-defined codes.\n'
body=coord/f'integration-v12-union-review/pr{pr}-current0cd-qualified-body.md'
body.write_text((remote.get('body') or '')+addition,encoding='utf8',newline='\n')
guard=json.loads(gh('api',f'repos/{repo}/pulls/{pr}'));assert guard['head']['sha']==configuration['expected']
subprocess.run(['git','-C',str(root),'push','origin','HEAD:refs/heads/'+configuration['branch']],check=True,env=env)
assert git('ls-remote','origin','refs/heads/'+configuration['branch']).split()[0]==configuration['head']
gh('pr','edit',str(pr),'--repo',repo,'--body-file',str(body))
value=dict(at=datetime.now(timezone.utc).isoformat(),pr=pr,oldHead=configuration['expected'],newHead=configuration['head'],
    main='9f7aab58400d446f451964dc492b34dc46d09f14',normalPush=True,remoteVerified=True,
    actualProofHead=configuration['proofHead'],websiteOnlyClosure=closure,
    proofs=proofs,completeCI=False,issuesClosed=[],worktreesDeleted=[])
(coord/f'integration-v12-union-review/pr{pr}-current0cd-normal-publication-v8.json').write_text(json.dumps(value,indent=2)+'\n')
print(json.dumps(value))
