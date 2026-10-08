"""Publish only an exact existing PR descendant with authenticated current Source proof."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

coord = Path(__file__).resolve().parent
tag = sys.argv[1]
settings = {
    "pr823": (823, "lf-p4-current-java-bd4-union-v12", "feat/phase4-state-runtime-718",
        "0a783d97762f763ca6ab237d4bb36eb306bbddec", "3b7af5096198ae9453b5616bc124def18798911c"),
    "pr828": (828, "lf-p4-pr828-current-java-union-v12", "feat/phase4-http-409",
        "0a637ba7844c7fe461873d0fa783bca8166f4971", "912701092b03c97d6ce92e5bbac8a9f9a2f5fc68"),
}
number, directory, branch, expected, head = settings[tag]
root = Path(r"C:\Users\turkins\Desktop") / directory
repo = "KirilsTurkins/latent-service-fabric"
env = dict(os.environ, GODEBUG="http2client=0")
def git(*args):
    return subprocess.check_output(["git", "-C", str(root), *args], env=env).decode().strip()
def gh(*args):
    return subprocess.check_output(["gh", *args], env=env)
assert git("rev-parse", "HEAD") == head and not git("status", "--porcelain")
subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", expected, head], check=True, env=env)
subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", "21cfd22148f849604cb6fc60247924de0012093c", head], check=True, env=env)
path = coord / ("integration-v12-" + tag + "-current-main-source-v16") / "receipt.json"
raw = path.read_bytes()
receipt = json.loads(raw)
assert receipt["head"] == head and receipt["passed"] and receipt["sourceClean"]
assert receipt["sourceHeadUnchanged"] and receipt["originalProcessReaped"] and receipt["infrastructureError"] is None
assert len(receipt["steps"]) == 7
for row in receipt["steps"]:
    data = (path.parent / row["log"]).read_bytes()
    assert row["exitCode"] == 0 and row["stopReason"] is None and row["originalProcessReaped"]
    assert hashlib.sha256(data).hexdigest() == row["sha256"] and len(data) == row["bytes"]
if tag == "pr823":
    review = json.loads((coord / "integration-v12-union-review/pr823-actual-dotnet-lock-adoption-review.json").read_bytes())
    actual_lock = subprocess.check_output(["git", "-C", str(root), "show", head + ":sdk/dotnet/protobuf.lock.json"])
    assert hashlib.sha256(actual_lock).hexdigest() == review["newLockSha256"]
    assert review["actualPinnedLinuxGrpcToolsReproducedTwice"] and review["allSixProtoInputsAndExactProjectOptionsByteIdentical"]
original = (coord / ("integration-v12-union-review/" + tag + "-current-fd-qualified-body.md")).read_text(encoding="utf8")
body = original.replace("`development` fd4623ac", "`development` 21cfd221")
body += "\nBoth maintained route collectors are retained on the same single request: the bounded closed status observer and the current rejected-delete receipt summary. The exact new head passes all seven Linux Source gates, including the locked libprotoc31.1 Node descriptor check; all inherited cases and guards remain.\n"
if tag == "pr823":
    body += "\nThe .NET input/output lock is derived from two actual pinned Linux Grpc.Tools2.71 code generations. This branch has77 fixtures and61 selected protobuf cases, so its original61-case oracle remains. Focused current .NET runtime tests and authoritative full Linux SDK/hosted CI remain pending; historical Native receipts keep their actual heads.\n"
body_path = coord / ("integration-v12-union-review/" + tag + "-current21c-qualified-body-v16.md")
body_path.write_text(body, encoding="utf8", newline="\n")
live = json.loads(gh("api", f"repos/{repo}/pulls/{number}"))
assert live["state"] == "open" and live["head"]["ref"] == branch and live["head"]["sha"] == expected
assert git("ls-remote", "origin", "refs/heads/" + branch).split()[0] == expected
subprocess.run(["git", "-C", str(root), "push", "origin", "HEAD:refs/heads/" + branch], check=True, env=env)
assert git("ls-remote", "origin", "refs/heads/" + branch).split()[0] == head
gh("pr", "edit", str(number), "--repo", repo, "--body-file", str(body_path))
record = dict(at=datetime.now(timezone.utc).isoformat(), pr=number, oldHead=expected, newHead=head,
    normalPush=True, remoteVerified=True, sourceReceiptSha256=hashlib.sha256(raw).hexdigest(),
    fullCI=False, issueClosed=False, worktreeDeleted=False)
(coord / ("integration-v12-union-review/" + tag + "-current21c-publication-v16.json")).write_text(json.dumps(record, indent=2) + "\n", encoding="utf8")
print(json.dumps(record))
