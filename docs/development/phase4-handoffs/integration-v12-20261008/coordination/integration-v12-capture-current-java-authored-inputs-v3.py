"""Capture current maintained authoring inputs only; never a compile receipt."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

base=Path('/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data')
head='2c441d83f2706c402c167bedfa2d4dfb042faca7'
source=base/('source-'+head[:16])
assert subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD']).decode().strip()==head
assert not subprocess.check_output(['git','-C',str(source),'status','--porcelain']).strip()
out=base/'jobs/integration-v12-current-java-authored-inputs-v3'
assert not out.exists()
out.mkdir(mode=0o700)
sys.path.insert(0,str(source))
from tools.compile_transaction_guests import authored_project, VARIANTS, JAVA_SCHEMA_VARIANTS, JAVA_DIAGNOSTIC_VARIANT
from tools.rust_capsule_project import inventory, snapshot
rows=[]
for variant in (*VARIANTS,*JAVA_SCHEMA_VARIANTS,JAVA_DIAGNOSTIC_VARIANT):
    project=authored_project('java',variant,out/variant)
    captured=snapshot(project)
    raw=inventory(captured)
    (out/(variant+'-source-inputs.json')).write_bytes(raw)
    rows.append(dict(variant=variant,sourceRevision=head,sourceDigest='sha256:'+hashlib.sha256(raw).hexdigest(),
                     fileCount=len(captured),compiled=False,signedNodeExecutionQualified=False))
assert not subprocess.check_output(['git','-C',str(source),'status','--porcelain']).strip()
(out/'capture-receipt.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps({'sourceRevision':head,'variants':rows,'sourceClean':True,'compiled':False}))
