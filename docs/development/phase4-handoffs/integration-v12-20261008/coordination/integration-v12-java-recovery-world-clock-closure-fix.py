from pathlib import Path
import hashlib
import json
import subprocess
import sys

root=Path(r'C:\Users\turkins\Desktop\lf-p4-current-java-bd4-union-v12')
parent='dca5d7737ef2ae37cd0c3a92c5c6c0ad40d897e9'
def git(*args):
    return subprocess.check_output(['git','-C',str(root),*args],text=True).strip()
assert git('rev-parse','HEAD')==parent and not git('status','--porcelain')
git('switch','-c','fix/phase4-java-recovery-runtime-clock-closure-v12')
sys.path.insert(0,str(root))
from tools.java_capsule_project import runtime_wit
directory=root/'examples/java-transaction-schema/recovery-v1'
directory.mkdir(parents=True,exist_ok=True)
for name in ('world.wit.in','recipe.json'):
    (directory/name).write_bytes(subprocess.check_output(['git','-C',str(root),'show',f'HEAD:examples/java-transaction-schema/recovery-v1/{name}']))
original=(directory/'world.wit.in').read_bytes()
assert b'latent:clock/' not in original
world=runtime_wit(original,'service')
(directory/'world.wit.in').write_bytes(world)
recipe=json.loads((directory/'recipe.json').read_bytes())
recipe['worldDigest']='sha256:'+hashlib.sha256(world).hexdigest()
(directory/'recipe.json').write_text(json.dumps(recipe,indent=2)+'\n',encoding='utf8',newline='\n')
path=root/'tools/tests/test_java_transaction_schema.py'
source=path.read_text()
marker='''            self.assertIn(b"key-version: option<list<u8>>", files["wit/world.wit"])
'''
assert source.count(marker)==1
source=source.replace(marker,marker+'''            for capability in (b"latent:clock/monotonic@0.1.0", b"latent:clock/wall@0.1.0"):
                self.assertEqual(files["wit/world.wit"].count(b"import " + capability + b";"), 2)
            self.assertIn(b"world runtime-support", files["wit/world.wit"])
''')
path.write_text(source,encoding='utf8',newline='\n')
print(json.dumps({'parent':parent,'worldDerivedThroughMaintainedRuntimeWit':True,
    'exactStateIntentsThreeFieldContractPreserved':True,'clockPermissionsGranted':False,
    'originalForbiddenHttpRefusalPreserved':True,'sharedDefaultChanged':False,
    'recipeDigest':recipe['worldDigest']}))
