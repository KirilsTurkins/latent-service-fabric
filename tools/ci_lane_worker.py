#!/usr/bin/env python3
"""Execute one co-located CI integration lane with the maintained runners.

This worker consumes the successful workspace Cargo inventory and current
checkout. It does not build the workspace or relocate native artifacts. Each
child is supervised by TestRun/owned_test_process and all timing records are
diagnostic observations rather than product performance gates.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import ci_suite_inventory as registry
from tools.owned_test_process import ProcessFailure
from tools.test_run import TestRun, require

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "latent.ci-lane-run.v1"

MINIO = "quay.io/minio/minio@sha256:a1a8bd4ac40ad7881a245bab97323e18f971e4d4cba2c2007ec1bedd21cbaba2"
VAULT = "hashicorp/vault@sha256:783103ba38c5e3edcaa9bbbcb0ff80fc93c690361f03fd487e89227da6c3efa9"
NATS = "nats@sha256:065e8355c20a5575b3c77224be1855e8103fd148b68fba05130b9b8ddfa40ccc"

PROVIDER_SELECTIONS = ("s3-blobs", "vault-secrets", "nats-events", "nats-triggers")
PROVIDER_STEPS = [
    "s3-blobs",
    "s3-invalid-prepared-harness",
    "vault-secrets",
    "nats-events",
    "nats-triggers",
    "capability-policy-cli",
]
RENDERER_STEPS = [
    "angular-ssr-hydration",
    "browser-boundary",
    "angular-renderer",
    "renderer-failure-control",
    "angular-build-contracts",
    "angular-package",
    "angular-package-runtime",
]


def _provider_cases(data: dict) -> list[str]:
    values = []
    for key in PROVIDER_SELECTIONS:
        selected = data["selections"][key]
        require(selected["runner"] == "provider-owner" and selected["names"],
                "invalid-fixture", "provider-selection-contract")
        values.extend(selected["names"])
    return values


def _renderer_cases(data: dict) -> list[str]:
    rows = {row["id"]: row for row in data["suites"]}
    selected = data["selections"]["browser-boundary"]
    require(selected["runner"] == "ci_rust_artifacts", "invalid-fixture", "browser-selection-contract")
    values = list(selected["names"])
    process = data["processContracts"]["angular-renderer"]
    for key in process["suiteIds"]:
        row = rows[key]
        require(row["recipe"] == "workspace-all-features" and row["expectedIgnored"],
                "invalid-fixture", "renderer-suite-contract")
        selected_cases = row["expectedIgnored"]
        if row["target"] == "latentd":
            selected_cases = [name for name in selected_cases if "actual_angular_http_" in name]
        values.extend(selected_cases)
    for key in ("latent-packaging.test.angular-build", "latent-wasmtime.test.angular-build"):
        build = rows[key]
        require(build["expectedIgnored"], "invalid-fixture", "angular-build-suite-contract")
        values.extend(build["expectedIgnored"])
    policy_cases = [name for name in rows["latent-policy.lib.latent-policy"]["expectedIgnored"]
                    if "supply_chain::tests::web::angular_build::" in name]
    require(len(policy_cases) == 1, "invalid-fixture", "angular-policy-case-contract")
    values.extend(policy_cases)
    return values


def _command(run: TestRun, args: list[str], *, stage: str, cwd: Path = ROOT,
             timeout: float = 600, env: dict[str, str] | None = None,
             check: bool = True):
    run.mark(stage)
    return run.command(args, cwd=cwd, timeout=timeout, maximum=8 * 1024 * 1024,
                       env=env, check=check)


def _wrong_s3_manifest(source: Path, destination: Path) -> None:
    target_root = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target")).resolve()
    changed = False
    with source.open("r", encoding="utf-8") as input_file, destination.open("x", encoding="utf-8") as output:
        for line in input_file:
            item = json.loads(line)
            if (item.get("reason") == "compiler-artifact"
                    and item.get("target", {}).get("name") == "s3_blobs"
                    and item.get("profile", {}).get("test")
                    and item.get("executable")):
                item["executable"] = str(target_root / "debug/deps/lsf-intentionally-missing-s3-harness")
                line = json.dumps(item, separators=(",", ":")) + "\n"
                changed = True
            output.write(line)
    require(changed, "invalid-fixture", "s3-negative-control-owner-missing")


def provider(run: TestRun, manifest: Path, data: dict) -> tuple[list[str], list[str]]:
    selected = _provider_cases(data)
    python = sys.executable
    _command(run, ["docker", "pull", MINIO], stage="provider-s3-image", timeout=240)
    _command(run, [python, "tools/run_s3_blob_tests.py", "--test-manifest", str(manifest)],
             stage="provider-s3", timeout=420)

    wrong = run.root / "wrong-s3-inventory.jsonl"
    _wrong_s3_manifest(manifest, wrong)
    negative = _command(
        run, [python, "tools/run_s3_blob_tests.py", "--test-manifest", str(wrong)],
        stage="provider-s3-invalid-prepared-harness", timeout=180, check=False,
    )
    require(negative.returncode != 0, "assertion-failure", "wrong-prepared-provider-harness-was-accepted")

    _command(run, ["docker", "pull", VAULT], stage="provider-vault-image", timeout=240)
    _command(run, [python, "tools/run_vault_secret_tests.py", "--test-manifest", str(manifest)],
             stage="provider-vault", timeout=420)

    _command(run, ["docker", "pull", NATS], stage="provider-nats-image", timeout=240)
    _command(run, [python, "tools/run_nats_event_tests.py", "--test-manifest", str(manifest)],
             stage="provider-nats-events", timeout=420)
    _command(run, [python, "tools/run_nats_event_tests.py", "--suite", "nats_triggers",
                   "--test-manifest", str(manifest)],
             stage="provider-nats-triggers", timeout=420)

    _command(run, [python, "tools/run_capability_policy_workflow.py",
                   "--cli", str(ROOT / "target/debug/latent"),
                   "--node", str(ROOT / "target/debug/latentd")],
             stage="provider-capability-policy", timeout=240)
    return PROVIDER_STEPS, selected


def renderer(run: TestRun, manifest: Path, data: dict) -> tuple[list[str], list[str]]:
    selected = _renderer_cases(data)
    node = shutil.which("node")
    npm = shutil.which("npm")
    chrome = shutil.which("google-chrome")
    wasm_tools = shutil.which("wasm-tools")
    objcopy = shutil.which("objcopy")
    require(all((node, npm, chrome, wasm_tools, objcopy)),
            "unavailable-environment", "renderer-lane-tools-unavailable")
    assert node and npm and chrome and objcopy

    profile = ROOT / "examples/renderer-profile"
    component = Path(os.environ["RUNNER_TEMP"]) / "browser-component/application.wasm"
    require(component.is_file(), "invalid-fixture", "browser-component-not-prepared")
    run.artifact("browser-component", component)

    _command(run, [npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
             stage="renderer-npm-prepare", cwd=profile, timeout=360)
    _command(run, [npm, "run", "build"], stage="renderer-profile-build", cwd=profile, timeout=360)
    _command(run, [node, "node-candidate.mjs"], stage="renderer-node-candidate", cwd=profile, timeout=120)
    _command(run, [str(ROOT / "target/debug/latent-renderer-profile"),
                   "dist/renderer.wasm", "dist/wasmtime-rendered.html"],
             stage="renderer-ssr", cwd=profile, timeout=480)
    _command(run, [node, "hydrate.mjs", chrome], stage="renderer-profile-hydration",
             cwd=profile, timeout=120)

    _command(run, [node, "--test", "tools/tests/browser_hydration.test.mjs",
                   "tools/tests/browser_application.test.mjs"],
             stage="renderer-browser-unit", timeout=120)
    browser = Path(os.environ["RUNNER_TEMP"]) / "browser-boundary"
    _command(run, [node, "tools/browser-boundary/build.mjs",
                   "examples/renderer-profile", str(browser)],
             stage="renderer-browser-build", timeout=240)
    browser_env = dict(
        os.environ,
        LSF_WEB_COMPONENT=str(component),
        LSF_BROWSER_BUILD=str(browser),
        LSF_BROWSER_NODE=node,
        LSF_BROWSER_CHROME=chrome,
        LSF_BROWSER_TOOLCHAIN=str(profile),
    )
    _command(run, [sys.executable, "tools/ci_rust_artifacts.py",
                   "--inventory", str(manifest), "--suite", "browser-boundary"],
             stage="renderer-browser-boundary", timeout=360, env=browser_env)

    _command(run, [sys.executable, "tools/build_angular_renderer.py"],
             stage="renderer-public-fixture", timeout=480)
    public_component = ROOT / "examples/renderer-profile/dist/runtime/application.wasm"
    _command(run, [sys.executable, "tools/run_angular_renderer_tests.py",
                   "--test-manifest", str(manifest), "--component", str(public_component),
                   "--diagnostic-root", str(Path(os.environ["RUNNER_TEMP"]) / "owned-renderer")],
             stage="renderer-generic-cells", timeout=840)

    fault = _command(run, [sys.executable, "tools/run_angular_renderer_tests.py",
                          "--test-manifest", str(manifest), "--component", str(public_component),
                          "--inject-failure", "after-discovery",
                          "--diagnostic-root", str(Path(os.environ["RUNNER_TEMP"]) / "owned-renderer-fault")],
                     stage="renderer-negative-control", timeout=240, check=False)
    require(fault.returncode == 1, "assertion-failure", "renderer-fault-control-did-not-fail")
    _command(run, [sys.executable, "tools/check_owned_diagnostics.py",
                   str(Path(os.environ["RUNNER_TEMP"]) / "owned-renderer-fault"),
                   "--suite", "angular-renderer", "--reason", "injected-after-discovery"],
             stage="renderer-negative-control-proof", timeout=60)

    build_env = dict(os.environ, LSF_ANGULAR_TOOLCHAIN=str(profile))
    _command(run, [sys.executable, "-m", "unittest",
                   "tools.tests.test_build_angular_package",
                   "tools.tests.test_build_inventory",
                   "tools.tests.test_web_admission_schemas",
                   "tools.tests.test_angular_build_runner"],
             stage="renderer-build-contracts", timeout=180, env=build_env)

    assembler = Path(os.environ["RUNNER_TEMP"]) / "lsf-angular-package-assembler"
    _command(run, [objcopy, "--strip-debug", str(ROOT / "target/debug/latent"), str(assembler)],
             stage="renderer-package-assembler", timeout=60)
    run.artifact("angular-package-assembler", assembler, 1024 * 1024 * 1024)
    angular_root = Path(os.environ["RUNNER_TEMP"]) / "angular-build"
    build = angular_root / "actual"
    _command(run, [sys.executable, "tools/build_angular_package.py",
                   "--input-root", "examples/angular-application",
                   "--toolchain-root", "examples/renderer-profile",
                   "--cli", str(assembler),
                   "--target-root", str(angular_root),
                   "--output", str(build),
                   "--cargo-target-dir", str(ROOT / "target"),
                   "--repository", "https://example.com/source"],
             stage="renderer-angular-package", timeout=780)
    html = angular_root / "rendered.html"
    _command(run, [sys.executable, "tools/run_angular_build_tests.py",
                   "--test-manifest", str(manifest), "--build", str(build), "--html", str(html)],
             stage="renderer-angular-runtime", timeout=780)
    _command(run, [node, "tools/check_angular_hydration.mjs",
                   "examples/renderer-profile", str(build), str(html), chrome],
             stage="renderer-angular-hydration", timeout=180)
    return RENDERER_STEPS, selected


def write_receipt(path: Path, value: dict) -> None:
    encoded = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    require(len(encoded) <= 256 * 1024, "invalid-fixture", "lane-worker-receipt-limit")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + ".tmp")
    with temporary.open("xb") as output:
        output.write(encoded)
    temporary.chmod(0o600)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", choices=("provider", "renderer"), required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = registry.load()
    manifest = args.inventory.resolve(strict=True)
    diagnostic = args.output.parent / "diagnostics"
    timeout = 1450 if args.lane == "provider" else 3850
    run = TestRun(
        "ci-" + args.lane + "-lane",
        {"timeoutSeconds": timeout},
        repo=ROOT,
        diagnostic_root=diagnostic,
        reproduction={"suite": "ci-" + args.lane + "-lane", "recipe": "workspace-all-features"},
    )
    steps: list[str] = []
    selected: list[str] = []
    error: BaseException | None = None
    try:
        with run:
            run.source_identity()
            run.artifact("test-manifest", manifest)
            if args.lane == "provider":
                steps, selected = provider(run, manifest, data)
            else:
                steps, selected = renderer(run, manifest, data)
    except BaseException as caught:
        error = caught

    record = run.record or {}
    receipt = {
        "schemaVersion": SCHEMA,
        "lane": args.lane,
        "outcome": "passed" if error is None else "failed",
        "steps": steps,
        "selectedCases": selected,
        "timings": record.get("timings", []),
        "diagnostic": run.record_path.name if run.record_path else None,
        "reason": record.get("reason"),
    }
    write_receipt(args.output, receipt)
    if error is not None:
        print(f"{args.lane} lane failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
