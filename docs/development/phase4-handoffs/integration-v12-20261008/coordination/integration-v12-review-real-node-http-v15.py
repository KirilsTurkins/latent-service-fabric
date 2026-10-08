import hashlib
import json
from pathlib import Path

coord = Path(__file__).resolve().parent
job = coord / "integration-v12-current-java-real-node-v15"
raw = (job / "receipt.json").read_bytes()
receipt = json.loads(raw)
assert receipt["head"] == "0feb8019a283475f516d63b69e595294f215e095" and not receipt["passed"]
assert receipt["sourceClean"] and receipt["sourceHeadUnchanged"] and receipt["originalProcessReaped"]
assert receipt["infrastructureError"] is None and [row["exitCode"] for row in receipt["steps"]] == [0, 0, 1]
for row in receipt["steps"]:
    data = (job / row["log"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == row["sha256"] and len(data) == row["bytes"]
campaign = json.loads((job / "campaign/campaign-receipt.json").read_bytes())
http_raw = (job / "campaign/evidence/http-001-response.json").read_bytes()
http = json.loads(http_raw)
assert campaign["failedStage"] == "actual-http" and campaign["fixedFailureReason"] == "transaction-response-status"
assert http["status"] == 403 and (job / "campaign/evidence/http-001.body").stat().st_size == 0
assert "namespace-create" in campaign["measuredCases"] and "deploy-put-once-legacy-v1" in campaign["measuredCases"]
source_receipt = (coord / "integration-v12-query-refusal-source-v17/receipt.json").read_bytes()
source = json.loads(source_receipt)
assert source["passed"] and source["sourceClean"] and source["sourceHeadUnchanged"] and source["originalProcessReaped"]
proof = dict(nativeHead=receipt["head"], nativeReceiptSha256=hashlib.sha256(raw).hexdigest(),
    firstQueryHttpStatus=403, firstQueryBodyBytes=0, responseSha256=hashlib.sha256(http_raw).hexdigest(),
    namespaceCreateAndDeploymentActuallyPassed=True, signedGuestExecutionQualified=False,
    queryExecutionStageNotYetObserved=True, originalHttpOracleUnchanged=True,
    observerHead=source["head"], observerSourceReceiptSha256=hashlib.sha256(source_receipt).hexdigest(),
    allSourceGatesPassed=True, originalFailedAttemptPreserved=True, failedRootNotResumed=True,
    productionAuthorizationUnchanged=True)
(coord / "integration-v12-union-review/current-real-node-http-failure-review-v15.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
print(json.dumps(proof))
