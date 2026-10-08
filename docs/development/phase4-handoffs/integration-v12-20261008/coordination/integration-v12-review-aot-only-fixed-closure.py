from pathlib import Path
import copy
import json
import subprocess

coord=Path(__file__).resolve().parent/'integration-v12-union-review'
pairs=[(823,Path(r'C:\Users\turkins\Desktop\lf-p4-current-java-bd4-union-v12'),
 '511d5687f360258d05469cd2593de4d6f2556cf1','44754a7b9de0b41c456bcbbf31797b0cd47b0814'),
 (828,Path(r'C:\Users\turkins\Desktop\lf-p4-pr828-current-java-union-v12'),
 'f0322bb74085cc452cc7c9885a08b89ab218d290','6f03062bc9131e477d09639fa9e77e7f84103d57')]
rows=[]
for pr,root,parent,head in pairs:
    changed=subprocess.check_output(['git','-C',str(root),'diff','--name-only',parent,head]).decode().splitlines()
    assert changed==['tools/ci/suites.json']
    original=json.loads(subprocess.check_output(['git','-C',str(root),'show',parent+':tools/ci/suites.json']))
    current=json.loads(subprocess.check_output(['git','-C',str(root),'show',head+':tools/ci/suites.json']))
    expected=copy.deepcopy(original)
    target=next(row for row in expected['suites'] if row['id']=='latent-wasmtime.test.aot-sandbox')
    assert target['minimumCases']==0;target['minimumCases']=1
    assert expected==current
    rows.append(dict(pr=pr,parent=parent,current=head,onlyExactHistoricalRequiredAotMinimumRestored=True,
        mode=target['mode'],successMarker=target['successMarker'],allOtherSemanticBytesPreserved=True,
        productionSourceNativeClosureUnchanged=True,actualCurrentAotExecutionPending=True,sourceCheckPending=True))
(coord/'current-aot-only-fixed-native-source-closure.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps(rows))
