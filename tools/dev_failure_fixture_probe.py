#!/usr/bin/env python3
"""Authored failures, real running cancellation, and same-byte portable recovery."""
from __future__ import annotations

import argparse
import copy
import os
from pathlib import Path
import shutil
import sys
import tempfile

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.compare_dev_node_portable import compare
from tools.dev_node_application_probe import run as run_node
from tools.dev_workflow import build, paths, portable, project, snapshot, state
from tools.dev_workflow.common import decode, encode, require

WORLD = """package examples:greeting@1.0.0;
interface api {
    bump: func() -> u32;
    fail: func() -> result<u32, string>;
    trap: func() -> u32;
    spin: func() -> u32;
    grow: func() -> u32;
}
world service { export api; }
"""
COMPONENT = """#[cfg(target_arch = "wasm32")]
mod component {
    wit_bindgen::generate!({path: "wit", world: "service", generate_all});
    struct Capsule;
    static COUNT: core::sync::atomic::AtomicU32 = core::sync::atomic::AtomicU32::new(0);
    impl exports::examples::greeting::api::Guest for Capsule {
        fn bump() -> u32 { COUNT.fetch_add(1, core::sync::atomic::Ordering::Relaxed) + 1 }
        fn fail() -> Result<u32, String> { Err("declared".to_owned()) }
        fn trap() -> u32 { core::arch::wasm32::unreachable() }
        fn spin() -> u32 {
            let mut value = 0u32;
            loop { value = std::hint::black_box(value.wrapping_add(1)); }
        }
        fn grow() -> u32 { core::arch::wasm32::memory_grow::<0>(1024) as u32 }
    }
    export!(Capsule);
}
"""


def author(payload: Path, destination: Path) -> tuple[dict, list[str]]:
    entry = decode(paths.read(payload, "templates.json"))["templates"]["greeting"]
    template = payload / entry["path"]
    manifest = decode(paths.read(template, "template.json"))
    project.scaffold(template, destination, manifest, entry["identity"])
    descriptor = copy.deepcopy(manifest["project"])
    require(descriptor["language"] == "rust", "rust-authoring-template-required")
    app = destination / "app"
    (app / "src/lib.rs").write_text(COMPONENT, encoding="utf-8", newline="\n")
    (app / "wit/world.wit").write_text(WORLD, encoding="utf-8", newline="\n")
    recipe = decode(paths.read(app, "capsule-project.json"))
    recipe["limits"].update(cpuFuel=10000000000, wallTimeLimitMillis=5000)
    (app / "capsule-project.json").write_bytes(encode(recipe))
    paths.write_new(destination / "tests/failure-input.json", b"[]")
    paths.write_new(destination / "tests/fresh-result.json", b"[1]")
    paths.write_new(destination / "tests/declared-result.json", b'[{"err":"declared"}]')
    cases = []
    def case(name, function="bump", code=None, **execution):
        row = {"id": name, "service": descriptor["service"], "contract": "examples:greeting/api@1.0.0",
            "function": function, "input": "tests/failure-input.json",
            "mediaType": "application/vnd.latent.wit-values.v1+json", "timeoutMillis": 1000,
            "nodeTimeoutMillis": 5000, "required": True, "requires": ["fresh-state"], "fixtures": [],
            "execution": {"grants": [], **execution},
            "expect": {"category": "success", "payload": "tests/fresh-result.json"}}
        if code:
            row["expect"] = {"category": "platform-failure", "platformCode": code}
        cases.append(row)
        return row
    case("cold-fresh")
    case("warm-fresh")
    case("declared", "fail")["expect"] = {"category": "declared-error", "payload": "tests/declared-result.json"}
    case("trap", "trap", "guest-trap")
    case("after-trap")
    case("fuel", "spin", "fuel-exhausted", fuel="10000")["expect"] = {
        "category": "platform-failure", "platformCodes": {"node": "resource-exhausted", "portable": "fuel-exhausted"}}
    case("after-fuel")
    case("memory", "grow", "memory-exhausted")["expect"] = {
        "category": "platform-failure", "platformCodes": {"node": "resource-exhausted", "portable": "memory-exhausted"}}
    case("after-memory")
    case("deadline", "spin", "deadline-exceeded").update(timeoutMillis=20, nodeTimeoutMillis=20)
    case("after-deadline")
    case("running-cancel", "spin", "cancelled", cancelWhenRunning=True).update(
        timeoutMillis=5000, nodeTimeoutMillis=5000, requires=["running-cancellation"])
    case("after-cancel")
    (destination / "tests/scenarios.json").write_bytes(encode({"schemaVersion": "latent.dev.scenarios.v1", "scenarios": cases}))
    (destination / "latent.project.json").write_bytes(encode(descriptor))
    return descriptor, [row["id"] for row in cases if row["id"] != "running-cancel"]


