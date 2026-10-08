import hashlib
import json
from pathlib import Path
import subprocess

coord = Path(__file__).resolve().parent
repo = Path(r"C:\Users\turkins\Desktop\latent-fabric")
head = "027315a4bda3cc9d6b921d671b2756f3edee25b0"
baseline = "0feb8019a283475f516d63b69e595294f215e095"
assert not subprocess.check_output(["git", "diff", baseline, head, "--", "apps", "crates", "api", "sdk", "wit", "schemas", "Cargo.lock", "Cargo.toml"], cwd=repo)
steps = json.loads((coord / "integration-v12-union-review/scoped-actor-real-node-source-paired-steps-v15.json").read_bytes())
job = "integration-v12-current-java-real-node-v17"
steps = [[value.replace(baseline, head).replace("integration-v12-current-java-real-node-v15", job) for value in argv] for argv in steps]
path = coord / "integration-v12-union-review/query-refusal-real-node-source-paired-steps-v17.json"
path.write_text(json.dumps(steps, indent=2) + "\n", encoding="utf8")
controller = (coord / "integration-v12-scoped-actor-real-node-source-paired-controller-v15.py").read_text(encoding="utf8")
controller = controller.replace(baseline, head).replace("integration-v12-current-java-real-node-v15", job)
path = coord / "integration-v12-query-refusal-real-node-source-paired-controller-v17.py"
compile(controller, str(path), "exec")
path.write_text(controller, encoding="utf8", newline="\n")
print(json.dumps(dict(head=head, originalNativeSourceByteIdentical=True,
    newReadOnlyObserverDoesNotChangeFailureOrGrants=True, freshRoot=job, sourceAndNativePending=True)))
