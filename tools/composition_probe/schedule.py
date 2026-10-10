"""Finite actual frontend checks around the normal Java owner's live campaign."""
from copy import deepcopy

from tools.dev_workflow.common import digest, encode
from tools.phase2_operator_process import require


class Schedule:
    def __init__(self, frontend, original):
        self.frontend = frontend
        self.original = deepcopy(original)
        self.original_digest = digest(encode(original))

    def check(self, name, value=None, **options):
        require(digest(encode(self.original)) == self.original_digest,
                "composition-probe-original-intent-changed")
        result = self.frontend.check(name, deepcopy(self.original if value is None else value), **options)
        require(digest(encode(self.original)) == self.original_digest,
                "composition-probe-original-intent-changed")
        return result

    def current(self, *, mode="standalone", name="current-signed-composition"):
        return self.check(name, mode=mode, checks=(
            ("authoritative-preparation", "passed", "selected-component-preparation"),
            ("authoritative-preparation", "passed", "actual-component-contract-surface"),
            ("authenticated-live-state", "passed", "coherent-authorized-composition-observation")))

    def negatives(self, *, mode="standalone"):
        require({row["id"] for row in self.original["components"]} == {"domain", "adapter"},
                "composition-probe-http-pair-required")
        cases = []
        value = deepcopy(self.original)
        value["nodeProfile"]["maximumWirePayloadBytes"] = "2097151"
        cases.append(("narrow-http-wire", value, "structural", "http-minimum-wire-payload"))
        value = deepcopy(self.original)
        value["triggers"] = [{**next(row for row in value["triggers"] if row["component"] == "domain"), "kind": "http"}]
        cases.append(("ordinary-domain-http-trigger", value, "structural", "trigger-contract-publication-match"))
        value = deepcopy(self.original)
        value["providers"] = [row for row in value["providers"] if row["contract"] != "latent:service/invoke@0.1.0"]
        cases.append(("missing-selected-service-provider", value, "structural", "declared-provider-installations"))
        value = deepcopy(self.original)
        adapter = next(row for row in value["components"] if row["id"] == "adapter")
        adapter["target"]["publicationId"] = "publication:sha256:" + "0" * 64
        cases.append(("stale-original-publication", value, "authenticated-live-state", "immutable-publication-selection-stale"))
        value = deepcopy(self.original)
        adapter = next(row for row in value["components"] if row["id"] == "adapter")
        adapter["target"]["deploymentGeneration"] = str(int(adapter["target"]["deploymentGeneration"]) + 1)
        cases.append(("different-deployment-generation", value, "authenticated-live-state", "immutable-publication-selection-stale"))
        value = deepcopy(self.original)
        domain = next(row for row in value["components"] if row["id"] == "domain")
        functions = domain["exports"][0]["functions"]
        omitted = next(function for function in functions if function != domain["target"]["function"])
        functions.remove(omitted)
        cases.append(("wrong-declared-compiled-surface", value, "authoritative-preparation", "actual-component-contract-surface"))
        return [self.check(name, value, mode=mode, passed=False, checks=((level, "failed", code),))
                for name, value, level, code in cases]

    def changed_authority(self, *, mode="standalone"):
        result = self.check("original-intent-after-policy-change", mode=mode, passed=False)
        require(any(row["state"] == "failed" and row["code"] in {
            "observed-composition-changed-or-stale", "selected-provider-binding-policy-current",
            "current-target-eligibility"} for row in result["checks"]),
            "composition-probe-old-authority-accepted")
        return result

    def former_profile(self, *, mode="standalone"):
        result = self.check("former-profile-original-allocation-rejection", mode=mode, passed=False,
            checks=(("authoritative-preparation", "failed", "selected-component-preparation"),))
        details = [row["diagnostic"] for row in result["checks"]
                   if row["code"] == "selected-component-preparation" and row.get("diagnostic") is not None]
        require(len(details) == 1 and details[0]["stage"] == 3 and details[0]["reason"] == 1,
                "composition-probe-original-former-diagnostic")
        diagnostic = details[0]
        bound, required, fixed, fuel, multiplier = (int(diagnostic[name]) for name in (
            "configuredBound", "calculatedRequirement", "fixedBytes", "liftingFuel", "liftMultiplier"))
        require(bound == 67108864 and fuel == 2097152 and required == fixed + fuel * multiplier
                and required > bound and diagnostic["profileDigest"],
                "composition-probe-original-former-allocation-math")
        return result
