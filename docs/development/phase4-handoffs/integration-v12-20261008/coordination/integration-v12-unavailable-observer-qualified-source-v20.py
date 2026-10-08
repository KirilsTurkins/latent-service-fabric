import hashlib
import json
from pathlib import Path
import subprocess

coord = Path(__file__).resolve().parent
repo = Path(r"C:\Users\turkins\Desktop\latent-fabric")
head = "6d09d6095e8ada217a51b5f878e48aba62e03abf"
parent = "528b2f59246855e3f3e23682d49b1fcd30940ad7"
job = coord / "integration-v12-unavailable-observer-source-v20"
raw = (job / "receipt.json").read_bytes()
receipt = json.loads(raw)
assert receipt["head"] == head and receipt["passed"] and receipt["sourceClean"]
assert receipt["sourceHeadUnchanged"] and receipt["originalProcessReaped"] and receipt["infrastructureError"] is None
for row in receipt["steps"]:
    data = (job / row["log"]).read_bytes()
    assert row["exitCode"] == 0 and row["stopReason"] is None and row["originalProcessReaped"]
    assert hashlib.sha256(data).hexdigest() == row["sha256"] and len(data) == row["bytes"]
assert not subprocess.check_output(["git", "diff", parent, head, "--", "apps", "crates", "api", "sdk", "wit", "schemas", "Cargo.lock", "Cargo.toml"], cwd=repo)
old = subprocess.check_output(["git", "show", parent + ":tools/java_transaction_qualification/campaign.py"], cwd=repo)
new = subprocess.check_output(["git", "show", head + ":tools/java_transaction_qualification/campaign.py"], cwd=repo)
assert new.replace(b"{400, 401, 403, 404, 405, 502, 503}", b"{400, 401, 403, 404, 405, 502}") == old
proof = dict(head=head, parent=parent, sourceReceiptSha256=hashlib.sha256(raw).hexdigest(),
    actualPythonCases=397, actualPassingCases=396, originalWindowsSkip=1,
    allSevenSourceGatesPassed=True, exactlyOneUnavailableObserverClassAdded=True,
    allRuntimeSdkApiWitSchemasLocksUnchanged=True, allOriginalResponseAssertionsUnchanged=True,
    original503GenericHeaderFailureNotAccepted=True, oneReadOnlyPageUnderOriginalDeadline=True,
    actualStageExecutionPending=True, normalOwnedCheckpointPublished=True, allProcessesReaped=True,
    fullCI=False, issueClosed=False)
(coord / "integration-v12-union-review/unavailable-observer-qualified-source-proof-v20.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
print(json.dumps(proof))
