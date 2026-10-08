from pathlib import Path
import hashlib
import json

coord=Path(__file__).resolve().parent;head='0a0dc2818946111c8657e6b681ecef1f9f3fafab'
prior=json.loads((coord/'integration-v12-union-review/current-java-six-compiler-steps-v6.json').read_text())
steps=[[part.replace('six-compiler-v6','six-compiler-v7') for part in row] for row in prior]
source=(coord/'integration-v12-current-java-six-compiler-controller-v6.py').read_text()
old='assert mode == "native" and steps == '+repr(prior);assert source.count(old)==1
source=source.replace(old,'assert mode == "native" and steps == '+repr(steps))
path=coord/'integration-v12-current-java-six-compiler-controller-v7.py';path.write_text(source,encoding='utf8')
(coord/'integration-v12-union-review/current-java-six-compiler-steps-v7.json').write_text(json.dumps(steps,indent=2)+'\n')
report=dict(exactHead=head,currentDevelopment='c84473ec9868fc496486f864afe52f1b7105329f',
 actualCurrentSource374OneOriginalSkipPassed=True,actualCurrentSigning58AndRuntimeOriginalGatesPassed=True,
 clockWorldRestoredByMaintainedRuntimeWit=True,preservedHistoricalAotMinimum=1,
 originalOuterSeconds=1800,originalVariantSeconds=900,originalCommandSeconds=600,
 oldFailedCompilerReceiptsPreserved=True,controllerSha256=hashlib.sha256(path.read_bytes()).hexdigest(),executed=False)
(coord/'integration-v12-union-review/current-c844-java-compiler-preparation-v7.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
