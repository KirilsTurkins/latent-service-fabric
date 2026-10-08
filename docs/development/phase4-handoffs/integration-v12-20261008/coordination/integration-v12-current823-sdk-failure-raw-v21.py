from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

coord = Path(__file__).resolve().parent
out = coord / "integration-v12-current823-sdk-failure-v21"
out.mkdir()
env = dict(os.environ, GODEBUG="http2client=0")
repo = "KirilsTurkins/latent-service-fabric"
job, run = 113159527038, 37728063383
raw_job = subprocess.check_output(["gh", "api", f"repos/{repo}/actions/jobs/{job}"], env=env)
metadata = json.loads(raw_job)
assert metadata["run_id"] == run and metadata["conclusion"] == "failure"
(out / "job.json").write_bytes(raw_job)
raw = subprocess.check_output(["gh", "api", f"repos/{repo}/actions/jobs/{job}/logs"], env=env)
assert 0 < len(raw) < 4 * 1024 ** 2
(out / "job.log").write_bytes(raw)
proof = dict(at=datetime.now(timezone.utc).isoformat(), pr=823, expectedHead="3b7af5096198ae9453b5616bc124def18798911c",
    run=run, job=job, conclusion=metadata["conclusion"], logBytes=len(raw), logSha256=hashlib.sha256(raw).hexdigest(),
    failedSteps=[row["name"] for row in metadata["steps"] if row.get("conclusion") == "failure"],
    rawSdkBytesNotPrinted=True, causePending=True, noSourceOrWorkflowMutation=True)
(out / "receipt.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
print(json.dumps(proof))
