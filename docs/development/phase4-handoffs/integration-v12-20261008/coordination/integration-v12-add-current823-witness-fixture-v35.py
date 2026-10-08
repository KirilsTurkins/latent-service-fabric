from pathlib import Path
import hashlib
import json
import subprocess

root=Path(r'C:\Users\turkins\Desktop\lf-p4-pr823-witness-vector-v35')
parent='76307dbbe24b51fb8b1316c4fbf7047914759a51'
donor='1b7a8073f9ec7b354a4dd00a365deb1c4094e3aa'
def read(head,path):
    return subprocess.check_output(['git','show',head+':'+path],cwd=root)
path='sdk/profile/fixtures.json'
before=read(parent,path)
value=json.loads(before)
donor_value=json.loads(read(donor,path))
addition=next(r for r in donor_value['cases'] if r['name']=='activation-tree-original-captured-intent-witness')
assert len(value['cases'])==77 and all(r['name']!=addition['name'] for r in value['cases'])
value['cases'].append(addition)
original_text=before.decode().replace('\r\n','\n')
marker='\n  ]\n}'
assert original_text.count(marker)==1
addition_text='\n'.join('    '+line for line in json.dumps(addition,indent=2).splitlines())
after=original_text.replace(marker,',\n'+addition_text+marker)
assert json.loads(after)==value
(root/path).write_text(after,encoding='utf8',newline='\n')
assert json.loads((root/path).read_bytes())['cases'][:-1]==json.loads(before)['cases']
counts=[('sdk/profile/test_profile.py','validate(), (77, 16)','validate(), (78, 16)'),
    ('sdk/java-client/src/transportTest/java/dev/latent/sdk/transport/FixtureCodecTest.java','count != 60','count != 61'),
    ('sdk/dotnet/Latent.Sdk.Transport.Tests/Vectors.cs','count == 61','count == 62')]
for path,old,new in counts:
    text=read(parent,path).decode()
    assert text.count(old)==1
    (root/path).write_text(text.replace(old,new),encoding='utf8',newline='\n')
result=dict(parent=parent,donor=donor,existing77CasesSemanticallyUnchanged=True,
    addedName=addition['name'],additionSha256=hashlib.sha256(json.dumps(addition,sort_keys=True).encode()).hexdigest(),
    allCountsOnlyIncreaseByOne=True, generatedFacadeAndVectorCheckPending=True,
    actualNativeExecuted=False)
out=Path(__file__).resolve().parent/'integration-v12-union-review/current823-witness-addition-preflight-v35.json'
out.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
