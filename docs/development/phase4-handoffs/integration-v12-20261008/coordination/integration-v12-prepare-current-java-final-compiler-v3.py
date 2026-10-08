from pathlib import Path
import hashlib
import json

coord=Path(__file__).resolve().parent
head='dca5d7737ef2ae37cd0c3a92c5c6c0ad40d897e9'
steps=json.loads((coord/'integration-v12-union-review/current-java-six-compiler-steps-v2.json').read_text())
steps=[[part.replace('six-compiler-v2','six-compiler-v3') for part in row] for row in steps]
source=(coord/'integration-v12-current-java-six-compiler-controller-v2.py').read_text()
old='assert mode == "native" and steps == '+repr(json.loads((coord/'integration-v12-union-review/current-java-six-compiler-steps-v2.json').read_text()))
assert source.count(old)==1
source=source.replace(old,'assert mode == "native" and steps == '+repr(steps))
path=coord/'integration-v12-current-java-six-compiler-controller-v3.py'
path.write_text(source,encoding='utf8')
(coord/'integration-v12-union-review/current-java-six-compiler-steps-v3.json').write_text(json.dumps(steps,indent=2)+'\n')
receipt=dict(exactHead=head,semanticJavaCreatorUnchangedFrom='291f6f13da92aa675b5caa955b26e2c27f395d05',
 sourceOnlyCaptureParent='2c441d83f2706c402c167bedfa2d4dfb042faca7',sourceOnlyCaptureNotCompile=True,
 controllerSha256=hashlib.sha256(path.read_bytes()).hexdigest(),sixActualComponentsRequired=True,
 originalOuterSeconds=1800,originalVariantSeconds=900,originalCommandSeconds=600,
 oldFailedCompilerAndNodeReceiptsPreserved=True,executed=False)
(coord/'integration-v12-union-review/current-java-final-compiler-preparation-v3.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt))
