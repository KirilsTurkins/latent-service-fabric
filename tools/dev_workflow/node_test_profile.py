"""Explicit language profile selection for a stopped disposable test workspace."""
from __future__ import annotations

import copy
from pathlib import Path

from tools.guest_runtime_profiles import profiles
from . import blob_fixture, metric_fixture, paths, secret_fixture, state
from .common import decode, digest, encode, require


def scope(descriptor: dict) -> dict:
    return {name: descriptor[name] for name in ("language", "tenant", "service")}


def configuration(original: dict, descriptor: dict, fixtures: dict | None = None, *, root: Path | None = None) -> tuple[dict, dict]:
    require(original["securityProfile"] == "local-experimental-v1", "test-profile-requires-local-installation")
    require(descriptor["tenant"] == "examples" and "providers" not in original,
            "test-profile-will-not-replace-existing-providers")
    selected = dict(profiles(descriptor["language"])) if descriptor["language"] in {"java", "dotnet", "go"} else {}
    value = copy.deepcopy(original)
    if fixtures is not None:
        from . import node_fixtures
        from tools.guest_runtime_profiles import RUNTIME
        require("developmentTest" not in original, "test-profile-will-not-replace-existing-fixtures")
        node_fixtures.validate(fixtures)
        if "clock" in fixtures:
            value["developmentTest"] = node_fixtures.configuration(fixtures)
            selected.update({name: RUNTIME[name] for name in ("clockMonotonic", "clockWall")})
        if "http" in fixtures:
            from . import http_fixture
            require(root is not None, "http-fixture-workspace-required")
            selected["http"] = http_fixture.PROVIDER
        if "blob" in fixtures:
            selected["blob"] = blob_fixture.PROVIDER
        if "secrets" in fixtures:
            require(root is not None, "secret-fixture-workspace-required")
            selected["secrets"] = secret_fixture.PROVIDER
        if "metrics" in fixtures:
            selected["metrics"] = metric_fixture.PROVIDER
    value["budgetProfile"] = {"mode": "phase3", "maximumOutboundRequests": 8,
                              "maximumBlobReadBytes": 65536, "maximumBlobWriteBytes": 65536}
    value["capabilityPolicies"] = {"formatVersion": 1, "maximumControlJobs": 2,
        "store": {"maximumRecords": 64, "maximumOutcomes": 128, "maximumCatalogBytes": 4194304,
                  "maximumReadOwners": 64, "maximumPageRecords": 16}}
    value["cells"] = [{"class": "standard", "capacity": 1, "queueCapacity": 2,
        "maximumMemoryBytes": 134217728 if descriptor["language"] in {"dotnet", "typescript"} else 67108864}]
    value.setdefault("execution", {}).update(maximumWallTimeMillis=120000, maximumCpuFuel=10000000000)
    value.setdefault("engine", {})["javaGuest"] = descriptor["language"] == "java"
    value["audit"].update(records=4096, diskBytes=67108864)
    if selected:
        value["providers"] = {"formatVersion": 1, "bindings": []}
        for name, (capability, _profile, _operation, _kind) in selected.items():
            provider_service = {"blob": blob_fixture.SERVICE, "secrets": secret_fixture.SERVICE,
                                "metrics": metric_fixture.SERVICE}.get(name, "runtime-host")
            value["providers"][name] = {"identity": {"id": name, "tenant": descriptor["tenant"],
                "service": provider_service, "epoch": 1}}
            if name == "http":
                value["providers"][name].update(http_fixture.installation(root, fixtures["http"]))
            if name == "blob":
                value["providers"][name].update(blob_fixture.validate(fixtures["blob"]))
            if name == "secrets":
                value["providers"][name].update(secret_fixture.installation(root, fixtures["secrets"]))
            if name == "metrics":
                value["providers"][name]["descriptors"] = metric_fixture.validate(fixtures["metrics"])
            value["providers"]["bindings"].append({"name": "dev-" + name,
                "tenant": descriptor["tenant"], "consumerService": descriptor["service"],
                "providerService": provider_service, "contract": capability, "providerBinding": "dev-" + name})
    return value, {name: list(profile) for name, profile in selected.items()}


