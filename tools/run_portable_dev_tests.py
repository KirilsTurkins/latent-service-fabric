#!/usr/bin/env python3
"""Run actual maintained Rust components in a native executable, outside the checkout."""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import platform
import shutil
import sys
import tempfile

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.dev_workflow import paths, portable, process
from tools.dev_workflow.common import decode, digest, encode, require

ROOT = Path(__file__).resolve().parents[1]
MEDIA = "application/vnd.latent.wit-values.v1+json"


def call(name, function, raw=b"[]", *, grants=(), fuel="1000000", memory="4194304", timeout=1000, cancel=False):
    return {"id": name, "service": "examples/echo", "contract": "tests:generic/values@0.1.0",
        "function": function, "input": base64.b64encode(raw).decode(), "grants": list(grants),
        "fuel": fuel, "memoryBytes": memory, "timeoutMillis": timeout, "cancelBeforeStart": cancel}


def run(host: Path, cwd: Path, component: bytes, manifest: bytes, contracts: bytes, calls: list, *, fixtures=None) -> dict:
    request = {"schemaVersion": "latent.dev.portable-request.v1", "environment": "portable",
        "controlledDevelopment": True, "component": base64.b64encode(component).decode(),
        "manifest": base64.b64encode(manifest).decode(), "contracts": base64.b64encode(contracts).decode(), "calls": calls}
    if fixtures is not None:
        request["fixtures"] = fixtures
    response = process.run([str(host)], cwd, stdin=encode(request), timeout=45, maximum=4 * 1024 * 1024)
    require(response.returncode == 0, "actual-portable-test-execution-failed:" + response.stdout[:512].decode("utf-8", errors="replace"))
    result = decode(response.stdout, 4 * 1024 * 1024)
    require(result["productionNode"] is False and result["environment"] == "portable", "portable-routing")
    require(result["component"] == digest(component), "portable-artifact-association")
    require([item["id"] for item in result["results"]] == [item["id"] for item in calls], "portable-call-association")
    require(all(item["cleanup"] == "reusable" for item in result["results"]), "portable-cleanup")
    return result


def payload(item: dict) -> bytes:
    value = item["data"]["payload"]
    raw = base64.b64decode(value["data"], validate=True)
    require(value["byteLength"] == str(len(raw)) and value["mediaType"] == MEDIA, "portable-exact-payload")
    return raw


