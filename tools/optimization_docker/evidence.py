"""Closed, offline replay of the original Docker comparison ownership graph."""
from __future__ import annotations

import base64
import binascii
from copy import deepcopy
import json
import hashlib
from pathlib import Path, PurePosixPath
import re
import tarfile
from urllib.parse import quote, urlencode

from tools.optimization_evidence.common import (
    canonical, decode, digest, fields, integer, read_json, require, sha256, text, uint, verify_artifact,
)
from tools.optimization_runner import fixtures as original_fixtures
from . import build, client_evidence, fixtures, images, model, resources
from .engine import API_VERSION, MAXIMUM_JSON
from .owned import LABEL, ROLE, configuration, mount


def equal(actual, expected, reason):
    require(canonical(actual) == canonical(expected), reason)


def relative(root, name):
    value = PurePosixPath(text(name, 4096))
    require(not value.is_absolute() and value.as_posix() == name and "\\" not in name
            and all(part not in (".", "..") and ":" not in part for part in value.parts), "docker-evidence-path")
    path = root
    for part in value.parts:
        path /= part
        require(not path.is_symlink(), "docker-evidence-symlink")
    return path


def original_root(value):
    path = PurePosixPath(text(value, 4096))
    require(path.is_relative_to("/bench") and path != PurePosixPath("/bench")
            and str(path) == value and ".." not in path.parts and "\\" not in value, "docker-original-root")
    return path


def source(value):
    fields(value, "commit tree clean cargo_lock_sha256")
    require(value["clean"] is True and all(isinstance(value[key], str)
            and re.fullmatch(r"[0-9a-f]{40}", value[key]) for key in ("commit", "tree")), "docker-source-identity")
    digest(value["cargo_lock_sha256"])


def source_closure(suite, root, built):
    source(suite["source"])
    source(built["source"])
    equal(suite["build_source"], built["source"], "docker-build-source-crossed")
    inputs = suite["collector_inputs"]
    require(isinstance(inputs, dict) and 1 <= len(inputs) <= 3500, "docker-collector-input-count")
    for name, reference in inputs.items():
        require(reference["path"] == "collector/source/" + name, "docker-collector-input-path")
        relative(root, reference["path"])
        verify_artifact(root, reference, model.MAX_FILE_BYTES)
    required = {
        "tools/optimization_docker/collect.py", "tools/optimization_docker/model.py",
        "tools/optimization_docker/applications.py", "tools/optimization_docker/session.py",
        "tools/optimization_docker/seeds.py", "tools/optimization_docker/owned.py",
        "tools/optimization_docker/engine.py", "tools/optimization_docker/resources.py",
    }
    require(required <= inputs.keys(), "docker-missing-collector-controls")
    require(all(name.startswith("tools/") and name.endswith(".py") for name in inputs), "docker-collector-python-scope")
    expected = {name: {key: row[key] for key in ("bytes", "sha256")}
                for name, row in built["inputs"].items() if not name.endswith(".py")}
    equal(suite["collector_build_inputs"], expected, "docker-binary-source-changed")
    require(suite["source"]["cargo_lock_sha256"] == expected["Cargo.lock"]["sha256"], "docker-collector-lock")


def journal(root, started, finished):
    """Bind original HTTP entity bytes, parsed values, requests, and closed sockets."""
    data = client_evidence._read(root / "engine.ndjson", model.MAX_FILE_BYTES)
    result, previous = [], started
    for line in data.splitlines(keepends=True):
        require(len(result) < 20000 and line.endswith(b"\n") and len(line) <= 24 * 1024**2,
                "docker-api-journal-bound")
        row = fields(decode(line, 24 * 1024**2), "ordinal method path request response receipt error response_bytes_base64")
        require(integer(row["ordinal"]) == len(result) and row["error"] is None, "docker-api-failed-or-sequence")
        receipt = fields(row["receipt"], "method path begin_nanos end_nanos status request_bytes request_sha256 "
                         "response_bytes response_sha256 response_complete connection_closed failure")
        path = text(row["path"], 16384)
        require(path.startswith("/") and not path.startswith("//") and all(33 <= ord(c) <= 126 for c in path)
                and receipt["method"] == row["method"] and receipt["path"] == "/v" + API_VERSION + path,
                "docker-api-version-or-path")
        begin, end = uint(receipt["begin_nanos"]), uint(receipt["end_nanos"])
        require(previous <= begin <= end <= finished and end - begin <= 600 * 10**9, "docker-api-clock")
        previous = end
        require(receipt["response_complete"] is True and receipt["connection_closed"] is True
                and receipt["failure"] is None, "docker-api-open-or-incomplete")
        require(integer(receipt["status"], 200, 599) in (200, 201, 204, 404), "docker-api-unexpected-status")
        encoded = text(row["response_bytes_base64"], 12 * 1024**2, empty=True)
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError("docker-api-response-base64") from error
        require(len(raw) <= MAXIMUM_JSON and base64.b64encode(raw).decode() == encoded
                and uint(receipt["response_bytes"]) == len(raw) and receipt["response_sha256"] == sha256(raw),
                "docker-api-response-bytes")
        equal(row["response"], decode(raw, MAXIMUM_JSON) if raw else None, "docker-api-parsed-response")
        request = b"" if row["request"] is None else json.dumps(row["request"], ensure_ascii=False,
                    allow_nan=False, separators=(",", ":")).encode()
        require(len(request) <= MAXIMUM_JSON and uint(receipt["request_bytes"]) == len(request)
                and receipt["request_sha256"] == sha256(request), "docker-api-request-bytes")
        result.append(row)
    require(result, "docker-empty-api-journal")
    return result


class Calls:
    def __init__(self, rows):
        self.rows = rows

    def at(self, ordinal, method, path):
        integer(ordinal, 0, len(self.rows)-1)
        row = self.rows[ordinal]
        require(row["method"] == method and row["path"] == path, "docker-crossed-api-reference")
        return row

    def find(self, method, path, response=None, *, after=-1, status=200):
        candidates = [row for row in self.rows if row["ordinal"] > after and row["method"] == method
                      and row["path"] == path and row["receipt"]["status"] == status
                      and (response is None or canonical(row["response"]) == canonical(response))]
        require(candidates, "docker-missing-api-binding")
        return candidates[0]


def inventory(root, value, *, retained=True):
    """Replay bytes and retained Unix modes; host extraction modes are not Unix evidence."""
    fields(value, "entries bytes")
    rows = value["entries"]
    require(isinstance(rows, list) and 1 <= len(rows) <= model.MAX_FILES+1, "docker-inventory-bound")
    names, total = [], 0
    for row in rows:
        fields(row, "path kind mode", "bytes sha256")
        name = row["path"]
        path = root if name == "." else relative(root, name)
        require(re.fullmatch(r"0[0-7]{3}", text(row["mode"], 4)) is not None, "docker-inventory-mode")
        require(name not in names, "docker-inventory-duplicate")
        names.append(name)
        if row["kind"] == "directory":
            # Portable archives omit empty directories; their original mode is
            # a source observation, not the extraction host's current mode.
            require(set(row) == {"path", "kind", "mode"}, "docker-inventory-directory")
        else:
            require(row["kind"] == "file" and set(row) == {"path", "kind", "mode", "bytes", "sha256"},
                    "docker-inventory-file")
            require(uint(row["bytes"]) <= model.MAX_FILE_BYTES, "docker-inventory-file-bound")
            digest(row["sha256"])
            if retained:
                verify_artifact(root, {key: row[key] for key in ("path", "bytes", "sha256")}, model.MAX_FILE_BYTES)
            total += uint(row["bytes"])
    require(names == sorted(names) and names[0] == "." and uint(value["bytes"]) == total <= model.MAX_TOTAL_BYTES,
            "docker-inventory-total")
    if retained:
        actual = fixtures.inventory(root)
        equal([{key: row[key] for key in row if key != "mode"} for row in rows if row["kind"] == "file"],
              [{key: row[key] for key in row if key != "mode"} for row in actual["entries"] if row["kind"] == "file"],
              "docker-inventory-file-set")