def run(payload: Path, supplied: Path, portable_host: Path, output: Path) -> dict:
    require(sys.platform == "linux" and os.geteuid() != 0 and not output.exists(),
            "new-unprivileged-linux-failure-probe-required")
    output.mkdir(mode=0o700, parents=True)
    temporary = Path(tempfile.mkdtemp(prefix="lsf-failure-fixtures-"))
    require(not temporary.is_relative_to(Path(__file__).resolve().parents[1]), "fixture-project-outside-checkout")
    report = {"schemaVersion": "latent.dev.failure-node-portable-probe.v1", "publisherAuthenticated": False,
              "cleanHost": False, "qualificationComplete": False, "passed": False, "cleanup": "unconfirmed"}
    try:
        author_root = temporary / "Author spaces-\u00fc"
        descriptor, shared = author(payload, author_root)
        record, content = snapshot.observe(author_root, descriptor["inputRoots"], tuple(descriptor["exclude"]))
        root = temporary / "test-failures"
        root.mkdir(mode=0o700)
        (root / "snapshots").mkdir(mode=0o700)
        source = root / "snapshots" / record["identity"][7:]
        snapshot.materialize(source, record, content)
        trust = project.trust_identity(descriptor)
        state.atomic(root, "project.json", {"descriptor": descriptor, "trust": trust,
            "source": str(source), "snapshot": record["identity"]})
        build.execute(root, source, descriptor, payload, trusted=trust, cli=supplied / "bin/latent")
        report["node"] = run_node(root, supplied, payload, descriptor, output / "node")
        accepted, _ = build.accepted(root, state.load(root, "project.json"))
        native = portable.execute(portable_host, accepted, accepted, descriptor, shared,
                                  host_identity={"kind": "explicit-local-test-build"})
        report["portable"] = native
        common_node = copy.deepcopy(report["node"]["tests"])
        common_node["selection"] = shared
        common_node["results"] = [row for row in common_node["results"] if row["id"] in shared]
        state.atomic(output, "shared-node.json", common_node)
        state.atomic(output, "portable.json", native)
        report["comparison"] = compare(common_node, native, native_os="linux")
        # A required live-cancellation case must block every portable invocation.
        blocked = portable.execute(portable_host, accepted, accepted, descriptor, [],
                                   host_identity={"kind": "explicit-local-test-build"})
        require(not blocked["passed"] and blocked["cleanup"] == "no-native-host-started"
                and next(row for row in blocked["results"] if row["id"] == "running-cancel")["status"] == "unsupported",
                "portable-cannot-substitute-prestart-for-running-cancel")
        report["portableRequiredCancellation"] = blocked
        retained = output / "project"
        retained.mkdir(mode=0o700)
        paths.write_new(retained / "latent.project.json", encode(descriptor))
        shutil.copytree(accepted / "tests", retained / "tests")
        shutil.copytree(accepted / "output", retained / "output")
        report.update(passed=True, cleanup="owned-node-and-portable-processes-reaped")
    finally:
        if report["passed"]:
            shutil.rmtree(temporary)
        else:
            report["retainedPrivateWorkspace"] = str(temporary)
        state.atomic(output, "observation.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("payload", "source-node", "portable-host", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    receipt = run(args.payload.resolve(strict=True), args.source_node.resolve(strict=True),
                  args.portable_host.resolve(strict=True), args.output.absolute())
    print(encode({"passed": receipt["passed"], "cleanup": receipt["cleanup"]}).decode())