def prepare(root: Path, descriptor: dict, *, consent: bool, admission: str = "trusted-local",
            tool_root: Path | None = None, fixtures: dict | None = None) -> dict:
    require(consent is True and root.name.startswith("test-"), "explicit-disposable-test-fixture-consent-required")
    require(admission in {"trusted-local", "signed-fixture"}, "explicit-test-admission-required")
    require(admission == "signed-fixture" or descriptor["language"] not in {"java", "dotnet", "go"},
            "managed-runtime-bindings-require-signed-fixture-package")
    if fixtures is not None:
        from . import node_fixtures
        node_fixtures.validate(fixtures)
        require(admission == "signed-fixture", "node-fixtures-require-signed-test-admission")
    lifecycle = state.load(root, "lifecycle.json") if (root / "lifecycle.json").exists() else {"state": "stopped"}
    require(lifecycle["state"] == "stopped", "stop-test-node-before-profile-configuration")
    require(not (root / "last-deployment.json").exists(), "prepare-test-profile-before-first-deployment")
    if (root / "operations.json").exists():
        require(state.load(root, "operations.json")["pending"] is None, "recover-original-operation-before-test-setup")
    runtime = root / "runtime"
    with state.lock(root, "supervisor.lock"), state.lock(runtime, "run.lock"):
        signing = None
        if admission == "signed-fixture":
            from . import node_test_signing
            require(tool_root is not None, "pinned-test-signer-tool-root-required")
            signing = node_test_signing.prepare(root, descriptor, tool_root)
        raw = paths.read(runtime / "config", "node.json")
        if (root / "test-profile-plan.json").exists():
            plan = state.load(root, "test-profile-plan.json")
            require(plan["scope"] == scope(descriptor) and plan["admission"] == admission,
                    "test-profile-is-owned-by-another-project")
            require(plan.get("fixtures") == fixtures, "test-fixture-selection-changed")
            require(digest(raw) == plan["after"] or "configuration" in plan and digest(raw) == plan["before"],
                    "test-node-configuration-changed")
        else:
            original = decode(raw)
            require(original["dataDirectory"] == str(runtime / "data"), "test-node-data-owner")
            value, selected = configuration(original, descriptor, fixtures, root=root)
            if signing is not None:
                value["supplyChain"] = {"mode": "enforced", "policyFile": str(root / "test-signing/policy.json")}
            fixture_check = node_fixtures.check_configuration(root, value) if fixtures is not None else None
            plan = {"scope": scope(descriptor), "before": digest(raw), "after": digest(encode(value)),
                    "configuration": value, "providers": selected, "profile": value["securityProfile"],
                    "admission": admission, "signing": signing, "fixtures": fixtures, "fixtureCheck": fixture_check}
            # This plan contains the existing private node configuration and
            # stays in the private workspace. It is never included in a report.
            state.atomic(root, "test-profile-plan.json", plan)
        if digest(raw) != plan["after"]:
            state.atomic(runtime / "config", "node.json", plan["configuration"])
        receipt = {"scope": plan["scope"], "configurationSha256": plan["after"],
            "providers": plan["providers"], "profile": plan["profile"],
            "admission": plan["admission"], "signing": plan["signing"],
            "capabilitiesGranted": False, "state": "configured-node-stopped"}
        if fixtures is not None:
            receipt.update(fixtures=fixtures, fixtureCheck=plan["fixtureCheck"])
        state.atomic(root, "test-profile.json", receipt)
        # Recovery no longer needs another copy of the node's private tokens.
        state.atomic(root, "test-profile-plan.json", {key: value for key, value in plan.items() if key != "configuration"})
        return receipt


def installed(root: Path, descriptor: dict, status: dict) -> dict:
    profile = state.load(root, "test-profile.json")
    require(profile["scope"] == scope(descriptor) and status.get("state") == "ready", "test-profile-scope-or-readiness")
    require(digest(paths.read(root / "runtime/config", "node.json")) == profile["configurationSha256"],
            "test-node-configuration-changed")
    actual = status.get("providers", [])
    require(len(actual) == len(profile["providers"]), "test-provider-installation-count")
    result = {}
    for name, (capability, provider_profile, _operation, _kind) in profile["providers"].items():
        rows = [entry for entry in actual if entry.get("id") == name]
        require(len(rows) == 1, "test-provider-installation-identity")
        entry = rows[0]
        provider_service = {"blob": blob_fixture.SERVICE, "secrets": secret_fixture.SERVICE,
                            "metrics": metric_fixture.SERVICE}.get(name, "runtime-host")
        require(entry.get("tenant") == descriptor["tenant"] and entry.get("service") == provider_service
                and entry.get("capability") == capability and entry.get("profile") == provider_profile
                and entry.get("configurationEpoch") == "1", "test-provider-installation-scope")
        from .common import sha
        sha(entry.get("configurationDigest"))
        result[name] = entry
    return result
