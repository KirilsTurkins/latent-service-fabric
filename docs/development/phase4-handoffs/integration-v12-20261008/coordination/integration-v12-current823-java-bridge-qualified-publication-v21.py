from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

coord = Path(__file__).resolve().parent
root = Path(r"C:\Users\turkins\Desktop\lf-p4-pr823-java-current-bridge-v21")
repo = "KirilsTurkins/latent-service-fabric"
head = "76307dbbe24b51fb8b1316c4fbf7047914759a51"
expected = "3b7af5096198ae9453b5616bc124def18798911c"
branch = "feat/phase4-state-runtime-718"
env = dict(os.environ, GODEBUG="http2client=0")
def git(*args):
    return subprocess.check_output(["git", "-C", str(root), *args], env=env).decode().strip()
def gh(*args):
    return subprocess.check_output(["gh", *args], env=env)
assert git("rev-parse", "HEAD") == head and not git("status", "--porcelain")
assert git("diff", "--name-only", expected, head) == "sdk/java-client/src/transport/java/dev/latent/sdk/transport/Wire.java"
subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", expected, head], env=env, check=True)
path = coord / "integration-v12-current823-java-bridge-source-v21/receipt.json"
raw = path.read_bytes()
receipt = json.loads(raw)
assert receipt["head"] == head and receipt["passed"] and receipt["sourceClean"]
assert receipt["sourceHeadUnchanged"] and receipt["originalProcessReaped"] and receipt["infrastructureError"] is None
for row in receipt["steps"]:
    data = (path.parent / row["log"]).read_bytes()
    assert row["exitCode"] == 0 and row["stopReason"] is None and row["originalProcessReaped"]
    assert hashlib.sha256(data).hexdigest() == row["sha256"] and len(data) == row["bytes"]
preservation = json.loads((coord / "integration-v12-union-review/current823-java-bridge-preservation-v21.json").read_bytes())
assert preservation["head"] == head and preservation["allOtherOriginalMethodBytesUnchanged"]
assert preservation["allOriginalFixturesByteUnchanged"] and preservation["originalJavaCodecSuccess60AndRefusal1OracleUnchanged"]
body = (coord / "integration-v12-union-review/pr823-current21c-sdk-qualified-body-v16.md").read_text(encoding="utf8")
body += "\nThe current completed Java CI prepareTransport failure is repaired by the maintained bridge producer: optional transactionStaging and all10 witness fields map in both directions. Only this generated bridge file changes; all other mapping methods,77 fixtures and the original60-success/one-contradictory Java codec oracle remain. The exact new head passes all seven Linux Source gates, SDK13, locked NodeRPC31.1 and JavaBridge generation checks. Current Java Gradle540 execution and full hosted CI remain pending; prior runtime/.NET receipts keep their actual source heads.\n"
body_path = coord / "integration-v12-union-review/pr823-current-java-bridge-source-qualified-body-v21.md"
body_path.write_text(body, encoding="utf8", newline="\n")
live = json.loads(gh("api", "repos/" + repo + "/pulls/823"))
assert live["state"] == "open" and live["head"]["ref"] == branch and live["head"]["sha"] == expected
assert git("ls-remote", "origin", "refs/heads/" + branch).split()[0] == expected
subprocess.run(["git", "-C", str(root), "push", "origin", "HEAD:refs/heads/" + branch], env=env, check=True)
assert git("ls-remote", "origin", "refs/heads/" + branch).split()[0] == head
gh("pr", "edit", "823", "--repo", repo, "--body-file", str(body_path))
record = dict(at=datetime.now(timezone.utc).isoformat(), pr=823, oldHead=expected, newHead=head,
    normalPush=True, remoteVerified=True, sourceReceiptSha256=hashlib.sha256(raw).hexdigest(),
    actualJavaGradlePending=True, fullCI=False, issueClosed=False, worktreeDeleted=False)
(coord / "integration-v12-union-review/pr823-java-bridge-source-qualified-publication-v21.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf8")
print(json.dumps(record))
