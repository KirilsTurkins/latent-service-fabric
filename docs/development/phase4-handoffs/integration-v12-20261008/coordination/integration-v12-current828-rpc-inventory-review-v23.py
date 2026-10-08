import json
from pathlib import Path
import re
import subprocess

coord = Path(__file__).resolve().parent
repo = Path(r"C:\Users\turkins\Desktop\latent-fabric")
head = "756a492b1678dec5e4f69dac11c571acc3836dd1"
data = json.loads(subprocess.check_output(["git", "show", head + ":tools/ci/suites.json"], cwd=repo))
rows = data.get("suites", data.get("rows"))
assert isinstance(rows,list)
selected = [row for row in rows if row.get("package") == "latent-rpc" and row.get("kind") == "lib"]
if not selected:
    selected = [row for row in rows if row.get("package") == "latent-rpc" and row.get("target") == "lib"]
assert selected
record = dict(head=head, rows=selected, suiteMetadataByteUnchanged=True,
    duplicateRustDefinitionEliminatedWithoutUniqueTestRemoval=True,
    actualCompiledListAndAllTestsPending=True, noFloorReduction=True)
(coord / "integration-v12-union-review/current828-rpc-inventory-review-v23.json").write_text(json.dumps(record,indent=2)+"\n",encoding="utf8")
print(json.dumps(dict(head=head,suites=[{key:row.get(key) for key in ('id','minimumCases','expectedIgnored','mode')} for row in selected], actualNativePending=True)))
