"""Offline final teardown proof, including both copies of private credentials.

Node UIDs were observed at bootstrap. Teardown rechecks the exact corresponding
Docker container identities; it does not claim a second Kubernetes UID read.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
import re

from tools.artifact_identity_runner.files import fingerprint
from tools.optimization_docker import evidence as docker
from tools.optimization_docker.engine import API_VERSION
from tools.optimization_evidence.common import decode, digest, fields, integer, read_json, require, uint
from . import bootstrap, bootstrap_evidence, transport_evidence as transport


class _Calls:
    def __init__(self, root, value):
        data = bootstrap_evidence._file(root, "cleanup.ndjson", 32 * 1024**2)
        lines = data.splitlines(keepends=True)
        require(6 <= len(lines) <= 24 and all(line.endswith(b"\n") and len(line) <= 24 * 1024**2 for line in lines),
                "kubernetes-cluster-cleanup-journal-bound")
        self.rows = [transport._line(line) for line in lines]
        require(all(integer(row.get("ordinal")) == index for index, row in enumerate(self.rows)),
                "kubernetes-cluster-cleanup-journal-order")
        self.position, self.previous, self.upper = 0, uint(value["started_nanos"]), uint(value["finished_nanos"])
        first = self.rows[0]
        fields(first, "ordinal provider operation failure receipt response")
        require(first["provider"] == "docker" and first["operation"] == "api-negotiation" and first["failure"] is None,
                "kubernetes-cluster-cleanup-negotiation")
        raw = transport._blob(first["response"])
        _, self.previous = transport._http(first["receipt"], method="GET", path="/version", status=200,
            request=b"", response=raw, lower=self.previous, upper=self.upper)
        version = decode(raw, transport.MAX_RESPONSE)
        require(value["engine"] == {"api_version": API_VERSION, "server_version": version["Version"]}
                and tuple(map(int, version["MinAPIVersion"].split("."))) <= (1, 54)
                <= tuple(map(int, version["ApiVersion"].split("."))), "kubernetes-cluster-cleanup-engine-version")
        self.position = 1

    def take(self, operation, method, path, body=None, *, statuses=(200,), maximum_seconds=30):
        require(self.position < len(self.rows), "kubernetes-cluster-cleanup-missing-call")
        row = self.rows[self.position]
        fields(row, "ordinal provider operation method path request response receipt failure")
        require(row["provider"] == "docker" and row["operation"] == operation and row["method"] == method
                and row["path"] == path and row["request"] == body and row["failure"] is None,
                "kubernetes-cluster-cleanup-call-binding")
        status = integer(row["receipt"]["status"], 100, 599)
        require(status in statuses, "kubernetes-cluster-cleanup-status")
        raw = transport._blob(row["response"])
        request = b"" if body is None else transport._wire(body)
        start, end = transport._http(row["receipt"], method=method, path="/v" + API_VERSION + path, status=status,
            request=request, response=raw, lower=self.previous, upper=self.upper)
        require(end - start <= maximum_seconds * 10**9, "kubernetes-cluster-cleanup-http-deadline")
        self.position += 1
        self.previous = end
        return (decode(raw, transport.MAX_RESPONSE) if raw else None), status

    def finished(self):
        require(self.position == len(self.rows), "kubernetes-cluster-cleanup-unused-call")


def _node(actual, expected, owner):
    bootstrap._node(actual, expected, owner, running=False)
    require(type(actual.get("State", {}).get("Running")) is bool, "kubernetes-cluster-cleanup-node-state")


def _linux_credentials(value, boot):
    recorded = boot["private_credentials"]
    require(len(recorded) == 4, "kubernetes-cluster-cleanup-bootstrap-credentials")
    expected = {PurePosixPath(row["path"]).name: (row["bytes"], row["sha256"]) for row in recorded}
    before = value["credentials_before"]
    require(isinstance(before, list) and len(before) <= 49, "kubernetes-cluster-cleanup-credential-count")
    seen = set()
    for row in before:
        fields(row, "path bytes sha256")
        path = row["path"]
        require(isinstance(path, str) and path not in seen and re.fullmatch(
            r"private/(?:kubeconfig|tls(?:-[a-z0-9][a-z0-9-]{0,63})?/(?:ca.pem|client.pem|client.key))", path),
            "kubernetes-cluster-cleanup-credential-path")
        require((row["bytes"], digest(row["sha256"])) == expected[PurePosixPath(path).name],
                "kubernetes-cluster-cleanup-credential-hash")
        seen.add(path)
    require(before == sorted(before, key=lambda row: (row["path"] == "private/kubeconfig", row["path"])),
            "kubernetes-cluster-cleanup-credential-order")
    require(isinstance(value["credentials_removed"], list)
            and all(row.get("absent") is True for row in value["credentials_removed"]),
            "kubernetes-cluster-cleanup-credential-absence")
    require(value["credentials_removed"] == [{**row, "absent": True} for row in before],
            "kubernetes-cluster-cleanup-credential-absence")


def _windows_credentials(root, bootstrap_root, value, boot):
    sidecar = read_json(docker.relative(root, "windows-credential-cleanup.json"), 64 * 1024)
    fields(sidecar, "schema owner original_setup_sha256 credential verified_before removed absent started_nanos "
                    "finished_nanos helper cluster_cleanup failure")
    require(sidecar["schema"] == "latent.optimization.kubernetes-windows-credential-cleanup.v1"
            and sidecar["owner"] == boot["owner"] and sidecar["failure"] is None
            and all(sidecar[key] is True for key in ("verified_before", "removed", "absent")),
            "kubernetes-cluster-cleanup-windows-outcome")
    require(uint(sidecar["started_nanos"]) <= uint(sidecar["finished_nanos"]),
            "kubernetes-cluster-cleanup-windows-clock")
    # These are separate Windows and Linux monotonic clock domains.
    bootstrap_evidence._artifact(bootstrap_root, boot["original_setup"], "original-setup.json", 8 * 1024**2)
    original = read_json(docker.relative(bootstrap_root, "original-setup.json"), 8 * 1024**2)
    require(sidecar["original_setup_sha256"] == boot["original_setup"]["sha256"],
            "kubernetes-cluster-cleanup-windows-original")
    expected = fields(original["private_kubeconfig_identity"], "path bytes sha256")
    require(expected["path"] == original["private_kubeconfig"] == "private/kubeconfig"
            and original["kubeconfig_publishable"] is False and 0 < uint(expected["bytes"]) <= 32 * 1024,
            "kubernetes-cluster-cleanup-windows-credential-bound")
    digest(expected["sha256"])
    # The helper emits the original relative identity, anchored by the retained
    # setup bytes. Resolve only its lexical Windows scope, never the replay host.
    root_name = original["root"]
    require(isinstance(root_name, str) and 0 < len(root_name) <= 32768 and "\0" not in root_name,
            "kubernetes-cluster-cleanup-windows-root")
    original_root = PureWindowsPath(root_name)
    credential_path = original_root / expected["path"]
    require(original_root.is_absolute() and re.fullmatch(r"[A-Za-z]:", original_root.drive) is not None
            and ".." not in original_root.parts and credential_path.is_relative_to(original_root)
            and credential_path.parent == original_root / "private",
            "kubernetes-cluster-cleanup-windows-root")
    fields(sidecar["credential"], "path bytes sha256")
    require(sidecar["credential"] == expected,
            "kubernetes-cluster-cleanup-windows-credential")
    bootstrap_evidence._artifact(root, sidecar["helper"], "windows-credential-cleanup.py", 64 * 1024)
    bootstrap_evidence._artifact(root, sidecar["cluster_cleanup"], "cleanup.json", 8 * 1024**2)
    require(read_json(docker.relative(root, "cleanup.json"), 8 * 1024**2) == value,
            "kubernetes-cluster-cleanup-windows-reference")


def validate(cleanup_root: Path, bootstrap_root: Path) -> dict:
    """Return the original successful cleanup receipt after all offline checks."""
    boot = bootstrap_evidence.validate(bootstrap_root)
    path = docker.relative(cleanup_root, "cleanup.json")
    value = read_json(path, 8 * 1024**2)
    fields(value, "schema owner bootstrap status failure nodes_removed nodes_already_absent controller_disconnected network_removed "
                  "public_files_images_volumes_retained credentials_removed started_nanos source credentials_before engine finished_nanos")
    require(value["schema"] == "latent.optimization.kubernetes-cluster-cleanup.v1"
            and value["status"] == "owned-cluster-removed" and value["failure"] is None
            and value["owner"] == boot["owner"] and value["public_files_images_volumes_retained"] is True,
            "kubernetes-cluster-cleanup-unqualified")
    docker.source(value["source"])
    fields(value["bootstrap"], "path sha256")
    require(value["bootstrap"] == {"path": boot["output"] + "/bootstrap.json",
                                    "sha256": fingerprint(docker.relative(bootstrap_root, "bootstrap.json"))[0]},
            "kubernetes-cluster-cleanup-bootstrap-reference")
    require(uint(boot["finished_nanos"]) <= uint(value["started_nanos"]) <= uint(value["finished_nanos"]),
            "kubernetes-cluster-cleanup-bootstrap-clock")
    calls = _Calls(cleanup_root, value)
    nodes, owner = boot["nodes"], boot["owner"]
    live, already = {}, []
    for role in ("worker", "control-plane"):
        node = nodes[role]
        observed, status = calls.take("node-before-" + role, "GET", "/containers/" + node["container_id"] + "/json", statuses=(200, 404))
        if status == 404:
            already.append(node["container_id"])
        else:
            _node(observed, node, owner)
            live[role] = observed
    require(value["nodes_already_absent"] == already, "kubernetes-cluster-cleanup-already-absent")
    controller, _ = calls.take("controller-before", "GET", "/containers/" + bootstrap.CONTROLLER + "/json")
    bootstrap._controller(controller)
    connections = bootstrap._connections(controller)
    attached = "kind" in connections
    require({name: identifier for name, identifier in connections.items() if name != "kind"} == boot["controller_original_networks"]
            and "kind" not in boot["controller_original_networks"], "kubernetes-cluster-cleanup-other-networks")
    network_id = boot["network_id"]
    observed_network, status = calls.take("network-before", "GET", "/networks/" + network_id, statuses=(200, 404))
    exists = status == 200
    if exists:
        require(bootstrap._network_identity(observed_network) == boot["network_identity"]
                and set(observed_network.get("Containers", {})) == {nodes[role]["container_id"] for role in live}
                | ({bootstrap.CONTROLLER} if attached else set()), "kubernetes-cluster-cleanup-network-members")
    else:
        require(not attached and all("kind" not in bootstrap._connections(row) for row in live.values()),
                "kubernetes-cluster-cleanup-network-absence")
    if attached:
        bootstrap._alias(controller, network_id, owner)
        calls.take("controller-disconnect", "POST", "/networks/" + network_id + "/disconnect",
                   {"Container": bootstrap.CONTROLLER, "Force": False})
    require(type(value["controller_disconnected"]) is bool and value["controller_disconnected"] == attached,
            "kubernetes-cluster-cleanup-disconnection")
    controller, _ = calls.take("controller-after", "GET", "/containers/" + bootstrap.CONTROLLER + "/json")
    bootstrap._controller(controller)
    require(bootstrap._connections(controller) == boot["controller_original_networks"],
            "kubernetes-cluster-cleanup-controller-restored")
    removed = []
    for role in ("worker", "control-plane"):
        if role not in live:
            continue
        node = nodes[role]
        current, _ = calls.take("node-recheck-" + role, "GET", "/containers/" + node["container_id"] + "/json")
        _node(current, node, owner)
        if current["State"]["Running"]:
            calls.take("node-stop-" + role, "POST", "/containers/" + node["container_id"] + "/stop?t=30",
                       statuses=(204, 304), maximum_seconds=40)
        stopped, _ = calls.take("node-stopped-" + role, "GET", "/containers/" + node["container_id"] + "/json")
        _node(stopped, node, owner)
        require(stopped["State"]["Running"] is False, "kubernetes-cluster-cleanup-node-running")
        calls.take("node-delete-" + role, "DELETE", "/containers/" + node["container_id"] + "?force=false&v=false", statuses=(204,))
        calls.take("node-absent-" + role, "GET", "/containers/" + node["container_id"] + "/json", statuses=(404,))
        removed.append(node["container_id"])
    require(value["nodes_removed"] == removed, "kubernetes-cluster-cleanup-deleted-nodes")
    if exists:
        empty, _ = calls.take("network-empty", "GET", "/networks/" + network_id)
        require(bootstrap._network_identity(empty) == boot["network_identity"] and not empty.get("Containers"),
                "kubernetes-cluster-cleanup-network-empty")
        if boot["network_created_by_setup"]:
            calls.take("network-delete", "DELETE", "/networks/" + network_id, statuses=(204,))
            calls.take("network-absent", "GET", "/networks/" + network_id, statuses=(404,))
    require(type(value["network_removed"]) is bool and value["network_removed"] == bool(exists and boot["network_created_by_setup"]),
            "kubernetes-cluster-cleanup-network-result")
    calls.finished()
    _linux_credentials(value, boot)
    _windows_credentials(cleanup_root, bootstrap_root, value, boot)
    return value
