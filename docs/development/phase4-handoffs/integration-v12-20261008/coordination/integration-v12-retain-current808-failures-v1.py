from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess

coord = Path(__file__).resolve().parent
out = coord/'integration-v12-pr808-completed-failures-913e-v1'
out.mkdir(exist_ok=True)
env = dict(os.environ,GODEBUG='http2client=0')
jobs = {113092175783:'C',113092410554:'Go',113092435300:'Java',113092176140:'TypeScript',
        113092177687:'DeveloperToolsRust',113092177607:'DeveloperToolsTypeScript'}
def capture(pair):
    job, lane = pair
    raw = subprocess.check_output(['gh','api',f'repos/KirilsTurkins/latent-service-fabric/actions/jobs/{job}/logs'],env=env,timeout=90)
    (out/f'{job}.log').write_bytes(raw)
    text = raw.decode('utf8',errors='replace')
    lines = [line for line in text.splitlines() if re.search(r'error\[|error:|Error:|Traceback|ValueError|##\[error\]',line)]
    return dict(job=job,lane=lane,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),diagnostics=lines[-12:])
with ThreadPoolExecutor(max_workers=3) as pool:
    rows=list(pool.map(capture,jobs.items()))
(out/'receipt.json').write_text(json.dumps(dict(head='913e03d454282c7f60b39d8a1850f25eb4bbdef6',logs=rows),indent=2)+'\n')
print(json.dumps(dict(custody=str(out),logs=rows)))
