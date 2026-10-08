from pathlib import Path
import json
import subprocess

root=Path(r'C:\Users\turkins\Desktop\lf-p4-current-java-bd4-union-v12')
revs=['cbef28330f87de778141017cfedf1faa32bb520a','0cd6c2e8649e8181366e0adbfe03da1bf2a3c7a3','511d5687f360258d05469cd2593de4d6f2556cf1','44754a7b9de0b41c456bcbbf31797b0cd47b0814']
rows=[]
for rev in revs:
    value=json.loads(subprocess.check_output(['git','-C',str(root),'show',rev+':tools/ci/suites.json']))
    row=next(row for row in value['suites'] if row['id']=='latent-wasmtime.test.aot-sandbox')
    rows.append(dict(head=rev,contract={key:row.get(key) for key in ('mode','minimumCases','expectedCases','expectedIgnored','successMarker','listContract','runArgs','expectedCustomCases','recipe','source')}))
print(json.dumps(rows))
(Path(__file__).resolve().parent/'integration-v12-union-review/aot-custom-harness-current-contract-review.json').write_text(json.dumps(rows,indent=2)+'\n')
