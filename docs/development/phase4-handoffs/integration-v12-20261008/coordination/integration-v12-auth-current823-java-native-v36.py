from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import subprocess

coord=Path(__file__).resolve().parent
folder=coord/'integration-v12-current823-witness-java-native-v36'
raw=(folder/'receipt.json').read_bytes()
receipt=json.loads(raw)
assert hashlib.sha256(raw).hexdigest()=='1b1effa6049fafd17cf744d973634715ad4ab22bd6ffdd85ef58d54a2ede4fbd'
assert receipt['head']=='1417e360a96954ce8abcc845024e7b7ff0eccb99'
assert all(receipt[k] for k in ['passed','sourceClean','sourceHeadUnchanged','originalProcessReaped'])
assert len(receipt['steps'])==3 and all(r['exitCode']==0 for r in receipt['steps'])
for row in receipt['steps']:
    data=(folder/row['log']).read_bytes()
    assert hashlib.sha256(data).hexdigest()==row['sha256'] and len(data)==row['bytes']
log=(folder/'step-3.log').read_text()
for required in ['shared profile vectors: 78','shared profile lifetime/recovery: passed',
 'Java shared protobuf cases: 61; contradictory oneof rejected: 1',
 'Java transport: twelve bounded TCP/protocol suites passed',
 '"release": 25, "classMajor": 69, "preview": false, "classes": 1471','BUILD SUCCESSFUL']:
    assert required in log
host=(folder/'step-2.log').read_text()
assert 'Ran 25 tests' in host and 'OK' in host
path=coord/'integration-v12-union-review/pr823-current-witness-body-v35.md'
body=path.read_text()
old='Current Java Gradle540, new fixture execution in all languages, signed public guest/provider/restore/browser workflows and full current CI remain pending; this PR does not establish complete ticket acceptance.'
new='Exact current Java25 validation passes the original Gradle540 clean check:78 semantic fixtures/lifetime,61 successful protobuf roundtrips plus the original contradictory refusal, twelve bounded TCP/protocol suites,1471 non-preview classes and25 host/toolchain tests. Other language execution for the added fixture, signed public guest/provider/restore/browser workflows and full current CI remain pending; this PR does not establish complete ticket acceptance.'
assert body.count(old)==1
body=body.replace(old,new)
updated=coord/'integration-v12-union-review/pr823-current-witness-java-qualified-body-v36.md'
updated.write_text(body,encoding='utf8',newline='\n')
env=dict(os.environ,GODEBUG='http2client=0')
live=json.loads(subprocess.check_output(['gh','pr','view','823','--repo','KirilsTurkins/latent-service-fabric','--json','headRefOid,state'],env=env))
assert live==dict(headRefOid=receipt['head'],state='OPEN')
subprocess.run(['gh','pr','edit','823','--repo','KirilsTurkins/latent-service-fabric','--body-file',str(updated)],env=env,check=True)
proof=dict(at=datetime.now(timezone.utc).isoformat(),head=receipt['head'],receiptSha256=hashlib.sha256(raw).hexdigest(),
    allThreeLogsAuthenticated=True,originalProcessReaped=True,actualHostToolTests25=True,
    actualJavaSharedSemantic78=True,actualJavaSuccessfulProtobuf61=True,originalContradictory1=True,
    actualBoundedTcpProtocolSuites12=True,actualJava25NonPreviewClasses1471=True,
    completeCI=False,signedNodeQualification=False)
(coord/'integration-v12-union-review/current823-witness-java-qualified-proof-v36.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof))
