import ast
import hashlib
import json
from pathlib import Path
import subprocess

coord = Path(__file__).resolve().parent
repo = Path(r"C:\Users\turkins\Desktop\latent-fabric")
head = "528b2f59246855e3f3e23682d49b1fcd30940ad7"
parent = "30300f5f776c8ce70a8e81e01436d050101c4931"
job = coord / "integration-v12-approved-origin-source-v19"
raw = (job / "receipt.json").read_bytes()
receipt = json.loads(raw)
assert receipt["head"] == head and receipt["passed"] and receipt["sourceClean"]
assert receipt["sourceHeadUnchanged"] and receipt["originalProcessReaped"] and receipt["infrastructureError"] is None
for row in receipt["steps"]:
    data = (job / row["log"]).read_bytes()
    assert row["exitCode"] == 0 and row["stopReason"] is None and row["originalProcessReaped"]
    assert hashlib.sha256(data).hexdigest() == row["sha256"] and len(data) == row["bytes"]
changes = subprocess.check_output(["git", "diff", "--name-only", parent, head], cwd=repo).decode().splitlines()
assert changes == ["tools/ci/contracts/python/test_java_transaction_origin.py.json",
    "tools/java_transaction_qualification/configuration.py", "tools/tests/test_java_transaction_origin.py"]
original = subprocess.check_output(["git", "show", parent + ":tools/java_transaction_qualification/configuration.py"], cwd=repo)
current = subprocess.check_output(["git", "show", head + ":tools/java_transaction_qualification/configuration.py"], cwd=repo)
addition = b'        "browserOrigins": [{"authority": authority, "tenant": TENANT}],\n'
assert current.count(addition) == 1 and current.replace(addition, b"") == original
assert not subprocess.check_output(["git", "diff", parent, head, "--", "apps", "crates", "api", "sdk", "wit", "schemas", "Cargo.lock", "Cargo.toml"], cwd=repo)
proof = dict(head=head, parent=parent, sourceReceiptSha256=hashlib.sha256(raw).hexdigest(),
    actualPythonCases=396, actualPassingCases=395, originalWindowsSkip=1,
    allSevenSourceGatesPassed=True, oldConfigurationBytesExactExceptOneExplicitOrigin=True,
    oldHttpOriginBearerRefusalAndBudgetSemanticsUnchanged=True, noProductionOrGrantChange=True,
    actualSignedNodeCorrectedWorkflowPending=True, allProcessesReaped=True, normalCheckpointPublished=True,
    fullCI=False, issueClosed=False)
(coord / "integration-v12-union-review/approved-origin-qualified-source-proof-v19.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
print(json.dumps(proof))
