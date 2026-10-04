"""Closed state declarations preserve explicit physical owners and target pins."""
import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "schemas/node-state.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)


def configuration():
    return {
        "formatVersion": 2, "configurationEpoch": 1, "storeIdentity": "production-state",
        "checkpointRoot": "/private/transaction-checkpoint", "startupTimeoutMillis": 5000,
        "store": {
            "maximumFileBytes": 268435456, "cacheBytes": 8388608, "maximumRows": 16384,
            "maximumLogicalBytes": 33554432, "maximumReadViews": 8,
            "maximumViewAgeMillis": 30000,
            "ordinary": {"workers": 3, "queuedJobs": 8, "acceptedJobs": 32,
                         "activeReads": 2, "retainedBytes": 117440512,
                         "maximumJobBytes": 41943040},
            "recovery": {"workers": 1, "queuedJobs": 4, "acceptedJobs": 8,
                         "retainedBytes": 16777216, "maximumJobBytes": 8396800},
        },
        "native": {
            "ordinary": {"slots": 128, "bytes": 268435456,
                         "maximumReservationBytes": 67108864},
            "recovery": {"slots": 8, "bytes": 100663296,
                         "maximumReservationBytes": 33554432},
            "maximumLifetimeMillis": 180000,
        },
        "dispatcher": {"workers": 2, "queuedJobs": 4, "acceptedJobs": 16,
                       "maximumCommandOwners": 128, "perTenantJobs": 1,
                       "retainedBytes": 83886080, "pageRows": 16, "pageBytes": 1048576,
                       "scanPagesPerTick": 4, "pollIntervalMillis": 100},
        "operations": [],
    }


def operation():
    return {"tenant": "tenant", "componentDigest": "sha256:" + "a" * 64,
            "publication": "publication:sha256:" + "b" * 64,
            "contract": "example:state/api@1.0.0", "function": "save",
            "deployment": "state", "binding": "state", "companionDigest": "sha256:" + "c" * 64,
            "incarnation": 1, "resultPolicy": "owner", "statePolicies": ["state"]}


class NodeStateSchema(unittest.TestCase):
    def test_explicit_finite_owner_profile_and_creation_refusal_default(self):
        Draft202012Validator.check_schema(SCHEMA)
        VALIDATOR.validate(configuration())
        self.assertEqual(SCHEMA["properties"]["createIfMissing"]["default"], False)
        for name in ("storeIdentity", "checkpointRoot", "startupTimeoutMillis", "store", "native",
                     "dispatcher", "operations", "configurationEpoch"):
            missing = configuration()
            del missing[name]
            self.assertFalse(VALIDATOR.is_valid(missing), name)
        for value in (None, [], {}, dict(configuration(), formatVersion=1)):
            self.assertFalse(VALIDATOR.is_valid(value), value)

    def test_unknown_authority_flags_and_positional_or_missing_owner_objects_refuse(self):
        for path in ((), ("store",), ("store", "ordinary"), ("store", "recovery"),
                     ("native",), ("native", "ordinary"), ("native", "recovery"),
                     ("dispatcher",)):
            for name in ("unlimited", "continuityProven", "restoreApproved", "grant"):
                changed = configuration()
                target = changed
                for field in path:
                    target = target[field]
                target[name] = True
                self.assertFalse(VALIDATOR.is_valid(changed), (path, name))
            if path:
                for value in (None, [], {}):
                    changed = configuration()
                    target = changed
                    for field in path[:-1]:
                        target = target[field]
                    target[path[-1]] = value
                    self.assertFalse(VALIDATOR.is_valid(changed), (path, value))

    def test_original_startup_deadline_and_reserved_recovery_bounds_are_finite(self):
        for name, values in {
            "startupTimeoutMillis": (0, 1, 999, 60001, True, None, 1.5),
            "configurationEpoch": (0, 18446744073709551616, True, None),
            "checkpointRoot": ("", "relative", None, "/" + "x" * 4096),
            "storeIdentity": ("", "x" * 129, "ambiguous identity", None),
        }.items():
            for value in values:
                self.assertFalse(VALIDATOR.is_valid(dict(configuration(), **{name: value})), (name, value))
        for duration in (1000, 60000):
            VALIDATOR.validate(dict(configuration(), startupTimeoutMillis=duration))
        for section, name, value in (("native", "maximumLifetimeMillis", 3600001),
                                     ("store", "maximumReadViews", 33),
                                     ("dispatcher", "acceptedJobs", 129)):
            changed = configuration()
            changed[section][name] = value
            self.assertFalse(VALIDATOR.is_valid(changed), (section, name))
        changed = configuration()
        changed["native"]["recovery"]["slots"] = 1
        self.assertFalse(VALIDATOR.is_valid(changed))
        changed = configuration()
        changed["store"]["recovery"]["maximumJobBytes"] = 8396799
        self.assertFalse(VALIDATOR.is_valid(changed))

    def test_installed_target_has_exact_immutable_identity_and_no_permission_flags(self):
        valid = dict(configuration(), operations=[operation()])
        VALIDATOR.validate(valid)
        for name in ("tenant", "componentDigest", "publication", "contract", "function",
                     "deployment", "binding", "companionDigest", "incarnation", "resultPolicy",
                     "statePolicies"):
            changed = copy.deepcopy(valid)
            del changed["operations"][0][name]
            self.assertFalse(VALIDATOR.is_valid(changed), name)
        for name, value in (("incarnation", 0), ("entity", None), ("route", None),
                            ("grant", True), ("statePolicies", ["same", "same"]),
                            ("deferredHttp", None), ("componentDigest", "sha256:" + "A" * 64)):
            changed = copy.deepcopy(valid)
            changed["operations"][0][name] = value
            self.assertFalse(VALIDATOR.is_valid(changed), (name, value))
        maximum = copy.deepcopy(valid)
        maximum["operations"][0]["incarnation"] = 18446744073709551615
        VALIDATOR.validate(maximum)
        self.assertFalse(VALIDATOR.is_valid(dict(configuration(), operations=[operation()] * 129)))

    def test_tenant_and_provider_constraints_are_closed_and_bounded(self):
        fields = SCHEMA["$defs"]["tenantLimits"]["properties"]
        limits = {name: (65536 if name.endswith(("Keys", "Rows")) else 1073741824)
                  for name in fields}
        valid = dict(configuration(), tenantQuotas=[{"tenant": "tenant", "limits": limits}])
        VALIDATOR.validate(valid)
        for name in fields:
            for value in (None, True, -1, fields[name]["maximum"] + 1):
                changed = copy.deepcopy(valid)
                changed["tenantQuotas"][0]["limits"][name] = value
                self.assertFalse(VALIDATOR.is_valid(changed), (name, value))
        provider = {"requirementsDigest": "sha256:" + "d" * 64,
                    "providerId": "http", "providerIncarnation": "e" * 64,
                    "credentialReference": "protected-reference", "stagingBinding": "stage",
                    "stagingPolicies": ["stage"], "dispatchBinding": "dispatch",
                    "dispatchPolicies": ["dispatch"]}
        valid = dict(configuration(), operations=[dict(operation(), deferredHttp=provider)])
        VALIDATOR.validate(valid)
        for name in ("credential", "enabled", "grant", "credentialEpoch", "policyRevision"):
            changed = copy.deepcopy(valid)
            changed["operations"][0]["deferredHttp"][name] = "config-is-not-authority"
            self.assertFalse(VALIDATOR.is_valid(changed), name)


if __name__ == "__main__":
    unittest.main()
