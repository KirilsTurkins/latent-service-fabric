from pathlib import Path
import hashlib
import json
import subprocess

coord=Path(__file__).resolve().parent
root=Path(r'C:\Users\turkins\Desktop\lf-p4-current-java-bd4-union-v12')
head='e9a054503aed62c4549d965301d6a4a84dd1a117'
parent='0a783d97762f763ca6ab237d4bb36eb306bbddec'
for path in ('api','apps','crates','sdk','wit','schemas','Cargo.toml','Cargo.lock','rust-toolchain.toml'):
    hashes=[subprocess.check_output(['git','-C',str(root),'rev-parse',rev+':'+path]).decode().strip() for rev in (parent,head)]
    assert hashes[0]==hashes[1],path
previous=json.loads((coord/'integration-v12-union-review/current-fd-real-node-source-paired-steps-v13.json').read_text())
steps=[list(row) for row in previous]
steps[-1]=[part.replace('real-node-v13','real-node-v14').replace(parent,head) for part in steps[-1]]
assert '--unresolved-effect-close' not in steps[-1]
manifest=json.loads((coord/'integration-v12-current-java-tools-custody/current-six-qualified-manifest-v7.json').read_text())
assert steps[-1][steps[-1].index('--current-selections-digest')+1]==manifest['selectionDigest']
source=(coord/'portable-v2-reconstructed-native-controller-20261007-v93.py').read_text()
old='assert all(row[:2] == ["cargo", "+1.97.1"] for row in steps) if mode == "native" else all(row[0] == "python3" for row in steps)'
assert source.count(old)==1;source=source.replace(old,'assert mode == "native" and steps == '+repr(steps))
controller=coord/'integration-v12-lease-fixed-real-node-source-paired-controller-v14.py';controller.write_text(source,encoding='utf8')
(coord/'integration-v12-union-review/lease-fixed-real-node-source-paired-steps-v14.json').write_text(json.dumps(steps,indent=2)+'\n')
report=dict(actualNativeAndConductorHead=head,actualCompilerHead=manifest['actualCompilerHead'],
    allSixCompiledCaptureHashesVerified=True,selectionDigest=manifest['selectionDigest'],
    exactDefaultCampaignSelected=True,optionalRestoreNotSelected=True,closedRestoreSourceQualificationSeparate=True,
    originalLeaseIntervalRespectedAfterInspection=True,productLeaseDeadlineAndPreconditionsChanged=False,
    sameOriginalHeavyLockAcrossActualToolBuildsAndCampaign=True,oldFailedRootResumed=False,
    originalCampaignDeadline=1200,originalControllerDeadline=1800,freshExecutionPending=True,
    controllerSha256=hashlib.sha256(controller.read_bytes()).hexdigest())
(coord/'integration-v12-union-review/lease-fixed-real-node-preparation-v14.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
