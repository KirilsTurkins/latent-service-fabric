import json
import os
from pathlib import Path
import subprocess

coord = Path(__file__).resolve().parent
env = dict(os.environ, GODEBUG="http2client=0")
raw = subprocess.check_output(["gh", "api", "repos/KirilsTurkins/latent-service-fabric/actions/runs/37729173027"], env=env)
value = json.loads(raw)
result = dict(run=value["id"], head=value["head_sha"], status=value["status"], conclusion=value["conclusion"],
    failedJobInfrastructureOnly=113154150383, unchangedHeadRerunOnlyAfterCompletion=True,
    noWorkflowMutation=True)
(coord / "integration-v12-union-review/current825-infra-run-status-v22.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf8")
print(json.dumps(result))
