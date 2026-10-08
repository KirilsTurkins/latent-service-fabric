from pathlib import Path
import copy
import hashlib
import json
import subprocess
import sys

root=Path(sys.argv[1]) if len(sys.argv)>1 else Path(r'C:\Users\turkins\Desktop\lf-p4-current-java-bd4-union-v12')
label=sys.argv[2] if len(sys.argv)>2 else 'current0cd-suite-custody'
assert label.isascii() and all(c.isalnum() or c=='-' for c in label)
coord=Path(__file__).resolve().parent/'integration-v12-union-review'/label
coord.mkdir(exist_ok=True)
name='tools/ci/suites.json'
raw={stage:subprocess.check_output(['git','-C',str(root),'show',f':{stage}:{name}']) for stage in (1,2,3)}
for stage,value in raw.items():(coord/f'stage-{stage}.json').write_bytes(value)
data={stage:json.loads(value) for stage,value in raw.items()}
result=copy.deepcopy(data[2]);maps={stage:{row['id']:row for row in value['suites']} for stage,value in data.items()}
rows={row['id']:row for row in result['suites']}
for identity,other in maps[3].items():
    if identity not in rows:
        rows[identity]=copy.deepcopy(other)
        result['suites'].append(rows[identity])
        additions.append(dict(suite=identity,field='suite',added='entire new current-main target'))
additions=[]
for identity,other in maps[3].items():
    current=rows[identity];base=maps[1].get(identity)
    for key in set(current)|set(other):
        if current.get(key)==other.get(key):continue
        if key in ('expectedCases','expectedIgnored','ignoredLeaves','prerequisites'):
            before=list(current.get(key,[]));current[key]=sorted(set(current.get(key,[]))|set(other.get(key,[])))
            additions.append(dict(suite=identity,field=key,added=sorted(set(current[key])-set(before))))
        elif key=='minimumCases':
            current[key]=max(current[key],other[key],len(current['expectedCases']))
        elif base and current.get(key)==base.get(key):
            current[key]=copy.deepcopy(other[key])
        elif not base or other.get(key)!=base.get(key):
            raise AssertionError((identity,key,'requires semantic review'))
for key in set(data[2])|set(data[3]):
    if key=='suites' or data[2].get(key)==data[3].get(key):continue
    old=data[1].get(key);ours=data[2].get(key);theirs=data[3].get(key)
    if ours==old:result[key]=copy.deepcopy(theirs)
    elif theirs==old:pass
    else:raise AssertionError((key,'requires semantic review'))
for identity,current in rows.items():
    if current['mode']=='libtest':
        expected=len(current['expectedCases'])
        assert expected>=maps[2].get(identity,{}).get('minimumCases',0)
        assert expected>=maps[3].get(identity,{}).get('minimumCases',0)
        current['minimumCases']=expected
for parent in (2,3):
    for identity,prior in maps[parent].items():
        current=rows[identity]
        assert current['minimumCases']>=prior['minimumCases']
        for key in ('expectedCases','expectedIgnored','ignoredLeaves','prerequisites'):
            assert set(prior.get(key,[]))<=set(current.get(key,[])),(identity,key)
        for key in prior:
            if key not in {'minimumCases','expectedCases','expectedIgnored','ignoredLeaves','prerequisites'}:
                assert current[key]==prior[key],(identity,key)
output=(json.dumps(result,indent=2)+'\n').encode()
(root/name).write_bytes(output)
report=dict(rawStageSha256={str(k):hashlib.sha256(v).hexdigest() for k,v in raw.items()},
    additions=additions,resultSha256=hashlib.sha256(output).hexdigest(),
    bothParentCasesIgnoresFloorsAndAllSemanticControlsPreserved=True,noCasesOrGatesDropped=True)
(coord/'review.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
