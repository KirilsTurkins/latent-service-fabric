"""Build two exact libtest surfaces into separate bounded evidence roots."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import time

from tools.optimization_revision_runner import backend, build as shared
from tools.optimization_revision_runner.collect import write
from tools.phase1_measurement_environment import build_configuration
from . import builds
from .files import Artifacts, inventory


def matching_controls(repo, refs):
    controls = []
    for ref in refs.values():
        names = shared.git(repo, "ls-tree", "-r", "--name-only", ref, *builds.COMMON).splitlines()
        rows = {name: {"sha256": shared.git(repo, "rev-parse", f"{ref}:{name}"), "bytes": "0"} for name in names}
        controls.append(builds.controlled(rows))
    if not controls[0] == controls[1] == controls[2]:
        raise ValueError("cache-common-source-controls-differ")


def execute(args, repo):
    if platform.system() != "Linux":
        raise ValueError("cache-build-requires-linux")
    refs = {key: getattr(args, key + "_ref") for key in ("control", "candidate", "harness")}
    shared.validate_refs(refs, args.profile)
    before = shared.source(repo)
    if before["commit"] != refs["harness"] or before["clean"] is not True:
        raise ValueError("cache-executed-harness-must-match-clean-ref")
    target = shared.preflight_build_parent(args.target_root)
    matching_controls(repo, refs)
    if any(os.environ.get(key) for key in ("LD_PRELOAD", "LD_AUDIT", "MALLOC_CONF", "MALLOC_ARENA_MAX")):
        raise ValueError("cache-build-inherited-allocation-override")
    roots = {"lookup": args.lookup_output.resolve(), "behavior": args.behavior_output.resolve()}
    if roots["lookup"].is_relative_to(roots["behavior"]) or roots["behavior"].is_relative_to(roots["lookup"]):
        raise ValueError("cache-build-output-roots-overlap")
    if any(path.exists() or path.is_symlink() for path in roots.values()):
        raise ValueError("cache-build-output-not-fresh")
    settings = build_configuration("full")
    settings["overrides"]["collector_surface"] = "libtest"
    receipts = {}
    for kind, output in roots.items():
        output.mkdir(parents=True)
        receipts[kind] = {"schema": builds.SCHEMA, "kind": kind, "requested_refs": refs, "build": settings,
                          "builds": {}, "harness": None, "cleanup": {"owned_worktree_removed": False}}

    def retain():
        for kind, output in roots.items():
            write(output / "cache-builds.json", receipts[kind])

    def cleaned(removed):
        for value in receipts.values():
            value["cleanup"]["owned_worktree_removed"] = removed
        retain()

    retain()
    deadline = time.monotonic_ns() + 10800 * 10**9
    target.mkdir(parents=True, exist_ok=True)
    try:
        with shared.owned_checkout(repo, refs["control"], target, cleaned) as (root, build_target):
            for label in ("control", "candidate", "harness"):
                if time.monotonic_ns() >= deadline:
                    raise TimeoutError("cache-build-deadline")
                if label != "control":
                    shared.git(root, "checkout", "--detach", refs[label])
                observed = shared.source(root)
                if observed["commit"] != refs[label] or observed["clean"] is not True:
                    raise ValueError("cache-build-ref-mismatch")
                if label == "harness":
                    retained = backend.inputs(root, label, roots["lookup"], (*builds.COMMON, *builds.PYTHON_INPUTS))
                    after = shared.source(root)
                    if observed != after:
                        raise ValueError("cache-harness-source-changed")
                    receipts["lookup"]["harness"] = {"source": observed, "source_after": after, "inputs": retained,
                                                          "source_path": str(root), "target_path": str(build_target)}
                    receipts["behavior"]["harness"] = backend.build_echo(root, build_target, roots["behavior"], deadline,
                                                                              (*builds.COMMON, *builds.PYTHON_INPUTS))
                else:
                    for kind, executable in (("lookup", "lookup"), ("behavior", "backend")):
                        receipts[kind]["builds"][label] = backend.build_libtest(root, build_target, label, roots[kind], deadline,
                                                                                 executable, builds.COMMON)
                        retain()
                retain()
        if shared.source(repo) != before:
            raise ValueError("cache-executed-harness-source-changed")
        for kind, output in roots.items():
            rows = inventory(output)
            binaries = {item["executables"]["lookup" if kind == "lookup" else "backend"]["path"]
                        for item in receipts[kind]["builds"].values()}
            builds.validate(receipts[kind], Artifacts(output, rows, binaries), args.profile, kind)
    except BaseException as error:
        for output in roots.values():
            write(output / "failure.json", {"type": type(error).__name__, "message": str(error)[:2048]})
        return 1
    return 0
