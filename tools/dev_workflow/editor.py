"""Generate explicit process tasks for the same frontend, with no editor lifecycle."""
from __future__ import annotations

import json
from pathlib import Path

from . import paths
from .common import identifier, require

PATTERN = r"^LSF (.*):([0-9]+):([0-9]+): (error|warning|info) ([A-Za-z0-9_-]*): (.*)$"


def configuration(frontend: Path, state_root: Path, workspace: str, tool_root: str | None) -> dict:
    identifier(workspace)
    for path in (frontend, state_root):
        paths.absolute(path)
        require("${" not in str(path), "editor-variable-in-literal-path")
    if tool_root is not None:
        require(tool_root.startswith("/") and "${" not in tool_root and "\0" not in tool_root,
                "explicit-linux-tool-root-required")
    matcher = {"owner": "lsf", "source": "LSF", "fileLocation": "absolute",
               "pattern": {"regexp": PATTERN, "file": 1, "line": 2, "column": 3, "severity": 4, "code": 5, "message": 6}}
    base = ["--state-root", str(state_root), "--editor-diagnostics", "dev"]
    selected = ["--workspace", workspace]
    build = ["--project", "${workspaceFolder}", "--tool-root", tool_root or "${input:lsfToolRoot}"]
    commands = {
        "init another project": ["init", "${input:lsfDestination}", "--bundle", "${input:lsfBundle}",
                                 "--template", "${input:lsfTemplate}", "--template-sha256", "${input:lsfTemplateSha}"],
        "trust reviewed recipe": ["trust", *selected, "--project", "${workspaceFolder}"],
        "doctor": ["doctor", *selected],
        "build": ["build", *selected, *build],
        "up": ["up", *selected],
        "watch": ["up", *selected, *build, "--watch"],
        "test isolated workspace": ["test", "--workspace", "${input:lsfTestWorkspace}", "--environment", "node"],
        "status": ["status", *selected],
        "recover original operation": ["recover", *selected],
        "logs": ["logs", *selected],
        "down": ["down", *selected],
    }
    tasks = [{"label": "LSF: " + label, "type": "process", "command": str(frontend), "args": [*base, *args],
              "options": {"cwd": "${workspaceFolder}"}, "problemMatcher": [matcher] if label in {"build", "watch"} else [],
              "runOptions": {"instanceLimit": 1, "runOn": "default"},
              "presentation": {"reveal": "always", "panel": "dedicated", "clear": False, "echo": True}}
             for label, args in commands.items()]
    inputs = [("lsfDestination", "New project directory (must not exist)"), ("lsfBundle", "Already authenticated template bundle ID"),
              ("lsfTemplate", "Language-owned template name"), ("lsfTemplateSha", "Exact template manifest SHA-256"),
              ("lsfTestWorkspace", "Separately provisioned test- workspace name")]
    if tool_root is None:
        inputs.append(("lsfToolRoot", "Explicit authenticated guest tool directory on the Linux filesystem"))
    return {"version": "2.0.0", "tasks": tasks,
            "inputs": [{"id": name, "type": "promptString", "description": description} for name, description in inputs]}


def generate(project: Path, frontend: Path, state_root: Path, workspace: str, tool_root: str | None) -> dict:
    with paths.opened(frontend.parent, frontend.name), paths.directory(project):
        value = configuration(frontend, state_root, workspace, tool_root)
        directory = project / ".vscode"
        if not directory.exists():
            paths.new_directory(directory)
        with paths.directory(directory):
            require(not (directory / "tasks.json").exists(), "existing-editor-tasks-preserved-merge-manually")
            paths.write_new(directory / "tasks.json", (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())
    return {"workspace": workspace, "tasks": str(directory / "tasks.json"), "taskCount": len(value["tasks"]),
            "automaticExecution": False, "recipeTrustRequired": True,
            "cancellation": "interrupt-watch-then-inspect-status-before-claiming-remote-cleanup"}
