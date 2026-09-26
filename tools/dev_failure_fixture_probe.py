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

from tools.dev_failure_case_inputs import populate


def author(payload: Path, destination: Path) -> tuple[dict, list[str]]:
    entry = decode(paths.read(payload, "templates.json"))["templates"]["greeting"]
    template = payload / entry["path"]
    manifest = decode(paths.read(template, "template.json"))
    project.scaffold(template, destination, manifest, entry["identity"])
    descriptor = copy.deepcopy(manifest["project"])
    require(descriptor["language"] == "rust", "rust-authoring-template-required")
    return populate(destination, descriptor)


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
