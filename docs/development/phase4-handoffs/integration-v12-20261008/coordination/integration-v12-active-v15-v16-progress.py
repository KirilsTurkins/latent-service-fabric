import json
from pathlib import Path
base = Path("/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data/jobs")
for job in ("integration-v12-current-java-real-node-v15", "integration-v12-pr823-current-main-source-v16"):
    path = base / job / "progress.json"
    if path.exists():
        value = json.loads(path.read_bytes())
        print(json.dumps(dict(job=job, head=value["head"], steps=[dict(index=i+1, exitCode=row["exitCode"], seconds=row["elapsedSeconds"], log=row["log"]) for i,row in enumerate(value["steps"])])))
    else:
        print(json.dumps(dict(job=job, noCompletedStepYet=True)))
