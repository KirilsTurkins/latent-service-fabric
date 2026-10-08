"""Retain only actual compiler materials, not derived C/build cache trees."""
from pathlib import Path
import hashlib
import json
import shutil

base=Path('/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data')
source_job=base/'jobs/integration-v12-current-java-six-compiler-v7'
head='0a0dc2818946111c8657e6b681ecef1f9f3fafab'
receipt=json.loads((source_job/'receipt.json').read_text())
assert receipt['head']==head and receipt['passed'] and receipt['sourceClean']
assert receipt['sourceHeadUnchanged'] and receipt['originalProcessReaped']
destination=base/'jobs/integration-v12-current-java-six-captures-v7'
assert not destination.exists()
destination.mkdir(mode=0o700)
selected=[]
for report_path in [*source_job.glob('results/*/report.json'),*source_job.glob('diagnostic/*/report.json')]:
    report=json.loads(report_path.read_text())
    assert report['sourceRevision']==head and report['compiled'] is True and report['status']=='compiled'
    assert report['workingTreeChanged'] is False and report['signedNodeExecutionQualified'] is False
    original=report_path.parent; target=destination/report['variant']; target.mkdir(mode=0o700)
    for name in ('report.json','source-inputs.json','source.tar.gz','recipe-inputs.json','compiler-inputs.json'):
        shutil.copyfile(original/name,target/name)
    shutil.copytree(original/'project',target/'project')
    raw=(original/'compiled/component.wasm').read_bytes()
    assert len(raw)==report['componentBytes'] and 'sha256:'+hashlib.sha256(raw).hexdigest()==report['componentDigest']
    (target/'component.wasm').write_bytes(raw)
    selected.append(dict(sourceCommit=head,variant=report['variant'],reportDigest='sha256:'+hashlib.sha256(report_path.read_bytes()).hexdigest(),
        componentDigest=report['componentDigest'],compilerInputsDigest='sha256:'+hashlib.sha256((original/'compiler-inputs.json').read_bytes()).hexdigest()))
assert len(selected)==6 and len({row['variant'] for row in selected})==6
files={path.relative_to(destination).as_posix():dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),size=path.stat().st_size)
       for path in destination.rglob('*') if path.is_file()}
manifest=dict(compilerSource=head,selections=selected,files=files,
    sourcePairedCompilerReceipt='integration-v12-current-java-six-compiler-v7/receipt.json',signedNodeExecutionQualified=False)
(base/'jobs/integration-v12-current-java-six-capture-manifest-v7.json').write_text(json.dumps(manifest,indent=2)+'\n')
selection=dict(schemaVersion='latent.java.current-campaign-selections.v1',selections=selected)
raw=(json.dumps(selection,indent=2)+'\n').encode()
(base/'jobs/integration-v12-current-java-six-selected-v7.json').write_bytes(raw)
print(json.dumps(dict(head=head,copiedFiles=len(files),selectionDigest='sha256:'+hashlib.sha256(raw).hexdigest(),
    signedNodeExecutionQualified=False,compilerCacheCopied=False)))
