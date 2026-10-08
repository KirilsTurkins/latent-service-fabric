from pathlib import Path
import hashlib
import json
import subprocess

root=Path(r'C:\Users\turkins\Desktop\lf-p4-current-java-bd4-union-v12')
coord=Path(__file__).resolve().parent
producer=coord/'portable-v2-dotnet-lock-native-reproduction-20261008-v262'
parent='0a783d97762f763ca6ab237d4bb36eb306bbddec'
def git(*args):return subprocess.check_output(['git','-C',str(root),*args],text=True).strip()
assert git('rev-parse','HEAD')==parent and not git('status','--porcelain')
receipt=json.loads((producer/'receipt.json').read_bytes());custody=json.loads((producer/'host-custody.json').read_bytes())
assert receipt['reproductionsIdentical'] and receipt['generatedSources']==10 and receipt['protocVersion']=='libprotoc 29.0'
assert receipt['toolHashes']=={'protoc':'42e0917ffb9f1bd467dd0153886e76335c0ea5d2cffe10269bb189dc3daa5330',
 'grpc_csharp_plugin':'986ed8d83e5abf359a2710ea445049dfc451716ff3eadaaf9c6c795518663643'}
assert receipt['changedInputs']==['latent/control/v1/node.proto'] and receipt['changedOutputs']==['latent/control/v1/Node.cs']
assert len(receipt['commands'])==12 and all(row['returncode']==0 for row in receipt['commands'])
checked=[]
for row in custody['capturedSources']:
    if row['path']=='sdk/dotnet/protobuf.lock.json':continue
    actual=subprocess.check_output(['git','-C',str(root),'show',parent+':'+row['path']]).replace(b'\r\n',b'\n')
    assert len(actual)==row['bytes'] and hashlib.sha256(actual).hexdigest()==row['sha256'],row['path']
    checked.append(row['path'])
assert len(checked)==7
old=json.loads(subprocess.check_output(['git','-C',str(root),'show',parent+':sdk/dotnet/protobuf.lock.json']))
new_raw=(producer/'protobuf.lock.json').read_bytes();new=json.loads(new_raw)
assert hashlib.sha256(new_raw).hexdigest()==receipt['newLockSha256']
for key in old:
    if key not in ('inputs','outputs'):assert old[key]==new[key],key
assert old['inputs'].keys()==new['inputs'].keys() and old['outputs'].keys()==new['outputs'].keys()
for name in new['inputs']:
    actual=subprocess.check_output(['git','-C',str(root),'show',parent+':api/proto/'+name]).replace(b'\r\n',b'\n')
    assert hashlib.sha256(actual).hexdigest()==new['inputs'][name]
assert [name for name in old['inputs'] if old['inputs'][name]!=new['inputs'][name]]==['latent/control/v1/node.proto']
assert [name for name in old['outputs'] if old['outputs'][name]!=new['outputs'][name]]==['latent/control/v1/Node.cs']
git('switch','-c','fix/phase4-current823-actual-dotnet-lock-v12')
path=root/'sdk/dotnet/protobuf.lock.json';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(new_raw)
record=dict(parent=parent,actualProducerHead=receipt['sourceHead'],allSixProtoInputsAndExactProjectOptionsByteIdentical=True,
 actualPinnedLinuxGrpcToolsReproducedTwice=True,actualToolHashes=receipt['toolHashes'],newLockSha256=receipt['newLockSha256'],
 changedInputs=receipt['changedInputs'],changedOutputs=receipt['changedOutputs'],producerReceiptsUnmodified=True,
 msbuildAndFullSdkQualificationClaimed=False)
(coord/'integration-v12-union-review/pr823-actual-dotnet-lock-adoption-review.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record))