def fixture_set(built, build_root):
    value = fields(built["fixtures"], "schema base_component node_config token publications")
    require(value["schema"] == "latent.optimization.docker-fixtures.v1", "docker-fixture-schema")
    equal(value, read_json(build_root / "fixtures/fixtures.json"), "docker-fixture-sidecar")
    equal(value["base_component"], built["component"], "docker-fixture-base")
    base = verify_artifact(build_root, built["component"], 16*1024**2).read_bytes()
    require(base[:8] == b"\0asm\x0d\0\x01\0", "docker-fixture-component")
    equal(read_json(verify_artifact(build_root, value["node_config"], 65536)), fixtures.node_configuration(),
          "docker-fixture-node-config")
    require(verify_artifact(build_root, value["token"], 259).read_bytes() == (model.TOKEN+"\n").encode(),
            "docker-fixture-credential")
    rows = value["publications"]
    require(isinstance(rows, list) and len(rows) == 32, "docker-fixture-population")
    capsule_base = read_json(verify_artifact(build_root, built["inputs"]["examples/echo-contract/capsule.json"], 65536))
    deployment_base = read_json(verify_artifact(build_root, built["inputs"]["examples/echo-contract/deployment.json"], 65536))
    result = {}
    for index, row in enumerate(rows):
        fields(row, "index service component capsule contracts deployment")
        require(type(row["index"]) is int and row["index"] == index and row["service"] == model.SERVICES[index],
                "docker-fixture-service-order")
        for key, filename in (("component", f"component-{index}.wasm"), ("capsule", f"capsule-{index}.json"),
                              ("deployment", f"deployment-{index}.json"), ("contracts", "contracts.json")):
            require(row[key]["path"] == "fixtures/"+filename, "docker-fixture-reference")
            verify_artifact(build_root, row[key], 16*1024**2)
        name = b"optimization-working-set-v1"
        section = original_fixtures.leb(len(name))+name+bytes([index])
        expected = base if index == 0 else base+b"\0"+original_fixtures.leb(len(section))+section
        require((build_root/row["component"]["path"]).read_bytes() == expected, "docker-fixture-component-delta")
        capsule = deepcopy(capsule_base)
        capsule["metadata"] = {"name": row["service"], "tenant": model.TENANT}
        capsule["component"].update(digest=sha256(expected), world="optimization:benchmark/service@0.1.0")
        capsule["exports"], capsule["imports"] = [model.CONTRACT], []
        capsule["execution"].update(threading="single-threaded", snapshotEligible=False, fusionEligible=False)
        capsule["execution"]["limits"].update(cpuFuel=10_000_000_000, memoryBytes=67_108_864)
        equal(read_json(build_root/row["capsule"]["path"]), capsule, "docker-fixture-capsule")
        deployment = deepcopy(deployment_base)
        deployment["metadata"] = {"name": f"optimization-{index}", "tenant": model.TENANT}
        deployment["spec"].update(service=row["service"], release=sha256(expected), grants=[])
        deployment["spec"]["resources"].update(cpuFuel=10_000_000_000, memoryBytes=67_108_864)
        equal(read_json(build_root/row["deployment"]["path"]), deployment, "docker-fixture-deployment")
        equal(read_json(build_root/row["contracts"]["path"]), original_fixtures.contracts(), "docker-fixture-contract")
        result[row["service"]] = {"release": sha256(expected), "deployment": deployment, "publication": row}
    return result


def http_body(build_root, receipt_ref, body_ref, *, method, path):
    receipt = read_json(verify_artifact(build_root, receipt_ref, 65536))
    fields(receipt, "method path begin_nanos end_nanos status request_bytes request_sha256 response_bytes response_sha256 "
           "response_complete connection_closed failure")
    body_path = verify_artifact(build_root, body_ref, 8*1024**2)
    data = client_evidence._read(body_path, 8*1024**2)
    require(receipt["method"] == method and receipt["path"] == path and receipt["status"] == 200
            and receipt["response_complete"] is True and receipt["connection_closed"] is True
            and receipt["failure"] is None and uint(receipt["begin_nanos"]) <= uint(receipt["end_nanos"])
            and uint(receipt["response_bytes"]) == len(data) and receipt["response_sha256"] == sha256(data),
            "docker-image-http-receipt")
    if method == "GET":
        require(uint(receipt["request_bytes"]) == 0 and receipt["request_sha256"] == sha256(b""), "docker-image-get-body")
    return receipt, data


def context_tar_hash(root, members):
    class Sink:
        def __init__(self):
            self.hash, self.bytes = hashlib.sha256(), 0

        def write(self, block):
            self.bytes += len(block)
            require(self.bytes <= 512*1024**2, "docker-context-tar-bound")
            self.hash.update(block)
            return len(block)

        def tell(self):
            return self.bytes

    sink = Sink()
    inventory(root, {"entries": members, "bytes": str(sum(uint(row["bytes"]) for row in members if row["kind"] == "file"))})
    with tarfile.open(fileobj=sink, mode="w", format=tarfile.USTAR_FORMAT) as target:
        for row in members:
            if row["path"] == ".":
                continue
            info = tarfile.TarInfo(row["path"])
            info.mode, info.uid, info.gid, info.mtime = int(row["mode"], 8), 0, 0, 0
            if row["kind"] == "directory":
                info.type = tarfile.DIRTYPE
                target.addfile(info)
            else:
                info.size = uint(row["bytes"])
                require(row["path"] == "Dockerfile" or info.mode == 0o755, "docker-context-executable-mode")
                with relative(root, row["path"]).open("rb") as original:
                    target.addfile(info, original)
    return "sha256:"+sink.hash.hexdigest(), str(sink.bytes)


