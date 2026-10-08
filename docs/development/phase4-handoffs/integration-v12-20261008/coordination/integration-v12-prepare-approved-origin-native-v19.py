import json
from pathlib import Path
import subprocess

coord = Path(__file__).resolve().parent
repo = Path(r"C:\Users\turkins\Desktop\latent-fabric")
head = "528b2f59246855e3f3e23682d49b1fcd30940ad7"
old = "027315a4bda3cc9d6b921d671b2756f3edee25b0"
native_delta = subprocess.check_output(["git", "diff", "--name-only", old, head, "--",
    "apps", "crates", "api", "sdk", "wit", "schemas", "Cargo.lock", "Cargo.toml"], cwd=repo).decode().splitlines()
assert native_delta == ["sdk/dotnet/protobuf.lock.json"]
steps = json.loads((coord / "integration-v12-union-review/query-refusal-real-node-source-paired-steps-v17.json").read_bytes())
job = "integration-v12-current-java-real-node-v19"
steps = [[part.replace(old, head).replace("integration-v12-current-java-real-node-v17", job) for part in argv] for argv in steps]
path = coord / "integration-v12-union-review/approved-origin-real-node-source-paired-steps-v19.json"
path.write_text(json.dumps(steps, indent=2) + "\n", encoding="utf8")
controller = (coord / "integration-v12-query-refusal-real-node-source-paired-controller-v17.py").read_text(encoding="utf8")
controller = controller.replace(old, head).replace("integration-v12-current-java-real-node-v17", job)
path = coord / "integration-v12-approved-origin-real-node-source-paired-controller-v19.py"
compile(controller, str(path), "exec")
path.write_text(controller, encoding="utf8", newline="\n")
print(json.dumps(dict(head=head, rustApiWitSchemasCargoByteIdentical=True,
    originalSixJavaCompilerInputsUnchanged=True, exactOriginConfigOnly=True,
    dotnetLockCurrentProducerDerived=True, originalBoundsRetained=True,
    actualSourceNativePending=True, heldForDiskMargin=True)))
