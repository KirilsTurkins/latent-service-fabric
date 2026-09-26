#!/usr/bin/env python3
"""Compare real exported metrics and cleanup on an authenticated node and native host."""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.compare_dev_node_portable import compare
from tools.dev_node_application_probe import run as run_node
from tools.dev_workflow import build, metric_fixture, paths, portable, project, snapshot, state
from tools.dev_workflow.common import decode, digest, encode, require
from tools.dev_workflow.node_output import PROVIDER_COUNTERS

WORLD = """package examples:greeting@1.0.0;
interface api { emit: func(wrong-kind: bool, name: string, region: string, twice: bool) -> u64; }
world service { import latent:telemetry/custom@0.1.0; export api; }
"""
COMPONENT = """#[cfg(target_arch = "wasm32")]
mod component {
    wit_bindgen::generate!({path: "wit", world: "service", generate_all,
        with: {"latent:telemetry/custom@0.1.0": latent_guest::bindings::metrics}});
    use latent_guest::metrics::{self, Metric, MetricKind, TelemetryError};
    use core::sync::atomic::{AtomicU32, Ordering};
    static ENTERED: AtomicU32 = AtomicU32::new(0);
    fn emit(metric: &Metric) -> u64 {
        match metrics::emit_metric(metric) {
            Ok(true) => 1, Ok(false) => 0,
            Err(TelemetryError::InvalidName) => 10,
            Err(TelemetryError::BudgetExhausted) => 11,
            Err(TelemetryError::Unavailable) => 12,
        }
    }
    struct Capsule;
    impl exports::examples::greeting::api::Guest for Capsule {
        fn emit(wrong_kind: bool, name: String, region: String, twice: bool) -> u64 {
            assert_eq!(ENTERED.fetch_add(1, Ordering::Relaxed), 0);
            let metric = Metric {name, kind: if wrong_kind {MetricKind::Gauge} else {MetricKind::Counter},
                value: 2.0, unit: "1".into(), attributes: vec![("region".into(), region)]};
            let first = emit(&metric);
            if twice {first * 100 + emit(&metric)} else {first}
        }
    }
    export!(Capsule);
}
"""


def author(payload: Path, destination: Path) -> tuple[dict, dict]:
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
    recipe["limits"].update(memoryBytes=16777216, cpuFuel=1000000000, wallTimeLimitMillis=5000)
    (app / "capsule-project.json").write_bytes(encode(recipe))
    telemetry = app / "wit/deps/telemetry"
    telemetry.mkdir(parents=True)
    paths.write_new(telemetry / "package.wit", paths.read(app, "vendor/lsf/wit/platform/telemetry/package.wit"))
    fixtures = {"metrics": [{"name": "dev.calls", "kind": "counter", "unit": "1",
        "labels": [{"key": "region", "values": ["east"]}], "histogramUpperBounds": []}]}
    raw = encode(fixtures)
    paths.write_new(destination / "tests/metric-fixture.json", raw)
    cases = []
    grants = [metric_fixture.PROVIDER[0]]
    for name, wrong, metric, region, twice, expected in (
            ("cold", False, "dev.calls", "east", False, "1"),
            ("warm", False, "dev.calls", "east", False, "1"),
            ("invalid-label", False, "dev.calls", "unregistered", False, "10"),
            ("unknown-name", False, "dev.other", "east", False, "10"),
            ("wrong-kind", True, "dev.calls", "east", False, "10"),
            ("policy-denied", False, "dev.calls", "east", False, "12"),
            ("after-denial", False, "dev.calls", "east", False, "1"),
            ("two-observations", False, "dev.calls", "east", True, "101"),
            ("after-two", False, "dev.calls", "east", False, "1")):
        paths.write_new(destination / f"tests/{name}-input.json", json.dumps([wrong, metric, region, twice]).encode())
        paths.write_new(destination / f"tests/{name}-expected.json", json.dumps([expected]).encode())
        cases.append({"id": name, "service": descriptor["service"], "contract": "examples:greeting/api@1.0.0",
            "function": "emit", "input": f"tests/{name}-input.json", "mediaType": "application/vnd.latent.wit-values.v1+json",
            "timeoutMillis": 5000, "required": True, "requires": ["metrics", "fresh-state"],
            "expect": {"category": "success", "payload": f"tests/{name}-expected.json"},
            "fixtures": [{"id": "metrics", "kind": "real-provider", "identity": digest(raw),
                          "configuration": "tests/metric-fixture.json"}],
            "execution": {"grants": grants, **({"deniedCapabilities": grants} if name == "policy-denied" else {})}})
    (destination / "tests/scenarios.json").write_bytes(encode({"schemaVersion": "latent.dev.scenarios.v1", "scenarios": cases}))
    (destination / "latent.project.json").write_bytes(encode(descriptor))
    return descriptor, fixtures


