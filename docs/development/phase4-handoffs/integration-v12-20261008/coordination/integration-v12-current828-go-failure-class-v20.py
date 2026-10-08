import hashlib
import json
from pathlib import Path

coord = Path(__file__).resolve().parent
out = coord / "integration-v12-current828-failed-go-ci-v20"
raw = (out / "job.log").read_bytes()
text = raw.decode()
metadata = json.loads((out / "job.json").read_bytes())
assert any(row["name"] == "Qualify captured Go libraries in signed components"
           and row.get("conclusion") == "failure" for row in metadata["steps"])
assert "WorkflowError: authoring-control-29-4" in text
assert 'File "/home/runner/work/latent-service-fabric/latent-service-fabric/tools/rust_capsule_cases.py", line 141, in population' in text
assert 'result = client.call("deployment", "apply", path' in text
proof = dict(pr=828, head="912701092b03c97d6ce92e5bbac8a9f9a2f5fc68", job=113151984458,
    logSha256=hashlib.sha256(raw).hexdigest(), failedQualifierStep="captured Go libraries",
    failedWorkflowPhase="node population deployment apply", failedOriginalControlCall=29,
    failedExitStatus=4, actualPlatformErrorCodePendingArtifact=True,
    sdkRuntimeCauseNotInferredFromJobName=True, authoredCompilerFailureNotEstablished=True,
    noBudgetChangeOrMutationRetry=True)
(out / "closed-failure-class.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
print(json.dumps(proof))
