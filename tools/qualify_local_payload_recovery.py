#!/usr/bin/env python3
"""Qualify a real committed local payload across protected startup recovery."""

import os
from pathlib import Path
import shutil
import sys
import tempfile

if __package__:
    from .build_process import run_bounded_result
else:
    from build_process import run_bounded_result


def main() -> None:
    repository = Path(__file__).resolve().parent.parent
    parent = Path(tempfile.gettempdir()).resolve(strict=True)
    created = Path(tempfile.mkdtemp(prefix="lsf-linked-payload-", dir=parent))
    root = created.resolve(strict=True)
    if created.is_symlink() or root.parent != parent:
        raise RuntimeError("invalid qualification directory")
    retired = True
    try:
        environment = os.environ.copy()
        environment["TMPDIR"] = str(root)
        environment["LSF_LINKED_PAYLOAD_REPORT"] = str(root / "producer-root.txt")
        commands = (
            ([
                "cargo", "test", "--locked", "-p", "latent-commit", "--lib",
                "atomic::tests::payloads::export_standalone_linked_payload",
                "--", "--ignored", "--exact", "--test-threads=1",
            ], "atomic::tests::payloads::export_standalone_linked_payload"),
            ([
                "cargo", "test", "--locked", "-p", "latentd", "--lib",
                "standalone::state::store::tests::actual_linked_payload_recovers_and_corruption_refuses_startup",
                "--", "--ignored", "--exact", "--test-threads=1",
            ], "standalone::state::store::tests::actual_linked_payload_recovers_and_corruption_refuses_startup"),
        )
        for command, expected in commands:
            # An interrupted or unretired process keeps its original files.
            retired = False
            result = run_bounded_result(command, repository, environment, 420, 16 * 1024 * 1024)
            retired = True
            output = result.stdout.decode("utf-8", errors="replace")
            sys.stderr.write(result.stderr.decode("utf-8", errors="replace"))
            sys.stdout.write(output)
            result.check_returncode()
            lines = output.splitlines()
            if lines.count(f"test {expected} ... ok") != 1 or not any(
                line.startswith("test result: ok. 1 passed; 0 failed; 0 ignored;")
                for line in lines
            ):
                raise RuntimeError("linked payload qualification did not run exactly one expected test")
    finally:
        if retired:
            if root.is_symlink() or root.parent != parent:
                raise RuntimeError("qualification directory changed before cleanup")
            shutil.rmtree(root)
        else:
            print("Retained qualification files because child retirement was not established", file=sys.stderr)


if __name__ == "__main__":
    main()