def run(payload: Path, supplied: Path, portable_host: Path, output: Path) -> dict:
    require(sys.platform == "linux" and os.geteuid() != 0 and not output.exists(),
            "new-unprivileged-linux-metric-probe-required")
    output.mkdir(mode=0o700, parents=True)
    temporary = Path(tempfile.mkdtemp(prefix="lsf-metrics-"))
    require(not temporary.is_relative_to(Path(__file__).resolve().parents[1]), "fixture-project-outside-checkout")
    report = {"schemaVersion": "latent.dev.metric-node-portable-probe.v1", "publisherAuthenticated": False,
              "cleanHost": False, "qualificationComplete": False, "passed": False, "cleanup": "unconfirmed"}
    try:
        author_root = temporary / "Author spaces-\u00fc"
        descriptor, fixtures = author(payload, author_root)
        record, content = snapshot.observe(author_root, descriptor["inputRoots"], tuple(descriptor["exclude"]))
        root = temporary / "test-metrics"
        root.mkdir(mode=0o700)
        (root / "snapshots").mkdir(mode=0o700)
        source = root / "snapshots" / record["identity"][7:]
        snapshot.materialize(source, record, content)
        trust = project.trust_identity(descriptor)
        state.atomic(root, "project.json", {"descriptor": descriptor, "trust": trust,
            "source": str(source), "snapshot": record["identity"]})
        build.execute(root, source, descriptor, payload, trusted=trust, cli=supplied / "bin/latent")
        report["node"] = run_node(root, supplied, payload, descriptor, output / "node", fixtures=fixtures)
        for key, expected in (("shutdownBeforeRestart", 6), ("shutdown", 1)):
            shutdown = report["node"][key]
            counters = shutdown.get("providerShutdown", {})
            require(shutdown.get("cleanShutdown") is True and counters.get("clean") is True
                    and all(type(counters.get(key)) is int and counters[key] == 0
                            for key in (*PROVIDER_COUNTERS, "secretGenerations", "secretReferences")),
                    "metric-node-resource-reclamation-required")
            metrics = metric_fixture.reclaimed(shutdown.get("metrics"))
            require(metrics["accepted"] == expected and metrics["records"] == [
                {"name": "latent.application.dev.calls", "unit": "1", "valueBits": "4000000000000000"}] * expected,
                "metric-exports-must-match-accepted-values")
        report["node"]["tests"]["identity"]["fixtureShutdown"] = {
            "metrics": report["node"]["shutdownBeforeRestart"]["metrics"]}
        state.atomic(output / "node", "node-tests.json", report["node"]["tests"])
        accepted, _ = build.accepted(root, state.load(root, "project.json"))
        native = portable.execute(portable_host, accepted, accepted, descriptor, [], host_identity={"kind": "explicit-local-test-build"})
        report.update(portable=native, comparison=compare(report["node"]["tests"], native, native_os="linux"))
        state.atomic(output, "shared-node.json", report["node"]["tests"])
        state.atomic(output, "portable.json", native)
        retained = output / "project"
        retained.mkdir(mode=0o700)
        paths.write_new(retained / "latent.project.json", encode(descriptor))
        shutil.copytree(accepted / "tests", retained / "tests")
        shutil.copytree(accepted / "output", retained / "output")
        report.update(passed=True, cleanup="owned-node-and-native-processes-reaped-exporter-joined-queue-drained")
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
