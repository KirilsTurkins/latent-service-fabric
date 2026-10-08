import json
import os
from pathlib import Path
import subprocess

coord = Path(__file__).resolve().parent
repo = "KirilsTurkins/latent-service-fabric"
head = "3b7af5096198ae9453b5616bc124def18798911c"
env = dict(os.environ, GODEBUG="http2client=0")
proof = json.loads((coord / "integration-v12-union-review/pr823-actual-dotnet-host-qualified-proof-v16.json").read_bytes())
assert proof["head"] == head and proof["allSixOriginalCommandsPass"] and proof["allProcessesReaped"]
live = json.loads(subprocess.check_output(["gh", "api", "repos/" + repo + "/pulls/823"], env=env))
assert live["state"] == "open" and live["head"]["sha"] == head
body = (coord / "integration-v12-union-review/pr823-current21c-qualified-body-v16.md").read_text(encoding="utf8")
old = "Focused current .NET runtime tests and authoritative full Linux SDK/hosted CI remain pending; historical Native receipts keep their actual heads."
new = "The exact current Windows .NET8.0.425/runtime8.0.31 locked test run passes61 protobuf cases,13 transport scenarios/569 checks and77 semantic records/lifetime checks, retaining all57 source hashes and original bounds. Authoritative full Linux SDK/hosted CI remain pending; historical Native receipts keep their actual heads."
assert body.count(old) == 1
body = body.replace(old, new)
path = coord / "integration-v12-union-review/pr823-current21c-sdk-qualified-body-v16.md"
path.write_text(body, encoding="utf8", newline="\n")
subprocess.run(["gh", "pr", "edit", "823", "--repo", repo, "--body-file", str(path)], env=env, check=True)
print(json.dumps(dict(pr=823, head=head, bodyUpdated=True, noCodeOrCiHeadChange=True, fullCI=False)))
