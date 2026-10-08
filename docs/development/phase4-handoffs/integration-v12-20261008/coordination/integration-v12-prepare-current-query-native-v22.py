import hashlib
import json
from pathlib import Path
import subprocess

coord = Path(__file__).resolve().parent
repo = Path(r"C:\Users\turkins\Desktop\latent-fabric")
head = "98281c17e28f9dd1dd6e9f0058069d71422df11e"
old = "6d09d6095e8ada217a51b5f878e48aba62e03abf"
job = coord / "integration-v12-current-collector-java-source-v22"
raw = (job / "receipt.json").read_bytes()
receipt = json.loads(raw)
assert receipt["head"] == head and receipt["passed"] and receipt["sourceClean"]
assert receipt["sourceHeadUnchanged"] and receipt["originalProcessReaped"] and receipt["infrastructureError"] is None
for row in receipt["steps"]:
    data = (job / row["log"]).read_bytes()
    assert row["exitCode"] == 0 and row["stopReason"] is None and row["originalProcessReaped"]
    assert hashlib.sha256(data).hexdigest() == row["sha256"] and len(data) == row["bytes"]
assert subprocess.check_output(["git", "diff", "--name-only", old, head], cwd=repo).decode().splitlines() == ["sdk/java-client/src/transport/java/dev/latent/sdk/transport/Wire.java"]
steps = json.loads((coord / "integration-v12-union-review/unavailable-observer-real-node-source-paired-steps-v20.json").read_bytes())
new_job = "integration-v12-current-java-real-node-v22"
steps = [[value.replace(old, head).replace("integration-v12-current-java-real-node-v20", new_job) for value in argv] for argv in steps]
path = coord / "integration-v12-union-review/current-query-real-node-source-paired-steps-v22.json"
path.write_text(json.dumps(steps, indent=2) + "\n", encoding="utf8")
controller = (coord / "integration-v12-unavailable-observer-real-node-source-paired-controller-v20.py").read_text(encoding="utf8")
controller = controller.replace(old, head).replace("integration-v12-current-java-real-node-v20", new_job)
path = coord / "integration-v12-current-query-real-node-source-paired-controller-v22.py"
compile(controller, str(path), "exec")
path.write_text(controller, encoding="utf8", newline="\n")
proof = dict(head=head, sourceReceiptSha256=hashlib.sha256(raw).hexdigest(), allSevenRawLogsAuthenticated=True,
    oldUnexecutedRecipeAndReceiptsUnmodified=True, exactCurrentGeneratedJavaBridgeRetained=True,
    actualJavaCompilerInputsRustApiWitCargoByteUnchanged=True, originalBoundsAndFreshRootRetained=True,
    actualNativePending=True, heldForSafeDiskMargin=True)
(coord / "integration-v12-union-review/current-query-native-preflight-v22.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
print(json.dumps(proof))
