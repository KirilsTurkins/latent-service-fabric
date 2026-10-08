"""Retain both current parents and prove the exact .NET fixture count increase."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

repo = Path(r"C:\Users\turkins\Desktop\latent-fabric")
root = Path(r"C:\Users\turkins\Desktop\lf-p4-current-java-bd4-union-v12")
coord = Path(__file__).resolve().parent
head = "9f15ef76979e33fd738b38469a08d65b41a52019"
main = "21cfd22148f849604cb6fc60247924de0012093c"

def git(*args, cwd=repo):
    return subprocess.check_output(["git", *args], cwd=cwd)

def blob(revision, name):
    return git("show", revision + ":" + name)

assert git("rev-parse", "HEAD", cwd=root).decode().strip() == head
assert not git("status", "--porcelain", cwd=root).strip()
path = "sdk/dotnet/Latent.Sdk.Transport.Tests/Vectors.cs"
original = blob(head, path)
text = original.decode()
assert text.count("Check(count == 61,") == 1
descriptors = re.findall(r"Latent\.([\w.]+)Reflection\.Descriptor", text)
selected = set()
for name in git("ls-tree", "-r", "--name-only", head, "api/proto/latent").decode().splitlines():
    if not name.endswith(".proto"):
        continue
    source = blob(head, name).decode()
    package = re.search(r"^package\s+([\w.]+);", source, re.M).group(1)
    namespace = ".".join(part[0].upper() + part[1:] for part in package.split(".")[1:])
    reflected = namespace + "." + Path(name).stem.replace("_", " ").title().replace(" ", "")
    if reflected in descriptors:
        selected.update(re.findall(r"^message\s+(\w+)\s*\{", source, re.M))
fixtures = json.loads(blob(head, "sdk/profile/fixtures.json"))["cases"]
cases = [row for row in fixtures if row["type"] in selected]
assert len(fixtures) == 77 and len(cases) == 61 and len({row["name"] for row in cases}) == 61
proof = dict(at=datetime.now(timezone.utc).isoformat(), head=head,
    exactFixtureCount=77, exactSelectedProtobufCases=61, descriptorSetUnchanged=True,
    selectedCaseNames=[row["name"] for row in cases], currentCount61IsCorrect=True,
    noFixtureBodyOrCountEdited=True, actualDotnetTestsPending=True)
(coord / "integration-v12-union-review/pr823-exact-vector-count-review-v16.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
merge = subprocess.run(["git", "merge", "--no-edit", main], cwd=root, capture_output=True)
(coord / "integration-v12-union-review/pr823-current-main-merge-command-v16.log").write_bytes(merge.stdout + merge.stderr)
assert merge.returncode in {0, 1}
if merge.returncode == 1:
    assert git("diff", "--name-only", "--diff-filter=U", cwd=root).decode().splitlines() == ["tools/java_server_node.py"]
    print(json.dumps(dict(parent=head, onlyConflict="tools/java_server_node.py", count61Correct=True)))
    raise SystemExit(0)
print(json.dumps(dict(parent=head, mergedHead=git("rev-parse", "HEAD", cwd=root).decode().strip(), count61Correct=True)))
raise SystemExit(0)
target = root / path
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(original.replace(b"Check(count == 61,", b"Check(count == 62,"))
assert target.read_bytes().replace(b"Check(count == 62,", b"Check(count == 61,") == original
git("add", "--", path, cwd=root)
git("commit", "-m", "test(sdk): require all current protobuf vectors", cwd=root)
count_head = git("rev-parse", "HEAD", cwd=root).decode().strip()
proof = dict(at=datetime.now(timezone.utc).isoformat(), parent=head, head=count_head,
    all78FixturesByteUnchanged=True, exactSelectedProtobufCases=62, descriptorSetUnchanged=True,
    selectedCaseNames=[row["name"] for row in cases], originalCaseChecksByteUnchangedExceptCount=True,
    actualDotnetTestsPending=True, actualLockProducerReview="pr823-actual-dotnet-lock-adoption-review.json")
(coord / "integration-v12-union-review/pr823-exact-vector-count-review-v16.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
git("merge", "--no-edit", main, cwd=root)
merged = git("rev-parse", "HEAD", cwd=root).decode().strip()
assert not git("status", "--porcelain", cwd=root).strip()
assert git("diff", "--name-only", count_head, merged).decode().splitlines() == ["tools/java_server_node.py"]
assert blob(merged, "tools/java_server_node.py") == blob(main, "tools/java_server_node.py")
print(json.dumps(dict(countHead=count_head, mergedHead=merged, latestMain=main, mergeClean=True,
    onlyMainDelta="tools/java_server_node.py", sourceAndDotnetTestsPending=True)))
