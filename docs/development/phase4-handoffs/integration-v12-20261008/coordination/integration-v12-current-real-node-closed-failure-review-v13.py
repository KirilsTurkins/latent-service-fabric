from pathlib import Path
import hashlib
import json

base=Path('/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data')
root=base/'jobs/integration-v12-current-java-real-node-v13/campaign'
floor_path=root/'node/data/supply-chain/floor.json'
if not floor_path.exists():
    matches=list((root/'node').glob('*/supply-chain/floor.json'))
    assert len(matches)==1
    floor_path=matches[0]
floor=json.loads(floor_path.read_bytes())
error_path=root/'evidence/node-2-startup.stderr'
raw=error_path.read_bytes();trace=json.loads(raw.splitlines()[0])
failure=json.loads((root/'evidence/node-2-startup-failure.json').read_bytes())
receipt=json.loads((root/'campaign-receipt.json').read_bytes())
result=dict(nativeHead=receipt['nativeSourceCommit'],compilerHead=receipt['compilerSourceCommit'],
    trace=trace,node2Exit=failure['exitStatus'],node2ProcessReaped=failure['reaped'],
    signedPublications=len([case for case in receipt['measuredCases'] if case.startswith('publish-')]),
    actualGuestInvocations=0,failureStage=receipt['failedStage'],floorKeys=list(floor),
    stderrSha256=hashlib.sha256(raw).hexdigest(),failureObservedFileUnixSeconds=int(error_path.stat().st_mtime),
    floorWrittenFileUnixSeconds=int(floor_path.stat().st_mtime),
    originalRestartNotBefore=floor.get('restartNotBefore',floor.get('restart_not_before')),
    physicalMutationRetried=False,originalRootResumed=False)
(base/'jobs/integration-v12-current-real-node-closed-failure-review-v13.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
