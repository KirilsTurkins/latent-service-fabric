from pathlib import Path
import hashlib
import json

coord=Path(__file__).resolve().parent
head='511d5687f360258d05469cd2593de4d6f2556cf1'
prior=json.loads((coord/'integration-v12-union-review/current-java-six-compiler-steps-v4.json').read_text())
steps=[[part.replace('six-compiler-v4','six-compiler-v5') for part in row] for row in prior]
source=(coord/'integration-v12-current-java-six-compiler-controller-v4.py').read_text()
old='assert mode == "native" and steps == '+repr(prior)
assert source.count(old)==1
source=source.replace(old,'assert mode == "native" and steps == '+repr(steps))
path=coord/'integration-v12-current-java-six-compiler-controller-v5.py'
path.write_text(source,encoding='utf8')
(coord/'integration-v12-union-review/current-java-six-compiler-steps-v5.json').write_text(json.dumps(steps,indent=2)+'\n')
value=dict(exactHead=head,currentDevelopment='9f7aab58400d446f451964dc492b34dc46d09f14',
    actualClocksRestoredByMaintainedRuntimeWit=True,oldFailedCompilerReceiptPreserved='integration-v12-current-java-six-compiler-v3/receipt.json',
    originalOuterSeconds=1800,originalVariantSeconds=900,originalCommandSeconds=600,
    controllerSha256=hashlib.sha256(path.read_bytes()).hexdigest(),executed=False)
(coord/'integration-v12-union-review/current9f-java-compiler-preparation-v5.json').write_text(json.dumps(value,indent=2)+'\n')
print(json.dumps(value))
