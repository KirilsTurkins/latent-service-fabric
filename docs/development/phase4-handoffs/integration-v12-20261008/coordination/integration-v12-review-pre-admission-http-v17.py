import hashlib
import json
from pathlib import Path

coord = Path(__file__).resolve().parent
job = coord / "integration-v12-current-java-real-node-v17"
raw = (job / "receipt.json").read_bytes()
receipt = json.loads(raw)
assert receipt["head"] == "027315a4bda3cc9d6b921d671b2756f3edee25b0" and not receipt["passed"]
assert receipt["sourceClean"] and receipt["sourceHeadUnchanged"] and receipt["originalProcessReaped"]
assert receipt["infrastructureError"] is None and [row["exitCode"] for row in receipt["steps"]] == [0, 0, 1]
for row in receipt["steps"]:
    data = (job / row["log"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == row["sha256"] and len(data) == row["bytes"]
observed = json.loads((job / "campaign/evidence/http-refusal-stage-observation.json").read_bytes())
roots_raw = (job / "campaign/evidence/cli-038.stdout").read_bytes()
roots = json.loads(roots_raw)
assert observed["observationAvailable"] is True and observed["rootCount"] == 0 and not observed["truncated"]
assert roots["category"] == "success" and roots["data"]["historyAvailable"] is True
assert roots["data"]["nodes"] == [] and roots["data"]["nextPageToken"] is None and not roots["data"]["cursorExpired"]
proof = dict(nativeHead=receipt["head"], nativeReceiptSha256=hashlib.sha256(raw).hexdigest(),
    originalOracleStillFails=True, firstQueryHttpStatus=403, actualServiceRootHistoryAvailable=True,
    actualRetainedServiceRoots=0, rootResponseSha256=hashlib.sha256(roots_raw).hexdigest(),
    rootStageDiagnosticDidNotReplaceFailure=True, guestExecutionQualified=False,
    likelyPreAdmissionBoundaryIsInference=True, exactProductionCausePending=True,
    allOriginalBoundsRetained=True, originalFailedCampaignNotResumed=True, allProcessesReaped=True)
(coord / "integration-v12-union-review/current-real-node-rootless-http-review-v17.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
print(json.dumps(proof))
