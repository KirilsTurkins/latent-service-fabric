from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess

base=Path('/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data').resolve()
receipt=base/'jobs/integration-v12-owned-source-cache-audit-v1.json'
raw=receipt.read_bytes();audit=json.loads(raw)
assert audit['ownedDisposableSourceClonesOnly'] and not audit['productWorktreesSelected']
assert not audit['jobArtifactsSelected'] and not audit['deleted']
assert len(audit['rows'])==8
deleted=[]
for row in audit['rows']:
    target=Path(row['target']);resolved=target.resolve()
    assert target.is_dir() and not target.is_symlink() and resolved.parent==base
    assert resolved.name=='source-'+row['head'][:16]
    assert subprocess.check_output(['git','-C',str(target),'rev-parse','HEAD']).decode().strip()==row['head']
    assert not subprocess.check_output(['git','-C',str(target),'status','--porcelain']).strip()
    subprocess.run(['git','--git-dir=/gitmeta','cat-file','-e',row['head']+'^{commit}'],check=True)
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal() or int(proc.name)==os.getpid(): continue
        try:
            cwd=(proc/'cwd').resolve();command=(proc/'cmdline').read_bytes()
        except (OSError,RuntimeError): continue
        assert cwd!=target and target not in cwd.parents
        assert str(target).encode() not in command
    shutil.rmtree(target)
    deleted.append(dict(target=str(target),head=row['head'],reconstructibleFromGit=True))
result=dict(auditSha256=hashlib.sha256(raw).hexdigest(),deletedDisposableClones=deleted,
            productWorktreesDeleted=False,jobArtifactsDeleted=False,peerPathsDeleted=False)
(base/'jobs/integration-v12-owned-source-cache-retirement-v1.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
