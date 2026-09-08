"""Materialize canonical benchmark publications with actual component identities."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from run_phase1_conformance import ROOT, digest
from .plans import CONTRACT, SERVICES, TENANT, TOKEN


def write(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        output.write("\n")


def signed(value: dict) -> dict:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return {**value, "digest": "sha256:" + hashlib.sha256(encoded).hexdigest()}


def contracts() -> dict:
    def field(name: str, value_type: object) -> dict:
        return {"name": name, "value_type": value_type, "documentation": None}

    def function(name: str, parameters: list[dict], result: object) -> dict:
        return {"id": name, "name": name, "asynchronous": False, "parameters": parameters,
                "results": [field("result", result)], "documentation": None, "attributes": {}}

    functions = [function("echo", [field("message", "String")], "String"),
                 function("compute", [field("seed", "U32"), field("rounds", "U32")], "U32"),
                 function("transform", [field("value", {"Record": "transform-value"})],
                          {"Record": "transform-value"})]
    interface = signed({"id": CONTRACT, "functions": functions, "documentation": None})
    contract = signed({"id": CONTRACT, "package_name": "optimization:benchmark", "semantic_version": "0.1.0",
                       "interfaces": [interface], "dependencies": []})
    return {"format_version": 1, "contracts": [contract]}


def leb(value: int) -> bytes:
    encoded = bytearray()
    while value >= 128:
        encoded.append((value & 127) | 128)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def materialize(component: Path, directory: Path) -> list[dict]:
    directory.mkdir()
    source = component.read_bytes()
    if not 0 < len(source) <= 16 * 1024 * 1024:
        raise ValueError("benchmark component outside publication bound")
    write(directory / "contracts.json", contracts())
    publications = []
    for index, service in enumerate(SERVICES):
        # Five real distinct component identities, identical executable logic.
        # A valid top-level custom section gives the working-set profile actual
        # prepared-cache misses without pretending one cached component is five.
        name = b"optimization-working-set-v1"
        section = leb(len(name)) + name + bytes([index])
        wasm = source if index == 0 else source + b"\x00" + leb(len(section)) + section
        component_path = directory / f"component-{index}.wasm"
        component_path.write_bytes(wasm)
        manifest = json.loads((ROOT / "examples/echo-contract/capsule.json").read_text())
        manifest["metadata"] = {"name": service, "tenant": TENANT}
        manifest["component"].update(digest=digest(component_path)[0], world="optimization:benchmark/service@0.1.0")
        manifest["exports"] = [CONTRACT]
        manifest["imports"] = []
        manifest["execution"].update(threading="single-threaded", snapshotEligible=False, fusionEligible=False)
        manifest["execution"]["limits"].update(cpuFuel=10_000_000_000, memoryBytes=67_108_864)
        manifest_path = directory / f"capsule-{index}.json"
        write(manifest_path, manifest)
        deployment = json.loads((ROOT / "examples/echo-contract/deployment.json").read_text())
        deployment["metadata"] = {"name": f"optimization-{index}", "tenant": TENANT}
        deployment["spec"].update(service=service, release=manifest["component"]["digest"], grants=[])
        deployment["spec"]["resources"].update(cpuFuel=10_000_000_000, memoryBytes=67_108_864)
        deployment_path = directory / f"deployment-{index}.json"
        write(deployment_path, deployment)
        publications.append({"component": component_path, "manifest": manifest_path,
                             "contracts": directory / "contracts.json", "deployment": deployment_path})
    return publications


def node_config(directory: Path, data_directory: Path) -> Path:
    path = directory / "node.json"
    write(path, {
        "formatVersion": 1, "dataDirectory": str(data_directory), "nodeId": "optimization-node", "bind": "127.0.0.1:0",
        "workers": {"runtime": 2, "control": 2},
        "cells": [{"class": "standard", "capacity": 4, "queueCapacity": 64, "maximumMemoryBytes": 67_108_864}],
        "execution": {"maximumCpuFuel": 10_000_000_000, "maximumWallTimeMillis": 5000, "maximumLogBytes": 16_384},
        "limits": {"maximumPayloadBytes": 1_048_576, "maximumConnections": 32},
        "cache": {"entries": 4, "preparations": 1},
        "catalogs": {"releaseEntries": 16, "deployments": 16},
        "retention": {"terminalEntries": 1024, "terminalTtlMillis": 30_000, "bytes": 512 * 1024 * 1024},
        "shutdownGraceMillis": 1000,
        "credentials": [{"token": TOKEN, "subject": "optimization-reference", "tenant": TENANT, "role": "operator"}],
    })
    return path


def cli_config(directory: Path, endpoint: str, name: str) -> Path:
    path = directory / name
    write(path, {"formatVersion": 1, "defaultProfile": "benchmark", "profiles": [{
        "name": "benchmark", "endpoint": endpoint, "tenant": TENANT, "token": TOKEN,
        "connectTimeoutMillis": 5000, "rpcTimeoutMillis": 5000,
    }]})
    return path
