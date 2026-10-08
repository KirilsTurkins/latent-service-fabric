from pathlib import Path
import hashlib
import json
import sys

coord=Path(__file__).resolve().parent;pr=int(sys.argv[1]);assert pr==823
head='0a0dc2818946111c8657e6b681ecef1f9f3fafab'
parent=coord/'integration-v12-current823-developmentc844-native-v10'
ordinary=coord/'integration-v12-current823-developmentc844-original-signing-clippy-v11'
raw=(parent/'receipt.json').read_bytes();first=json.loads(raw)
additional=(ordinary/'receipt.json').read_bytes();second=json.loads(additional)
for receipt in (first,second):
    assert receipt['head']==head and receipt['sourceClean'] and receipt['sourceHeadUnchanged'] and receipt['originalProcessReaped']
assert len(first['steps'])==4 and len(second['steps'])==1
assert all(first['steps'][index]['exitCode']==0 for index in (0,2,3))
assert first['steps'][1]['exitCode']==101 and not first['passed']
assert second['passed'] and second['steps'][0]['exitCode']==0
records=[]
for index in (0,2,3):
    step=first['steps'][index];data=(parent/step['log']).read_bytes()
    assert hashlib.sha256(data).hexdigest()==step['sha256']
    records.append(dict(job=parent.name,step=index+1,argv=step['argv'],sha256=step['sha256'],passed=True))
step=second['steps'][0];data=(ordinary/step['log']).read_bytes();assert hashlib.sha256(data).hexdigest()==step['sha256']
records.append(dict(job=ordinary.name,step=1,argv=step['argv'],sha256=step['sha256'],passed=True))
result=dict(head=head,requiredScopedNativeGatesPassed=True,actualSourceCleanAllProcessesReaped=True,
    originalRawDiagnosticReceiptSha256=hashlib.sha256(raw).hexdigest(),originalRawDiagnosticPassed=False,
    ordinaryClippyReceiptSha256=hashlib.sha256(additional).hexdigest(),qualifyingActualSteps=records,
    extraSigningOnlyStrictGatePassed=False,extraSigningOnlyStrictBaselineDiagnosticsPreserved=True,
    fullWorkspaceCiPassed=False)
(coord/'integration-v12-union-review/pr823-c844-original-native-qualified-proof-v11.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
