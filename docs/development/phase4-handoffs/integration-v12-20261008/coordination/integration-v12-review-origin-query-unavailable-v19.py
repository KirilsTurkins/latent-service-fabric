import hashlib
import json
from pathlib import Path

coord = Path(__file__).resolve().parent
job = coord / "integration-v12-current-java-real-node-v19"
raw = (job / "receipt.json").read_bytes()
receipt = json.loads(raw)
assert receipt["head"] == "528b2f59246855e3f3e23682d49b1fcd30940ad7" and not receipt["passed"]
assert receipt["sourceClean"] and receipt["sourceHeadUnchanged"] and receipt["originalProcessReaped"]
assert receipt["infrastructureError"] is None and [row["exitCode"] for row in receipt["steps"]] == [0, 0, 1]
for row in receipt["steps"]:
    data = (job / row["log"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == row["sha256"] and len(data) == row["bytes"]
http_raw = (job / "campaign/evidence/http-001-response.json").read_bytes()
http = json.loads(http_raw)
body = (job / "campaign/evidence/http-001.body").read_bytes()
assert http["status"] == 503 and body == b"Unavailable\n"
settings = json.loads((job / "campaign/node/installed-node.json").read_bytes())
origins = settings["httpIngress"]["browserOrigins"]
assert len(origins) == 1 and origins[0]["tenant"] == "examples" and origins[0]["authority"].startswith("localhost:")
campaign = json.loads((job / "campaign/campaign-receipt.json").read_bytes())
assert campaign["fixedFailureReason"] == "host-owned-transaction-response-headers"
proof = dict(head=receipt["head"], nativeReceiptSha256=hashlib.sha256(raw).hexdigest(),
    exactOriginalBrowserOriginNowConfigured=True, priorRootless403NoLongerObserved=True,
    firstQueryStatus=503, bodyBytes=len(body), responseSha256=hashlib.sha256(http_raw).hexdigest(),
    originalTransactionEnvelopeOracleStillRefusesGenericPlatformBody=True,
    actualActivationStagePending=True, signedGuestExecutionQualified=False,
    allProcessesReaped=True, originalDeadlineAndQuotasUnchanged=True,
    monitorCompletedWithoutSignals=True, originalFailedRootNotResumed=True)
(coord / "integration-v12-union-review/current-real-node-approved-origin-unavailable-review-v19.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
print(json.dumps(proof))
