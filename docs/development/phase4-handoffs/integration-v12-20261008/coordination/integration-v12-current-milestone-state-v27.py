from datetime import datetime, timezone
from pathlib import Path
import json
import os
import subprocess

coord = Path(__file__).resolve().parent
env = dict(os.environ, GODEBUG='http2client=0')
raw = subprocess.check_output(['gh', 'api', 'repos/KirilsTurkins/latent-service-fabric/issues?milestone=7&state=all&per_page=100'], env=env)
issues = json.loads(raw)
assert all(i.get('milestone', {}).get('number') == 7 for i in issues)
rows = [dict(number=i['number'], state=i['state'], title=i['title'], updatedAt=i['updated_at']) for i in issues]
result = dict(at=datetime.now(timezone.utc).isoformat(), milestone=7,
    exactTitle=issues[0]['milestone']['title'],
    openCount=sum(r['state'] == 'open' for r in rows),
    closedCount=sum(r['state'] == 'closed' for r in rows), rows=rows,
    closureMutationPerformed=False)
out = coord / 'integration-v12-union-review/current-milestone-state-v27.json'
out.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(dict(custody=str(out), openCount=result['openCount'], closedCount=result['closedCount'],
    closedIssues=[r['number'] for r in rows if r['state'] == 'closed'])))
