"""Connect the owned Linux collector to its verified kind cluster, without Invokes."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import stat
import tarfile
import time

from tools.artifact_identity_runner.files import fingerprint, reference, write_json
from tools.optimization_docker.engine import Engine
from tools.optimization_evidence.common import read_json, require
from tools.optimization_revision_runner.build import source
from .transport import Journal, Kubernetes, Worker, blob, private_tls

CONTROLLER = "8c6562736fe48363248c46e3bcb929c1a44c2708d27f445aa531dedf3ac84fda"
BENCH_ROOT = Path("/bench/kubernetes")


def _fresh(root, parent, pattern):
    require(root.parent == parent and re.fullmatch(pattern, root.name) is not None and not root.exists(),
            "kubernetes-bootstrap-fresh-root")
    for path in root.parents:
        if path.exists():
            require(stat.S_ISDIR(path.lstat().st_mode) and not path.is_symlink(), "kubernetes-bootstrap-root-parent")
    root.mkdir(parents=True)


def _request(engine, journal, operation, method, path, body=None, **kwargs):
    receipt, raw, failure = None, b"", None
    try:
        value, receipt = engine.request(method, path, body, **kwargs)
        raw = engine.last_body
        return value, receipt
    except BaseException as error:
        receipt, raw, failure = getattr(error, "receipt", None), getattr(error, "body", b""), type(error).__name__
        raise
    finally:
        journal.append({"provider": "docker", "operation": operation, "method": method, "path": path,
                        "request": body, "response": blob(raw), "receipt": receipt, "failure": failure})


def _engine(journal):
    try:
        engine = Engine()
    except BaseException as error:
        journal.append({"provider": "docker", "operation": "api-negotiation", "failure": type(error).__name__,
                        "receipt": getattr(error, "receipt", None), "response": blob(getattr(error, "body", b""))})
        raise
    journal.append({"provider": "docker", "operation": "api-negotiation", "failure": None,
                    "receipt": engine.version_receipt, "response": blob(engine.version_body)})
    return engine


def _bytes(path, maximum):
    expected = fingerprint(path, maximum)
    with path.open("rb") as stream:
        value = stream.read(maximum + 1)
    require(len(value) == expected[1] and blob(value)["sha256"] == expected[0], "kubernetes-bootstrap-input-changed")
    return value


def _setup(args):
    setup = read_json(args.setup, 8 * 1024**2)
    require(setup.get("schema") in ("latent.optimization.kubernetes-setup.v1",
            "latent.optimization.kubernetes-setup-resume.v1")
            and setup.get("status") == "ready-for-campaign-preflight" and setup.get("failure") is None
            and setup.get("source_before") == setup.get("source_after")
            and setup.get("source_before", {}).get("clean") is True, "kubernetes-unverified-setup")
    original = setup
    if setup["schema"].endswith("-resume.v1"):
        path = getattr(args, "original_setup", None)
        require(isinstance(path, Path), "kubernetes-original-setup-required")
        expected = setup["original_setup"]
        require(fingerprint(path, 8 * 1024**2) == (expected["sha256"], int(expected["bytes"])),
                "kubernetes-original-setup-hash")
        original = read_json(path, 8 * 1024**2)
        require(original.get("schema") == "latent.optimization.kubernetes-setup.v1"
                and original.get("status") == "incomplete" and original.get("failure") is not None
                and original["failure"] == setup.get("historical_failure")
                and setup.get("verification_kind") == "read-only-existing-import"
                and setup.get("original_source_before") == setup.get("original_source_after")
                and setup.get("original_source_before") == original.get("source_before"),
                "kubernetes-original-setup-resume-binding")
        for key in ("owner", "context", "nodes", "original_images", "private_kubeconfig_identity"):
            require(setup[key] == original[key], "kubernetes-original-setup-field")
        projection = {"archive": setup["image_archive"]["archive"], "images": {
            arm: {key: value for key, value in item.items() if key not in ("archive_index_digest", "archive_index_entry")}
            for arm, item in setup["image_archive"]["images"].items()}}
        require(projection == original["image_archive"], "kubernetes-original-image-archive")
    require(re.fullmatch(r"lsf-112-[0-9a-f]{12}", setup.get("owner", "")) is not None,
            "kubernetes-bootstrap-owner")
    require(isinstance(original.get("networks_before"), list) and len(original["networks_before"]) <= 64,
            "kubernetes-bootstrap-original-networks")
    return setup, original


def _nodes(setup):
    require(len(setup["nodes"]) == 2, "kubernetes-bootstrap-node-set")
    nodes = {row["role"]: row for row in setup["nodes"]}
    require(set(nodes) == {"control-plane", "worker"}
            and len({row["container_id"] for row in nodes.values()}) == 2, "kubernetes-bootstrap-node-roles")
    for role, row in nodes.items():
        require(re.fullmatch(r"[0-9a-f]{64}", row["container_id"]) is not None
                and row["container_id"] != CONTROLLER and row["name"] == setup["owner"] + "-" + role,
                "kubernetes-bootstrap-node-id")
    return nodes


def _node(actual, expected, owner, *, running):
    labels = actual.get("Config", {}).get("Labels", {})
    require(actual.get("Id") == expected["container_id"] and actual.get("Name") == "/" + expected["name"]
            and actual.get("Image") == expected["image_id"]
            and labels.get("io.x-k8s.kind.cluster") == owner
            and labels.get("io.x-k8s.kind.role") == expected["role"]
            and (not running or actual.get("State", {}).get("Running") is True), "kubernetes-bootstrap-node-ownership")


def _controller(actual):
    require(actual.get("Id") == CONTROLLER and actual.get("State", {}).get("Running") is True
            and actual.get("Config", {}).get("Labels", {}).get("latent.benchmark.owner") == "issue111-controller-01",
            "kubernetes-bootstrap-controller-owner")


def _network_identity(network):
    require(network.get("Name") == "kind" and re.fullmatch(r"[0-9a-f]{64}", network.get("Id", "")) is not None,
            "kubernetes-bootstrap-network-id")
    return {key: network.get(key) for key in ("Id", "Name", "Created", "Driver", "Scope", "Internal",
                                             "EnableIPv6", "Options", "Labels", "IPAM")}


def _connections(controller):
    return {name: row["NetworkID"] for name, row in controller.get("NetworkSettings", {}).get("Networks", {}).items()}


def _alias(controller, network_id, owner):
    endpoint = controller.get("NetworkSettings", {}).get("Networks", {}).get("kind", {})
    require(endpoint.get("NetworkID") == network_id and endpoint.get("Aliases") == [owner + "-controller"],
            "kubernetes-controller-owned-alias")


def _credentials(base, boot):
    """Bound only copied credentials; every TLS copy must match bootstrap hashes."""
    private = base / "private"
    require(private.is_dir() and not private.is_symlink(), "kubernetes-cleanup-private-directory")
    recorded = boot["private_credentials"]
    require(len(recorded) == 4 and {row["path"] for row in recorded} ==
            {"private/kubeconfig", "private/tls/ca.pem", "private/tls/client.pem", "private/tls/client.key"},
            "kubernetes-cleanup-credential-records")
    hashes = {Path(row["path"]).name: (row["sha256"], int(row["bytes"])) for row in recorded}
    files, directories = [], list(private.iterdir())
    require(len(directories) <= 17, "kubernetes-cleanup-private-count")
    for item in directories:
        require(not item.is_symlink(), "kubernetes-cleanup-private-symlink")
        if item.name == "kubeconfig":
            selected = [item]
        else:
            require(item.is_dir() and re.fullmatch(r"tls(?:-[a-z0-9][a-z0-9-]{0,63})?", item.name),
                    "kubernetes-cleanup-private-scope")
            selected = list(item.iterdir())
            require(len(selected) <= 3 and all(path.name in ("ca.pem", "client.pem", "client.key") for path in selected),
                    "kubernetes-cleanup-pem-set")
        for path in selected:
            require(fingerprint(path, 32 * 1024) == hashes[path.name], "kubernetes-cleanup-credential-hash")
            files.append(reference(path, base))
    return sorted(files, key=lambda row: (row["path"] == "private/kubeconfig", row["path"]))


def execute(args, repository):
    setup, original_setup = _setup(args)
    owner = setup["owner"]
    root = args.output.absolute()
    _fresh(root, BENCH_ROOT, owner)
    result = {"schema": "latent.optimization.kubernetes-bootstrap.v1", "owner": owner,
              "setup_file": str(args.setup), "setup_sha256": fingerprint(args.setup)[0],
              "output": str(root), "controller_id": CONTROLLER, "failure": None, "status": "incomplete",
              "started_nanos": str(time.monotonic_ns())}
    journal = None
    try:
        (root / "private").mkdir(mode=0o700)
        (root / "tools").mkdir()
        journal = Journal(root / "bootstrap.ndjson", maximum=32 * 1024**2)
        identity = source(repository)
        result["source"] = identity
        config = _bytes(args.kubeconfig, 32 * 1024)
        expected_config = setup["private_kubeconfig_identity"]
        require((blob(config)["sha256"], len(config)) == (expected_config["sha256"], int(expected_config["bytes"])),
                "kubernetes-bootstrap-kubeconfig-identity")
        with (root / "setup.json").open("xb") as stream:
            stream.write(_bytes(args.setup, 8 * 1024**2))
        result["setup"] = reference(root / "setup.json", root)
        nodes = _nodes(setup)
        result["nodes"] = nodes
        original_path = getattr(args, "original_setup", None) if setup is not original_setup else args.setup
        with (root / "original-setup.json").open("xb") as stream:
            stream.write(_bytes(original_path, 8 * 1024**2))
        result["original_setup"] = reference(root / "original-setup.json", root)
        result["images"] = {arm: {"tag": item["tag"],
            "original_docker_image_id": setup["original_images"][arm]["Id"],
            "imported": setup["imported_images"][arm]}
            for arm, item in setup["image_archive"]["images"].items()}
        engine = _engine(journal)
        result["engine"] = {"api_version": engine.api_version, "server_version": engine.server_version}
        for role, node in nodes.items():
            actual, _ = _request(engine, journal, "node-identity-" + role, "GET", "/containers/" + node["container_id"] + "/json")
            _node(actual, node, owner, running=True)
        controller, _ = _request(engine, journal, "controller-identity", "GET", "/containers/" + CONTROLLER + "/json")
        _controller(controller)
        result["controller_original_networks"] = _connections(controller)
        require("kind" not in result["controller_original_networks"], "kubernetes-controller-already-connected")
        network, _ = _request(engine, journal, "kind-network-before", "GET", "/networks/kind")
        expected_nodes = {row["container_id"] for row in nodes.values()}
        require(network["Name"] == "kind" and set(network["Containers"]) == expected_nodes
                and CONTROLLER not in network["Containers"], "kubernetes-bootstrap-network-membership")
        result["network_id"] = network["Id"]
        result["network_identity"] = _network_identity(network)
        result["network_created_by_setup"] = not any(row.get("Name") == "kind" for row in original_setup["networks_before"])
        request = {"Container": CONTROLLER, "EndpointConfig": {"Aliases": [owner + "-controller"]}}
        _request(engine, journal, "controller-connect", "POST", "/networks/" + network["Id"] + "/connect", request)
        after, _ = _request(engine, journal, "kind-network-after", "GET", "/networks/" + network["Id"])
        require(_network_identity(after) == result["network_identity"]
                and set(after["Containers"]) == expected_nodes | {CONTROLLER}, "kubernetes-bootstrap-network-after")
        connected, _ = _request(engine, journal, "controller-alias", "GET", "/containers/" + CONTROLLER + "/json")
        _controller(connected)
        _alias(connected, network["Id"], owner)
        require(_connections(connected) == {**result["controller_original_networks"], "kind": network["Id"]},
                "kubernetes-controller-other-networks-changed")
        worker = Worker(engine, nodes["worker"]["container_id"], owner, journal)
        archive = root / "kubectl.tar"
        receipt = engine.download_archive(worker.container_id, "/usr/bin/kubectl", archive,
                                           timeout=60, maximum=128 * 1024**2)
        journal.append({"operation": "kubectl-download", "receipt": receipt,
                        "archive": reference(archive, root)})
        with tarfile.open(archive, "r:") as stream:
            iterator = iter(stream)
            member = next(iterator, None)
            require(member is not None and member.name == "kubectl" and member.isfile()
                    and 0 < member.size <= 128 * 1024**2 and next(iterator, None) is None,
                    "kubernetes-bootstrap-kubectl-tar")
            binary = root / "tools/kubectl"
            with stream.extractfile(member) as incoming, binary.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, 65536)
        binary.chmod(0o700)
        original, call = worker.command(["sha256sum", "/usr/bin/kubectl"])
        require(original.decode().strip().split() == [fingerprint(binary)[0][7:], "/usr/bin/kubectl"],
                "kubernetes-bootstrap-kubectl-identity")
        result["kubectl"] = {"file": reference(binary, root), "worker_call": call}
        require(0 < len(config) <= 32 * 1024, "kubernetes-bootstrap-config-bound")
        private = root / "private/kubeconfig"
        with private.open("xb") as stream:
            stream.write(config)
        private.chmod(0o600)
        result["private_kubeconfig"] = {"sha256": fingerprint(private)[0], "publishable": False}
        tls = private_tls(private, root / "private/tls")
        result["private_credentials"] = [reference(path, root) for path in (
            private, root / "private/tls/ca.pem", root / "private/tls/client.pem", root / "private/tls/client.key")]
        api = Kubernetes(owner + "-control-plane", tls, journal)
        observed, call = api.call("GET", "/api/v1/nodes")
        require({item["metadata"]["name"]: item["metadata"]["uid"] for item in observed["items"]}
                == {row["name"]: row["uid"] for row in nodes.values()}, "kubernetes-bootstrap-node-uids")
        result["node_api_call"] = call
        remote = "/var/local/lsf112/" + owner
        worker.command(["mkdir", "-p", "/var/local/lsf112"])
        _, call = worker.command(["mkdir", "-m", "700", remote])
        result["worker_root_create_call"] = call
        result["worker_root"] = remote
        require(source(repository) == identity, "kubernetes-bootstrap-source-changed")
        require(fingerprint(args.setup)[0] == result["setup_sha256"]
                and read_json(root / "original-setup.json", 8 * 1024**2) == original_setup,
                "kubernetes-bootstrap-setup-changed")
        result["status"] = "connected-no-workload"
    except BaseException as error:
        result["failure"] = {"type": type(error).__name__, "reason": str(error)[:2048]}
        result["status"] = "incomplete"
        if journal is not None and getattr(error, "receipt", None) is not None:
            journal.append({"operation": "bootstrap-failure", "receipt": error.receipt,
                            "response": blob(getattr(error, "body", b"")), "failure": type(error).__name__})
        raise
    finally:
        result["finished_nanos"] = str(time.monotonic_ns())
        write_json(root / "bootstrap.json", result)
    print(json.dumps({"status": result["status"], "owner": owner, "output": str(root)}))
    return 0


def cleanup(args, repository):
    """Explicit final teardown; private credential copies are removed last."""
    path = args.bootstrap.absolute()
    boot = read_json(path, 8 * 1024**2)
    owner, base = boot["owner"], path.parent
    require(re.fullmatch(r"lsf-112-[0-9a-f]{12}", owner) is not None
            and path.name == "bootstrap.json" and base == BENCH_ROOT / owner
            and boot.get("schema") == "latent.optimization.kubernetes-bootstrap.v1"
            and boot.get("output") == str(base) and boot.get("controller_id") == CONTROLLER,
            "kubernetes-cleanup-bootstrap-binding")
    root = args.output.absolute()
    _fresh(root, base, r"cleanup-[0-9]{2}")
    result = {"schema": "latent.optimization.kubernetes-cluster-cleanup.v1", "owner": owner,
              "bootstrap": {"path": str(path), "sha256": fingerprint(path)[0]}, "status": "incomplete",
              "failure": None, "nodes_removed": [], "nodes_already_absent": [],
              "controller_disconnected": False, "network_removed": False,
              "public_files_images_volumes_retained": True, "credentials_removed": [],
              "started_nanos": str(time.monotonic_ns())}
    journal = None
    try:
        journal = Journal(root / "cleanup.ndjson", maximum=32 * 1024**2)
        identity = source(repository)
        result["source"] = identity
        require(boot["original_setup"]["path"] == "original-setup.json"
                and reference(base / "original-setup.json", base) == boot["original_setup"],
                "kubernetes-cleanup-original-setup")
        original = read_json(base / "original-setup.json", 8 * 1024**2)
        nodes = _nodes(original)
        require(original["owner"] == owner and nodes == boot["nodes"], "kubernetes-cleanup-node-records")
        require(boot["network_created_by_setup"] is (not any(row.get("Name") == "kind"
                    for row in original["networks_before"])), "kubernetes-cleanup-network-creation")
        network_id = boot["network_id"]
        require(boot["network_identity"]["Id"] == network_id
                and re.fullmatch(r"[0-9a-f]{64}", network_id) is not None, "kubernetes-cleanup-network-id")
        credentials = _credentials(base, boot)
        result["credentials_before"] = credentials
        engine = _engine(journal)
        result["engine"] = {"api_version": engine.api_version, "server_version": engine.server_version}
        actual_nodes = {}
        for role in ("worker", "control-plane"):
            node = nodes[role]
            actual, receipt = _request(engine, journal, "node-before-" + role, "GET",
                                      "/containers/" + node["container_id"] + "/json", expected=(200, 404))
            if receipt["status"] == 404:
                result["nodes_already_absent"].append(node["container_id"])
            else:
                _node(actual, node, owner, running=False)
                actual_nodes[role] = actual
        controller, _ = _request(engine, journal, "controller-before", "GET", "/containers/" + CONTROLLER + "/json")
        _controller(controller)
        original_connections = boot["controller_original_networks"]
        require("kind" not in original_connections and {name: value for name, value in _connections(controller).items()
                if name != "kind"} == original_connections, "kubernetes-controller-other-networks-changed")
        network, receipt = _request(engine, journal, "network-before", "GET", "/networks/" + network_id,
                                    expected=(200, 404))
        network_exists = receipt["status"] == 200
        attached = "kind" in _connections(controller)
        live_ids = {nodes[role]["container_id"] for role in actual_nodes}
        if network_exists:
            require(_network_identity(network) == boot["network_identity"]
                    and set(network.get("Containers", {})) == live_ids | ({CONTROLLER} if attached else set()),
                    "kubernetes-cleanup-unrelated-network-members")
        else:
            require(not attached and all("kind" not in _connections(row) for row in actual_nodes.values()),
                    "kubernetes-cleanup-missing-network-attached")
        if attached:
            _alias(controller, network_id, owner)
            _request(engine, journal, "controller-disconnect", "POST", "/networks/" + network_id + "/disconnect",
                     {"Container": CONTROLLER, "Force": False})
            result["controller_disconnected"] = True
        after, _ = _request(engine, journal, "controller-after", "GET", "/containers/" + CONTROLLER + "/json")
        _controller(after)
        require(_connections(after) == original_connections, "kubernetes-cleanup-controller-connections")
        for role in ("worker", "control-plane"):
            if role not in actual_nodes:
                continue
            node = nodes[role]
            current, _ = _request(engine, journal, "node-recheck-" + role, "GET", "/containers/" + node["container_id"] + "/json")
            _node(current, node, owner, running=False)
            if current.get("State", {}).get("Running") is True:
                _request(engine, journal, "node-stop-" + role, "POST", "/containers/" + node["container_id"] + "/stop?t=30",
                         expected=(204, 304), timeout=40)
            stopped, _ = _request(engine, journal, "node-stopped-" + role, "GET", "/containers/" + node["container_id"] + "/json")
            _node(stopped, node, owner, running=False)
            require(stopped.get("State", {}).get("Running") is False, "kubernetes-cleanup-node-still-running")
            _request(engine, journal, "node-delete-" + role, "DELETE",
                     "/containers/" + node["container_id"] + "?force=false&v=false", expected=(204,))
            _request(engine, journal, "node-absent-" + role, "GET", "/containers/" + node["container_id"] + "/json",
                     expected=(404,))
            result["nodes_removed"].append(node["container_id"])
        if network_exists:
            empty, _ = _request(engine, journal, "network-empty", "GET", "/networks/" + network_id)
            require(_network_identity(empty) == boot["network_identity"] and not empty.get("Containers"),
                    "kubernetes-cleanup-network-not-empty")
            if boot["network_created_by_setup"]:
                _request(engine, journal, "network-delete", "DELETE", "/networks/" + network_id, expected=(204,))
                _request(engine, journal, "network-absent", "GET", "/networks/" + network_id, expected=(404,))
                result["network_removed"] = True
        require(source(repository) == identity and fingerprint(path)[0] == result["bootstrap"]["sha256"],
                "kubernetes-cleanup-source-changed")
        require(_credentials(base, boot) == credentials, "kubernetes-cleanup-credentials-changed")
        for item in credentials:
            credential = base / item["path"]
            require(reference(credential, base) == item and not credential.parent.is_symlink(),
                    "kubernetes-cleanup-credential-recheck")
            credential.unlink()
            require(not credential.exists() and not credential.is_symlink(), "kubernetes-cleanup-credential-remains")
            result["credentials_removed"].append({**item, "absent": True})
        require(not _credentials(base, boot), "kubernetes-cleanup-private-not-empty")
        result["status"] = "owned-cluster-removed"
    except BaseException as error:
        result["failure"] = {"type": type(error).__name__, "reason": str(error)[:2048]}
    finally:
        result["finished_nanos"] = str(time.monotonic_ns())
        write_json(root / "cleanup.json", result)
    print(json.dumps({"status": result["status"], "owner": owner, "output": str(root)}))
    return 0 if result["failure"] is None else 1
