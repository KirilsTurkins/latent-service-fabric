"""Audit the released Source checkout and prepare the exact additive oracle run."""
import hashlib
import json
from pathlib import Path
import subprocess

coord = Path(__file__).resolve().parent
job = "entity-postinspection-staging-source-20261008-v2"
prior_head = "e9a054503aed62c4549d965301d6a4a84dd1a117"
head = "0feb8019a283475f516d63b69e595294f215e095"
raw = (coord / job / "receipt.json").read_bytes()
prior = json.loads(raw)
assert hashlib.sha256(raw).hexdigest() == "8400fb4b1bf6907317369a87ef5128bb4d4780e1e909c1e551c66e5c5afb3b34"
assert prior["head"] == prior_head and prior["passed"]
assert prior["sourceClean"] and prior["sourceHeadUnchanged"] and prior["originalProcessReaped"]
assert prior["infrastructureError"] is None and len(prior["steps"]) == 7
for row in prior["steps"]:
    data = (coord / job / row["log"]).read_bytes()
    assert row["exitCode"] == 0 and row["stopReason"] is None and row["originalProcessReaped"]
    assert hashlib.sha256(data).hexdigest() == row["sha256"] and len(data) == row["bytes"]
worktree = Path(r"C:\Users\turkins\Desktop\lf-p4-current-java-scoped-actor-v15")
assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=worktree).decode().strip() == head
assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=worktree).strip()
steps = json.loads((coord / job / "invocation.json").read_bytes())["steps"]
needle = "'tools.tests.test_java_resource_diagnostics']"
assert steps[0][-1].count(needle) == 1
steps[0][-1] = steps[0][-1].replace(needle, "'tools.tests.test_java_resource_diagnostics', 'tools.tests.test_java_transaction_actor']")
steps[3][-1] = "target/ci/observed-scoped-actor-v15-linux.json"
step_path = coord / "integration-v12-scoped-actor-source-steps-v15.json"
step_path.write_text(json.dumps(steps, indent=2) + "\n", encoding="utf8")
controller = (coord / "entity-contract-v73-reused-signing-source-controller.py").read_text(encoding="utf8")
controller = controller.replace("integration-v12-current828-developmentc844-source-v10", job)
controller = controller.replace("7bc6e42254ef94c2b0248ad174d1e959aefc10e2", prior_head)
controller_path = coord / "integration-v12-scoped-actor-reused-source-controller-v15.py"
compile(controller, str(controller_path), "exec")
controller_path.write_text(controller, encoding="utf8", newline="\n")
proof = dict(head=head, priorHead=prior_head, priorReceiptSha256=hashlib.sha256(raw).hexdigest(),
    sevenLogsAuthenticated=True, originalBoundsAndAllPriorModulesRetained=True,
    sourceOnly=True, checkout=prior["checkout"], controller=str(controller_path), steps=str(step_path))
(coord / "integration-v12-union-review/scoped-actor-source-preflight-v15.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
print(json.dumps(proof))
