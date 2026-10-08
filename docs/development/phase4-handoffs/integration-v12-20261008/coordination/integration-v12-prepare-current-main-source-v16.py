"""Audit the released Source lane; add the locked maintained RPC descriptor check."""
import hashlib
import json
from pathlib import Path

coord = Path(__file__).resolve().parent
prior_job = "portable-v2-pr828-final-main-source-20261008-v264"
prior_head = "8fe134c08c0535e2eddf9cac7579fcdbacca90af"
raw = (coord / prior_job / "receipt.json").read_bytes()
prior = json.loads(raw)
assert prior["head"] == prior_head and prior["passed"] and prior["sourceClean"]
assert prior["sourceHeadUnchanged"] and prior["originalProcessReaped"] and prior["infrastructureError"] is None
assert len(prior["steps"]) == 7
for row in prior["steps"]:
    data = (coord / prior_job / row["log"]).read_bytes()
    assert row["exitCode"] == 0 and row["stopReason"] is None and row["originalProcessReaped"]
    assert hashlib.sha256(data).hexdigest() == row["sha256"] and len(data) == row["bytes"]
base = "/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data"
protoc = base + "/cargo/registry/src/index.crates.io-1949cf8c6b5b557f/protoc-bin-vendored-linux-x86_64-3.2.0/bin/protoc"
for tag, head in (("pr823", "3b7af5096198ae9453b5616bc124def18798911c"),
                  ("pr828", "912701092b03c97d6ce92e5bbac8a9f9a2f5fc68")):
    steps = json.loads((coord / prior_job / "invocation.json").read_bytes())["steps"]
    steps[3][-1] = "target/ci/observed-" + tag + "-current21c-v16-linux.json"
    steps[-1][-1] += "; subprocess.run(['python3','-X','utf8','-B','tools/generate_node_rpc.py','--protoc'," + repr(protoc) + ",'--check'],check=True)"
    path = coord / ("integration-v12-" + tag + "-current-main-source-steps-v16.json")
    path.write_text(json.dumps(steps, indent=2) + "\n", encoding="utf8")
controller = (coord / "entity-contract-v73-reused-signing-source-controller.py").read_text(encoding="utf8")
controller = controller.replace("source-dca5d7737ef2ae37", "source-6ab38845e5a266f3")
controller = controller.replace("integration-v12-current828-developmentc844-source-v10", prior_job)
controller = controller.replace("7bc6e42254ef94c2b0248ad174d1e959aefc10e2", prior_head)
needle = "assert previous['head'] == '" + prior_head + "'"
assert controller.count(needle) == 1
controller = controller.replace(needle, needle + "\n    assert hashlib.sha256((prior / 'receipt.json').read_bytes()).hexdigest() == '" + hashlib.sha256(raw).hexdigest() + "'")
path = coord / "integration-v12-current-main-reused-source-controller-v16.py"
compile(controller, str(path), "exec")
path.write_text(controller, encoding="utf8", newline="\n")
proof = dict(priorHead=prior_head, priorReceiptSha256=hashlib.sha256(raw).hexdigest(),
    allSevenPriorLogsAuthenticated=True, sourceOnly=True, noNewClone=True,
    originalSevenGatesAndAllModulesRetained=True, lockedActualDescriptorCheckAdded=True,
    controller=str(path), current823="3b7af5096198ae9453b5616bc124def18798911c",
    current828="912701092b03c97d6ce92e5bbac8a9f9a2f5fc68")
(coord / "integration-v12-union-review/current-main-source-reuse-preflight-v16.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
print(json.dumps(proof))
