#!/usr/bin/env python3
"""Compare the same authored HTTP capsule on the actual Windows native host."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.compare_dev_node_portable import compare
from tools.dev_workflow import paths, portable, project
from tools.dev_workflow.common import DevError, decode, encode, require


def retire_temporary(temporary, root: Path, parent: Path) -> None:
    """Remove this owned fixture after execution; never repeat native execution.

    Windows can briefly retain a file mapping after the process Job and leader
    have been reaped. Only its sharing violation receives bounded cleanup
    attempts; a persistent lock or any other failure remains non-success.
    """
    cutoff = time.monotonic() + 1
    for attempt in range(8):
        require(root.is_absolute() and Path(temporary.name).absolute() == root and root.resolve().parent == parent
                and not root.is_symlink() and not root.is_junction(), "native-http-owned-temporary-root")
        try:
            temporary.cleanup()
            require(time.monotonic() <= cutoff, "native-http-temporary-cleanup-deadline")
            return
        except PermissionError as error:
            remaining = cutoff - time.monotonic()
            if os.name != "nt" or getattr(error, "winerror", None) != 32 or attempt == 7 or remaining <= 0:
                raise
            time.sleep(min(0.05, remaining))


@contextmanager
def native_temporary():
    parent = Path(tempfile.gettempdir()).resolve()
    temporary = tempfile.TemporaryDirectory(prefix="lsf-http-native-", dir=parent)
    root = Path(temporary.name)
    try:
        yield root
    finally:
        retire_temporary(temporary, root, parent)


def run(host: Path, inputs: Path, output: Path) -> dict:
    require(os.name == "nt" and not output.exists(), "actual-windows-and-new-http-output-required")
    report = {"schemaVersion": "latent.dev.windows-http-comparison.v1", "passed": False,
              "publisherAuthenticated": False, "cleanHost": False, "qualificationComplete": False,
              "cleanup": "unconfirmed"}
    try:
        with native_temporary() as root:
            require(not root.is_relative_to(Path(__file__).resolve().parents[1]), "native-http-outside-checkout")
            executable = root / "latent-portable-test-host.exe"
            shutil.copyfile(host, executable)
            report["hostSha256"] = paths.digest_file(root, executable.name, 256 * 1024 * 1024)[0]
            node = decode(paths.read(inputs, "shared-node.json", 4 * 1024 * 1024), 4 * 1024 * 1024)
            application = root / "application"
            shutil.copytree(inputs / "project", application)
            descriptor, _ = project.load(application)
            native = portable.execute(executable, application, application, descriptor, node["selection"],
                                      host_identity={"kind": "explicit-local-test-build"})
            report.update(portable=native, comparison=compare(node, native))
            require(native["identity"]["runtime"]["runs"][0]["httpFixtureRequests"] == 4,
                    "native-denied-http-must-not-contact-peer")
        report.update(passed=True, cleanup="owned-native-host-and-peer-reaped")
    except (DevError, OSError, ValueError) as error:
        report["failure"] = error.code if isinstance(error, DevError) else type(error).__name__
        report["diagnostics"] = error.diagnostics if isinstance(error, DevError) else []
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
