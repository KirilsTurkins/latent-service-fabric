"""Exact copied-build provenance for the unchanged external warm engine slice."""
from tools.optimization_revision_runner import engine
from tools.optimization_evidence.common import require, uint
from . import budget_builds

HARNESS_SOURCES = (*budget_builds.HARNESS_SOURCES,
                   "tools/optimization_revision_runner/engine.py",
                   "tools/optimization_revision_runner/engine_build.py",
                   "tools/optimization_revision_evidence/engine.py",
                   "tools/optimization_revision_evidence/engine_builds.py",
                   "tools/phase1_cleanup_shutdown.py")


def identity_check(value, refs, artifacts):
    return budget_builds.identity_check(value, refs, artifacts, model=engine, harness_sources=HARNESS_SOURCES)


def receipt(suite):
    return budget_builds.receipt(suite, model=engine)


def validate(value, artifacts, profile):
    result = budget_builds.validate(value, artifacts, profile, model=engine, harness_sources=HARNESS_SOURCES)
    require(uint(value["elapsed_nanos"]) <= 7200 * 10**9, "engine-build-stage-time-bound")
    return result


def load(path, profile):
    result = budget_builds.load(path, profile, model=engine, harness_sources=HARNESS_SOURCES)
    require(uint(result["elapsed_nanos"]) <= 7200 * 10**9, "engine-build-stage-time-bound")
    return result
