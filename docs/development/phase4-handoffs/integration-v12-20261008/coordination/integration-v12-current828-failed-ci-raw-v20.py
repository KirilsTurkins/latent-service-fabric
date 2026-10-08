from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

coord = Path(__file__).resolve().parent
out = coord / "integration-v12-current828-failed-go-ci-v20"
out.mkdir(exist_ok=True)
env = dict(os.environ, GODEBUG="http2client=0")
repo = "KirilsTurkins/latent-service-fabric"
job = 113151984458
run = 37728484462
metadata = subprocess.check_output(["gh", "api", f"repos/{repo}/actions/jobs/{job}"], env=env)
value = json.loads(metadata)
assert value["run_id"] == run and value["conclusion"] == "failure"
(out / "job.json").write_bytes(metadata)
raw = subprocess.check_output(["gh", "api", f"repos/{repo}/actions/jobs/{job}/logs"], env=env)
assert 0 < len(raw) < 4 * 1024 ** 2
(out / "job.log").write_bytes(raw)
proof = dict(at=datetime.now(timezone.utc).isoformat(), pr=828, expectedHead="912701092b03c97d6ce92e5bbac8a9f9a2f5fc68",
    run=run, job=job, conclusion=value["conclusion"], logBytes=len(raw), logSha256=hashlib.sha256(raw).hexdigest(),
    failedStepNames=[row["name"] for row in value["steps"] if row.get("conclusion") == "failure"],
    rawGuestOutputNotPrinted=True, causePending=True, noSourceOrWorkflowMutation=True)
(out / "receipt.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
print(json.dumps(proof))
