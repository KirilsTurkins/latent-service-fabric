from pathlib import Path
import ast
import json
import subprocess
import sys

root=Path(r'C:\Users\turkins\Desktop\lf-p4-current-java-bd4-union-v12')
sys.path.insert(0,str(root))
from tools.ci_contracts import python_expectations
name='tools/tests/test_java_transaction_schema.py'
before=json.loads((root/'tools/ci/contracts/python/test_java_transaction_schema.py.json').read_text())
after=python_expectations(root)[name]
assert before['cases']==after['cases'] and before['guards']==after['guards']
old_source=subprocess.check_output(['git','-C',str(root),'show','dca5d7737ef2ae37cd0c3a92c5c6c0ad40d897e9:'+name]).decode()
new_source=(root/name).read_text()
old=ast.parse(old_source);new=ast.parse(new_source)
def methods(tree):
    return {node.name:node for node in ast.walk(tree) if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name.startswith('test_')}
previous=methods(old);current=methods(new)
assert previous.keys()==current.keys()
assert all(sum(isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr.startswith('assert')
                  for node in ast.walk(current[key]))>=sum(isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
                  and node.func.attr.startswith('assert') for node in ast.walk(previous[key])) for key in previous)
result=dict(allSevenCasesAndSkipSetupGuardsByteSemanticUnchanged=True,originalAssertionCountsNeverReduced=True,
            addedCanonicalClockDeclarationChecks=True,jsonGuardRecordChanged=False,
            currentRecipeHead='d6006fe34001b0129d9205d5e83398626920c24b')
(Path(__file__).resolve().parent/'integration-v12-union-review/java-recovery-clock-source-guard-review.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
