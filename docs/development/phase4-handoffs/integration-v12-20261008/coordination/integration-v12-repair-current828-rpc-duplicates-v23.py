import hashlib
import json
from pathlib import Path
import re

root = Path(r"C:\Users\turkins\Desktop\lf-p4-pr828-current-renderer-contracts-v23")
coord = Path(__file__).resolve().parent
path = root / "crates/latent-rpc/src/phase4/tests.rs"
raw = path.read_bytes()
source = raw.decode()
start = source.index("fn floor_release() -> c::MutateStateRequest {")
end = source.index("fn mutation() -> c::MutateNamespaceRequest {", start)
first = source[start:end]
second_start = source.index("fn floor_release() -> c::MutateStateRequest {", end)
second = source[second_start:]
assert second.count("fn floor_release()") == 1
names = ("floor_release_requires_original_canonical_identity_and_history_precondition",
         "floor_release_receipt_cannot_substitute_another_record_policy_or_original_view")
assert all(first.count("fn " + name + "()") == second.count("fn " + name + "()") == 1 for name in names)
normalized = second.replace('        ..Default::default()\n', '').replace('        effect: None,\n', '')
normalized = normalized.replace('        audit_ack: None,\n        replayed: false\n', '        audit_ack: None\n')
normalized = normalized.replace('                audit_ack: None,\n                replayed: false\n', '                audit_ack: None\n')
assert normalized.strip() == first.strip(), "duplicate bodies contain unique assertions"
before_cases = set(re.findall(r"(?m)^fn\s+(\w+)\(\)", source))
resolved = source[:start] + source[end:]
after_cases = set(re.findall(r"(?m)^fn\s+(\w+)\(\)", resolved))
assert before_cases == after_cases and all(resolved.count("fn " + name + "()") == 1 for name in names)
assert resolved.count("fn floor_release()") == 1
assert "effect: None," in resolved and "replayed: false" in resolved
out = coord / "integration-v12-union-review/current828-rpc-duplicate-custody-v23"
out.mkdir()
(out / "original.rs").write_bytes(raw)
(out / "first-stale-floor.rs").write_text(first, encoding="utf8", newline="\n")
(out / "retained-current-floor.rs").write_text(second, encoding="utf8", newline="\n")
path.write_text(resolved, encoding="utf8", newline="\n")
proof = dict(parent="912701092b03c97d6ce92e5bbac8a9f9a2f5fc68", onlyObsoleteDuplicateCopyRemoved=True,
    allOriginalUniqueFunctionNamesRetained=True, allFloorCaseAssertionBytesEqual=True,
    typedOptionalEffectPlanEffectAndReplayFieldsPreserved=True, noProductionOrProtoChange=True,
    originalSha256=hashlib.sha256(raw).hexdigest(), removedBytes=len(first.encode()),
    retainedCaseNames=list(names), actualRpcCompilationPending=True)
(out / "review.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
print(json.dumps(proof))
