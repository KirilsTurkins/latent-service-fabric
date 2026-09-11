"""Bind application/client components to original transport and retained files.

The campaign/archive layer separately binds bootstrap/source closures, namespace
cleanup, and all remaining setup operations. No retained source is executed.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import re

from tools.optimization_docker import build, client_evidence, evidence as docker_evidence
from tools.optimization_docker import model as docker_model
from tools.optimization_docker import resources as wrapper
from tools.optimization_evidence.common import (
    canonical, decode, digest, fields, integer, read_json, require, sha256, text, uint, verify_artifact,
)
from . import model, node, proxy, resources, services, transport_evidence as transport


def _same(left, right, reason):
    require(canonical(left) == canonical(right), reason)


def _path(root, relative):
    name = text(relative, 4096)
    selected = PurePosixPath(name)
    require(not selected.is_absolute() and selected.as_posix() == name and ".." not in selected.parts
            and "\\" not in name, "kubernetes-evidence-relative-path")
    path = root.joinpath(*selected.parts)
    require(path.resolve().is_relative_to(root.resolve()) and not any(item.is_symlink()
            for item in (path, *path.parents) if item != root.parent), "kubernetes-evidence-path-owner")
    return path


def _read(root, relative, maximum=16 * 1024**2):
    return client_evidence._read(_path(root, relative), maximum)


def _json(root, relative, expected, maximum=16 * 1024**2):
    _same(decode(_read(root, relative, maximum), maximum), expected, "kubernetes-evidence-sidecar")


def _ref(root, value, *, expected=None, maximum=16 * 1024**2):
    selected = fields(value, "path bytes sha256")
    if expected is not None:
        require(selected["path"] == expected, "kubernetes-evidence-reference-path")
    path = verify_artifact(root, selected, maximum)
    return client_evidence._read(path, maximum)


def _counter(value):
    return uint(value) if isinstance(value, str) else integer(value, 0, 2**64 - 1)


def _image(pod, cri, arm, bootstrap):
    original = bootstrap["images"][arm]
    require(pod["spec"]["containers"][0]["image"] == original["tag"], "kubernetes-evidence-original-image-tag")
    imported = original["imported"]
    allowed = {digest(imported["config_digest"]), digest(imported["manifest_digest"])}
    require(original["original_docker_image_id"] == imported["manifest_digest"]
            and imported["status_id"] == imported["config_digest"], "kubernetes-evidence-image-graph")
    selected = cri["info"]["config"]["image"]
    require(selected.get("image") == imported["config_digest"]
            and selected.get("user_specified_image") == original["tag"], "kubernetes-evidence-cri-selected-image")
    for observed in (pod["status"]["containerStatuses"][0]["imageID"], cri["status"]["imageRef"]):
        value = text(observed, 1024)
        # CRI can report the imported archive's repository alias. The per-arm
        # config identity above, not this shared index digest, proves selection.
        if imported.get("repo_digest_scope") == "archive-index" and value in imported.get("repo_digests", []):
            require("@" in value and value.rsplit("@", 1)[1] == digest(imported["archive_index_digest"]),
                    "kubernetes-evidence-image-index-alias")
            continue
        if value.startswith("docker-pullable://"):
            value = value[len("docker-pullable://"):]
        if "@" in value:
            name, value = value.rsplit("@", 1)
            require(name in (original["tag"], "docker.io/library/" + original["tag"]),
                    "kubernetes-evidence-image-repository")
        require(value in allowed, "kubernetes-evidence-running-image")
    requested = cri["status"].get("image", {}).get("image")
    if requested is not None:
        require(requested in (original["tag"], "docker.io/library/" + original["tag"]),
                "kubernetes-evidence-cri-requested-image")


def _client_stats(value, container):
    rows = fields(value, "stats")["stats"]
    require(isinstance(rows, list) and len(rows) == 1, "kubernetes-evidence-client-stats-count")
    row = rows[0]
    require(row["attributes"]["id"] == container, "kubernetes-evidence-client-stats-owner")
    result = {"container_id": container}
    for group, metric, name, timestamp in (
        ("cpu", "usageCoreNanoSeconds", "cpu_usage_nanos", "cpu_timestamp_nanos"),
        ("memory", "workingSetBytes", "memory_working_set_bytes", "memory_timestamp_nanos"),
    ):
        current = row.get(group)
        require(current is None or isinstance(current, dict), "kubernetes-evidence-client-stats-object")
        counter = None if current is None else current.get(metric)
        require(counter is None or isinstance(counter, dict), "kubernetes-evidence-client-stats-counter")
        reported = counter is not None and "value" in counter
        result[name] = str(_counter(counter["value"])) if reported else None
        result[name + "_unavailable_reason"] = None if reported else "cri-field-not-reported"
        captured = None if current is None else current.get("timestamp")
        result[timestamp] = str(_counter(captured)) if captured is not None else None
        result[timestamp + "_unavailable_reason"] = None if captured is not None else "cri-field-not-reported"
    return result


def _client_pods(ready, final, manifest, worker):
    expected = {**manifest, "spec": {**manifest["spec"], "containers": [dict(manifest["spec"]["containers"][0])]}}
    del expected["spec"]["containers"][0]["resources"]
    for pod, phase in ((ready, "Running"), (final, "Succeeded")):
        services.subset(pod, expected)
        require(pod["metadata"].get("deletionTimestamp") is None and pod["spec"]["nodeName"] == worker["name"]
                and pod["status"]["phase"] == phase, "kubernetes-evidence-client-pod")
        spec = pod["spec"]
        require(not spec.get("runtimeClassName") and not spec.get("initContainers")
                and not spec.get("ephemeralContainers") and len(spec["containers"]) == 1,
                "kubernetes-evidence-client-extra-container")
        container = spec["containers"][0]
        require(not any(container.get(key) for key in ("command", "env", "envFrom", "startupProbe", "readinessProbe", "livenessProbe")),
                "kubernetes-evidence-client-container-controls")
        limits = fields(container["resources"], "requests limits")
        for limit in limits.values():
            fields(limit, "cpu memory")
            require(resources._quantity(limit["cpu"], cpu=True) == 2
                    and resources._quantity(limit["memory"]) == 256 * 1024**2,
                    "kubernetes-evidence-client-pod-resources")
        statuses = pod["status"]["containerStatuses"]
        require(len(statuses) == 1, "kubernetes-evidence-client-status-count")
        status = statuses[0]
        require(status["name"] == "client" and type(status["restartCount"]) is int
                and status["restartCount"] == 0 and not status.get("lastState")
                and re.fullmatch(r"containerd://[0-9a-f]{64}", status["containerID"]),
                "kubernetes-evidence-client-restarted")
        if phase == "Running":
            fields(status["state"], "running")
        else:
            stopped = fields(status["state"], "terminated")["terminated"]
            require(type(stopped["exitCode"]) is int and stopped["exitCode"] == 0
                    and type(stopped.get("signal", 0)) is int and stopped.get("signal", 0) == 0
                    and stopped.get("reason") == "Completed", "kubernetes-evidence-client-pod-exit")
    before, after = (pod["status"]["containerStatuses"][0] for pod in (ready, final))
    require(ready["metadata"]["uid"] == final["metadata"]["uid"] and ready["spec"] == final["spec"]
            and before["containerID"] == after["containerID"] and before["imageID"] == after["imageID"]
            and before["state"]["running"]["startedAt"] == after["state"]["terminated"]["startedAt"],
            "kubernetes-evidence-client-pod-replaced")


def _attachment(root, parent, expected_argv, original_ack_lines):
    value = fields(parent["attach"], "argv process_id start_time_ticks started_nanos finished_nanos exit_code reaped "
                   "output_closed forced_kill failure process_group_gone descendant_reaps subreaper streams")
    _same(value["argv"], expected_argv, "kubernetes-evidence-attach-argv")
    integer(value["process_id"], 2, 2**31 - 1)
    uint(value["start_time_ticks"])
    require(type(value["exit_code"]) is int and value["exit_code"] == 0 and value["reaped"] is True
            and value["output_closed"] is True and value["forced_kill"] is False and value["failure"] is None
            and value["process_group_gone"] is True, "kubernetes-evidence-attach-cleanup")
    state = fields(value["subreaper"], "previous enabled restored")
    integer(state["previous"], 0, 1)
    require(state["enabled"] is True and state["restored"] is True, "kubernetes-evidence-attach-subreaper")
    begin, end = uint(value["started_nanos"]), uint(value["finished_nanos"])
    require(begin <= end and end - begin <= 1800 * 10**9, "kubernetes-evidence-attach-clock")
    reaps = value["descendant_reaps"]
    require(isinstance(reaps, list) and len(reaps) <= 512, "kubernetes-evidence-attach-descendant-bound")
    identities = {value["process_id"]}
    for reap in reaps:
        fields(reap, "process_id exit_code reaped_nanos")
        pid = integer(reap["process_id"], 2, 2**31 - 1)
        require(pid not in identities and type(reap["exit_code"]) is int and reap["exit_code"] == 0
                and begin <= uint(reap["reaped_nanos"]) <= end, "kubernetes-evidence-attach-descendant")
        identities.add(pid)
    streams = fields(value["streams"], "stdin stdout stderr")
    sent = b"".join(row["line"].encode("utf-8") for row in parent["commands"])
    directory = parent["parent_directory"]
    actual = {"stdin": sent, "stdout": _read(root, directory + "/attach-stdout.ndjson", 1024**2),
              "stderr": _read(root, directory + "/attach-stderr.bin", 256 * 1024)}
    require(len(sent) <= 1024**2 and actual["stdout"] == b"".join(original_ack_lines[1:]),
            "kubernetes-evidence-attach-original-output")
    for key, data in actual.items():
        _same(fields(streams[key], "bytes sha256"), {"bytes": str(len(data)), "sha256": sha256(data)},
              "kubernetes-evidence-attach-stream-hash")
    # kubectl may emit informational stderr; its bounded original bytes are retained.
    _json(root, directory + "/attachment.json", value)
    return value


class Replay:
    def __init__(self, root, suite, journal, bootstrap, built, build_root, docker_root):
        self.root, self.suite, self.journal, self.bootstrap = root, suite, journal, bootstrap
        self.owner, self.run_id, self.profile = suite["owner"], suite["run_id"], suite["profile"]
        self.namespace = model.namespace_name(self.owner, self.run_id)
        self.lower, self.upper = uint(suite["started_nanos"]), uint(suite["finished_nanos"])
        require(self.lower <= self.upper and suite["namespace"] == self.namespace
                and bootstrap["owner"] == self.owner, "kubernetes-evidence-campaign-identity")
        selected = bootstrap["nodes"]["worker"]
        self.worker = {key: selected[key] for key in ("name", "uid", "container_id")}
        self.used = set()
        self.created_services = {}
        self.fixture_releases = docker_evidence.fixture_set(built, build_root)
        self.seeds = {density: read_json(docker_root / "seeds" / str(density) / "seed.json") for density in model.DENSITIES}
        self.observer = model.host_path(self.owner, self.run_id, "tools") + "/observer.sh"

    def call(self, ordinal, **expected):
        value = transport.get(self.journal, ordinal, **expected)
        self.used.add(ordinal)
        return value

    def api(self, ordinal, method, path, *, body=None, response=None, status=None):
        value = self.call(ordinal, provider="kubernetes", method=method, path=path, status=status)
        if body is not None:
            _same(value["request_json"], body, "kubernetes-evidence-api-request")
        if response is not None:
            _same(value["response_json"], response, "kubernetes-evidence-api-response")
        return value

    def command(self, ordinal, argv, *, response=None):
        value = self.call(ordinal, provider="docker", operation="worker-exec", argv=argv, timeout_seconds=20)
        if response is not None:
            _same(decode(value["stdout"], transport.MAX_RESPONSE), response, "kubernetes-evidence-worker-response")
        return value

    def created(self, value, manifest):
        fields(value, "pod call observed_nanos")
        path = f"/api/v1/namespaces/{self.namespace}/pods"
        selected = self.api(value["call"], "POST", path, body=manifest, response=value["pod"], status=201)
        actual = value["pod"]
        expected = {**manifest, "spec": {**manifest["spec"], "containers": [dict(manifest["spec"]["containers"][0])]}}
        del expected["spec"]["containers"][0]["resources"]
        services.subset(actual, expected)
        require(uint(selected["finished_nanos"]) <= uint(value["observed_nanos"]) <= self.upper,
                "kubernetes-evidence-created-clock")
        return {"create_started_nanos": selected["started_nanos"], "create_finished_nanos": selected["finished_nanos"]}

    def deleted(self, value, pod):
        fields(value, "name uid call absence_call")
        name, uid = pod["metadata"]["name"], pod["metadata"]["uid"]
        require(value["name"] == name and value["uid"] == uid, "kubernetes-evidence-delete-owner")
        path = f"/api/v1/namespaces/{self.namespace}/pods/{name}"
        body = {"apiVersion": "v1", "kind": "DeleteOptions", "preconditions": {"uid": uid},
                "gracePeriodSeconds": 0, "propagationPolicy": "Background"}
        deleted = self.api(value["call"], "DELETE", path, body=body)
        absent = self.api(value["absence_call"], "GET", path, status=404)
        require(uint(deleted["finished_nanos"]) <= uint(absent["started_nanos"]), "kubernetes-evidence-delete-clock")

    def downloaded(self, value, remote, local):
        fields(value, "remote local call archive inventory")
        require(value["remote"] == remote and value["local"] == local, "kubernetes-evidence-download-owner")
        selected = self.call(value["call"], provider="docker", operation="worker-download")
        require(selected["raw"]["source_path"] == remote, "kubernetes-evidence-download-source")
        artifact = fields(value["archive"], "path bytes sha256")
        verify_artifact(self.root, artifact, transport.MAX_TRANSFER)
        _same({key: artifact[key] for key in ("bytes", "sha256")}, selected["archive"], "kubernetes-evidence-download-tar")
        _same(value["inventory"], selected["inventory"], "kubernetes-evidence-download-inventory")
        docker_evidence.inventory(_path(self.root, local), value["inventory"], retained=True)

    def application(self, parent, pair, group, index):
        arm, density = group["arm"], group["density"]
        role = model.application_role(pair, group["ordinal"], arm, index)
        require(parent["role"] == role and parent["arm"] == arm and parent["density"] == density
                and parent["directory"] == "owners/" + role and parent["raw_directory"] == "owners/" + role + "/raw",
                "kubernetes-evidence-application-owner")
        remote = model.host_path(self.owner, self.run_id, "owners/" + role)
        data = model.host_path(self.owner, self.run_id, "data/" + role) if arm == "lsf" else None
        command = ["--app", arm, "--executable", "/opt/lsf/" + ("latentd" if arm == "lsf" else "optimization-native"),
                   "--output", "/output"]
        command += ["--config", "/fixtures/node.json"] if arm == "lsf" else ["--token-file", "/fixtures/token", "--service", model.SERVICES[index]]
        manifest = model.pod(self.bootstrap["images"][arm]["tag"], command, arm=arm, density=density,
            owner=self.owner, run_id=self.run_id, role=role, fixtures=model.host_path(self.owner, self.run_id, "fixtures"),
            output=remote, data=data)
        _same(parent["manifest"], manifest, "kubernetes-evidence-application-manifest")
        require(parent["remote_output"] == remote and parent["remote_data"] == data, "kubernetes-evidence-application-path")
        _json(self.root, parent["directory"] + "/manifest.json", manifest)
        _json(self.root, parent["directory"] + "/parent.json", parent)
        if arm == "lsf":
            seed = self.seeds[density]["template"]
            _same(parent["template_copy"], {"schema": "latent.optimization.docker-template-copy.v1", "density": density,
                "source_stop": seed["stop"], "inventory": seed["inventory"]}, "kubernetes-evidence-seed-copy")
            docker_evidence.inventory(_path(self.root, "inputs/data/" + role), seed["inventory"], retained=True)
        else:
            require(parent["template_copy"] is None, "kubernetes-evidence-native-catalog")
        lifecycle = self.created(parent["create"], manifest)
        require(parent["create"]["pod"]["metadata"]["uid"] == parent["pod_ready"]["metadata"]["uid"],
                "kubernetes-evidence-created-application-uid")
        path = f"/api/v1/namespaces/{self.namespace}/pods/{role}"
        self.api(parent["ready_call"], "GET", path, response=parent["pod_ready"], status=200)
        self.api(parent["final_call"], "GET", path, response=parent["pod_final"], status=200)
        container = parent["container_id"]
        for phase in ("ready", "final"):
            self.command(parent["cri_" + phase + "_call"], ["crictl", "inspect", container], response=parent["cri_" + phase])
            _image(parent["pod_" + phase], parent["cri_" + phase], arm, self.bootstrap)
        pid = parent["cri_ready"]["info"]["pid"]
        identity = self.command(parent["identity_call"], ["cat", f"/proc/{pid}/stat"])
        ticks, _ = wrapper._stat(identity["stdout"].decode(), pid)
        require(ticks == parent["start_time_ticks"], "kubernetes-evidence-application-start")
        signals = ["sh", self.observer, "signal", str(pid), container, ticks]
        stop = self.command(parent["stop_signal_call"], [*signals, "TERM"])
        require(not stop["stdout"], "kubernetes-evidence-signal-output")
        self.downloaded(parent["download"], remote, parent["raw_directory"])
        validated = resources.validate(_path(self.root, parent["raw_directory"]), arm=arm, density=density,
            pod_ready=parent["pod_ready"], pod_final=parent["pod_final"], cri_ready=parent["cri_ready"],
            cri_final=parent["cri_final"], worker=self.worker, observations=parent["observations"],
            expected_connections=(density if arm == "lsf" else 1) + 1)
        require(parent["app_process_id"] == validated["identity"]["child_pid"]
                and parent["owner_ref"] == "owner-" + container, "kubernetes-evidence-child-owner")
        self.events(parent)
        require(len(parent["snapshots"]) == 6 and len(parent["observations"]) == 6, "kubernetes-evidence-snapshot-count")
        unique = set()
        for index, (snapshot, facts) in enumerate(zip(parent["snapshots"], parent["observations"]), 1):
            fields(snapshot, "snapshot_index signal_before_nanos call observed_nanos event_sequence node_call node_finished_nanos")
            require(snapshot["snapshot_index"] == index and snapshot["event_sequence"] == index + 1
                    and snapshot["call"] not in unique, "kubernetes-evidence-snapshot-order")
            unique.add(snapshot["call"])
            signal = self.command(snapshot["call"], [*signals, "USR1"])
            require(not signal["stdout"], "kubernetes-evidence-signal-output")
            observed = self.command(snapshot["node_call"], ["sh", self.observer, "observe", str(pid), container, ticks])
            _same(node.observation(observed["stdout"], index, snapshot["observed_nanos"], snapshot["node_finished_nanos"]),
                  facts, "kubernetes-evidence-node-original")
            event_time = uint(parent["event_observations"][index + 1]["observed_nanos"])
            require(uint(snapshot["signal_before_nanos"]) <= uint(signal["started_nanos"]) <= uint(signal["finished_nanos"])
                    <= event_time <= uint(snapshot["observed_nanos"]) <= uint(observed["started_nanos"])
                    <= uint(observed["finished_nanos"]) <= uint(snapshot["node_finished_nanos"]),
                    "kubernetes-evidence-signal-observation-clock")
        require(uint(stop["finished_nanos"]) <= uint(parent["event_observations"][-1]["observed_nanos"]),
                "kubernetes-evidence-stop-observation-clock")
        self.deleted(parent["delete"], parent["pod_final"])
        return {"parent": parent, "resources": validated, "lifecycle": lifecycle,
                "connection_accounting": {"client_channels": density if arm == "lsf" else 1,
                    "observed_residual": 1, "interpretation": "consistent-with-startupProbe-under-closed-owned-path",
                    "source_peer_tracing": False}}

    def events(self, parent):
        original = _read(self.root, parent["raw_directory"] + "/events.ndjson", 10 * wrapper.EVENT_BYTES)
        events = [decode(line, wrapper.EVENT_BYTES) for line in original.splitlines()]
        require(len(events) == 9 and len(parent["event_observations"]) == 9, "kubernetes-evidence-event-population")
        offset, pending, event_index = 0, bytearray(), 0
        calls = [row for row in self.journal["rows"] if row["raw"].get("operation") == "worker-exec"
                 and row["raw"].get("argv", [])[:2] == ["tail", "-c"]
                 and row["raw"]["argv"][-1] == parent["remote_output"] + "/events.ndjson"]
        require(1 <= len(calls) <= 20_000, "kubernetes-evidence-event-reads")
        captured = bytearray()
        for row in calls:
            call = row["raw"]["ordinal"]
            selected = self.command(call, ["tail", "-c", "+" + str(offset + 1), parent["remote_output"] + "/events.ndjson"])
            block = selected["stdout"]
            offset += len(block)
            require(offset <= len(original), "kubernetes-evidence-event-prefix")
            pending.extend(block)
            captured.extend(block)
            while (end := pending.find(b"\n")) >= 0:
                line = bytes(pending[:end + 1])
                del pending[:end + 1]
                require(event_index < len(events), "kubernetes-evidence-extra-event")
                _same(decode(line, wrapper.EVENT_BYTES), events[event_index], "kubernetes-evidence-event-original")
                receipt = fields(parent["event_observations"][event_index], "sequence observed_nanos call")
                require(receipt["sequence"] == event_index and receipt["call"] == call
                        and uint(selected["finished_nanos"]) <= uint(receipt["observed_nanos"]) <= self.upper,
                        "kubernetes-evidence-event-clock")
                event_index += 1
        require(not pending and bytes(captured) == original and event_index == 9, "kubernetes-evidence-event-complete")
        return events

    def proxy_ready(self, parent, graph):
        attempts = parent["proxy_attempts"]
        require(isinstance(attempts, list) and 1 <= len(attempts) <= proxy.MAX_ATTEMPTS,
                "kubernetes-evidence-proxy-attempt-bound")
        begin, previous = uint(parent["graph_ready_nanos"]), uint(parent["graph_ready_nanos"])
        ready = uint(parent["proxy_ready_nanos"])
        require(begin <= ready <= uint(parent["finished_nanos"]) and ready - begin <= proxy.TIMEOUT_NANOS,
                "kubernetes-evidence-proxy-clock")
        seen = set()
        for index, attempt in enumerate(attempts):
            fields(attempt, "nat_call filter_call observed_nanos result")
            require(attempt["nat_call"] != attempt["filter_call"]
                    and not seen.intersection((attempt["nat_call"], attempt["filter_call"])),
                    "kubernetes-evidence-proxy-call-reused")
            seen.update((attempt["nat_call"], attempt["filter_call"]))
            nat = self.command(attempt["nat_call"], proxy.COMMANDS["nat"])
            filtered = self.command(attempt["filter_call"], proxy.COMMANDS["filter"])
            observed = uint(attempt["observed_nanos"])
            require(previous <= uint(nat["started_nanos"]) <= uint(nat["finished_nanos"])
                    <= uint(filtered["started_nanos"]) <= uint(filtered["finished_nanos"]) <= observed <= ready,
                    "kubernetes-evidence-proxy-attempt-clock")
            result = proxy.validate(nat["stdout"], filtered["stdout"], graph)
            _same(result, attempt["result"], "kubernetes-evidence-proxy-original-rules")
            require(result["ready"] is (index == len(attempts) - 1),
                    "kubernetes-evidence-proxy-first-ready")
            previous = observed
        return ready

    def group(self, parent, pair, expected, *, require_proxy=True):
        ordinal, arm, density = expected["ordinal"], expected["arm"], expected["density"]
        require(type(require_proxy) is bool, "kubernetes-evidence-proxy-policy")
        if not require_proxy:
            require(self.suite["profile"] == "smoke" and self.suite["source"]["commit"]
                    == "7a655e7967dbde1431f0ff8a5b928443a5986832"
                    and self.suite["failure"] == {"type": "EvidenceError", "reason": "kubernetes-client-ack-order-identity"}
                    and pair == 0 and ordinal == 0 and len(self.suite["groups"]) == 1
                    and parent == self.suite["groups"][0]
                    and "proxy_attempts" not in parent and "proxy_ready_nanos" not in parent,
                    "kubernetes-evidence-historical-failed-proxy-policy")
        require(parent["pair"] == pair and parent["group"] == ordinal and parent["arm"] == arm
                and parent["density"] == density, "kubernetes-evidence-group-order")
        start, end = uint(parent["started_nanos"]), uint(parent["finished_nanos"])
        require(self.lower <= start <= uint(parent["pod_create_started_nanos"]) <= uint(parent["graph_ready_nanos"]) <= end <= self.upper
                and end - start <= 600 * 10**9, "kubernetes-evidence-group-clock")
        _json(self.root, f"group-{pair}-{ordinal}.json", parent)
        desired = model.services(owner=self.owner, run_id=self.run_id, pair=pair, group=ordinal, arm=arm, density=density)
        require(len(parent["services"]) == density and 1 <= len(parent["graph_attempts"]) <= 1200
                and len(parent["owners"]) == (density if arm == "native" else 1), "kubernetes-evidence-group-population")
        current_services = {}
        for row, manifest in zip(parent["services"], desired):
            fields(row, "manifest actual call")
            _same(row["manifest"], manifest, "kubernetes-evidence-service-manifest")
            self.api(row["call"], "POST", f"/api/v1/namespaces/{self.namespace}/services",
                     body=manifest, response=row["actual"], status=201)
            services.subset(row["actual"], manifest)
            name, uid = row["actual"]["metadata"]["name"], text(row["actual"]["metadata"]["uid"], 253)
            require(name not in self.created_services and uid not in self.created_services.values(),
                    "kubernetes-evidence-service-identity-reused")
            self.created_services[name] = current_services[name] = uid
        names = {model.application_role(pair, ordinal, arm, index) for index in range(len(parent["owners"]))}
        graph = None
        for index, attempt in enumerate(parent["graph_attempts"]):
            fields(attempt, "pods_call services_call slices_call observed_nanos")
            pods = self.api(attempt["pods_call"], "GET", f"/api/v1/namespaces/{self.namespace}/pods", status=200)
            service_list = self.api(attempt["services_call"], "GET", f"/api/v1/namespaces/{self.namespace}/services", status=200)
            slices = self.api(attempt["slices_call"], "GET", f"/apis/discovery.k8s.io/v1/namespaces/{self.namespace}/endpointslices", status=200)
            require(uint(slices["finished_nanos"]) <= uint(attempt["observed_nanos"]) <= uint(parent["graph_ready_nanos"]),
                    "kubernetes-evidence-graph-clock")
            pod_items = services.list_items(pods["response_json"], "Pod")
            service_items = services.list_items(service_list["response_json"], "Service")
            slice_items = services.list_items(slices["response_json"], "EndpointSlice")
            selected_slices = _current_slices(slice_items, current_services, self.created_services,
                                              owner=self.owner, run_id=self.run_id, embedded_items=True)
            if index == len(parent["graph_attempts"]) - 1:
                selected = [pod for pod in pod_items if pod["metadata"]["name"] in names]
                graph = services.graph(service_items, selected_slices, selected,
                    owner=self.owner, run_id=self.run_id, pair=pair, group=ordinal, arm=arm, density=density,
                    worker_name=self.worker["name"], embedded_items=True)
        _same(graph, parent["graph"], "kubernetes-evidence-graph-replay")
        forwarding_ready = self.proxy_ready(parent, graph) if require_proxy else uint(parent["graph_ready_nanos"])
        owners = [self.application(value, pair, expected, index) for index, value in enumerate(parent["owners"])]
        for owner in owners:
            absent = self.api(owner["parent"]["delete"]["absence_call"], "GET",
                f"/api/v1/namespaces/{self.namespace}/pods/{owner['parent']['role']}", status=404)
            require(uint(parent["pod_create_started_nanos"]) <= uint(owner["lifecycle"]["create_started_nanos"])
                    <= uint(owner["lifecycle"]["create_finished_nanos"]) <= uint(parent["graph_ready_nanos"])
                    and uint(absent["finished_nanos"]) <= end, "kubernetes-evidence-owner-outside-group")
        by_uid = {value["parent"]["pod_ready"]["metadata"]["uid"]: value["parent"] for value in owners}
        require(set(by_uid) == set(graph["pods"]), "kubernetes-evidence-graph-owner-set")
        targets = []
        for target in graph["targets"]:
            owner = by_uid[target["pod_uid"]]
            require(owner["container_id"] == target["container_id"]
                    and owner["pod_ready"]["status"]["podIP"] == target["pod_ip"], "kubernetes-evidence-graph-container")
            targets.append({"service": target["service"], "endpoint": target["endpoint"],
                            "owner_ref": owner["owner_ref"], "app_process_id": owner["app_process_id"]})
        _same(targets, parent["targets"], "kubernetes-evidence-service-targets")
        for uid, owner in by_uid.items():
            _same(owner["service_endpoints"], {row["service"]: row["endpoint"] for row in graph["service_endpoints"][uid]},
                  "kubernetes-evidence-owner-endpoints")
        require(len(parent["windows"]) == 3, "kubernetes-evidence-window-count")
        previous = forwarding_ready
        for position, (window, stage) in enumerate(zip(parent["windows"], ("ready", "served", "final"))):
            fields(window, "stage started_nanos before sleep_begin_nanos sleep_end_nanos after finished_nanos")
            require(window["stage"] == stage and previous <= uint(window["started_nanos"])
                    <= uint(window["sleep_begin_nanos"]) <= uint(window["sleep_end_nanos"])
                    <= uint(window["finished_nanos"]) <= end
                    and uint(window["sleep_end_nanos"]) - uint(window["sleep_begin_nanos"]) >= 250_000_000,
                    "kubernetes-evidence-idle-window")
            for key, slot in (("before", 2 * position), ("after", 2 * position + 1)):
                _same(window[key], [owner["parent"]["snapshots"][slot] for owner in owners], "kubernetes-evidence-window-owners")
                for snapshot in window[key]:
                    if key == "before":
                        require(uint(window["started_nanos"]) <= uint(snapshot["signal_before_nanos"])
                                <= uint(snapshot["node_finished_nanos"]) <= uint(window["sleep_begin_nanos"]),
                                "kubernetes-evidence-window-before")
                    else:
                        require(uint(window["sleep_end_nanos"]) <= uint(snapshot["signal_before_nanos"])
                                <= uint(snapshot["node_finished_nanos"]) <= uint(window["finished_nanos"]),
                                "kubernetes-evidence-window-after")
            previous = uint(window["finished_nanos"])
        require(len(parent["service_deletes"]) == density, "kubernetes-evidence-service-delete-count")
        for row, original in zip(parent["service_deletes"], parent["services"]):
            fields(row, "uid call absence_call")
            actual = original["actual"]
            require(row["uid"] == actual["metadata"]["uid"], "kubernetes-evidence-service-delete-uid")
            path = f"/api/v1/namespaces/{self.namespace}/services/{actual['metadata']['name']}"
            self.api(row["call"], "DELETE", path, body={"apiVersion": "v1", "kind": "DeleteOptions",
                     "preconditions": {"uid": row["uid"]}})
            self.api(row["absence_call"], "GET", path, status=404)
        return {**parent, "owners": owners}

    def client_observation(self, observation, pod, stage, final=False):
        fields(observation, "stage container_id observed_nanos cri call stats stats_call stats_unavailable_reason kernel")
        container = pod["status"]["containerStatuses"][0]["containerID"].removeprefix("containerd://")
        require(observation["stage"] == stage and observation["container_id"] == container,
                "kubernetes-evidence-client-observation")
        cri = observation["cri"]
        call = self.command(observation["call"], ["crictl", "inspect", container], response=cri)
        require(uint(call["finished_nanos"]) <= uint(observation["observed_nanos"]) <= self.upper,
                "kubernetes-evidence-client-observation-clock")
        status = cri["status"]
        require(status["id"] == container and status["metadata"] == {"name": "client", "attempt": 0}
                and type(status["metadata"]["attempt"]) is int
                and status["state"] == ("CONTAINER_EXITED" if final else "CONTAINER_RUNNING"),
                "kubernetes-evidence-client-cri-state")
        require(resources.cri_timestamp(status["createdAt"]) <= resources.cri_timestamp(status["startedAt"]),
                "kubernetes-evidence-client-cri-start")
        if not final:
            require(resources.cri_timestamp(status.get("finishedAt"), unreported=True) is None,
                    "kubernetes-evidence-running-client-finished")
        _image(pod, cri, "client", self.bootstrap)
        uid = pod["metadata"]["uid"]
        require(all(status["labels"].get("io.kubernetes.pod." + key) == value for key, value in
                    (("uid", uid), ("name", pod["metadata"]["name"]), ("namespace", self.namespace))),
                "kubernetes-evidence-client-cri-pod")
        spec = cri["info"]["runtimeSpec"]
        controls = docker_model.resources("client")
        controls["pids_limit"] = model.POD_PIDS_LIMIT
        require(cri["info"]["runtimeType"] == "io.containerd.runc.v2" and cri["info"]["removing"] is False
                and spec["process"]["args"] == ["/opt/lsf/optimization-client", "--session", "/output/plan.json", "--output", "/output"]
                and spec["process"]["noNewPrivileges"] is True and spec["root"]["readonly"] is True
                and all(not items for items in spec["process"]["capabilities"].values()), "kubernetes-evidence-client-runtime")
        require(spec["linux"]["resources"]["cpu"]["quota"] == controls["cpu_quota"]
                and spec["linux"]["resources"]["cpu"]["period"] == controls["cpu_period"]
                and spec["linux"]["resources"]["memory"]["limit"] == controls["memory"], "kubernetes-evidence-client-runtime-limits")
        kernel = None
        if stage == "ready":
            kernel = self.client_kernel(observation["kernel"], cri, {"container_id": container, "uid": uid}, controls)
        else:
            require(observation["kernel"] is None, "kubernetes-evidence-extra-client-kernel")
        if final:
            require(type(status["exitCode"]) is int and status["exitCode"] == 0 and status["reason"] == "Completed"
                    and observation["stats"] is None and observation["stats_call"] is None
                    and observation["stats_unavailable_reason"] == "container-exited-cgroup-stats-unavailable",
                    "kubernetes-evidence-client-final")
            derived = None
        else:
            require(observation["stats_unavailable_reason"] is None, "kubernetes-evidence-client-stats-availability")
            stats_call = self.command(observation["stats_call"], ["crictl", "stats", "--output", "json", container],
                                      response=observation["stats"])
            require(uint(stats_call["finished_nanos"]) <= uint(observation["observed_nanos"]),
                    "kubernetes-evidence-client-stats-clock")
            derived = _client_stats(observation["stats"], container)
        return {"stage": stage, "observed_nanos": observation["observed_nanos"], "derived_stats": derived,
                "unavailable_reason": observation["stats_unavailable_reason"], "kernel": kernel}

    def client_kernel(self, value, cri, identity, controls):
        fields(value, "facts identity_call call start_time_ticks")
        pid = integer(cri["info"]["pid"], 1)
        selected = self.command(value["identity_call"], ["cat", f"/proc/{pid}/stat"])
        ticks, _ = wrapper._stat(selected["stdout"].decode(), pid)
        require(ticks == value["start_time_ticks"], "kubernetes-evidence-client-kernel-start")
        observed = self.command(value["call"], ["sh", self.observer, "client", str(pid), identity["container_id"], ticks])
        facts = fields(value["facts"], "snapshot_index started_nanos finished_nanos wrapper cgroups")
        _same(node.observation(observed["stdout"], 0, facts["started_nanos"], facts["finished_nanos"], client=True),
              facts, "kubernetes-evidence-client-kernel-original")
        require(uint(selected["finished_nanos"]) <= uint(facts["started_nanos"]) <= uint(observed["started_nanos"])
                <= uint(observed["finished_nanos"]) <= uint(facts["finished_nanos"]), "kubernetes-evidence-client-kernel-clock")
        process = fields(facts["wrapper"], "pid stat stat_after status limits cgroup mountinfo namespaces")
        require(process["pid"] == pid and wrapper._stat(wrapper._raw(process["stat"]), pid)
                == wrapper._stat(wrapper._raw(process["stat_after"]), pid)
                and wrapper._stat(wrapper._raw(process["stat"]), pid)[0] == ticks, "kubernetes-evidence-client-kernel-identity")
        status = wrapper._raw(process["status"])
        require(status is not None, "kubernetes-evidence-client-status")
        nspids = [row.split()[1:] for row in status.splitlines() if row.startswith("NSpid:")]
        require(len(nspids) == 1 and 1 <= len(nspids[0]) <= 16 and uint(nspids[0][0]) == pid
                and uint(nspids[0][-1]) == 1, "kubernetes-evidence-client-nspid")
        for name, raw in fields(process["namespaces"], "pid mnt net user").items():
            actual = wrapper._raw(raw)
            require(actual is not None and re.fullmatch(name + r":\[[0-9]+\]", actual), "kubernetes-evidence-client-namespace")
        for name in ("limits", "mountinfo"):
            wrapper._raw(process[name])
        leaf = resources._membership(process["cgroup"])
        resources._oci_path(cri["info"]["runtimeSpec"], leaf, identity["container_id"])
        return {"process": process, "cgroup": resources._ancestry(facts["cgroups"], leaf, identity, controls),
                "started_nanos": facts["started_nanos"], "finished_nanos": facts["finished_nanos"]}

    def client(self, parent, pair, groups):
        directory, role = f"clients/{pair}", model.client_role(pair)
        remote = model.host_path(self.owner, self.run_id, directory)
        plan = {"schema": model.CLIENT_PREFIX + "plan.v1", "run_id": self.run_id,
                "profile": self.profile, "pair": pair, "token_file": "/fixtures/token"}
        require(parent["pair"] == pair and parent["parent_directory"] == directory
                and parent["directory"] == directory + "/raw" and parent["remote_directory"] == remote,
                "kubernetes-evidence-client-path")
        _same(parent["plan"], plan, "kubernetes-evidence-client-plan")
        manifest = model.pod(self.bootstrap["images"]["client"]["tag"],
            ["--session", "/output/plan.json", "--output", "/output"], arm="client", density=1,
            owner=self.owner, run_id=self.run_id, role=role,
            fixtures=model.host_path(self.owner, self.run_id, "fixtures"), output=remote)
        _same(parent["manifest"], manifest, "kubernetes-evidence-client-manifest")
        for name, expected in (("manifest.json", manifest), ("parent.json", parent), ("plan.json", plan),
                               ("before-delete.json", {key: value for key, value in parent.items() if key != "delete"})):
            _json(self.root, directory + "/" + name, expected)
        lifecycle = self.created(parent["create"], manifest)
        ready, final = parent["ready"]["pod"], parent["final"]["pod"]
        _client_pods(ready, final, manifest, self.worker)
        require(parent["create"]["pod"]["metadata"]["uid"] == ready["metadata"]["uid"],
                "kubernetes-evidence-created-client-uid")
        path = f"/api/v1/namespaces/{self.namespace}/pods/{role}"
        self.api(parent["ready"]["call"], "GET", path, response=ready, status=200)
        self.api(parent["final"]["call"], "GET", path, response=final, status=200)
        self.downloaded(parent["download"], remote, parent["directory"])
        original_plan = _read(self.root, directory + "/plan.json", 4096)
        require(_read(self.root, parent["directory"] + "/plan.json", 4096) == original_plan,
                "kubernetes-evidence-client-plan-copy")
        _same(parent["downloaded_plan"], {"bytes": str(len(original_plan)), "sha256": sha256(original_plan),
                                        "byte_identical": True}, "kubernetes-evidence-client-plan-receipt")
        owner_map = {}
        for group in groups:
            for owner in group["owners"]:
                row = owner["parent"]
                endpoint = next(iter(row["service_endpoints"].values()))
                value = {"app_process_id": row["app_process_id"], "endpoint": endpoint,
                    "service_endpoints": row["service_endpoints"], "arm": group["arm"], "density": group["density"],
                    "group": group["group"], "container_id": row["container_id"]}
                if group["arm"] == "lsf":
                    value["release_digests"] = {service: self.fixture_releases[service]["release"]
                                               for service in model.SERVICES[:group["density"]]}
                require(row["owner_ref"] not in owner_map, "kubernetes-evidence-owner-reused")
                owner_map[row["owner_ref"]] = value
        derived = client_evidence.validate(_path(self.root, parent["directory"]), plan,
                                           parent["commands"], parent["acknowledgements"], owner_map)
        require(derived["process_id"] == 1, "kubernetes-evidence-client-pid1")
        for filename, key, count, line_max in (("parent-commands.ndjson", "commands", 61, 128 * 1024),
                ("parent-acks.ndjson", "acknowledgements", 68, 8192),
                ("parent-observations.ndjson", "observations", 19, 4 * 1024**2)):
            data = _read(self.root, directory + "/" + filename, 32 * 1024**2)
            rows = client_evidence._lines(data, line_max, count)
            require(len(rows) == count, "kubernetes-evidence-client-ledger-count")
            _same([row[0] for row in rows], parent[key], "kubernetes-evidence-client-ledger")
        initial = parent["initial_log"]
        fields(initial, "call calls path bytes sha256")
        require(initial["calls"] == parent["initial_log_calls"] and 1 <= len(initial["calls"]) <= 1200
                and initial["call"] == initial["calls"][-1]
                and len(set(initial["calls"])) == len(initial["calls"]), "kubernetes-evidence-client-ready-polls")
        log_path = path + "/log?container=client"
        for ordinal in initial["calls"]:
            selected = self.api(ordinal, "GET", log_path, status=200)
            if ordinal != initial["call"]:
                require(not selected["response_bytes"], "kubernetes-evidence-client-skipped-ready")
        first = _ref(self.root, {key: initial[key] for key in ("path", "bytes", "sha256")},
                     expected=directory + "/initial-pod-stdout.log", maximum=4096)
        require(selected["response_bytes"] == first, "kubernetes-evidence-client-ready-original")
        final_log = fields(parent["final_log"], "call path bytes sha256")
        final_call = self.api(final_log["call"], "GET", log_path, status=200)
        stdout = _ref(self.root, {key: final_log[key] for key in ("path", "bytes", "sha256")},
                      expected=directory + "/final-pod-stdout.log", maximum=1024**2)
        require(final_call["response_bytes"] == stdout, "kubernetes-evidence-client-final-original")
        lines = client_evidence._lines(stdout, 4096, 68)
        require(len(lines) == 68 and lines[0][2] == first, "kubernetes-evidence-client-stdout-count")
        _same([row[0] for row in lines], [row["ack"] for row in parent["acknowledgements"]],
              "kubernetes-evidence-client-original-acks")
        bootstrap_root = PurePosixPath(self.bootstrap["output"])
        argv = [str(bootstrap_root / "tools/kubectl"), "--kubeconfig", str(bootstrap_root / "private/kubeconfig"),
                "--context", "kind-" + self.owner, "--server", "https://" + self.owner + "-control-plane:6443",
                "-n", self.namespace, "attach", "-i", role, "-c", "client", "--quiet=true"]
        attach = _attachment(self.root, parent, argv, [row[2] for row in lines])
        require(uint(selected["finished_nanos"]) <= uint(parent["acknowledgements"][0]["received_nanos"])
                <= uint(attach["started_nanos"]) <= uint(parent["commands"][0]["sent_nanos"])
                and uint(parent["acknowledgements"][-1]["received_nanos"]) <= uint(attach["finished_nanos"])
                <= uint(final_call["started_nanos"]), "kubernetes-evidence-client-attach-clock")
        stages = ["ready"] + [f"group-{group}-{stage}" for group in range(6) for stage in ("ready", "served", "final")]
        require(len(parent["observations"]) == len(stages), "kubernetes-evidence-client-observation-count")
        points, previous, counters, stable = [], uint(attach["started_nanos"]), {}, None
        for observed, stage in zip(parent["observations"], stages):
            fields(observed, "stage observed_nanos observation")
            require(observed["stage"] == stage and previous <= uint(observed["observation"]["observed_nanos"])
                    <= uint(observed["observed_nanos"]) <= uint(attach["finished_nanos"]),
                    "kubernetes-evidence-client-observation-order")
            point = self.client_observation(observed["observation"], ready, stage)
            point["observed_nanos"] = observed["observed_nanos"]
            cri = observed["observation"]["cri"]
            current = _client_cri_identity(cri)
            if stable is None:
                stable = current
            _same(current, stable, "kubernetes-evidence-client-cri-replaced")
            for key in ("cpu_usage_nanos", "cpu_timestamp_nanos", "memory_timestamp_nanos"):
                number = point["derived_stats"][key]
                if number is not None:
                    require(counters.get(key, 0) <= uint(number), "kubernetes-evidence-client-counter-regressed")
                    counters[key] = uint(number)
            points.append(point)
            previous = uint(observed["observed_nanos"])
        final_observation = parent["final"]["observation"]
        points.append(self.client_observation(final_observation, final, "final", final=True))
        _same(_client_cri_identity(final_observation["cri"]), stable, "kubernetes-evidence-client-final-replaced")
        status = final_observation["cri"]["status"]
        require(resources.cri_timestamp(status["createdAt"]) <= resources.cri_timestamp(status["startedAt"])
                < resources.cri_timestamp(status["finishedAt"]),
                "kubernetes-evidence-client-cri-lifetime")
        self.client_barriers(parent, groups, derived)
        self.deleted(parent["delete"], final)
        return {"parent": parent, "evidence": derived, "resources": points, "lifecycle": lifecycle}

    def client_barriers(self, parent, groups, derived):
        commands = [decode(row["line"].encode(), 64 * 1024) for row in parent["commands"]]
        acks = {row["ack"]["command_ordinal"]: row for row in parent["acknowledgements"]
                if row["ack"]["event"] not in ("ready", "first-response")}
        for group in groups:
            ordinal = group["group"]
            begin = next(index for index, command in enumerate(commands)
                         if command["group"] == ordinal and command["command"] == "begin-group")
            finish = next(index for index, command in enumerate(commands)
                          if command["group"] == ordinal and command["command"] == "finish-group")
            _same(commands[begin]["targets"], group["targets"], "kubernetes-evidence-client-service-targets")
            require(uint(group["proxy_ready_nanos"]) <= uint(parent["commands"][begin]["sent_nanos"])
                    and uint(acks[finish]["received_nanos"]) <= uint(group["finished_nanos"]),
                    "kubernetes-evidence-client-group-clock")
            for position, window in enumerate(group["windows"]):
                index = next(index for index, command in enumerate(commands) if command["group"] == ordinal
                             and command["command"] == "inventory" and command["barrier"] == window["stage"])
                observation = parent["observations"][1 + ordinal * 3 + position]
                require(uint(acks[index]["received_nanos"]) <= uint(window["started_nanos"])
                        <= uint(window["finished_nanos"]) <= uint(observation["observation"]["observed_nanos"])
                        <= uint(observation["observed_nanos"]) <= uint(parent["commands"][index + 1]["sent_nanos"]),
                        "kubernetes-evidence-client-window-barrier")
            for owner in group["owners"]:
                call = self.command(owner["parent"]["stop_signal_call"],
                    ["sh", self.observer, "signal", str(owner["parent"]["cri_ready"]["info"]["pid"]),
                     owner["parent"]["container_id"], owner["parent"]["start_time_ticks"], "TERM"])
                require(uint(acks[finish]["received_nanos"]) <= uint(call["started_nanos"]),
                        "kubernetes-evidence-stop-before-client-dropped")
            if group["arm"] == "lsf":
                expected = model.groups(self.profile, parent["pair"])[ordinal]
                for stage, count, grants in (("ready", 0, 0), ("served", group["density"], group["density"]),
                    ("final", group["density"], sum(phase["offers"] for phase in expected["phases"]))):
                    docker_evidence.node_inventory(derived["inventories"][f"{ordinal}/{stage}"]["inventory"],
                                                   expected_entries=count, expected_grants=grants)


def _client_cri_identity(value):
    status, info = value["status"], value["info"]
    return {"container_id": status["id"], "created_at": status["createdAt"], "started_at": status["startedAt"],
            "image_ref": status["imageRef"], "sandbox_id": info["sandboxID"], "runtime_spec": info["runtimeSpec"]}


def _current_slices(rows, current, known, *, owner, run_id, embedded_items=False):
    """Replay original list membership using previously observed Service POSTs."""
    require(isinstance(rows, list) and len(rows) <= services.MAX_SLICES,
            "kubernetes-evidence-slice-list-bound")
    names, uids, selected = set(), set(), []
    for value in rows:
        services.item_kind(value, "EndpointSlice", embedded=embedded_items)
        metadata = value["metadata"]
        require(isinstance(metadata, dict), "kubernetes-evidence-slice-list-metadata")
        name, uid = text(metadata["name"], 253), text(metadata["uid"], 253)
        require(metadata["namespace"] == model.namespace_name(owner, run_id)
                and name not in names and uid not in uids, "kubernetes-evidence-slice-list-identity")
        names.add(name)
        uids.add(uid)
        refs, labels = metadata.get("ownerReferences", []), metadata.get("labels", {})
        require(isinstance(refs, list) and len(refs) == 1 and isinstance(refs[0], dict) and isinstance(labels, dict),
                "kubernetes-evidence-slice-owner-count")
        service = text(labels.get("kubernetes.io/service-name"), 253)
        require(service in known and refs[0].get("apiVersion") == "v1" and refs[0].get("kind") == "Service"
                and refs[0].get("name") == service and refs[0].get("uid") == known[service]
                and refs[0].get("controller") is True
                and labels.get("endpointslice.kubernetes.io/managed-by") == "endpointslice-controller.k8s.io"
                and all(key not in labels or labels[key] == expected for key, expected in
                        ((model.OWNER_LABEL, owner), (model.RUN_LABEL, run_id))),
                "kubernetes-evidence-slice-owner")
        if service in current:
            require(current[service] == known[service], "kubernetes-evidence-slice-current-owner")
            selected.append(value)
    return selected


def validate(root: Path, *, suite: dict, journal: dict, bootstrap: dict, build_root: Path, docker_root: Path) -> dict:
    """Replay components; the caller must additionally qualify the campaign closure."""
    root, build_root, docker_root = Path(root), Path(build_root), Path(docker_root)
    require(suite["failure"] is None, "kubernetes-evidence-failed-campaign")
    _same(suite["plan"], model.plan(suite["profile"], owner=suite["owner"]), "kubernetes-evidence-plan")
    _json(root, "plan.json", suite["plan"])
    _json(root, "suite.json", suite, 128 * 1024**2)
    original = _ref(docker_root, suite["docker_suite"], expected="suite.json", maximum=64 * 1024**2)
    require(decode(original, 64 * 1024**2)["profile"] == "full", "kubernetes-evidence-original-full")
    built = build.validate_receipt(read_json(build_root / "docker-builds.json"), build_root)
    _same(suite["build_source"], built["source"], "kubernetes-evidence-build-source")
    replay = Replay(root, suite, journal, bootstrap, built, build_root, docker_root)
    pairs = model.repetitions(suite["profile"])
    require(len(suite["groups"]) == pairs * 6 and len(suite["clients"]) == pairs, "kubernetes-evidence-population")
    groups, clients, pods, containers, previous = [], [], set(), set(), replay.lower
    for pair in range(pairs):
        selected = []
        for expected in model.groups(suite["profile"], pair):
            group = replay.group(suite["groups"][pair * 6 + expected["ordinal"]], pair, expected)
            require(previous <= uint(group["started_nanos"]), "kubernetes-evidence-overlapping-groups")
            previous = uint(group["finished_nanos"])
            for owner in group["owners"]:
                parent = owner["parent"]
                uid, cid = parent["pod_ready"]["metadata"]["uid"], parent["container_id"]
                require(uid not in pods and cid not in containers, "kubernetes-evidence-reused-owner")
                pods.add(uid)
                containers.add(cid)
            selected.append(group)
        client = replay.client(suite["clients"][pair], pair, selected)
        status = client["parent"]["ready"]["pod"]
        uid = status["metadata"]["uid"]
        cid = status["status"]["containerStatuses"][0]["containerID"].removeprefix("containerd://")
        require(uid not in pods and cid not in containers, "kubernetes-evidence-reused-client")
        pods.add(uid)
        containers.add(cid)
        groups.extend(selected)
        clients.append(client)
    total = sum(uint(row["evidence"]["offers"]) for row in clients)
    require(total == uint(suite["plan"]["workload"]["logical_offers"]), "kubernetes-evidence-total-offers")
    return {"groups": groups, "clients": clients, "docker_suite": suite["docker_suite"],
            "transport_calls_used": sorted(replay.used),
            "counts": {"offers": str(total), "successful": str(total), "seed_management_rpcs": "0", "seed_invokes": "0",
                       "measured_application_owners": 44 * pairs, "client_owners": pairs}}
