"""Offline ownership and readiness proof for one actual ClusterIP group.

Inputs are the original API item lists selected for this application group.
The outer replay binds list selection, request/response bytes, image content,
resource quantities, CRI identities, mounts and wrapper child PIDs separately.
"""
from __future__ import annotations

from datetime import datetime
from ipaddress import IPv4Address
import re

from tools.optimization_evidence.common import canonical, require, sha256, text
from . import model

MAX_SLICES = 128
ITEM_TYPES = {"Pod": "v1", "Service": "v1", "EndpointSlice": "discovery.k8s.io/v1"}
ZERO_DEFAULTS = {
    ("spec", "publishNotReadyAddresses"), ("spec", "hostNetwork"),
    ("spec", "hostPID"), ("spec", "hostIPC"),
    ("spec", "containers", 0, "stdin"), ("spec", "containers", 0, "stdinOnce"),
    ("spec", "containers", 0, "tty"),
    ("spec", "containers", 0, "startupProbe", "initialDelaySeconds"),
    *(("spec", "containers", 0, "volumeMounts", index, "readOnly") for index in range(4)),
}


def _object(value, reason):
    require(isinstance(value, dict), reason)
    return value


def item_kind(value, kind, *, embedded=False):
    """Only a caller-validated typed List can supply an item's omitted TypeMeta."""
    _object(value, "kubernetes-graph-item-object")
    require(kind in ITEM_TYPES and type(embedded) is bool, "kubernetes-graph-item-type")
    for key, expected in (("kind", kind), ("apiVersion", ITEM_TYPES[kind])):
        require(embedded and key not in value or value.get(key) == expected,
                "kubernetes-graph-item-kind")


def list_items(value, kind):
    """Validate the complete enclosing API list without modifying any raw item."""
    _object(value, "kubernetes-graph-list-object")
    require(kind in ITEM_TYPES and value.get("kind") == kind + "List"
            and value.get("apiVersion") == ITEM_TYPES[kind], "kubernetes-graph-list-kind")
    metadata = _object(value.get("metadata"), "kubernetes-graph-list-metadata")
    require(metadata.get("continue", "") == "", "kubernetes-graph-list-incomplete")
    rows = value.get("items")
    require(isinstance(rows, list) and len(rows) <= 512, "kubernetes-graph-list-population")
    for row in rows:
        item_kind(row, kind, embedded=True)
    return rows


def _typed_subset(actual, expected, *, embedded):
    item_kind(actual, expected["kind"], embedded=embedded)
    subset(actual, {key: value for key, value in expected.items() if key not in ("kind", "apiVersion")})


def subset(actual, expected, path=()):
    """Compare relevant desired fields, allowing API defaults elsewhere."""
    if isinstance(expected, dict):
        _object(actual, "kubernetes-graph-object")
        for key, value in expected.items():
            selected = path + (key,)
            if key not in actual and selected in ZERO_DEFAULTS:
                require(type(value) in (bool, int) and value == 0, "kubernetes-graph-zero-default")
                continue
            require(key in actual, "kubernetes-graph-declared-field")
            subset(actual[key], value, selected)
    elif isinstance(expected, list):
        require(isinstance(actual, list) and len(actual) == len(expected), "kubernetes-graph-array")
        for index, (left, right) in enumerate(zip(actual, expected)):
            subset(left, right, path + (index,))
    else:
        require(type(actual) is type(expected) and actual == expected, "kubernetes-graph-declared-value")


