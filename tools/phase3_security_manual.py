"""Reuse maintained fixture exporters and real-node workflow owners in process."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import time

from tools.phase3_security_artifacts import file_identity, require, tree_identity, unique_object


def validate_workflow(report: dict, name: str, schema: str) -> dict:
    require(isinstance(report, dict) and report.get("schemaVersion") == schema, "workflow-receipt")
    shutdown_count = {"publication": 3, "security-profile": 2, "provider-management": 2, "angular-t1": 2}.get(name)
    require(shutdown_count is not None, "workflow-name")
    if name == "provider-management":
        require(report.get("grantsRevoked") is True
                and report.get("selectedRevisionPreservedAcrossRestart") is True
                and report.get("angularT1Qualified") is False
                and report.get("upstream") == {"requests": 4, "authorized": 4, "unexpected": 0}
                and len(report.get("activations", [])) == 9, "provider-workflow-proof")
    else:
        require(report.get("passed") is True and report.get("temporaryOutputsRemoved") is True,
                "workflow-receipt")
    qualification = angular_qualification(report) if name == "angular-t1" else {}
    shutdown = report.get("shutdown")
    require(isinstance(shutdown, list) and len(shutdown) == shutdown_count, "workflow-shutdown-count")
    for stopped in shutdown:
        require(stopped.get("reaped") is True and stopped.get("record", {}).get("clean") is True
                and stopped["record"].get("event") == "stopped"
                and stopped["record"].get("report", {}).get("clean") is True, "workflow-owner-retained")
    encoded = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    require(len(encoded) <= 128 * 1024, "workflow-receipt-limit")
    return {"id": name, "schema": schema, "passed": True,
            "receiptSha256": hashlib.sha256(encoded).hexdigest(), "nodeShutdowns": len(shutdown),
            **({"qualification": qualification} if qualification else {})}


def angular_qualification(report: dict) -> dict:
    profile = report.get("profile")
    require(isinstance(profile, dict) and profile.get("profile") == "external-capsule-v1"
            and profile.get("threatClass") == "T1" and profile.get("admission") == "enforced"
            and profile.get("protectedCredentialFile") is True
            and profile.get("compiler") == "isolated-aot-compiler-v1"
            and profile.get("authenticatedNativeLoading") is True, "angular-t1-profile")
    observation = report.get("buildObservationDigest")
    require(report.get("actualAngularBuild") is True and report.get("reproducibility") == "not-checked"
            and isinstance(observation, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", observation)
            and report.get("nativeCacheFilesUnchangedOnRestart") is True, "angular-t1-proof")
    cancellations = report.get("cancellations")
    require(isinstance(cancellations, list) and len(cancellations) == 2
            and all(isinstance(item, dict) and item.get("terminal") == "cancelled" for item in cancellations)
            and cancellations[0].get("disconnect") is False and cancellations[1].get("disconnect") is True,
            "angular-t1-cancellation")
    watermark = report.get("preRestartNativeCacheHitHighWatermark")
    hits = report.get("authenticatedNativeCacheHits")
    require(isinstance(watermark, str) and re.fullmatch(r"[0-9]{1,20}", watermark)
            and isinstance(hits, list) and 0 < len(hits) <= 32, "angular-t1-restart-cache")
    for hit in hits:
        sequence = hit.get("sequence") if isinstance(hit, dict) else None
        require(isinstance(sequence, str) and re.fullmatch(r"[0-9]{1,20}", sequence)
                and int(sequence) > int(watermark), "angular-t1-restart-cache")
    return {"profile": profile["profile"], "buildObservationDigest": observation,
            "preRestartNativeCacheHitHighWatermark": watermark, "authenticatedNativeCacheHits": hits,
            "cancelledActivations": len(cancellations)}


def inputs(args, runner, directory: Path) -> tuple[dict[str, str], dict]:
    require(args.container_owner is not None, "manual-enclosing-container-required")
    required = ("cli", "node", "compiler", "guest_capsules", "web_component",
                "browser_node", "browser_chrome", "browser_toolchain", "angular_build", "angular_compiler")
    paths = {}
    identities = {}
    for name in required:
        value = getattr(args, name)
        require(value is not None, "missing-manual-prerequisite")
        path = value.resolve(strict=True)
        paths[name] = path
        setattr(args, name, path)
        if name == "guest_capsules":
            require((path / "BUILD-COMPLETE.json").is_file(), "guest-build-incomplete")
            identities[name] = tree_identity(path, runner.deadline)
        elif name == "angular_build":
            require((path / "observation.json").is_file() and (path / "package").is_dir(),
                    "angular-build-incomplete")
            identities[name] = tree_identity(path, runner.deadline)
        elif name == "browser_toolchain":
            identities[name] = file_identity(path / "package-lock.json", runner.deadline)
            require((path / "node_modules/playwright-core/package.json").is_file(),
                    "browser-toolchain-not-installed")
        else:
            identities[name] = file_identity(path, runner.deadline)
    node_version = runner.command([str(paths["browser_node"]), "--version"], maximum=4096)
    require(node_version.stdout.strip() == b"v24.19.0", "browser-node-version")
    chrome = runner.command([str(paths["browser_chrome"]), "--version"], maximum=4096)
    version = chrome.stdout.decode("ascii", errors="strict").strip()
    require(0 < len(version) <= 128 and all(32 <= ord(character) < 127 for character in version),
            "browser-version")
    identities["browserVersion"] = version
    identities["browserOsSandboxDisabled"] = True
    identities["cargoCompiler"] = file_identity(runner.repo / "target/debug/latent-aot-compiler", runner.deadline)
    environment = {
        "LSF_OPERATOR_FIXTURE_ROOT": str(directory / "operator"),
        "LSF_PHASE3_WORKFLOW_FIXTURE_ROOT": str(directory / "provider"),
        "LSF_GUEST_CAPSULES": str(paths["guest_capsules"]),
        "LSF_AOT_COMPILER": str(paths["compiler"]),
        "LSF_WEB_COMPONENT": str(paths["web_component"]),
        "LSF_BROWSER_BUILD": str(directory / "browser"),
        "LSF_BROWSER_NODE": str(paths["browser_node"]),
        "LSF_BROWSER_CHROME": str(paths["browser_chrome"]),
        "LSF_BROWSER_TOOLCHAIN": str(paths["browser_toolchain"]),
        "LSF_ANGULAR_BUILD_DIR": str(paths["angular_build"]),
        "LSF_ANGULAR_T1_FIXTURE_ROOT": str(directory / "angular"),
    }
    built = runner.command([str(paths["browser_node"]), "tools/browser-boundary/build.mjs",
                            str(paths["browser_toolchain"]), str(directory / "browser")], timeout=180)
    report = json.loads(built.stdout)
    require(report == {"angular": "22.1.6", "built": True, "transferredSecrets": False,
                       "sourceSeparated": True}, "browser-build-receipt")
    return environment, identities


def verify_inputs(args, runner, identities: dict) -> None:
    for name in ("cli", "node", "compiler", "web_component", "browser_node", "browser_chrome", "angular_compiler"):
        require(file_identity(getattr(args, name), runner.deadline) == identities[name], "manual-input-changed")
    require(tree_identity(args.guest_capsules, runner.deadline) == identities["guest_capsules"],
            "guest-fixture-changed")
    require(tree_identity(args.angular_build, runner.deadline) == identities["angular_build"],
            "angular-build-changed")
    require(file_identity(args.browser_toolchain / "package-lock.json", runner.deadline)
            == identities["browser_toolchain"], "browser-lock-changed")
    require(file_identity(runner.repo / "target/debug/latent-aot-compiler", runner.deadline)
            == identities["cargoCompiler"], "cargo-compiler-changed")


def browser_output(directory: Path, deadline: float, *, application: bool = False) -> bytes:
    path = directory / "browser" / ("browser-application-receipt.json" if application else "browser-receipt.json")
    identity = file_identity(path, deadline, 4096)
    with path.open("rb") as source:
        raw = source.read(4097)
    require(len(raw) == identity["bytes"] and hashlib.sha256(raw).hexdigest() == identity["sha256"],
            "browser-receipt-changed")
    report = json.loads(raw, object_pairs_hook=unique_object)
    observed = ("liveSharedIngress", "controlledNodeSsr", "originalDomReused", "navigationHydrated",
                "escapedDataRoundTrip", "inlineAndRemoteScriptsBlocked", "baseOverrideBlocked",
                "wrongScriptMimeBlocked", "sameOriginPostReachedMethodPolicy")
    public = ("publicApplicationQualified", "applicationComponentInvoked", "managementRpcAbsent",
              "browserFetchCredentialsOmitted", "cookiesDoNotAuthenticate")
    require(isinstance(report, dict) and set(report) == {*observed, *public, "browser", "componentRenderClaimed", "errors"},
            "browser-receipt-fields")
    require(all(report[name] is True for name in observed) and report["componentRenderClaimed"] is False
            and all(report[name] is application for name in public)
            and type(report["errors"]) is int and report["errors"] == 0, "browser-receipt-proof")
    require(isinstance(report["browser"], str)
            and re.fullmatch(r"[0-9]{1,5}(?:\.[0-9]{1,6}){3}", report["browser"]) is not None,
            "browser-receipt-version")
    return raw


def workflows(args, runner, directory: Path) -> list[dict]:
    from tools import run_publication_workflow, run_security_profile_workflow
    from tools import run_angular_t1_workflow, run_phase3_management_workflow

    operations = (
        ("publication", run_publication_workflow.run, "latent.publication.workflow.v1", "publication", 180),
        ("security-profile", run_security_profile_workflow.run, "latent.security-profile.workflow.v1", "operator", 180),
        ("provider-management", run_phase3_management_workflow.run,
         "latent.phase3.management.workflow.v1", "provider", 300),
        ("angular-t1", run_angular_t1_workflow.run, "latent.angular.t1.workflow.v1", "angular", 1200),
    )
    results = []
    for name, execute, schema, fixture, maximum in operations:
        runner.current = "workflow:" + name
        require(runner.deadline - time.monotonic() >= maximum + 10, "workflow-budget-unavailable")
        compiler = args.angular_compiler if name == "angular-t1" else args.compiler
        arguments = argparse.Namespace(cli=args.cli, node=args.node, compiler=compiler,
                                       fixture_root=directory / fixture, source_commit=args.source_commit)
        before = tree_identity(arguments.fixture_root, runner.deadline)
        report = execute(arguments)
        if isinstance(report, str):
            report = json.loads(report)
        summary = validate_workflow(report, name, schema)
        require(tree_identity(arguments.fixture_root, runner.deadline) == before, "workflow-fixture-mutated")
        results.append({**summary, "fixture": before})
        runner.validated_workflows.append(name)
    return results


def fixture_identities(directory: Path, deadline: float) -> dict:
    identities = {name: tree_identity(directory / name, deadline)
                  for name in ("operator", "publication", "provider", "browser", "angular")}
    identities["browserObservations"] = json.loads(browser_output(directory, deadline))
    identities["browserApplicationObservations"] = json.loads(browser_output(directory, deadline, application=True))
    return identities
