"""Fresh controlled attempt with actual failure observation, no old-root resume."""
import hashlib
import json
from pathlib import Path

coord=Path(__file__).resolve().parent
head='2c441d83f2706c402c167bedfa2d4dfb042faca7'
steps=json.loads((coord/'integration-v12-union-review/current-java-source-paired-node-steps-v7.json').read_text())
steps=[list(row) for row in steps]
steps[2]=[part.replace('real-node-v7','real-node-v8').replace(
    '291f6f13da92aa675b5caa955b26e2c27f395d05',head) for part in steps[2]]
steps.insert(0,['cargo','+1.97.1','test','-p','latentd','--lib',
    'standalone::startup_observation::tests::','--all-features','--locked','--offline',
    '--','--test-threads=1'])
steps.insert(1,['cargo','+1.97.1','clippy','-p','latentd','--all-targets','--all-features',
    '--locked','--offline','--no-deps','--','-D','warnings'])
source=(coord/'portable-v2-reconstructed-native-controller-20261007-v93.py').read_text()
old='assert all(row[:2] == ["cargo", "+1.97.1"] for row in steps) if mode == "native" else all(row[0] == "python3" for row in steps)'
assert source.count(old)==1
source=source.replace(old,'assert mode == "native" and steps == '+repr(steps))
path=coord/'integration-v12-observed-startup-source-paired-node-controller-v8.py'
path.write_text(source,encoding='utf8')
step_path=coord/'integration-v12-union-review/observed-startup-source-paired-node-steps-v8.json'
step_path.write_text(json.dumps(steps,indent=2)+'\n',encoding='utf8')
receipt=dict(head=head,steps=len(steps),controllerSha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    originalCampaignDeadline=1200,originalOuterDeadline=1800,oneHeavyLockThroughToolsAndCampaign=True,
    oldFailedRootResumed=False,oldBusinessOperationsRetried=False,
    compilerMaterialHead='b133685145a66940358ec38eb6c90e61e6fa39b3',actualExecutionPending=True)
(coord/'integration-v12-union-review/observed-startup-campaign-preparation-v8.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt))
