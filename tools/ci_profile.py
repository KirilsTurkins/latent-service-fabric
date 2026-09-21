#!/usr/bin/env python3
"""Select docs/website/full from complete Git diffs; uncertainty selects full."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass

MAX_EVENT_BYTES = 1_048_576
MAX_GIT_BYTES = 8_388_608
MAX_PATHS = 100_000
MAX_PATH_BYTES = 4096
GIT_TIMEOUT_SECONDS = 30
ROOT_DOCS = frozenset({
    "README.md", "ARCHITECTURE.md", "CONTRIBUTING.md", "VALIDATION.md", "CHANGELOG.md",
    "SECURITY.md", "CODE_OF_CONDUCT.md",
})
README_AREAS = frozenset({
    "apps", "crates", "sdk", "tools", "tests", "examples", "schemas", "api", "wit",
})
FROZEN_DOCS = frozenset({"docs/testing/phase-2-resource-profile.md"})
ISSUE_FORM_DOCS = frozenset({
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/architecture.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
})


class ProfileError(Exception):
    """A bounded diagnostic which must not produce an accepted profile."""


@dataclass(frozen=True)
class Decision:
    profile: str
    reason: str
    changed_files: int
    renderer: bool = True


def documentation_path(name: str) -> bool:
    # Reject ambiguous path spelling rather than normalize it into the allowlist.
    if (not name or len(name.encode("utf-8")) > MAX_PATH_BYTES
            or "\\" in name or any(ord(char) < 32 for char in name)):
        return False
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    if name in FROZEN_DOCS or parts[0] == "benchmarks":
        return False
    if name in ROOT_DOCS or name in ISSUE_FORM_DOCS:
        return True
    path = PurePosixPath(name)
    if len(parts) > 1 and parts[0] in {"docs", "adr", "research", "rfcs"}:
        if path.suffix == ".md":
            return True
    if len(parts) > 2 and parts[:2] == ["docs", "assets"] and path.suffix == ".svg":
        return True
    return len(parts) > 1 and parts[0] in README_AREAS and path.name == "README.md"


def classify_paths(paths: list[str]) -> Decision:
    if not paths:
        return Decision("full", "empty-diff", 0)
    if len(paths) > MAX_PATHS:
        return Decision("full", "diff-limit", len(paths))
    if all(documentation_path(path) for path in paths):
        return Decision("docs", "documentation-only", len(paths), renderer=False)
    if all(documentation_path(path) or website_path(path) for path in paths):
        return Decision("website", "website-only", len(paths), renderer=False)
    renderer = any(
        path in {"Cargo.toml", "Cargo.lock", ".cargo/config.toml", "rust-toolchain.toml",
                 ".github/workflows/ci.yml", "tools/ci_profile.py", "tools/toolchain.toml",
                 "tools/ci_rust_artifacts.py", "tools/tests/test_angular_t1_workflow.py",
                 "tools/run_angular_t1_workflow.py", "apps/latent/src/args/web.rs",
                 "tools/run_phase3_resource_acceptance.py",
                 "api/proto/latent/control/v1/release.proto",
                 "tools/native_loader_boundary.py", "schemas/capsule-manifest.schema.json",
                 "schemas/angular-build.schema.json", "schemas/web-build-observation.schema.json",
                 "schemas/builder-policy.schema.json",
                 "tools/tests/test_build_angular_package.py", "tools/tests/test_angular_build_runner.py",
                 "tools/tests/test_build_inventory.py", "tools/tests/test_web_admission_schemas.py",
                 "schemas/node-renderer-profile.schema.json"}
        or path.startswith(("examples/renderer-profile/", "tools/renderer-profile/", "tools/angular-renderer-adapter/",
                            "examples/browser-boundary/", "tools/browser-boundary/", "tools/tests/browser_hydration.test.mjs",
                            "tools/tests/browser_application.test.mjs",
                            "examples/angular-application/", "tools/angular_build/", "tools/build_angular_package.py",
                            "tools/run_angular_build_tests.py", "tools/check_angular_hydration.mjs",
                            "tools/phase3_web_", "apps/latent/src/management/web",
                            "tools/phase3_resource_", "tools/tests/test_phase3_resource",
                            "crates/latent-wire/src/management/",
                            "tools/build_inventory", "tools/build_sbom_inputs.py", "tools/build_process",
                            "tools/build_observation.py", "tools/build_snapshot.py",
                            "crates/latent-signing/", "crates/latent-policy/", "apps/latent/src/package",
                            "apps/latent/src/args/package.rs",
                            "tools/build_angular_renderer.py", "tools/run_angular_renderer_tests.py",
                            "crates/latent-manifest/", "crates/latent-packaging/", "crates/latent-artifacts/",
                            "apps/latentd/", "crates/latent-executor/", "crates/latent-node/", "crates/latent-ingress/",
                            "crates/latent-wasmtime/", "crates/latent-component-bindings/",
                            "crates/latent-core/", "crates/latent-admission/", "crates/latent-control-store/",
                            "wit/platform/web/", "wit/platform/context/", "wit/host-abi-"))
        for path in paths
    )
    return Decision("full", "non-documentation-path", len(paths), renderer=renderer)


def website_path(name: str) -> bool:
    """Allow only reviewed site source kinds; shared/product inputs stay full."""
    if (not name or len(name.encode("utf-8")) > MAX_PATH_BYTES or "\\" in name
            or any(ord(char) < 32 for char in name)
            or any(part in ("", ".", "..") for part in name.split("/"))):
        return False
    if name in {"docs/assets/illustrations.json", "docs/assets/lsf-palette.json"}:
        return True
    if name.startswith(("docs/", "adr/")) and name.endswith(".mdx"):
        return True
    if not name.startswith("website/") or name.startswith((
            "website/build/", "website/.docusaurus/", "website/.generated/",
            "website/node_modules/")):
        return False
    return PurePosixPath(name).suffix in {
        ".mjs", ".cjs", ".js", ".ts", ".tsx", ".css", ".json", ".md", ".mdx", ".svg", ".png",
    }


def git_command(repo: Path, *arguments: str, allow_failure: bool = False) -> bytes | None:
    """Bound stdout and duration, including fetch; do not invoke hooks or a shell."""
    try:
        process = subprocess.Popen(
            ["git", "-c", "gc.auto=0", *arguments], cwd=repo,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat",
                 "GIT_NO_LAZY_FETCH": "1", "GIT_NO_REPLACE_OBJECTS": "1"},
            start_new_session=os.name == "posix",
        )
    except OSError as error:
        raise ProfileError("git-unavailable") from error
    expired = threading.Event()

    def stop() -> None:
        try:
            if os.name == "posix":
                # A fetch helper may inherit stdout; retire the owned group too.
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except OSError:
            pass

    def expire() -> None:
        expired.set()
        stop()

    timer = threading.Timer(GIT_TIMEOUT_SECONDS, expire)
    timer.daemon = True
    timer.start()
    try:
        assert process.stdout is not None
        output = process.stdout.read(MAX_GIT_BYTES + 1)
        if len(output) > MAX_GIT_BYTES:
            stop()
            raise ProfileError("git-output-limit")
        process.wait(timeout=5)
        if expired.is_set():
            raise ProfileError("git-timeout")
        if process.returncode:
            if allow_failure:
                return None
            raise ProfileError("git-command-failed")
        return output
    except subprocess.TimeoutExpired as error:
        raise ProfileError("git-timeout") from error
    finally:
        timer.cancel()
        timer.join()
        if process.poll() is None:
            stop()
        process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()


def sha(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", value) is None:
        raise ProfileError("invalid-commit-identity")
    return value.lower()


def commit_exists(repo: Path, identity: str) -> bool:
    value = git_command(repo, "rev-parse", "--verify", identity + "^{commit}", allow_failure=True)
    return value is not None and value.strip() == identity.encode("ascii")


def comparison_base(repo: Path, base: str, head: str, pull_request: bool) -> str | None:
    def available() -> str | None:
        if not commit_exists(repo, base) or not commit_exists(repo, head):
            return None
        if not pull_request:
            return base
        value = git_command(repo, "merge-base", "--all", base, head, allow_failure=True)
        if value is None:
            return None
        identities = value.splitlines()
        if len(identities) != 1:
            return None
        try:
            return sha(identities[0].decode("ascii"))
        except (UnicodeError, ProfileError):
            return None

    found = available()
    if found is not None:
        return found
    for depth in (128, 512):
        git_command(repo, "fetch", "--no-tags", "--filter=blob:none", f"--depth={depth}",
                    "origin", base, head)
        found = available()
        if found is not None:
            return found
    return None


def diff_paths(output: bytes) -> list[str]:
    if not output:
        return []
    if not output.endswith(b"\0"):
        raise ProfileError("invalid-git-diff")
    entries = output[:-1].split(b"\0")
    if len(entries) > MAX_PATHS or any(not item or len(item) > MAX_PATH_BYTES for item in entries):
        raise ProfileError("git-diff-limit")
    try:
        return [entry.decode("utf-8", errors="strict") for entry in entries]
    except UnicodeError as error:
        raise ProfileError("invalid-git-path") from error


def classify_event(event_name: str, event: dict, repo: Path) -> Decision:
    if event_name == "workflow_dispatch":
        return Decision("full", "manual-dispatch", 0)
    if event_name == "pull_request":
        try:
            base = sha(event["pull_request"]["base"]["sha"])
            head = sha(event["pull_request"]["head"]["sha"])
        except (KeyError, TypeError) as error:
            raise ProfileError("invalid-pull-request-event") from error
        pull_request = True
    elif event_name == "push":
        if event.get("before") is None or event.get("after") is None:
            return Decision("full", "missing-push-boundary", 0)
        base, head = sha(event["before"]), sha(event["after"])
        if int(base, 16) == 0 or int(head, 16) == 0:
            return Decision("full", "new-or-deleted-branch", 0)
        pull_request = False
    else:
        return Decision("full", "unclassified-event", 0)
    start = comparison_base(repo, base, head, pull_request)
    if start is None:
        return Decision("full", "history-unavailable", 0)
    output = git_command(repo, "diff", "--no-ext-diff", "--no-textconv", "--name-only",
                         "-z", "--no-renames", start, head, "--")
    assert output is not None
    decision = classify_paths(diff_paths(output))
    if decision.profile in {"docs", "website"}:
        # Links and executable modes never acquire a narrow validation profile.
        modes = git_command(repo, "diff", "--no-ext-diff", "--no-textconv", "--raw",
                            "-z", "--no-renames", start, head, "--")
        assert modes is not None
        records = modes.split(b"\0")
        for header in records[::2]:
            if not header:
                continue
            fields = header.split()
            if (len(fields) != 5 or not fields[0].startswith(b":")
                    or fields[0][1:] not in {b"000000", b"100644"}
                    or fields[1] not in {b"000000", b"100644"}):
                return Decision("full", "non-documentation-mode", decision.changed_files)
    return decision


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProfileError("duplicate-event-key")
        result[key] = value
    return result


def read_event(path: Path) -> dict:
    with path.open("rb") as source:
        encoded = source.read(MAX_EVENT_BYTES + 1)
    if len(encoded) > MAX_EVENT_BYTES:
        raise ProfileError("event-size-limit")
    event = json.loads(encoded, object_pairs_hook=unique_object)
    if not isinstance(event, dict):
        raise ProfileError("invalid-event-object")
    return event


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME"))
    parser.add_argument("--event-path", default=os.environ.get("GITHUB_EVENT_PATH"), type=Path)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"), type=Path)
    parser.add_argument("--github-step-summary", default=os.environ.get("GITHUB_STEP_SUMMARY"), type=Path)
    args = parser.parse_args(argv)
    try:
        if not args.event_name or args.event_path is None:
            raise ProfileError("missing-event-input")
        decision = classify_event(args.event_name, read_event(args.event_path), args.repo)
        summary = (f"CI profile: {decision.profile}; reason: {decision.reason}; "
                   f"changed paths: {decision.changed_files}; renderer: {decision.renderer}")
        if args.github_step_summary:
            with args.github_step_summary.open("a", encoding="utf-8") as target:
                target.write(summary + "\n")
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as target:
                target.write(f"profile={decision.profile}\nreason={decision.reason}\n"
                             f"changed_files={decision.changed_files}\n"
                             f"renderer={str(decision.renderer).lower()}\n")
        print(summary)
        return 0
    except (ProfileError, OSError, ValueError, TypeError, RecursionError, subprocess.SubprocessError) as error:
        reason = str(error) if isinstance(error, ProfileError) else "classification-failed"
        print(f"CI profile error: {reason}; no profile accepted", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
