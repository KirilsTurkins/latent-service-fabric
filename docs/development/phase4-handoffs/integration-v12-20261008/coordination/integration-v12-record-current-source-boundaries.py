from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json

coord=Path(__file__).resolve().parent
paths={
 'httpFinalSource':coord/'integration-v12-http-current-java-output-source-v3/receipt.json',
 'effectParentSource':coord/'integration-v12-current-public-effect-union-source-v1/receipt.json',
 'actualStartupWrapperSource':coord/'integration-v12-actual-startup-wrapper-source-v1/receipt.json',
 'configuredDiagnostic':coord/'integration-v12-configured-startup-diagnosis-execution-v4/receipt.json',
}
proofs={}
for name,path in paths.items():
    raw=path.read_bytes(); data=json.loads(raw)
    assert data['passed'] and data['sourceClean'] and data['sourceHeadUnchanged'] and data['originalProcessReaped']
    proofs[name]=dict(head=data['head'],receipt=str(path),sha256=hashlib.sha256(raw).hexdigest(),
                     passed=True,sourceClean=True,allProcessesReaped=True)
value=dict(at=datetime.now(timezone.utc).isoformat(),proofs=proofs,
 current823='291f6f13da92aa675b5caa955b26e2c27f395d05',
 current828='ed2254f1c7300ec11cbf827c4e1ed9fe364e8776',
 nextHttp='6f0a8e82299aa0a1224dee293aaa8a4db7f3a7d9',nextEffect='dc1114cc9f3531361a7776d15367b4daf786a9f7',
 nextStartup='2c441d83f2706c402c167bedfa2d4dfb042faca7',
 nativePending=['nextHttp','nextEffect','nextStartup'],
 actualOriginalJavaCampaign=dict(head='291f6f13da92aa675b5caa955b26e2c27f395d05',signedPublications=5,
   nativeHostInspectionPassed=True,secondStartupFailed=True,guestInvocations=0,oldFailurePreserved=True),
 laterDiagnosticQualifiesOriginalFailure=False,localFullCiPassed=False,newIssueClosures=[],
 noOwnedPrMergedWorktreeDeletionEligible=True)
(coord/'integration-v12-union-review/current-source-native-delivery-boundaries-v4.json').write_text(json.dumps(value,indent=2)+'\n')
print(json.dumps({'recordedProofs':len(proofs),'nativePending':3,'newIssueClosures':0}))
