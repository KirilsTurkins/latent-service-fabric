from pathlib import Path
import json

coord=Path(__file__).resolve().parent
review=coord/'integration-v12-union-review'
steps=json.loads((coord/'integration-v12-http-current-java-final-source-v2/invocation.json').read_text())['steps']
(review/'http-current-java-output-source-steps-v3.json').write_text(json.dumps(steps,indent=2)+'\n')
native=[
 ['cargo','+1.97.1','test','-p','latentd','--lib','standalone::startup_observation::tests::',
  '--all-features','--locked','--offline','--','--test-threads=1'],
 ['cargo','+1.97.1','clippy','-p','latentd','--all-targets','--all-features',
  '--locked','--offline','--no-deps','--','-D','warnings'],
 ['cargo','+1.97.1','build','-p','latentd','--bin','latentd',
  '--all-features','--locked','--offline']]
(review/'actual-startup-wrapper-native-steps-v1.json').write_text(json.dumps(native,indent=2)+'\n')
print(json.dumps({'httpSourceSteps':len(steps),'startupNativeSteps':len(native)}))
