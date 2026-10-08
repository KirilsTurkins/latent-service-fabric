import hashlib
import json
from pathlib import Path

coord = Path(__file__).resolve().parent
job = "integration-v12-approved-origin-source-v19"
prior_head = "528b2f59246855e3f3e23682d49b1fcd30940ad7"
head = "6d09d6095e8ada217a51b5f878e48aba62e03abf"
raw = (coord / job / "receipt.json").read_bytes()
assert hashlib.sha256(raw).hexdigest() == "38971e26308eed381f70efbbd5b4c01f53715cad20c8e45b016dd6e77014f8e0"
receipt = json.loads(raw)
assert receipt["head"] == prior_head and receipt["passed"] and receipt["sourceClean"]
assert receipt["sourceHeadUnchanged"] and receipt["originalProcessReaped"] and receipt["infrastructureError"] is None
for row in receipt["steps"]:
    data = (coord / job / row["log"]).read_bytes()
    assert row["exitCode"] == 0 and row["stopReason"] is None and row["originalProcessReaped"]
    assert hashlib.sha256(data).hexdigest() == row["sha256"] and len(data) == row["bytes"]
steps = json.loads((coord / job / "invocation.json").read_bytes())["steps"]
needle = "'tools.tests.test_java_transaction_origin']"
assert steps[0][-1].count(needle) == 1
steps[0][-1] = steps[0][-1].replace(needle, "'tools.tests.test_java_transaction_origin', 'tools.tests.test_java_transaction_unavailable_observation']")
steps[3][-1] = "target/ci/observed-unavailable-query-v20-linux.json"
path = coord / "integration-v12-unavailable-observer-source-steps-v20.json"
path.write_text(json.dumps(steps, indent=2) + "\n", encoding="utf8")
controller = (coord / "entity-contract-v73-reused-signing-source-controller.py").read_text(encoding="utf8")
controller = controller.replace("integration-v12-current828-developmentc844-source-v10", job)
controller = controller.replace("7bc6e42254ef94c2b0248ad174d1e959aefc10e2", prior_head)
needle = "assert previous['head'] == '" + prior_head + "'"
controller = controller.replace(needle, needle + "\n    assert hashlib.sha256((prior / 'receipt.json').read_bytes()).hexdigest() == '" + hashlib.sha256(raw).hexdigest() + "'")
path = coord / "integration-v12-unavailable-observer-reused-source-controller-v20.py"
compile(controller, str(path), "exec")
path.write_text(controller, encoding="utf8", newline="\n")
print(json.dumps(dict(head=head, priorHead=prior_head, priorReceiptSha256=hashlib.sha256(raw).hexdigest(), allLogsAuthenticated=True, sourceOnly=True)))
