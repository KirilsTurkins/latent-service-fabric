"""Real bounded scanner canaries; generated markers are not credentials."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.security_advisories import audit_lock, fetch_rustsec
from tools.security_common import ROOT, SecurityError, read_file, require
from tools.security_content import scan_secrets, source_findings, stage_text, workflow_findings
from tools.security_install import verify_tool


def fixture_secrets(root: Path, paths: list[str], binary: Path, scratch: Path) -> list:
    with tempfile.TemporaryDirectory(dir=scratch, prefix="text-") as directory:
        staged = Path(directory) / "input"
        selected, binaries = stage_text(root, staged, paths)
        require(binaries == 0, "unexpected-binary-fixture")
        return scan_secrets(staged, selected, binary, scratch)


def exercise(tools: Path, scratch: Path) -> dict:
    cargo = verify_tool("cargo-audit", tools)
    gitleaks = verify_tool("gitleaks", tools)
    zizmor = verify_tool("zizmor", tools)
    database, identity = fetch_rustsec(scratch)
    fixtures = ROOT / "tools/security_fixtures"
    clean, unused = audit_lock(read_file(fixtures, "clean.lock.fixture"), "clean.lock.fixture", cargo, database, identity, scratch)
    require(not clean, "clean-dependency-canary-failed")
    vulnerable, unused = audit_lock(read_file(fixtures, "vulnerable.lock.fixture"), "vulnerable.lock.fixture",
                                    cargo, database, identity, scratch)
    require(any(item.finding == "RUSTSEC-2020-0071" for item in vulnerable), "vulnerable-dependency-canary-missed")
    failed_database = scratch / "unavailable"
    failed_database.mkdir()
    with patch("tools.security_advisories.RUSTSEC_URL", "https://127.0.0.1:1/unavailable"):
        try:
            fetch_rustsec(failed_database)
        except SecurityError:
            pass
        else:
            require(False, "unavailable-database-canary-passed")
    content = scratch / "content"
    content.mkdir()
    document = content / "fixture.md"
    document.write_text("Harmless public documentation.\n", encoding="utf-8")
    require(not fixture_secrets(content, ["fixture.md"], gitleaks, scratch), "clean-secret-canary-failed")
    marker = "LSF_SYNTHETIC_TEST_ONLY_" + "A1" * 16
    document.write_text(marker + " # gitleaks:allow\n", encoding="utf-8")
    detected = fixture_secrets(content, ["fixture.md"], gitleaks, scratch)
    require(any(item.finding == "lsf-synthetic-secret" for item in detected), "secret-canary-missed")
    document.unlink()
    svg = content / "fixture.svg"
    svg.write_text(f'<svg xmlns="http://www.w3.org/2000/svg"><text>{marker}</text></svg>', encoding="utf-8")
    require(bool(fixture_secrets(content, ["fixture.svg"], gitleaks, scratch)), "svg-secret-canary-missed")
    program = content / "tools/fixture.py"
    program.parent.mkdir()
    program.write_text("value = 1\n", encoding="utf-8")
    require(not source_findings(content, ["tools/fixture.py"]), "clean-source-canary-failed")
    program.write_text("value = ev" + "al(user_input)\n", encoding="utf-8")
    require(bool(source_findings(content, ["tools/fixture.py"])), "source-rule-canary-missed")
    workflow = content / ".github/workflows/fixture.yml"
    workflow.parent.mkdir(parents=True)
    prefix = "name: Fixture\non: pull_request\npermissions:\n  contents: read\njobs:\n  check:\n    runs-on: ubuntu-24.04\n    steps:\n"
    workflow.write_text(prefix + "      - run: echo harmless\n", encoding="utf-8")
    paths = [".github/workflows/fixture.yml"]
    require(not workflow_findings(content, paths, zizmor, scratch), "clean-workflow-canary-failed")
    workflow.write_text(prefix + '      - run: echo "${{ github.event.pull_request.title }}"\n', encoding="utf-8")
    detected = workflow_findings(content, paths, zizmor, scratch)
    require(any(item.finding == "template-injection" for item in detected), "workflow-injection-canary-missed")
    return {"schema": 1, "status": "pass", "database": identity,
            "canaries": ["clean-lock", "RUSTSEC-2020-0071", "unavailable-database", "clean-documentation",
                         "synthetic-secret-despite-inline-ignore", "svg-secret", "source-pass-and-fail", "workflow-pass-and-fail"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools", required=True, type=Path)
    parser.add_argument("--scratch", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        arguments.scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=arguments.scratch, prefix="canary-") as directory:
            report = exercise(arguments.tools.resolve(), Path(directory))
        print(json.dumps(report, sort_keys=True))
        return 0
    except (SecurityError, OSError, ValueError, KeyError, TypeError) as error:
        code = str(error) if isinstance(error, SecurityError) else "canary-tool-or-data-unavailable"
        print(json.dumps({"schema": 1, "status": "error", "code": code}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
