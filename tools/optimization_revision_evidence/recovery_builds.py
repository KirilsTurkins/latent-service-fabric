"""Distinct #119 build identity using the existing strict copied-build replay."""
from tools.optimization_revision_runner import recovery
from . import budget_builds

HARNESS_SOURCES = (*budget_builds.HARNESS_SOURCES,
                   "tools/optimization_revision_runner/recovery.py",
                   "tools/optimization_revision_runner/recovery_build.py",
                   "tools/optimization_revision_evidence/recovery.py",
                   "tools/optimization_revision_evidence/recovery_builds.py",
                   "tools/phase1_cleanup_shutdown.py")


def identity_check(value, refs, artifacts):
    return budget_builds.identity_check(value, refs, artifacts, model=recovery, harness_sources=HARNESS_SOURCES)


def receipt(suite):
    return budget_builds.receipt(suite, model=recovery)


def validate(value, artifacts, profile):
    return budget_builds.validate(value, artifacts, profile, model=recovery, harness_sources=HARNESS_SOURCES)


def load(path, profile):
    return budget_builds.load(path, profile, model=recovery, harness_sources=HARNESS_SOURCES)
