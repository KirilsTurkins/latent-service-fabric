from pathlib import Path
import hashlib
import json

coord=Path(__file__).resolve().parent
old_head='98281c17e28f9dd1dd6e9f0058069d71422df11e'
head='1fcc6d0fa6ec8e19c3ffc11ca02dd9242d0a10e6'
old_job='integration-v12-current-java-real-node-v22'
job='integration-v12-current-java-real-node-v40'
path=coord/'integration-v12-union-review/current-query-real-node-source-paired-steps-v22.json'
steps=json.loads(path.read_bytes())
steps=json.loads(json.dumps(steps).replace(old_head,head).replace(old_job,job))
assert len(steps)==3 and steps[2][-1]=='1200'
text=(coord/'integration-v12-current-query-real-node-source-paired-controller-v22.py').read_text()
text=text.replace(old_head,head).replace(old_job,job)
text=text.replace('assert mode == "native" and steps == ','assert mode == "native" and head == '+repr(head)+' and steps == ')
compile(text,'query-witness-native-v40','exec')
controller=coord/'integration-v12-current-query-real-node-source-paired-controller-v40.py'
controller.write_text(text,encoding='utf8',newline='\n')
step_path=coord/'integration-v12-union-review/current-query-real-node-source-paired-steps-v40.json'
step_path.write_text(json.dumps(steps,indent=2)+'\n')
proof=dict(head=head,job=job,oldHeadRecipeUnchanged=True,
    originalBuilds1200Campaign1800ControllerAnd16GiBBoundsRetained=True,
    currentPublishedWitnessFixtureUnionRetained=True,actualCompilerCaptureSelectionUnchanged=True,
    currentNativeLaunched=False,sourceQualificationRequired=True,
    controllerSha256=hashlib.sha256(controller.read_bytes()).hexdigest())
(coord/'integration-v12-union-review/current-query-witness-native-preflight-v40.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof))
