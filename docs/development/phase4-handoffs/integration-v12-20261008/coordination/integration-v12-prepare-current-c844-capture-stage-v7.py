from pathlib import Path
import hashlib
import json

coord=Path(__file__).resolve().parent
source=(coord/'integration-v12-current-java-capture-stage-v3.py').read_text()
source=source.replace('six-compiler-v3','six-compiler-v7').replace('six-captures-v3','six-captures-v7')
source=source.replace('capture-manifest-v3','capture-manifest-v7').replace('six-selected-v3','six-selected-v7')
source=source.replace('dca5d7737ef2ae37cd0c3a92c5c6c0ad40d897e9','0a0dc2818946111c8657e6b681ecef1f9f3fafab')
path=coord/'integration-v12-current-java-capture-stage-v7.py';path.write_text(source,encoding='utf8')
print(json.dumps({'exactCompilerHead':'0a0dc2818946111c8657e6b681ecef1f9f3fafab',
 'allSixActualPassReceiptRequired':True,'oldMaterialsRelabeled':False,'copyDerivedCompilerCaches':False,
 'stageSha256':hashlib.sha256(path.read_bytes()).hexdigest()}))
