#!/usr/bin/env python3
"""Clone an exact CI source into a private host workspace, without repairing ACLs."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.native_runtime import files, verify
from tools.native_runtime.common import InstallError, execute, require

ROOT = Path(__file__).resolve().parents[1]


def prepare():
    require(sys.platform == "linux" and os.environ.get("GITHUB_REPOSITORY") == verify.REPOSITORY,
            "native-host-workspace-requires-own-repository-linux-ci")
    commit = os.environ["GITHUB_SHA"]
    require(verify.SOURCE.fullmatch(commit), "exact-host-workspace-commit-required")
    status, head = execute(["git", "rev-parse", "HEAD"], cwd=str(ROOT))
    require(status == 0 and head.decode().strip() == commit, "host-workspace-source-commit-mismatch")
    root = Path(tempfile.mkdtemp(prefix="lsf-native-", dir="/tmp"))
    with files.directory(root, {0, os.geteuid()}):
        pass
    source = root / "source"
    for command in (["git", "clone", "--no-hardlinks", "--no-local", "--no-checkout", "--depth", "1", str(ROOT), str(source)],
                    ["git", "-C", str(source), "checkout", "--detach", commit]):
        status, _output = execute(command, timeout=90, maximum=65536)
        require(status == 0, "private-native-source-clone-failed")
    status, observed = execute(["git", "-C", str(source), "rev-parse", "HEAD"])
    require(status == 0 and observed.decode().strip() == commit, "private-native-source-commit-mismatch")
    target = source / "target"
    target.mkdir(mode=0o700)
    trust = target / "verification"
    trust.mkdir(mode=0o700)
    with files.directory(trust, {0, os.geteuid()}):
        pass
    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as stream:
        stream.write("NATIVE_WORKSPACE=" + str(source) + "\nNATIVE_TRUST=" + str(trust) + "\n")
    print("Prepared private exact-source native host workspace; runner and installation ACLs are unchanged.")


if __name__ == "__main__":
    try:
        prepare()
    except (InstallError, OSError, KeyError, UnicodeError):
        print("private-native-host-workspace-preparation-failed", file=sys.stderr)
        raise SystemExit(1)
