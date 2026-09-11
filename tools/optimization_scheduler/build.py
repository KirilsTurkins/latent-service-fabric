"""Build the two scheduler libtests in one owned checkout; never run probes."""
import os
import platform
import time

from tools.optimization_revision_runner import backend, build as shared
from tools.optimization_revision_runner.collect import write
from tools.optimization_cache_lookup.files import Artifacts, inventory
from tools.phase1_measurement_environment import build_configuration
from . import builds


def execute(args, repo):
    if platform.system() != "Linux":
        raise ValueError("scheduler-build-requires-linux")
    refs = {key: getattr(args, key + "_ref") for key in ("control", "candidate", "harness")}
    shared.validate_refs(refs, args.profile)
    before = shared.source(repo)
    if before["commit"] != refs["harness"] or before["clean"] is not True:
        raise ValueError("scheduler-executed-harness-must-match-clean-ref")
    controls = []
    for ref in refs.values():
        names = shared.git(repo, "ls-tree", "-r", "--name-only", ref, *builds.COMMON).splitlines()
        rows = {name: {"sha256": shared.git(repo, "rev-parse", f"{ref}:{name}"), "bytes": "0"} for name in names}
        controls.append(builds.controlled(rows))
    if not controls[0] == controls[1] == controls[2]:
        raise ValueError("scheduler-common-source-controls-differ")
    if any(os.environ.get(key) for key in ("LD_PRELOAD", "LD_AUDIT", "MALLOC_CONF", "MALLOC_ARENA_MAX")):
        raise ValueError("scheduler-build-inherited-allocation-override")
    target = shared.preflight_build_parent(args.target_root)
    output = args.output.resolve()
    if output.exists() or output.is_symlink() or output.is_relative_to(target) or target.is_relative_to(output):
        raise ValueError("scheduler-build-output-not-fresh-or-overlapping")
    settings = build_configuration("full")
    settings["overrides"]["collector_surface"] = "libtest"
    output.mkdir(parents=True)
    receipt = {"schema": builds.SCHEMA, "requested_refs": refs, "build": settings, "builds": {}, "harness": None,
               "cleanup": {"owned_worktree_removed": False}}
    def retain():
        write(output / "scheduler-builds.json", receipt)
    def cleaned(removed):
        receipt["cleanup"]["owned_worktree_removed"] = removed
        retain()
    retain()
    deadline = time.monotonic_ns() + 10800 * 10**9
    target.mkdir(parents=True, exist_ok=True)
    try:
        with shared.owned_checkout(repo, refs["control"], target, cleaned) as (root, build_target):
            for label in ("control", "candidate", "harness"):
                if time.monotonic_ns() >= deadline:
                    raise TimeoutError("scheduler-build-deadline")
                if label != "control":
                    shared.git(root, "checkout", "--detach", refs[label])
                observed = shared.source(root)
                if observed["commit"] != refs[label] or observed["clean"] is not True:
                    raise ValueError("scheduler-build-ref-mismatch")
                if label == "harness":
                    inputs = backend.inputs(root, label, output, builds.COMMON)
                    after = shared.source(root)
                    if observed != after:
                        raise ValueError("scheduler-harness-source-changed")
                    receipt["harness"] = {"source": observed, "source_after": after, "inputs": inputs,
                                          "source_path": str(root), "target_path": str(build_target)}
                else:
                    receipt["builds"][label] = backend.build_libtest(root, build_target, label, output, deadline,
                                                                    "scheduler", builds.COMMON)
                retain()
        if shared.source(repo) != before:
            raise ValueError("scheduler-executed-harness-source-changed")
        builds.validate(receipt, Artifacts(output, inventory(output)), args.profile)
    except BaseException as error:
        write(output / "failure.json", {"type": type(error).__name__, "message": str(error)[:2048]})
        return 1
    return 0
