#!/usr/bin/env python3
"""Qualify a real committed local payload across protected startup recovery."""

import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

if __package__:
    from .build_process import run_bounded_result
else:
    from build_process import run_bounded_result


def verify_test_output(output: str, expected: str, *, exact: bool) -> None:
    """Require executed tests, not Cargo's successful zero-match exit status."""
    lines = output.splitlines()
    summaries = [
        re.fullmatch(
            r"test result: ok\. ([0-9]+) passed; 0 failed; 0 ignored; "
            r"0 measured; [0-9]+ filtered out; finished in .+",
            line,
        )
        for line in lines if line.startswith("test result:")
    ]
    tests = [
        line for line in lines
        if line.startswith("test ") and not line.startswith("test result:")
    ]
    suffix = " ... ok"
    names = [line[len("test "):-len(suffix)] for line in tests if line.endswith(suffix)]
    if (len(summaries) != 1 or summaries[0] is None
            or not names or len(names) != int(summaries[0].group(1))
            or len(names) != len(tests) or len(set(names)) != len(names)
            or (names != [expected] if exact else any(
                not name.startswith(expected) or name == expected for name in names))):
        raise RuntimeError("linked payload qualification did not run its selected tests")


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
            # Keep all local storage regressions in this focused lane even when
            # an unrelated earlier workspace test binary fails. Discover current
            # cases, including recovery and inventory, without freezing names.
            ([
                "cargo", "test", "--locked", "-p", "latent-local-blobs", "--lib",
                "local::", "--", "--test-threads=1",
            ], "local::", False),
            ([
                "cargo", "test", "--locked", "-p", "latent-commit", "--lib",
                "atomic::tests::payloads::export_standalone_linked_payload",
                "--", "--ignored", "--exact", "--test-threads=1",
            ], "atomic::tests::payloads::export_standalone_linked_payload", True),
            ([
                "cargo", "test", "--locked", "-p", "latentd", "--lib",
                "standalone::state::store::tests::actual_linked_payload_recovers_and_corruption_refuses_startup",
                "--", "--ignored", "--exact", "--test-threads=1",
            ], "standalone::state::store::tests::actual_linked_payload_recovers_and_corruption_refuses_startup", True),
        )
        for command, expected, exact in commands:
            # An interrupted or unretired process keeps its original files.
            retired = False
            result = run_bounded_result(command, repository, environment, 420, 16 * 1024 * 1024)
            retired = True
            output = result.stdout.decode("utf-8", errors="replace")
            sys.stderr.write(result.stderr.decode("utf-8", errors="replace"))
            sys.stdout.write(output)
            result.check_returncode()
            verify_test_output(output, expected, exact=exact)
    finally:
        if retired:
            if root.is_symlink() or root.parent != parent:
                raise RuntimeError("qualification directory changed before cleanup")
            shutil.rmtree(root)
        else:
            print("Retained qualification files because child retirement was not established", file=sys.stderr)


if __name__ == "__main__":
    main()
