"""Audit explicitly owned, reaped disposable source clones; never product worktrees."""
from pathlib import Path
import hashlib
import json
import os
import subprocess

base=Path('/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data').resolve()
jobs=[
 'integration-v12-current-effect-startup-union-source-v4',
 'integration-v12-startup-observation-box-source-v3',
 'integration-v12-actual-startup-report-preservation-source-v2',
 'integration-v12-actual-startup-wrapper-source-v1',
 'integration-v12-http-current-java-final-source-v2',
 'integration-v12-current-public-effect-union-source-v1',
 'integration-v12-effect-actual-retention-source-v2',
 'integration-v12-effect-actual-receipt-tests-source-v3',
]
rows=[]
for job in jobs:
    receipt_path=base/'jobs'/job/'receipt.json'
    raw=receipt_path.read_bytes();receipt=json.loads(raw)
    assert receipt['sourceClean'] and receipt['sourceHeadUnchanged'] and receipt['originalProcessReaped']
    head=receipt['head'];target=base/('source-'+head[:16])
    assert target.is_dir() and not target.is_symlink()
    resolved=target.resolve()
    assert resolved.parent==base and resolved.name=='source-'+head[:16]
    actual=subprocess.check_output(['git','-C',str(target),'rev-parse','HEAD'],timeout=20).decode().strip()
    assert actual==head
    assert not subprocess.check_output(['git','-C',str(target),'status','--porcelain'],timeout=20).strip()
    subprocess.run(['git','--git-dir=/gitmeta','cat-file','-e',head+'^{commit}'],check=True,timeout=20)
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal() or int(proc.name)==os.getpid():
            continue
        try:
            cwd=(proc/'cwd').resolve()
            command=(proc/'cmdline').read_bytes()
        except (OSError,RuntimeError):
            continue
        assert target not in cwd.parents and cwd!=target,(job,proc.name,'active-cwd')
        assert str(target).encode() not in command,(job,proc.name,'active-argv')
    rows.append(dict(job=job,head=head,target=str(target),receiptSha256=hashlib.sha256(raw).hexdigest(),
                     sourceClean=True,originalProcessesReaped=True,gitObjectPreserved=True))
output=base/'jobs/integration-v12-owned-source-cache-audit-v1.json'
output.write_text(json.dumps(dict(ownedDisposableSourceClonesOnly=True,productWorktreesSelected=False,
    jobArtifactsSelected=False,rows=rows,deleted=False),indent=2)+'\n')
print(json.dumps({'audited':len(rows),'output':str(output),'deleted':False,'targets':[r['target'] for r in rows]}))
