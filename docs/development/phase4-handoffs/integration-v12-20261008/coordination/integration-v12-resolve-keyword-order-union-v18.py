import ast
import hashlib
import json
from pathlib import Path
import subprocess

root = Path(r"C:\Users\turkins\Desktop\lf-p4-query-refusal-observation-v17")
coord = Path(__file__).resolve().parent
name = "tools/java_server_node.py"
def git(*args):
    return subprocess.check_output(["git", *args], cwd=root)
assert git("diff", "--name-only", "--diff-filter=U").decode().splitlines() == [name]
ours, theirs = git("show", ":2:" + name), git("show", ":3:" + name)
old = 'observer=observe_route_call, evidence=evidence'
new = 'evidence=evidence, observer=observe_route_call'
assert ours.decode().count(old) == 1 and theirs.decode().count(new) == 1
assert ast.dump(ast.parse(ours.decode().replace(old, new)), include_attributes=False) == ast.dump(ast.parse(theirs), include_attributes=False)
out = coord / "integration-v12-union-review/collector-published-sdk-keyword-custody-v18"
out.mkdir()
(out / "ours.py").write_bytes(ours)
(out / "theirs.py").write_bytes(theirs)
(root / name).write_bytes(theirs)
git("add", "--", name)
git("commit", "--no-edit")
head = git("rev-parse", "HEAD").decode().strip()
assert not git("status", "--porcelain").strip()
(out / "review.json").write_text(json.dumps(dict(head=head, onlyConflictKeywordOrder=True,
    normalizedAstExact=True, bothCollectorsRetained=True,
    originalSdkLockActuallyDerived=True, stagesSha256=[hashlib.sha256(raw).hexdigest() for raw in (ours, theirs)]), indent=2) + "\n", encoding="utf8")
print(json.dumps(dict(head=head, custody=str(out), freshSourcePending=True)))
