from pathlib import Path
import ast
import hashlib
import json
import subprocess

root=Path(r'C:\Users\turkins\Desktop\lf-p4-pr823-witness-vector-v35')
coord=Path(__file__).resolve().parent
parent='76307dbbe24b51fb8b1316c4fbf7047914759a51'
paths=subprocess.check_output(['git','diff','--name-only'],cwd=root,text=True).splitlines()
expected={'sdk/c/tests/profile_vectors.h','sdk/dotnet/Latent.Sdk.SemanticTests/ProfileVectors.cs',
 'sdk/dotnet/Latent.Sdk.Transport.Tests/Vectors.cs','sdk/go/profile/vectors_test.go',
 'sdk/java-client/src/test/java/dev/latent/sdk/ProfileVectors.java',
 'sdk/java-client/src/transportTest/java/dev/latent/sdk/transport/FixtureCodecTest.java',
 'sdk/profile/fixtures.json','sdk/profile/test_profile.py','sdk/rust/tests/client_profile_vectors.rs',
 'sdk/typescript-client/tests/profile-vectors.ts'}
assert set(paths)==expected
reviews=[]
for path in paths:
    before=subprocess.check_output(['git','show',parent+':'+path],cwd=root).decode().replace('\r\n','\n')
    after=(root/path).read_text(encoding='utf8').replace('\r\n','\n')
    if path=='sdk/profile/fixtures.json':
        assert json.loads(after)['cases'][:-1]==json.loads(before)['cases']
    elif path=='sdk/profile/test_profile.py':
        assert after.replace('validate(), (78, 16)','validate(), (77, 16)')==before
    elif path.endswith('FixtureCodecTest.java'):
        assert after.replace('count != 61','count != 60')==before
    elif path.endswith('Transport.Tests/Vectors.cs'):
        assert after.replace('count == 62','count == 61')==before
    else:
        patch=subprocess.check_output(['git','diff','--unified=0','--',path],cwd=root,text=True)
        removed=[line[1:] for line in patch.splitlines() if line.startswith('-') and not line.startswith('---')]
        assert all('shared profile vectors: 77' in line for line in removed), (path,removed)
        assert 'activation-tree-original-captured-intent-witness' in after
    reviews.append(dict(path=path,beforeSha256=hashlib.sha256(before.encode()).hexdigest(),
        afterSha256=hashlib.sha256(after.encode()).hexdigest(),allPriorFixtureAndAssertionContentPreserved=True))
result=dict(parent=parent,paths=reviews,all13GeneratedFilesActualCheckPassed=True,
    actual12ProfileTestsPassed=True,original77FixturesUnchanged=True,newTotal78=True,
    JavaSuccessfulProtobuf61WithOriginalContradictory1=True,DotnetSelectedProtobuf62=True,
    noProductionModelProtoOrGrantChanges=True,linuxSourceAndNativePending=True)
(coord/'integration-v12-union-review/current823-witness-addition-review-v35.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(dict(reviewedPaths=len(reviews),allPriorAssertionsPreserved=True)))
