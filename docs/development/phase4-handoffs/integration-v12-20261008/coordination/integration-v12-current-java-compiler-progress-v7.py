from pathlib import Path
import json

root=Path('/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data/jobs/integration-v12-current-java-six-compiler-v7')
rows=[]
for path in [*root.glob('results/*/report.json'),*root.glob('diagnostic/*/report.json')]:
    value=json.loads(path.read_text())
    rows.append({key:value.get(key) for key in ('variant','status','compiled','sourceRevision','componentDigest','componentBytes','workingTreeChanged','reason')})
print(json.dumps(rows))
