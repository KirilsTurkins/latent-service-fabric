"""Exact failed-full01 owner deletion, 33 retained outputs and final absence."""
from pathlib import PurePosixPath

from tools.optimization_docker import evidence as docker
from tools.optimization_evidence.common import fields, read_json, require, uint, verify_artifact
from .. import failure_evidence as failed, model, replay, transport_evidence as transport

REMOVAL = ('set -eu; p="$1"; [ "$(readlink -f -- "$p")" = "$p" ]; '
           '[ ! -L "$p" ]; if [ -d "$p" ]; then rm -rf --one-file-system -- "$p"; fi; [ ! -e "$p" ]')


def original_deletions(suite, journal):
    base = "/api/v1/namespaces/" + suite["namespace"]
    created = {}
    for selected in journal["rows"]:
        row = selected["raw"]
        if row["provider"] == "kubernetes" and row["method"] == "POST" and row["path"] == base + "/pods":
            pod = selected["response_json"]
            name, uid = pod["metadata"]["name"], pod["metadata"]["uid"]
            failed._pod(pod, suite, name, uid)
            require(name not in created, "kubernetes-full01-duplicate-created-pod")
            created[name] = uid
    expected = {"client-p0", "p0-g0-lsf-0", "p0-g1-native-0", "p0-g3-lsf-0", "p0-g4-lsf-0",
                *("p0-g2-native-" + str(i) for i in range(8)), *("p0-g5-native-" + str(i) for i in range(32))}
    require(set(created) == expected and len(created) == 45, "kubernetes-full01-created-owner-set")
    for row in suite["cleanup"]["pods"]:
        name, uid = row["name"], row["uid"]
        require(created.get(name) == uid, "kubernetes-full01-deleted-owner")
        call = transport.get(journal, row["call"], provider="kubernetes", method="DELETE", path=base + "/pods/" + name)
        body = call["request_json"]
        require(body["apiVersion"] == "v1" and body["kind"] == "DeleteOptions"
                and body["preconditions"] == {"uid": uid} and body["propagationPolicy"] == "Background"
                and body["gracePeriodSeconds"] == (40 if name == "client-p0" or name.startswith("p0-g5-") else 0),
                "kubernetes-full01-delete-precondition")
        transport.get(journal, row["absence_call"], provider="kubernetes", method="GET", path=base + "/pods/" + name, status=404)
    require({row["name"] for row in suite["cleanup"]["pods"]} == expected, "kubernetes-full01-deleted-set")
    transport.get(journal, suite["cleanup"]["namespace_calls"][-1], provider="kubernetes", method="GET", path=base, status=404)


