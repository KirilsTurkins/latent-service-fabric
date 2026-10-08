from pathlib import Path
import json
import subprocess

pairs=[(823,Path(r'C:\Users\turkins\Desktop\lf-p4-current-java-bd4-union-v12'),'0a0dc2818946111c8657e6b681ecef1f9f3fafab'),
       (828,Path(r'C:\Users\turkins\Desktop\lf-p4-pr828-current-java-union-v12'),'7bc6e42254ef94c2b0248ad174d1e959aefc10e2')]
rows=[]
for pr,root,head in pairs:
    value=json.loads(subprocess.check_output(['git','-C',str(root),'show',head+':tools/ci/suites.json']))
    row=next(item for item in value['suites'] if item['id']=='latent-wasmtime.test.aot-sandbox')
    assert row['minimumCases']>=1
    rows.append(dict(pr=pr,head=head,suite=row,requiredHistoricalMinimum=1,fullNativeFixtureExecutedHere=False))
out=Path(__file__).resolve().parent/'integration-v12-union-review/current-aot-historical-floor-review-v9.json'
out.write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps([dict(pr=row['pr'],floor=row['suite']['minimumCases'],historicalMinimumPreserved=True) for row in rows]))