def image_set(suite, built, build_root, calls):
    require(isinstance(suite["images"], dict) and set(suite["images"]) == {"lsf", "native", "client"}, "docker-images")
    image_build = fields(read_json(build_root/"images.json"), "schema owner build engine base images builds")
    require(image_build["schema"] == "latent.optimization.docker-images.v1"
            and re.fullmatch(r"lsf111-images-[0-9a-f]{20}", text(image_build["owner"], 64)), "docker-image-build-envelope")
    equal(image_build["images"], suite["images"], "docker-image-sidecar")
    equal(image_build["build"], suite["build_receipt"], "docker-image-build-reference")
    require(set(image_build["builds"]) == set(suite["images"]), "docker-image-build-count")
    engine = fields(image_build["engine"], "api_version server_version version_http version_response")
    require(engine["api_version"] == API_VERSION, "docker-image-api-version")
    _, version_data = http_body(build_root, engine["version_http"], engine["version_response"], method="GET", path="/version")
    require(decode(version_data)["Version"] == engine["server_version"], "docker-image-server-version")
    base = fields(image_build["base"], "requested inspect_http inspect_response")
    require(base["requested"] == model.BASE_IMAGE, "docker-image-base-request")
    _, base_data = http_body(build_root, base["inspect_http"], base["inspect_response"], method="GET",
                             path="/v"+API_VERSION+"/images/"+quote(model.BASE_IMAGE, safe="")+"/json")
    base_image = decode(base_data)
    base_digest = model.BASE_IMAGE.split("@", 1)[1]
    require(base_image["Os"] == "linux" and base_image["Architecture"] == "amd64"
            and (base_digest in (base_image.get("Id"), (base_image.get("Descriptor") or {}).get("digest"))
                 or any(item.endswith("@"+base_digest) for item in base_image.get("RepoDigests", []))), "docker-image-base-identity")
    for kind, image in suite["images"].items():
        raw = calls.find("GET", "/images/"+image["image_id"]+"/json")["response"]
        equal(images.inspect_receipt(kind, raw, image["context"]), image, "docker-image-inspect-replay")
        context = fields(image["context"], "kind base context dockerfile executables build_arguments")
        require(context["kind"] == kind and context["base"] == model.BASE_IMAGE
                and context["context"] == "images/contexts/"+kind, "docker-image-context")
        recipe = "tools/optimization-docker/"+("client.Dockerfile" if kind == "client" else "app.Dockerfile")
        context_path = original_root(suite["build_path"])/context["context"]
        equal(context["build_arguments"], ["build", "--network=none", "--pull=false", "--file",
              str(context_path/"Dockerfile"), str(context_path)], "docker-image-context-arguments")
        equal({key: context["dockerfile"][key] for key in ("sha256", "bytes")},
              {key: built["inputs"][recipe][key] for key in ("sha256", "bytes")}, "docker-image-recipe")
        verify_artifact(build_root, context["dockerfile"], 65536)
        selected = {"client"} if kind == "client" else {kind, "wrapper"} | ({"cli"} if kind == "lsf" else set())
        require(set(context["executables"]) == selected, "docker-image-executables")
        for key, ref in context["executables"].items():
            verify_artifact(build_root, ref, model.MAX_FILE_BYTES)
            equal({field: ref[field] for field in ("sha256", "bytes")},
                  {field: built["executables"][key][field] for field in ("sha256", "bytes")}, "docker-image-binary")
        row = fields(image_build["builds"][kind], "context_archive context_members query build_http build_response "
                     "inspect_http inspect_response consumed_receipt")
        expected_members = {"Dockerfile"} | {str(PurePosixPath(ref["path"]).relative_to(context["context"]))
                                             for ref in context["executables"].values()}
        require({entry["path"] for entry in row["context_members"] if entry["kind"] == "file"} == expected_members,
                "docker-image-extra-context-file")
        expected_query = {"t": image_build["owner"]+":"+kind, "labels": {LABEL: image_build["owner"], ROLE: kind},
                          "dockerfile": "Dockerfile", "networkmode": "none", "pull": "0", "rm": "1", "forcerm": "1",
                          "version": "1", "platform": "linux/amd64"}
        equal(row["query"], expected_query, "docker-image-build-query")
        query = {key: expected_query[key] for key in ("dockerfile", "networkmode", "pull", "rm", "forcerm", "version", "platform")}
        query.update(t=expected_query["t"], labels=json.dumps(expected_query["labels"], sort_keys=True, separators=(",", ":")))
        request, response_data = http_body(build_root, row["build_http"], row["build_response"], method="POST",
                                          path="/v"+API_VERSION+"/build?"+urlencode(query))
        archive = fields(row["context_archive"], "source_path sha256 bytes retained")
        require(archive["retained"] is False and PurePosixPath(archive["source_path"]).parent == PurePosixPath("/bench/scratch"),
                "docker-image-context-scratch")
        checksum, size = context_tar_hash(relative(build_root, context["context"]), row["context_members"])
        require((archive["sha256"], archive["bytes"]) == (checksum, size)
                == (request["request_sha256"], request["request_bytes"]), "docker-image-context-wire-bytes")
        for line in response_data.splitlines():
            record = decode(line, 8*1024**2)
            require(isinstance(record, dict) and not record.get("error") and not record.get("errorDetail"), "docker-image-build-failure")
        require(response_data, "docker-image-missing-build-response")
        _, inspect_data = http_body(build_root, row["inspect_http"], row["inspect_response"], method="GET",
                                   path="/v"+API_VERSION+"/images/"+quote(expected_query["t"], safe="")+"/json")
        equal(images.inspect_receipt(kind, decode(inspect_data), context), image, "docker-image-build-inspect")
        require(image["config"].get("Labels", {}).get(LABEL) == image_build["owner"]
                and image["config"].get("Labels", {}).get(ROLE) == kind, "docker-image-build-labels")
        consumed = deepcopy(row)
        del consumed["consumed_receipt"]
        del consumed["context_archive"]["retained"]
        equal(read_json(verify_artifact(build_root, row["consumed_receipt"], 65536)),
              {"image_id": image["image_id"], "build": consumed}, "docker-image-consumed-receipt")


def owner_rows(suite):
    owners = []
    require(len(suite["setup"]) == 3, "docker-seed-count")
    for density, seed in zip(model.DENSITIES, suite["setup"]):
        require(seed["density"] == density, "docker-seed-order")
        owners.append((seed["owner"], "lsf", density, f"seed-d{density}", None))
    groups = [group for pair in suite["plan"]["groups"] for group in pair]
    require(len(suite["groups"]) == len(groups), "docker-group-count")
    for index, (value, expected) in enumerate(zip(suite["groups"], groups)):
        pair = index//6
        require(value["pair"] == pair and value["group"] == expected["ordinal"]
                and value["arm"] == expected["arm"] and value["density"] == expected["density"], "docker-group-order")
        count = 1 if expected["arm"] == "lsf" else expected["density"]
        require(len(value["owners"]) == count, "docker-app-owner-count")
        for position, owner in enumerate(value["owners"]):
            role = f"p{pair}-g{expected['ordinal']}-{expected['arm']}-{position}"
            owners.append((owner, expected["arm"], expected["density"], role, position))
    return owners


def configurations(suite, owners):
    collection, build_path = original_root(suite["collection_path"]), original_root(suite["build_path"])
    require(not collection.is_relative_to(build_path) and not build_path.is_relative_to(collection), "docker-root-overlap")
    network = suite["cleanup"]["network_id"]
    volume = text(suite["volume"], 128)
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", volume) is not None, "docker-volume-name")
    fixture_mount = mount(volume, str((build_path/"fixtures").relative_to("/bench")), "/fixtures", True)
    result = {}
    for owner, arm, density, role, position in owners:
        seed = role == f"seed-d{density}"
        require(owner["role"] == role and owner["arm"] == arm and owner["density"] == density
                and owner["output"] == "owners/"+role
                and owner["endpoint"] == "http://"+("127.0.0.1" if seed else role)+":7070"
                and owner["owner_ref"] == "owner-"+owner["container_id"], "docker-app-owner-identity")
        mounts = [fixture_mount, mount(volume, str((collection/owner["output"]).relative_to("/bench")), "/output")]
        if arm == "lsf":
            mounts.append(mount(volume, str((collection/"data"/role).relative_to("/bench")), "/data"))
        argv = ["--app", arm, "--executable", "/opt/lsf/"+("latentd" if arm == "lsf" else "optimization-native"),
                "--output", "/output"]
        argv += ["--config", "/fixtures/node.json"] if arm == "lsf" else ["--token-file", "/fixtures/token",
                                                                                   "--service", model.SERVICES[position]]
        result[role] = (owner["container_id"], configuration(suite["images"][arm]["image_id"], argv,
            arm=arm, density=density, network=network, mounts=mounts, owner=suite["run_id"], role=role,
            network_namespace=suite["environment"]["controller"]["Id"] if seed else None))
    require(len(suite["clients"]) == suite["plan"]["repetitions"], "docker-client-count")
    for pair, client in enumerate(suite["clients"]):
        require(client["pair"] == pair and client["directory"] == f"clients/{pair}", "docker-client-order")
        role = f"client-p{pair}"
        result[role] = (client["container_id"], configuration(suite["images"]["client"]["image_id"],
            ["--session", "/output/plan.json", "--output", "/output"], arm="client", density=1,
            network=network, mounts=[fixture_mount, mount(volume,
                str((collection/client["directory"]).relative_to("/bench")), "/output")],
            owner=suite["run_id"], role=role, interactive=True))
    require(len({row[0] for row in result.values()}) == len(result), "docker-container-id-reuse")
    return result


