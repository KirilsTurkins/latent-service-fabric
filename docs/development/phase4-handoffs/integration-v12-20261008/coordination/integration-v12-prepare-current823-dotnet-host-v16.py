"""Capture exact current SDK inputs and retain the original bounded host recipe."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

repo = Path(r"C:\Users\turkins\Desktop\latent-fabric")
coord = Path(__file__).resolve().parent
head = "3b7af5096198ae9453b5616bc124def18798911c"
out = coord / "integration-v12-current823-dotnet-host-v16"
assert not out.exists()
source = out / "source"
source.mkdir(parents=True)
listed = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", head,
    "sdk/dotnet", "api/proto", "sdk/profile"], cwd=repo).decode().splitlines()
projects = {"Latent.Sdk", "Latent.Sdk.SemanticTests", "Latent.Sdk.Transport", "Latent.Sdk.Transport.Tests", "Latent.Sdk.ProviderWorkflow"}
selected = []
for name in listed:
    parts = Path(name).parts
    if name in ("sdk/dotnet/global.json", "sdk/dotnet/nuget.transport.config", "sdk/profile/fixtures.json"):
        selected.append(name)
    elif name.startswith("api/proto/") and name.endswith(".proto"):
        selected.append(name)
    elif len(parts) > 3 and parts[:2] == ("sdk", "dotnet") and parts[2] in projects and (
        Path(name).suffix in (".cs", ".csproj") or parts[-1] == "packages.lock.json"):
        selected.append(name)
assert 50 <= len(selected) <= 128
records = []
for name in selected:
    raw = subprocess.check_output(["git", "show", head + ":" + name], cwd=repo)
    assert len(raw) <= 2 * 1024 ** 2
    target = source / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    records.append(dict(path=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
proof = dict(at=datetime.now(timezone.utc).isoformat(), head=head, files=records, fileCount=len(records),
    source=str(source), exactTrackedSourceBytes=True, pinnedSDK="8.0.425", pinnedRuntime="8.0.31",
    originalProtobufCaseCount=61, windowsFocusedValidationPending=True, authoritativeLinuxQualification=False)
(out / "source-receipt.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
controller = (coord / "portable-v2-pr800-dotnet-current-host-controller-v221.py").read_text(encoding="utf8")
controller = controller.replace("portable-v2-pr800-dotnet-current-native-v220", out.name)
controller = controller.replace("0055f9778e0d4ee2ace92dfdafabfd3e8ad57b7c", head)
controller = controller.replace("sourceAll64HashesUnchanged=True", "sourceAllHashesUnchanged=True")
path = coord / "integration-v12-current823-dotnet-host-controller-v16.py"
compile(controller, str(path), "exec")
path.write_text(controller, encoding="utf8", newline="\n")
print(json.dumps(dict(head=head, fileCount=len(records), source=str(source), controller=str(path), actualExecutionPending=True)))
