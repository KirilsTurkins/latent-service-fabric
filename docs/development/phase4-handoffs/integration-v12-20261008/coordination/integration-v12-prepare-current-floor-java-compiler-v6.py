from pathlib import Path
import hashlib
import json

coord=Path(__file__).resolve().parent
head='44754a7b9de0b41c456bcbbf31797b0cd47b0814'
prior=json.loads((coord/'integration-v12-union-review/current-java-six-compiler-steps-v5.json').read_text())
steps=[[part.replace('six-compiler-v5','six-compiler-v6') for part in row] for row in prior]
source=(coord/'integration-v12-current-java-six-compiler-controller-v5.py').read_text()
old='assert mode == "native" and steps == '+repr(prior);assert source.count(old)==1
source=source.replace(old,'assert mode == "native" and steps == '+repr(steps))
path=coord/'integration-v12-current-java-six-compiler-controller-v6.py'
path.write_text(source,encoding='utf8')
(coord/'integration-v12-union-review/current-java-six-compiler-steps-v6.json').write_text(json.dumps(steps,indent=2)+'\n')
report=dict(exactHead=head,currentDevelopment='9f7aab58400d446f451964dc492b34dc46d09f14',
 restoredHistoricalAotMinimum=1,clockWorldActualMaintainedProducer=True,oldFailedCompilerReportsPreserved=True,
 originalOuterSeconds=1800,originalVariantSeconds=900,originalCommandSeconds=600,
 controllerSha256=hashlib.sha256(path.read_bytes()).hexdigest(),executed=False)
(coord/'integration-v12-union-review/current-floor-java-compiler-preparation-v6.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
