from pathlib import Path
import hashlib
import json

base=Path('/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data')
job=base/'jobs/integration-v12-current-java-six-compiler-v7'
raw=(job/'receipt.json').read_bytes();receipt=json.loads(raw)
head='0a0dc2818946111c8657e6b681ecef1f9f3fafab'
assert receipt['head']==head and receipt['passed'] and receipt['sourceClean'] and receipt['sourceHeadUnchanged'] and receipt['originalProcessReaped']
capture=base/'jobs/integration-v12-current-java-six-captures-v7'
manifest=json.loads((base/'jobs/integration-v12-current-java-six-capture-manifest-v7.json').read_bytes())
for name,item in manifest['files'].items():
    raw_file=(capture/name).read_bytes()
    assert len(raw_file)==item['size'] and hashlib.sha256(raw_file).hexdigest()==item['sha256']
rows=[]
for folder in sorted(capture.iterdir()):
    report=json.loads((folder/'report.json').read_bytes())
    assert report['sourceRevision']==head and report['compiled'] is True and not report['workingTreeChanged']
    selected=next(row for row in manifest['selections'] if row['variant']==report['variant'])
    assert selected['sourceCommit']==head
    rows.append(dict(variant=report['variant'],sourceHead=head,componentDigest=report['componentDigest'],
        componentBytes=report['componentBytes'],companionDigest=report['companionDigest'],
        hostAbiDigest=report['hostAbiDigest'],recipeDigest=report['recipeDigest'],
        deferredHttpRequirementsDigest=report.get('deferredHttpRequirementsDigest'),
        reportDigest=selected['reportDigest'],compilerInputsDigest=selected['compilerInputsDigest'],
        actualImports=report['actualImports']))
assert len(rows)==6
selector=(base/'jobs/integration-v12-current-java-six-selected-v7.json').read_bytes()
result=dict(actualCompilerHead=head,actualReceiptSha256=hashlib.sha256(raw).hexdigest(),
 receipt=str(job/'receipt.json'),captureRoot=str(capture),selectionPath=str(base/'jobs/integration-v12-current-java-six-selected-v7.json'),
 selectionDigest='sha256:'+hashlib.sha256(selector).hexdigest(),all835CapturedFileHashesVerified=len(manifest['files'])==835,
 rows=rows,allActualCompiledAndValidated=True,oldFailedV3ReceiptsPreserved=True,
 signingAdmissionGuestNodeFullCiQualification=False)
path=base/'jobs/integration-v12-current-java-six-qualified-manifest-v7.json'
path.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
