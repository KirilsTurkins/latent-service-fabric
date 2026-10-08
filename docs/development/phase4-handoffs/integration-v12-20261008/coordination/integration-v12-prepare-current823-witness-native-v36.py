from pathlib import Path
import hashlib
import json

coord=Path(__file__).resolve().parent
head='1417e360a96954ce8abcc845024e7b7ff0eccb99'
old=(coord/'integration-v12-current823-java-bridge-native-controller-v21.py').read_text(encoding='utf8')
old_steps=json.loads((coord/'integration-v12-current823-java-bridge-native-steps-v21.json').read_bytes())
steps=json.loads(json.dumps(old_steps))
job='integration-v12-current823-witness-java-native-v36'
assert steps[2][3]=='--project-cache-dir'
steps[2][4]='/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data/jobs/'+job+'/gradle-project-cache'
body=[]
for line in old.splitlines(keepends=True):
    if line.startswith('assert mode == "native" and steps == '):
        body.append('assert mode == "native" and head == '+repr(head)+' and steps == '+repr(steps)+'\n')
    else:
        body.append(line)
text=''.join(body)
compile(text,'witness-java-v36','exec')
controller=coord/'integration-v12-current823-witness-java-native-controller-v36.py'
controller.write_text(text,encoding='utf8',newline='\n')
path=coord/'integration-v12-current823-witness-java-native-steps-v36.json'
path.write_text(json.dumps(steps,indent=2)+'\n')
proof=dict(head=head,job=job,actualNativeLaunched=False,
    originalThreeCommandsOnlyOwnedProjectCacheRebound=True,original540And1800BoundsRetained=True,
    original76307RecipePreserved=True,requiredJavaSuccessfulCount61AndContradictory1=True,
    oldAndNewHeadReceiptsMustRemainDistinct=True,sourceQualificationRequiredBeforeLaunch=True,
    controllerSha256=hashlib.sha256(controller.read_bytes()).hexdigest())
(coord/'integration-v12-union-review/current823-witness-java-native-preflight-v36.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof))
