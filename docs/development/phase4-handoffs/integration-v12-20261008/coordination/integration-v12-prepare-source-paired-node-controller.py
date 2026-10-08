"""Build the exact package/node tools and run the unchanged bounded campaign."""
import hashlib
import json
from pathlib import Path

coord=Path(__file__).resolve().parent
base='/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data'
head='291f6f13da92aa675b5caa955b26e2c27f395d05'
job='integration-v12-current-java-real-node-v7'
steps=[['cargo','+1.97.1','build','-p','latent-packaging','--example','capsule_contracts',
        '-p','latent-policy','--example','capsule_authoring','--all-features','--locked','--offline'],
       ['cargo','+1.97.1','build','-p','latent','--bin','latent','-p','latentd','--bin','latentd',
        '-p','latent-wasmtime','--bin','latent-aot-compiler','--all-features','--locked','--offline']]
execution=json.loads((coord/'integration-v12-union-review/current-java-current-node-steps-v6.json').read_text())[0]
execution=[value.replace('real-node-v6','real-node-v7') for value in execution]
steps.append(execution)
source=(coord/'portable-v2-reconstructed-native-controller-20261007-v93.py').read_text()
old='assert all(row[:2] == ["cargo", "+1.97.1"] for row in steps) if mode == "native" else all(row[0] == "python3" for row in steps)'
assert source.count(old)==1
source=source.replace(old,'assert mode == "native" and steps == '+repr(steps))
path=coord/'integration-v12-current-java-source-paired-node-controller-v7.py'
path.write_text(source,encoding='utf8')
step_path=coord/'integration-v12-union-review/current-java-source-paired-node-steps-v7.json'
step_path.write_text(json.dumps(steps,indent=2)+'\n',encoding='utf8')
print(json.dumps({'controllerSha256':hashlib.sha256(path.read_bytes()).hexdigest(),
    'exactHead':head,'toolSourceBuilds':2,'originalCampaignDeadline':1200,
    'outerOriginalDeadline':1800,'oneHeavyLockAcrossBuildAndExecution':True,
    'failedSharedTargetAttemptPreserved':True,'executed':False}))
