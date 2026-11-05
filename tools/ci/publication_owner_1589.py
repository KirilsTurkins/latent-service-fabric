#!/usr/bin/env python3
"""Review-only focused owner for #1589; never invokes a deployed service."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

SOURCE = "caaad83be6053e6e19635acbe62cb33b08bac234"
TREE = "035644bf3336ac4bc1f85a4ae5a377cb44347a09"
ROOT = Path.cwd().resolve(strict=True)
sys.path.insert(0, str(ROOT))
from tools import ci_suite_inventory as registry  # noqa: E402
from tools.owned_test_process import ProcessFailure, run_owned  # noqa: E402

# suite ID, package, target kind, target, Cargo test-name filter, exact
SPECS = (
    ("latent-audit.lib.latent-audit", "latent-audit", "lib", None,
     "durable::tests::publication::", False),
    ("latent.lib.latent", "latent", "lib", None,
     "management::retention::tests::", False),
    ("latent-control-store.lib.latent-control-store", "latent-control-store", "lib", None,
     "deployments::tests::publications::deletion::", False),
    ("latent-control-store.lib.latent-control-store", "latent-control-store", "lib", None,
     "deployments::tests::http::deletion::", False),
    ("latent-wire.lib.latent-wire", "latent-wire", "lib", None,
     "management::release::maintenance::tests::", False),
    ("latent-wire.test.management-service", "latent-wire", "test", "management_service",
     "maintenance::", False),
    ("latent-artifacts.lib.latent-artifacts", "latent-artifacts", "lib", None,
     "local_repository::tests::publication_reads::", False),
    ("latent-artifacts.lib.latent-artifacts", "latent-artifacts", "lib", None,
     "local_repository::tests::web::projection::historical_renderer_read_blocks_deletion_but_an_unrelated_web_read_does_not", True),
    ("latent-artifacts.lib.latent-artifacts", "latent-artifacts", "lib", None,
     "local_repository::tests::web::retired_web_publication_keeps_exact_reader_reference_through_eligibility_clones", True),
    ("latent.test.publication-operator", "latent", "test", "publication_operator",
     None, False),
    ("latent-artifacts.test.publication-retention", "latent-artifacts", "test", "publication_retention",
     None, False),
)
COUNTS = {
    "latent-audit.lib.latent-audit": 2,
    "latent.lib.latent": 5,
    "latent-control-store.lib.latent-control-store": 91,
    "latent-wire.lib.latent-wire": 4,
    "latent-wire.test.management-service": 5,
    "latent-artifacts.lib.latent-artifacts": 4,
    "latent.test.publication-operator": 2,
    "latent-artifacts.test.publication-retention": 17,
}
STRICT = [
    "cargo", "clippy", "-p", "latent", "-p", "latentd", "-p", "latent-testkit",
    "-p", "latent-admission", "--all-targets", "--all-features", "--locked",
    "--no-deps", "--", "-D", "warnings",
]
CASE = re.compile(r"^test (\S+) \.\.\. (ok|ignored|FAILED)(?:,.*)?$")
SUMMARY = re.compile(r"^test result: ok\. \d+ passed; 0 failed; \d+ ignored;")
OWNER_ENV = ("GH_TOKEN", "GITHUB_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
             "ACTIONS_RUNTIME_TOKEN", "ACTIONS_CACHE_URL", "ACTIONS_RESULTS_URL")


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                            text=True, timeout=30, check=True)
    require(len(result.stdout) <= 1024 * 1024, "git-output-bound")
    return result.stdout.strip()


def source_state() -> None:
    require(git("rev-parse", "HEAD") == SOURCE, "source-commit-mismatch")
    require(git("rev-parse", "HEAD^{tree}") == TREE, "source-tree-mismatch")
    require(not git("status", "--porcelain=v1", "--untracked-files=all"), "source-not-clean")
    require(not git("clean", "-ndx"), "unexpected-ignored-or-untracked-input")


def selected(spec: tuple, name: str) -> bool:
    pattern, exact = spec[4], spec[5]
    return pattern is None or (name == pattern if exact else pattern in name)


def contracts() -> dict[str, set[str]]:
    data = registry.load(ROOT / "tools/ci/suites.json")
    suites = {row["id"]: row for row in data["suites"]}
    require(set(COUNTS) <= set(suites), "missing-suite")
    required = {}
    for name, count in COUNTS.items():
        suite = suites[name]
        cases = suite.get("requiredCases", [])
        require(suite["mode"] == "libtest" and "linux-x86_64" in suite["platforms"],
                "suite-platform")
        require(len(cases) == count and len(set(cases)) == count, "suite-case-count")
        require(not set(cases).intersection(suite["expectedIgnored"]), "required-case-ignored")
        require(all(isinstance(case, str) and 0 < len(case) <= 512 for case in cases),
                "case-name-bound")
        required[name] = set(cases)
    for spec in SPECS:
        suite = suites[spec[0]]
        require(suite["package"] == spec[1] and suite["kind"] == spec[2], "suite-target-owner")
        expected_target = spec[3] if spec[2] == "test" else spec[1].replace("-", "_")
        expected_manifest = ("apps/latent/Cargo.toml" if spec[1] == "latent"
                             else "crates/" + spec[1] + "/Cargo.toml")
        expected_source = ("tests/" + spec[3] + ".rs" if spec[2] == "test"
                           else "src/lib.rs")
        require(suite["target"] == expected_target and suite["manifest"] == expected_manifest
                and suite["source"] == expected_source, "suite-source-target-owner")
    for suite, cases in required.items():
        relevant = [spec for spec in SPECS if spec[0] == suite]
        require(relevant, "suite-without-command")
        for case in cases:
            require(sum(selected(spec, case) for spec in relevant) == 1,
                    "case-selection-ambiguous-or-missing")
    require(sum(map(len, required.values())) == 130 and len(SPECS) == 11, "plan-count")
    return required


def cargo_test(spec: tuple) -> list[str]:
    _, package, kind, target, pattern, exact = spec
    command = ["cargo", "test", "--locked", "--all-features", "-p", package]
    command += ["--lib"] if kind == "lib" else ["--test", target]
    if pattern is not None:
        command.append(pattern)
    command.append("--")
    if exact:
        command.append("--exact")
    command.append("--test-threads=1")
    return command


def parse_log(raw: bytes) -> tuple[dict[str, list[str]], int]:
    require(len(raw) <= 8 * 1024 * 1024, "test-log-limit")
    results: dict[str, list[str]] = {}
    summaries = 0
    for line in raw.decode("utf-8", errors="strict").splitlines():
        if match := CASE.fullmatch(line):
            results.setdefault(match.group(1), []).append(match.group(2))
        if SUMMARY.match(line):
            summaries += 1
    return results, summaries


def verify_outcomes(required: dict[str, set[str]],
                    seen: dict[str, dict[str, list[str]]]) -> None:
    for suite, cases in required.items():
        for case in cases:
            require(seen.get(suite, {}).get(case) == ["ok"],
                    "missing-duplicate-ignored-or-failed-case:" + suite + ":" + case)


def selftest() -> None:
    required = {"suite": {"a", "b"}}
    normal, summaries = parse_log(b"test a ... ok\ntest b ... ok\ntest extra ... ok\n"
                                  b"test result: ok. 3 passed; 0 failed; 0 ignored;\n")
    require(summaries == 1, "selftest-summary")
    verify_outcomes(required, {"suite": normal})
    for bad in ({"a": ["ok"]}, {"a": ["ok"], "b": ["ignored"]},
                {"a": ["ok"], "b": ["FAILED"]},
                {"a": ["ok"], "b": ["ok", "ok"]}):
        try:
            verify_outcomes(required, {"suite": bad})
        except ValueError:
            pass
        else:
            raise ValueError("selftest-failed-open")


def paths() -> tuple[Path, Path, Path]:
    runner = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    supplied = [Path(os.environ[name]) for name in
                ("PUBLICATION_REPORTS", "PUBLICATION_TESTS", "CARGO_TARGET_DIR")]
    require(all(path.is_absolute() and not path.is_symlink() for path in supplied),
            "linked-or-relative-owner-path")
    reports, tests, target = (path.resolve(strict=True) for path in supplied)
    for child in (reports, tests, target):
        require(child != runner and child.is_relative_to(runner) and child.is_dir(),
                "non-disposable-owner-path")
    require(len({reports, tests, target}) == 3 and reports.parent == tests.parent == target.parent,
            "overlapping-owner-path")
    return reports, tests, target


def write_json(path: Path, payload: dict) -> None:
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(pending, path)


def execute(command: list[str], env: dict[str, str], log: Path, timeout: int,
            maximum: int) -> dict:
    start = time.monotonic()
    try:
        result = run_owned(command, cwd=ROOT, env=env, timeout=timeout, maximum=maximum)
    except ProcessFailure as error:
        if error.result is not None:
            log.write_bytes(error.result.output)
        raise ValueError("owned-process-" + error.category) from None
    log.write_bytes(result.output)
    require(result.cleaned and result.returncode is not None, "owned-process-not-retired")
    return {"command": command, "returncode": result.returncode,
            "cleaned": result.cleaned, "elapsedSeconds": round(time.monotonic() - start, 3),
            "log": log.name, "logBytes": len(result.output),
            "logSha256": hashlib.sha256(result.output).hexdigest()}


def base_env(target: Path) -> dict[str, str]:
    env = dict(os.environ)
    for name in OWNER_ENV:
        env.pop(name, None)
    env.update(CARGO_TARGET_DIR=str(target), CARGO_TERM_COLOR="never",
               PYTHONDONTWRITEBYTECODE="1")
    return env


def run_clippy() -> None:
    reports, tests, target = paths()
    env = base_env(target)
    temporary = tests / "clippy"
    temporary.mkdir(mode=0o700)
    env["TMPDIR"] = str(temporary)
    record = {"source": SOURCE, "tree": TREE, "ownerHead": os.environ.get("GITHUB_SHA"),
              "status": "started", "command": STRICT}
    write_json(reports / "clippy.json", record)
    try:
        source_state()
        record["result"] = execute(STRICT, env, reports / "clippy.log", 1950, 16 * 1024 * 1024)
        source_state()
        require(record["result"]["returncode"] == 0, "strict-clippy-failed")
        record["status"] = "passed"
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        record.update(status="failed", error=str(error)[:512])
        raise
    finally:
        write_json(reports / "clippy.json", record)


def run_tests() -> None:
    reports, tests, target = paths()
    required = contracts()
    seen: dict[str, dict[str, list[str]]] = {}
    record = {"source": SOURCE, "tree": TREE, "ownerHead": os.environ.get("GITHUB_SHA"),
              "status": "started", "expectedCases": 130, "commands": [],
              "required": {suite: sorted(cases) for suite, cases in required.items()}}
    write_json(reports / "publication-tests.json", record)
    try:
        source_state()
        for number, spec in enumerate(SPECS, start=1):
            env = base_env(target)
            temporary = tests / f"case-group-{number:02d}"
            temporary.mkdir(mode=0o700)
            env["TMPDIR"] = str(temporary)
            log = reports / f"tests-{number:02d}.log"
            command = cargo_test(spec)
            record["active"] = {"suite": spec[0], "command": command, "log": log.name}
            write_json(reports / "publication-tests.json", record)
            outcome = execute(command, env, log, 1800, 8 * 1024 * 1024)
            outcome["suite"] = spec[0]
            record["commands"].append(outcome)
            record.pop("active")
            write_json(reports / "publication-tests.json", record)
            source_state()
            require(outcome["returncode"] == 0, "publication-test-command-failed")
            parsed, summaries = parse_log(log.read_bytes())
            require(summaries == 1, "missing-or-duplicate-libtest-summary")
            observed = seen.setdefault(spec[0], {})
            for case, statuses in parsed.items():
                observed.setdefault(case, []).extend(statuses)
        verify_outcomes(required, seen)
        record.update(status="passed", passedRequiredCases=sum(map(len, required.values())),
                      suites={suite: sorted(cases) for suite, cases in required.items()})
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        record.update(status="failed", error=str(error)[:512])
        raise
    finally:
        write_json(reports / "publication-tests.json", record)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("check-plan", "clippy", "tests"))
    args = parser.parse_args()
    try:
        source_state()
        contracts()
        selftest()
        if args.mode == "clippy":
            run_clippy()
        elif args.mode == "tests":
            run_tests()
        print("owner-" + args.mode + ": passed")
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print("owner-" + args.mode + ": failed: " + str(error)[:512], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