def api_protocol(rows, suite, configs):
    """Finite allowlist plus actual create/start/wait/delete state transitions."""
    network = suite["cleanup"]["network_id"]
    require(re.fullmatch(r"[0-9a-f]{64}", text(network, 64)) is not None, "docker-network-id")
    run = suite["run_id"]
    names = {run+"-"+role: (role, row[0], row[1]) for role, row in configs.items()}
    identities = {row[0]: (role, row[1]) for role, row in configs.items()}
    controller = suite["environment"]["controller"]["Id"]
    require(controller not in identities, "docker-controller-is-measured-owner")
    states, signals = {}, {cid: [] for cid in identities}
    net_created = net_removed = connected = False
    created_names, absent = set(), set()
    network_body = {"Name": run+"-bridge", "CheckDuplicate": True, "Driver": "bridge", "Internal": True,
                    "Attachable": False, "EnableIPv6": False, "Labels": {LABEL: run, ROLE: "bridge"}}
    for row in rows:
        method, path, body, response = (row[key] for key in ("method", "path", "request", "response"))
        status = row["receipt"]["status"]
        if method == "GET":
            require(body is None, "docker-get-with-body")
        if path in ("/version", "/info"):
            require(method == "GET" and status == 200 and not states, "docker-engine-environment-order")
        elif path.startswith("/images/"):
            require(method == "GET" and status == 200 and path in {
                "/images/"+image["image_id"]+"/json" for image in suite["images"].values()} and not states,
                "docker-unexpected-image-api")
        elif path == "/networks/create":
            equal(body, network_body, "docker-private-network-config")
            require(method == "POST" and status == 201 and not net_created and response["Id"] == network,
                    "docker-network-create")
            net_created = True
        elif path == "/networks/"+run+"-bridge":
            require(method == "GET" and status == (200 if net_created else 404), "docker-network-name-probe")
            if status == 200:
                require(response["Id"] == network and response["Labels"] == network_body["Labels"], "docker-network-reconcile")
        elif path == "/networks/"+network+"/connect":
            require(method == "POST" and status == 200 and net_created and not connected and not states,
                    "docker-controller-connect")
            equal(body, {"Container": controller}, "docker-controller-connect-body")
            connected = True
        elif path == "/networks/"+network+"/disconnect":
            require(method == "POST" and status == 200 and connected and all(state == "absent" for state in states.values()),
                    "docker-controller-disconnect")
            equal(body, {"Container": controller, "Force": False}, "docker-controller-disconnect-body")
            connected = False
        elif path == "/networks/"+network:
            if method == "DELETE":
                require(status == 204 and body is None and not connected and not net_removed
                        and set(states) == set(identities) and all(state == "absent" for state in states.values()),
                        "docker-network-delete-live-owner")
                net_removed = True
            else:
                require(method == "GET" and status == (404 if net_removed else 200), "docker-network-probe")
                if status == 200:
                    require(response["Id"] == network and response["Driver"] == "bridge" and response["Internal"] is True
                            and response["Labels"] == network_body["Labels"] and not response["Containers"],
                            "docker-private-empty-network")
                else:
                    absent.add(network)
        elif path == "/containers/"+controller+"/json":
            require(method == "GET" and status == 200 and not states and response["State"]["Running"] is True
                    and response["Config"]["Labels"].get(LABEL) == "issue111-controller-01", "docker-controller-identity")
            equal(response, suite["environment"]["controller"], "docker-controller-inspect-binding")
        elif path.startswith("/volumes/"):
            require(path == "/volumes/"+suite["volume"] and method == "GET" and status == 200
                    and connected and not states, "docker-owned-volume-order")
            equal(response, suite["environment"]["volume"], "docker-volume-inspect-binding")
        elif path.startswith("/containers/create?name="):
            name = path.removeprefix("/containers/create?name=")
            require(name in names and name not in created_names and method == "POST" and status == 201
                    and connected, "docker-unexpected-container-create")
            role, cid, expected = names[name]
            equal(body, expected, "docker-container-exact-config")
            require(response["Id"] == cid and not response.get("Warnings"), "docker-container-create-result")
            states[cid] = "created"
            created_names.add(name)
        elif path.startswith("/containers/"):
            token, slash, suffix = path[len("/containers/"):].partition("/")
            if token in names:
                role, cid, _ = names[token]
                require(method == "GET" and suffix == "json" and status == (200 if cid in states else 404),
                        "docker-container-name-probe")
                if status == 200:
                    require(response["Id"] == cid and response["Name"] == "/"+token
                            and response["Config"]["Labels"] == {LABEL: run, ROLE: role}, "docker-container-name-binding")
                continue
            cid = token.split("?", 1)[0]
            require(cid in identities, "docker-unowned-container-api")
            role, expected = identities[cid]
            state = states.get(cid)
            if method == "POST" and suffix == "start":
                require(body is None and status == 204 and state == "created", "docker-container-start")
                states[cid] = "started"
            elif method == "POST" and suffix == "kill?signal=SIGUSR1":
                require(body is None and status == 204 and state == "started" and not role.startswith(("seed-", "client-")),
                        "docker-unexpected-signal")
                signals[cid].append(row["ordinal"])
            elif method == "POST" and suffix == "stop?t=30":
                require(body is None and status == 204 and state == "started" and not role.startswith("client-"),
                        "docker-container-stop")
                states[cid] = "stopping"
            elif method == "POST" and suffix == "wait?condition=not-running":
                require(body is None and status == 200 and state == ("started" if role.startswith("client-") else "stopping"),
                        "docker-container-wait")
                require(type(response.get("StatusCode")) is int and response["StatusCode"] == 0 and not response.get("Error"),
                        "docker-container-exit")
                states[cid] = "waited"
            elif method == "DELETE" and token == cid+"?v=false&force=false" and not slash:
                require(body is None and status == 204 and state == "waited", "docker-container-delete")
                states[cid] = "removed"
            elif method == "GET" and suffix == "json":
                if state == "removed":
                    require(status == 404, "docker-container-still-present")
                    states[cid] = "absent"
                else:
                    require(status == 200 and state in ("started", "stopping", "waited")
                            and response["Id"] == cid and response["Name"] == "/"+run+"-"+role
                            and response["Image"] == expected["Image"]
                            and response["Config"]["Labels"] == expected["Labels"], "docker-container-inspect")
                    require(response["State"]["OOMKilled"] is False, "docker-container-oom")
                    if "NetworkSettings" in response:
                        networks = response["NetworkSettings"]["Networks"]
                        if role.startswith("seed-"):
                            require(networks == {} and response["HostConfig"]["NetworkMode"] == "container:"+controller,
                                    "docker-seed-network-namespace")
                        else:
                            require(isinstance(networks, dict) and len(networks) == 1
                                    and next(iter(networks.values()))["NetworkID"] == network,
                                    "docker-container-network-isolation")
                        require(all(value is None for value in (response["NetworkSettings"].get("Ports") or {}).values()),
                                "docker-container-published-port")
                    if state == "waited":
                        require(response["State"]["Running"] is False and response["State"]["ExitCode"] == 0,
                                "docker-container-unreaped-inspect")
            elif method == "GET" and suffix == "stats?stream=false&one-shot=true":
                require(status == 200 and state == "started" and role.startswith("client-"), "docker-unexpected-stats")
            else:
                raise ValueError("docker-unexpected-container-operation")
        else:
            raise ValueError("docker-unexpected-engine-operation")
    require(set(states) == set(identities) and all(state == "absent" for state in states.values())
            and net_removed and network in absent and not connected, "docker-incomplete-owner-cleanup")
    for cid, (role, _) in identities.items():
        require(len(signals[cid]) == (0 if role.startswith(("seed-", "client-")) else 6), "docker-signal-count")
    return signals


def lifecycle(parent, calls, cleanup):
    cid = parent["container_id"]
    start = fields(parent["start"], "started_nanos finished_nanos call")
    row = calls.at(start["call"], "POST", f"/containers/{cid}/start")
    begin, end = uint(start["started_nanos"]), uint(start["finished_nanos"])
    require(begin <= uint(row["receipt"]["begin_nanos"]) <= uint(row["receipt"]["end_nanos"]) <= end,
            "docker-start-clock-binding")
    ready = calls.find("GET", f"/containers/{cid}/json", parent["ready_inspect"], after=row["ordinal"])
    final = fields(parent["final"], "wait inspect")
    waited = calls.find("POST", f"/containers/{cid}/wait?condition=not-running", final["wait"], after=ready["ordinal"])
    stopped = calls.find("GET", f"/containers/{cid}/json", final["inspect"], after=waited["ordinal"])
    removed = calls.find("DELETE", f"/containers/{cid}?v=false&force=false", after=stopped["ordinal"], status=204)
    absent = calls.find("GET", f"/containers/{cid}/json", after=removed["ordinal"], status=404)
    rows = [value for value in cleanup["containers"] if value["container_id"] == cid]
    require(len(rows) == 1, "docker-cleanup-owner-count")
    equal(rows[0], {"container_id": cid, "name": final["inspect"]["Name"], "removed": True,
                   "absence_call": absent["ordinal"], "exit_code": 0, "oom_killed": False}, "docker-cleanup-owner-binding")
    return {"start": start, "ready_inspect_call": ready["ordinal"], "wait_call": waited["ordinal"],
            "final_inspect_call": stopped["ordinal"], "remove_call": removed["ordinal"],
            "absence_call": absent["ordinal"], "absent_nanos": absent["receipt"]["end_nanos"]}


