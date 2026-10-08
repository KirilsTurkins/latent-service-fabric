from pathlib import Path
import hashlib
import json

coord=Path(__file__).resolve().parent
head='d6006fe34001b0129d9205d5e83398626920c24b'
prior_steps=json.loads((coord/'integration-v12-union-review/current-java-six-compiler-steps-v3.json').read_text())
steps=[[part.replace('six-compiler-v3','six-compiler-v4') for part in row] for row in prior_steps]
source=(coord/'integration-v12-current-java-six-compiler-controller-v3.py').read_text()
old='assert mode == "native" and steps == '+repr(prior_steps)
assert source.count(old)==1
source=source.replace(old,'assert mode == "native" and steps == '+repr(steps))
path=coord/'integration-v12-current-java-six-compiler-controller-v4.py'
path.write_text(source,encoding='utf8')
(coord/'integration-v12-union-review/current-java-six-compiler-steps-v4.json').write_text(json.dumps(steps,indent=2)+'\n')
report=dict(exactHead=head,previousFailedReceipt='integration-v12-current-java-six-compiler-v3/receipt.json',
    actualOriginalClocksReintroducedThroughMaintainedProducer=True,compilerVariantAssertionsUnchanged=True,
    noCompilerPinOrPermissionOrDeadlineChanges=True,originalOuterSeconds=1800,
    originalVariantSeconds=900,originalCommandSeconds=600,controllerSha256=hashlib.sha256(path.read_bytes()).hexdigest(),executed=False)
(coord/'integration-v12-union-review/current-java-clock-fixed-compiler-preparation-v4.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
