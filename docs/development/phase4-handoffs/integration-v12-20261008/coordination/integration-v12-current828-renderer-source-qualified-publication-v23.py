from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

coord = Path(__file__).resolve().parent
root = Path(r"C:\Users\turkins\Desktop\lf-p4-pr828-current-renderer-contracts-v23")
repo = "KirilsTurkins/latent-service-fabric"
head = "756a492b1678dec5e4f69dac11c571acc3836dd1"
expected = "912701092b03c97d6ce92e5bbac8a9f9a2f5fc68"
branch = "feat/phase4-http-409"
env = dict(os.environ, GODEBUG="http2client=0")
def git(*args):
    return subprocess.check_output(["git", "-C", str(root), *args], env=env).decode().strip()
def gh(*args):
    return subprocess.check_output(["gh", *args], env=env)
assert git("rev-parse", "HEAD") == head and not git("status", "--porcelain")
assert git("diff", "--name-only", expected, head).splitlines() == ["crates/latent-rpc/src/phase4/tests.rs", "website/lib/navigation.mjs"]
subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", expected, head], check=True, env=env)
path = coord / "integration-v12-current828-renderer-source-v23/receipt.json"
raw = path.read_bytes()
receipt = json.loads(raw)
assert receipt["head"] == head and receipt["passed"] and receipt["sourceClean"]
assert receipt["sourceHeadUnchanged"] and receipt["originalProcessReaped"] and receipt["infrastructureError"] is None
for row in receipt["steps"]:
    data = (path.parent / row["log"]).read_bytes()
    assert row["exitCode"] == 0 and row["stopReason"] is None and row["originalProcessReaped"]
    assert hashlib.sha256(data).hexdigest() == row["sha256"] and len(data) == row["bytes"]
rpc = json.loads((coord / "integration-v12-union-review/current828-rpc-duplicate-custody-v23/review.json").read_bytes())
assert rpc["allFloorCaseAssertionBytesEqual"] and rpc["allOriginalUniqueFunctionNamesRetained"]
nav = json.loads((coord / "integration-v12-union-review/current828-guide-pure-proof-v23.json").read_bytes())
assert nav["sameOriginalFailedCaseInputsAndAssertions"] and nav["allSevenPageIdsUniqueAndRetained"]
body = (coord / "integration-v12-union-review/pr828-current21c-qualified-body-v16.md").read_text(encoding="utf8")
body += "\nCurrent completed renderer build failures are repaired by retaining the existing current typed floor-release helper and both reviewed cases once. The stale duplicate copies had identical assertions; every unique case name,27-case inventory and floor remains. The transactional authoring guide is restored to Learn, with all six compiler references retained. The exact new head passes all seven Linux Source gates/SDK13/locked NodeRPC31.1 and the original pure guide inputs/assertions through the actual navigation function. Current RPC compiled27-case suite, full website132-case suite and fresh hosted CI remain pending; the separate original Go control29 clock-lease refusal is still under investigation. No production clock, grant or transaction behavior is changed.\n"
body_path = coord / "integration-v12-union-review/pr828-current-renderer-source-qualified-body-v23.md"
body_path.write_text(body, encoding="utf8", newline="\n")
live = json.loads(gh("api", "repos/" + repo + "/pulls/828"))
assert live["state"] == "open" and live["head"]["ref"] == branch and live["head"]["sha"] == expected
assert git("ls-remote", "origin", "refs/heads/" + branch).split()[0] == expected
subprocess.run(["git", "-C", str(root), "push", "origin", "HEAD:refs/heads/" + branch], env=env, check=True)
assert git("ls-remote", "origin", "refs/heads/" + branch).split()[0] == head
gh("pr", "edit", "828", "--repo", repo, "--body-file", str(body_path))
record = dict(at=datetime.now(timezone.utc).isoformat(), pr=828, oldHead=expected, newHead=head,
    normalPush=True, remoteVerified=True, sourceReceiptSha256=hashlib.sha256(raw).hexdigest(),
    fullRpcNativeAndWebsitePending=True, fullCI=False, issueClosed=False, worktreeDeleted=False)
(coord / "integration-v12-union-review/pr828-renderer-source-qualified-publication-v23.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf8")
print(json.dumps(record))
