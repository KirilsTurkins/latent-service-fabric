#!/usr/bin/env python3
"""Execute checked C application and SDK components with the actual native host."""
from __future__ import annotations

import argparse
from pathlib import Path
import platform
import shutil
import sys
import tempfile

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.dev_workflow import paths, portable, project
from tools.dev_workflow.common import DevError, encode, require
from tools.portable_dev_provider_tests import verify as verify_providers


def verify(host: Path, providers: Path, applications: Path, output: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="lsf-native-c-execution-") as temporary:
        root = Path(temporary)
        require(not root.is_relative_to(Path(__file__).resolve().parents[1]), "native-test-must-be-outside-checkout")
        shipped = root / host.name
        shutil.copyfile(host, shipped)
        shipped.chmod(0o700)
        report = {"schemaVersion": "latent.dev.portable-c-smoke.v1", "environment": "portable",
            "os": platform.system(), "architecture": platform.machine(), "hostSha256": paths.digest_file(root, shipped.name, 256 * 1024 * 1024)[0],
            "execution": "actual-component-production-wasmtime", "language": "c", "ownerIssue": 545,
            "compilerInExecutionPath": False, "outsideCheckout": True, "publisherAuthenticated": False, "applications": {},
            "passed": False, "cleanup": "unconfirmed", "qualification": "c-native-subset-only"}
        try:
            for name in ("greeting", "word-count", "shipping"):
                report["phase"] = "application-" + name
                case = root / name
                shutil.copytree(applications / name, case)
                descriptor, _ = project.load(case)
                require(descriptor["language"] == "c", "c-authoring-application-required")
                report["applications"][name] = portable.execute(shipped, case, case, descriptor, [],
                    host_identity={"kind": "explicit-local-test-build"})
            report["phase"] = "sdk-providers"
            report["providers"] = verify_providers(shipped, root, providers)
            report.update(passed=all(item["passed"] for item in report["applications"].values()),
                          phase="complete", cleanup="owned-processes-reaped")
        except DevError as error:
            report["failureCode"] = error.code
            raise
        finally:
            output.write_bytes(encode(report))
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("host", "providers", "applications", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    receipt = verify(args.host.absolute(), args.providers.absolute(), args.applications.absolute(), args.output.absolute())
    require(receipt["passed"], "actual-c-common-scenarios-failed")
    print("Actual native C applications and supported SDK providers passed")
