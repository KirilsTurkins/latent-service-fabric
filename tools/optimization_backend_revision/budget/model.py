"""The fixed 23-offer diagnostic; profile changes pair count, never its cases."""
from tools.optimization_evidence.common import require

COLLECTOR = "standalone::measurements::comparison::budget::phase1_budget_collector"
SCHEMA = "latent.optimization.budget-lifecycle-suite.v1"
BUDGETS = (1, 2, 5, 10)


def plan(profile, repetition=1, variant="control"):
    require(profile in ("smoke", "full") and variant in ("control", "candidate"), "budget-lifecycle-plan-selection")
    require(type(repetition) is int and 1 <= repetition <= (7 if profile == "full" else 1), "budget-lifecycle-repetition")
    return {"schema": "latent.optimization.budget-lifecycle-plan.v1", "profile": profile, "repetition": repetition}


def offers():
    rows = [("prewarm", 1000, "identify")]
    rows += [("holder", 1000, "spin")] * 4
    for case, function in (("queued", "identify"), ("delayed-body", "identify"),
                           ("runaway", "spin"), ("cancel", "spin")):
        rows += [(case, budget, function) for budget in BUDGETS]
    return rows + [("positive-cancel", 1000, "spin"), ("recovery", 1000, "identify")]


def maximum_seconds(_profile):
    return 180


def transport_budget(case, budget):
    return 1000 if case in ("runaway", "cancel") else budget


def identity(builds, variant, environment):
    from ..model import identity as common_identity
    # Only the retained fixture source differs from the existing identity graph.
    projected = dict(builds, harness={"echo": {"component": builds["harness"]["component"]}})
    value = common_identity(projected, variant, environment)
    value["fixtures"][0]["name"] = "generic"
    return value
