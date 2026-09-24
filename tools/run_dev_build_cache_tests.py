#!/usr/bin/env python3
"""Exercise developer build caching against actual maintained capsule package inputs."""
from __future__ import annotations

import argparse
import io
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.dev_workflow import common, paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packager", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    common.require(sys.platform == "linux", "actual-linux-cache-qualification-required")
    output = args.output.absolute()
    paths.new_directory(output)
    with tempfile.TemporaryDirectory(prefix="lsf-dev-build-check-") as temporary:
        binary = Path(temporary) / "latent"
        # Cargo may hardlink binaries; stage a separate immutable test input.
        shutil.copyfile(args.packager, binary)
        binary.chmod(0o700)
        identity = paths.digest_file(binary.parent, binary.name, 268435456)[0]
        os.environ.update(LSF_DEV_PACKAGER=str(binary), LSF_DEV_BUILD_INPUTS=str(args.inputs.absolute()))
        suite = unittest.defaultTestLoader.loadTestsFromName("tools.tests.test_dev_build_cache")
        log = io.StringIO()
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
        raw = log.getvalue().encode()
        common.require(len(raw) <= 1048576, "cache-test-log-bound")
        paths.write_new(output / "tests.log", raw)
        receipt = {"schemaVersion": "latent.dev.build-cache-tests.v1", "passed": result.wasSuccessful() and not result.skipped,
            "tests": result.testsRun, "skipped": len(result.skipped), "operatorSha256": identity,
            "componentSha256": paths.digest_file(args.inputs.absolute(), "component.wasm")[0],
            "environment": "linux", "languageCompilerQualified": False, "publisherAuthenticated": False}
        paths.write_new(output / "receipt.json", common.encode(receipt))
        sys.stdout.buffer.write(common.encode(receipt))
        return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
