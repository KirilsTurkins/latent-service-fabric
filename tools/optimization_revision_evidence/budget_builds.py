"""Bind a copied build-only graph before any new external budget measurement."""
from pathlib import Path

from tools.optimization_evidence.artifacts import Artifacts
from tools.optimization_evidence.common import DOCUMENT_BYTES, fields, hash_file, read_json, require, uint
from tools.optimization_revision_runner import budget
from tools.optimization_revision_runner.build import validate_refs
from . import identity

HARNESS_SOURCES = ("tools/optimization_revision_runner/budget.py",
                   "tools/optimization_revision_runner/budget_build.py",
                   "tools/optimization_revision_evidence/budget.py",
                   "tools/optimization_revision_evidence/budget_builds.py")


def identity_check(value, refs, artifacts):
    identity.validate(value, refs, artifacts, source_controls=budget.SOURCE_CONTROLS,
                      harness_command=budget.HARNESS_COMMAND, extra_harness_sources=HARNESS_SOURCES)
    require(len({build["source"]["cargo_lock_sha256"] for build in value["builds"].values()}) == 1,
            "budget-build-lock-controls-differ")


def receipt(suite):
    return {"schema": budget.BUILD_SCHEMA, "status": suite["status"], "reason": suite["reason"],
            "elapsed_nanos": suite["elapsed_nanos"], "requested_refs": suite["requested_refs"],
            "identity": suite["identity"], "cleanup": suite["cleanup"], "artifacts": suite["artifacts"]}


def validate(value, artifacts, profile):
    fields(value, "schema status reason elapsed_nanos requested_refs identity cleanup artifacts")
    require(value["schema"] == budget.BUILD_SCHEMA, "budget-build-schema")
    validate_refs(value["requested_refs"], profile)
    require(value["status"] == "passed" and value["reason"] is None,
            "budget-build-not-complete")
    require(uint(value["elapsed_nanos"]) <= 10800 * 10**9, "budget-build-time-bound")
    require(value["cleanup"] == {"owned_worktree_removed": True}, "budget-build-owner-not-clean")
    require(isinstance(value["artifacts"], list) and 1 <= len(value["artifacts"]) <= 4096
            and len({row["path"].casefold() for row in value["artifacts"]}) == len(value["artifacts"])
            and sum(uint(row["bytes"]) for row in value["artifacts"]) <= 1024**3,
            "budget-build-artifact-bound")
    for row in value["artifacts"]:
        artifacts.path(row)
    identity_check(value["identity"], value["requested_refs"], artifacts)
    return value


def load(path, profile):
    path = Path(path)
    checksum = hash_file(path, DOCUMENT_BYTES)
    value = read_json(path)
    executables = {row["path"] for build in value.get("identity", {}).get("builds", {}).values()
                   for row in build.get("executables", {}).values()}
    artifacts = Artifacts(path.parent, value["artifacts"], executables)
    validate(value, artifacts, profile)
    require(hash_file(path, DOCUMENT_BYTES) == checksum, "budget-build-receipt-changed-during-read")
    return value
