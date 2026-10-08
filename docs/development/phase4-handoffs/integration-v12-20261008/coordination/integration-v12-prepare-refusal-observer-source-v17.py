import hashlib
import json
from pathlib import Path

coord = Path(__file__).resolve().parent
job = "entity-offline-helper-actor-21c-source-20261008-v1"
prior_head = "a458d7a6c69a3122f4317d566be4d5ff672278a0"
head = "027315a4bda3cc9d6b921d671b2756f3edee25b0"
raw = (coord / job / "receipt.json").read_bytes()
assert hashlib.sha256(raw).hexdigest() == "448bc97ea3252938d3f67166abb2fafd41c819396a1218af4dfe154c48882959"
receipt = json.loads(raw)
assert receipt["head"] == prior_head and receipt["passed"] and receipt["sourceClean"]
assert receipt["sourceHeadUnchanged"] and receipt["originalProcessReaped"] and receipt["infrastructureError"] is None
for row in receipt["steps"]:
    data = (coord / job / row["log"]).read_bytes()
    assert row["exitCode"] == 0 and row["stopReason"] is None and row["originalProcessReaped"]
    assert hashlib.sha256(data).hexdigest() == row["sha256"] and len(data) == row["bytes"]
steps = json.loads((coord / job / "invocation.json").read_bytes())["steps"]
needle = "'tools.tests.test_java_transaction_actor']"
assert steps[0][-1].count(needle) == 1
steps[0][-1] = steps[0][-1].replace(needle, "'tools.tests.test_java_transaction_actor', 'tools.tests.test_java_transaction_refusal_observation']")
steps[3][-1] = "target/ci/observed-query-refusal-v17-linux.json"
path = coord / "integration-v12-query-refusal-source-steps-v17.json"
path.write_text(json.dumps(steps, indent=2) + "\n", encoding="utf8")
controller = (coord / "entity-contract-v73-reused-signing-source-controller.py").read_text(encoding="utf8")
controller = controller.replace("integration-v12-current828-developmentc844-source-v10", job)
controller = controller.replace("7bc6e42254ef94c2b0248ad174d1e959aefc10e2", prior_head)
needle = "assert previous['head'] == '" + prior_head + "'"
assert controller.count(needle) == 1
controller = controller.replace(needle, needle + "\n    assert hashlib.sha256((prior / 'receipt.json').read_bytes()).hexdigest() == '" + hashlib.sha256(raw).hexdigest() + "'")
path = coord / "integration-v12-query-refusal-reused-source-controller-v17.py"
compile(controller, str(path), "exec")
path.write_text(controller, encoding="utf8", newline="\n")
print(json.dumps(dict(head=head, priorHead=prior_head, priorReceiptSha256=hashlib.sha256(raw).hexdigest(), allLogsAuthenticated=True, sourceOnly=True)))
