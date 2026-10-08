import hashlib
import json
from pathlib import Path

coord = Path(__file__).resolve().parent
raw = (coord / "integration-v12-current823-sdk-failure-v21/job.log").read_bytes()
assert hashlib.sha256(raw).hexdigest() == "cc5ba35e7818cb7d81fa2220fcab2e71ffdd4689310ec615430f0ac8a9f524d9"
assert b"Java bridge is stale; generate_bridge.py --patch" in raw
proof = dict(originalJob=113159527038, originalHead="3b7af5096198ae9453b5616bc124def18798911c",
    actualCause="maintained Java bridge generated output stale", rawLogSha256=hashlib.sha256(raw).hexdigest(),
    repairedHead="76307dbbe24b51fb8b1316c4fbf7047914759a51", actualGeneratorCheckPassed=True,
    actualSourceAllSevenGatesPassed=True, normalExistingPrPublicationVerified=True,
    currentGradleAndFullHostedCiPending=True, originalFailureReceiptUnchanged=True)
(coord / "integration-v12-union-review/current823-java-cause-reviewed-v24.json").write_text(json.dumps(proof,indent=2)+"\n",encoding="utf8")
print(json.dumps(proof))
