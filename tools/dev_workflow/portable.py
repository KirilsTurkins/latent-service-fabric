"""Explicit native component testing, using the same scenario assertions as Linux."""
from __future__ import annotations

import base64
from contextlib import ExitStack
import os
from pathlib import Path
import platform
import re
import time

from . import bundle, paths, process, project, scenarios, state
from .common import HOST_ABI, decode, digest, encode, members, require

SUPPORTED = scenarios.PORTABLE


def fixture_inputs(source: Path, fixtures: list[dict]) -> dict | None:
    selected = {}
    for fixture in fixtures:
        if fixture["kind"] not in {"test-adapter", "controlled-peer"} or "configuration" not in fixture:
            return None
        raw = paths.read(source, fixture["configuration"], 256 * 1024)
        require(digest(raw) == fixture["identity"], "portable-fixture-identity")
        value = decode(raw, 256 * 1024)
        require(isinstance(value, dict) and value and value.keys() <= {"clock", "entropy", "metrics", "http"},
                "portable-fixture-configuration")
        require(not selected.keys() & value.keys(), "duplicate-portable-provider-fixture")
        require((fixture["kind"] == "controlled-peer") == (set(value) == {"http"}), "portable-fixture-kind")
        if "clock" in value:
            clock = members(value["clock"], {"monotonicNanos", "wallUnixMillis"})
            require(all(isinstance(reading, str) and re.fullmatch(r"0|[1-9][0-9]{0,19}", reading)
                        and int(reading) <= 18446744073709551615 for reading in clock.values()),
                    "invalid-guest-clock-fixture")
        selected.update(value)
    return selected


def execute(executable: Path, source: Path, artifacts: Path, descriptor: dict,
            selection: list[str], *, host_identity: dict) -> dict:
    deadline = time.monotonic() + 300
    project.validate(descriptor)
    documents = [scenarios.validate(decode(paths.read(source, name)), "portable")
                 for name in descriptor["scenarios"]]
    document = scenarios.validate({"schemaVersion": "latent.dev.scenarios.v1",
        "scenarios": [case for item in documents for case in item["scenarios"]]}, "portable")
    require(set(selection) <= {case["id"] for case in document["scenarios"]}, "unknown-test-selection")
    content = {name: paths.read(artifacts, descriptor["artifacts"][name])
               for name in ("component", "capsule", "contracts")}
    manifest = decode(content["capsule"])
    require(manifest.get("component", {}).get("digest") == digest(content["component"]), "portable-component-identity")
    ceiling = manifest["execution"]["limits"]
    fixtures_by_case, initialized = {}, set()
    for case in document["scenarios"]:
        if selection and case["id"] not in selection:
            continue
        require(case["service"] == descriptor["service"], "scenario-service-outside-test-project")
        # Unsupported requirements never reach the guest and still fail required
        # coverage in the common report. No fixture is implicitly substituted.
        if set(case["requires"]) - SUPPORTED:
            continue
        fixtures = fixture_inputs(source, case["fixtures"])
        if fixtures is None:
            continue
        initialized.update(item["id"] for item in case["fixtures"])
        fixtures_by_case[case["id"]] = fixtures
    prepared, unsupported = scenarios.prepare(document, source, "portable", selection,
        supported=SUPPORTED, initialized_fixtures=initialized, execution_controls=True)
    groups = []
    for case, input_bytes, _expected in prepared:
        if case["id"] in unsupported:
            continue
        fixtures = fixtures_by_case[case["id"]]
        execution = case.get("execution", {"grants": []})
        require(case["timeoutMillis"] <= 5000, "portable-timeout-limit")
        # A scenario deadline bounds the test. Its default invocation budget
        # must also honor a capsule declaring a smaller wall-time ceiling.
        wall = ceiling.get("wallTimeLimitMillis")
        timeout = case["timeoutMillis"] if wall is None else min(case["timeoutMillis"], wall)
        if not groups or groups[-1][0] != fixtures:
            groups.append((fixtures, []))
            require(len(groups) <= 8, "portable-fixture-group-limit")
        groups[-1][1].append({"id": case["id"], "service": case["service"], "contract": case["contract"],
            "function": case["function"], "input": base64.b64encode(input_bytes).decode(),
            "grants": execution["grants"], "deniedCapabilities": execution.get("deniedCapabilities", []),
            "fuel": execution.get("fuel", str(ceiling["cpuFuel"])),
            "memoryBytes": execution.get("memoryBytes", str(ceiling["memoryBytes"])),
            "timeoutMillis": timeout, "cancelBeforeStart": execution.get("cancelBeforeStart", False)})
    if any(item["required"] for item in unsupported.values()):
        groups = []
    results, runs = {}, []
    for fixtures, calls in groups:
        request = {"schemaVersion": "latent.dev.portable-request.v1", "environment": "portable",
            "runtimeProfile": {"java": "java-linear-v1", "dotnet": "dotnet-native-aot-v1",
                               "typescript": "typescript-spidermonkey-v1"}.get(descriptor["language"], "standard-v1"),
            "controlledDevelopment": True, "component": base64.b64encode(content["component"]).decode(),
            "manifest": base64.b64encode(content["capsule"]).decode(),
            "contracts": base64.b64encode(content["contracts"]).decode(), "calls": calls, "fixtures": fixtures}
        raw = encode(request)
        require(len(raw) <= 32 * 1024 * 1024, "portable-request-byte-limit")
        # Native preparation compiles the embedded language runtime as well as
        # application code. Its finite host allowance is separate from every
        # guest's unchanged activation deadline. All groups share one run bound.
        remaining = deadline - time.monotonic()
        require(remaining > 0, "portable-test-run-deadline")
        completed = process.run([str(executable)], source, stdin=raw,
            timeout=min(remaining, 120 + sum(case["timeoutMillis"] for case in calls) / 1000),
            maximum=4 * 1024 * 1024)
        runtime = decode(completed.stdout, 4 * 1024 * 1024)
        require(completed.returncode == 0 and runtime.get("schemaVersion") == "latent.dev.portable-result.v1"
                and runtime.get("environment") == "portable" and runtime.get("productionNode") is False
                and runtime.get("component") == digest(content["component"])
                and runtime.get("runtimeProfile") == request["runtimeProfile"], "portable-host-rejected-input")
        require(isinstance(runtime.get("results"), list)
                and [item["id"] for item in runtime["results"]] == [item["id"] for item in calls], "portable-result-association")
        require(all(item.get("cleanup") == "reusable" for item in runtime["results"]), "portable-cleanup-unconfirmed")
        results.update({item["id"]: item for item in runtime.pop("results")})
        runs.append(runtime)
    runtime = {"execution": "actual-component-production-wasmtime" if runs else "no-compatible-selected-scenarios", "runs": runs}
    report = scenarios.run_prepared(prepared, unsupported, "portable",
        lambda case, _raw: results[case["id"]],
        {"host": host_identity, "runtime": runtime, "hostAbi": HOST_ABI,
         "artifacts": {name: digest(raw) for name, raw in content.items()},
         "trust": "controlled-development-test", "productionNode": False})
    report["cleanup"] = "owned-native-host-reaped" if groups else "no-native-host-started"
    return report


