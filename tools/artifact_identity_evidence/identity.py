"""Retained source, build, fixture and helper-process associations."""
from __future__ import annotations

from .common import ARMS, GIT_HASH, canonical, digest, fields, integer, require, text, uint
from tools.optimization_evidence.resources import cgroup, clean, process

CONFIGURATION = {
    "artifacts": {"max_index_entries": 4, "max_index_bytes": 4 * 1024**2, "max_page_size": 4,
                  "max_page_bytes": 1024**2, "max_descriptor_bytes": 64 * 1024,
                  "max_metadata_bytes": 1024**2, "max_component_bytes": 64 * 1024**2,
                  "max_recovery_directories": 4},
    "deployments": {"max_deployments": 4, "max_state_bytes": 4 * 1024**2, "max_route_entries": 64,
                    "max_identifier_bytes": 512, "max_routing_key_bytes": 512, "max_page_size": 4,
                    "max_page_bytes": 1024**2},
}


def source(value):
    fields(value, "commit tree clean")
    require(value["clean"] is True and all(isinstance(value[key], str) and GIT_HASH.fullmatch(value[key])
                                          for key in ("commit", "tree")), "unclean-source-identity")


def helper(value, checksum, log, artifacts):
    owner = process(value, "artifact-identity-helper", checksum)
    require(clean(value), "helper-not-cleanly-reaped")
    artifacts.path(log)
    receipt = artifacts.rows.get(log["path"] + ".process.json")
    require(receipt is not None and artifacts.json(receipt) == value, "unbound-helper-receipt")
    return owner


def environment(value, tools):
    fields(value, "host cgroup runner_source")
    source(value["runner_source"])
    cgroup(value["cgroup"])
    host = fields(value["host"], "os arch kernel cpu_model logical_cpus memory_total_bytes virtualization allocator cpu_policy load_before")
    require(host["os"] == "Linux" and uint(host["logical_cpus"]) > 0
            and uint(host["memory_total_bytes"]) > 0, "missing-linux-host-capacity")
    for key in ("arch", "kernel", "cpu_model"):
        text(host[key])
    for key in ("virtualization", "allocator", "cpu_policy"):
        require(isinstance(host[key], dict), "missing-host-controls")
    require(isinstance(host["load_before"], list) and len(host["load_before"]) == 3
            and all(type(x) in (int, float) and x >= 0 for x in host["load_before"]), "invalid-host-load")
    fields(tools, "heaptrack heaptrack_print zstd rustc cargo git")
    for tool in tools.values():
        fields(tool, "path sha256 version")
        require(text(tool["path"]).startswith("/"), "invalid-tool-path")
        digest(tool["sha256"])
        text(tool["version"], 65536)
    require("1.4.0" in tools["heaptrack"]["version"], "unsupported-heaptrack-version")


def build_rows(suite, artifacts):
    from tools.artifact_identity_runner.model import BUILD_RECIPE, PROBE, PROBE_DIRECTORY
    fields(suite["builds"], "control candidate")
    fields(suite["requested_refs"], "control candidate")
    result = {}
    for arm in ARMS:
        item = fields(suite["builds"][arm], "source_before source_after binary inputs probe_sources command log process source_path target_path")
        source(item["source_before"])
        source(item["source_after"])
        require(item["source_before"] == item["source_after"]
                and item["source_before"]["commit"] == suite["requested_refs"][arm], "source-changed-or-crossed")
        require(item["command"] == ["/bin/bash", "-eu", "-o", "pipefail", "-c", BUILD_RECIPE], "changed-build-recipe")
        for key in ("source_path", "target_path"):
            require(text(item[key]).startswith("/"), "invalid-build-path")
        require(item["source_path"] != item["target_path"], "shared-source-target")
        artifacts.path(item["binary"])
        require(uint(item["binary"]["bytes"]) > 0, "empty-probe-binary")
        digest(item["process"]["executable_sha256"])
        helper(item["process"], item["process"]["executable_sha256"], item["log"], artifacts)
        for key, maximum in (("inputs", 128), ("probe_sources", 64)):
            mapping = item[key]
            require(isinstance(mapping, dict) and 1 <= len(mapping) <= maximum, "build-input-count")
            for name, ref in mapping.items():
                require(ref["path"] == f"builds/{arm}/source/{name}", "unbound-source-path")
                artifacts.path(ref)
        require({"Cargo.lock", "Cargo.toml", ".cargo/config.toml", "rust-toolchain.toml",
                 "tools/phase0_build_environment.sh", "tools/optimization-bench/Cargo.toml"}
                <= item["inputs"].keys(), "missing-build-input")
        require(PROBE in item["probe_sources"] and all(name == PROBE or name.startswith(PROBE_DIRECTORY + "/")
                for name in item["probe_sources"]), "changed-probe-source-set")
        prefix = f"builds/{arm}/source/"
        require(item["probe_sources"] == {name[len(prefix):]: ref for name, ref in artifacts.rows.items()
                if name == prefix + PROBE or name.startswith(prefix + PROBE_DIRECTORY + "/")},
                "omitted-probe-source-artifact")
        result[arm] = {name: (ref["sha256"], ref["bytes"]) for name, ref in item["probe_sources"].items()}
    require(result["control"] == result["candidate"], "mismatched-measurement-harness")
    control, candidate = (suite["builds"][arm] for arm in ARMS)
    require(all(control[key] == candidate[key] for key in ("source_path", "target_path", "command")), "unmatched-build-path-or-recipe")
    for name in ("tools/phase0_build_environment.sh", "tools/optimization-bench/Cargo.toml",
                 "rust-toolchain.toml", ".cargo/config.toml"):
        require(control["inputs"][name]["sha256"] == candidate["inputs"][name]["sha256"],
                "mismatched-build-control")
    if suite["profile"] == "full":
        require(suite["requested_refs"]["control"] != suite["requested_refs"]["candidate"], "full-needs-distinct-sources")


