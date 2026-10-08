import json
from pathlib import Path

coord = Path(__file__).resolve().parent
job = coord / "integration-v12-current-java-real-node-v19"
path = job / "campaign/campaign-receipt.json"
if not path.exists():
    print(json.dumps(dict(job=job.name, complete=False)))
else:
    result = json.loads(path.read_bytes())
    print(json.dumps({key:result.get(key) for key in (
        "passed", "nativeSourceCommit", "signedGuestExecutionQualified", "failedStage",
        "failureType", "fixedFailureReason", "cliProcesses", "seconds", "measuredCases")}))
