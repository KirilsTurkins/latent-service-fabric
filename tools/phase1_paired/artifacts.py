"""Retained bytes, bootstrap provenance and matched maintained guest sources."""

from pathlib import Path

from ..phase1_evidence.common import fields, read_json, require, uint, verify_artifact
from .common import CONTROL_COMMIT, CONTROL_TREE, RAW_LIMIT

SOURCES = tuple("tools/toolchain-smoke/examples/echo_capsule/" + name
                for name in ("component.rs", "logic.rs"))


class Artifacts:
    def __init__(self, root, rows):
        require(isinstance(rows, list) and 1 <= len(rows) <= 1024, "invalid-paired-artifact-count")
        self.root = root
        self.rows = {}
        self.paths = {}
        total = 0
        for row in rows:
            fields(row, "path sha256 bytes")
            require(row["path"] not in self.rows, "duplicate-paired-artifact")
            # Only retained executables may use the 1 GiB reproduction bound.
            binary = row["path"] in ("reproduction/control/release/phase0-baseline", "reproduction/candidate/collector")
            maximum = 1024**3 if binary else RAW_LIMIT
            path = verify_artifact(root, row, maximum)
            total += uint(row["bytes"])
            require(total <= 3 * 1024**3, "paired-artifact-total-limit")
            self.rows[row["path"]] = row
            self.paths[row["path"]] = path

    def path(self, ref):
        fields(ref, "path sha256 bytes")
        require(self.rows.get(ref["path"]) == ref, "unregistered-paired-artifact")
        return self.paths[ref["path"]]

    def json(self, ref, maximum=RAW_LIMIT):
        return read_json(self.path(ref), maximum)

    def nested(self, parent: Path, ref):
        # Nested references retain their original relative boundary.
        path = verify_artifact(parent, ref, 1024**3)
        relative = path.relative_to(self.root).as_posix()
        require(self.rows.get(relative) == dict(ref, path=relative), "unregistered-nested-artifact")
        return path


def bootstrap(artifacts, ref, candidate_sources):
    path = artifacts.path(ref)
    value = read_json(path, 256 * 1024)
    fields(value, "schema source build binary component capsule artifacts shared_guest_sources commands staged_manifest_changes scope full_invariant_proof")
    require(value["schema"] == "latent.phase1.control-build.v1"
            and value["scope"] == "targeted-historical-runtime-comparison-not-native-calibration"
            and value["full_invariant_proof"] == "not-run-by-this-build-helper", "invalid-control-build-scope")
    require(value["source"]["commit"] == CONTROL_COMMIT and value["source"]["tree"] == CONTROL_TREE
            and value["source"]["dirty"] is False, "changed-control-build-source")
    require(value["staged_manifest_changes"] == {"cpuFuel": "10000000000", "memoryBytes": "16777216"}, "changed-control-grants")
    require(value["commands"] == [["python3", "tools/build_echo_capsule.py", "--verify-reproducible"],
            ["phase0_release_cargo", "build", "-p", "latentd", "--bin", "phase0-baseline", "--release", "--locked"]], "changed-control-build-command")
    require(isinstance(value["artifacts"], list) and 10 <= len(value["artifacts"]) <= 128, "invalid-control-inputs")
    for item in [value[key] for key in ("binary", "component", "capsule")] + value["artifacts"]:
        artifacts.nested(path.parent, item)
    require(isinstance(candidate_sources, list) and len(candidate_sources) == 2
            and isinstance(value["shared_guest_sources"], list) and len(value["shared_guest_sources"]) == 2, "missing-matched-guest-source")
    for logical, current, proof in zip(SOURCES, candidate_sources, value["shared_guest_sources"], strict=True):
        fields(current, "path artifact")
        fields(proof, "source_path historical candidate")
        require(current["path"] == proof["source_path"] == logical, "crossed-guest-source")
        artifacts.path(current["artifact"])
        for arm in ("historical", "candidate"):
            artifacts.nested(path.parent, proof[arm])
            require(all(proof[arm][key] == current["artifact"][key] for key in ("sha256", "bytes")), "guest-logic-is-not-matched")
    indexed = {item["path"]: item for item in value["artifacts"]}
    for suffix, expected in (("/Cargo.lock", value["source"]["cargo_lock_sha256"]),
                             ("/tools/phase0_build_environment.sh", value["build"]["overrides"]["recipe_sha256"])):
        matches = [row for name, row in indexed.items() if name.endswith(suffix)]
        require(len(matches) == 1 and matches[0]["sha256"] == expected, "unbound-control-build-input")
    capsule = read_json(artifacts.nested(path.parent, value["capsule"]), 1024**2)
    limits = capsule["execution"]["limits"]
    require(limits["cpuFuel"] == 10_000_000_000 and limits["memoryBytes"] == 16_777_216
            and limits["logBytes"] == 16384, "control-capsule-grant-mismatch")
    return value
