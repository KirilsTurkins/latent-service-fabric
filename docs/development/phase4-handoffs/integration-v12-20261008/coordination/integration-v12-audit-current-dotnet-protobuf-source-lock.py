from pathlib import Path
import hashlib
import json
import subprocess

coord=Path(__file__).resolve().parent/'integration-v12-union-review'
roots=[(823,Path(r'C:\Users\turkins\Desktop\lf-p4-current-java-bd4-union-v12'),'0a783d97762f763ca6ab237d4bb36eb306bbddec'),
       (828,Path(r'C:\Users\turkins\Desktop\lf-p4-pr828-current-java-union-v12'),'0a637ba7844c7fe461873d0fa783bca8166f4971')]
rows=[]
for pr,root,head in roots:
    lock=json.loads(subprocess.check_output(['git','-C',str(root),'show',head+':sdk/dotnet/protobuf.lock.json']))
    mismatch=[];actual={}
    for name,before in lock['inputs'].items():
        raw=subprocess.check_output(['git','-C',str(root),'show',head+':api/proto/'+name]).replace(b'\r\n',b'\n')
        value=hashlib.sha256(raw).hexdigest();actual[name]=value
        if value!=before:mismatch.append(dict(path=name,locked=before,actual=value))
    rows.append(dict(pr=pr,head=head,actualInputs=actual,mismatches=mismatch,
                     hashesNotMutated=True,actualPinnedProducerRequired=True))
(coord/'current-dotnet-protobuf-input-lock-audit-v13.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps(rows))
