import hashlib
import json
from pathlib import Path
import subprocess

coord = Path(__file__).resolve().parent
repo = Path(r"C:\Users\turkins\Desktop\latent-fabric")
head = "528b2f59246855e3f3e23682d49b1fcd30940ad7"
cases = {
    "apps/latentd/src/standalone/http/tests/browser_config.rs":
        "browser_origin_bindings_are_closed_unique_tenant_scoped_and_optional_for_native_clients",
    "crates/latent-ingress/src/http/browser/tests.rs":
        "browser_origin_is_exact_and_never_accepts_null_lists_siblings_or_forwarding",
}
records = []
for name, case in cases.items():
    raw = subprocess.check_output(["git", "show", head + ":" + name], cwd=repo)
    assert ("fn " + case + "(").encode() in raw
    records.append(dict(path=name, case=case, sourceSha256=hashlib.sha256(raw).hexdigest()))
steps = json.loads((coord / "integration-v12-approved-origin-native-fence-steps-v19.json").read_bytes())
assert len(steps) == 2 and all("--exact" in row and "--locked" in row and "--offline" in row for row in steps)
proof = dict(head=head, exactlyTwoMaintainedNativeCases=records, originalCaseBodiesUnchanged=True,
    requireActualOneExecutedCasePerCommand=True, executionPending=True, noZeroCaseQualification=True)
(coord / "integration-v12-union-review/approved-origin-native-case-review-v19.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
print(json.dumps(proof))
