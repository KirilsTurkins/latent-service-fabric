"""Composition identity, changing authority, safe diagnostics and no dispatch."""
from __future__ import annotations

import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.dev_workflow import preflight
from tools.dev_workflow.common import DevError, encode
from tools.dev_workflow.preflight_operation import using_client

ROOT = Path(__file__).resolve().parents[2]
MATH = "latent:math/arithmetic@0.1.0"
SERVICE = "latent:service/call@0.1.0"
ENGINE = "blake3:" + "a" * 64


def sha(character):
    return "sha256:" + character * 64


def component(identifier="domain", *, imported=False):
    return {"id": identifier, "packageDigest": sha("1"), "componentDigest": sha("2"), "releaseDigest": sha("2"),
            "contractMetadataDigest": sha("3"), "language": "java", "witShape": "nested-values-v1", "publicationKind": "capsule",
            "target": {"service": "examples/math", "route": "math-route", "revision": "revision-v1:" + sha("4"),
                       "publicationId": "publication:" + sha("5"), "deploymentId": "math-deployment", "deploymentGeneration": "4", "contract": MATH, "function": "add"},
            "imports": [SERVICE] if imported else [], "exports": [{"contract": MATH, "functions": ["add"]}],
            "budget": {name: "100" for name in preflight.BUDGETS}, "engineConfigurationDigest": ENGINE}


def composition(*, imported=False):
    result = {"schemaVersion": preflight.FORMAT, "tenant": "examples", "nodeProfile": {"id": "http-java-v1", "javaGuest": True,
              "maximumWirePayloadBytes": "2097152", "maximumRequestBodyBytes": "65536", "maximumResponseBodyBytes": "65536"},
              "components": [component(imported=imported)], "triggers": [{"kind": "typed", "component": "domain", "contract": MATH, "function": "add"}],
              "serviceEdges": [], "providers": [], "policies": []}
    if imported:
        result["policies"] = [{"id": "service-policy", "digest": sha("6")}]
        result["providers"] = [{"contract": SERVICE, "providerProfile": "local-service-v1", "configurationDigest": sha("7"),
                                "bindingId": "service-binding", "bindingDigest": sha("8"), "policyIds": ["service-policy"], "configurationEpoch": "1"}]
    return result


def observed(selected, value):
    imports = selected["imports"]
    exported = [{"contract": row["contract"], "function": function} for row in selected["exports"] for function in row["functions"]]
    prepared = {"state": 1, "stateName": "ready", "diagnostic": None, "profile": 1, "profileName": "wasmtime-service-values-v1",
                "engineVersion": "wasmtime-45.0.0", "engineConfigurationDigest": ENGINE, "targetTriple": "x86_64-unknown-linux-gnu",
                "cpuFeatureSet": "baseline", "sealedMetadataFingerprint": "c" * 64, "importCount": str(len(imports)),
                "functionCount": str(len(exported)), "hostcallFuel": "1048576", "maximumLiftedBytes": "33554432", "maximumTypeNodes": "1024",
                "declaredBudget": {name: int(number) if name in preflight.U32_BUDGETS else number
                                   for name, number in selected["budget"].items()}, "imports": imports, "typeImports": [], "exports": exported}
    dependencies = [{"capability": row["contract"], "state": "configured-current", "policyIdentityDigest": "d" * 64,
                     "providerConfigurationEpoch": row.get("configurationEpoch", "1"),
                     "binding": {"id": row["bindingId"], "digest": row["bindingDigest"], "revision": "1"},
                     "policies": [{**policy, "revision": "1"} for policy in value["policies"] if policy["id"] in row["policyIds"]],
                     "providerProfile": row["providerProfile"], "configurationDigest": row["configurationDigest"]}
                    for row in value["providers"] if row["contract"] in imports]
    candidate = {"deploymentId": selected["target"]["deploymentId"], "deploymentGeneration": "4", "revisionId": selected["target"]["revision"],
                 "componentDigest": selected["componentDigest"], "publication": {"tenant": value["tenant"], "id": selected["target"]["publicationId"]},
                 "requestedPublication": {"tenant": value["tenant"], "id": selected["target"]["publicationId"]}, "packageDigest": selected["packageDigest"],
                 "publicationGeneration": "3", "routingWeight": 10000, "exportCompatible": True, "httpCompatible": False,
                 "eligible": True, "reasons": [1], "reasonNames": ["current"], "dependencies": dependencies,
                 "preparation": prepared, "publicationKind": "capsule", "httpBindings": []}
    return {"schemaVersion": "latent.cli.result.v1", "outcomeKnown": True, "category": "success", "data": {
        "schemaVersion": 1, "tenant": value["tenant"], **{name: selected["target"][name] for name in ("service", "contract", "function", "route")},
        "state": 1, "stateName": "coherent", "catalogTransaction": "5", "routeGeneration": "4", "bindingGeneration": "4",
        "policyStoreGeneration": "7", "candidates": [candidate], "selectedRevisionId": None, "liveGrantsChecked": False}}


