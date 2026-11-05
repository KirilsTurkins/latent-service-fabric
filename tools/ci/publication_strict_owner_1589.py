#!/usr/bin/env python3
"""Immutable-source, strict-Clippy-only diagnostic for #1589."""
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

SOURCE = "256357c3270c5317f8e78963d696507064eabcc8"
TREE = "a2e1915642bb320e867ae2972ed2668bbd3bd5a7"
ROOT = Path.cwd().resolve(strict=True)
sys.path.insert(0, str(ROOT))
from tools.ci_cargo import RECIPES  # noqa: E402
from tools.owned_test_process import ProcessFailure, run_owned  # noqa: E402

STRICT = [
    "cargo", "clippy", "-p", "latent", "-p", "latentd", "-p", "latent-testkit",
    "-p", "latent-admission", "--all-targets", "--all-features", "--locked",
    "--no-deps", "--", "-D", "warnings",
]
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


def diagnostics(raw: bytes) -> str:
    # Always expose bounded actionable output, even if artifact upload fails.
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    lines = text.splitlines()
    indexes = [i for i, line in enumerate(lines)
               if re.match(r"^error(?:\[[^]]+\])?:", line)]
    if indexes:
        chosen = []
        for index in indexes[:5]:
            chosen.extend(lines[index:index + 9])
        return "\n".join(chosen)[:12000]
    return "\n".join(lines[-40:])[-12000:]


def selftest() -> None:
    require(STRICT == ["cargo", *RECIPES["clippy"][1].args], "strict-recipe-drift")
    sample = b"noise\nerror: bad literal\n --> sample.rs:4:2\nreason\n"
    require("error: bad literal" in diagnostics(sample), "diagnostic-first-error")
    require(len(diagnostics(b"x" * 30000)) <= 12000, "diagnostic-bound")
    require("last" in diagnostics(b"previous\nlast\n"), "diagnostic-fallback")


def paths() -> tuple[Path, Path, Path]:
    runner = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    supplied = [Path(os.environ[name]) for name in
                ("PUBLICATION_REPORTS", "PUBLICATION_SCRATCH", "CARGO_TARGET_DIR")]
    require(all(path.is_absolute() and not path.is_symlink() for path in supplied),
            "linked-or-relative-owner-path")
    reports, scratch, target = (path.resolve(strict=True) for path in supplied)
    for child in (reports, scratch, target):
        require(child != runner and child.is_relative_to(runner) and child.is_dir(),
                "non-disposable-owner-path")
    require(len({reports, scratch, target}) == 3
            and reports.parent == scratch.parent == target.parent, "overlapping-owner-path")
    return reports, scratch, target


def write_json(path: Path, payload: dict) -> None:
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(pending, path)


def run_clippy() -> None:
    reports, scratch, target = paths()
    env = dict(os.environ)
    for name in OWNER_ENV:
        env.pop(name, None)
    env.update(CARGO_TARGET_DIR=str(target), CARGO_TERM_COLOR="never",
               PYTHONDONTWRITEBYTECODE="1", TMPDIR=str(scratch))
    record = {"source": SOURCE, "tree": TREE, "ownerHead": os.environ.get("GITHUB_SHA"),
              "status": "started", "command": STRICT}
    write_json(reports / "clippy.json", record)
    raw = b""
    try:
        source_state()
        start = time.monotonic()
        try:
            result = run_owned(STRICT, cwd=ROOT, env=env, timeout=2700,
                               maximum=16 * 1024 * 1024)
        except ProcessFailure as error:
            if error.result is not None:
                raw = error.result.output
            raise ValueError("owned-process-" + error.category) from None
        raw = result.output
        require(result.cleaned and result.returncode is not None, "owned-process-not-retired")
        record["result"] = {
            "returncode": result.returncode, "cleaned": result.cleaned,
            "elapsedSeconds": round(time.monotonic() - start, 3),
            "log": "clippy.log", "logBytes": len(raw),
            "logSha256": hashlib.sha256(raw).hexdigest(),
        }
        source_state()
        require(result.returncode == 0, "strict-clippy-failed")
        record["status"] = "passed"
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        record.update(status="failed", error=str(error)[:512])
        print("Bounded Clippy diagnostics:\n" + diagnostics(raw), file=sys.stderr, flush=True)
        raise
    finally:
        (reports / "clippy.log").write_bytes(raw)
        record["logBytes"] = len(raw)
        record["logSha256"] = hashlib.sha256(raw).hexdigest()
        write_json(reports / "clippy.json", record)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("check-plan", "clippy"))
    args = parser.parse_args()
    try:
        source_state()
        selftest()
        if args.mode == "clippy":
            run_clippy()
        print("strict-owner-" + args.mode + ": passed")
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print("strict-owner-" + args.mode + ": failed: " + str(error)[:512], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
