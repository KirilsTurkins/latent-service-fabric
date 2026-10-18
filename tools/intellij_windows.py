"""Native Windows IDE task adapters; no Bash, Make, WSL or implicit installs.

Only the explicit website-prepare/browser-install tasks install their inputs.
The existing website scripts, manifests and authenticated npm derivation remain
owners. This module contains no compiler, dependency or package-manager pins.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

WEBSITE_SCRIPTS = {
    "website-start": "start", "website-check": "check", "website-test": "test",
    "website-build": "build", "website-build-root": "build:root",
    "website-test-build": "test:build", "website-browser-install": "browser:install",
}
SOURCE_SCRIPTS = {
    "docs": ("tools/validate_docs.py",),
    "schemas": ("tools/validate_repository.py", "tools/validate_foundation.py"),
    "ci-contracts": ("tools/ci_coverage.py", "tools/validate_workflow_actions.py"),
}
TASKS = frozenset(WEBSITE_SCRIPTS) | frozenset(SOURCE_SCRIPTS) | {
    "help", "tree", "test-list", "fmt", "fmt-check", "validate-source",
    "website-prepare", "website-validate",
}


def executable(name: str) -> str:
    value = shutil.which(name)
    if not value:
        raise ValueError(f"{name} is missing from PATH; install the selected toolchain first")
    return value


def bootstrap_cli(node: str) -> Path:
    """Run npm's JS entry with Node, never pass an npm.cmd path to a shell."""
    override = os.environ.get("LSF_IDE_BOOTSTRAP_NPM_CLI")
    if override:
        path = Path(override)
        if not path.is_file() or path.name != "npm-cli.js":
            raise ValueError("LSF_IDE_BOOTSTRAP_NPM_CLI must name an existing npm-cli.js")
        return path.resolve()
    candidates = [Path(node).resolve().parent / "node_modules/npm/bin/npm-cli.js"]
    launcher = shutil.which("npm.cmd")
    if launcher:
        parent = Path(launcher).resolve().parent
        candidates.extend((parent / "node_modules/npm/bin/npm-cli.js",
                           parent.parent / "npm/bin/npm-cli.js"))
    for path in candidates:
        if path.is_file():
            return path
    raise ValueError("Cannot locate bootstrap npm-cli.js; set LSF_IDE_BOOTSTRAP_NPM_CLI "
                     "to its full path. No global npm downgrade is needed.")


def website_commands(root: Path, task: str, node: str) -> list[list[str]]:
    verify = [node, "website/scripts/check-package-manager.mjs"]
    npm = [node, "website/toolchain/node_modules/npm/bin/npm-cli.js", "--prefix", "website"]
    flags = ["--ignore-scripts", "--no-audit", "--no-fund"]
    if task == "website-prepare":
        return [[sys.executable, "website/toolchain/prepare.py"],
                [node, str(bootstrap_cli(node)), "ci", "--prefix", "website/toolchain", *flags],
                verify, [*npm, "ci", *flags]]
    scripts = (["check", "test", "build", "build:root", "test:build"]
               if task == "website-validate" else [WEBSITE_SCRIPTS[task]])
    package = json.loads((root / "website/package.json").read_text(encoding="utf-8"))
    for script in scripts:
        if script not in package["scripts"]:
            raise ValueError(f"website/package.json no longer defines script {script}")
    if not (root / npm[1]).is_file():
        raise ValueError("Website package manager is not prepared; run "
                         "tools\\intellij.cmd website-prepare first")
    return [verify, *[[*npm, "run", script] for script in scripts]]


def run(root: Path, task: str) -> int:
    if task not in TASKS:
        raise ValueError(f"{task} requires the Bash/Make or Linux contributor environment; "
                         "use a configured Linux/WSL backend explicitly. "
                         "Native Windows never starts WSL automatically.")
    if task == "help":
        print("LSF native Windows contributor commands (no Bash, Make or WSL)")
        print("Usage: tools\\intellij.cmd <task>")
        for name in sorted(TASKS):
            print("  " + name)
        print("Also: ide-doctor, ide-check, ide-tests, java-client-prepare, "
              "java-client-build, java-client-test")
        print("Only website-prepare and website-browser-install install website inputs.")
        print("Runtime/contracts/full validation require their declared Linux environment.")
        return 0
    environment = os.environ.copy()
    if task.startswith("website-"):
        node = executable("node")
        package = json.loads((root / "website/package.json").read_text(encoding="utf-8"))
        result = subprocess.run([node, "--version"], cwd=root, check=False,
                                stdout=subprocess.PIPE, text=True, timeout=30)
        if result.returncode:
            return result.returncode
        if result.stdout.strip() != "v" + package["engines"]["node"]:
            raise ValueError("Node version does not match website/package.json; "
                             "select the pinned Node installation on PATH")
        commands = website_commands(root, task, node)
        # npm lifecycle commands must resolve the prepared npm, not global npm.
        environment["PATH"] = str(root / "website/toolchain/node_modules/.bin") + os.pathsep + environment.get("PATH", "")
    elif task in SOURCE_SCRIPTS or task == "validate-source":
        scripts = (sum(SOURCE_SCRIPTS.values(), ()) if task == "validate-source"
                   else SOURCE_SCRIPTS[task])
        commands = [[sys.executable, script] for script in scripts]
    elif task == "tree":
        commands = [[executable("git"), "ls-files"]]
    elif task == "test-list":
        commands = [[sys.executable, "tools/test.py", "list", "--output", "human"]]
    elif task == "fmt":
        commands = [[executable("cargo"), "fmt", "--all"]]
    else:  # fmt-check: use the existing shared recipe, not an IDE formatter.
        commands = [[sys.executable, "tools/ci_cargo.py", "run", "format"]]
    for command in commands:
        result = subprocess.run(command, cwd=root, env=environment, check=False)
        if result.returncode:
            return result.returncode
    return 0
