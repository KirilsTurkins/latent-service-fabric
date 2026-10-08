from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

coord=Path(__file__).resolve().parent;pr=int(sys.argv[1]);assert pr in (823,828)
cfg={
 823:dict(root='lf-p4-current-java-bd4-union-v12',branch='feat/phase4-state-runtime-718',old='0a0dc2818946111c8657e6b681ecef1f9f3fafab',
          head='0a783d97762f763ca6ab237d4bb36eb306bbddec',count=374),
 828:dict(root='lf-p4-pr828-current-java-union-v12',branch='feat/phase4-http-409',old='7bc6e42254ef94c2b0248ad174d1e959aefc10e2',
          head='0a637ba7844c7fe461873d0fa783bca8166f4971',count=375),
}[pr]
root=Path(r'C:\Users\turkins\Desktop')/cfg['root'];repo='KirilsTurkins/latent-service-fabric';env=dict(os.environ,GODEBUG='http2client=0')
def git(*args):return subprocess.check_output(['git','-C',str(root),*args],env=env,text=True).strip()
def gh(*args):return subprocess.check_output(['gh',*args],env=env)
assert git('rev-parse','HEAD')==cfg['head'] and not git('status','--porcelain')
job=f'integration-v12-current{pr}-developmentfd-source-v12'
raw=(coord/job/'receipt.json').read_bytes();receipt=json.loads(raw)
assert receipt['head']==cfg['head'] and receipt['passed'] and receipt['sourceClean'] and receipt['sourceHeadUnchanged'] and receipt['originalProcessReaped']
closure=next(row for row in json.loads((coord/'integration-v12-union-review/current-fd-native-compiler-byte-closure.json').read_text()) if row['pr']==pr)
assert closure['actualQualifiedParent']==cfg['old'] and closure['currentFdHead']==cfg['head']
subprocess.run(['git','-C',str(root),'merge-base','--is-ancestor','fd4623acdc8f94e72291b85716c16d10dcd118cd',cfg['head']],check=True,env=env)
remote=json.loads(gh('api',f'repos/{repo}/pulls/{pr}'));assert remote['state']=='open' and remote['head']['ref']==cfg['branch'] and remote['head']['sha']==cfg['old']
addition=f'''

Development `fd4623ac` is integrated with all current source gates passing on `{cfg['head'][:8]}` ({cfg['count']} cases, one original Windows skip). This merge adds the retained Java native-AOT evidence and two composition-qualifier evidence lines. Rust, SDK, protocol, schemas, lockfiles and current transaction compiler inputs are byte-identical to the already validated parent; native/compiler receipts retain their actual source heads. No fixture, assertion, minimum count or workflow command is removed. The separate composition/browser/full hosted CI obligations remain pending.
'''
if pr==823:
    addition+='All six current Java variants actually compiled and validated on parent `0a0dc281` under the original pinned toolchain/deadlines, with all835 retained material hashes verified. This does not yet qualify signed guest execution, provider effects or restore.\n'
if pr==823:
    body_text='''The daemon composes host-owned transactions, read-only queries, original-result recovery and effect management with its installed state store, dispatcher, policy, clock and native capacity owners. Result/effect reads retain the original caller, publication and current data-read decisions through response release. Effect status verifies actual payload retention and durable management receipts, distinguishes provider confirmation from administrator termination, and preserves original attempt history. Java source packaging uses an explicit current compiler-material selection and the maintained transaction/clock declarations; descriptions supply no grants.

Current `development` fd4623ac is integrated, with all parent cases, ignores, limits and the original AOT sandbox floor preserved. Current source gates pass374 cases with one original Windows skip. Native evidence on the unchanged c844 parent passes58 signing cases, Node116/Wire195/daemon282 with27 original ignored fixtures, ordinary signing Clippy and the original selected strict lint gate. All six current Java variants actually compile and validate;835 capture hashes are verified. Receipts retain their actual source heads. The extra signing-only strict diagnostic retains four baseline lint findings. Signed public guest/provider/restore workflows, browser/full hosted CI and the complete milestone acceptance remain pending. Tracks #718, #388, #387 and #400.
'''
else:
    body_text='''Shared HTTP ingress routes transactional commands, queries and original-result recovery through the installed transaction owners. Admission keeps the original deadline and caller/source policy, charges native request/response ownership, and permits bounded recovery progress while ordinary responses remain retained. The native inspection command waits for actual runtime retirement and uses the existing bounded encoder. Current Java packaging and typed client/profile models stay synchronized.

Current `development` fd4623ac is integrated, with all parent cases, ignores, limits and the original AOT sandbox floor preserved. Current source gates pass375 cases with one original Windows skip. Native evidence on the unchanged c844 parent passes58 signing cases, Node116/Wire193/daemon282 with27 original ignored fixtures, ordinary signing Clippy and the original selected strict lint gate. The restored AOT custom harness executed all12 unprivileged entry probes and its exact-policy syscall probe. Receipts retain their actual source heads. Full hosted CI, signed public transactional HTTP/browser workflows and complete #409 acceptance remain pending.
'''
body=coord/f'integration-v12-union-review/pr{pr}-current-fd-qualified-body.md';body.write_text(body_text,encoding='utf8',newline='\n')
guard=json.loads(gh('api',f'repos/{repo}/pulls/{pr}'));assert guard['head']['sha']==cfg['old']
subprocess.run(['git','-C',str(root),'push','origin','HEAD:refs/heads/'+cfg['branch']],check=True,env=env)
assert git('ls-remote','origin','refs/heads/'+cfg['branch']).split()[0]==cfg['head']
gh('pr','edit',str(pr),'--repo',repo,'--body-file',str(body))
record=dict(at=datetime.now(timezone.utc).isoformat(),pr=pr,oldHead=cfg['old'],newHead=cfg['head'],normalPush=True,remoteVerified=True,
    currentMain='fd4623acdc8f94e72291b85716c16d10dcd118cd',sourceReceiptSha256=hashlib.sha256(raw).hexdigest(),
    nativeCompilerClosure=closure,fullCi=False,issuesClosed=[],worktreesDeleted=[])
(coord/f'integration-v12-union-review/pr{pr}-current-fd-normal-publication-v12.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({'pr':pr,'oldHead':cfg['old'],'newHead':cfg['head'],'normalPush':True,'remoteVerified':True,'fullCi':False}))
