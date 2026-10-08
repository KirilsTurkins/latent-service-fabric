from pathlib import Path
import json

review=Path(__file__).resolve().parent/'integration-v12-union-review'
steps=json.loads((review/'current-c844-signing-native-steps-v10.json').read_text())
old=steps[1];assert old[-3:]==['--','-D','warnings']
steps[1]=old[:-4]
assert steps[1][-1]=='--offline'
(review/'current-c844-original-clippy-native-steps-v11.json').write_text(json.dumps(steps,indent=2)+'\n')
print(json.dumps({'originalSigningClippyMode':'ordinary','originalSelectedStrictFourPackagesRetained':True,
                  'extraFailedSigningOnlyStrictReceiptPreserved':True,'noProductOrRepositoryGateChanged':True,
                  'fullWorkspaceCiNotClaimed':True}))