def _timestamp(value):
    value = text(value, 64)
    require(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?(?:Z|[+-][0-9]{2}:[0-9]{2})", value),
            "kubernetes-graph-timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        require(False, "kubernetes-graph-timestamp")
    require(parsed.tzinfo is not None, "kubernetes-graph-timestamp-zone")
    return value


def _ip(value):
    value = text(value, 15)
    try:
        parsed = IPv4Address(value)
    except ValueError:
        require(False, "kubernetes-graph-ipv4")
    require(str(parsed) == value and not parsed.is_unspecified and not parsed.is_loopback
            and not parsed.is_multicast and value != "255.255.255.255", "kubernetes-graph-unicast")
    return value


def _metadata(value, namespace):
    metadata = _object(value.get("metadata"), "kubernetes-graph-metadata")
    require(metadata.get("namespace") == namespace and metadata.get("deletionTimestamp") is None,
            "kubernetes-graph-namespace-or-deletion")
    name = text(metadata.get("name"), 253)
    require(re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", name), "kubernetes-graph-name")
    uid = text(metadata.get("uid"), 64)
    require(re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", uid),
            "kubernetes-graph-uid")
    version = text(metadata.get("resourceVersion"), 32)
    require(re.fullmatch(r"[1-9][0-9]*", version), "kubernetes-graph-resource-version")
    return metadata, {"name": name, "uid": uid, "resource_version": version,
                      "created_at": _timestamp(metadata.get("creationTimestamp"))}


def _condition(conditions, name):
    selected = [row for row in conditions if row.get("type") == name]
    require(len(selected) == 1 and selected[0].get("status") == "True", "kubernetes-graph-pod-condition")
    return _timestamp(selected[0].get("lastTransitionTime"))


def _pod(value, *, owner, run_id, role, arm, density, worker_name, embedded=False,
         startup_protocol=model.CURRENT_STARTUP_PROTOCOL):
    namespace = model.namespace_name(owner, run_id)
    _, identity = _metadata(value, namespace)
    spec = _object(value.get("spec"), "kubernetes-graph-pod-spec")
    containers = spec.get("containers")
    require(isinstance(containers, list) and len(containers) == 1, "kubernetes-graph-container-count")
    container = _object(containers[0], "kubernetes-graph-container")
    volumes = spec.get("volumes")
    require(isinstance(volumes, list) and len(volumes) == (4 if arm == "lsf" else 3)
            and all(isinstance(row, dict) for row in volumes), "kubernetes-graph-volumes")
    volume_map = {row.get("name"): row for row in volumes}
    required_volumes = {"fixtures", "output", "tmp"} | ({"data"} if arm == "lsf" else set())
    require(len(volume_map) == len(volumes) and set(volume_map) == required_volumes, "kubernetes-graph-volume-names")
    paths = {name: _object(volume_map[name].get("hostPath"), "kubernetes-graph-host-path").get("path")
             for name in required_volumes - {"tmp"}}
    # Check the model's control and owned-path shapes using the actual retained
    # inputs. Outer replay additionally binds args/image/data to setup receipts.
    expected = model.pod(container.get("image"), container.get("args"),
        arm=arm, density=density, owner=owner, run_id=run_id, role=role,
        fixtures=paths["fixtures"], output=paths["output"], data=paths.get("data"), startup_protocol=startup_protocol)
    projected = expected["spec"]["containers"][0]
    del projected["resources"]  # Quantity normalization and effective controls have their own proof.
    _typed_subset(value, expected, embedded=embedded)
    model.validate_startup_probe(container.get("startupProbe"), startup_protocol=startup_protocol)
    require(spec.get("nodeName") == worker_name and not spec.get("runtimeClassName")
            and not spec.get("initContainers") and not spec.get("ephemeralContainers")
            and not container.get("command") and not container.get("readinessProbe")
            and not container.get("livenessProbe"), "kubernetes-graph-pod-runtime")
    model._image(container.get("image"), arm)
    status = _object(value.get("status"), "kubernetes-graph-pod-status")
    require(status.get("phase") == "Running", "kubernetes-graph-pod-not-running")
    conditions = status.get("conditions")
    require(isinstance(conditions, list) and 4 <= len(conditions) <= 32
            and all(isinstance(row, dict) for row in conditions), "kubernetes-graph-conditions")
    types = [text(row.get("type"), 128) for row in conditions]
    require(len(set(types)) == len(types), "kubernetes-graph-duplicate-condition")
    times = {name: _condition(conditions, name) for name in ("PodScheduled", "Initialized", "ContainersReady", "Ready")}
    statuses = status.get("containerStatuses")
    require(isinstance(statuses, list) and len(statuses) == 1, "kubernetes-graph-container-status")
    running = _object(statuses[0], "kubernetes-graph-container-status")
    require(running.get("name") == arm and type(running.get("restartCount")) is int
            and running["restartCount"] == 0 and not running.get("lastState")
            and running.get("ready") is True and running.get("started") is True,
            "kubernetes-graph-container-restart-or-not-ready")
    state = _object(running.get("state"), "kubernetes-graph-container-state")
    require(set(state) == {"running"}, "kubernetes-graph-container-state")
    container_uri = text(running.get("containerID"), 80)
    require(re.fullmatch(r"containerd://[0-9a-f]{64}", container_uri), "kubernetes-graph-container-id")
    image_id = text(running.get("imageID"), 512)
    require(not any(ord(char) <= 32 or ord(char) == 127 for char in image_id), "kubernetes-graph-image-id")
    pod_ip = _ip(status.get("podIP"))
    require(status.get("podIPs") == [{"ip": pod_ip}], "kubernetes-graph-pod-ip-set")
    return {**identity, "namespace": namespace, "role": role, "node_name": worker_name,
            "pod_ip": pod_ip, "container_name": arm, "container_id": container_uri[len("containerd://"):],
            "container_uri": container_uri, "image_id": image_id, "image": container["image"],
            "timestamps": {"created_at": identity["created_at"], "pod_start_at": _timestamp(status.get("startTime")),
                           "scheduled_at": times["PodScheduled"], "initialized_at": times["Initialized"],
                           "containers_ready_at": times["ContainersReady"], "ready_at": times["Ready"],
                           "container_started_at": _timestamp(_object(state["running"], "kubernetes-graph-running").get("startedAt"))},
            "pod_sha256": sha256(canonical(value))}


def graph(services, endpointslices, pods, *, owner, run_id, pair, group, arm, density, worker_name, embedded_items=False,
          startup_protocol=model.CURRENT_STARTUP_PROTOCOL):
    """Require exactly one ready endpoint for every declared Service identity."""
    desired = model.services(owner=owner, run_id=run_id, pair=pair, group=group, arm=arm, density=density)
    namespace = model.namespace_name(owner, run_id)
    worker_name = model._label(worker_name, "kubernetes-graph-worker", 63)
    expected_pods = 1 if arm == "lsf" else density
    require(isinstance(services, list) and len(services) == density
            and isinstance(pods, list) and len(pods) == expected_pods
            and isinstance(endpointslices, list) and density <= len(endpointslices) <= MAX_SLICES,
            "kubernetes-graph-population")
    require(len(canonical([services, endpointslices, pods])) <= 8 * 1024**2, "kubernetes-graph-byte-bound")
    names = [model.application_role(pair, group, arm, index) for index in range(expected_pods)]
    pod_map, seen_uids, seen_ips, seen_containers = {}, set(), set(), set()
    for value in pods:
        _object(value, "kubernetes-graph-pod")
        role = _object(value.get("metadata"), "kubernetes-graph-pod-metadata").get("name")
        require(role in names and role not in pod_map, "kubernetes-graph-pod-name-set")
        identity = _pod(value, owner=owner, run_id=run_id, role=role, arm=arm, density=density,
                        worker_name=worker_name, embedded=embedded_items, startup_protocol=startup_protocol)
        require(identity["uid"] not in seen_uids and identity["pod_ip"] not in seen_ips
                and identity["container_id"] not in seen_containers, "kubernetes-graph-pod-identity-reused")
        pod_map[role] = identity
        seen_uids.add(identity["uid"])
        seen_ips.add(identity["pod_ip"])
        seen_containers.add(identity["container_id"])
    desired_by_name = {value["metadata"]["name"]: value for value in desired}
    service_map = {}
    for value in services:
        _object(value, "kubernetes-graph-service")
        _, identity = _metadata(value, namespace)
        name = identity["name"]
        require(name in desired_by_name and name not in service_map and identity["uid"] not in seen_uids,
                "kubernetes-graph-service-identity")
        _typed_subset(value, desired_by_name[name], embedded=embedded_items)
        require(value["spec"]["selector"] == desired_by_name[name]["spec"]["selector"],
                "kubernetes-graph-service-selector")
        ip = _ip(value["spec"].get("clusterIP"))
        require(value["spec"].get("clusterIPs") == [ip] and ip not in seen_ips
                and not value["spec"].get("externalIPs") and not value["spec"].get("externalName"),
                "kubernetes-graph-service-ip-set")
        seen_uids.add(identity["uid"])
        seen_ips.add(ip)
        service_map[name] = {**identity, "cluster_ip": ip, "slices": [], "endpoints": [],
                             "service_sha256": sha256(canonical(value))}
    slice_names, slice_rows = set(), {}
    for value in endpointslices:
        _object(value, "kubernetes-graph-slice")
        item_kind(value, "EndpointSlice", embedded=embedded_items)
        require(value.get("addressType") == "IPv4", "kubernetes-graph-slice-kind")
        metadata, identity = _metadata(value, namespace)
        require(identity["uid"] not in seen_uids and identity["name"] not in slice_names,
                "kubernetes-graph-slice-identity")
        seen_uids.add(identity["uid"])
        slice_names.add(identity["name"])
        labels = _object(metadata.get("labels"), "kubernetes-graph-slice-labels")
        name = labels.get("kubernetes.io/service-name")
        require(name in service_map and labels.get("endpointslice.kubernetes.io/managed-by") == "endpointslice-controller.k8s.io",
                "kubernetes-graph-slice-service")
        for key, expected in ((model.OWNER_LABEL, owner), (model.RUN_LABEL, run_id)):
            require(key not in labels or labels[key] == expected, "kubernetes-graph-slice-owner-label")
        service = service_map[name]
        refs = metadata.get("ownerReferences")
        require(isinstance(refs, list) and len(refs) == 1, "kubernetes-graph-slice-owner-count")
        subset(refs[0], {"apiVersion": "v1", "kind": "Service", "name": name,
                         "uid": service["uid"], "controller": True})
        subset(value.get("ports"), [{"name": "grpc", "port": 7070, "protocol": "TCP"}])
        entries = value.get("endpoints")
        require(isinstance(entries, list) and len(entries) <= 1, "kubernetes-graph-slice-endpoint-count")
        for endpoint in entries:
            endpoint = _object(endpoint, "kubernetes-graph-endpoint")
            conditions = _object(endpoint.get("conditions"), "kubernetes-graph-endpoint-conditions")
            require(conditions.get("ready") is True and conditions.get("serving") is True
                    and conditions.get("terminating") is False, "kubernetes-graph-endpoint-not-ready")
            pod_name = desired_by_name[name]["spec"]["selector"][model.ROLE_LABEL]
            pod = pod_map[pod_name]
            require(endpoint.get("addresses") == [pod["pod_ip"]] and endpoint.get("nodeName") == worker_name,
                    "kubernetes-graph-endpoint-address-or-worker")
            target = _object(endpoint.get("targetRef"), "kubernetes-graph-endpoint-target")
            subset(target, {"kind": "Pod", "namespace": namespace, "name": pod_name, "uid": pod["uid"]})
            require(target.get("apiVersion", "v1") == "v1", "kubernetes-graph-endpoint-api-version")
            service["endpoints"].append({"pod": pod, "slice": identity})
        service["slices"].append(identity["uid"])
        slice_rows[identity["uid"]] = {**identity, "service_name": name, "service_uid": service["uid"],
                                      "endpoint_count": len(entries), "slice_sha256": sha256(canonical(value))}
    targets, service_endpoints = [], {pod["uid"]: [] for pod in pod_map.values()}
    for index, value in enumerate(desired):
        service = service_map[value["metadata"]["name"]]
        require(len(service["endpoints"]) == 1, "kubernetes-graph-service-endpoint-bijection")
        endpoint = service["endpoints"][0]
        pod, selected_slice = endpoint["pod"], endpoint["slice"]
        target = {"index": index, "service": model.SERVICES[index],
                  "endpoint": "http://" + service["cluster_ip"] + ":7070",
                  "service_name": service["name"], "service_uid": service["uid"],
                  "service_resource_version": service["resource_version"], "cluster_ip": service["cluster_ip"],
                  "service_sha256": service["service_sha256"],
                  "slice_name": selected_slice["name"], "slice_uid": selected_slice["uid"],
                  "slice_resource_version": selected_slice["resource_version"],
                  "all_slice_uids": sorted(service["slices"]),
                  "pod_name": pod["name"], "pod_uid": pod["uid"], "pod_ip": pod["pod_ip"],
                  "container_name": arm, "container_id": pod["container_id"], "image_id": pod["image_id"]}
        targets.append(target)
        service_endpoints[pod["uid"]].append(dict(target))
    return {"schema": model.PREFIX + "service-graph.v1", "namespace": namespace, "targets": targets,
            "service_endpoints": service_endpoints, "pods": {pod["uid"]: pod for pod in pod_map.values()},
            "slices": slice_rows, "timestamp_scope": "original-api-wall-times-no-cross-clock-subtraction"}
