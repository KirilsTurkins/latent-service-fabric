import hashlib
import json
from pathlib import Path

coord = Path(__file__).resolve().parent
prior_job = "integration-v12-query-refusal-source-v17"
prior_head = "027315a4bda3cc9d6b921d671b2756f3edee25b0"
raw = (coord / prior_job / "receipt.json").read_bytes()
receipt = json.loads(raw)
assert receipt["head"] == prior_head and receipt["passed"] and receipt["sourceClean"]
assert receipt["sourceHeadUnchanged"] and receipt["originalProcessReaped"] and receipt["infrastructureError"] is None
for row in receipt["steps"]:
    data = (coord / prior_job / row["log"]).read_bytes()
    assert row["exitCode"] == 0 and row["stopReason"] is None and row["originalProcessReaped"]
    assert hashlib.sha256(data).hexdigest() == row["sha256"] and len(data) == row["bytes"]
steps = json.loads((coord / prior_job / "invocation.json").read_bytes())["steps"]
steps[3][-1] = "target/ci/observed-current-collector-v18-linux.json"
path = coord / "integration-v12-current-collector-source-steps-v18.json"
path.write_text(json.dumps(steps, indent=2) + "\n", encoding="utf8")
controller = (coord / "entity-contract-v73-reused-signing-source-controller.py").read_text(encoding="utf8")
controller = controller.replace("integration-v12-current828-developmentc844-source-v10", prior_job)
controller = controller.replace("7bc6e42254ef94c2b0248ad174d1e959aefc10e2", prior_head)
needle = "assert previous['head'] == '" + prior_head + "'"
controller = controller.replace(needle, needle + "\n    assert hashlib.sha256((prior / 'receipt.json').read_bytes()).hexdigest() == '" + hashlib.sha256(raw).hexdigest() + "'")
path = coord / "integration-v12-current-collector-reused-source-controller-v18.py"
compile(controller, str(path), "exec")
path.write_text(controller, encoding="utf8", newline="\n")
print(json.dumps(dict(priorHead=prior_head, priorReceiptSha256=hashlib.sha256(raw).hexdigest(), allSevenLogsAuthenticated=True)))
