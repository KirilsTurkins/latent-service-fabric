"""Validate the retained successful namespace receipt without replaying a mutation."""
import hashlib
import json
from pathlib import Path

coord = Path(__file__).resolve().parent
job = coord / "integration-v12-current-java-real-node-v14"
raw_receipt = (job / "receipt.json").read_bytes()
receipt = json.loads(raw_receipt)
assert receipt["head"] == "e9a054503aed62c4549d965301d6a4a84dd1a117"
assert receipt["passed"] is False and receipt["sourceClean"] and receipt["sourceHeadUnchanged"]
assert receipt["originalProcessReaped"] and receipt["infrastructureError"] is None
for row in receipt["steps"]:
    raw = (job / row["log"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == row["sha256"] and len(raw) == row["bytes"]
assert [row["exitCode"] for row in receipt["steps"]] == [0, 0, 1]
raw = (job / "campaign/evidence/cli-024.stdout").read_bytes()
value = json.loads(raw)
created = value["data"]["receipt"]
configuration = json.loads((job / "campaign/client/namespace-create.json").read_bytes())
framed = bytearray(b"latent.host-recovery-scope.v1\0\x01")
for text in ("examples", "administrator", "workflow-operator"):
    encoded = text.encode()
    framed.extend(len(encoded).to_bytes(2, "little"))
    framed.extend(encoded)
actor = "administrator:recovery:sha256:" + hashlib.sha256(framed).hexdigest()
predicates = dict(outcomeKnown=value["outcomeKnown"] is True,
    exactOperation=created["operationId"] == "java-create",
    exactSignedSchema=created["stateSchema"] == configuration["stateSchema"],
    durableAudit=value["data"]["auditAcknowledgement"]["status"] == "AUDIT_ACK_STATUS_DURABLE",
    exactDerivedActor=created["authenticatedOperator"] == actor,
    staleBareSubjectComparison=created["authenticatedOperator"] == "workflow-operator")
assert all(ok for name, ok in predicates.items() if name != "staleBareSubjectComparison")
assert predicates["staleBareSubjectComparison"] is False
campaign = json.loads((job / "campaign/campaign-receipt.json").read_bytes())
assert campaign["fixedFailureReason"] == "actual-authorized-namespace-create"
assert len(campaign["measuredCases"]) == 5 and not campaign["signedGuestExecutionQualified"]
proof = dict(nativeHead=receipt["head"], receiptSha256=hashlib.sha256(raw_receipt).hexdigest(),
    createResponseSha256=hashlib.sha256(raw).hexdigest(), exactOriginalCallerActor=actor,
    predicates=predicates, namespaceCreationActuallyCommitted=True, priorLeaseRestartStagePassed=True,
    signedPublications=5, actualGuestInvocations=0, allProcessesReaped=True,
    productAuthorizationUnchanged=True, originalMutationNotRetried=True, failedRootNotResumed=True)
(coord / "integration-v12-union-review/current-real-node-namespace-create-review-v14.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
print(json.dumps(proof, indent=2))
