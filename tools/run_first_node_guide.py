#!/usr/bin/env python3
"""Exercise the source-based first-node guide with explicit prebuilt artifacts.

This is not an installer or a release attestation. It never builds, downloads,
reads arbitrary Markdown commands, weakens an existing node or retries a mutation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import re
import sys
import tempfile
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_process_signals import owned_cancellation
from tools.first_node_guide import ECHO_FILES, exercise, stage_echo
from tools.phase2_operator_process import Client, bounded_receipt, file_digest, require

COLLECTORS = (
    "tools/run_first_node_guide.py", "tools/first_node_guide.py",
    "tools/phase2_operator_process.py", "tools/build_process.py",
    "tools/build_process_linux.py", "tools/build_process_signals.py",
)


def source_commit(value):
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise argparse.ArgumentTypeError("an exact lowercase Git commit is required")
    return value


def absolute_file(value):
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise argparse.ArgumentTypeError("an absolute regular artifact path is required")
    return path


def run(args):
    require(sys.platform == "linux" and sys.version_info >= (3, 13), "guide-platform")
    root = Path(__file__).resolve().parents[1]
    with owned_cancellation() as cancellation:
        deadline = time.monotonic() + 180
        identities = {"cli": (args.cli, 1024 ** 3), "node": (args.node, 1024 ** 3),
                      **{name: (root / name, 262144) for name in COLLECTORS},
                      "Cargo.lock": (root / "Cargo.lock", 1024 ** 2),
                      "rust-toolchain.toml": (root / "rust-toolchain.toml", 262144)}
        before = {name: file_digest(path, maximum, cancellation, deadline)
                  for name, (path, maximum) in identities.items()}
        with tempfile.TemporaryDirectory(prefix="latent-first-node-") as temporary:
            work = Path(temporary)
            work.chmod(0o700)
            node, client_directory, package = (work / name for name in ("node", "client", "package"))
            for directory in (node, client_directory, package):
                directory.mkdir(mode=0o700)
            inputs = stage_echo(args.echo_root, package)
            client = Client(args.cli, client_directory, cancellation, deadline)
            result = exercise(client, args.node, node, package)
            after = {name: file_digest(path, maximum, cancellation, deadline)
                     for name, (path, maximum) in identities.items()}
            require(before == after, "guide-artifacts-changed")
            for name, maximum in ECHO_FILES.items():
                require(file_digest(args.echo_root / name, maximum, cancellation, deadline)
                        == inputs[name], "guide-inputs-changed")
        require(not work.exists(), "guide-temporary-cleanup")
        return {"schemaVersion": "latent.first-node-guide.v1", "passed": True,
                "measuredAt": datetime.now(timezone.utc).isoformat(),
                "profile": "local-experimental-v1", "admission": "trusted-local",
                "scope": "source-based prebuilt CLI/node/echo; not installed-bundle or external-profile qualification",
                "suppliedBuildSourceCommit": args.source_commit,
                "sourceCommitKind": "caller-supplied; binary and collector bytes hashed separately",
                "identities": before, "echoInputs": inputs, "cliProcesses": client.calls,
                "temporaryOutputsRemoved": True, **result}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=absolute_file, required=True)
    parser.add_argument("--node", type=absolute_file, required=True)
    parser.add_argument("--echo-root", type=Path, required=True)
    parser.add_argument("--source-commit", type=source_commit, required=True)
    args = parser.parse_args(argv)
    try:
        print(bounded_receipt(run(args)))
        return 0
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        # Neither raw child output nor exception strings/paths belong in a public
        # receipt. The failing bounded run is not silently retried or certified.
        print(bounded_receipt({"schemaVersion": "latent.first-node-guide.v1", "passed": False,
                               "reason": "guide-check-failed"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
