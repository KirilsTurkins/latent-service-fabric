"""Separate cleanup proof for the immutable, fully completed smoke03 workload.

The original suite and its failed cleanup remain authoritative original bytes.
This module proves only the later seven-call cleanup completion; it neither
executes the retained helper nor changes the campaign's measurement interval.
"""
from __future__ import annotations

from pathlib import Path

from tools.optimization_docker import evidence as docker
from tools.optimization_evidence.common import decode, fields, read_json, require, uint, verify_artifact
from . import model, replay, transport_evidence as transport

PREFIX = "kubernetes-cleanup-completion-"
SOURCE = "2f7e3b1616056ba11a7e97ac613cdc3f416eb8c0"
SUITE = {"path": "smoke-03/suite.json", "bytes": "841691",
         "sha256": "sha256:10e8a31aecf383324e2adc516f553ece8134b93e87c8974cd6e4cbd02406740b"}
CLEANUP = {"path": "smoke-03/cleanup.json", "bytes": "6488",
           "sha256": "sha256:7be2690f8823c981e8c7fde490dd45c07d44fa015e0b04cb480fab7a47a781de"}
HELPER = {"path": "recovery.py", "bytes": "4225",
          "sha256": "sha256:301640f83e6ae2a44f79029fc91a6a3d151f47656c8edc87eaa850c97fe7d1a5"}
ERROR = [{"reason": "kubernetes-worker-exec-stderr", "stage": "owned-resources", "type": "EvidenceError"}]
REMOVAL = ('set -eu; p="$1"; [ "$(readlink -f -- "$p")" = "$p" ]; '
           '[ ! -L "$p" ]; if [ -d "$p" ]; then '
           'rm -rf --one-file-system -- "$p"; fi; [ ! -e "$p" ]')


def load(root, suite):
    """Gate the historical transport exception before decoding its original row."""
    root = Path(root)
    directory = root / "cleanup-completion"
    if suite["cleanup"]["errors"] == []:
        require(not directory.exists() and not directory.is_symlink(), PREFIX + "unexpected-sidecar")
        return None
    require(directory.is_dir() and not directory.is_symlink(), PREFIX + "missing-sidecar")
    value = read_json(directory / "recovery.json", 256 * 1024)
    fields(value, "schema source original_suite original_cleanup original_deleted_pods owner run_id "
           "started_nanos finished_nanos failure status new_guest_invokes helper cleanup")
    require(value["schema"] == model.PREFIX + "cleanup-completion.v1"
            and value["status"] == "owned-cleanup-completed" and value["failure"] is None
            and type(value["new_guest_invokes"]) is int and value["new_guest_invokes"] == 0,
            PREFIX + "outcome")
    require(value["owner"] == suite["owner"] == "lsf-112-8c22b65b1529"
            and value["run_id"] == suite["run_id"] == "smoke-03" and suite["profile"] == "smoke"
            and suite["failure"] is None and suite["source"]["commit"] == SOURCE
            and value["source"] == suite["source"] == suite["source_after"]
            and len(suite["groups"]) == 6 and len(suite["clients"]) == 1,
            PREFIX + "historical-scope")
    for key, reference, name in (("original_suite", SUITE, "suite.json"),
                                  ("original_cleanup", CLEANUP, "cleanup.json")):
        require(value[key] == reference, PREFIX + "original-reference")
        verify_artifact(root, {**reference, "path": name}, 16 * 1024**2)
    require(value["helper"] == HELPER, PREFIX + "helper-identity")
    verify_artifact(directory, value["helper"], 65536)
    original = suite["cleanup"]
    docker.equal(read_json(root / "cleanup.json"), original, PREFIX + "original-cleanup-sidecar")
    require(original["errors"] == ERROR and original["namespace_absent"] is True
            and original["remote_removed"] is False and original["remaining_pods"] == {}
            and original["private_tls_removed"] is True and original["failure_diagnostics"] == []
            and original["cri_calls"] == [2638] and len(original["pods"]) == 45
            and value["original_deleted_pods"] == original["pods"], PREFIX + "original-partial-cleanup")
    require(uint(suite["finished_nanos"]) <= uint(value["started_nanos"])
            <= uint(value["cleanup"]["started_nanos"]) <= uint(value["cleanup"]["finished_nanos"])
            <= uint(value["finished_nanos"]) <= uint(value["started_nanos"]) + 120 * 10**9,
            PREFIX + "separate-clock")
    children = {entry.name for entry in directory.iterdir()}
    require(children in ({"recovery.json", "api.ndjson", "cleanup.json", "recovery.py"},
                         {"recovery.json", "api.ndjson", "cleanup.json", "recovery.py", "transfers"}),
            PREFIX + "unexpected-artifact")
    if "transfers" in children:
        empty = directory / "transfers"
        require(empty.is_dir() and not empty.is_symlink() and not any(empty.iterdir()), PREFIX + "unexpected-transfer")
    return value


