from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

coord = Path(__file__).resolve().parent
out = coord / "integration-v12-current828-renderer-web-failure-v23"
out.mkdir()
env = dict(os.environ, GODEBUG="http2client=0")
repo = "KirilsTurkins/latent-service-fabric"
run = 37728484802
records = []
for job in (113161200993, 113161201105):
    raw_metadata = subprocess.check_output(["gh", "api", f"repos/{repo}/actions/jobs/{job}"], env=env)
    value = json.loads(raw_metadata)
    assert value["run_id"] == run and value["conclusion"] == "failure"
    (out / (str(job) + ".json")).write_bytes(raw_metadata)
    raw = subprocess.check_output(["gh", "api", f"repos/{repo}/actions/jobs/{job}/logs"], env=env)
    assert 0 < len(raw) <= 4 * 1024 ** 2
    (out / (str(job) + ".log")).write_bytes(raw)
    records.append(dict(job=job, name=value["name"], failedSteps=[row["name"] for row in value["steps"] if row.get("conclusion") == "failure"],
        logBytes=len(raw), logSha256=hashlib.sha256(raw).hexdigest()))
proof = dict(at=datetime.now(timezone.utc).isoformat(), pr=828, expectedHead="912701092b03c97d6ce92e5bbac8a9f9a2f5fc68",
    run=run, jobs=records, rawGuestOrBrowserPayloadNotPrinted=True, noWorkflowOrSourceMutation=True)
(out / "receipt.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
print(json.dumps(proof))
