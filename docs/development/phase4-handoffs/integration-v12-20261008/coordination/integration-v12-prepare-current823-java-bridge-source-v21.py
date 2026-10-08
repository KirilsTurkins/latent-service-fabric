import hashlib
import json
from pathlib import Path

coord = Path(__file__).resolve().parent
prior_job = "integration-v12-unavailable-observer-source-v20"
prior_head = "6d09d6095e8ada217a51b5f878e48aba62e03abf"
head = "76307dbbe24b51fb8b1316c4fbf7047914759a51"
raw = (coord / prior_job / "receipt.json").read_bytes()
assert hashlib.sha256(raw).hexdigest() == "2e7d216746b29a9225d8ab7ccd68f6b8472a5a29f55b1110b78c00d1d4c03e50"
receipt = json.loads(raw)
assert receipt["head"] == prior_head and receipt["passed"] and receipt["sourceClean"]
assert receipt["sourceHeadUnchanged"] and receipt["originalProcessReaped"] and receipt["infrastructureError"] is None
for row in receipt["steps"]:
    data = (coord / prior_job / row["log"]).read_bytes()
    assert row["exitCode"] == 0 and row["stopReason"] is None and row["originalProcessReaped"]
    assert hashlib.sha256(data).hexdigest() == row["sha256"] and len(data) == row["bytes"]
steps = json.loads((coord / "integration-v12-pr823-current-main-source-v16/invocation.json").read_bytes())["steps"]
steps[3][-1] = "target/ci/observed-current823-java-bridge-v21-linux.json"
steps[-1][-1] += "; subprocess.run(['python3','-X','utf8','-B','sdk/java-client/tools/generate_bridge.py','--check'],check=True)"
path = coord / "integration-v12-current823-java-bridge-source-steps-v21.json"
path.write_text(json.dumps(steps, indent=2) + "\n", encoding="utf8")
controller = (coord / "entity-contract-v73-reused-signing-source-controller.py").read_text(encoding="utf8")
controller = controller.replace("integration-v12-current828-developmentc844-source-v10", prior_job)
controller = controller.replace("7bc6e42254ef94c2b0248ad174d1e959aefc10e2", prior_head)
needle = "assert previous['head'] == '" + prior_head + "'"
controller = controller.replace(needle, needle + "\n    assert hashlib.sha256((prior / 'receipt.json').read_bytes()).hexdigest() == '" + hashlib.sha256(raw).hexdigest() + "'")
path = coord / "integration-v12-current823-java-bridge-reused-source-controller-v21.py"
compile(controller, str(path), "exec")
path.write_text(controller, encoding="utf8", newline="\n")
print(json.dumps(dict(head=head, priorHead=prior_head, allSevenPriorLogsAuthenticated=True,
    originalBranchModulesAndLimitsRetained=True, actualJavaBridgeAndLockedRpcChecksAdded=True, sourceOnly=True)))
