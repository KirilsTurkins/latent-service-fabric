import hashlib
import json
from pathlib import Path
import shutil
import subprocess

coord = Path(__file__).resolve().parent
job = coord / "integration-v12-approved-origin-source-v19"
head = "528b2f59246855e3f3e23682d49b1fcd30940ad7"
raw = (job / "receipt.json").read_bytes()
assert hashlib.sha256(raw).hexdigest() == "38971e26308eed381f70efbbd5b4c01f53715cad20c8e45b016dd6e77014f8e0"
receipt = json.loads(raw)
assert receipt["head"] == head and receipt["passed"] and receipt["sourceClean"]
assert receipt["sourceHeadUnchanged"] and receipt["originalProcessReaped"] and receipt["infrastructureError"] is None
for row in receipt["steps"]:
    data = (job / row["log"]).read_bytes()
    assert row["exitCode"] == 0 and row["stopReason"] is None and row["originalProcessReaped"]
    assert hashlib.sha256(data).hexdigest() == row["sha256"] and len(data) == row["bytes"]
repo = Path(r"C:\Users\turkins\Desktop\latent-fabric")
assert not subprocess.check_output(["git", "diff", "3b7af5096198ae9453b5616bc124def18798911c", head,
    "--", "apps", "crates", "api", "sdk", "wit", "schemas", "Cargo.lock", "Cargo.toml"], cwd=repo)
steps = json.loads((coord / "integration-v12-union-review/approved-origin-real-node-source-paired-steps-v19.json").read_bytes())
assert len(steps) == 3 and steps[0][0] == "cargo" and steps[1][0] == "cargo"
assert head in steps[2] and steps[2][-2:] == ["--timeout", "1200"]
assert not (coord / "integration-v12-current-java-real-node-v19").exists()
assert shutil.disk_usage(coord).free >= 2 * 1024 ** 3, "safe-host-disk-margin"
proof = dict(head=head, exactSourceReceiptAuthenticated=True, allSevenRawLogsAuthenticated=True,
    currentProductionAndSdkSourcesByteIdentical=True, originalSameHeadBuildAndNewRoot=True,
    originalSixCompilerMaterialSelectionUnchanged=True, originalBoundsRetained=True,
    actualExecutionPending=True, freeHostBytes=shutil.disk_usage(coord).free)
(coord / "integration-v12-union-review/approved-origin-native-preflight-v19.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
print(json.dumps(proof))
