import json
from pathlib import Path
import subprocess

coord = Path(__file__).resolve().parent
repo = Path(r"C:\Users\turkins\Desktop\latent-fabric")
head = "6d09d6095e8ada217a51b5f878e48aba62e03abf"
old = "528b2f59246855e3f3e23682d49b1fcd30940ad7"
assert not subprocess.check_output(["git", "diff", old, head, "--", "apps", "crates", "api", "sdk", "wit", "schemas", "Cargo.lock", "Cargo.toml"], cwd=repo)
steps = json.loads((coord / "integration-v12-union-review/approved-origin-real-node-source-paired-steps-v19.json").read_bytes())
job = "integration-v12-current-java-real-node-v20"
steps = [[value.replace(old, head).replace("integration-v12-current-java-real-node-v19", job) for value in argv] for argv in steps]
path = coord / "integration-v12-union-review/unavailable-observer-real-node-source-paired-steps-v20.json"
path.write_text(json.dumps(steps, indent=2) + "\n", encoding="utf8")
controller = (coord / "integration-v12-approved-origin-real-node-source-paired-controller-v19.py").read_text(encoding="utf8")
controller = controller.replace(old, head).replace("integration-v12-current-java-real-node-v19", job)
path = coord / "integration-v12-unavailable-observer-real-node-source-paired-controller-v20.py"
compile(controller, str(path), "exec")
path.write_text(controller, encoding="utf8", newline="\n")
print(json.dumps(dict(head=head, exactRuntimeApiSdkCompilerInputsUnchanged=True,
    originalHeaderOracleRetained=True, oneFiniteReadOnly503Observation=True,
    originalBoundsRetained=True, sourceAndNativePending=True, heldForDiskMargin=True)))
