from datetime import datetime, timezone
from pathlib import Path
import json
import os
import subprocess

coord=Path(__file__).resolve().parent
repo='KirilsTurkins/latent-service-fabric'
env=dict(os.environ,GODEBUG='http2client=0')
raw=subprocess.check_output(['gh','api',f'repos/{repo}/issues?milestone=7&state=all&per_page=100'],env=env,timeout=90)
rows=json.loads(raw)
assert rows and all(row['milestone']['number']==7 for row in rows)
issues=[dict(number=row['number'],title=row['title'],state=row['state'],closedAt=row['closed_at'])
        for row in rows if 'pull_request' not in row]
out=coord/'integration-v12-union-review/current-phase4-ticket-live-reconcile-v3.json'
result=dict(at=datetime.now(timezone.utc).isoformat(),milestone=7,
    openCount=sum(row['state']=='open' for row in issues),closedCount=sum(row['state']=='closed' for row in issues),
    issues=issues,additionalFullyCompleteMergedTicketConfirmed=False)
out.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
