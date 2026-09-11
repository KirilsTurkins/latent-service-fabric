"""Offline campaign closure around original Kubernetes transport and workload bytes."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import json
import tarfile

from tools.optimization_docker import build, evidence as docker
from tools.optimization_evidence.common import canonical, read_json, require, sha256, uint, verify_artifact
from . import model, transport_evidence


def _source(suite, root, built):
    docker.source(suite["source"])
    docker.equal(suite["source_after"], suite["source"], "kubernetes-replay-source-changed")
    docker.equal(suite["build_source"], built["source"], "kubernetes-replay-build-source")
    inputs = suite["collector_inputs"]
    require(isinstance(inputs, dict) and 1 <= len(inputs) <= 3500, "kubernetes-replay-source-count")
    required = {"tools/run_optimization_kubernetes.py", *("tools/optimization_kubernetes/" + name for name in (
        "collect.py", "applications.py", "session.py", "model.py", "services.py", "transport.py",
        "attach.py", "files.py", "node.py", "observer.sh"))}
    require(required <= inputs.keys(), "kubernetes-replay-collector-closure")
    for name, reference in inputs.items():
        require(name.startswith("tools/") and (name.endswith(".py") or name == "tools/optimization_kubernetes/observer.sh")
                and reference["path"] == "collector/source/" + name, "kubernetes-replay-source-path")
        verify_artifact(root, reference, model.MAX_FILE_BYTES)
    expected = {name: {key: row[key] for key in ("bytes", "sha256")}
                for name, row in built["inputs"].items() if not name.endswith(".py")}
    docker.equal(suite["build_inputs"], expected, "kubernetes-replay-binary-inputs")
    require(suite["source"]["cargo_lock_sha256"] == expected["Cargo.lock"]["sha256"],
            "kubernetes-replay-source-lock")


def _tar(path, inventory, *, root_name=None):
    """Bind every retained transfer byte to its original file inventory, without extraction."""
    expected = {row["path"]: row for row in inventory["entries"] if row["path"] != "." or root_name is not None}
    seen = set()
    with tarfile.open(path, "r:") as archive:
        for member in archive:
            name = member.name
            if root_name is not None:
                require(name == root_name or name.startswith(root_name + "/"), "kubernetes-replay-tar-root")
                name = name[len(root_name):].lstrip("/") or "."
            require(name in expected and name not in seen, "kubernetes-replay-tar-population")
            seen.add(name)
            row = expected[name]
            require(member.mode & 0o777 == int(row["mode"], 8), "kubernetes-replay-tar-mode")
            if row["kind"] == "directory":
                require(member.isdir() and member.size == 0, "kubernetes-replay-tar-directory")
            else:
                require(member.isfile() and member.size == uint(row["bytes"]) <= 40 * 1024**2,
                        "kubernetes-replay-tar-file")
                with archive.extractfile(member) as stream:
                    data = stream.read(member.size + 1)
                require(len(data) == member.size and sha256(data) == row["sha256"], "kubernetes-replay-tar-bytes")
    require(seen == expected.keys(), "kubernetes-replay-tar-missing")


def _transfers(suite, root, journal, used, build_root, docker_root):
    for row in suite["preparations"]:
        destination = model.host_path(suite["owner"], suite["run_id"], row["relative"])
        require(row["destination"] == destination, "kubernetes-replay-upload-destination")
        transport_evidence.get(journal, row["create_call"], provider="docker", operation="worker-exec",
                               argv=["mkdir", "-m", "700", destination])
        used.add(row["create_call"])
        if row["transfer"] is None:
            require(row["upload_call"] is None, "kubernetes-replay-unexpected-upload")
            continue
        transfer = row["transfer"]
        if row["relative"] == "fixtures":
            docker.inventory(build_root / "fixtures", transfer["inventory"])
        elif row["relative"] == "tools":
            expected_file = suite["collector_inputs"]["tools/optimization_kubernetes/observer.sh"]
            files = [item for item in transfer["inventory"]["entries"] if item["kind"] == "file"]
            require(len(files) == 1 and files[0]["path"] == "observer.sh"
                    and all(files[0][key] == expected_file[key] for key in ("bytes", "sha256")),
                    "kubernetes-replay-uploaded-observer")
        elif row["relative"].startswith("data/"):
            role = row["relative"].removeprefix("data/")
            owners = [owner for group in suite["groups"] for owner in group["owners"]
                      if owner["role"] == role and group["arm"] == "lsf"]
            require(len(owners) == 1, "kubernetes-replay-uploaded-seed-owner")
            seed = suite["seeds"][str(owners[0]["density"])]
            original = read_json(verify_artifact(docker_root, seed["receipt"], 8 * 1024**2))
            docker.equal(seed["template"], original["template"], "kubernetes-replay-original-seed")
            docker.equal(transfer["inventory"], seed["template"]["inventory"], "kubernetes-replay-uploaded-seed")
        elif row["relative"].startswith("clients/"):
            pair = row["relative"].removeprefix("clients/")
            require(pair.isdecimal() and int(pair) < len(suite["clients"]), "kubernetes-replay-client-input")
            plan_path = root / "clients" / pair / "plan.json"
            files = [item for item in transfer["inventory"]["entries"] if item["kind"] == "file"]
            require(len(files) == 1 and files[0]["path"] == "plan.json"
                    and files[0]["sha256"] == sha256(plan_path.read_bytes())
                    and uint(files[0]["bytes"]) == plan_path.stat().st_size, "kubernetes-replay-uploaded-client-plan")
        else:
            raise ValueError("kubernetes-replay-unexpected-upload-input")
        path = verify_artifact(root, row["archive"], 40 * 1024**2)
        require(row["archive"]["sha256"] == transfer["archive_sha256"]
                and row["archive"]["bytes"] == transfer["archive_bytes"], "kubernetes-replay-upload-hash")
        _tar(path, transfer["inventory"])
        call = transport_evidence.get(journal, row["upload_call"], provider="docker", operation="worker-upload")
        require(call["raw"]["destination"] == destination
                and call["archive"] == {key: row["archive"][key] for key in ("bytes", "sha256")},
                "kubernetes-replay-upload-call")
        used.add(row["upload_call"])
    for row in suite["transfers"]:
        path = verify_artifact(root, row["archive"], 40 * 1024**2)
        docker.inventory(docker.relative(root, row["local"]), row["inventory"])
        _tar(path, row["inventory"], root_name=PurePosixPath(row["remote"]).name)
        call = transport_evidence.get(journal, row["call"], provider="docker", operation="worker-download")
        require(call["raw"]["source_path"] == row["remote"]
                and call["archive"] == {key: row["archive"][key] for key in ("bytes", "sha256")},
                "kubernetes-replay-download-call")
        docker.equal(call["inventory"], row["inventory"], "kubernetes-replay-download-inventory")
        used.add(row["call"])


def _cleanup(suite, root, journal, used):
    value = suite["cleanup"]
    docker.equal(read_json(root / "cleanup.json"), value, "kubernetes-replay-cleanup-sidecar")
    require(value["schema"] == model.PREFIX + "cleanup.v1" and value["errors"] == []
            and value["namespace"] == suite["namespace"] and value["namespace_uid"] == suite["namespace_uid"]
            and value["namespace_absent"] is True and value["remote_removed"] is True
            and value["remaining_pods"] == {} and value["private_tls_removed"] is True,
            "kubernetes-replay-incomplete-cleanup")
    expected = {row["create"]["pod"]["metadata"]["uid"]: row["create"]["pod"]["metadata"]["name"]
                for row in suite["clients"] + [app for group in suite["groups"] for app in group["owners"]]}
    require(len(value["pods"]) == len(expected)
            and {row["uid"]: row["name"] for row in value["pods"]} == expected,
            "kubernetes-replay-pod-delete-population")
    base = "/api/v1/namespaces/" + suite["namespace"]
    for row in value["pods"]:
        path = base + "/pods/" + row["name"]
        call = transport_evidence.get(journal, row["call"], provider="kubernetes", method="DELETE", path=path)
        require(call["request_json"]["preconditions"] == {"uid": row["uid"]}, "kubernetes-replay-pod-delete-uid")
        transport_evidence.get(journal, row["absence_call"], provider="kubernetes", method="GET", path=path, status=404)
        used.update((row["call"], row["absence_call"]))
    require(value["namespace_calls"], "kubernetes-replay-namespace-cleanup-calls")
    deleted = False
    for ordinal in value["namespace_calls"]:
        call = transport_evidence.get(journal, ordinal, provider="kubernetes")
        raw = call["raw"]
        require(raw["path"] in (base, base + "/pods"), "kubernetes-replay-namespace-cleanup-path")
        if raw["method"] == "DELETE":
            require(not deleted and raw["path"] == base
                    and call["request_json"]["preconditions"] == {"uid": suite["namespace_uid"]},
                    "kubernetes-replay-namespace-delete-uid")
            deleted = True
        else:
            require(raw["method"] == "GET", "kubernetes-replay-namespace-cleanup-method")
        used.add(ordinal)
    require(deleted and journal["rows"][value["namespace_calls"][-1]]["raw"]["status"] == 404,
            "kubernetes-replay-namespace-absence")
    require(len(value["cri_calls"]) == 4, "kubernetes-replay-runtime-cleanup-count")
    removable = {}
    for index, ordinal in enumerate(value["cri_calls"]):
        command = ["crictl", "ps", "-a", "-o", "json"] if index < 2 else ["crictl", "pods", "-o", "json"]
        call = transport_evidence.get(journal, ordinal, provider="docker", operation="worker-exec", argv=command)
        data = json.loads(call["stdout"])
        if index % 2:
            require(not any(row.get("labels", {}).get("io.kubernetes.pod.namespace") == suite["namespace"]
                    for row in data.get("containers" if index < 2 else "items", [])), "kubernetes-replay-runtime-remains")
        else:
            for row in data.get("containers" if index < 2 else "items", []):
                labels = row.get("labels", {})
                if labels.get("io.kubernetes.pod.namespace") != suite["namespace"]:
                    continue
                require(labels.get("io.kubernetes.pod.uid") in expected
                        and expected[labels["io.kubernetes.pod.uid"]] == labels.get("io.kubernetes.pod.name")
                        and row.get("state") == ("CONTAINER_EXITED" if index < 2 else "SANDBOX_NOTREADY"),
                        "kubernetes-replay-runtime-owner")
                removable[row["id"]] = "rm" if index < 2 else "rmp"
        used.add(ordinal)
    require(len(value["cri_removed"]) == len(removable)
            and {row["id"]: row["operation"] for row in value["cri_removed"]} == removable,
            "kubernetes-replay-runtime-remove-population")
    for row in value["cri_removed"]:
        require(row["operation"] in ("rm", "rmp"), "kubernetes-replay-runtime-remove-operation")
        transport_evidence.get(journal, row["call"], provider="docker", operation="worker-exec",
                               argv=["crictl", row["operation"], row["id"]])
        used.add(row["call"])
    call = transport_evidence.get(journal, value["remote_remove_call"], provider="docker", operation="worker-exec")
    argv = call["raw"]["argv"]
    script = ('set -eu; p="$1"; [ "$(readlink -f -- "$p")" = "$p" ]; '
              '[ ! -L "$p" ]; if [ -d "$p" ]; then '
              'rm -rf --one-file-system -- "$p"; fi; [ ! -e "$p" ]')
    require(argv == ["sh", "-c", script, "owned-cleanup", model.host_path(suite["owner"], suite["run_id"])],
            "kubernetes-replay-remote-removal")
    used.add(value["remote_remove_call"])


def validate(root, build_root, docker_root, bootstrap_root):
    """Return both independently validated platform records for aggregation."""
    from . import evidence
    root, build_root, docker_root, bootstrap_root = map(Path, (root, build_root, docker_root, bootstrap_root))
    suite = read_json(root / "suite.json", 128 * 1024**2)
    require(suite["schema"] == model.PREFIX + "suite.v1" and suite["failure"] is None,
            "kubernetes-replay-incomplete-suite")
    require(suite["namespace"] == model.namespace_name(suite["owner"], suite["run_id"]), "kubernetes-replay-namespace")
    docker.equal(suite["plan"], model.plan(suite["profile"], owner=suite["owner"]), "kubernetes-replay-plan")
    docker.equal(read_json(root / "plan.json"), suite["plan"], "kubernetes-replay-plan-sidecar")
    before, after = uint(suite["started_nanos"]), uint(suite["finished_nanos"])
    require(before <= after <= before + 7200 * 10**9, "kubernetes-replay-campaign-bound")
    built = build.validate_receipt(read_json(verify_artifact(build_root, suite["build_receipt"], 16 * 1024**2)), build_root)
    _source(suite, root, built)
    verify_artifact(docker_root, suite["docker_suite"], 32 * 1024**2)
    from . import bootstrap_evidence
    verify_artifact(bootstrap_root, suite["bootstrap"], 8 * 1024**2)
    bootstrap = bootstrap_evidence.validate(bootstrap_root)
    require(bootstrap["schema"] == model.PREFIX + "bootstrap.v1" and bootstrap["failure"] is None
            and bootstrap["status"] == "connected-no-workload" and bootstrap["owner"] == suite["owner"],
            "kubernetes-replay-bootstrap")
    require(suite["images"] == {arm: item["tag"] for arm, item in bootstrap["images"].items()},
            "kubernetes-replay-imported-image-set")
    journal = transport_evidence.validate(root / "api.ndjson",
        worker_container_id=bootstrap["nodes"]["worker"]["container_id"],
        node_container_ids={role: row["container_id"] for role, row in bootstrap["nodes"].items()},
        started_nanos=suite["started_nanos"], finished_nanos=suite["finished_nanos"])
    derived = evidence.validate(root, suite=suite, journal=journal, bootstrap=bootstrap,
                                build_root=build_root, docker_root=docker_root)
    used = set(derived.pop("transport_calls_used"))
    _transfers(suite, root, journal, used, build_root, docker_root)
    _cleanup(suite, root, journal, used)
    from . import closure
    closure.validate(suite, root, journal, bootstrap, used)
    docker_derived = docker.validate(docker_root, build_root)
    derived.update(schema=model.PREFIX + "derived.v1", status="passed", profile=suite["profile"],
        owner=suite["owner"], run_id=suite["run_id"], source=suite["source"], build_source=suite["build_source"],
        suite_sha256=sha256((root / "suite.json").read_bytes()), plan=suite["plan"],
        bootstrap=bootstrap, docker_suite=suite["docker_suite"], images=bootstrap["images"],
        background=suite["background"], cleanup=suite["cleanup"],
        started_nanos=suite["started_nanos"], finished_nanos=suite["finished_nanos"],
        transport={"bytes": journal["bytes"], "sha256": journal["sha256"], "calls": len(journal["rows"])})
    return derived, docker_derived