def validate(root, suite, value, boot, original, recovery_root):
    from ..failure_full import ORIGINALS
    fields(value, "schema source original_source original_suite original_cleanup original_api original_progress "
        "original_deleted_pods original_transfers owner run_id started_nanos finished_nanos failure status "
        "new_guest_invokes helper cleanup")
    require(value["schema"] == model.PREFIX + "campaign-recovery.v1" and value["status"] == "owned-cleanup-completed"
            and value["failure"] is None and type(value["new_guest_invokes"]) is int and value["new_guest_invokes"] == 0
            and value["owner"] == suite["owner"] and value["run_id"] == "full-01"
            and value["original_source"] == suite["source"] and value["source"] == suite["source"],
            "kubernetes-full01-recovery-identity")
    for key, name in (("suite", "suite.json"), ("cleanup", "cleanup.json"), ("api", "api.ndjson"), ("progress", "progress.ndjson")):
        size, digest = ORIGINALS[name]
        require(value["original_" + key] == {"path": "full-01/" + name, "bytes": str(size), "sha256": digest},
                "kubernetes-full01-recovery-original-reference")
    require(value["original_deleted_pods"] == suite["cleanup"]["pods"]
            and value["original_transfers"] == suite["transfers"], "kubernetes-full01-original-owner-receipts")
    require(value["helper"] == {"path": "recovery.py", "bytes": "5694",
                "sha256": "sha256:8b78d87630ca8fadcd8e40f742cfab19cbad0d6ed361a683c2d4804eb43176f9"},
            "kubernetes-full01-recovery-helper")
    verify_artifact(recovery_root, value["helper"], 16384)
    docker.equal(read_json(recovery_root / "recovery.json", 16 * 1024**2), value, "kubernetes-full01-recovery-sidecar")
    cleanup = value["cleanup"]
    docker.equal(read_json(recovery_root / "cleanup.json"), cleanup, "kubernetes-full01-new-cleanup-sidecar")
    require(cleanup["schema"] == model.PREFIX + "cleanup.v1" and cleanup["namespace"] == suite["namespace"]
            and cleanup["namespace_uid"] == suite["namespace_uid"] and cleanup["pods"] == suite["cleanup"]["pods"]
            and all(cleanup[key] is True for key in ("namespace_absent", "remote_removed", "private_tls_removed"))
            and cleanup["remaining_pods"] == {} and cleanup["attachments"] == cleanup["cri_removed"] == cleanup["errors"] == []
            and cleanup["namespace_calls"] == [1] and cleanup["cri_calls"] == [2, 3, 4, 5]
            and cleanup["remote_remove_call"] == 39 and len(cleanup["failure_diagnostics"]) == 33,
            "kubernetes-full01-recovery-cleanup")
    times = [suite["finished_nanos"], value["started_nanos"], cleanup["started_nanos"], cleanup["finished_nanos"], value["finished_nanos"]]
    require([uint(x) for x in times] == sorted(uint(x) for x in times), "kubernetes-full01-recovery-time-order")
    checked = transport.validate(recovery_root / "api.ndjson", worker_container_id=boot["nodes"]["worker"]["container_id"],
        started_nanos=value["started_nanos"], finished_nanos=value["finished_nanos"])
    require(len(checked["rows"]) == 40, "kubernetes-full01-recovery-call-count")
    calls = failed._Calls(checked)
    calls.get(0, provider="docker", operation="worker-identity")
    calls.api(1, "GET", "/api/v1/namespaces/" + suite["namespace"], status=404)
    for ordinal, argv, key in ((2, ["crictl", "ps", "-a", "-o", "json"], "containers"),
                               (3, ["crictl", "ps", "-a", "-o", "json"], "containers"),
                               (4, ["crictl", "pods", "-o", "json"], "items"),
                               (5, ["crictl", "pods", "-o", "json"], "items")):
        raw = calls.command(ordinal, argv)
        actual = transport.decode(raw["stdout"], transport.MAX_RESPONSE)
        require(not any(item.get("labels", {}).get("io.kubernetes.pod.namespace") == suite["namespace"]
                        for item in actual.get(key, [])), "kubernetes-full01-runtime-owner-remains")
    indexes = [2, *range(18, 50)]
    for offset, (row, preparation) in enumerate(zip(cleanup["failure_diagnostics"], indexes)):
        remote = suite["preparations"][preparation]["destination"]
        require(row["remote"] == remote and row["local"] == f"failure-outputs/{preparation}"
                and row["call"] == 6 + offset and row["archive"]["path"] == f"transfers/download-{12 + offset:04d}.tar",
                "kubernetes-full01-recovery-download-order")
        selected = calls.get(row["call"], provider="docker", operation="worker-download")
        require(selected["raw"]["source_path"] == remote and selected["inventory"] == row["inventory"]
                and selected["archive"] == {key: row["archive"][key] for key in ("bytes", "sha256")},
                "kubernetes-full01-recovery-download-receipt")
        replay._tar(verify_artifact(recovery_root, row["archive"], transport.MAX_TRANSFER), row["inventory"],
                    root_name=PurePosixPath(remote).name)
        docker.inventory(recovery_root / row["local"], row["inventory"], retained=True)
    calls.command(39, ["sh", "-c", REMOVAL, "owned-cleanup", model.host_path(suite["owner"], suite["run_id"])])
    calls.finish()
    original_deletions(suite, original)
