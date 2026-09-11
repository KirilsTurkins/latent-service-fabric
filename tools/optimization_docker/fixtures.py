"""Actual density publications and stopped, byte-verified seed directories."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import stat

from tools.artifact_identity_runner.files import fingerprint, reference, retain
from tools.optimization_runner import fixtures as canonical
from .model import CONTRACT, DENSITIES, MAX_FILE_BYTES, MAX_FILES, MAX_TOTAL_BYTES, SERVICES, TENANT, TOKEN

MAXIMUM_BYTES = MAX_TOTAL_BYTES
MAXIMUM_FILE_BYTES = MAX_FILE_BYTES
MAXIMUM_FILES = MAX_FILES


def node_configuration() -> dict:
    value = canonical.node_configuration(Path("/data"))
    value["dataDirectory"] = "/data"
    value["bind"] = "127.0.0.1:7071"
    value["cache"]["entries"] = 32
    value["catalogs"] = {"releaseEntries": 64, "deployments": 64}
    return value


def materialize(component: Path, directory: Path, *, root: Path, repository: Path) -> dict:
    """Keep the old five-fixture generator unchanged; reuse its canonical tables."""
    checksum, size = fingerprint(component, 16 * 1024**2)
    source = component.read_bytes()
    if size < 8 or source[:8] != b"\0asm\x0d\0\x01\0":
        raise ValueError("docker-fixture-not-component")
    if directory.exists() or directory.is_symlink() or not directory.is_relative_to(root):
        raise ValueError("docker-fixture-directory-not-fresh")
    capsule_template = json.loads((repository / "examples/echo-contract/capsule.json").read_bytes())
    deployment_template = json.loads((repository / "examples/echo-contract/deployment.json").read_bytes())
    directory.mkdir(parents=True)
    contracts = directory / "contracts.json"
    canonical.write(contracts, canonical.contracts())
    canonical.write(directory / "node.json", node_configuration())
    token = directory / "token"
    with token.open("xb") as stream:
        stream.write((TOKEN + "\n").encode())
    token.chmod(0o600)
    rows = []
    for index, service in enumerate(SERVICES):
        name = b"optimization-working-set-v1"
        section = canonical.leb(len(name)) + name + bytes([index])
        wasm = source if index == 0 else source + b"\0" + canonical.leb(len(section)) + section
        path = directory / f"component-{index}.wasm"
        with path.open("xb") as stream:
            stream.write(wasm)
        capsule = copy.deepcopy(capsule_template)
        capsule["metadata"] = {"name": service, "tenant": TENANT}
        capsule["component"].update(digest=fingerprint(path)[0], world="optimization:benchmark/service@0.1.0")
        capsule["exports"], capsule["imports"] = [CONTRACT], []
        capsule["execution"].update(threading="single-threaded", snapshotEligible=False, fusionEligible=False)
        capsule["execution"]["limits"].update(cpuFuel=10_000_000_000, memoryBytes=67_108_864)
        capsule_path = directory / f"capsule-{index}.json"
        canonical.write(capsule_path, capsule)
        deployment = copy.deepcopy(deployment_template)
        deployment["metadata"] = {"name": f"optimization-{index}", "tenant": TENANT}
        deployment["spec"].update(service=service, release=capsule["component"]["digest"], grants=[])
        deployment["spec"]["resources"].update(cpuFuel=10_000_000_000, memoryBytes=67_108_864)
        deployment_path = directory / f"deployment-{index}.json"
        canonical.write(deployment_path, deployment)
        rows.append({"index": index, "service": service, "component": reference(path, root),
                     "capsule": reference(capsule_path, root), "contracts": reference(contracts, root),
                     "deployment": reference(deployment_path, root)})
    if fingerprint(component, 16 * 1024**2) != (checksum, size):
        raise ValueError("docker-fixture-source-changed")
    value = {"schema": "latent.optimization.docker-fixtures.v1", "base_component": reference(component, root),
             "node_config": reference(directory / "node.json", root), "token": reference(token, root),
             "publications": rows}
    canonical.write(directory / "fixtures.json", value)
    return value


def inventory(directory: Path) -> dict:
    """Bound metadata traversal before copying; record empty directories and modes."""
    rows, total, entries = [], 0, 0
    pending = [(directory, 0)]
    while pending:
        current, depth = pending.pop()
        info = current.lstat()
        if (not stat.S_ISDIR(info.st_mode) or current.is_symlink()
                or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError("docker-template-directory-type")
        rows.append({"path": current.relative_to(directory).as_posix(), "kind": "directory",
                     "mode": format(stat.S_IMODE(info.st_mode), "04o")})
        with os.scandir(current) as children:
            for child in children:
                entries += 1
                if entries > MAXIMUM_FILES:
                    raise ValueError("docker-template-entry-bound")
                path, value = Path(child.path), child.stat(follow_symlinks=False)
                if stat.S_ISLNK(value.st_mode) or getattr(value, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    raise ValueError("docker-template-entry-type")
                if stat.S_ISDIR(value.st_mode):
                    if depth >= 8:
                        raise ValueError("docker-template-depth-bound")
                    pending.append((path, depth + 1))
                elif stat.S_ISREG(value.st_mode):
                    digest, size = fingerprint(path, MAXIMUM_FILE_BYTES)
                    total += size
                    if total > MAXIMUM_BYTES:
                        raise ValueError("docker-template-total-bound")
                    rows.append({"path": path.relative_to(directory).as_posix(), "kind": "file",
                                 "sha256": digest, "bytes": str(size),
                                 "mode": format(stat.S_IMODE(value.st_mode), "04o")})
                else:
                    raise ValueError("docker-template-entry-type")
    return {"entries": sorted(rows, key=lambda row: row["path"]), "bytes": str(total)}


def seal_template(data: Path, *, density: int, stop_receipt: dict) -> dict:
    expected = {"exit_code": 0, "running": False, "child_reaped": True,
                "output_closed": True, "copy_tasks_joined": True, "invokes": 0}
    if (type(density) is not int or density not in DENSITIES or not isinstance(stop_receipt, dict)
            or set(stop_receipt) != set(expected) | {"container_id"}
            or not isinstance(stop_receipt["container_id"], str)
            or re.fullmatch(r"[0-9a-f]{64}", stop_receipt["container_id"]) is None
            or any(type(stop_receipt[key]) is not type(value) or stop_receipt[key] != value
                   for key, value in expected.items())):
        raise ValueError("docker-template-requires-clean-zero-invoke-stop")
    return {"schema": "latent.optimization.docker-template.v1", "density": density,
            "stop": dict(stop_receipt), "inventory": inventory(data)}


def copy_template(template: Path, destination: Path, receipt: dict) -> dict:
    """Copy a stopped real repository, never synthesize a persisted catalog."""
    if any(path.is_symlink() for path in (template, *template.parents, destination, *destination.parents)):
        raise ValueError("docker-template-copy-symlink")
    template, destination = template.resolve(), destination.absolute()
    if (destination.exists() or destination.is_symlink() or destination.is_relative_to(template)
            or template.is_relative_to(destination)):
        raise ValueError("docker-template-copy-not-fresh-or-overlapping")
    if (not isinstance(receipt, dict) or set(receipt) != {"schema", "density", "stop", "inventory"}
            or seal_template(template, density=receipt["density"], stop_receipt=receipt["stop"]) != receipt):
        raise ValueError("docker-template-receipt-mismatch")
    rows = receipt["inventory"]["entries"]
    destination.mkdir(parents=True)
    for row in rows:
        path = destination / row["path"]
        if row["kind"] == "directory":
            path.mkdir(exist_ok=True)
        else:
            retain(template / row["path"], path, destination)
            path.chmod(int(row["mode"], 8))
    for row in reversed(rows):
        if row["kind"] == "directory":
            (destination / row["path"]).chmod(int(row["mode"], 8))
    if inventory(template) != receipt["inventory"] or inventory(destination) != receipt["inventory"]:
        raise ValueError("docker-template-copy-mismatch")
    return {"schema": "latent.optimization.docker-template-copy.v1", "density": receipt["density"],
            "source_stop": receipt["stop"], "inventory": receipt["inventory"]}