def app_resources(root, parent, calls, cleanup, snapshots, connections):
    fields(parent, "role arm density container_id owner_ref endpoint app_process_id output start ready_inspect final "
           "event_observations snapshots template_copy data_inventory", "data_cleanup")
    derived = resources.validate(relative(root, parent["output"]), arm=parent["arm"], density=parent["density"],
        container_id=parent["container_id"], ready_inspect=parent["ready_inspect"],
        final_inspect=parent["final"]["inspect"], expected_snapshots=snapshots, expected_connections=connections)
    require(derived["identity"]["child_pid"] == parent["app_process_id"], "docker-app-process-binding")
    life = lifecycle(parent, calls, cleanup)
    events = [decode(line, resources.EVENT_BYTES) for line in
              (relative(root, parent["output"])/"events.ndjson").read_bytes().splitlines()]
    seen = parent["event_observations"]
    require(len(seen) == len(events), "docker-parent-event-observation-count")
    lower = uint(parent["start"]["started_nanos"])
    upper, previous = None, lower
    for index, (observation, event) in enumerate(zip(seen, events)):
        fields(observation, "sequence observed_nanos")
        require(integer(observation["sequence"]) == index, "docker-parent-event-sequence")
        observed = uint(observation["observed_nanos"])
        require(previous <= observed <= uint(calls.rows[life["remove_call"]]["receipt"]["begin_nanos"]),
                "docker-parent-event-clock")
        previous = observed
        possible = observed - uint(event["elapsed_nanos"])
        upper = possible if upper is None else min(upper, possible)
    require(uint(seen[1]["observed_nanos"]) <= uint(parent["start"]["finished_nanos"])+120*10**9,
            "docker-ready-parent-deadline")
    require(len(parent["snapshots"]) == snapshots, "docker-parent-snapshot-count")
    for index, (sample, event) in enumerate(zip(parent["snapshots"], events[2:-1]), 1):
        fields(sample, "snapshot_index signal_before_nanos call observed_nanos event_sequence")
        require(sample["snapshot_index"] == index and sample["event_sequence"] == event["sequence"],
                "docker-parent-snapshot-binding")
        call = calls.at(sample["call"], "POST", f"/containers/{parent['container_id']}/kill?signal=SIGUSR1")
        before, observed = uint(sample["signal_before_nanos"]), uint(sample["observed_nanos"])
        require(before <= uint(call["receipt"]["begin_nanos"]) <= uint(call["receipt"]["end_nanos"]) <= observed
                and observed-before <= 10*10**9 and uint(seen[event["sequence"]]["observed_nanos"]) <= observed,
                "docker-snapshot-parent-clock")
        lower = max(lower, before-uint(event["detail"]["started_nanos"]))
        upper = min(upper, observed-uint(event["detail"]["finished_nanos"]))
    require(upper is not None and lower <= upper, "docker-wrapper-clock-association")
    life["wrapper_origin_parent_nanos_interval"] = {"minimum": str(lower), "maximum": str(upper)}
    life["ready_event"] = events[1]
    return {"parent": parent, "resources": derived, "lifecycle": life}


def node_inventory(value, *, expected_entries, expected_grants=None):
    fields(value, "node cellCapacity memoryPressureMilli queueDepth routeGeneration cacheEntries observedAtUnixMillis "
           "cacheSummary pressure health topology quotas retainedBytes")
    client_evidence._inventory_fields(value)
    require(value["health"]["ready"] is True and value["queueDepth"] == "0"
            and len(value["cellCapacity"]) == 1, "docker-node-idle-health")
    cell = value["cellCapacity"][0]
    require(cell["class"] == "standard" and cell["observationAvailable"] is True and cell["accepting"] is True
            and cell["total"] == cell["available"] == 4 and cell["queueCapacity"] == 64
            and all(uint(cell[key]) == 0 for key in ("rejected", "cancellations", "expired")), "docker-node-cell-config")
    if expected_grants is not None:
        require(uint(cell["granted"]) == expected_grants, "docker-node-hidden-invocations")
    cache = value["cacheSummary"]
    require(cache["available"] is True and uint(cache["maximumEntries"]) == 32
            and uint(cache["entries"]) == expected_entries and uint(cache["maximumConcurrentPreparations"]) == 1
            and all(uint(cache[key]) == 0 for key in ("preparing", "preparingSourceBytes", "preparingMetadataBytes")),
            "docker-node-cache-config")
    require(value["topology"]["available"] is True and value["topology"]["complete"] is True
            and value["quotas"] is not None, "docker-node-missing-topology")
    names = [row["name"] for row in value["topology"]["entries"]]
    require(len(names) == len(set(names)), "docker-node-topology-duplicate")


def applied_manifest(source):
    """The manifest codec sorts architectures and omits empty optional fields."""
    value = deepcopy(source)
    spec = value["spec"]
    if spec.get("grants") == []:
        del spec["grants"]
    if spec["resources"].get("wallTimeLimitMillis") is None:
        spec["resources"].pop("wallTimeLimitMillis", None)
    spec["placement"]["architectures"].sort()
    return value


def seeds(suite, root, built, calls, publications):
    results, helper_ids, total = {}, set(), 0
    build_path = original_root(suite["build_path"])
    for density, value in zip(model.DENSITIES, suite["setup"]):
        fields(value, "schema density owner calls before after template template_path resources")
        require(value["schema"] == model.PREFIX+"seed.v1" and value["density"] == density
                and value["template_path"] == f"data/seed-d{density}", "docker-seed-shape")
        equal(value, read_json(root/f"seeds/{density}/seed.json"), "docker-seed-sidecar")
        app = app_resources(root, value["owner"], calls, suite["cleanup"], 0, None)
        equal(value["resources"], app["resources"], "docker-seed-resource-replay")
        require(value["owner"]["template_copy"] is None and not value["owner"]["snapshots"], "docker-seed-pristine-start")
        expected = [("inventory-before", ["node", "get", "optimization-node"], None)]
        for index in range(density):
            base = str(build_path/"fixtures")
            expected += [(f"publish-{index}", ["release", "publish", "--manifest", f"{base}/capsule-{index}.json",
                "--component", f"{base}/component-{index}.wasm", "--contracts", f"{base}/contracts.json"], index),
                (f"apply-{index}", ["deployment", "apply", f"{base}/deployment-{index}.json"], index)]
        expected.append(("inventory-after", ["node", "get", "optimization-node"], None))
        require(len(value["calls"]) == len(expected), "docker-seed-command-count")
        for row, (name, arguments, index) in zip(value["calls"], expected):
            fields(row, "name arguments process log result")
            require(row["name"] == name, "docker-seed-command-order")
            equal(row["arguments"], arguments, "docker-seed-command-arguments")
            require(row["log"]["path"] == f"seeds/{density}/{name}.json.log", "docker-seed-log-path")
            log = verify_artifact(root, row["log"], 2*1024**2)
            result = read_json(log, 2*1024**2)
            equal(result, row["result"], "docker-seed-original-result")
            process = fields(row["process"], "process_id start_time_ticks role executable_sha256 reaped output_closed exit_code")
            require(integer(process["process_id"], 1) > 1 and process["role"] == "artifact-identity-helper"
                    and process["executable_sha256"] == built["executables"]["cli"]["sha256"]
                    and process["reaped"] is True and process["output_closed"] is True
                    and type(process["exit_code"]) is int and process["exit_code"] == 0, "docker-seed-helper-owner")
            identity = (process["process_id"], str(process["start_time_ticks"]))
            require(uint(identity[1]) > 0 and identity not in helper_ids, "docker-seed-helper-identity")
            helper_ids.add(identity)
            equal(read_json(log.with_suffix(log.suffix+".process.json")), process, "docker-seed-helper-sidecar")
            fields(result, "schemaVersion command category data error requestDispatched outcomeKnown")
            require(result["schemaVersion"] == "latent.cli.result.v1" and result["category"] == "success"
                    and result["command"] == " ".join(arguments[:2]) and result["error"] is None
                    and result["outcomeKnown"] is True and type(result["requestDispatched"]) is bool,
                    "docker-seed-result-failure")
            if name.startswith("inventory"):
                equal(result["data"]["inventory"], value["before" if name.endswith("before") else "after"],
                      "docker-seed-inventory-binding")
            elif name.startswith("publish"):
                publication = publications[model.SERVICES[index]]
                release = result["data"]["release"]
                require(release["digest"] == publication["release"] and release["service"] == model.SERVICES[index]
                        and release["tenant"] == model.TENANT and release["admitted"] is True
                        and result["data"]["admissionWarnings"] == [], "docker-seed-publication-result")
            else:
                deployment = result["data"]["deployment"]
                require(uint(deployment["generation"]) == index+1 and result["data"]["warnings"] == [],
                        "docker-seed-deployment-generation")
                equal(deployment["manifest"], applied_manifest(publications[model.SERVICES[index]]["deployment"]),
                      "docker-seed-applied-manifest")
            total += 1
        for observed in (value["before"], value["after"]):
            node_inventory(observed, expected_entries=0, expected_grants=0)
        require(uint(value["before"]["routeGeneration"]) == 0 and uint(value["after"]["routeGeneration"]) == density,
                "docker-seed-route-generation")
        template = fields(value["template"], "schema density stop inventory")
        require(template["schema"] == "latent.optimization.docker-template.v1" and template["density"] == density,
                "docker-template-schema")
        equal(template["stop"], {"container_id": value["owner"]["container_id"], "exit_code": 0, "running": False,
            "child_reaped": app["resources"]["shutdown"]["child_reaped"],
            "output_closed": app["resources"]["shutdown"]["output_closed"],
            "copy_tasks_joined": app["resources"]["shutdown"]["copy_tasks_joined"], "invokes": 0}, "docker-template-stop")
        inventory(relative(root, value["template_path"]), template["inventory"])
        equal(template["inventory"], value["owner"]["data_inventory"], "docker-seed-final-inventory")
        results[density] = {"parent": value, "application": app}
    require(total == 88 and len(helper_ids) == 88, "docker-seed-total-work")
    return results


