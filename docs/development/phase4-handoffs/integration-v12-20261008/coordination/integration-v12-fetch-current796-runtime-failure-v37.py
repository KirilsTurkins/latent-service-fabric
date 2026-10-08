from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import subprocess

coord=Path(__file__).resolve().parent
out=coord/'integration-v12-current796-runtime-failure-v37'
out.mkdir(exist_ok=False)
env=dict(os.environ,GODEBUG='http2client=0')
repo='KirilsTurkins/latent-service-fabric'
job=113168379343
meta=subprocess.check_output(['gh','api',f'repos/{repo}/actions/jobs/{job}'],env=env)
(out/'job.json').write_bytes(meta)
parsed=json.loads(meta)
assert parsed['status']=='completed' and parsed['conclusion']=='failure'
raw=subprocess.check_output(['gh','api',f'repos/{repo}/actions/jobs/{job}/logs'],env=env)
(out/'job.log').write_bytes(raw)
receipt=dict(at=datetime.now(timezone.utc).isoformat(),job=job,run=parsed['run_id'],
    head=parsed['head_sha'],name=parsed['name'],bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),
    failedSteps=[s['name'] for s in parsed['steps'] if s.get('conclusion')=='failure'],readOnly=True)
(out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt))
