"""Select security jobs from complete Git changes; docs never select a build."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.security_common import SecurityError, changed_paths, decode_json, read_file, relative_path, require
from tools.security_findings import load_exceptions
from tools.security_inventory import is_manifest

SOURCE_EXTENSIONS = frozenset({".rs", ".py", ".js", ".ts", ".mjs", ".cjs", ".tsx", ".go", ".java",
                              ".cs", ".c", ".h", ".cc", ".cpp", ".hpp", ".sh", ".ps1"})


def classify(paths: list[str]) -> dict[str, bool]:
    require(len(paths) <= 20000, "change-count-limit")
    paths = [relative_path(path) for path in paths]
    if not paths:
        return dict.fromkeys(("rustsec", "dependencies", "static", "selftest"), True)
    if all(PurePosixPath(path).suffix in {".md", ".svg"} for path in paths):
        return dict.fromkeys(("rustsec", "dependencies", "static", "selftest"), False)
    controls = any(path.startswith((".github/security/", "tools/security", "tools/tests/test_security",
                                    ".github/workflows/security-"))
                   or path in {"tools/toolchain.toml", "tools/validate_workflow_actions.py", "tools/workflow_action_yaml.py"}
                   for path in paths)
    workflows = any(path.startswith(".github/workflows/") or PurePosixPath(path).name in {"action.yml", "action.yaml"}
                    or path == ".github/dependabot.yml" for path in paths)
    rustsec = controls or any(PurePosixPath(path).name in {"Cargo.lock", "Cargo.toml", "rust-toolchain.toml"}
                              or path.startswith((".cargo/", "wit/platform/", "crates/latent-wasmtime/src/host/",
                                                  "crates/latent-wasmtime/src/surface", "crates/latent-component-bindings/"))
                              for path in paths)
    return {"rustsec": rustsec, "dependencies": controls or any(is_manifest(path) for path in paths),
            "static": controls or workflows or any(PurePosixPath(path).suffix in SOURCE_EXTENSIONS for path in paths),
            "selftest": controls or workflows}


def select(event_name: str, event: dict, repo: Path, revision: str) -> dict:
    require(re.fullmatch(r"[0-9a-f]{40}", revision) is not None, "invalid-source-revision")
    if event_name in {"schedule", "workflow_dispatch"}:
        return {"refs": ["development", "release"], "changed_paths": None,
                **dict.fromkeys(("rustsec", "dependencies", "static", "selftest"), True)}
    require(event_name in {"pull_request", "push"}, "unsupported-security-event")
    base = event["pull_request"]["base"]["sha"] if event_name == "pull_request" else event["before"]
    require(re.fullmatch(r"[0-9a-f]{40}", base) is not None, "invalid-base-revision")
    if base == "0" * 40:
        paths = []
    else:
        paths = changed_paths(repo, base, revision)
    return {"refs": [revision], "changed_paths": len(paths), **classify(paths)}


def validate_results(results: dict) -> bool:
    if results.get("scope", {}).get("result") != "success" or results.get("secrets", {}).get("result") != "success":
        return False
    outputs = results["scope"].get("outputs", {})
    for job, output in (("rustsec", "rustsec"), ("dependencies", "dependencies"),
                        ("static", "static"), ("self-test", "selftest")):
        if outputs.get(output) not in {"true", "false"}:
            return False
        expected = "success" if outputs[output] == "true" else "skipped"
        if results.get(job, {}).get("result") != expected:
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    try:
        load_exceptions()
        event_path = Path(os.environ["GITHUB_EVENT_PATH"])
        event = decode_json(read_file(event_path.parent, event_path.name, 1024 * 1024))
        selection = select(os.environ["GITHUB_EVENT_NAME"], event, arguments.repo.resolve(), os.environ["GITHUB_SHA"])
        if "GITHUB_OUTPUT" in os.environ:
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                output.write(f"matrix={json.dumps({'ref': selection['refs']}, separators=(',', ':'))}\n")
                for name in ("rustsec", "dependencies", "static", "selftest"):
                    output.write(f"{name}={str(selection[name]).lower()}\n")
        print(json.dumps(selection, sort_keys=True))
        return 0
    except (SecurityError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        code = str(error) if isinstance(error, SecurityError) else "security-scope-unavailable"
        print(f"Security scope failed: {code}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
