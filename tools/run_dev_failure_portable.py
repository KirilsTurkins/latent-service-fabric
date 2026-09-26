#!/usr/bin/env python3
"""Compare authored failure/recovery capsules on actual native Windows."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys
import tempfile

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.compare_dev_node_portable import compare
from tools.dev_workflow import paths, portable, project
from tools.dev_workflow.common import DevError, decode, encode, require


def run(host: Path, inputs: Path, output: Path) -> dict:
    require(os.name == "nt" and not output.exists(), "actual-windows-and-new-failure-output-required")
    report = {"schemaVersion": "latent.dev.windows-failure-comparison.v1", "passed": False,
              "publisherAuthenticated": False, "cleanHost": False, "qualificationComplete": False,
              "cleanup": "unconfirmed"}
    with tempfile.TemporaryDirectory(prefix="lsf-failure-native-") as temporary:
        root = Path(temporary)
        require(not root.is_relative_to(Path(__file__).resolve().parents[1]), "native-failure-outside-checkout")
        executable = root / "latent-portable-test-host.exe"
        try:
            shutil.copyfile(host, executable)
            report["hostSha256"] = paths.digest_file(root, executable.name, 256 * 1024 * 1024)[0]
            node = decode(paths.read(inputs, "shared-node.json", 4 * 1024 * 1024), 4 * 1024 * 1024)
            application = root / "application"
            shutil.copytree(inputs / "project", application)
            descriptor, _ = project.load(application)
            native = portable.execute(executable, application, application, descriptor, node["selection"],
                                      host_identity={"kind": "explicit-local-test-build"})
            report.update(portable=native, comparison=compare(node, native))
            blocked = portable.execute(executable, application, application, descriptor, [],
                                       host_identity={"kind": "explicit-local-test-build"})
            require(not blocked["passed"] and blocked["cleanup"] == "no-native-host-started"
                    and next(row for row in blocked["results"] if row["id"] == "running-cancel")["status"] == "unsupported",
                    "portable-cannot-substitute-running-cancellation")
            report.update(portableRequiredCancellation=blocked, passed=True, cleanup="owned-native-host-reaped")
        except (DevError, OSError, ValueError) as error:
            report["failure"] = error.code if isinstance(error, DevError) else type(error).__name__
            raise
        finally:
            output.write_bytes(encode(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("host", "inputs", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    receipt = run(args.host.absolute(), args.inputs.absolute(), args.output.absolute())
    print(encode({"passed": receipt["passed"], "cleanup": receipt["cleanup"]}).decode())
