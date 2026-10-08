from pathlib import Path
import hashlib
import json

coord=Path(__file__).resolve().parent
source=(coord/'integration-v12-current-java-capture-stage-v3.py').read_text()
source=source.replace('six-compiler-v3','six-compiler-v4').replace('six-captures-v3','six-captures-v4')
source=source.replace('capture-manifest-v3','capture-manifest-v4').replace('six-selected-v3','six-selected-v4')
source=source.replace('dca5d7737ef2ae37cd0c3a92c5c6c0ad40d897e9','d6006fe34001b0129d9205d5e83398626920c24b')
path=coord/'integration-v12-current-java-capture-stage-v4.py'
path.write_text(source,encoding='utf8')
print(json.dumps({'exactActualCompilerHead':'d6006fe34001b0129d9205d5e83398626920c24b',
                  'stageSha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                  'oldFailedCapturesReusedOrRetagged':False,'executionRequiresAllSixCompilerPass':True}))
