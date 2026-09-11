"""Pinned full01 prefix and explicit recovery; never a qualified full campaign."""
from pathlib import Path

from tools.optimization_docker import build, client_evidence as client, evidence as docker
from tools.optimization_evidence.common import fields, read_json, require, sha256, uint, verify_artifact
from . import bootstrap_evidence, evidence, model, replay
from .failure_full_support import journal, prefix, recovery

SOURCE = "901b25161c258704fa079113e1e73f0dfbd882eb"
TREE = "cf722017e87abab9b2f66eb57879ffd499f19dcd"
OWNER = "lsf-112-8c22b65b1529"
FAILURE = {"type": "EvidenceError", "reason": "kubernetes-pod-failed-or-restarted"}
ORIGINALS = {
    "suite.json": (481871, "sha256:bea8d80a92f6e7d6bc53728671af72f2f67f8299ad13d441aa888be01efcbe59"),
    "cleanup.json": (6738, "sha256:d2a0848e57aa0e92be03b488c491f46c1f8ad544b96addf018b3c7ad468c6a33"),
    "api.ndjson": (19305412, "sha256:af1aaaac6603bcd4e2a8190278e28608555e5a7e21adf1fa382783ce44923790"),
    "progress.ndjson": (935397, "sha256:d7344115b9c381b64fe0591eb2c2d474acafd1fac67887f2baa1cfccaaeda281"),
}


def original_bytes(root, name):
    maximum, checksum = ORIGINALS[name]
    raw = client._read(Path(root) / name, maximum)
    require(len(raw) == maximum and sha256(raw) == checksum, "kubernetes-full01-original-byte-identity")
    return raw


def original_shape(suite):
    require(suite["profile"] == "full" and suite["run_id"] == "full-01" and suite["owner"] == OWNER
            and suite["source"]["commit"] == SOURCE and suite["source"]["tree"] == TREE
            and suite["source"]["clean"] is True and suite["source_after"] is None
            and suite["failure"] == FAILURE and len(suite["groups"]) == 5 and suite["clients"] == [],
            "kubernetes-full01-original-shape")
    require(model.suite_startup_protocol(suite) == "tcp-socket.v1", "kubernetes-full01-original-probe")
    old = suite["cleanup"]
    require(old["namespace_absent"] is True and old["private_tls_removed"] is True
            and old["remaining_pods"] == {} and old["remote_removed"] is False
            and old["failure_diagnostics"] == [] and len(old["pods"]) == 45
            and old["errors"] == [{"stage": "owned-resources", "type": "EvidenceError",
                                    "reason": "kubernetes-worker-exec-not-clean"}]
            and len(suite["preparations"]) == 50 and len(suite["transfers"]) == 12,
            "kubernetes-full01-original-cleanup-shape")


def groups(root, suite):
    result = []
    for saved, expected in zip(suite["groups"], model.groups("full", 0)[:5]):
        fields(saved, "pair group arm density artifact")
        identity = {"pair": 0, "group": expected["ordinal"], "arm": expected["arm"], "density": expected["density"]}
        docker.equal({key: saved[key] for key in identity}, identity, "kubernetes-full01-group-order")
        artifact = fields(saved["artifact"], "path bytes sha256")
        require(artifact["path"] == f"group-0-{expected['ordinal']}.json", "kubernetes-full01-group-path")
        value = read_json(verify_artifact(root, artifact, 16 * 1024**2), 16 * 1024**2)
        docker.equal({key: value[key] for key in identity}, identity, "kubernetes-full01-group-identity")
        result.append(value)
    return result


def _source(root, suite, built):
    docker.source(suite["source"])
    docker.equal(suite["build_source"], built["source"], "kubernetes-full01-build-source")
    inputs = suite["collector_inputs"]
    require(isinstance(inputs, dict) and 1 <= len(inputs) <= 3500, "kubernetes-full01-source-count")
    for name, reference in inputs.items():
        require(name.startswith("tools/") and (name.endswith(".py") or name.endswith("/observer.sh"))
                and reference["path"] == "collector/source/" + name, "kubernetes-full01-source-path")
        verify_artifact(root, reference, model.MAX_FILE_BYTES)
    expected = {name: {key: row[key] for key in ("bytes", "sha256")} for name, row in built["inputs"].items()
                if not name.endswith(".py")}
    docker.equal(suite["build_inputs"], expected, "kubernetes-full01-build-inputs")


def validate(root, bootstrap_root, build_root, docker_root, *, recovery_root=None):
    root, bootstrap_root, build_root, docker_root = map(Path, (root, bootstrap_root, build_root, docker_root))
    for name in ORIGINALS:
        original_bytes(root, name)
    suite = read_json(root / "suite.json", 16 * 1024**2)
    original_shape(suite)
    docker.equal(read_json(root / "cleanup.json"), suite["cleanup"], "kubernetes-full01-cleanup-sidecar")
    boot = bootstrap_evidence.validate(bootstrap_root)
    built = build.validate_receipt(read_json(build_root / "docker-builds.json"), build_root)
    _source(root, suite, built)
    calls = journal.validate(root, suite, boot)
    expanded = {**suite, "groups": groups(root, suite)}
    checked = evidence.Replay(root, expanded, calls, boot, built, build_root, docker_root)
    completed = [checked.group(value, 0, expected) for value, expected in
                 zip(expanded["groups"], model.groups("full", 0)[:5])]
    separate_recovery = recovery_root is not None
    recovery_root = Path(recovery_root) if separate_recovery else root / "recovery"
    recovered = read_json((recovery_root if separate_recovery else root) / "recovery.json", 16 * 1024**2)
    recovery.validate(root, suite, recovered, boot, calls, recovery_root)
    prefix.validate(root, suite, recovered, completed, checked, recovery_root)
    # Each old API byte is pinned and parsed; the final nonzero exit remains failed.
    # No success-only whole-campaign closure or invented zero-Invoke claim applies.
    require(uint(recovered["finished_nanos"]) >= uint(suite["finished_nanos"]), "kubernetes-full01-recovery-clock")
    for name in ORIGINALS:
        original_bytes(root, name)
    return recovered
