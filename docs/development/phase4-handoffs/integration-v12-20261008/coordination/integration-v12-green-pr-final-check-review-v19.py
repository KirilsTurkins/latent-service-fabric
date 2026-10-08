from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

coord = Path(__file__).resolve().parent
env = dict(os.environ, GODEBUG="http2client=0")
records = []
for number in (796, 784):
    raw = subprocess.check_output(["gh", "pr", "checks", str(number), "--repo", "KirilsTurkins/latent-service-fabric",
        "--json", "name,state,bucket,link"], env=env)
    rows = json.loads(raw)
    records.append(dict(pr=number, total=len(rows), pendingOrFailed=[row for row in rows if row["bucket"] in {"pending", "fail"}],
        accepted=len([row for row in rows if row["bucket"] == "pass"])))
result = dict(at=datetime.now(timezone.utc).isoformat(), records=records, noWorkflowMutation=True)
(coord / "integration-v12-union-review/green-pr-final-check-review-v19.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf8")
print(json.dumps(result))
