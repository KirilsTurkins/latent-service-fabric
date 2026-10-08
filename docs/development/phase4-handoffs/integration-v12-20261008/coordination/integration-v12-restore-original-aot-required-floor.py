from pathlib import Path
import json
import sys

root=Path(sys.argv[1]);path=root/'tools/ci/suites.json'
value=json.loads(path.read_text())
row=next(row for row in value['suites'] if row['id']=='latent-wasmtime.test.aot-sandbox')
assert row['minimumCases']==0
row['minimumCases']=1
path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf8',newline='\n')
print(json.dumps({'restoredHistoricalRequiredMinimum':1,'old':0,'caseNamesIgnoresAndEveryOtherControlChanged':False}))
