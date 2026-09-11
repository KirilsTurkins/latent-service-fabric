"""Offline bootstrap/setup proof. Never read credentials or execute retained code."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import tarfile
from types import SimpleNamespace
from urllib.parse import urlencode

from tools.optimization_docker import evidence as docker
from tools.optimization_docker.engine import API_VERSION
from tools.optimization_evidence.common import (
    decode, digest, fields, integer, read_json, require, sha256, uint, verify_artifact,
)
from . import bootstrap, setup as setup_model, transport_evidence as transport

MAX_JSON = 8 * 1024**2
MAX_JOURNAL = 32 * 1024**2


def _file(root, name, maximum=MAX_JSON):
    path = docker.relative(root, name)
    require(path.is_file() and path.stat().st_size <= maximum, "kubernetes-bootstrap-evidence-file")
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    require(len(data) <= maximum, "kubernetes-bootstrap-evidence-file-growth")
    return data


def _artifact(root, value, name, maximum=MAX_JSON):
    fields(value, "path bytes sha256")
    require(value["path"] == name, "kubernetes-bootstrap-evidence-artifact-path")
    docker.relative(root, name)
    verify_artifact(root, value, maximum)


def _windows(root, document):
    """Replay bounded original command bytes, process identities and closed jobs."""
    rows, identities, result = document["commands"], set(), {}
    require(isinstance(rows, list) and 1 <= len(rows) <= 64, "kubernetes-setup-command-count")
    previous, upper = uint(document["started_nanos"]), uint(document["finished_nanos"])
    for index, reference in enumerate(rows):
        match = re.fullmatch(r"commands/([0-9]{2})-([a-z0-9-]+)/receipt.json", reference["path"])
        require(match is not None and int(match[1]) == index and match[2] not in result,
                "kubernetes-setup-command-order")
        _artifact(root, reference, reference["path"])
        row = decode(_file(root, reference["path"]), MAX_JSON)
        fields(row, "argv cleanup_timeout_seconds creation_time_100ns cwd disk_free_before executable exit_code "
                    "failure finished_nanos job job_empty minimum_disk_free output_closed process_id reaped "
                    "started_nanos stderr stdout timeout_seconds")
        begin, end = uint(row["started_nanos"]), uint(row["finished_nanos"])
        require(previous <= begin <= end <= upper and row["exit_code"] == 0 and row["failure"] is None
                and all(row[key] is True for key in ("job_empty", "output_closed", "reaped")),
                "kubernetes-setup-command-cleanup")
        integer(row["timeout_seconds"], 1, 600)
        require(row["cleanup_timeout_seconds"] == 10, "kubernetes-setup-cleanup-timeout")
        fields(row["job"], "active terminated total")
        require(integer(row["job"]["active"]) == 0 and integer(row["job"]["total"], 1) >= integer(row["job"]["terminated"]),
                "kubernetes-setup-job-active")
        identity = (integer(row["process_id"], 1), uint(row["creation_time_100ns"]))
        require(identity[1] > 0 and identity not in identities, "kubernetes-setup-process-identity")
        identities.add(identity)
        require(uint(row["minimum_disk_free"]) >= setup_model.HEADROOM
                and uint(row["disk_free_before"]) >= setup_model.HEADROOM, "kubernetes-setup-disk-headroom")
        argv = row["argv"]
        require(isinstance(argv, list) and 1 <= len(argv) <= 64
                and all(isinstance(item, str) and len(item) <= 16384 and "\0" not in item for item in argv),
                "kubernetes-setup-command-argv")
        fields(row["executable"], "path bytes sha256")
        require(row["executable"]["path"] == argv[0] and PureWindowsPath(argv[0]).is_absolute()
                and PureWindowsPath(argv[0]).suffix.lower() == ".exe", "kubernetes-setup-command-executable")
        digest(row["executable"]["sha256"])
        require(0 < uint(row["executable"]["bytes"]) <= 256 * 1024**2, "kubernetes-setup-executable-bound")
        values = {}
        for stream in ("stdout", "stderr"):
            name = str(PurePosixPath(reference["path"]).parent / (stream + ".bin"))
            _artifact(root, row[stream], name)
            values[stream] = _file(root, name)
        result[match[2]] = {"raw": row, **values}
        previous = end
    return result


def _image_graph(setup, commands):
    images = setup["image_archive"]["images"]
    require(set(images) == set(setup_model.IMAGE_IDS) == set(setup["imported_images"]), "kubernetes-setup-image-set")
    worker = next(row["container_id"] for row in setup["nodes"] if row["role"] == "worker")
    selected = commands["runtime-images"]
    prefix = selected["raw"]["argv"][:3]
    require(PureWindowsPath(prefix[0]).name.lower() == "docker.exe" and prefix[1:] == ["--context", "desktop-linux"],
            "kubernetes-setup-docker-context")
    for arm, expected in images.items():
        require(expected["manifest_digest"] == setup_model.IMAGE_IDS[arm]
                and expected["tag"] == setup_model.IMAGE_PREFIX + ":" + arm, "kubernetes-setup-frozen-image")
    class RetainedCommands:
        def run(self, name, argv, *, parse=False):
            row = commands[name]
            require(row["raw"]["argv"] == argv, "kubernetes-setup-image-command-binding")
            require(not row["stderr"], "kubernetes-setup-image-command-stderr")
            data = row["stdout"]
            return data if parse == "bytes" else decode(data, MAX_JSON) if parse else data.decode("utf-8").strip()
    observed = setup_model._verify_runtime_images(RetainedCommands(), prefix, worker, setup["image_archive"])
    docker.equal(observed, setup["imported_images"], "kubernetes-setup-imported-image-projection")
    original = setup_model._outer_images(decode(commands["original-images"]["stdout"], MAX_JSON))
    docker.equal(original, setup["original_images"], "kubernetes-setup-original-images")
    docker.equal(original, setup_model._outer_images(decode(commands["original-images-after"]["stdout"], MAX_JSON)),
                 "kubernetes-setup-original-images-after")
    for arm, image in images.items():
        config = image["config"]
        require(config["rootfs"]["diff_ids"] == original[arm]["RootFS"]["Layers"]
                and config["config"]["Entrypoint"] == original[arm]["Config"]["Entrypoint"]
                and config["architecture"] == "amd64" and config["os"] == "linux"
                and len(config["rootfs"]["diff_ids"]) == len(image["layers"]), "kubernetes-setup-image-rootfs")
    return observed


def _provenance(root, setup, original):
    original_commands = _windows(root / "setup-provenance/original", original)
    require(len(original_commands) == 25 and "images-load" in original_commands,
            "kubernetes-original-setup-population")
    commands = _windows(root / "setup-provenance/resume", setup)
    required = {"docker-version", "original-images", "owned-nodes", "kubelet-control-plane", "kubelet-worker",
                "kubernetes-nodes", "runtime-images", "runtime-index", "original-images-after"}
    required |= {"runtime-" + kind + "-" + arm for kind in ("manifest", "config") for arm in setup_model.IMAGE_IDS}
    required |= {"import-" + arm for arm in setup_model.IMAGE_IDS}
    for group, identity in (("verifier-before", setup["source_before"]), ("verifier-after", setup["source_after"]),
                            ("original-before", original["source_before"]), ("original-after", original["source_before"])):
        for suffix in ("generated-untracked", "clean", "commit", "tree"):
            required.add(group + "-" + suffix)
        require(not commands[group + "-generated-untracked"]["stdout"] and not commands[group + "-clean"]["stdout"]
                and commands[group + "-commit"]["stdout"].decode().strip() == identity["commit"]
                and commands[group + "-tree"]["stdout"].decode().strip() == identity["tree"],
                "kubernetes-setup-original-source-output")
    require(set(commands) == required and len(commands) == 34, "kubernetes-resume-command-population")
    _image_graph(setup, commands)


def _journal(root, boot):
    lower, upper = uint(boot["started_nanos"]), uint(boot["finished_nanos"])
    data = _file(root, "bootstrap.ndjson", MAX_JOURNAL)
    lines = data.splitlines(keepends=True)
    require(len(lines) == 14, "kubernetes-bootstrap-journal-population")
    rows, previous = [], lower
    worker = boot["nodes"]["worker"]["container_id"]
    operations = ["api-negotiation", "node-identity-control-plane", "node-identity-worker", "controller-identity",
                  "kind-network-before", "controller-connect", "kind-network-after", "controller-alias",
                  "worker-identity", "kubectl-download", "worker-exec", None, "worker-exec", "worker-exec"]
    for index, line in enumerate(lines):
        require(len(line) <= 24 * 1024**2 and line.endswith(b"\n"), "kubernetes-bootstrap-journal-line")
        row = transport._line(line)
        require(row["ordinal"] == index and row.get("operation") == operations[index],
                "kubernetes-bootstrap-journal-order")
        if index == 0:
            fields(row, "ordinal provider operation failure receipt response")
            require(row["provider"] == "docker" and row["failure"] is None, "kubernetes-bootstrap-negotiation")
            raw = transport._blob(row["response"])
            start, end = transport._http(row["receipt"], method="GET", path="/version", status=200,
                                         request=b"", response=raw, lower=previous, upper=upper)
            value = decode(raw, MAX_JSON)
            require(boot["engine"] == {"api_version": API_VERSION, "server_version": value["Version"]}
                    and tuple(map(int, value["MinAPIVersion"].split("."))) <= (1, 54)
                    <= tuple(map(int, value["ApiVersion"].split("."))), "kubernetes-bootstrap-engine-version")
            derived = {"response_json": value}
        elif index == 8:
            derived, start, end = transport._identity(row, worker, previous, upper)
        elif index == 9:
            fields(row, "ordinal operation receipt archive")
            fields(row["archive"], "path bytes sha256")
            require(row["archive"]["path"] == "kubectl.tar" and 0 < uint(row["archive"]["bytes"]) <= 128 * 1024**2,
                    "kubernetes-bootstrap-download-bound")
            archive = {key: row["archive"][key] for key in ("bytes", "sha256")}
            start, end = transport._http(row["receipt"], method="GET", path=f"/v{API_VERSION}/containers/{worker}/archive?" +
                                         urlencode({"path": "/usr/bin/kubectl"}), status=200, request=b"", response=archive,
                                         lower=previous, upper=upper, download=True)
            require(row["receipt"]["destination"] == boot["output"] + "/kubectl.tar", "kubernetes-bootstrap-download-destination")
            derived = {"archive": row["archive"]}
        elif index in (10, 12, 13):
            derived, start, end = transport._exec(row, worker, previous, upper)
            expected = {10: ["sha256sum", "/usr/bin/kubectl"], 12: ["mkdir", "-p", "/var/local/lsf112"],
                        13: ["mkdir", "-m", "700", boot["worker_root"]]}[index]
            require(row["argv"] == expected and row["timeout_seconds"] == 20, "kubernetes-bootstrap-worker-command")
            if index != 10:
                require(not derived["stdout"], "kubernetes-bootstrap-mkdir-output")
        elif index == 11:
            derived, start, end = transport._kubernetes(row, previous, upper)
            require(row["method"] == "GET" and row["path"] == "/api/v1/nodes" and row["status"] == 200
                    and row["timeout_seconds"] == 15 and row["expected_statuses"] == [200], "kubernetes-bootstrap-node-api")
        else:
            fields(row, "ordinal provider operation method path request response receipt failure")
            require(row["provider"] == "docker" and row["failure"] is None, "kubernetes-bootstrap-api-failure")
            raw = transport._blob(row["response"])
            request = b"" if row["request"] is None else transport._wire(row["request"])
            start, end = transport._http(row["receipt"], method=row["method"], path="/v" + API_VERSION + row["path"],
                                         status=200, request=request, response=raw, lower=previous, upper=upper)
            derived = {"response_json": decode(raw, MAX_JSON) if raw else None}
        rows.append({"raw": row, **derived})
        previous = end
    return rows


def _bindings(boot, original, rows):
    nodes, owner = boot["nodes"], boot["owner"]
    require(boot["network_id"] == boot["network_identity"]["Id"], "kubernetes-bootstrap-network-id-binding")
    for index, role in ((1, "control-plane"), (2, "worker")):
        row = rows[index]
        require(row["raw"]["method"] == "GET" and row["raw"]["request"] is None
                and row["raw"]["path"] == "/containers/" + nodes[role]["container_id"] + "/json",
                "kubernetes-bootstrap-node-path")
        bootstrap._node(row["response_json"], nodes[role], owner, running=True)
        actual_limits, expected_limits = row["response_json"]["HostConfig"], nodes[role]["outer_limits"]
        require(actual_limits["NanoCpus"] == expected_limits["cpu_nano"]
                and actual_limits["Memory"] == expected_limits["memory_bytes"]
                and actual_limits["MemorySwap"] == expected_limits["memory_plus_swap_bytes"],
                "kubernetes-bootstrap-node-ceilings")
    controller = rows[3]["response_json"]
    bootstrap._controller(controller)
    require(bootstrap._connections(controller) == boot["controller_original_networks"]
            and "kind" not in boot["controller_original_networks"], "kubernetes-bootstrap-original-connections")
    for index in (3, 7):
        require(rows[index]["raw"]["method"] == "GET" and rows[index]["raw"]["request"] is None
                and rows[index]["raw"]["path"] == "/containers/" + bootstrap.CONTROLLER + "/json",
                "kubernetes-bootstrap-controller-path")
    identifiers = {node["container_id"] for node in nodes.values()}
    for index, path, members in ((4, "/networks/kind", identifiers),
                                  (6, "/networks/" + boot["network_id"], identifiers | {bootstrap.CONTROLLER})):
        row = rows[index]
        require(row["raw"]["method"] == "GET" and row["raw"]["request"] is None and row["raw"]["path"] == path
                and bootstrap._network_identity(row["response_json"]) == boot["network_identity"]
                and set(row["response_json"]["Containers"]) == members, "kubernetes-bootstrap-network-binding")
    connect = rows[5]["raw"]
    require(connect["method"] == "POST" and connect["path"] == "/networks/" + boot["network_id"] + "/connect"
            and connect["request"] == {"Container": bootstrap.CONTROLLER, "EndpointConfig": {"Aliases": [owner + "-controller"]}}
            and rows[5]["response_json"] in (None, {}), "kubernetes-bootstrap-connect-binding")
    connected = rows[7]["response_json"]
    bootstrap._controller(connected)
    bootstrap._alias(connected, boot["network_id"], owner)
    require(bootstrap._connections(connected) == {**boot["controller_original_networks"], "kind": boot["network_id"]}
            and rows[8]["owner"] == owner, "kubernetes-bootstrap-connected-owner")
    bootstrap._node(rows[8]["response_json"], nodes["worker"], owner, running=True)
    require(boot["network_created_by_setup"] is (not any(row.get("Name") == "kind" for row in original["networks_before"])),
            "kubernetes-bootstrap-network-created")
    observed = rows[11]["response_json"]["items"]
    require(len(observed) == 2 and {row["metadata"]["name"]: row["metadata"]["uid"] for row in observed}
            == {row["name"]: row["uid"] for row in nodes.values()}, "kubernetes-bootstrap-node-uids")
    require(boot["kubectl"]["worker_call"] == 10 and boot["node_api_call"] == 11 and boot["worker_root_create_call"] == 13
            and boot["worker_root"] == "/var/local/lsf112/" + owner, "kubernetes-bootstrap-call-references")


def _kubectl(root, boot, rows):
    artifact = rows[9]["archive"]
    _artifact(root, artifact, "kubectl.tar", 128 * 1024**2)
    _artifact(root, boot["kubectl"]["file"], "tools/kubectl", 128 * 1024**2)
    with tarfile.open(docker.relative(root, "kubectl.tar"), "r:") as archive:
        iterator = iter(archive)
        member = next(iterator, None)
        require(member is not None and member.isfile() and member.name == "kubectl" and 0 < member.size <= 128 * 1024**2
                and next(iterator, None) is None, "kubernetes-bootstrap-kubectl-member")
        with archive.extractfile(member) as stream:
            checksum = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
        require((checksum, member.size) == (boot["kubectl"]["file"]["sha256"], uint(boot["kubectl"]["file"]["bytes"])),
                "kubernetes-bootstrap-kubectl-original")
        encoded = rows[9]["raw"]["receipt"]["archive_stat_header"]
        require(isinstance(encoded, str) and len(encoded) <= 65536, "kubernetes-bootstrap-kubectl-header-bound")
        header = base64.b64decode(encoded, validate=True)
        require(base64.b64encode(header).decode() == encoded, "kubernetes-bootstrap-kubectl-header-base64")
        metadata = fields(decode(header, 65536), "name size mode mtime linkTarget")
        mode = integer(metadata["mode"])
        require(metadata["name"] == "kubectl" and integer(metadata["size"]) == member.size
                and mode & 0x88000000 == 0 and mode & 0o777 == member.mode & 0o777 and metadata["linkTarget"] == "",
                "kubernetes-bootstrap-kubectl-header")
    require(rows[10]["stdout"].decode().strip().split() == [checksum[7:], "/usr/bin/kubectl"],
            "kubernetes-bootstrap-kubectl-worker-hash")


def validate(root: Path) -> dict:
    """Return the verified bootstrap record; private credentials are metadata only."""
    boot = read_json(docker.relative(root, "bootstrap.json"), MAX_JSON)
    fields(boot, "controller_id controller_original_networks engine failure finished_nanos images kubectl network_created_by_setup "
                 "network_id network_identity node_api_call nodes original_setup output owner private_credentials private_kubeconfig "
                 "schema setup setup_file setup_sha256 source started_nanos status worker_root worker_root_create_call")
    require(boot["schema"] == "latent.optimization.kubernetes-bootstrap.v1" and boot["status"] == "connected-no-workload"
            and boot["failure"] is None and boot["controller_id"] == bootstrap.CONTROLLER,
            "kubernetes-bootstrap-unqualified")
    docker.source(boot["source"])
    require(boot["output"] == "/bench/kubernetes/" + boot["owner"], "kubernetes-bootstrap-original-root")
    _artifact(root, boot["setup"], "setup.json")
    _artifact(root, boot["original_setup"], "original-setup.json")
    setup, original = bootstrap._setup(SimpleNamespace(setup=root / "setup.json", original_setup=root / "original-setup.json"))
    require(setup["owner"] == boot["owner"] and bootstrap._nodes(setup) == boot["nodes"]
            and boot["setup_sha256"] == boot["setup"]["sha256"], "kubernetes-bootstrap-setup-owner")
    _provenance(root, setup, original)
    expected_images = {arm: {"tag": item["tag"], "original_docker_image_id": setup["original_images"][arm]["Id"],
                             "imported": setup["imported_images"][arm]} for arm, item in setup["image_archive"]["images"].items()}
    docker.equal(boot["images"], expected_images, "kubernetes-bootstrap-image-records")
    credentials = boot["private_credentials"]
    require(isinstance(credentials, list) and len(credentials) == 4, "kubernetes-bootstrap-credential-count")
    expected_paths = {"private/kubeconfig", "private/tls/ca.pem", "private/tls/client.pem", "private/tls/client.key"}
    require({row["path"] for row in credentials} == expected_paths, "kubernetes-bootstrap-credential-paths")
    for row in credentials:
        fields(row, "path bytes sha256")
        digest(row["sha256"])
        require(0 < uint(row["bytes"]) <= 32 * 1024, "kubernetes-bootstrap-credential-bound")
    copied = next(row for row in credentials if row["path"] == "private/kubeconfig")
    require(copied == setup["private_kubeconfig_identity"]
            and boot["private_kubeconfig"] == {"sha256": copied["sha256"], "publishable": False},
            "kubernetes-bootstrap-credential-identity")
    rows = _journal(root, boot)
    _bindings(boot, original, rows)
    _kubectl(root, boot, rows)
    return boot
