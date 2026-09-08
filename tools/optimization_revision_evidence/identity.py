"""Bind each server to its actual build and the shared immutable harness inputs."""
from __future__ import annotations

from tools.optimization_evidence.common import GIT_HASH, digest, fields, require, text, uint
from tools.optimization_evidence.resources import clean, process, cgroup
from tools.optimization_revision_runner.model import HARNESS_COMMAND, SERVER_RECIPE, SOURCE_CONTROLS


def source(value):
    fields(value, "commit tree clean cargo_lock_sha256")
    for name in ("commit", "tree"):
        require(isinstance(value[name], str) and GIT_HASH.fullmatch(value[name]), "revision-source-identity")
    require(value["clean"] is True, "unclean-revision-source")
    digest(value["cargo_lock_sha256"])


def environment(value):
    fields(value, "os arch kernel cpu_model logical_cpus memory_total_bytes virtualization allocator cpu_policy load_before")
    for name in ("os", "arch", "kernel", "cpu_model"):
        text(value[name])
    require(value["os"] == "Linux", "revision-requires-observed-linux")
    require(uint(value["logical_cpus"]) > 0 and uint(value["memory_total_bytes"]) > 0, "missing-host-capacity")
    for name in ("virtualization", "allocator", "cpu_policy"):
        require(isinstance(value[name], dict), "missing-host-settings")
    require(isinstance(value["load_before"], list) and len(value["load_before"]) == 3
            and all(type(item) in (float, int) and item >= 0 for item in value["load_before"]), "invalid-host-load")
    return {key: item for key, item in value.items() if key != "load_before"}


def validate(value, refs, artifacts):
    fields(value, "runner_source runner_source_after build builds components publications harness_sources environment cgroup")
    source(value["runner_source"])
    require(value["runner_source"] == value["runner_source_after"]
            and value["runner_source"]["commit"] == refs["harness"], "revision-harness-source-changed")
    environment(value["environment"])
    cgroup(value["cgroup"])
    settings = fields(value["build"], "profile rustc cargo wasmtime target overrides")
    require(settings["profile"] == "release" and settings["wasmtime"] == "47.0.3", "revision-build-controls")
    for name in ("rustc", "cargo", "target"):
        text(settings[name])
    required_options = {"recipe": "tools/phase0_build_environment.sh:phase0_release_cargo",
                        "opt_level": "3", "debug": "1", "codegen_units": "16", "lto": "false",
                        "debug_assertions": "false", "overflow_checks": "false", "incremental": "false",
                        "panic": "unwind", "strip": "none", "path_remap": "source-target-cargo-home-v1",
                        "linker_build_id": "sha1", "promoted_locals": "source-filename",
                        "collector_surface": "separate-standalone-server-and-load-client"}
    require(set(settings["overrides"]) == set(required_options) | {"recipe_sha256"}
            and all(settings["overrides"][name] == item for name, item in required_options.items()),
            "changed-pinned-release-settings")
    builds = fields(value["builds"], "control candidate harness")
    paths, controls = set(), []
    for label, build in builds.items():
        fields(build, "source source_after inputs executables command process log source_path target_path",
               "component" if label == "harness" else "")
        source(build["source"])
        require(build["source"] == build["source_after"] and build["source"]["commit"] == refs[label],
                "revision-build-source-mismatch")
        if label == "harness":
            require(build["source"] == value["runner_source"], "revision-client-harness-source-mismatch")
        text(build["source_path"])
        text(build["target_path"])
        paths.add((build["source_path"], build["target_path"]))
        expected = HARNESS_COMMAND if label == "harness" else ["/bin/bash", "-eu", "-o", "pipefail", "-c", SERVER_RECIPE]
        require(build["command"] == expected, "revision-build-command-changed")
        owner = build["process"]
        process(owner, "artifact-identity-helper", owner["executable_sha256"])
        require(clean(owner), "unclean-revision-build")
        artifacts.path(build["log"])
        sidecar = build["log"]["path"] + ".process.json"
        require(sidecar in artifacts.rows and artifacts.json(artifacts.rows[sidecar]) == owner,
                "unbound-build-process-receipt")
        inputs = build["inputs"]
        require(isinstance(inputs, dict) and 1 <= len(inputs) <= 512, "revision-input-bound")
        for name, row in inputs.items():
            require(row["path"] == f"builds/{label}/source/{name}" and uint(row["bytes"]) > 0,
                    "crossed-build-source-path")
            artifacts.path(row)
        require(inputs.get("Cargo.lock", {}).get("sha256") == build["source"]["cargo_lock_sha256"],
                "unbound-revision-lockfile")
        selected = {}
        for prefix in SOURCE_CONTROLS:
            found = {name: (row["sha256"], row["bytes"]) for name, row in inputs.items()
                     if name == prefix or name.startswith(prefix + "/")}
            require(found, "missing-shared-build-control")
            selected.update(found)
        controls.append(selected)
        require(inputs["tools/phase0_build_environment.sh"]["sha256"] == settings["overrides"]["recipe_sha256"],
                "unbound-release-recipe")
        fields(build["executables"], "client cli" if label == "harness" else "server")
        for row in build["executables"].values():
            artifacts.path(row)
            require(uint(row["bytes"]) > 0, "empty-revision-executable")
    require(len(paths) == 1 and controls[0] == controls[1] == controls[2], "unmatched-build-path-or-shared-sources")
    harness_sources = value["harness_sources"]
    require(isinstance(harness_sources, dict) and 1 <= len(harness_sources) <= 1024, "missing-runner-sources")
    for name in ("tools/run_optimization_revision_benchmarks.py", "tools/run_optimization_benchmarks.py",
                 "tools/optimization_revision_runner/model.py", "tools/optimization_revision_evidence/suite.py",
                 "tools/optimization_evidence/client.py", "tools/optimization_runner/fixtures.py"):
        require(name in harness_sources, "missing-executed-harness-source")
    for name, row in harness_sources.items():
        require(row["path"] == "harness-source/" + name, "crossed-runner-source-path")
        artifacts.path(row)
    fixture(value, artifacts)


