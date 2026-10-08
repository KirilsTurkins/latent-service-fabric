from pathlib import Path
import hashlib
import json
import subprocess

root=Path(r'C:\Users\turkins\Desktop\lf-p4-current-public-effect-union-v12')
coord=Path(__file__).resolve().parent/'integration-v12-union-review'
parents=['291f6f13da92aa675b5caa955b26e2c27f395d05','24df5ebc0bfaa74626a2f5f44488caab73c66365']
def show(rev,path):
    return subprocess.check_output(['git','-C',str(root),'show',f'{rev}:{path}'])
name='tools/ci/suites.json'
actual=show('',name)
value=json.loads(actual)
print(json.dumps({'suiteRootKeys':list(value),'suiteKeys':list(value['suites'][0])}))
rows={row['id']:row for row in value['suites']}
reviews=[]
for parent in parents:
    original=json.loads(show(parent,name))
    for prior in original['suites']:
        current=rows[prior['id']]
        assert current['minimumCases']>=prior['minimumCases'],prior['id']
        for key in ('expectedCases','expectedIgnored','ignoredLeaves','prerequisites'):
            if key in prior:
                assert set(prior[key])<=set(current[key]),(prior['id'],key)
        for key in prior:
            if key not in {'minimumCases','expectedCases','expectedIgnored','ignoredLeaves','prerequisites'}:
                assert current[key]==prior[key],(prior['id'],key)
    reviews.append(dict(parent=parent,suiteCount=len(original['suites']),allCaseNamesIgnoresFloorsRetained=True))
names=subprocess.check_output(['git','-C',str(root),'diff','--cached','--name-only']).decode().splitlines()
files=[]
for path in names:
    if path==name:
        continue
    current=show('',path)
    donor=show(parents[1],path)
    assert current==donor,path
    files.append(dict(path=path,sha256=hashlib.sha256(current).hexdigest(),byteExactDonor=True))
(coord/'public-effect-current-parent-semantic-review.json').write_text(json.dumps(dict(
    parents=parents,suitePreservation=reviews,sourceFiles=files,newCaseCount=2,
    allCurrentSignerAndRpcSourceUnchanged=True),indent=2)+'\n')
print(json.dumps({'sourceFiles':len(files),'suites':len(rows),'reviewed':True}))
