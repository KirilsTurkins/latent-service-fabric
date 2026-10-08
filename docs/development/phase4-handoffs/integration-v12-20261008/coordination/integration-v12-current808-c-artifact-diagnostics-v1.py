from pathlib import Path
import hashlib
import io
import json
import os
import re
import subprocess
import zipfile

out=Path(__file__).resolve().parent/'integration-v12-pr808-completed-failures-913e-v1'
env=dict(os.environ,GODEBUG='http2client=0')
artifact=11523465191
expected='6a11337aac7e3c8594f2ed0fdace2e70598bb9c7dcca6d2125134e88c708a859'
data=subprocess.check_output(['gh','api',f'repos/KirilsTurkins/latent-service-fabric/actions/artifacts/{artifact}/zip'],env=env,timeout=120)
assert len(data)==1140495 and hashlib.sha256(data).hexdigest()==expected
(out/f'artifact-{artifact}.zip').write_bytes(data)
rows=[]
with zipfile.ZipFile(io.BytesIO(data)) as archive:
    for member in archive.infolist():
        if not member.filename.endswith(('.stderr','.stderr.txt','.log')) or member.file_size>2097152:
            continue
        raw=archive.read(member)
        text=raw.decode('utf8',errors='replace')
        if not re.search(r'error\[E\d+\]|error: could not compile',text):
            continue
        lines=text.splitlines()
        contexts=[]
        for index,line in enumerate(lines):
            if re.search(r'error\[E\d+\]|error: could not compile',line):
                contexts.append('\n'.join(lines[max(0,index-1):min(len(lines),index+14)]))
        identity=hashlib.sha256(raw).hexdigest()
        (out/f'compiler-{identity[:16]}.txt').write_bytes(raw)
        rows.append(dict(path=member.filename,sha256=identity,bytes=len(raw),contexts=contexts))
(out/'c-actual-build-diagnostics.json').write_text(json.dumps(dict(artifact=artifact,digest=expected,files=rows),indent=2)+'\n')
print(json.dumps(rows))
