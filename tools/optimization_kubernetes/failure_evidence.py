"""Offline proof of the retained pre-Invoke TypeMeta failure and its recovery.

This deliberately accepts only the observed early-failure protocol. It does not
turn the failed attempt into a qualified workload or execute its retained code.
Original and recovery paths are mapped explicitly; original JSON stays intact.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath

from tools.optimization_docker import evidence as docker
from tools.optimization_evidence.common import (
    decode, fields, integer, read_json, require, sha256, uint, verify_artifact,
)
from . import bootstrap_evidence, model, replay, services, transport_evidence as transport

PREFIX = "kubernetes-failure-"
EMPTY = {"bytes": "0", "sha256": sha256(b"")}
ROLES = ("client-p0", "p0-g0-lsf-0")


class _Calls:
    def __init__(self, journal):
        self.journal, self.used = journal, set()

    def get(self, ordinal, **expected):
        require(ordinal not in self.used, PREFIX + "duplicate-call")
        self.used.add(ordinal)
        return transport.get(self.journal, ordinal, **expected)

    def api(self, ordinal, method, path, *, body=None, status=200):
        row = self.get(ordinal, provider="kubernetes", method=method, path=path, status=status)
        require(row["request_json"] == body, PREFIX + "api-request")
        return row["response_json"]

    def command(self, ordinal, argv):
        return self.get(ordinal, provider="docker", operation="worker-exec", argv=argv,
                        timeout_seconds=20)

    def finish(self):
        require(self.used == set(range(len(self.journal["rows"]))), PREFIX + "unused-call")


def _pod(value, suite, name, uid, *, embedded=False):
    services.item_kind(value, "Pod", embedded=embedded)
    metadata = value["metadata"]
    require(metadata["name"] == name and metadata["uid"] == uid
            and metadata["namespace"] == suite["namespace"]
            and all(metadata.get("labels", {}).get(key) == expected
                    for key, expected in model.labels(suite["owner"], suite["run_id"], name).items()),
            PREFIX + "pod-identity")


def _namespace(value, suite):
    services.subset(value, model.namespace(suite["owner"], suite["run_id"]))
    require(value["metadata"]["uid"] == suite["namespace_uid"], PREFIX + "namespace-uid")


def _pod_list(value, suite, pods):
    items = services.list_items(value, "Pod")
    require(len(items) == len(pods) and {row["metadata"]["name"] for row in items} == set(pods),
            PREFIX + "pod-list-population")
    for row in items:
        _pod(row, suite, row["metadata"]["name"], pods[row["metadata"]["name"]], embedded=True)
    return items


def _preparations(root, suite, calls):
    selected = [("fixtures", 3, 4), ("tools", 6, 7), ("clients/0", 15, 16),
                ("owners/p0-g0-lsf-0", 33, None), ("data/p0-g0-lsf-0", 35, 36)]
    require(len(suite["preparations"]) == len(selected) and suite["transfers"] == [],
            PREFIX + "preparation-population")
    for row, (relative, create, upload) in zip(suite["preparations"], selected):
        destination = model.host_path(suite["owner"], suite["run_id"], relative)
        require((row["relative"], row["destination"], row["create_call"], row["upload_call"])
                == (relative, destination, create, upload), PREFIX + "preparation-binding")
        for ordinal, argv in ((create - 1, ["mkdir", "-p", str(PurePosixPath(destination).parent)]),
                              (create, ["mkdir", "-m", "700", destination])):
            require(calls.command(ordinal, argv)["stdout"] == b"", PREFIX + "mkdir-output")
        if upload is None:
            require(row.get("transfer") is None and row.get("archive") is None, PREFIX + "unexpected-upload")
            continue
        transfer = row["transfer"]
        transport._inventory(transfer["inventory"])
        artifact = row["archive"]
        path = verify_artifact(root, artifact, transport.MAX_TRANSFER)
        require(artifact["bytes"] == transfer["archive_bytes"] and artifact["sha256"] == transfer["archive_sha256"],
                PREFIX + "upload-hash")
        replay._tar(path, transfer["inventory"])
        raw = calls.get(upload, provider="docker", operation="worker-upload")
        require(raw["raw"]["destination"] == destination and raw["archive"] ==
                {key: artifact[key] for key in ("bytes", "sha256")}, PREFIX + "upload-call")
        if relative == "tools":
            files = [entry for entry in transfer["inventory"]["entries"] if entry["kind"] == "file"]
            observer = suite["collector_inputs"]["tools/optimization_kubernetes/observer.sh"]
            require(len(files) == 1 and files[0]["path"] == "observer.sh"
                    and all(files[0][key] == observer[key] for key in ("bytes", "sha256")), PREFIX + "observer-input")
        if relative == "clients/0":
            require(transfer["inventory"]["entries"][1:] == [{"kind": "file", "mode": "0644",
                "path": "plan.json", "bytes": str((root / "clients/0/plan.json").stat().st_size),
                "sha256": sha256(bootstrap_evidence._file(root, "clients/0/plan.json", 4096))}], PREFIX + "client-plan-upload")


def _attachment(root, suite, boot):
    rows = suite["cleanup"]["attachments"]
    require(len(rows) == 1, PREFIX + "attach-population")
    row = rows[0]
    fields(row, "argv process_id start_time_ticks started_nanos finished_nanos exit_code reaped output_closed "
                "forced_kill failure process_group_gone descendant_reaps subreaper streams")
    expected = [boot["output"] + "/tools/kubectl", "--kubeconfig", boot["output"] + "/private/kubeconfig",
                "--context", "kind-" + suite["owner"], "--server", "https://" + suite["owner"] + "-control-plane:6443",
                "-n", suite["namespace"], "attach", "-i", "client-p0", "-c", "client", "--quiet=true"]
    require(row["argv"] == expected and row["failure"] is None and row["exit_code"] == -9
            and all(row[key] is True for key in ("reaped", "output_closed", "forced_kill", "process_group_gone"))
            and row["descendant_reaps"] == [] and row["subreaper"] == {"enabled": True, "previous": 0, "restored": True},
            PREFIX + "attach-closure")
    integer(row["process_id"], 1)
    require(uint(row["start_time_ticks"]) > 0 and uint(suite["started_nanos"]) <= uint(row["started_nanos"])
            <= uint(suite["cleanup"]["started_nanos"]) <= uint(row["finished_nanos"])
            <= uint(suite["cleanup"]["finished_nanos"]), PREFIX + "attach-clock")
    require(row["streams"] == {key: EMPTY for key in ("stdin", "stdout", "stderr")}, PREFIX + "nonzero-client-input")
    require(read_json(root / "clients/0/attachment.json") == row, PREFIX + "attach-sidecar")
    for name in ("parent-commands.ndjson", "attach-stdout.ndjson", "attach-stderr.bin"):
        require(bootstrap_evidence._file(root, "clients/0/" + name, 1024**2) == b"", PREFIX + "nonzero-client-input")


def _original(root, suite, boot, journal):
    require(len(journal["rows"]) == 61, PREFIX + "original-call-population")
    calls = _Calls(journal)
    owner, run = suite["owner"], suite["run_id"]
    remote, base = model.host_path(owner, run), "/api/v1/namespaces/" + suite["namespace"]
    require(calls.get(0, provider="docker", operation="worker-identity")["owner"] == owner, PREFIX + "worker")
    require(suite["remote_create_call"] == 1 and calls.command(1, ["mkdir", "-m", "700", remote])["stdout"] == b"",
            PREFIX + "remote-create")
    _preparations(root, suite, calls)
    require(suite["namespace_absence_call"] == 8 and suite["namespace_create_call"] == 9, PREFIX + "namespace-calls")
    calls.api(8, "GET", base, status=404)
    namespace = calls.api(9, "POST", "/api/v1/namespaces", body=model.namespace(owner, run), status=201)
    require(namespace == suite["namespace_create"], PREFIX + "namespace-create")
    _namespace(namespace, suite)
    require([row["stage"] for row in suite["background"]] == ["idle-before-start", "idle-before-end"], PREFIX + "background")
    for index, observed in enumerate(suite["background"]):
        require(len(observed["observations"]) == 2, PREFIX + "background-count")
        for offset, role in enumerate(("control-plane", "worker")):
            row = observed["observations"][offset]
            ordinal = 10 + 2 * index + offset
            call = calls.get(ordinal, provider="docker", operation="node-stats", role=role)
            require(row["role"] == role and row["call"] == ordinal and row["stats"] == call["response_json"]
                    and row["container_id"] == boot["nodes"][role]["container_id"], PREFIX + "background-binding")
    pods, ready = {}, {}
    for role, arm, ordinal, poll_start, poll_end in ((ROLES[0], "client", 17, 18, 26), (ROLES[1], "lsf", 38, 39, 52)):
        command = (["--session", "/output/plan.json", "--output", "/output"] if arm == "client" else
                   ["--app", "lsf", "--executable", "/opt/lsf/latentd", "--output", "/output", "--config", "/fixtures/node.json"])
        manifest = model.pod(boot["images"][arm]["tag"], command, arm=arm, density=1, owner=owner, run_id=run,
            role=role, fixtures=remote + "/fixtures", output=remote + ("/clients/0" if arm == "client" else "/owners/" + role),
             data=remote + "/data/" + role if arm == "lsf" else None,
             startup_protocol=model.suite_startup_protocol(suite))
        pod = calls.api(ordinal, "POST", base + "/pods", body=manifest, status=201)
        uid = pod["metadata"]["uid"]
        _pod(pod, suite, role, uid)
        pods[role] = uid
        for poll in range(poll_start, poll_end + 1):
            ready[role] = calls.api(poll, "GET", base + "/pods/" + role)
            _pod(ready[role], suite, role, uid)
    service = model.service(owner=owner, run_id=run, pair=0, group=0, arm="lsf", density=1, index=0)
    calls.api(37, "POST", base + "/services", body=service, status=201)
    calls.get(27, provider="kubernetes", method="GET", path=base + "/pods/client-p0/log?container=client", status=200)
    for role, inspect, stat_call, proc in ((ROLES[0], 28, 29, 30), (ROLES[1], 53, None, 55)):
        statuses = ready[role]["status"]["containerStatuses"]
        require(len(statuses) == 1 and statuses[0]["restartCount"] == 0, PREFIX + "pod-container-count")
        identifier = statuses[0]["containerID"].removeprefix("containerd://")
        transport._id(identifier)
        native = decode(calls.command(inspect, ["crictl", "inspect", identifier])["stdout"], transport.MAX_RESPONSE)
        labels = native["status"]["labels"]
        require(native["status"]["id"] == identifier and labels["io.kubernetes.pod.uid"] == pods[role]
                and labels["io.kubernetes.pod.name"] == role and labels["io.kubernetes.pod.namespace"] == suite["namespace"],
                PREFIX + "cri-original-identity")
        pid = integer(native["info"]["pid"], 1)
        stat = calls.command(proc, ["cat", f"/proc/{pid}/stat"])["stdout"].decode()
        require(stat.startswith(str(pid) + " ("), PREFIX + "process-identity")
        ticks = stat[stat.rindex(")") + 2:].split()[19]
        if stat_call is not None:
            calls.command(stat_call, ["crictl", "stats", "--output", "json", identifier])
            calls.command(31, ["sh", remote + "/tools/observer.sh", "client", str(pid), identifier, ticks])
    calls.command(54, ["tail", "-c", "+1", remote + "/owners/" + ROLES[1] + "/events.ndjson"])
    for ordinal, kind, path in ((56, "Pod", base + "/pods"), (57, "Service", base + "/services"),
                              (58, "EndpointSlice", "/apis/discovery.k8s.io/v1/namespaces/" + suite["namespace"] + "/endpointslices")):
        actual = calls.api(ordinal, "GET", path)
        items = services.list_items(actual, kind)
        require(items and all("kind" not in row and "apiVersion" not in row for row in items), PREFIX + "missing-embedded-typemeta")
        if kind == "Pod":
            _pod_list(actual, suite, pods)
    _namespace(calls.api(59, "GET", base), suite)
    _pod_list(calls.api(60, "GET", base + "/pods"), suite, pods)
    old = suite["cleanup"]
    require(old["errors"] == [{"reason": "kubernetes-cleanup-pod-owner", "stage": "owned-resources", "type": "EvidenceError"}]
            and old["namespace_calls"] == [59, 60] and old["remaining_pods"] == pods
            and old["namespace_absent"] is False and old["remote_removed"] is False and old["private_tls_removed"] is True
            and all(old[key] == [] for key in ("pods", "cri_calls", "cri_removed", "failure_diagnostics")), PREFIX + "original-cleanup-failure")
    require(read_json(root / "cleanup.json") == old, PREFIX + "original-cleanup-sidecar")
    _attachment(root, suite, boot)
    calls.finish()
    return pods


def _delete(calls, ordinal, path, uid, suite, name=None):
    body = {"apiVersion": "v1", "kind": "DeleteOptions", "preconditions": {"uid": uid},
            "propagationPolicy": "Foreground" if name is None else "Background"}
    if name is not None:
        body["gracePeriodSeconds"] = model.TERMINATION_SECONDS
    calls.api(ordinal, "DELETE", path, body=body)
    for selected in range(ordinal + 1, len(calls.journal["rows"])):
        row = calls.journal["rows"][selected]
        actual = calls.api(selected, "GET", path, status=row["raw"]["status"])
        if row["raw"]["status"] == 404:
            require(uint(row["finished_nanos"]) - uint(calls.journal["rows"][ordinal]["started_nanos"]) <= 120 * 10**9,
                    PREFIX + "delete-deadline")
            return selected
        (_namespace(actual, suite) if name is None else _pod(actual, suite, name, uid))
    require(False, PREFIX + "missing-404")


def _runtime(calls, value, suite, pods, ordinal):
    consumed, removed = [], []
    for command, key, state, operation in ((["crictl", "ps", "-a", "-o", "json"], "containers", "CONTAINER_EXITED", "rm"),
            (["crictl", "pods", "-o", "json"], "items", "SANDBOX_NOTREADY", "rmp")):
        before = decode(calls.command(ordinal, command)["stdout"], transport.MAX_RESPONSE)
        require(isinstance(before, dict) and isinstance(before.get(key), list) and len(before[key]) <= 512,
                PREFIX + "runtime-list")
        consumed.append(ordinal)
        ordinal += 1
        for row in before.get(key, []):
            labels = row.get("labels", {})
            if labels.get("io.kubernetes.pod.namespace") != suite["namespace"]:
                continue
            name = labels.get("io.kubernetes.pod.name")
            require(name in pods and labels.get("io.kubernetes.pod.uid") == pods[name] and row["state"] == state,
                    PREFIX + "runtime-uid")
            identifier = transport._id(row["id"])
            calls.command(ordinal, ["crictl", operation, identifier])
            removed.append({"call": ordinal, "id": identifier, "operation": operation})
            ordinal += 1
        after = decode(calls.command(ordinal, command)["stdout"], transport.MAX_RESPONSE)
        require(isinstance(after, dict) and isinstance(after.get(key), list) and len(after[key]) <= 512,
                PREFIX + "runtime-list")
        require(not any(row.get("labels", {}).get("io.kubernetes.pod.namespace") == suite["namespace"]
                        for row in after.get(key, [])), PREFIX + "runtime-remains")
        consumed.append(ordinal)
        ordinal += 1
    require(value["cri_calls"] == consumed and value["cri_removed"] == removed, PREFIX + "runtime-receipt")
    return ordinal


def _downloads(root, value, suite, calls, ordinal):
    require(len(value["failure_diagnostics"]) == 2, PREFIX + "download-count")
    for index, (row, suffix) in enumerate(zip(value["failure_diagnostics"], ("clients/0", "owners/" + ROLES[1]))):
        fields(row, "remote local call archive inventory")
        require(row["remote"] == model.host_path(suite["owner"], suite["run_id"], suffix)
                and row["local"] == "failure-outputs/" + str(index + 2) and row["call"] == ordinal + index,
                PREFIX + "download-path")
        selected = calls.get(row["call"], provider="docker", operation="worker-download")
        require(selected["raw"]["source_path"] == row["remote"] and selected["inventory"] == row["inventory"]
                and selected["archive"] == {key: row["archive"][key] for key in ("bytes", "sha256")}, PREFIX + "download-binding")
        recovery_root = root / "recovery"
        archive = verify_artifact(recovery_root, row["archive"], transport.MAX_TRANSFER)
        replay._tar(archive, row["inventory"], root_name=PurePosixPath(row["remote"]).name)
        docker.inventory(docker.relative(recovery_root, row["local"]), row["inventory"])
    require(bootstrap_evidence._file(root, "recovery/failure-outputs/2/attempts.jsonl", 1024**2) == b"",
            PREFIX + "nonzero-invokes")
    return ordinal + 2


def _recovery(root, suite, value, pods, journal):
    calls = _Calls(journal)
    require(calls.get(0, provider="docker", operation="worker-identity")["owner"] == suite["owner"], PREFIX + "recovery-worker")
    cleanup = value["cleanup"]
    require(cleanup["schema"] == model.PREFIX + "cleanup.v1" and cleanup["errors"] == []
            and cleanup["attachments"] == [] and cleanup["remaining_pods"] == {}
            and cleanup["namespace"] == suite["namespace"] and cleanup["namespace_uid"] == suite["namespace_uid"]
            and all(cleanup[key] is True for key in ("namespace_absent", "remote_removed", "private_tls_removed")),
            PREFIX + "recovery-incomplete")
    require(read_json(root / "recovery/cleanup.json") == cleanup, PREFIX + "recovery-cleanup-sidecar")
    base = "/api/v1/namespaces/" + suite["namespace"]
    _namespace(calls.api(1, "GET", base), suite)
    order = _pod_list(calls.api(2, "GET", base + "/pods"), suite, pods)
    ordinal, deletions = 3, []
    for pod in order:
        name, uid = pod["metadata"]["name"], pod["metadata"]["uid"]
        path = base + "/pods/" + name
        current = calls.api(ordinal, "GET", path)
        _pod(current, suite, name, uid)
        require(current["status"]["phase"] != "Succeeded", PREFIX + "recovery-grace-state")
        absent = _delete(calls, ordinal + 1, path, uid, suite, name)
        deletions.append({"name": name, "uid": uid, "call": ordinal + 1, "absence_call": absent})
        ordinal = absent + 1
    require(cleanup["pods"] == deletions, PREFIX + "recovery-delete-receipts")
    absent = _delete(calls, ordinal, base, suite["namespace_uid"], suite)
    require(cleanup["namespace_calls"] == [1, 2, *range(ordinal, absent + 1)], PREFIX + "recovery-namespace-receipts")
    ordinal = _runtime(calls, cleanup, suite, pods, absent + 1)
    ordinal = _downloads(root, cleanup, suite, calls, ordinal)
    script = ('set -eu; p="$1"; [ "$(readlink -f -- "$p")" = "$p" ]; '
              '[ ! -L "$p" ]; if [ -d "$p" ]; then rm -rf --one-file-system -- "$p"; fi; [ ! -e "$p" ]')
    require(cleanup["remote_remove_call"] == ordinal and calls.command(ordinal,
        ["sh", "-c", script, "owned-cleanup", model.host_path(suite["owner"], suite["run_id"])])["stdout"] == b"",
        PREFIX + "remote-removal")
    calls.finish()


def validate(failure_root: Path, bootstrap_root: Path, *, build_root=None, docker_root=None) -> dict:
    """Return the original recovery receipt; the original suite remains failed."""
    root = Path(failure_root)
    suite = read_json(docker.relative(root, "suite.json"), 8 * 1024**2)
    if suite.get("failure") == {"reason": "kubernetes-client-ack-order-identity", "type": "EvidenceError"}:
        from . import failure_inline
        require(build_root is not None and docker_root is not None, PREFIX + "inline-dependency-required")
        return failure_inline.validate(root, Path(bootstrap_root), Path(build_root), Path(docker_root))
    value = read_json(docker.relative(root, "recovery.json"), 8 * 1024**2)
    boot = bootstrap_evidence.validate(bootstrap_root)
    fields(value, "schema source original_suite owner run_id started_nanos failure status new_guest_invokes helper "
                  "original_pods cleanup finished_nanos")
    require(suite["schema"] == model.PREFIX + "suite.v1" and suite["profile"] == "smoke"
            and suite["failure"] == {"reason": "kubernetes-endpoint-list-kind", "type": "EvidenceError"}
            and suite["groups"] == [] and suite["clients"] == [] and suite["source_after"] is None,
            PREFIX + "unsupported-failure")
    require(value["schema"] == model.PREFIX + "campaign-recovery.v1" and value["status"] == "owned-campaign-recovered"
            and value["failure"] is None and integer(value["new_guest_invokes"], 0, 0) == 0
            and value["owner"] == suite["owner"] == boot["owner"] and value["run_id"] == suite["run_id"] == "smoke-01",
            PREFIX + "recovery-outcome")
    require(suite["namespace"] == model.namespace_name(suite["owner"], suite["run_id"])
            and suite["images"] == {arm: row["tag"] for arm, row in boot["images"].items()}
            and suite["collection_path"] == boot["output"] + "/" + suite["run_id"]
            and suite["bootstrap_path"] == boot["output"] + "/bootstrap.json", PREFIX + "original-scope")
    require(model.suite_startup_protocol(suite) == model.HISTORICAL_STARTUP_PROTOCOL, PREFIX + "plan")
    verify_artifact(bootstrap_root, suite["bootstrap"], 8 * 1024**2)
    original = value["original_suite"]
    require(original == {"path": suite["run_id"] + "/suite.json", "bytes": str((root / "suite.json").stat().st_size),
                         "sha256": sha256(bootstrap_evidence._file(root, "suite.json"))}, PREFIX + "original-suite-hash")
    bootstrap_evidence._artifact(root, value["helper"], "recovery.py", 64 * 1024)
    docker.source(suite["source"])
    docker.source(value["source"])
    require(value["source"] == suite["source"], PREFIX + "recovery-source")
    inputs = suite["collector_inputs"]
    require(isinstance(inputs, dict) and 1 <= len(inputs) <= 3500, PREFIX + "source-count")
    require({"tools/optimization_kubernetes/" + name for name in
             ("collect.py", "services.py", "transport.py", "session.py", "attach.py", "observer.sh")} <= inputs.keys(),
            PREFIX + "source-closure")
    for name, reference in inputs.items():
        require(name.startswith("tools/") and reference["path"] == "collector/source/" + name, PREFIX + "source-path")
        verify_artifact(root, reference, 16 * 1024**2)
    expected_plan = {"schema": model.CLIENT_PREFIX + "plan.v1", "run_id": suite["run_id"], "profile": "smoke",
                     "pair": 0, "token_file": "/fixtures/token"}
    require(read_json(root / "clients/0/plan.json") == expected_plan, PREFIX + "client-plan")
    times = [boot["finished_nanos"], suite["started_nanos"], suite["cleanup"]["started_nanos"],
             suite["cleanup"]["finished_nanos"], suite["finished_nanos"], value["started_nanos"],
             value["cleanup"]["started_nanos"], value["cleanup"]["finished_nanos"], value["finished_nanos"]]
    require(list(map(uint, times)) == sorted(map(uint, times)) and uint(value["finished_nanos"]) - uint(value["started_nanos"])
            <= 300 * 10**9, PREFIX + "recovery-clock")
    nodes = {role: row["container_id"] for role, row in boot["nodes"].items()}
    def journal(name, receipt):
        path = docker.relative(root, name)
        require(path.stat().st_size <= 16 * 1024**2, PREFIX + "journal-bound")
        result = transport.validate(path, worker_container_id=nodes["worker"], node_container_ids=nodes,
            started_nanos=receipt["started_nanos"], finished_nanos=receipt["finished_nanos"])
        require(len(result["rows"]) <= 1024, PREFIX + "journal-count")
        return result
    original_journal, recovery_journal = journal("api.ndjson", suite), journal("recovery-api.ndjson", value)
    pods = _original(root, suite, boot, original_journal)
    require(value["original_pods"] == pods, PREFIX + "recovery-original-pods")
    _recovery(root, suite, value, pods, recovery_journal)
    return value
