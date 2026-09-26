#!/usr/bin/env python3
"""Execute the retained clock capsule on Windows and compare actual node receipts."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.compare_dev_node_portable import compare
from tools.dev_workflow import paths, portable, project
from tools.dev_workflow.common import decode, encode, require


def run(host: Path, inputs: Path, output: Path) -> dict:
    require(os.name == "nt" and not output.exists(), "actual-windows-and-new-fixture-output-required")
    result = {"schemaVersion": "latent.dev.windows-clock-comparison.v1", "passed": False,
              "publisherAuthenticated": False, "cleanHost": False, "qualificationComplete": False,
              "cleanup": "unconfirmed", "fixtures": {}}
    with tempfile.TemporaryDirectory(prefix="lsf-clock-native-") as temporary:
        root = Path(temporary)
        require(not root.is_relative_to(Path(__file__).resolve().parents[1]), "native-clock-outside-checkout")
        executable = root / "latent-portable-test-host.exe"
        shutil.copyfile(host, executable)
        result["hostSha256"] = paths.digest_file(root, executable.name, 256 * 1024 * 1024)[0]
        try:
            for name in ("zero", "maximum"):
                node = decode(paths.read(inputs, name + "/node/node-tests.json", 4 * 1024 * 1024), 4 * 1024 * 1024)
                application = root / name
                shutil.copytree(inputs / name / "project", application)
                descriptor, _ = project.load(application)
                native = portable.execute(executable, application, application, descriptor, node["selection"],
                                          host_identity={"kind": "explicit-local-test-build"})
                result["fixtures"][name] = {"portable": native, "comparison": compare(node, native)}
            result.update(passed=True, cleanup="owned-native-hosts-reaped")
        finally:
            output.write_bytes(encode(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("host", "inputs", "output"):
        parser.add_argument("--" + argument, type=Path, required=True)
    args = parser.parse_args()
    receipt = run(args.host.absolute(), args.inputs.absolute(), args.output.absolute())
    print(json.dumps({"passed": receipt["passed"], "cleanup": receipt["cleanup"]}))