def _original_runtime(suite, journal, used, expected):
    require(journal["sha256"] == transport.SMOKE03_JOURNAL_SHA256 and len(journal["rows"]) == 2642
            and journal.get("recovered_cleanup", {}).get("ordinal") == 2641,
            PREFIX + "original-journal")
    before = transport.get(journal, 2638, provider="docker", operation="worker-exec",
                           argv=["crictl", "ps", "-a", "-o", "json"], timeout_seconds=20)
    containers = decode(before["stdout"], transport.MAX_RESPONSE).get("containers")
    require(isinstance(containers, list) and len(containers) <= 512, PREFIX + "original-runtime-list")
    owned = {}
    for item in containers:
        labels = item.get("labels", {})
        if labels.get("io.kubernetes.pod.namespace") != suite["namespace"]:
            continue
        require(item["id"] not in owned and labels.get("io.kubernetes.pod.uid") in expected
                and expected[labels["io.kubernetes.pod.uid"]] == labels.get("io.kubernetes.pod.name")
                and item.get("state") == "CONTAINER_EXITED", PREFIX + "original-runtime-owner")
        owned[item["id"]] = labels
    require(len(owned) == 6, PREFIX + "original-runtime-population")
    removed = suite["cleanup"]["cri_removed"]
    require(len(removed) == 2 and [row["call"] for row in removed] == [2639, 2640], PREFIX + "original-removed")
    ids = []
    for ordinal in (2639, 2640, 2641):
        call = transport.get(journal, ordinal, provider="docker", operation="worker-exec", timeout_seconds=20)
        argv = call["raw"]["argv"]
        require(len(argv) == 3 and argv[:2] == ["crictl", "rm"] and argv[2] in owned
                and call["stdout"] == (argv[2] + "\n").encode(), PREFIX + "original-remove-binding")
        ids.append(argv[2])
        if ordinal < 2641:
            require(removed[ordinal - 2639] == {"call": ordinal, "id": argv[2], "operation": "rm"}
                    and not call["stderr"], PREFIX + "original-successful-removal")
        else:
            labels = owned[argv[2]]
            require(call.get("recovered_failure") == "EvidenceError" and call.get("cleanup_log_warning")
                    and call["cleanup_log_owner"] == {
                        "namespace": suite["namespace"], "pod_name": labels["io.kubernetes.pod.name"],
                        "pod_uid": labels["io.kubernetes.pod.uid"],
                        "container_name": labels["io.kubernetes.container.name"], "container_id": argv[2]},
                    PREFIX + "original-warning-owner")
        used.add(ordinal)
    require(len(set(ids)) == 3, PREFIX + "duplicate-original-removal")
    used.add(2638)


def _completed(value, suite, directory, bootstrap):
    cleanup = value["cleanup"]
    fields(cleanup, "schema started_nanos finished_nanos namespace namespace_uid pods namespace_absent "
           "remote_removed attachments cri_calls cri_removed errors failure_diagnostics namespace_calls "
           "private_tls_removed remaining_pods remote_remove_call")
    docker.equal(read_json(directory / "cleanup.json"), cleanup, PREFIX + "completion-sidecar")
    require(cleanup["schema"] == model.PREFIX + "cleanup.v1"
            and cleanup["namespace"] == suite["namespace"] and cleanup["namespace_uid"] == suite["namespace_uid"]
            and cleanup["pods"] == value["original_deleted_pods"]
            and all(cleanup[key] is True for key in ("namespace_absent", "remote_removed", "private_tls_removed"))
            and all(cleanup[key] == [] for key in ("attachments", "cri_removed", "errors", "failure_diagnostics"))
            and cleanup["remaining_pods"] == {} and cleanup["namespace_calls"] == [1]
            and cleanup["cri_calls"] == [2, 3, 4, 5] and cleanup["remote_remove_call"] == 6,
            PREFIX + "completed-shape")
    journal = transport.validate(directory / "api.ndjson",
        worker_container_id=bootstrap["nodes"]["worker"]["container_id"],
        started_nanos=value["started_nanos"], finished_nanos=value["finished_nanos"])
    require(len(journal["rows"]) == 7, PREFIX + "new-call-population")
    worker = transport.get(journal, 0, provider="docker", operation="worker-identity")
    require(worker["owner"] == suite["owner"]
            and worker["response_json"]["Image"] == bootstrap["nodes"]["worker"]["image_id"],
            PREFIX + "worker-image")
    transport.get(journal, 1, provider="kubernetes", method="GET", status=404,
                  path="/api/v1/namespaces/" + suite["namespace"], timeout_seconds=15, expected_statuses=[200, 404])
    inventories = []
    for ordinal in (2, 3, 4, 5):
        argv = ["crictl", "ps", "-a", "-o", "json"] if ordinal < 4 else ["crictl", "pods", "-o", "json"]
        call = transport.get(journal, ordinal, provider="docker", operation="worker-exec", argv=argv, timeout_seconds=20)
        rows = decode(call["stdout"], transport.MAX_RESPONSE).get("containers" if ordinal < 4 else "items")
        require(isinstance(rows, list) and len(rows) <= 512
                and not any(row.get("labels", {}).get("io.kubernetes.pod.namespace") == suite["namespace"] for row in rows),
                PREFIX + "runtime-remains")
        inventories.append(rows)
    require(inventories[0] == inventories[1] and inventories[2] == inventories[3], PREFIX + "unrelated-runtime-changed")
    remote = transport.get(journal, 6, provider="docker", operation="worker-exec", timeout_seconds=20,
        argv=["sh", "-c", REMOVAL, "owned-cleanup", model.host_path(suite["owner"], suite["run_id"])])
    require(remote["stdout"] == b"" and remote["stderr"] == b"", PREFIX + "remote-output")
    require(all(uint(cleanup["started_nanos"]) <= uint(row["started_nanos"])
                <= uint(row["finished_nanos"]) <= uint(cleanup["finished_nanos"]) for row in journal["rows"][1:]),
            PREFIX + "completion-call-window")


def validate(root, suite, journal, bootstrap, used, value):
    """Prove the completion chain; return the unchanged original recovery record."""
    require(value is not None, PREFIX + "required")
    expected = replay._cleanup_objects(suite, journal, used)
    require(len(expected) == 45, PREFIX + "pod-population")
    docker.equal(suite["cleanup"]["attachments"], [suite["clients"][0]["attach"]], PREFIX + "original-client-closed")
    _original_runtime(suite, journal, used, expected)
    _completed(value, suite, Path(root) / "cleanup-completion", bootstrap)
    return value
