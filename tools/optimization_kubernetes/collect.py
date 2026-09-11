"""Finite owned Kubernetes lifecycle around the unchanged infrastructure client."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import time

from tools.artifact_identity_runner.files import fingerprint, reference, retain, write_json
from tools.optimization_docker import build, fixtures
from tools.optimization_docker.engine import Engine
from tools.optimization_docker.owned import encoded, stamp
from tools.optimization_evidence.common import read_json, require, text
from tools.optimization_revision_runner.build import source
from . import files, model, node, proxy, services
from .applications import Application, idle_window
from .session import Session
from .transport import Journal, Kubernetes, Worker, cleanup_owner, private_tls


def _current_slices(rows, current, known, *, owner, run_id, embedded_items=False):
    """Retain the API list; only known prior Service owners may linger in it."""
    require(isinstance(rows, list) and len(rows) <= services.MAX_SLICES,
            "kubernetes-endpoint-list-bound")
    selected, names, identifiers = [], set(), set()
    namespace = model.namespace_name(owner, run_id)
    for row in rows:
        services.item_kind(row, "EndpointSlice", embedded=embedded_items)
        metadata = row["metadata"]
        require(isinstance(metadata, dict), "kubernetes-endpoint-list-metadata")
        name, uid = text(metadata.get("name"), 253), text(metadata.get("uid"), 253)
        require(metadata.get("namespace") == namespace and name not in names and uid not in identifiers,
                "kubernetes-endpoint-list-identity")
        names.add(name)
        identifiers.add(uid)
        labels, refs = metadata.get("labels", {}), metadata.get("ownerReferences", [])
        require(isinstance(labels, dict), "kubernetes-endpoint-list-labels")
        service = text(labels.get("kubernetes.io/service-name"), 253)
        require(isinstance(refs, list) and len(refs) == 1 and isinstance(refs[0], dict)
                and service in known and refs[0].get("apiVersion") == "v1"
                and refs[0].get("kind") == "Service" and refs[0].get("name") == service
                and refs[0].get("uid") == known[service] and refs[0].get("controller") is True
                and labels.get("endpointslice.kubernetes.io/managed-by") == "endpointslice-controller.k8s.io",
                "kubernetes-endpoint-list-owner")
        require(all(key not in labels or labels[key] == expected for key, expected in
                    ((model.OWNER_LABEL, owner), (model.RUN_LABEL, run_id))), "kubernetes-endpoint-list-labels")
        if service in current:
            require(current[service] == known[service], "kubernetes-endpoint-current-owner")
            selected.append(row)
    return selected


class Campaign:
    def __init__(self, args, repository):
        self.repository = repository.resolve()
        require(os.name == "posix", "kubernetes-linux-collector")
        self.source = source(self.repository)
        require(self.source["commit"] == args.source_ref, "kubernetes-collector-source-ref")
        self.bootstrap_path = args.bootstrap.resolve()
        self.bootstrap = read_json(self.bootstrap_path)
        require(self.bootstrap["status"] == "connected-no-workload" and self.bootstrap["failure"] is None,
                "kubernetes-unqualified-bootstrap")
        self.owner = self.bootstrap["owner"]
        self.profile, self.run_id = args.profile, args.run_id
        self.namespace = model.namespace_name(self.owner, self.run_id)
        self.root = args.output.absolute()
        require(self.root.parent == self.bootstrap_path.parent and self.root.name == self.run_id
                and not self.root.exists(), "kubernetes-fresh-campaign-root")
        self.root.mkdir()
        for name in ("clients", "owners", "inputs", "transfers", "collector"):
            (self.root / name).mkdir()
        self.plan = model.plan(self.profile, owner=self.owner)
        self.workload = self.plan["workload"]
        write_json(self.root / "plan.json", self.plan)
        self.started = stamp()
        self.deadline = int(self.started) + self.workload["collection_timeout_seconds"] * 10**9
        self.journal = Journal(self.root / "api.ndjson")
        self.progress_journal = Journal(self.root / "progress.ndjson", maximum=32 * 1024**2)
        self.engine = Engine()
        self.worker_record = self.bootstrap["nodes"]["worker"]
        self.worker_name = self.worker_record["name"]
        self.worker = Worker(self.engine, self.worker_record["container_id"], self.owner, self.journal)
        self.kubectl = self.bootstrap_path.parent / "tools/kubectl"
        self.kubeconfig = self.bootstrap_path.parent / "private/kubeconfig"
        self.private_directory = self.bootstrap_path.parent / "private" / ("tls-" + self.run_id)
        self.api = Kubernetes(self.owner + "-control-plane", private_tls(self.kubeconfig, self.private_directory), self.journal)
        self.remote_root = model.host_path(self.owner, self.run_id)
        self.namespace_uid = None
        self.namespace_attempted = self.remote_attempted = False
        self.pending_pods, self.pods, self.delete_receipts = set(), {}, []
        self.preparations, self.transfers, self.groups, self.clients, self.sessions = [], [], [], [], []
        self.applications = []
        self.created_services = {}
        self.build_root, self.docker_root = args.build_root.resolve(), args.docker_run.resolve()
        self.built = build.validate_receipt(read_json(self.build_root / "docker-builds.json"), self.build_root)
        self.docker_suite = read_json(self.docker_root / "suite.json")
        require(self.docker_suite["profile"] == "full" and self.docker_suite["failure"] is None
                and not self.docker_suite["cleanup"]["errors"]
                and self.docker_suite["build_source"] == self.built["source"], "kubernetes-docker-handoff")
        original_images = read_json(self.build_root / "images.json")["images"]
        require({arm: item["original_docker_image_id"] for arm, item in self.bootstrap["images"].items()}
                == {arm: item["image_id"] for arm, item in original_images.items()}, "kubernetes-original-image-handoff")
        self.images = {arm: item["tag"] for arm, item in self.bootstrap["images"].items()}
        self.seeds = {}
        for density in model.DENSITIES:
            seed = read_json(self.docker_root / "seeds" / str(density) / "seed.json")
            path = self.docker_root / seed["template_path"]
            require(path.resolve().is_relative_to(self.docker_root)
                    and fixtures.seal_template(path, density=density, stop_receipt=seed["template"]["stop"]) == seed["template"],
                    "kubernetes-original-seed-changed")
            self.seeds[density] = {"path": path, "template": seed["template"],
                                  "receipt": reference(self.docker_root / "seeds" / str(density) / "seed.json", self.docker_root)}
        names = set(build.input_names(self.repository))
        names.add("tools/optimization_kubernetes/observer.sh")
        self.collector_inputs = {name: retain(self.repository / name, self.root / "collector/source" / name, self.root)
                                 for name in sorted(names) if name.endswith((".py", "/observer.sh"))}
        self.build_inputs = {name: {"sha256": fingerprint(self.repository / name)[0],
                                   "bytes": str(fingerprint(self.repository / name)[1])}
                             for name in sorted(names) if not name.endswith((".py", "/observer.sh"))}
        require(self.build_inputs == {name: {"sha256": row["sha256"], "bytes": row["bytes"]}
                    for name, row in self.built["inputs"].items() if not name.endswith(".py")},
                "kubernetes-original-binary-inputs-changed")
        self.background = []

    def progress(self, kind, value):
        require(time.monotonic_ns() < self.deadline, "kubernetes-campaign-deadline")
        self.progress_journal.append({"kind": kind, "observed_nanos": stamp(), "value": value})

    def reserve(self):
        inventory = files.campaign_inventory(self.root)
        require(int(inventory["bytes"]) <= model.MAX_TOTAL_BYTES - 64 * 1024**2,
                "kubernetes-evidence-reserve")

    def prepare_directory(self, relative, local_source=None):
        destination = model.host_path(self.owner, self.run_id, relative)
        self.worker.command(["mkdir", "-p", str(Path(destination).parent)])
        _, create_call = self.worker.command(["mkdir", "-m", "700", destination])
        row = {"relative": relative, "destination": destination, "create_call": create_call,
               "transfer": None, "upload_call": None}
        if local_source is not None:
            archive = self.root / "transfers" / f"upload-{len(self.preparations):04d}.tar"
            row["transfer"] = files.create_archive(local_source, archive)
            row["archive"] = reference(archive, self.root)
            row["upload_call"] = self.worker.upload(archive, destination)
        self.preparations.append(row)
        self.progress("directory-prepared", row)
        return destination

    def download_directory(self, remote, local):
        archive = self.root / "transfers" / f"download-{len(self.transfers):04d}.tar"
        call = files.download(self.worker, remote, local, archive)
        row = {"remote": remote, "local": local.relative_to(self.root).as_posix(), "call": call,
               "archive": reference(archive, self.root), "inventory": fixtures.inventory(local)}
        self.transfers.append(row)
        return row

    def create_pod(self, manifest):
        role = manifest["metadata"]["name"]
        require(role not in self.pending_pods, "kubernetes-pod-name-reused")
        self.pending_pods.add(role)
        self.progress("pod-create-attempt", manifest)
        value, call = self.api.call("POST", f"/api/v1/namespaces/{self.namespace}/pods", manifest, expected=(201,))
        require(value["metadata"]["name"] == role and value["metadata"]["namespace"] == self.namespace,
                "kubernetes-created-pod-name")
        self.pods[role] = value["metadata"]["uid"]
        result = {"pod": value, "call": call, "observed_nanos": stamp()}
        self.progress("pod-created", result)
        return result

    def wait_pod(self, name, condition="running"):
        until = min(time.monotonic_ns() + 120 * 10**9, self.deadline)
        while time.monotonic_ns() < until:
            pod, call = self.api.call("GET", f"/api/v1/namespaces/{self.namespace}/pods/{name}")
            require(pod["metadata"]["uid"] == self.pods[name], "kubernetes-pod-uid-changed")
            status = pod.get("status", {})
            states = status.get("containerStatuses", [])
            require(status.get("phase") != "Failed" and all(row.get("restartCount", 0) == 0 for row in states),
                    "kubernetes-pod-failed-or-restarted")
            if condition == "running" and status.get("phase") == "Running" and len(states) == 1 \
                    and states[0].get("ready") is True and states[0].get("started") is True:
                return pod, call
            if condition == "succeeded" and status.get("phase") == "Succeeded" and len(states) == 1 \
                    and states[0].get("state", {}).get("terminated", {}).get("exitCode") == 0:
                return pod, call
            time.sleep(0.1)
        raise TimeoutError("kubernetes-pod-readiness-or-exit-deadline")

    def delete_pod(self, pod):
        name, uid = pod["metadata"]["name"], pod["metadata"]["uid"]
        require(self.pods.get(name) == uid and pod["metadata"]["namespace"] == self.namespace,
                "kubernetes-delete-pod-identity")
        path = f"/api/v1/namespaces/{self.namespace}/pods/{name}"
        body = {"apiVersion": "v1", "kind": "DeleteOptions", "preconditions": {"uid": uid},
                "gracePeriodSeconds": 0 if pod.get("status", {}).get("phase") == "Succeeded" else 40,
                "propagationPolicy": "Background"}
        _, call = self.api.call("DELETE", path, body, expected=(200, 202))
        until = time.monotonic() + 60
        while time.monotonic() < until:
            value, absent = self.api.call("GET", path, expected=(200, 404))
            if value.get("kind") == "Status" and value.get("code") == 404:
                del self.pods[name]
                row = {"name": name, "uid": uid, "call": call, "absence_call": absent}
                self.delete_receipts.append(row)
                return row
            require(value["metadata"]["uid"] == uid, "kubernetes-delete-replaced-pod")
            time.sleep(0.1)
        raise TimeoutError("kubernetes-pod-delete-deadline")

    def observe_client(self, pod, stage):
        container = pod["status"]["containerStatuses"][0]["containerID"].removeprefix("containerd://")
        cri, call = self.worker.json(["crictl", "inspect", container])
        require(cri["status"]["id"] == container, "kubernetes-client-cri-id")
        if cri["status"]["state"] == "CONTAINER_RUNNING":
            stats, stats_call = self.worker.json(["crictl", "stats", "--output", "json", container])
            unavailable = None
        else:
            stats = stats_call = None
            unavailable = "container-exited-cgroup-stats-unavailable"
        kernel = None
        if stage == "ready":
            pid = cri["info"]["pid"]
            raw, identity_call = self.worker.command(["cat", f"/proc/{pid}/stat"])
            head, separator, tail = raw.decode().rpartition(") ")
            require(separator and head.startswith(str(pid) + " ("), "kubernetes-client-host-pid")
            ticks, began = tail.split()[19], stamp()
            raw, kernel_call = self.worker.command(["sh", self.observer, "client", str(pid), container, ticks])
            kernel = {"facts": node.observation(raw, 0, began, stamp(), client=True),
                      "identity_call": identity_call, "call": kernel_call, "start_time_ticks": ticks}
        return {"stage": stage, "container_id": container, "observed_nanos": stamp(),
                "cri": cri, "call": call, "stats": stats, "stats_call": stats_call,
                "stats_unavailable_reason": unavailable, "kernel": kernel}

    def observe_cluster(self, stage):
        rows = []
        for role, node_record in self.bootstrap["nodes"].items():
            value, receipt = self.engine.request("GET", "/containers/" + node_record["container_id"]
                                                  + "/stats?stream=false&one-shot=true")
            from .transport import blob
            call = self.journal.append({"provider": "docker", "operation": "node-stats", "role": role,
                "container_id": node_record["container_id"], "receipt": receipt, "response": blob(self.engine.last_body)})["ordinal"]
            rows.append({"role": role, "container_id": node_record["container_id"], "call": call,
                         "stats": value, "observed_nanos": stamp()})
        result = {"stage": stage, "observations": rows}
        self.background.append(result)
        return result

    def initialize(self):
        self.remote_attempted = True
        _, self.remote_create_call = self.worker.command(["mkdir", "-m", "700", self.remote_root])
        self.remote_fixtures = self.prepare_directory("fixtures", self.build_root / "fixtures")
        tool_inputs = self.root / "inputs/tools"
        tool_inputs.mkdir()
        files.copy_file(self.repository / "tools/optimization_kubernetes/observer.sh", tool_inputs / "observer.sh")
        self.observer = self.prepare_directory("tools", tool_inputs) + "/observer.sh"
        path = "/api/v1/namespaces/" + self.namespace
        _, self.namespace_absence_call = self.api.call("GET", path, expected=(404,))
        self.namespace_attempted = True
        actual, self.namespace_create_call = self.api.call("POST", "/api/v1/namespaces",
            model.namespace(self.owner, self.run_id), expected=(201,))
        self.namespace_uid = actual["metadata"]["uid"]
        self.namespace_create = actual
        self.observe_cluster("idle-before-start")
        time.sleep(0.25)
        self.observe_cluster("idle-before-end")

    def group(self, pair, group, client):
        began = stamp()
        arm, density, ordinal = group["arm"], group["density"], group["ordinal"]
        self.reserve()
        apps = [Application(self, pair, group, index) for index in range(density if arm == "native" else 1)]
        self.applications.extend(apps)
        service_rows = []
        current_services = {}
        for manifest in model.services(owner=self.owner, run_id=self.run_id, pair=pair, group=ordinal,
                                       arm=arm, density=density):
            actual, call = self.api.call("POST", f"/api/v1/namespaces/{self.namespace}/services", manifest, expected=(201,))
            services.subset(actual, manifest)
            name, uid = actual["metadata"]["name"], text(actual["metadata"].get("uid"), 253)
            require(name not in self.created_services and uid not in self.created_services.values(),
                    "kubernetes-service-identity-reused")
            self.created_services[name] = current_services[name] = uid
            service_rows.append({"manifest": manifest, "actual": actual, "call": call})
        # All owned files and Services exist before the first application Pod is submitted.
        pod_create_started = stamp()
        for app in apps:
            app.create()
        for app in apps:
            app.ready()
        until = min(time.monotonic_ns() + 120 * 10**9, self.deadline)
        graph_attempts = []
        while time.monotonic_ns() < until:
            pods, pods_call = self.api.call("GET", f"/api/v1/namespaces/{self.namespace}/pods")
            service_list, service_call = self.api.call("GET", f"/api/v1/namespaces/{self.namespace}/services")
            slices, slices_call = self.api.call("GET", f"/apis/discovery.k8s.io/v1/namespaces/{self.namespace}/endpointslices")
            pod_items = services.list_items(pods, "Pod")
            service_items = services.list_items(service_list, "Service")
            slice_items = services.list_items(slices, "EndpointSlice")
            selected = [row for row in pod_items if row["metadata"]["name"] in {app.role for app in apps}]
            graph_attempts.append({"pods_call": pods_call, "services_call": service_call, "slices_call": slices_call,
                                   "observed_nanos": stamp()})
            current_slices = _current_slices(slice_items, current_services, self.created_services,
                                             owner=self.owner, run_id=self.run_id, embedded_items=True)
            endpoints = [entry for row in current_slices for entry in row.get("endpoints", [])]
            if len(endpoints) == density and all(entry.get("conditions", {}).get("ready") is True for entry in endpoints):
                graph = services.graph(service_items, current_slices, selected, owner=self.owner,
                    run_id=self.run_id, pair=pair, group=ordinal, arm=arm, density=density,
                    worker_name=self.worker_name, embedded_items=True)
                break
            time.sleep(0.1)
        else:
            raise TimeoutError("kubernetes-service-endpoint-deadline")
        graph_ready = stamp()
        programmed = proxy.wait(self.worker, graph, deadline=self.deadline,
            progress=lambda attempt: self.progress("proxy-attempt", {"pair": pair, "group": ordinal, **attempt}))
        by_uid = {app.uid: app for app in apps}
        targets = [{"service": item["service"], "endpoint": item["endpoint"],
                    "owner_ref": by_uid[item["pod_uid"]].owner_ref,
                    "app_process_id": by_uid[item["pod_uid"]].app_pid} for item in graph["targets"]]
        for app in apps:
            app.record["service_endpoints"] = {item["service"]: item["endpoint"] for item in graph["service_endpoints"][app.uid]}
        cluster_before = self.observe_cluster(f"pair-{pair}-group-{ordinal}-ready")
        client.command("begin-group", ordinal, targets=targets)
        client.command("inventory", ordinal, barrier="ready")
        windows = [idle_window(apps, "ready")]
        client.observe(f"group-{ordinal}-ready")
        for phase in group["phases"]:
            client.command("phase", ordinal, phase=phase["ordinal"])
            if phase["ordinal"] == 0:
                client.command("inventory", ordinal, barrier="served")
                windows.append(idle_window(apps, "served"))
                client.observe(f"group-{ordinal}-served")
        client.command("inventory", ordinal, barrier="final")
        windows.append(idle_window(apps, "final"))
        client.observe(f"group-{ordinal}-final")
        cluster_after = self.observe_cluster(f"pair-{pair}-group-{ordinal}-final")
        client.command("finish-group", ordinal)
        owners = [app.finish() for app in apps]
        service_deletes = []
        for row in service_rows:
            item = row["actual"]
            path = f"/api/v1/namespaces/{self.namespace}/services/{item['metadata']['name']}"
            body = {"apiVersion": "v1", "kind": "DeleteOptions", "preconditions": {"uid": item["metadata"]["uid"]}}
            _, call = self.api.call("DELETE", path, body, expected=(200, 202))
            _, absent = self.api.call("GET", path, expected=(404,))
            service_deletes.append({"uid": item["metadata"]["uid"], "call": call, "absence_call": absent})
        value = {"pair": pair, "group": ordinal, "arm": arm, "density": density,
            "started_nanos": began, "pod_create_started_nanos": pod_create_started,
            "graph_ready_nanos": graph_ready, "finished_nanos": stamp(), "graph_attempts": graph_attempts,
            "proxy_attempts": programmed["attempts"], "proxy_ready_nanos": programmed["ready_nanos"],
            "services": service_rows, "graph": graph, "targets": targets, "owners": owners, "windows": windows,
            "cluster_before": cluster_before, "cluster_after": cluster_after, "service_deletes": service_deletes}
        require(int(value["finished_nanos"]) - int(began) <= 600 * 10**9, "kubernetes-group-deadline")
        self.groups.append(value)
        write_json(self.root / f"group-{pair}-{ordinal}.json", value)
        self.progress("group-complete", {"pair": pair, "group": ordinal, "arm": arm, "density": density})
        self.reserve()
        print(f"completed pair={pair} group={ordinal} arm={arm} density={density}", flush=True)

    def cleanup(self, *, failed=False):
        """Remove only this run's UID-bound namespace and stopped CRI objects."""
        result = {"schema": model.PREFIX + "cleanup.v1", "namespace": self.namespace,
            "namespace_uid": self.namespace_uid, "started_nanos": stamp(), "errors": [],
            "attachments": [], "pods": self.delete_receipts, "namespace_calls": [],
            "cri_calls": [], "cri_removed": [], "remote_removed": False,
            "namespace_absent": not self.namespace_attempted, "private_tls_removed": False,
            "failure_diagnostics": []}
        for session in self.sessions:
            try:
                result["attachments"].append(session.close(force=True))
            except BaseException as error:
                result["errors"].append({"stage": "attach", "type": type(error).__name__, "reason": str(error)[:1024]})
        try:
            if self.namespace_attempted:
                path = "/api/v1/namespaces/" + self.namespace
                actual, call = self.api.call("GET", path, expected=(200, 404))
                result["namespace_calls"].append(call)
                if actual.get("kind") == "Status" and actual.get("code") == 404:
                    result["namespace_absent"] = True
                else:
                    self._namespace_identity(actual)
                    if self.namespace_uid is None:
                        self.namespace_uid = actual["metadata"]["uid"]
                        result["namespace_uid"] = self.namespace_uid
                    require(actual["metadata"]["uid"] == self.namespace_uid,
                            "kubernetes-cleanup-namespace-replaced")
                    pods, call = self.api.call("GET", path + "/pods")
                    result["namespace_calls"].append(call)
                    for pod in services.list_items(pods, "Pod"):
                        self._namespace_pod(pod, embedded=True)
                        name, uid = pod["metadata"]["name"], pod["metadata"]["uid"]
                        require(name in self.pending_pods and self.pods.get(name, uid) == uid,
                                "kubernetes-cleanup-unowned-pod")
                        self.pods[name] = uid
                        self.delete_pod(pod)
                    _, call = self.api.call("DELETE", path, {"apiVersion": "v1", "kind": "DeleteOptions",
                        "preconditions": {"uid": self.namespace_uid}, "propagationPolicy": "Foreground"},
                        expected=(200, 202))
                    result["namespace_calls"].append(call)
                    until = time.monotonic() + 90
                    while time.monotonic() < until:
                        actual, call = self.api.call("GET", path, expected=(200, 404))
                        result["namespace_calls"].append(call)
                        if actual.get("kind") == "Status" and actual.get("code") == 404:
                            result["namespace_absent"] = True
                            break
                        require(actual["metadata"]["uid"] == self.namespace_uid,
                                "kubernetes-cleanup-namespace-replaced")
                        time.sleep(0.2)
                    require(result["namespace_absent"], "kubernetes-cleanup-namespace-timeout")
            # Kubelet can retain stopped sandbox metadata after API deletion.
            # Explicitly remove only records belonging to the verified Pod UIDs.
            for command, key, state_key, dead, removal in (
                    (["crictl", "ps", "-a", "-o", "json"], "containers", "state", "CONTAINER_EXITED", "rm"),
                    (["crictl", "pods", "-o", "json"], "items", "state", "SANDBOX_NOTREADY", "rmp")):
                value, call = self.worker.json(command)
                result["cri_calls"].append(call)
                for item in value.get(key, []):
                    labels = item.get("labels", {})
                    if labels.get("io.kubernetes.pod.namespace") != self.namespace:
                        continue
                    identifier = item.get("id", "")
                    require(re.fullmatch(r"[0-9a-f]{64}", identifier)
                            and item.get(state_key) == dead
                            and any(row["uid"] == labels.get("io.kubernetes.pod.uid")
                                    and row["name"] == labels.get("io.kubernetes.pod.name")
                                    for row in self.delete_receipts), "kubernetes-cleanup-cri-owner")
                    policy = {"cleanup_log_owner": cleanup_owner(item)} if removal == "rm" else {}
                    _, call = self.worker.command(["crictl", removal, identifier], **policy)
                    result["cri_removed"].append({"id": identifier, "operation": removal, "call": call})
                after, call = self.worker.json(command)
                result["cri_calls"].append(call)
                require(not any(row.get("labels", {}).get("io.kubernetes.pod.namespace") == self.namespace
                                for row in after.get(key, [])), "kubernetes-cleanup-cri-remains")
            require(not self.pods and result["namespace_absent"], "kubernetes-cleanup-pods-remain")
            if failed:
                # Quiesce processes first, then preserve every unfinished output.
                # If a bounded download fails, retain the worker tree for explicit recovery.
                retained = {row["remote"] for row in self.transfers}
                for index, row in enumerate(self.preparations):
                    if not row["relative"].startswith(("owners/", "clients/")) or row["destination"] in retained:
                        continue
                    local = self.root / "failure-outputs" / str(index)
                    local.parent.mkdir(exist_ok=True)
                    diagnostic = self.download_directory(row["destination"], local)
                    result["failure_diagnostics"].append(diagnostic)
            if self.remote_attempted:
                expected = model.host_path(self.owner, self.run_id)
                require(expected == self.remote_root, "kubernetes-cleanup-remote-owner")
                # Shell source is constant; the canonical owner path is an argv value.
                script = ('set -eu; p="$1"; [ "$(readlink -f -- "$p")" = "$p" ]; '
                          '[ ! -L "$p" ]; if [ -d "$p" ]; then '
                          'rm -rf --one-file-system -- "$p"; fi; [ ! -e "$p" ]')
                _, result["remote_remove_call"] = self.worker.command(["sh", "-c", script, "owned-cleanup", expected])
                result["remote_removed"] = True
        except BaseException as error:
            result["errors"].append({"stage": "owned-resources", "type": type(error).__name__, "reason": str(error)[:2048]})
        try:
            require(self.private_directory.parent == self.bootstrap_path.parent / "private"
                    and self.private_directory.name == "tls-" + self.run_id
                    and not self.private_directory.is_symlink(), "kubernetes-cleanup-private-owner")
            for name in ("ca.pem", "client.pem", "client.key"):
                path = self.private_directory / name
                require(path.is_file() and not path.is_symlink(), "kubernetes-cleanup-private-file")
            require({path.name for path in self.private_directory.iterdir()} == {"ca.pem", "client.pem", "client.key"},
                    "kubernetes-cleanup-private-extra-file")
            for name in ("ca.pem", "client.pem", "client.key"):
                (self.private_directory / name).unlink()
            self.private_directory.rmdir()
            result["private_tls_removed"] = True
        except BaseException as error:
            result["errors"].append({"stage": "private-tls", "type": type(error).__name__, "reason": str(error)[:1024]})
        result.update(finished_nanos=stamp(), remaining_pods=dict(self.pods))
        write_json(self.root / "cleanup.json", result)
        return result

    def _namespace_identity(self, value):
        require(value.get("kind") == "Namespace" and value["metadata"]["name"] == self.namespace
                and all(value["metadata"].get("labels", {}).get(key) == expected
                        for key, expected in model.labels(self.owner, self.run_id).items()),
                "kubernetes-cleanup-namespace-owner")

    def _namespace_pod(self, value, *, embedded=False):
        services.item_kind(value, "Pod", embedded=embedded)
        metadata = value["metadata"]
        require(metadata["namespace"] == self.namespace
                and all(metadata.get("labels", {}).get(key) == expected
                        for key, expected in model.labels(self.owner, self.run_id, metadata["name"]).items()),
                "kubernetes-cleanup-pod-owner")

    def execute(self):
        failure, source_after = None, None
        try:
            self.initialize()
            for pair in range(self.workload["repetitions"]):
                client = Session(self, pair)
                self.sessions.append(client)
                for group in model.groups(self.profile, pair):
                    self.group(pair, group, client)
                self.clients.append(client.finish())
            self.observe_cluster("idle-after-start")
            time.sleep(0.25)
            self.observe_cluster("idle-after-end")
            source_after = source(self.repository)
            require(source_after == self.source, "kubernetes-collector-source-changed")
        except BaseException as error:
            failure = {"type": type(error).__name__, "reason": str(error)[:2048]}
        finally:
            cleanup = self.cleanup(failed=failure is not None)
            suite = {"schema": model.PREFIX + "suite.v1", "profile": self.profile,
                "run_id": self.run_id, "owner": self.owner, "namespace": self.namespace,
                "namespace_uid": self.namespace_uid, "plan": self.plan,
                "source": self.source, "source_after": source_after, "build_source": self.built["source"],
                "build_receipt": reference(self.build_root / "docker-builds.json", self.build_root),
                "docker_suite": reference(self.docker_root / "suite.json", self.docker_root),
                "bootstrap": reference(self.bootstrap_path, self.bootstrap_path.parent), "images": self.images,
                "seeds": {str(key): {"template": row["template"], "receipt": row["receipt"]}
                          for key, row in self.seeds.items()},
                "collection_path": str(self.root), "build_path": str(self.build_root),
                "docker_path": str(self.docker_root), "bootstrap_path": str(self.bootstrap_path),
                "collector_inputs": self.collector_inputs, "build_inputs": self.build_inputs,
                "started_nanos": self.started, "finished_nanos": stamp(), "background": self.background,
                "namespace_create": getattr(self, "namespace_create", None),
                "namespace_create_call": getattr(self, "namespace_create_call", None),
                "namespace_absence_call": getattr(self, "namespace_absence_call", None),
                "remote_create_call": getattr(self, "remote_create_call", None),
                "groups": [{**{key: row[key] for key in ("pair", "group", "arm", "density")},
                            "artifact": reference(self.root / f"group-{row['pair']}-{row['group']}.json", self.root)}
                           for row in self.groups],
                "clients": self.clients, "preparations": self.preparations,
                "transfers": self.transfers, "cleanup": cleanup, "failure": failure}
            write_json(self.root / "suite.json", suite)
        print(json.dumps({"profile": self.profile, "groups": len(self.groups), "clients": len(self.clients),
                          "failure": failure, "cleanup_errors": cleanup["errors"]}), flush=True)
        self.reserve()
        return 0 if failure is None and not cleanup["errors"] else 1


def execute(args, repository):
    try:
        campaign = Campaign(args, repository)
    except BaseException as error:
        if args.output.is_dir() and not (args.output / "preflight-failure.json").exists():
            write_json(args.output / "preflight-failure.json", {"type": type(error).__name__,
                "reason": str(error)[:2048], "guest_invokes": 0, "workload_started": False})
        raise
    return campaign.execute()
