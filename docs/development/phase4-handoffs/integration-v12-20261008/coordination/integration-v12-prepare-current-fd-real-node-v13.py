from pathlib import Path
import hashlib
import json

coord=Path(__file__).resolve().parent
head='0a783d97762f763ca6ab237d4bb36eb306bbddec'
previous=json.loads((coord/'integration-v12-union-review/current-java-real-node-source-paired-steps-v12.json').read_text())
steps=[list(row) for row in previous]
steps[-1]=[part.replace('real-node-v12','real-node-v13').replace('0a0dc2818946111c8657e6b681ecef1f9f3fafab',head) for part in steps[-1]]
manifest=json.loads((coord/'integration-v12-current-java-tools-custody/current-six-qualified-manifest-v7.json').read_text())
assert steps[-1][steps[-1].index('--current-selections-digest')+1]==manifest['selectionDigest']
source=(coord/'portable-v2-reconstructed-native-controller-20261007-v93.py').read_text()
old='assert all(row[:2] == ["cargo", "+1.97.1"] for row in steps) if mode == "native" else all(row[0] == "python3" for row in steps)'
assert source.count(old)==1;source=source.replace(old,'assert mode == "native" and steps == '+repr(steps))
path=coord/'integration-v12-current-fd-real-node-source-paired-controller-v13.py';path.write_text(source,encoding='utf8')
(coord/'integration-v12-union-review/current-fd-real-node-source-paired-steps-v13.json').write_text(json.dumps(steps,indent=2)+'\n')
record=dict(nativeAndConductorHead=head,actualCompilerHead=manifest['actualCompilerHead'],
    qualifiedCompilerReceiptSha256=manifest['actualReceiptSha256'],selectionDigest=manifest['selectionDigest'],
    nativeBuildAndExecutionUseOneOriginalHeavyLock=True,compilerMaterialScopeDistinctNotRelabeled=True,
    newDisposableRoot='integration-v12-current-java-real-node-v13/campaign',oldFailedRootResumed=False,
    businessRetriesAdded=False,originalCampaignDeadline=1200,originalControllerDeadline=1800,
    nativeActualExecutionPending=True,controllerSha256=hashlib.sha256(path.read_bytes()).hexdigest())
(coord/'integration-v12-union-review/current-fd-real-node-preparation-v13.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record))
