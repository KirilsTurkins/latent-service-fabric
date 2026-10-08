import hashlib
import json
from pathlib import Path

coord = Path(__file__).resolve().parent
job = "integration-v12-pr823-current-main-source-v16"
head = "3b7af5096198ae9453b5616bc124def18798911c"
raw = (coord / job / "receipt.json").read_bytes()
receipt = json.loads(raw)
assert receipt["head"] == head and receipt["passed"] and receipt["sourceClean"]
assert receipt["sourceHeadUnchanged"] and receipt["originalProcessReaped"] and receipt["infrastructureError"] is None
for row in receipt["steps"]:
    data = (coord / job / row["log"]).read_bytes()
    assert row["exitCode"] == 0 and row["stopReason"] is None and row["originalProcessReaped"]
    assert hashlib.sha256(data).hexdigest() == row["sha256"] and len(data) == row["bytes"]
source = (coord / "integration-v12-current-main-reused-source-controller-v16.py").read_text(encoding="utf8")
source = source.replace("portable-v2-pr828-final-main-source-20261008-v264", job)
source = source.replace("8fe134c08c0535e2eddf9cac7579fcdbacca90af", head)
source = source.replace("39b0e37c045ff71c7ddc1b42fe8fa8c5b79c36957808a0c1164bbd1cdac65a08", hashlib.sha256(raw).hexdigest())
path = coord / "integration-v12-current828-reused-source-controller-v16.py"
compile(source, str(path), "exec")
path.write_text(source, encoding="utf8", newline="\n")
print(json.dumps(dict(priorHead=head, priorReceiptSha256=hashlib.sha256(raw).hexdigest(), allLogsAuthenticated=True, sourceOnly=True)))