def verify(host: Path, echo: Path, generic: Path, providers: Path | None = None) -> dict:
    with tempfile.TemporaryDirectory(prefix="lsf-portable-real-") as temporary:
        cwd = Path(temporary)
        # Cargo hard-links its build outputs. Stage the shipping executable as a
        # single-link file and execute the staged bytes outside the source tree.
        shipped = cwd / host.name
        shutil.copy2(host, shipped)
        host = shipped
        # Only precompiled components are supplied to this execution environment.
        # process.environment excludes language tool paths and ambient credentials.
        grants = ["latent:context/context@0.1.0", "latent:log/log@0.1.0"]
        calls = [call("success", "echo", b'["hello"]', grants=grants),
                 call("declared-error", "echo", b'[""]', grants=grants),
                 call("denied", "echo", b'["denied"]'),
                 call("cancelled", "echo", b'["cancel"]', grants=grants, cancel=True),
                 call("after-failure", "echo", b'["after"]', grants=grants)]
        for item in calls:
            item["contract"] = "examples:echo/api@0.1.0"
        echo_bytes = paths.read(echo, "echo-capsule.wasm")
        echo_manifest = paths.read(echo, "capsule.json")
        echo_contracts = paths.read(echo, "contracts.json")
        result = run(host, cwd, echo_bytes, echo_manifest, echo_contracts, calls)
        results = result["results"]
        require([item["category"] for item in results] ==
            ["success", "declared-error", "platform-failure", "platform-failure", "success"], "echo-categories")
        require(payload(results[0]) == b'[{"ok":"hello"}]'
                and payload(results[1]) == b'[{"err":{"case":"empty-message"}}]'
                and payload(results[4]) == b'[{"ok":"after"}]', "typed-echo-values")
        require(results[3]["error"]["code"] == "cancelled", "actual-cancellation")
        require(results[0]["logs"] and results[0]["logs"][0]["activation_id"] == "success", "actual-host-log")
        native = paths.read(generic.parent, generic.name)
        fixture = ROOT / "tools/tests/fixtures/budget_lifecycle"
        manifest = decode(paths.read(fixture, "generic-capsule.json"))
        manifest["component"]["digest"] = digest(native)
        tests = [call("fresh-first", "bump"), call("fresh-second", "bump"),
                 call("declared", "checked", b"[false]"), call("absent-result", "unit-result", b"[true]"),
                 call("trap", "trap"), call("fuel", "spin", fuel="10000"),
                 call("memory", "grow", fuel="100000000"),
                 call("deadline", "spin", fuel="10000000000", timeout=20),
                 call("recover", "bump")]
        generic_result = run(host, cwd, native, encode(manifest), paths.read(fixture, "generic-contracts.json"), tests)
        actual = generic_result["results"]
        require(payload(actual[0]) == payload(actual[1]) == payload(actual[-1]) == b"[1]", "fresh-store-recovery")
        require(payload(actual[2]) == b'[{"err":{"case":"named","value":"denied"}}]'
                and payload(actual[3]) == b'[{"ok":null}]', "declared-and-absence-values")
        require([item["error"]["code"] for item in actual[4:8]] ==
            ["guest-trap", "fuel-exhausted", "memory-exhausted", "deadline-exceeded"], "actual-budget-interruptions")
        require(actual[-1]["storesCreated"] == str(len(tests)), "fresh-store-count")
        # A syntactically valid unsupported import is rejected before preparation,
        # even though the supplied component bytes themselves are executable.
        rejected = decode(echo_manifest)
        rejected["imports"].append({"contract": "latent:secrets/reader@0.1.0", "optional": False})
        request = {"schemaVersion": "latent.dev.portable-request.v1", "environment": "portable",
            "controlledDevelopment": True, "component": base64.b64encode(echo_bytes).decode(),
            "manifest": base64.b64encode(encode(rejected)).decode(),
            "contracts": base64.b64encode(echo_contracts).decode(), "calls": calls[:1]}
        denied = process.run([str(host)], cwd, stdin=encode(request), timeout=15)
        require(denied.returncode == 2 and decode(denied.stdout)["code"] ==
                "portable-import-unsupported-before-execution", "unsupported-import-rejected")
        from tools.tests.test_dev_contracts import descriptor
        selected = descriptor()
        selected["service"] = "examples/echo"
        for directory in (cwd / "src", cwd / "output"):
            paths.new_directory(directory)
        for name, raw in (("output/capsule.wasm", echo_bytes), ("output/capsule.json", echo_manifest),
                          ("output/contracts.json", echo_contracts), ("src/input.json", b'["hello"]'),
                          ("src/expected.json", b'[{"ok":"hello"}]')):
            paths.write_new(cwd / name, raw)
        scenario = {"id": "shared-success", "service": "examples/echo", "contract": "examples:echo/api@0.1.0",
            "function": "echo", "input": "src/input.json", "mediaType": MEDIA,
            "expect": {"category": "success", "payload": "src/expected.json"}, "requires": ["context", "log"],
            "timeoutMillis": 1000, "required": True, "fixtures": [], "execution": {"grants": grants}}
        document = {"schemaVersion": "latent.dev.scenarios.v1", "scenarios":
            [scenario, {**scenario, "id": "required-linux", "requires": ["deployment"]}]}
        paths.write_new(cwd / "src/tests.json", encode(document))
        blocked = portable.execute(host, cwd, cwd, selected, [], host_identity={"kind": "explicit-local-test-build"})
        require(blocked["passed"] is False and [item["status"] for item in blocked["results"]] ==
                ["not-run", "unsupported"] and blocked["cleanup"] == "no-native-host-started"
                and blocked["identity"]["runtime"]["runs"] == [],
                "required-linux-test-must-block-all-portable-execution")
        shared = portable.execute(host, cwd, cwd, selected, ["shared-success"],
                                  host_identity={"kind": "explicit-local-test-build"})
        require(shared["passed"] is True and len(shared["results"]) == 1,
                "selected-common-scenario-must-execute")
        provider_results = None
        if providers is not None:
            from tools.portable_dev_provider_tests import verify as verify_providers
            provider_results = verify_providers(host, cwd, providers)
        return {"schemaVersion": "latent.dev.portable-smoke.v1", "os": platform.system(),
            "architecture": platform.machine(), "hostSha256": digest(paths.read(host.parent, host.name, 256 * 1024 * 1024)),
            "environment": "portable", "outsideCheckout": True, "compilerInExecutionPath": False,
            "execution": "actual-component-production-wasmtime", "publisherAuthenticated": False,
            "qualification": "rust-native-subset-only", "cleanup": "owned-processes-reaped",
            "echo": result, "generic": generic_result, "providers": provider_results,
            "sharedScenarioAdapter": shared, "requiredLinuxScenario": blocked,
            "unsupportedImportRejected": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", type=Path, required=True)
    parser.add_argument("--echo", type=Path, required=True)
    parser.add_argument("--generic", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--providers", type=Path)
    args = parser.parse_args()
    receipt = verify(args.host.absolute(), args.echo.absolute(), args.generic.absolute(), args.providers.absolute() if args.providers else None)
    args.output.write_bytes(encode(receipt))
    print("Actual portable Rust subset passed: typed values/errors, log/context, deny, cancellation, fresh state, trap and budgets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