def run(root: Path, args) -> dict:
    require(args.controlled_development, "portable-controlled-development-consent-required")
    require(args.project is not None and args.artifacts is not None and args.portable_bundle is not None,
            "portable-project-artifacts-and-verified-bundle-required")
    require(os.name == "nt" and platform.machine().lower() in {"amd64", "x86_64"},
            "portable-native-target-not-qualified")
    name = args.portable_bundle
    require(len(name) == 64 and all(c in "0123456789abcdef" for c in name), "bundle-id-required")
    cache = root / "bundles" / name
    selected = bundle.cached(cache)
    bundle.manifest(selected, target="windows-x86_64", version=selected["version"], commit=selected["sourceCommit"])
    require(selected["archive"]["sha256"] == "sha256:" + name, "portable-bundle-identity")
    executable = "bin/latent-portable-test-host.exe"
    require(any(item["path"] == executable and item["executable"] for item in selected["files"]),
            "verified-portable-host-missing")
    workspace = state.workspace(root, args.workspace, create=True)
    with state.lock(workspace), ExitStack() as held:
        for entry in selected["files"]:
            held.enter_context(paths.opened(cache, entry["path"]))
            require(digest(paths.read(cache, entry["path"], bundle.MAX_BUNDLE)) == entry["sha256"],
                    "portable-bundle-modified")
        source, artifacts = args.project.absolute(), args.artifacts.absolute()
        descriptor, _identity = project.load(source)
        report = execute(cache / executable, source, artifacts, descriptor, args.select,
            host_identity={"bundle": name, "sourceCommit": selected["sourceCommit"], "target": selected["target"]})
        state.atomic(workspace, "test-report.json", report)
        return report
