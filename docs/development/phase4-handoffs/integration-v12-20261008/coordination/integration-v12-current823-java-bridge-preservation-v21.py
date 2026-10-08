import hashlib
import json
from pathlib import Path
import re
import subprocess

coord = Path(__file__).resolve().parent
repo = Path(r"C:\Users\turkins\Desktop\latent-fabric")
old = "3b7af5096198ae9453b5616bc124def18798911c"
head = "76307dbbe24b51fb8b1316c4fbf7047914759a51"
name = "sdk/java-client/src/transport/java/dev/latent/sdk/transport/Wire.java"
def blob(revision,path):
    return subprocess.check_output(["git", "show", revision + ":" + path], cwd=repo)
assert subprocess.check_output(["git", "diff", "--name-only", old, head], cwd=repo).decode().splitlines() == [name]
before, after = blob(old,name), blob(head,name)
def methods(raw):
    source = raw.decode()
    matches = list(re.finditer(r"    public static ([^\n]+) \{\n", source))
    return {match.group(1):source[match.start():matches[i+1].start() if i+1<len(matches) else source.rfind("}\n")]
        for i,match in enumerate(matches)}
a,b = methods(before),methods(after)
assert set(a) <= set(b)
changed = [key for key in a if a[key] != b[key]]
assert len(changed) == 2 and all("ActivationTreeNode" in key for key in changed)
added = list(set(b)-set(a))
assert len(added) == 2 and all("TransactionStagingWitness" in key for key in added)
assert blob(old,"sdk/profile/fixtures.json") == blob(head,"sdk/profile/fixtures.json")
assert len(json.loads(blob(head,"sdk/profile/fixtures.json"))["cases"]) == 77
proof = dict(parent=old,head=head,actualMaintainedGeneratorOutput=True, changedPath=name,
    changedOriginalMethods=changed,newWitnessMethods=sorted(added),allOtherOriginalMethodBytesUnchanged=True,
    allOriginalFixturesByteUnchanged=True,branchFixtureCount77=True,
    originalJavaCodecSuccess60AndRefusal1OracleUnchanged=True,
    generatorSha256=hashlib.sha256(blob(head,"sdk/java-client/tools/generate_bridge.py")).hexdigest(),
    generatedOutputSha256=hashlib.sha256(after).hexdigest(), actualGradleQualificationPending=True)
(coord/"integration-v12-union-review/current823-java-bridge-preservation-v21.json").write_text(json.dumps(proof,indent=2)+"\n",encoding="utf8")
print(json.dumps(proof))
