"""Retain bounded failed-population facts without claiming semantic qualification."""
from tools.optimization_evidence.common import fields, require, uint


def summarize(raw, plan, identity):
    require(isinstance(raw, dict) and raw.get("schema") == "latent.optimization.budget-lifecycle-arm.v1"
            and raw.get("plan") == plan and raw.get("identity") == identity, "budget-failed-raw-identity-crossed")
    rows = raw.get("samples")
    require(isinstance(rows, list) and len(rows) <= 256, "budget-failed-raw-bound")
    work = fields(raw.get("work"), "invoke_attempts commands budget_exhausted")
    offered, commands = uint(work["invoke_attempts"]), uint(work["commands"])
    require(offered <= 23 and offered <= commands <= 153 and type(work["budget_exhausted"]) is bool, "budget-failed-work-bound")
    retained = [row for row in rows if row.get("kind") == "invoke"]
    ordinals = [uint(row.get("ordinal")) for row in retained]
    require(len(retained) <= offered and len(set(ordinals)) == len(ordinals)
            and all(index < 23 for index in ordinals), "budget-failed-duplicate-offer")
    return {"observed_invoke_attempts": str(offered), "observed_commands": str(commands),
            "retained_offer_rows": str(len(retained)), "offers_without_final_rows": str(offered - len(retained)),
            "raw_status": raw.get("status"), "raw_reason": raw.get("reason"),
            "qualification": "failed-unqualified-raw-retained"}