def fixture(value, artifacts):
    import copy
    from tools.optimization_runner.plans import SERVICES, TENANT, CONTRACT
    from tools.optimization_runner.fixtures import contracts, leb
    components, publications = value["components"], value["publications"]
    require(isinstance(components, list) and len(components) == 5
            and isinstance(publications, list) and len(publications) == 5, "missing-common-working-set")
    base = value["builds"]["harness"]["component"]
    payload = artifacts.path(base).read_bytes()
    require(0 < len(payload) <= 16 * 1024**2, "base-component-size")
    digests = set()
    for index, (row, package) in enumerate(zip(components, publications, strict=True)):
        fields(package, "component manifest contracts deployment")
        require(row == package["component"], "crossed-publication-component")
        actual = artifacts.path(row).read_bytes()
        name = b"optimization-working-set-v1"
        section = leb(len(name)) + name + bytes([index])
        expected = payload if index == 0 else payload + b"\x00" + leb(len(section)) + section
        require(actual == expected, "changed-common-component-variant")
        digests.add(row["sha256"])
        manifest, deployment = (artifacts.json(package[key]) for key in ("manifest", "deployment"))
        inputs = value["builds"]["harness"]["inputs"]
        expected_manifest = copy.deepcopy(artifacts.json(inputs["examples/echo-contract/capsule.json"]))
        expected_manifest["metadata"] = {"name": SERVICES[index], "tenant": TENANT}
        expected_manifest["component"].update(digest=row["sha256"], world="optimization:benchmark/service@0.1.0")
        expected_manifest.update(exports=[CONTRACT], imports=[])
        expected_manifest["execution"].update(threading="single-threaded", snapshotEligible=False, fusionEligible=False)
        expected_manifest["execution"]["limits"].update(cpuFuel=10_000_000_000, memoryBytes=67_108_864)
        expected_deployment = copy.deepcopy(artifacts.json(inputs["examples/echo-contract/deployment.json"]))
        expected_deployment["metadata"] = {"name": f"optimization-{index}", "tenant": TENANT}
        expected_deployment["spec"].update(service=SERVICES[index], release=row["sha256"], grants=[])
        expected_deployment["spec"]["resources"].update(cpuFuel=10_000_000_000, memoryBytes=67_108_864)
        require(manifest == expected_manifest and deployment == expected_deployment, "changed-complete-fixture-policy")
        require(manifest["metadata"] == {"name": SERVICES[index], "tenant": TENANT}
                and manifest["component"]["digest"] == row["sha256"]
                and manifest["component"]["world"] == "optimization:benchmark/service@0.1.0"
                and manifest["exports"] == [CONTRACT] and manifest["imports"] == []
                and artifacts.json(package["contracts"]) == contracts(), "changed-publication-contract-or-scope")
        require(deployment["metadata"] == {"name": f"optimization-{index}", "tenant": TENANT}
                and deployment["spec"]["service"] == SERVICES[index]
                and deployment["spec"]["release"] == row["sha256"], "changed-deployment-scope")
        for limits in (manifest["execution"]["limits"], deployment["spec"]["resources"]):
            require(limits["cpuFuel"] == 10_000_000_000 and limits["memoryBytes"] == 67_108_864,
                    "changed-fixture-grants")
    require(len(digests) == 5, "working-set-reuses-component-identity")