def windows(group, applications, calls, client):
    require(len(group["windows"]) == 3, "docker-window-count")
    previous = uint(group["started_nanos"])
    commands = [json.loads(row["line"]) for row in client["commands"]]
    acknowledgements = {row["ack"]["command_ordinal"]: row for row in client["acknowledgements"]
                        if row["ack"]["event"] not in ("first-response", "ready")}
    for window, stage, first in zip(group["windows"], ("ready", "served", "final"), (1, 3, 5)):
        fields(window, "stage started_nanos before sleep_begin_nanos sleep_end_nanos after finished_nanos")
        require(window["stage"] == stage, "docker-window-order")
        begin, end = uint(window["started_nanos"]), uint(window["finished_nanos"])
        sleep_begin, sleep_end = uint(window["sleep_begin_nanos"]), uint(window["sleep_end_nanos"])
        require(previous <= begin <= sleep_begin <= sleep_end <= end <= uint(group["finished_nanos"])
                and sleep_end-sleep_begin >= 250_000_000, "docker-window-clock")
        require(len(window["before"]) == len(window["after"]) == len(applications), "docker-window-owner-count")
        for app, before, after in zip(applications, window["before"], window["after"]):
            equal(before, app["parent"]["snapshots"][first-1], "docker-window-before-binding")
            equal(after, app["parent"]["snapshots"][first], "docker-window-after-binding")
            require(begin <= uint(before["signal_before_nanos"]) <= uint(before["observed_nanos"]) <= sleep_begin
                    and sleep_end <= uint(after["signal_before_nanos"]) <= uint(after["observed_nanos"]) <= end,
                    "docker-window-signal-placement")
        indices = [index for index, cmd in enumerate(commands) if cmd["group"] == group["group"]
                   and cmd["command"] == "inventory" and cmd["barrier"] == stage]
        require(len(indices) == 1, "docker-window-inventory-command")
        index = indices[0]
        require(uint(acknowledgements[index]["received_nanos"]) <= begin
                and end <= uint(client["commands"][index+1]["sent_nanos"]), "docker-window-client-barrier")
        previous = end


def attachment(parent, root, collection):
    value = fields(parent["attach"], "container_id begin_nanos end_nanos status stdin_bytes stdin_sha256 "
                   "stdout_path stdout_bytes stdout_sha256 stderr_path stderr_bytes stderr_sha256 eof frames "
                   "upgrade_response_bytes upgrade_response_sha256 connection_closed files_closed failure")
    require(value["container_id"] == parent["container_id"] and value["status"] in (101, 200)
            and value["eof"] is True and value["connection_closed"] is True and value["files_closed"] is True
            and value["failure"] is None and uint(value["begin_nanos"]) <= uint(parent["start"]["started_nanos"])
            <= uint(value["end_nanos"]), "docker-client-attach-owner")
    require(uint(value["upgrade_response_bytes"]) == 0 and value["upgrade_response_sha256"] == sha256(b""),
            "docker-client-attach-upgrade-body")
    sent = b"".join(row["line"].encode() for row in parent["commands"])
    require(uint(value["stdin_bytes"]) == len(sent) and value["stdin_sha256"] == sha256(sent), "docker-client-stdin-receipt")
    for stream, name, maximum in (("stdout", "stdout.ndjson", 1024**2), ("stderr", "stderr.bin", 256*1024)):
        require(value[stream+"_path"] == str(collection/parent["directory"]/name), "docker-client-attach-path")
        data = client_evidence._read(relative(root, parent["directory"])/name, maximum)
        require(uint(value[stream+"_bytes"]) == len(data) and value[stream+"_sha256"] == sha256(data),
                "docker-client-attach-output")
        if stream == "stdout":
            actual = [decode(line, 4096) for line in data.splitlines()]
            equal(actual, [row["ack"] for row in parent["acknowledgements"]], "docker-client-original-acks")
    integer(value["frames"], 1, 1000000)
    for filename, key, maximum, count in (("parent-commands.ndjson", "commands", 2*1024**2, 61),
                                          ("parent-acks.ndjson", "acknowledgements", 1024**2, 68)):
        data = client_evidence._read(relative(root, parent["directory"])/filename, maximum)
        lines = data.splitlines(keepends=True)
        require(len(lines) == count and all(line.endswith(b"\n") and len(line) <= 32768 for line in lines),
                "docker-parent-journal-bound")
        equal([decode(line, 32768) for line in lines], parent[key], "docker-parent-journal-binding")


def client_resources(parent, calls):
    ready, final = parent["ready_inspect"], parent["final"]["inspect"]
    require(ready["Id"] == final["Id"] == parent["container_id"]
            and ready["State"]["Running"] is True and ready["State"]["Pid"] > 0
            and final["State"]["Running"] is False and final["State"]["Pid"] == 0
            and type(final["State"]["ExitCode"]) is int and final["State"]["ExitCode"] == 0,
            "docker-client-container-exit")
    equal(ready["Config"], final["Config"], "docker-client-config-changed")
    equal(ready["HostConfig"], final["HostConfig"], "docker-client-host-config-changed")
    require(ready["Config"].get("Entrypoint") == ["/opt/lsf/optimization-client"], "docker-client-entrypoint")
    require(ready["State"]["StartedAt"] == final["State"]["StartedAt"] and ready["RestartCount"] == final["RestartCount"] == 0
            and ready["State"]["OOMKilled"] is False and final["State"]["OOMKilled"] is False,
            "docker-client-restarted-or-oom")
    expected = model.resources("client")
    for key, name in (("CpuPeriod", "cpu_period"), ("CpuQuota", "cpu_quota"), ("Memory", "memory"),
                      ("MemorySwap", "memory_swap"), ("PidsLimit", "pids_limit")):
        require(type(ready["HostConfig"][key]) is int and ready["HostConfig"][key] == expected[name],
                "docker-client-effective-control")
    stages = ["ready"]+[f"group-{group}-{stage}" for group in range(6) for stage in ("ready", "served", "final")]
    require(len(parent["observations"]) == len(stages), "docker-client-resource-count")
    previous_cpu = 0
    for observation, stage in zip(parent["observations"], stages):
        fields(observation, "stage call observed_nanos stats")
        require(observation["stage"] == stage, "docker-client-resource-order")
        row = calls.at(observation["call"], "GET", f"/containers/{parent['container_id']}/stats?stream=false&one-shot=true")
        equal(row["response"], observation["stats"], "docker-client-stats-binding")
        require(uint(row["receipt"]["end_nanos"]) <= uint(observation["observed_nanos"]), "docker-client-stats-clock")
        stats = observation["stats"]
        require(stats["id"] == parent["container_id"], "docker-client-stats-id")
        cpu = integer(stats["cpu_stats"]["cpu_usage"]["total_usage"], 0, 2**64-1)
        require(cpu >= previous_cpu, "docker-client-cpu-regression")
        previous_cpu = cpu
        require(stats["memory_stats"]["limit"] == expected["memory"] and stats["pids_stats"]["limit"] == expected["pids_limit"],
                "docker-client-stats-limits")


