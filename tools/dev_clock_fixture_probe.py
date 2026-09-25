#!/usr/bin/env python3
"""Build a Rust application and compare signed node and portable clock fixtures.

Uses the maintained standalone authoring recipe, production package admission,
and shared scenarios. Source-built runtime inputs are explicitly identified;
this contributor probe cannot qualify publisher trust or a clean host.
"""
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
from tools.dev_workflow import build, paths, portable, project, snapshot, state
from tools.dev_workflow.common import decode, digest, encode, require

WORLD = """package examples:greeting@1.0.0;
interface api {
    record reading { monotonic: u64, wall: u64 }
    clocks: func() -> reading;
}
world service {
    import latent:clock/monotonic@0.1.0;
    import latent:clock/wall@0.1.0;
    export api;
}
"""
COMPONENT = """#[cfg(target_arch = "wasm32")]
mod component {
    wit_bindgen::generate!({path: "wit", world: "service", generate_all});
    struct Capsule;
    impl exports::examples::greeting::api::Guest for Capsule {
        fn clocks() -> exports::examples::greeting::api::Reading {
            exports::examples::greeting::api::Reading {
                monotonic: latent::clock::monotonic::now_nanos(),
                wall: latent::clock::wall::now_unix_millis(),
            }
        }
    }
    export!(Capsule);
}
"""


def author(payload: Path, destination: Path) -> dict:
    entry = decode(paths.read(payload, "templates.json"))["templates"]["greeting"]
    template = payload / entry["path"]
    manifest = decode(paths.read(template, "template.json"))
    project.scaffold(template, destination, manifest, entry["identity"])
    descriptor = copy.deepcopy(manifest["project"])
    require(descriptor["language"] == "rust", "rust-authoring-template-required")
    app = destination / "app"
    (app / "src/lib.rs").write_text(COMPONENT, encoding="utf-8", newline="\n")
    (app / "wit/world.wit").write_text(WORLD, encoding="utf-8", newline="\n")
    clocks = app / "wit/deps/clock"
    clocks.mkdir(parents=True)
    paths.write_new(clocks / "package.wit", paths.read(app, "vendor/lsf/wit/platform/clock/package.wit"))
    cases = []
    grants = ["latent:clock/monotonic@0.1.0", "latent:clock/wall@0.1.0"]
    for name, value in (("zero", "0"), ("maximum", "18446744073709551615")):
        fixture = encode({"clock": {"monotonicNanos": value, "wallUnixMillis": value}})
        paths.write_new(destination / f"tests/clock-{name}.json", fixture)
        paths.write_new(destination / f"tests/clock-{name}-expected.json",
                        json.dumps([{"monotonic": value, "wall": value}], separators=(",", ":")).encode())
        for behavior in ("cold", "warm", "denied", "fresh"):
            case = {"id": f"clock-{name}-{behavior}", "service": descriptor["service"],
                "contract": "examples:greeting/api@1.0.0", "function": "clocks", "input": "tests/clock-input.json",
                "mediaType": "application/vnd.latent.wit-values.v1+json", "timeoutMillis": 1000,
                "nodeTimeoutMillis": 5000, "required": True, "requires": ["clock"],
                "fixtures": [{"id": f"clock-{name}", "kind": "test-adapter", "identity": digest(fixture),
                              "configuration": f"tests/clock-{name}.json"}],
                "execution": {"grants": grants},
                "expect": {"category": "success", "payload": f"tests/clock-{name}-expected.json"}}
            if behavior == "denied":
                case["execution"] = {"grants": grants, "deniedCapabilities": grants}
                case["expect"] = {"category": "platform-failure", "platformCode": "guest-trap"}
            cases.append(case)
    paths.write_new(destination / "tests/clock-input.json", b"[]")
    (destination / "tests/scenarios.json").write_bytes(encode({"schemaVersion": "latent.dev.scenarios.v1", "scenarios": cases}))
    (destination / "latent.project.json").write_bytes(encode(descriptor))
    return descriptor


def run(payload: Path, supplied: Path, portable_host: Path, output: Path) -> dict:
    require(sys.platform == "linux" and os.geteuid() != 0 and not output.exists(),
            "new-unprivileged-linux-fixture-probe-required")
    output.mkdir(mode=0o700, parents=True)
    temporary = Path(tempfile.mkdtemp(prefix="lsf-clock-fixtures-"))
    require(not temporary.is_relative_to(Path(__file__).resolve().parents[1]), "fixture-project-outside-checkout")
    report = {"schemaVersion": "latent.dev.clock-node-portable-probe.v1", "publisherAuthenticated": False,
              "cleanHost": False, "qualificationComplete": False, "passed": False,
              "cleanup": "unconfirmed", "fixtures": {}}
    # Retain each private workspace until all owned process cleanup is known.
    try:
        descriptor = author(payload, temporary / "Author spaces-\u00fc")
        author_root = temporary / "Author spaces-\u00fc"
        record, content = snapshot.observe(author_root, descriptor["inputRoots"], tuple(descriptor["exclude"]))
        for name, value in (("zero", "0"), ("maximum", "18446744073709551615")):
            root = temporary / ("test-" + name)
            root.mkdir(mode=0o700)
            (root / "snapshots").mkdir(mode=0o700)
            source = root / "snapshots" / record["identity"][7:]
            snapshot.materialize(source, record, content)
            trust = project.trust_identity(descriptor)
            state.atomic(root, "project.json", {"descriptor": descriptor, "trust": trust,
                "source": str(source), "snapshot": record["identity"]})
            build.execute(root, source, descriptor, payload, trusted=trust, cli=supplied / "bin/latent")
            selection = [f"clock-{name}-{behavior}" for behavior in ("cold", "warm", "denied", "fresh")]
            fixtures = {"clock": {"monotonicNanos": value, "wallUnixMillis": value}}
            (output / name).mkdir(mode=0o700)
            node = run_node(root, supplied, payload, descriptor, output / name / "node",
                            fixtures=fixtures, selection=selection)
            accepted, _ = build.accepted(root, state.load(root, "project.json"))
            native = portable.execute(portable_host, accepted, accepted, descriptor, selection,
                                      host_identity={"kind": "explicit-local-test-build"})
            state.atomic(output / name, "portable.json", native)
            comparison = compare(node["tests"], native, native_os="linux")
            report["fixtures"][name] = {"node": node, "portable": native, "comparison": comparison}
            # Public source and package outputs can also be executed by the
            # Windows portable host. Never copy runtime/test-signing files.
            retained = output / name / "project"
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
    for argument in ("payload", "source-node", "portable-host", "output"):
        parser.add_argument("--" + argument, type=Path, required=True)
    args = parser.parse_args()
    receipt = run(args.payload.resolve(strict=True), args.source_node.resolve(strict=True),
                  args.portable_host.resolve(strict=True), args.output.absolute())
    print(json.dumps({"passed": receipt["passed"], "cleanup": receipt["cleanup"]}))
