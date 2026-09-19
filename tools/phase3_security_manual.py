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
    shutdown_count = {"publication": 3, "security-profile": 2, "provider-management": 2}.get(name)
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
    shutdown = report.get("shutdown")
    require(isinstance(shutdown, list) and len(shutdown) == shutdown_count, "workflow-shutdown-count")
    for stopped in shutdown:
        require(stopped.get("reaped") is True and stopped.get("record", {}).get("clean") is True
                and stopped["record"].get("event") == "stopped"
                and stopped["record"].get("report", {}).get("clean") is True, "workflow-owner-retained")
    encoded = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    require(len(encoded) <= 128 * 1024, "workflow-receipt-limit")
    return {"id": name, "schema": schema, "passed": True,
            "receiptSha256": hashlib.sha256(encoded).hexdigest(), "nodeShutdowns": len(shutdown)}


def inputs(args, runner, directory: Path) -> tuple[dict[str, str], dict]:
    require(args.container_owner is not None, "manual-enclosing-container-required")
    required = ("cli", "node", "compiler", "guest_capsules", "web_component",
                "browser_node", "browser_chrome", "browser_toolchain")
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
    }
    built = runner.command([str(paths["browser_node"]), "tools/browser-boundary/build.mjs",
                            str(paths["browser_toolchain"]), str(directory / "browser")], timeout=180)
    report = json.loads(built.stdout)
    require(report == {"angular": "22.1.6", "built": True, "transferredSecrets": False,
                       "sourceSeparated": True}, "browser-build-receipt")
    return environment, identities


def verify_inputs(args, runner, identities: dict) -> None:
    for name in ("cli", "node", "compiler", "web_component", "browser_node", "browser_chrome"):
        require(file_identity(getattr(args, name), runner.deadline) == identities[name], "manual-input-changed")
    require(tree_identity(args.guest_capsules, runner.deadline) == identities["guest_capsules"],
            "guest-fixture-changed")
    require(file_identity(args.browser_toolchain / "package-lock.json", runner.deadline)
            == identities["browser_toolchain"], "browser-lock-changed")
    require(file_identity(runner.repo / "target/debug/latent-aot-compiler", runner.deadline)
            == identities["cargoCompiler"], "cargo-compiler-changed")


def browser_output(directory: Path, deadline: float) -> bytes:
    path = directory / "browser/browser-receipt.json"
    identity = file_identity(path, deadline, 4096)
    with path.open("rb") as source:
        raw = source.read(4097)
    require(len(raw) == identity["bytes"] and hashlib.sha256(raw).hexdigest() == identity["sha256"],
            "browser-receipt-changed")
    report = json.loads(raw, object_pairs_hook=unique_object)
    observed = ("liveSharedIngress", "controlledNodeSsr", "originalDomReused", "navigationHydrated",
                "escapedDataRoundTrip", "inlineAndRemoteScriptsBlocked", "baseOverrideBlocked",
                "wrongScriptMimeBlocked", "sameOriginPostReachedMethodPolicy")
    require(isinstance(report, dict) and set(report) == {*observed, "browser", "componentRenderClaimed", "errors"},
            "browser-receipt-fields")
    require(all(report[name] is True for name in observed) and report["componentRenderClaimed"] is False
            and type(report["errors"]) is int and report["errors"] == 0, "browser-receipt-proof")
    require(isinstance(report["browser"], str)
            and re.fullmatch(r"[0-9]{1,5}(?:\.[0-9]{1,6}){3}", report["browser"]) is not None,
            "browser-receipt-version")
    return raw


def workflows(args, runner, directory: Path) -> list[dict]:
    from tools import run_publication_workflow, run_security_profile_workflow
    from tools import run_phase3_management_workflow

    operations = (
        ("publication", run_publication_workflow.run, "latent.publication.workflow.v1", "publication", 180),
        ("security-profile", run_security_profile_workflow.run, "latent.security-profile.workflow.v1", "operator", 180),
        ("provider-management", run_phase3_management_workflow.run,
         "latent.phase3.management.workflow.v1", "provider", 300),
    )
    results = []
    for name, execute, schema, fixture, maximum in operations:
        runner.current = "workflow:" + name
        require(runner.deadline - time.monotonic() >= maximum + 10, "workflow-budget-unavailable")
        arguments = argparse.Namespace(cli=args.cli, node=args.node, compiler=args.compiler,
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
                  for name in ("operator", "publication", "provider", "browser")}
    identities["browserObservations"] = json.loads(browser_output(directory, deadline))
    return identities
