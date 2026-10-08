import ast
import hashlib
import json
from pathlib import Path
import subprocess

root = Path(r"C:\Users\turkins\Desktop\lf-p4-query-refusal-observation-v17")
coord = Path(__file__).resolve().parent
paths = ["tools/ci/contracts/python/test_java_transaction_actor.py.json", "tools/tests/test_java_transaction_actor.py"]
def git(*args):
    return subprocess.check_output(["git", *args], cwd=root)
assert git("diff", "--name-only", "--diff-filter=U").decode().splitlines() == paths
out = coord / "integration-v12-union-review/query-refusal-actor-additive-stages-v17"
out.mkdir()
raws = {}
for name in paths:
    ours = git("show", ":2:" + name)
    theirs = git("show", ":3:" + name)
    for label, raw in (("ours", ours), ("theirs", theirs)):
        (out / (Path(name).name + "." + label)).write_bytes(raw)
    if name.endswith(".py"):
        def classes(raw):
            return {node.name: ast.dump(node, include_attributes=False) for node in ast.parse(raw).body if isinstance(node, ast.ClassDef)}
        old, new = classes(ours), classes(theirs)
        assert set(old) <= set(new) and all(new[key] == value for key, value in old.items())
        assert set(new) - set(old) == {"OfflineQuiesceActorOracle"}
    else:
        old, new = json.loads(ours), json.loads(theirs)
        assert set(old["cases"]) <= set(new["cases"])
        assert all(new["guards"][key] == value for key, value in old["guards"].items())
    (root / name).write_bytes(theirs)
    raws[name] = dict(ours=hashlib.sha256(ours).hexdigest(), theirs=hashlib.sha256(theirs).hexdigest())
git("add", "--", *paths)
git("commit", "--no-edit")
head = git("rev-parse", "HEAD").decode().strip()
assert not git("status", "--porcelain").strip()
(out / "review.json").write_text(json.dumps(dict(head=head, allOriginalActorClassAstUnchanged=True,
    allOriginalActorCasesAndGuardsUnchanged=True, exactlyOneOfflineQuiesceCaseAdded=True,
    stages=raws), indent=2) + "\n", encoding="utf8")
print(json.dumps(dict(head=head, custody=str(out))))
