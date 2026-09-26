#!/usr/bin/env python3
"""Select a real prior candidate artifact for bounded VM-only diagnostics."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import sys
import tomllib

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.native_release_gate import github
from tools.native_runtime import verify
from tools.native_runtime.common import InstallError, require

ROOT = Path(__file__).resolve().parents[1]


def candidate_source(run):
    require(run.get("path") == verify.CANDIDATE_WORKFLOW
            and run.get("head_repository", {}).get("full_name") == verify.REPOSITORY
            and run.get("event") in {"push", "workflow_dispatch"}, "only-own-candidate-workflow-artifacts-may-be-retested")
    commit, branch = run.get("head_sha"), run.get("head_branch")
    require(isinstance(commit, str) and verify.SOURCE.fullmatch(commit)
            and isinstance(branch, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,220}", branch)
            and ".." not in branch and "//" not in branch, "exact-candidate-source-ref-required")
    return commit, "refs/heads/" + branch


def select():
    require(os.environ.get("GITHUB_REPOSITORY") == verify.REPOSITORY, "own-native-candidate-repository-required")
    selected = os.environ.get("VM_ARTIFACT_RUN", "")
    run_id = selected or os.environ["GITHUB_RUN_ID"]
    require(re.fullmatch(r"[1-9][0-9]{0,14}", run_id), "bounded-exact-candidate-artifact-run-required")
    if selected:
        require(os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "artifact-retest-requires-explicit-dispatch")
        commit, reference = candidate_source(github("actions/runs/" + run_id))
        source = github("contents/Cargo.toml?ref=" + commit)
        require(source.get("encoding") == "base64" and source.get("size", 65537) <= 65536, "bounded-source-version-required")
        cargo = base64.b64decode(source["content"])
    else:
        commit, reference = os.environ["GITHUB_SHA"], os.environ["GITHUB_REF"]
        cargo = (ROOT / "Cargo.toml").read_bytes()
    version = verify.version(tomllib.loads(cargo.decode())["workspace"]["package"]["version"])
    verify.publisher_policy({"schemaVersion": "latent.native-publisher-policy.v1", "repository": verify.REPOSITORY,
                             "workflow": verify.CANDIDATE_WORKFLOW, "sourceRef": reference, "sourceCommit": commit,
                             "version": version, "purpose": "candidate"}, version, True)
    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as stream:
        for name, value in {"NATIVE_ARTIFACT_COMMIT": commit, "NATIVE_ARTIFACT_REF": reference,
                            "NATIVE_VERSION": version, "NATIVE_ARTIFACT_RUN": run_id}.items():
            stream.write(name + "=" + value + "\n")
    print(json.dumps({"artifactRun": run_id, "sourceCommit": commit, "sourceRef": reference,
                      "version": version, "vmOnlyRetest": bool(selected), "releaseAuthority": False}))


if __name__ == "__main__":
    try:
        select()
    except (InstallError, OSError, KeyError, TypeError, ValueError):
        print("native-candidate-artifact-selection-failed", file=sys.stderr)
        raise SystemExit(1)
