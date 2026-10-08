from pathlib import Path
import hashlib
import json

coord=Path(__file__).resolve().parent
head='0a0dc2818946111c8657e6b681ecef1f9f3fafab'
job='integration-v12-current-java-real-node-v12'
manifest=json.loads((coord/'integration-v12-current-java-tools-custody/current-six-qualified-manifest-v7.json').read_text())
assert manifest['actualCompilerHead']==head and manifest['allActualCompiledAndValidated'] and manifest['all835CapturedFileHashesVerified']
steps=json.loads((coord/'integration-v12-union-review/current-java-source-paired-node-steps-v7.json').read_text())
steps=[list(row) for row in steps]
for index,part in enumerate(steps[-1]):
    steps[-1][index]=part.replace('real-node-v7','real-node-v12').replace(
        '291f6f13da92aa675b5caa955b26e2c27f395d05',head).replace('six-captures-v2','six-captures-v7').replace(
        'six-selected-v1','six-selected-v7').replace('sha256:5100ebe6de062db8ce6962178e0d7b5079247d9de4430995d5d3abb2049de177',manifest['selectionDigest'])
assert steps[-1][steps[-1].index('--current-selections-digest')+1]==manifest['selectionDigest']
source=(coord/'portable-v2-reconstructed-native-controller-20261007-v93.py').read_text()
old='assert all(row[:2] == ["cargo", "+1.97.1"] for row in steps) if mode == "native" else all(row[0] == "python3" for row in steps)'
assert source.count(old)==1;source=source.replace(old,'assert mode == "native" and steps == '+repr(steps))
path=coord/'integration-v12-current-java-real-node-source-paired-controller-v12.py'
path.write_text(source,encoding='utf8')
(coord/'integration-v12-union-review/current-java-real-node-source-paired-steps-v12.json').write_text(json.dumps(steps,indent=2)+'\n')
report=dict(actualCompilerHead=head,actualCompilerReceiptSha256=manifest['actualReceiptSha256'],
    allSixActualCurrentCapturesSelected=True,selectionDigest=manifest['selectionDigest'],
    exactToolBuildHead=head,sameHeavyLockAcrossPackageCliNodeAotBuildAndCampaign=True,
    originalCampaignDeadlineSeconds=1200,originalControllerDeadlineSeconds=1800,
    originalPreconditionsAndBusinessMutationIdsUnchanged=True,oldFailedRootsResumed=False,
    oldBusinessMutationsRetried=False,actualExecutionPending=True,
    controllerSha256=hashlib.sha256(path.read_bytes()).hexdigest())
(coord/'integration-v12-union-review/current-java-real-node-preparation-v12.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
