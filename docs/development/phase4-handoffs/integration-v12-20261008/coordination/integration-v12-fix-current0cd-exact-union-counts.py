from pathlib import Path
import json
import subprocess
import sys

root=Path(sys.argv[1])
path=root/'tools/ci/suites.json'
value=json.loads(path.read_text())
changes=[]
for row in value['suites']:
    if row['mode']!='libtest':continue
    cases=row['expectedCases'];assert len(cases)==len(set(cases))
    if row['minimumCases']!=len(cases):
        assert len(cases)>=row['minimumCases'],row['id']
        changes.append(dict(id=row['id'],old=row['minimumCases'],new=len(cases)))
        row['minimumCases']=len(cases)
path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf8',newline='\n')
print(json.dumps({'actualUnionCountFloorsIncreased':changes,'casesRemoved':False}))
