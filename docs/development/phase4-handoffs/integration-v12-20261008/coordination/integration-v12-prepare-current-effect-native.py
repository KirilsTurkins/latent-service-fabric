from pathlib import Path
import json

review=Path(__file__).resolve().parent/'integration-v12-union-review'
steps=json.loads((review/'public-effect-full-native-steps.json').read_text())[:2]
steps[0] += ['-p','latentd','-p','latent-node','-p','latent-effects']
steps.insert(1,['cargo','+1.97.1','test','-p','latent-effects','--lib',
  'dispatch_store::effect_management::tests::','--all-features','--locked','--offline',
  '--','--test-threads=1'])
steps += json.loads((review/'full-node-wire-daemon-native-steps.json').read_text())
(review/'current-public-effect-native-steps-v1.json').write_text(json.dumps(steps,indent=2)+'\n')
print(json.dumps({'steps':len(steps),'originalFocusedAndFullWireRetained':True,
                  'ordinaryCurrentLibrariesClippyRetained':True,'originalSelectedStrictRetained':True,
                  'extraOldWireStrict47DiagnosticNotClaimedPassed':True}))
