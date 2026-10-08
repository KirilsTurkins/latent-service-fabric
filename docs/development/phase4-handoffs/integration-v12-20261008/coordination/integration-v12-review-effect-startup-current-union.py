from pathlib import Path
import hashlib
import json
import subprocess

root=Path(r'C:\Users\turkins\Desktop\lf-p4-current-java-bd4-union-v12')
coord=Path(__file__).resolve().parent/'integration-v12-union-review'
parents=['753d080680a9be155e7912cf9dde5d41cfc6e198','27d32ea9780784cab5cb1a14aee8b2fb4a46cb03']
base='291f6f13da92aa675b5caa955b26e2c27f395d05'
def show(rev,path):
    return subprocess.check_output(['git','-C',str(root),'show',f'{rev}:{path}'])
review=[]
for parent in parents:
    names=subprocess.check_output(['git','-C',str(root),'diff','--name-only',base,parent]).decode().splitlines()
    for name in names:
        if name=='tools/ci/suites.json':
            continue
        raw=show('',name); original=show(parent,name)
        assert raw==original,name
        review.append(dict(parent=parent,path=name,sha256=hashlib.sha256(raw).hexdigest(),byteExact=True))
actual=json.loads(show('','tools/ci/suites.json'))
rows={row['id']:row for row in actual['suites']}
for parent in parents:
    for old in json.loads(show(parent,'tools/ci/suites.json'))['suites']:
        row=rows[old['id']]
        assert row['minimumCases']>=old['minimumCases']
        for key in ('expectedCases','expectedIgnored','ignoredLeaves','prerequisites'):
            if key in old:
                assert set(old[key])<=set(row[key]),(old['id'],key)
        for key in old:
            if key not in {'minimumCases','expectedCases','expectedIgnored','ignoredLeaves','prerequisites'}:
                assert row[key]==old[key],(old['id'],key)
(coord/'current-effect-startup-semantic-union-review.json').write_text(json.dumps(dict(parents=parents,
    paths=review,allParentCasesFloorsIgnoresRetained=True,authorityAndLimitsChanged=False),indent=2)+'\n')
print(json.dumps({'reviewedSourcePaths':len(review),'suites':len(rows),'allParentsPreserved':True}))
