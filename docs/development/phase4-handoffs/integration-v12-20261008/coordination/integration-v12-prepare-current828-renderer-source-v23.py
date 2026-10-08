import hashlib
import json
from pathlib import Path

coord = Path(__file__).resolve().parent
job = "integration-v12-current-collector-java-source-v22"
prior_head = "98281c17e28f9dd1dd6e9f0058069d71422df11e"
head = "756a492b1678dec5e4f69dac11c571acc3836dd1"
raw = (coord / job / "receipt.json").read_bytes()
assert hashlib.sha256(raw).hexdigest() == "dc208b40ba026944a3028a3ae305a4272a326a6fba63e7a097457034014dc401"
receipt = json.loads(raw)
assert receipt["head"] == prior_head and receipt["passed"] and receipt["sourceClean"]
assert receipt["sourceHeadUnchanged"] and receipt["originalProcessReaped"] and receipt["infrastructureError"] is None
for row in receipt["steps"]:
    data = (coord / job / row["log"]).read_bytes()
    assert row["exitCode"] == 0 and row["stopReason"] is None and row["originalProcessReaped"]
    assert hashlib.sha256(data).hexdigest() == row["sha256"] and len(data) == row["bytes"]
steps = json.loads((coord / "integration-v12-pr828-current-main-source-v16/invocation.json").read_bytes())["steps"]
steps[3][-1] = "target/ci/observed-current828-renderer-v23-linux.json"
path = coord / "integration-v12-current828-renderer-source-steps-v23.json"
path.write_text(json.dumps(steps, indent=2) + "\n", encoding="utf8")
controller = (coord / "entity-contract-v73-reused-signing-source-controller.py").read_text(encoding="utf8")
controller = controller.replace("integration-v12-current828-developmentc844-source-v10", job)
controller = controller.replace("7bc6e42254ef94c2b0248ad174d1e959aefc10e2", prior_head)
needle = "assert previous['head'] == '" + prior_head + "'"
controller = controller.replace(needle, needle + "\n    assert hashlib.sha256((prior / 'receipt.json').read_bytes()).hexdigest() == '" + hashlib.sha256(raw).hexdigest() + "'")
path = coord / "integration-v12-current828-renderer-reused-source-controller-v23.py"
compile(controller, str(path), "exec")
path.write_text(controller, encoding="utf8", newline="\n")
print(json.dumps(dict(head=head, priorHead=prior_head, allSevenLogsAuthenticated=True,
    original375BranchCasesAndLimitsPreserved=True, sourceOnly=True)))
