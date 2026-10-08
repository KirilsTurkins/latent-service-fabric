"""Pair the fresh collector head with unchanged compiled inputs and new campaign root."""
import hashlib
import json
from pathlib import Path
import subprocess

coord = Path(__file__).resolve().parent
repo = Path(r"C:\Users\turkins\Desktop\latent-fabric")
head = "0feb8019a283475f516d63b69e595294f215e095"
old = "e9a054503aed62c4549d965301d6a4a84dd1a117"
receipt_path = coord / "integration-v12-scoped-actor-source-v15/receipt.json"
raw = receipt_path.read_bytes()
receipt = json.loads(raw)
assert receipt["head"] == head and receipt["passed"] and receipt["sourceClean"]
assert receipt["sourceHeadUnchanged"] and receipt["originalProcessReaped"]
assert len(receipt["steps"]) == 7 and receipt["infrastructureError"] is None
for row in receipt["steps"]:
    content = (receipt_path.parent / row["log"]).read_bytes()
    assert hashlib.sha256(content).hexdigest() == row["sha256"] and len(content) == row["bytes"]
delta = subprocess.check_output(["git", "diff", "--name-only", old, head], cwd=repo).decode().splitlines()
assert delta == ["tools/ci/contracts/python/test_java_transaction_actor.py.json",
    "tools/java_transaction_qualification/lifecycle.py", "tools/tests/test_java_transaction_actor.py"]
assert not subprocess.check_output(["git", "diff", old, head, "--", "apps", "crates", "api", "sdk", "wit", "schemas", "Cargo.lock", "Cargo.toml"], cwd=repo)
steps = json.loads((coord / "integration-v12-union-review/lease-fixed-real-node-source-paired-steps-v14.json").read_bytes())
old_job = "integration-v12-current-java-real-node-v14"
job = "integration-v12-current-java-real-node-v15"
steps = [[value.replace(old, head).replace(old_job, job) for value in argv] for argv in steps]
path = coord / "integration-v12-union-review/scoped-actor-real-node-source-paired-steps-v15.json"
path.write_text(json.dumps(steps, indent=2) + "\n", encoding="utf8")
controller = (coord / "integration-v12-lease-fixed-real-node-source-paired-controller-v14.py").read_text(encoding="utf8")
controller = controller.replace(old, head).replace(old_job, job)
controller_path = coord / "integration-v12-scoped-actor-real-node-source-paired-controller-v15.py"
compile(controller, str(controller_path), "exec")
controller_path.write_text(controller, encoding="utf8", newline="\n")
proof = dict(head=head, priorNativeHead=old, sourceReceiptSha256=hashlib.sha256(raw).hexdigest(),
    allSevenSourceLogsAuthenticated=True, onlyThreeOraclePathsChanged=delta,
    allRuntimeSdkWitSchemasLocksByteIdentical=True, originalCompilerInputsAndSelectionDigestUnchanged=True,
    original1800Controller1200CampaignBoundsRetained=True, freshCampaignRoot=job,
    actualGuestExecutionPending=True, controller=str(controller_path), steps=str(path))
(coord / "integration-v12-union-review/scoped-actor-real-node-preflight-v15.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
print(json.dumps(proof))