def codes(result, state=None):
    return {row["code"] for row in result["checks"] if state is None or row["state"] == state}


class CompositionPreflight(unittest.TestCase):
    def test_structural_evidence_is_never_preparation_or_execution(self):
        result = preflight.run(composition())
        self.assertTrue(result["passed"])
        self.assertFalse(result["fullyChecked"])
        self.assertEqual(result["observation"]["state"], "not-checked")
        for key in ("executionAuthorized", "grantCreated", "reservationCreated", "trafficEnabled"):
            self.assertFalse(result[key])
        self.assertIn("separate-controlled-qualification-required", codes(result, "not-checked"))

    def test_full_width_budget_and_reduced_declared_child_shares(self):
        value = composition()
        parent = value["components"][0]
        child = copy.deepcopy(parent)
        child["id"] = "child"
        child["target"]["service"] = "examples/child"
        child["budget"]["cpuFuel"] = "18446744073709551615"
        parent["budget"]["cpuFuel"] = "400"
        parent["budget"]["wallTimeLimitMillis"] = None
        child["budget"]["wallTimeLimitMillis"] = "5000"
        value["components"].append(child)
        value["serviceEdges"] = [{"from": "domain", "to": "child", "contract": MATH, "function": "add",
                                 "declaredGrantDigest": sha("9"), "requestBudget": {"cpuFuel": "250", "wallTimeLimitMillis": "2000"}}]
        hop = preflight.run(value)["serviceHops"][0]
        self.assertEqual(hop["maximumDeclaredShare"]["cpuFuel"], "250")
        self.assertEqual(hop["maximumDeclaredShare"]["wallTimeLimitMillis"], "2000")
        self.assertEqual(hop["remainingShare"], "invocation-dependent")
        self.assertEqual(hop["principal"], "host-derived-service")
        self.assertEqual(hop["callerService"], "examples/math")
        self.assertFalse(hop["authorizationCreated"])
        parent["budget"]["cpuFuel"] = "18446744073709551616"
        with self.assertRaises(DevError):
            preflight.run(value)

    def test_unknown_version_duplicate_selection_and_unsafe_paths_reject(self):
        changes = [lambda value: value.update(schemaVersion="latent.composition.v99"),
                   lambda value: value["components"].append(copy.deepcopy(value["components"][0])),
                   lambda value: value["components"][0].update(componentPath="../private/key"),
                   lambda value: value["components"][0]["budget"].update(cpuFuel=100),
                   lambda value: value["components"][0].update(headerNames=["x-\u2603"])]
        for change in changes:
            value = composition()
            change(value)
            with self.subTest(change=change), self.assertRaises(DevError):
                preflight.run(value)
        for field in ("triggers", "providers", "policies"):
            value = composition(imported=True)
            value[field].append(copy.deepcopy(value[field][0]))
            with self.subTest(field=field), self.assertRaises(DevError):
                preflight.run(value)
        value = composition(imported=True)
        extra = copy.deepcopy(value["providers"][0])
        extra["bindingId"] = "other-binding"
        value["providers"].append(extra)
        with self.assertRaisesRegex(DevError, "preflight-ambiguous-provider-contract"):
            preflight.run(value)
        value = composition(imported=True)
        value["providers"][0]["policyIds"] = ["missing-policy"]
        with self.assertRaisesRegex(DevError, "preflight-provider-policy-selection"):
            preflight.run(value)

    def test_payload_trigger_export_and_context_rejections_are_distinct(self):
        bounded = composition()
        bounded["components"][0]["target"].update(contract=preflight.WEB_CONTRACT, function="handle")
        bounded["components"][0]["exports"] = [{"contract": preflight.WEB_CONTRACT, "functions": ["handle"]}]
        bounded["triggers"] = [{"kind": "http", "component": "domain", "contract": preflight.WEB_CONTRACT, "function": "handle"}]
        bounded["nodeProfile"]["maximumResponseBodyBytes"] = "262144"
        accepted = preflight.run(bounded)
        self.assertTrue(accepted["passed"])
        self.assertIn("buffered-http-body-profile", codes(accepted, "passed"))
        for field, maximum in (("maximumRequestBodyBytes", 65536), ("maximumResponseBodyBytes", 262144)):
            too_large = copy.deepcopy(bounded)
            too_large["nodeProfile"][field] = str(maximum + 1)
            with self.subTest(field=field):
                rejected = preflight.run(too_large)
                self.assertFalse(rejected["passed"])
                self.assertIn("buffered-http-body-profile", codes(rejected, "unsupported"))
        value = composition()
        value["triggers"] = [{"kind": "http", "component": "domain", "contract": preflight.WEB_CONTRACT, "function": "handle"}]
        value["nodeProfile"]["maximumWirePayloadBytes"] = "1048576"
        result = preflight.run(value)
        self.assertIn("trigger-contract-publication-match", codes(result, "failed"))
        self.assertIn("http-minimum-wire-payload", codes(result, "failed"))
        value = composition()
        value["components"][0]["imports"] = [preflight.CONTEXT_CONTRACT]
        result = preflight.run(value)
        row = next(row for row in result["checks"] if row["code"] == "ordinary-context-provider-not-installed")
        self.assertEqual((row["state"], row["diagnostic"]), ("unsupported", {"schemaVersion": 1, "stage": 4, "reason": 6}))

    def test_nonjava_resource_shapes_stay_untested(self):
        value = composition()
        value["components"][0].update(language="rust", witShape="resources")
        result = preflight.run(value)
        self.assertIn("shape-requires-language-owned-qualification", codes(result, "untested"))
        self.assertNotIn("shape-requires-language-owned-qualification", codes(result, "unsupported"))

    def test_static_selection_has_assets_and_no_guest_identity(self):
        value = composition()
        selected = value["components"][0]
        for name in ("componentDigest", "releaseDigest", "contractMetadataDigest", "engineConfigurationDigest", "budget"):
            del selected[name]
        selected["target"] = {"publicationId": selected["target"]["publicationId"], "webGeneration": "1"}
        selected.update(language="static", witShape="static-assets-v1", publicationKind="static-site", assetsDigest=sha("a"),
                        webManifestDigest=sha("b"), exports=[])
        value["triggers"] = [{"kind": "static", "component": "domain"}]
        result = preflight.run(value)
        self.assertTrue(result["passed"])
        selected["componentDigest"] = sha("a")
        with self.assertRaises(DevError):
            preflight.run(value)

    def test_authorized_preparation_uses_actual_surface_and_exact_profile(self):
        value = composition(imported=True)
        result = preflight.run(value, observe=lambda selected, **_: observed(selected, value))
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["observation"]["state"], "coherent")
        self.assertEqual(result["observation"]["engineConfigurationDigests"], [ENGINE])
        self.assertIn("actual-component-contract-surface", codes(result, "passed"))
        self.assertIn("selected-provider-binding-policy-current", codes(result, "passed"))
        self.assertFalse(result["fullyChecked"])
        self.assertFalse(result["observation"]["liveGrantsChecked"])
        selected = value["components"][0]
        shared_types = "examples:domain/types@1.0.0"
        selected["imports"].append(shared_types)
        def typed_observation(component, **_):
            reply = observed(component, value)
            prepared = reply["data"]["candidates"][0]["preparation"]
            prepared["imports"] = [SERVICE]
            prepared["typeImports"] = [shared_types]
            return reply
        result = preflight.run(value, observe=typed_observation)
        self.assertTrue(result["passed"], result)
        self.assertIn("actual-component-contract-surface", codes(result, "passed"))
        self.assertNotIn("required-provider-not-selected", codes(result, "failed"))

    def test_changed_catalog_policy_provider_or_profile_refuses_mixed_positive(self):
        for change in (lambda data: data.update(catalogTransaction="6"),
                       lambda data: data.update(policyStoreGeneration="8"),
                       lambda data: data["candidates"][0]["dependencies"][0].update(configurationDigest=sha("b")),
                       lambda data: data["candidates"][0]["preparation"].update(engineConfigurationDigest="blake3:" + "b" * 64)):
            value = composition(imported=True)
            calls = 0
            def observe(selected, **_):
                nonlocal calls
                reply = observed(selected, value)
                calls += 1
                if calls == 2:
                    change(reply["data"])
                return reply
            result = preflight.run(value, observe=observe)
            with self.subTest(change=change):
                self.assertFalse(result["passed"])
                self.assertEqual(result["observation"]["state"], "changed")
                self.assertNotIn("selected-component-preparation", codes(result, "passed"))

    def test_stale_publication_package_and_actual_surface_fail(self):
        changes = [lambda row: row.update(publication={"tenant": "examples", "id": "publication:" + sha("b")}),
                   lambda row: row.update(deploymentGeneration="5"),
                   lambda row: row.update(packageDigest=sha("b")),
                   lambda row: row["preparation"].update(exports=[{"contract": MATH, "function": "subtract"}])]
        for change in changes:
            value = composition()
            def observe(selected, **_):
                reply = observed(selected, value)
                change(reply["data"]["candidates"][0])
                return reply
            with self.subTest(change=change):
                self.assertFalse(preflight.run(value, observe=observe)["passed"])

    def test_missing_or_changed_provider_and_current_grant_denial_fail(self):
        for change in (lambda row: row["dependencies"][0].update(state="policy-changed-or-revoked"),
                       lambda row: row["dependencies"][0].update(configurationDigest=sha("b")),
                       lambda row: row.update(dependencies=[]),
                       lambda row: row.update(eligible=False, reasons=[5])):
            value = composition(imported=True)
            def observe(selected, **_):
                reply = observed(selected, value)
                change(reply["data"]["candidates"][0])
                return reply
            with self.subTest(change=change):
                self.assertFalse(preflight.run(value, observe=observe)["passed"])

    def test_former_profile_specific_numeric_producer_diagnostic_survives(self):
        value = composition()
        details = {"schemaVersion": 1, "stage": 3, "reason": 1, "profile": 1, "profileDigest": "a" * 64,
                   "configuredBound": "67108864", "calculatedRequirement": "159384064", "fixedBytes": "512",
                   "liftingFuel": "2097152", "liftMultiplier": "76"}
        def observe(selected, **_):
            reply = observed(selected, value)
            reply["data"]["candidates"][0]["preparation"].update(state=2, stateName="rejected", diagnostic=details)
            return reply
        result = preflight.run(value, observe=observe)
        self.assertFalse(result["passed"])
        row = next(row for row in result["checks"] if row["code"] == "selected-component-preparation")
        self.assertEqual(row["diagnostic"], details)
        self.assertIn("exact-engine-configuration-identity", codes(result, "passed"))

    def test_hostile_diagnostic_or_foreign_owner_never_echoes_payload(self):
        for change in (lambda data: data.update(tenant="another-tenant"),
                       lambda data: data["candidates"][0]["preparation"].update(exports=[
                           {"contract": MATH, "function": "export" + str(index)} for index in range(129)]),
                       lambda data: data["candidates"][0]["preparation"].update(diagnostic={"schemaVersion": 1, "stage": 3, "reason": 1, "payload": "PRIVATE_CANARY"})):
            value = composition()
            def observe(selected, **_):
                reply = observed(selected, value)
                change(reply["data"])
                return reply
            result = preflight.run(value, observe=observe)
            self.assertFalse(result["passed"])
            self.assertNotIn(b"PRIVATE_CANARY", encode(result))
            self.assertNotIn(b"another-tenant", encode(result))

    def test_operator_dispatch_is_bounded_read_only_and_explicit_tenant(self):
        value = composition()
        class Operator:
            calls = []
            def call(self, *arguments, **_):
                self.calls.append(arguments)
                return observed(value["components"][0], value)
        operator = Operator()
        result = using_client(value, operator)
        self.assertTrue(result["passed"])
        self.assertEqual(len(operator.calls), 2)
        for arguments in operator.calls:
            self.assertEqual(arguments[2:6], ("--tenant", "examples", "route", "target"))
            self.assertIn("--include-preparation", arguments)
            self.assertNotIn("invoke", arguments)
            self.assertNotIn("apply", arguments)

    def test_frontend_structural_command_creates_no_controller_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            selected = directory / "composition.json"
            selected.write_bytes(encode(composition()))
            owned_state = directory / "must-remain-absent"
            reply = subprocess.run([sys.executable, str(ROOT / "tools/latent_dev.py"), "--state-root", str(owned_state),
                                    "dev", "preflight", "--input", str(selected), "--output", "human"],
                                   cwd=directory, capture_output=True, timeout=15)
            self.assertEqual(reply.returncode, 0, reply.stdout + reply.stderr)
            self.assertIn(b"authoritative-preparation: not-checked", reply.stdout)
            self.assertFalse(owned_state.exists())


if __name__ == "__main__":
    unittest.main()