def fixtures(suite, artifacts):
    require(set(suite["fixtures"]) == set(suite["plan"]["sizes"]), "missing-fixture-population")
    source_component = artifacts.rows.get("inputs/component.wasm")
    require(source_component is not None and 0 < uint(source_component["bytes"]) <= 16 * 1024**2,
            "missing-source-component")
    for size, item in suite["fixtures"].items():
        fields(item, "root manifest files generation_process command generation_log")
        require(item["root"] == f"fixtures/{size}", "crossed-fixture-root")
        require(isinstance(item["files"], dict) and 8 <= len(item["files"]) <= 64, "fixture-file-count")
        for name, ref in item["files"].items():
            require(ref["path"] == item["root"] + "/" + name, "crossed-fixture-file")
            artifacts.path(ref)
        require(item["files"] == {name[len(item["root"]) + 1:]: ref for name, ref in artifacts.rows.items()
                                 if name.startswith(item["root"] + "/")}, "omitted-fixture-file")
        manifest = fields(item["manifest"], "schema size component_digest component_bytes source_component_digest source_component_bytes capsule_sha256 contracts_sha256 deployment_sha256 tenant service deployment_id contract function revision_id route_generation configuration")
        require(manifest == artifacts.json(item["files"]["fixture.json"], 16384)
                and manifest["schema"] == "latent.artifact-identity.fixture.v1" and manifest["size"] == size,
                "unbound-fixture-manifest")
        expected_bytes = uint(source_component["bytes"]) if size == "small" else {"16m": 16, "64m": 64}[size] * 1024**2
        component = item["files"]["component.wasm"]
        require(uint(component["bytes"]) == expected_bytes and manifest["component_bytes"] == component["bytes"]
                and manifest["component_digest"] == component["sha256"]
                and manifest["source_component_digest"] == source_component["sha256"]
                and manifest["source_component_bytes"] == source_component["bytes"], "fixture-component-identity")
        for name in ("capsule", "contracts", "deployment"):
            require(manifest[name + "_sha256"] == item["files"][name + ".json"]["sha256"], "fixture-metadata-identity")
        for name in ("tenant", "service", "deployment_id", "contract", "function", "revision_id"):
            text(manifest[name], 512)
        require(manifest["route_generation"] == "1", "fixture-route-generation")
        require(manifest["configuration"] == CONFIGURATION, "changed-fixture-configuration")
        command = item["command"]
        binary = suite["builds"]["control"]["binary"]
        require(isinstance(command, list) and len(command) == 12 and isinstance(command[0], str)
                and command[0].endswith("/" + binary["path"]), "invalid-fixture-command")
        root = command[0].removesuffix(binary["path"])
        require(command == [root + binary["path"], "fixture", "--component", root + "inputs/component.wasm",
                            "--capsule", root + "inputs/capsule.json", "--contracts", root + "inputs/contracts.json",
                            "--output", root + item["root"], "--size", size], "changed-fixture-command")
        for name in ("capsule", "contracts"):
            ref = artifacts.rows.get("inputs/" + name + ".json")
            require(ref is not None and 0 < uint(ref["bytes"]) <= 1024**2, "missing-fixture-generation-input")
        helper(item["generation_process"], suite["builds"]["control"]["binary"]["sha256"], item["generation_log"], artifacts)
    return CONFIGURATION