def negotiation(value, started, finished):
    fields(value, "response receipt response_bytes_base64")
    receipt = fields(value["receipt"], "method path begin_nanos end_nanos status request_bytes request_sha256 response_bytes "
                     "response_sha256 response_complete connection_closed failure")
    require(receipt["method"] == "GET" and receipt["path"] == "/version" and receipt["status"] == 200
            and receipt["response_complete"] is True and receipt["connection_closed"] is True and receipt["failure"] is None
            and started <= uint(receipt["begin_nanos"]) <= uint(receipt["end_nanos"]) <= finished
            and uint(receipt["request_bytes"]) == 0 and receipt["request_sha256"] == sha256(b""), "docker-negotiation-receipt")
    try:
        raw = base64.b64decode(text(value["response_bytes_base64"], 12*1024**2), validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("docker-negotiation-base64") from error
    require(len(raw) <= MAXIMUM_JSON and uint(receipt["response_bytes"]) == len(raw)
            and receipt["response_sha256"] == sha256(raw), "docker-negotiation-bytes")
    equal(decode(raw), value["response"], "docker-negotiation-response")
    versions = []
    for key in ("MinAPIVersion", "ApiVersion"):
        token = text(value["response"].get(key), 32)
        require(re.fullmatch(r"[0-9]+\.[0-9]+", token), "docker-negotiation-version")
        versions.append(tuple(map(int, token.split("."))))
    require(versions[0] <= (1, 54) <= versions[1], "docker-negotiation-version")


def environment(value, calls, groups, started, finished):
    fields(value, "engine_version engine_info engine_negotiation controller_platform observations controller volume")
    volume = value["volume"]
    require(volume["Labels"] == {LABEL: "issue111-controller-01"}
            and any(row["Type"] == "volume" and row.get("Name") == volume["Name"]
                    and row["Destination"] == "/bench" and row["RW"] is True
                    for row in value["controller"]["Mounts"]), "docker-owned-data-volume")
    equal(calls.find("GET", "/volumes/"+volume["Name"])["response"], volume, "docker-volume-binding")
    negotiation(value["engine_negotiation"], started, uint(calls.rows[0]["receipt"]["begin_nanos"]))
    equal(value["engine_negotiation"]["response"], value["engine_version"], "docker-engine-version-changed")
    equal(calls.find("GET", "/version")["response"], value["engine_version"], "docker-version-binding")
    equal(calls.find("GET", "/info")["response"], value["engine_info"], "docker-info-binding")
    info = value["engine_info"]
    require(info["OSType"] == "linux" and info["CgroupVersion"] == "2" and not info.get("Warnings")
            and all(info[key] is True for key in ("MemoryLimit", "SwapLimit", "CpuCfsPeriod", "CpuCfsQuota")),
            "docker-linux-controls")
    require(value["controller_platform"]["system"] == "Linux", "docker-controller-platform")
    require(len(value["observations"]) == 2, "docker-environment-count")
    observations = [(value["observations"][0], "before-seeds")]
    for group in groups:
        observations += [(group["environment_before"], f"pair-{group['pair']}-group-{group['group']}-before"),
                         (group["environment_after"], f"pair-{group['pair']}-group-{group['group']}-after")]
    observations.append((value["observations"][1], "after-clients"))
    previous = started
    for observation, stage in observations:
        fields(observation, "stage observed_nanos raw")
        require(observation["stage"] == stage and previous <= uint(observation["observed_nanos"]) <= finished,
                "docker-environment-clock")
        previous = uint(observation["observed_nanos"])
        raw = fields(observation["raw"], "stat meminfo loadavg pressure/cpu pressure/memory pressure/io")
        for item in raw.values():
            fields(item, "value unavailable_reason")
            if item["value"] is None:
                text(item["unavailable_reason"], 128)
            else:
                text(item["value"], 65536, empty=True)
                require(item["unavailable_reason"] is None, "docker-environment-availability")


def progress(root, suite, applications):
    data = client_evidence._read(root/"progress.ndjson", 32*1024**2)
    by_id = {app["parent"]["container_id"]: app for app in applications}
    stages = {cid: 0 for cid in by_id}
    snapshots = {cid: 0 for cid in by_id}
    expected_helpers = {}
    for seed in suite["setup"]:
        for row in seed["calls"]:
            expected_helpers[(seed["density"], row["name"])] = row
    helper_states, attempted = {}, set()
    previous = uint(suite["started_nanos"])
    lines = data.splitlines(keepends=True)
    require(1 <= len(lines) <= 20000, "docker-progress-population")
    for index, line in enumerate(lines):
        require(line.endswith(b"\n") and len(line) <= 2*1024**2, "docker-progress-line-bound")
        row = fields(decode(line, 2*1024**2), "ordinal observed_nanos kind value")
        require(integer(row["ordinal"]) == index and previous <= uint(row["observed_nanos"])
                <= uint(suite["finished_nanos"]), "docker-progress-clock")
        previous = uint(row["observed_nanos"])
        kind, value = row["kind"], row["value"]
        if kind in ("seed-command-attempt", "seed-command-completed"):
            key = (value["density"], value["name"])
            require(key in expected_helpers, "docker-progress-extra-helper")
            expected = expected_helpers[key]
            if kind.endswith("attempt"):
                require(key not in attempted, "docker-progress-duplicate-helper")
                arguments = [str(original_root(suite["build_path"])/"binaries/latent"), "--config",
                    str(original_root(suite["collection_path"])/f"seeds/{key[0]}/cli.json"), "--output", "json", *expected["arguments"]]
                equal(value, {"density": key[0], "name": key[1], "argv": arguments}, "docker-progress-helper-command")
                attempted.add(key)
                helper_states[key] = False
            else:
                require(key in helper_states and helper_states[key] is False, "docker-progress-helper-completion")
                equal(value, {"density": key[0], **expected}, "docker-progress-helper-result")
                helper_states[key] = True
            continue
        cid = value.get("container_id") if isinstance(value, dict) else None
        require(cid in by_id, "docker-progress-unowned-app")
        app, stage = by_id[cid], stages[cid]
        parent = app["parent"]
        if kind == "app-created":
            require(stage == 0, "docker-progress-duplicate-create")
            equal(value, {key: parent[key] for key in ("role", "arm", "density", "container_id", "template_copy")},
                  "docker-progress-created-binding")
            stages[cid] = 1
        elif kind == "app-started":
            require(stage == 1, "docker-progress-start-order")
            equal(value, {"container_id": cid, "start": parent["start"]}, "docker-progress-start-binding")
            stages[cid] = 2
        elif kind == "app-ready":
            require(stage == 2, "docker-progress-ready-order")
            equal(value, {"container_id": cid, "ready": app["lifecycle"]["ready_event"],
                  "event_observations": parent["event_observations"][:2],
                  "ready_inspect_call": app["lifecycle"]["ready_inspect_call"]}, "docker-progress-ready-binding")
            stages[cid] = 3
        elif kind == "app-snapshot-attempt":
            index = snapshots[cid]
            require(stage == 3 and index < len(parent["snapshots"]), "docker-progress-snapshot-order")
            sample = parent["snapshots"][index]
            equal(value, {"container_id": cid, "index": index+1, "signal_before_nanos": sample["signal_before_nanos"]},
                  "docker-progress-snapshot-attempt")
            stages[cid] = 4
        elif kind == "app-snapshot-observed":
            require(stage == 4, "docker-progress-snapshot-without-attempt")
            equal(value, {"container_id": cid, **parent["snapshots"][snapshots[cid]]}, "docker-progress-snapshot-observed")
            snapshots[cid] += 1
            stages[cid] = 3
        elif kind == "app-finished":
            require(stage == 3 and snapshots[cid] == len(parent["snapshots"]), "docker-progress-finish-order")
            equal(value, {key: item for key, item in parent.items() if key != "data_cleanup"}, "docker-progress-finished-binding")
            stages[cid] = 5
        else:
            raise ValueError("docker-progress-kind")
    require(all(stage == 5 for stage in stages.values()) and set(helper_states) == set(expected_helpers)
            and all(helper_states.values()), "docker-progress-incomplete")


def validate(root: Path, build_root: Path) -> dict:
    """Qualify complete retained work; never repair, execute, or delete evidence."""
    root, build_root = Path(root), Path(build_root)
    require(root.is_dir() and build_root.is_dir() and not root.is_symlink() and not build_root.is_symlink(),
            "docker-evidence-root")
    fixtures.inventory(root)
    suite_path = root/"suite.json"
    suite = fields(read_json(suite_path, 32*1024**2), "schema profile run_id plan source build_source build_receipt "
        "collection_path build_path collector_inputs collector_build_inputs images volume started_nanos finished_nanos environment setup groups clients "
        "failed_attachments failure cleanup")
    require(suite["schema"] == model.PREFIX+"suite.v1" and suite["failure"] is None and suite["failed_attachments"] == []
            and re.fullmatch(r"[a-z0-9-]{1,24}", text(suite["run_id"], 24)), "docker-incomplete-suite")
    equal(suite["plan"], model.plan(suite["profile"]), "docker-exact-plan")
    equal(read_json(root/"plan.json"), suite["plan"], "docker-plan-file")
    started, finished = uint(suite["started_nanos"]), uint(suite["finished_nanos"])
    require(started <= finished and finished-started <= 7200*10**9, "docker-collection-deadline")
    require(suite["build_receipt"]["path"] == "docker-builds.json", "docker-build-reference")
    built = build.validate_receipt(read_json(verify_artifact(build_root, suite["build_receipt"], 16*1024**2)), build_root)
    source_closure(suite, root, built)
    publications = fixture_set(built, build_root)
    rows = journal(root, started, finished)
    calls = Calls(rows)
    image_set(suite, built, build_root, calls)
    cleanup = fields(suite["cleanup"], "schema containers network_id network_removed errors remaining_containers journal_closed pending_names")
    require(cleanup["schema"] == model.PREFIX+"cleanup.v1" and cleanup["network_removed"] is True
            and cleanup["journal_closed"] is True and cleanup["errors"] == cleanup["remaining_containers"] == cleanup["pending_names"] == [],
            "docker-suite-cleanup")
    equal(read_json(root/"cleanup.json"), cleanup, "docker-cleanup-sidecar")
    owners = owner_rows(suite)
    configs = configurations(suite, owners)
    signals = api_protocol(rows, suite, configs)
    require(len(cleanup["containers"]) == len(configs), "docker-cleanup-container-population")
    seed_results = seeds(suite, root, built, calls, publications)
    derived_groups, derived_clients = [], []
    last_finished = started
    for pair, parent in enumerate(suite["clients"]):
        fields(parent, "pair container_id plan directory start ready_inspect final attach commands acknowledgements observations")
        equal(parent, read_json(root/f"clients/{pair}/parent.json", 16*1024**2), "docker-client-parent-sidecar")
        equal(parent["plan"], {"schema": model.CLIENT_PREFIX+"plan.v1", "run_id": suite["run_id"], "profile": suite["profile"],
                              "pair": pair, "token_file": "/fixtures/token"}, "docker-client-exact-plan")
        owner_map = {}
        pair_groups = suite["groups"][pair*6:pair*6+6]
        for group in pair_groups:
            fields(group, "pair group arm density started_nanos finished_nanos targets owners windows environment_before environment_after")
            equal(group, read_json(root/f"group-{pair}-{group['group']}.json", 16*1024**2), "docker-group-sidecar")
            begin, end = uint(group["started_nanos"]), uint(group["finished_nanos"])
            require(last_finished <= begin <= end <= finished and end-begin <= 600*10**9, "docker-group-clock")
            last_finished = end
            applications = []
            for owner in group["owners"]:
                app = app_resources(root, owner, calls, cleanup, 6, group["density"] if group["arm"] == "lsf" else 1)
                require([item["call"] for item in owner["snapshots"]] == signals[owner["container_id"]], "docker-signal-population")
                require(begin <= uint(owner["start"]["started_nanos"])
                        and uint(app["lifecycle"]["absent_nanos"]) <= end, "docker-owner-outside-group")
                if group["arm"] == "lsf":
                    template = seed_results[group["density"]]["parent"]["template"]
                    equal(owner["template_copy"], {"schema": "latent.optimization.docker-template-copy.v1", "density": group["density"],
                          "source_stop": template["stop"], "inventory": template["inventory"]}, "docker-app-template-copy")
                    inventory(root/"data"/owner["role"], owner["data_inventory"], retained=False)
                    data_cleanup = fields(owner.get("data_cleanup"), "path inventory_sha256 container_absence_call removed")
                    equal(data_cleanup, {"path": "data/"+owner["role"],
                        "inventory_sha256": sha256(canonical(owner["data_inventory"])),
                        "container_absence_call": app["lifecycle"]["absence_call"], "removed": True}, "docker-stopped-data-cleanup")
                    require(not relative(root, data_cleanup["path"]).exists(), "docker-measured-data-still-retained")
                else:
                    require(owner["template_copy"] is None and owner["data_inventory"] is None
                            and owner.get("data_cleanup") is None, "docker-native-data-owner")
                applications.append(app)
                owner_map[owner["owner_ref"]] = {"app_process_id": owner["app_process_id"], "endpoint": owner["endpoint"],
                    "arm": group["arm"], "density": group["density"], "group": group["group"], "container_id": owner["container_id"]}
                if group["arm"] == "lsf":
                    owner_map[owner["owner_ref"]]["release_digests"] = {
                        service: publications[service]["release"] for service in model.SERVICES[:group["density"]]}
            targets = [{"service": service, "endpoint": applications[0 if group["arm"] == "lsf" else index]["parent"]["endpoint"],
                "owner_ref": applications[0 if group["arm"] == "lsf" else index]["parent"]["owner_ref"],
                "app_process_id": applications[0 if group["arm"] == "lsf" else index]["parent"]["app_process_id"]}
                for index, service in enumerate(model.SERVICES[:group["density"]])]
            equal(group["targets"], targets, "docker-group-target-owners")
            windows(group, applications, calls, parent)
            derived_groups.append({**group, "owners": applications})
        derived = client_evidence.validate(relative(root, parent["directory"]), parent["plan"], parent["commands"],
                                           parent["acknowledgements"], owner_map)
        require(derived["process_id"] == 1, "docker-client-not-pid1")
        for group in pair_groups:
            if group["arm"] != "lsf":
                continue
            expected = suite["plan"]["groups"][pair][group["group"]]
            for stage, count, grants in (("ready", 0, 0), ("served", group["density"], group["density"]),
                ("final", group["density"], sum(phase["offers"] for phase in expected["phases"]))):
                node_inventory(derived["inventories"][f"{group['group']}/{stage}"]["inventory"],
                               expected_entries=count, expected_grants=grants)
        attachment(parent, root, original_root(suite["collection_path"]))
        client_resources(parent, calls)
        life = lifecycle(parent, calls, cleanup)
        derived_clients.append({"parent": parent, "evidence": derived, "lifecycle": life})
    environment(suite["environment"], calls, suite["groups"], started, finished)
    progress(root, suite, [row["application"] for row in seed_results.values()]
             + [app for group in derived_groups for app in group["owners"]])
    total = sum(uint(client["evidence"]["offers"]) for client in derived_clients)
    require(total == uint(suite["plan"]["logical_offers"]), "docker-total-offers")
    return {"schema": model.PREFIX+"derived.v1", "status": "passed", "profile": suite["profile"], "plan": suite["plan"],
            "source": suite["source"], "build_source": suite["build_source"], "suite_sha256": sha256(suite_path.read_bytes()),
            "groups": derived_groups, "clients": derived_clients, "seeds": list(seed_results.values()),
            "environment": suite["environment"], "images": suite["images"],
            "counts": {"offers": str(total), "successful": str(total), "seed_management_rpcs": "88", "seed_invokes": "0",
                       "measured_application_owners": str(len(owners)-3), "client_owners": str(len(derived_clients)),
                       "all_containers_removed": str(len(configs)), "api_calls": str(len(rows))},
            "started_nanos": suite["started_nanos"], "finished_nanos": suite["finished_nanos"], "cleanup": cleanup}
