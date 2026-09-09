"""One fixed 61-offer pair; smoke never becomes full publication evidence."""
from tools.optimization_evidence.common import require
from ..budget.model import identity

SCHEMA = "latent.optimization.recovery-suite.v1"
COLLECTOR = "standalone::measurements::comparison::recovery::phase1_recovery_collector"
BUDGETS = (1, 2, 5, 10)


def plan(profile, repetition=1, variant="control"):
    require(profile in ("smoke", "full") and variant in ("control", "candidate")
            and type(repetition) is int and repetition == 1, "recovery-plan-selection")
    return {"schema": "latent.optimization.recovery-plan.v1", "profile": profile, "repetition": 1}


def population(profile):
    plan(profile)
    return [(1, "control"), (1, "candidate")]


def offers():
    rows = [("prewarm", 1000, "identify")]
    for _round in range(3):
        for ceiling in BUDGETS:
            for case in ("expiry", "disconnect"):
                rows.extend(((case, ceiling, "spin"), ("recovery", 1000, "identify")))
    for _index in range(5):
        rows.extend((("running-disconnect", 1000, "spin"), ("recovery", 1000, "identify")))
    return rows + [("positive-cancel", 1000, "spin"), ("recovery", 1000, "identify")]


def maximum_seconds(_profile):
    return 180
