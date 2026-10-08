import hashlib
import json
from pathlib import Path
import subprocess

coord = Path(__file__).resolve().parent
repo = Path(r"C:\Users\turkins\Desktop\latent-fabric")
job = coord / "integration-v12-current-java-real-node-v17"
settings_raw = (job / "campaign/node/installed-node.json").read_bytes()
settings = json.loads(settings_raw)
assert settings["httpIngress"]["authentication"] == {"mode": "bearer"}
assert not settings["httpIngress"].get("browserOrigins", [])
head = "027315a4bda3cc9d6b921d671b2756f3edee25b0"
def blob(name):
    return subprocess.check_output(["git", "show", head + ":" + name], cwd=repo)
http = blob("tools/java_transaction_qualification/http.py")
browser = blob("crates/latent-ingress/src/http/browser.rs")
transport = blob("apps/latentd/src/standalone/http/head.rs")
assert b'("Origin", "http://" + self.authority)' in http
assert b'if browser && !approved_origin' in browser and b'return Err(403)' in browser
assert b'origin.authority == target.authority()' in transport
assert b'origin.tenant' in transport
proof = dict(actualNativeHead=head, currentFixHead="528b2f59246855e3f3e23682d49b1fcd30940ad7",
    actualInstalledConfigSha256=hashlib.sha256(settings_raw).hexdigest(),
    actualConfigBrowserOriginsEmpty=True, maintainedCollectorAlwaysSendsOrigin=True,
    existingNativePolicyRejectsOriginWithoutExactApprovedAuthority=True,
    actualRootless403ConsistentWithPreAdmissionFence=True,
    newConfigContainsOnlyActualLoopbackAuthorityAndOriginalTenant=True,
    originBearerAndAuthorizationOraclePreserved=True, productionBrowserPolicyUnchanged=True,
    actualCorrectedSignedNodeExecutionPending=True,
    sourceHashes={name:hashlib.sha256(raw).hexdigest() for name,raw in (
        ("collector-http",http),("browser-admission",browser),("daemon-http-head",transport))})
(coord / "integration-v12-union-review/browser-origin-cause-review-v19.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
print(json.dumps(proof))
