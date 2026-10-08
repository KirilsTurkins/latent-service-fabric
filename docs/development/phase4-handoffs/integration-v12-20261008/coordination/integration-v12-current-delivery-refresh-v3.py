from datetime import datetime, timezone
from pathlib import Path
import json
import os
import subprocess

coord = Path(__file__).resolve().parent
repo = 'KirilsTurkins/latent-service-fabric'
env = dict(os.environ, GODEBUG='http2client=0')
out = coord / ('integration-v12-delivery-refresh-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
out.mkdir()
raw = subprocess.check_output(['gh','pr','list','--repo',repo,'--base','development','--state','open',
    '--limit','100','--json','number,headRefOid,mergeable,title,statusCheckRollup'], env=env)
(out/'raw.json').write_bytes(raw)
owned = {784,787,790,791,796,800,808,811,823,825,828}
rows = []
for row in json.loads(raw):
    if row['number'] not in owned:
        continue
    checks = row['statusCheckRollup']
    failed = [item for item in checks if item.get('conclusion') in {'FAILURE','TIMED_OUT','ACTION_REQUIRED'}]
    pending = [item for item in checks if item.get('status') != 'COMPLETED']
    green = bool(checks) and not pending and all(item.get('conclusion') in {'SUCCESS','SKIPPED','NEUTRAL'} for item in checks)
    rows.append(dict(number=row['number'],head=row['headRefOid'],mergeable=row['mergeable'],
        failures=[dict(name=item.get('name'),url=item.get('detailsUrl'),conclusion=item.get('conclusion'))
                  for item in failed],pending=len(pending),checkCount=len(checks),fullyGreen=green))
(out/'summary.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps(dict(custody=str(out),prs=rows)))
