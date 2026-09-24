#!/usr/bin/env python3
"""Execute the same maintained tutorial components and assertions on each host."""
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


def verify(host: Path, applications: Path, output: Path, language: str) -> dict:
    require(language in project.LANGUAGES, "maintained-guest-language")
    with tempfile.TemporaryDirectory(prefix="lsf-native-" + language + "-") as temporary:
        root = Path(temporary)
        require(not root.is_relative_to(Path(__file__).resolve().parents[1]), "native-test-must-be-outside-checkout")
        shipped = root / host.name
        shutil.copyfile(host, shipped)
        shipped.chmod(0o700)
        report = {"schemaVersion": "latent.dev.portable-applications.v1", "environment": "portable",
            "os": platform.system(), "architecture": platform.machine(),
            "hostSha256": paths.digest_file(root, shipped.name, 256 * 1024 * 1024)[0],
            "execution": "actual-component-production-wasmtime", "language": language, "ownerIssue": project.LANGUAGES[language],
            "compilerInExecutionPath": False, "outsideCheckout": True, "publisherAuthenticated": False,
            "applications": {}, "passed": False, "cleanup": "unconfirmed", "qualification": "native-tutorial-subset-only"}
        try:
            for name in ("greeting", "word-count", "shipping"):
                report["phase"] = name
                case = root / name
                shutil.copytree(applications / name, case)
                descriptor, _ = project.load(case)
                require(descriptor["language"] == language, "maintained-language-application-required")
                report["applications"][name] = portable.execute(shipped, case, case, descriptor, [],
                    host_identity={"kind": "explicit-local-test-build", "sha256": report["hostSha256"]})
            require(paths.digest_file(root, shipped.name, 256 * 1024 * 1024)[0] == report["hostSha256"], "native-host-changed")
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
    for name in ("host", "applications", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--language", choices=sorted(project.LANGUAGES), required=True)
    args = parser.parse_args()
    result = verify(args.host.absolute(), args.applications.absolute(), args.output.absolute(), args.language)
    require(result["passed"], "actual-native-common-scenarios-failed")
    print("Actual native " + args.language + " tutorial scenarios passed")
