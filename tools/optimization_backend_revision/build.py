"""Build only the two exact libtest collectors and one shared Echo fixture."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import time

from tools.optimization_revision_runner import backend, build as shared
from tools.optimization_revision_runner.collect import write
from tools.phase1_measurement_environment import build_configuration


def matching_controls(repo,refs,experiment):
    names=(*backend.CONTROLS,"rust-toolchain.toml",".cargo/config.toml","tools/phase0_build_environment.sh")
    if experiment == "catalog":
        from .catalog.builds import CONTROLS
        names=(*CONTROLS,"rust-toolchain.toml",".cargo/config.toml","tools/phase0_build_environment.sh")
    if experiment == "cold":
        names=(*names,*backend.COLD_CONTROLS)
    for name in names:
        if len({shared.git(repo,"rev-parse",f"{ref}:{name}") for ref in refs.values()}) != 1:
            raise ValueError("backend-collector-source-controls-differ:"+name)


def collect(repo,refs,output,target,deadline,receipt,*,extra_controls=()):
    def cleaned(removed):
        receipt["cleanup"]["owned_worktree_removed"]=removed
        write(output/"backend-builds.json",receipt)
    with shared.owned_checkout(repo,refs["control"],target,cleaned) as (root,build_target):
        for label in ("control","candidate","harness"):
            if time.monotonic_ns() >= deadline:
                raise TimeoutError("backend-build-deadline")
            if label != "control":
                shared.git(root,"checkout","--detach",refs[label])
            observed=shared.source(root)
            if observed["commit"] != refs[label] or observed["clean"] is not True:
                raise ValueError("backend-source-ref-mismatch")
            if label == "harness":
                receipt["harness"]=(backend.build_echo(root,build_target,output,deadline,extra_controls)
                                    if extra_controls else backend.build_echo(root,build_target,output,deadline))
            else:
                receipt["builds"][label]=(backend.build_libtest(root,build_target,label,output,deadline,"backend",extra_controls)
                                          if extra_controls else backend.build_backend(root,build_target,label,output,deadline))
            write(output/"backend-builds.json",receipt)


def execute(args,repo: Path):
    if platform.system() != "Linux":
        raise ValueError("backend-build-requires-linux")
    if args.experiment not in ("warm","cold","catalog") or args.profile not in ("smoke","full"):
        raise ValueError("backend-build-selection")
    refs={name:getattr(args,name+"_ref") for name in ("control","candidate","harness")}
    shared.validate_refs(refs,args.profile)
    before=shared.source(repo)
    if before["commit"] != refs["harness"] or before["clean"] is not True:
        raise ValueError("executed-runner-must-match-clean-harness-ref")
    target=shared.preflight_build_parent(args.target_root)
    matching_controls(repo,refs,args.experiment)
    if any(os.environ.get(name) for name in ("LD_PRELOAD","LD_AUDIT","MALLOC_CONF","MALLOC_ARENA_MAX")):
        raise ValueError("backend-build-inherited-allocation-override")
    output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=False)
    target.mkdir(parents=True,exist_ok=True)
    settings=build_configuration("full")
    settings["overrides"]["collector_surface"]="libtest"
    receipt={"schema":"latent.optimization.catalog-builds.v1" if args.experiment == "catalog" else "latent.optimization.backend-builds.v1","requested_refs":refs,"build":settings,
             "builds":{},"harness":None,"cleanup":{"owned_worktree_removed":False}}
    write(output/"backend-builds.json",receipt)
    began=time.monotonic_ns()
    try:
        if args.experiment == "catalog":
            from .catalog.builds import CONTROLS
            collect(repo,refs,output,target,began+10_800*10**9,receipt,extra_controls=CONTROLS)
        else:
            collect(repo,refs,output,target,began+10_800*10**9,receipt)
        if shared.source(repo) != before:
            raise ValueError("backend-executed-harness-source-changed")
        from .builds import validate_experiment
        from .evidence import artifact_set
        validate_experiment(receipt,artifact_set(output,receipt),args.profile,args.experiment)
    except BaseException as error:
        write(output/"failure.json",{"type":type(error).__name__,"message":str(error)[:2048]})
        return 1
    return 0
