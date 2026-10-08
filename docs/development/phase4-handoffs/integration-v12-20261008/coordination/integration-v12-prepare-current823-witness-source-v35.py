from pathlib import Path
import hashlib
import json

coord=Path(__file__).resolve().parent
prior=json.loads((coord/'integration-v12-current823-java-bridge-source-v21/invocation.json').read_bytes())
steps=prior['steps']
assert len(steps)==7
steps[3][-1]='target/ci/observed-current823-witness-v35-linux.json'
# Add meaningful existing profile scenarios after all original modules. Use the
# existing process-local pinned formatter needed by its deterministic generator.
prefix="import os; from pathlib import Path; fmt=Path('/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data/jobs/root-private-go127-formatter-20261007-v1/go/bin'); env=dict(os.environ,PATH=str(fmt)+os.pathsep+os.environ['PATH']); "
steps[6][-1]+='; '+prefix+"subprocess.run(['python3','-X','utf8','-B','-m','unittest','discover','-s','sdk/profile','-p','test_profile.py'],env=env,check=True)"
out=coord/'integration-v12-current823-witness-source-steps-v35.json'
out.write_text(json.dumps(steps,indent=2)+'\n')
proof=dict(head='1417e360a96954ce8abcc845024e7b7ff0eccb99',allOriginalSevenStepsRetained=True,
    actual12ProfileCasesAddedToLastGeneratorStep=True, sourceControllerAwaitingExplicitReleasedReceipt=True,
    sourceStepsSha256=hashlib.sha256(out.read_bytes()).hexdigest(), actualSourceLaunched=False)
(coord/'integration-v12-union-review/current823-witness-source-steps-preflight-v35.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof))
