"""Run the scoped baseline and emit only compact, source-free finding metadata."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import security_advisories, security_content
from tools.security_common import POLICY, ROOT, SecurityError, digest, read_file, run
from tools.security_findings import apply_exceptions, load_exceptions
from tools.security_install import tool_lock


def scan(mode: str, repo: Path, scratch: Path, tools: Path, base: str = "") -> tuple[int, dict]:
    exceptions = load_exceptions()
    if mode == "rustsec":
        findings, observation = security_advisories.rustsec(repo, scratch, tools)
    elif mode == "dependencies":
        findings, observation = security_advisories.dependencies(repo)
    elif mode == "secrets":
        findings, observation = security_content.secrets(repo, scratch, tools, base)
    else:
        findings, observation = security_content.static(repo, scratch, tools)
    remaining, waived = apply_exceptions(findings, exceptions)
    _, revision = run(["git", "-C", str(repo), "rev-parse", "HEAD"], scratch, timeout=15)
    _, control = run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], scratch, timeout=15)
    policy_hashes = {path.name: digest(read_file(POLICY, path.name)) for path in sorted(POLICY.iterdir()) if path.is_file()}
    report = {"schema": 1, "mode": mode, "status": "findings" if remaining else "pass",
              "source_revision": revision.decode().strip(), "control_revision": control.decode().strip(),
              "observed_at": datetime.now(timezone.utc).isoformat(), "policy_sha256": policy_hashes,
              "tools": tool_lock()["tools"], "observation": observation,
              "finding_count": len(remaining), "exception_count": len(waived),
              "findings": [item.public() for item in remaining[:50]],
              "excepted_findings": [item.public() for item in waived[:50]]}
    return int(bool(remaining)), report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("rustsec", "dependencies", "secrets", "static"))
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--tools", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--base", default="")
    arguments = parser.parse_args()
    try:
        arguments.scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="lsf-security-", dir=arguments.scratch) as temporary:
            status, report = scan(arguments.mode, arguments.repo.resolve(), Path(temporary), arguments.tools.resolve(), arguments.base)
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as target:
                target.write(f"### Security {arguments.mode}\n\nResult: {report['status']}; "
                             f"findings: {report['finding_count']}; exact exceptions: {report['exception_count']}.\n\n"
                             f"Source: `{report['source_revision']}`; controls: `{report['control_revision']}`.\n\n"
                             "The log contains only tool/database identity and redacted metadata, not matches.\n")
        return status
    except (SecurityError, OSError, ValueError, KeyError, TypeError, RecursionError, subprocess.SubprocessError) as error:
        code = str(error) if isinstance(error, SecurityError) else "invalid-or-unavailable-scan-data"
        print(json.dumps({"schema": 1, "mode": arguments.mode, "status": "error", "code": code}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
