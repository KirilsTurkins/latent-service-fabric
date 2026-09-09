"""Fixed ownership populations and full-completion structural guards.

Synthetic aggregate envelopes below test schema boundaries, not performance.
Actual source, call, resource and profiler replay remains mandatory.
"""
import copy
import json
from pathlib import Path
import unittest

import jsonschema

from tools.optimization_backend_revision.ownership import model
from tools.optimization_revision_runner import ownership as rpc


DIRECTORY = Path(__file__).resolve().parents[2] / "benchmarks/optimization"


def validator(kind):
    schema = json.loads((DIRECTORY / f"{kind}.schema.json").read_bytes())
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


class OwnershipSchemaTests(unittest.TestCase):
    def test_all_eight_envelopes_are_valid_schemas(self):
        for prefix in ("ownership", "ownership-rpc"):
            for kind in ("plan", "builds", "suite", "aggregate"):
                with self.subTest(prefix=prefix, kind=kind):
                    validator(f"{prefix}-{kind}")

    def test_exact_plans_reject_changed_or_extended_populations(self):
        direct, external = validator("ownership-plan"), validator("ownership-rpc-plan")
        for profile in ("smoke", "full"):
            external.validate(rpc.plan(profile))
            plans = [model.plan(profile, mode="fixtures")]
            plans.extend(model.plan(profile, repetition) for repetition in range(1, 8 if profile == "full" else 2))
            plans.extend(model.plan(profile, mode="allocation", shape=shape) for shape in model.SHAPES)
            for plan in plans:
                direct.validate(plan)
                for changed in (dict(plan, invented=True), dict(plan, measured_per_shape=999)):
                    with self.assertRaises(jsonschema.ValidationError):
                        direct.validate(changed)
            for changed in (dict(rpc.plan(profile), setup_cases=["prewarm-echo"]),
                            dict(rpc.plan(profile), repetitions=8)):
                with self.assertRaises(jsonschema.ValidationError):
                    external.validate(changed)

    def test_full_completion_requires_correct_counts_and_both_flags(self):
        for prefix, attempts, processes, scope in (
            ("ownership", "3160", "26", "direct-wasmtime-invocation-and-independent-input-ownership-and-allocation-populations"),
            ("ownership-rpc", "12936", "70", "lsf-revisions-shared-external-client-request-payload-ownership"),
        ):
            value = {"schema": f"latent.optimization.{prefix}-aggregate.v1", "profile": "full", "status": "complete",
                     "population_complete": True, "attempt_count_complete": True,
                     "validated_attempts": attempts, "validated_processes": processes,
                     "suite_sha256": "sha256:" + "a" * 64, "plan_sha256": "sha256:" + "b" * 64,
                     "scope": scope, "runs": [], "comparisons": [], "limitations": []}
            value.update({"builds": {}} if prefix == "ownership" else {"identity": {}, "clock_ticks_per_second": 100})
            selected = validator(f"{prefix}-aggregate")
            selected.validate(value)
            for field, changed in (("profile", "smoke"), ("population_complete", False),
                                   ("attempt_count_complete", False), ("validated_attempts", "0"),
                                   ("validated_processes", "0"), ("invented", True)):
                with self.subTest(prefix=prefix, field=field), self.assertRaises(jsonschema.ValidationError):
                    selected.validate(dict(value, **{field: changed}))
            # A structurally valid smoke envelope is still incomplete evidence.
            smoke = copy.deepcopy(value)
            smoke.update(profile="smoke", status="incomplete", validated_attempts="88" if prefix == "ownership" else "76",
                         validated_processes="14" if prefix == "ownership" else "10")
            selected.validate(smoke)


if __name__ == "__main__":
    unittest.main()
