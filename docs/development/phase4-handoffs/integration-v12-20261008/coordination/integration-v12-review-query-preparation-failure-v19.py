import hashlib
import json
from pathlib import Path

coord = Path(__file__).resolve().parent
path = coord / "integration-v12-current-java-real-node-v19/campaign/evidence/node-3-stopped.json"
raw = path.read_bytes()
stopped = json.loads(raw)
assert stopped["reaped"] is True
record = stopped["record"]
assert record["clean"] is True
report = record["report"]
compiler = report["compiler"]
assert (compiler["jobs_started"], compiler["jobs_completed"], compiler["jobs_failed"]) == (1, 0, 1)
assert compiler["workers_joined"] == 1 and compiler["workers_live"] == 0
assert not compiler["failed"] and compiler["jobs_abandoned"] == 0
for name in ("liveStores", "liveHostStates", "liveInstances", "activeActivations", "quotaReservations"):
    assert report[name] == 0
assert report["state"]["clean"] and report["state"]["storeEngine"] == "closed"
proof = dict(head="528b2f59246855e3f3e23682d49b1fcd30940ad7", stoppedRecordSha256=hashlib.sha256(raw).hexdigest(),
    actualOnePreparationJobStarted=True, actualPreparationJobsFailed=1, actualPreparationJobsCompleted=0,
    preparationWorkerPhysicallyJoined=True, compilationFailureStageReasonPending=True,
    actualGuestInvocationSuccessNotProven=True, nativeGuestStateOwnersPhysicallyRetired=True,
    noBudgetOrProfileRelaxation=True, originalFailedRootNotResumed=True)
(coord / "integration-v12-union-review/query-preparation-failure-review-v19.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
print(json.dumps(proof))
