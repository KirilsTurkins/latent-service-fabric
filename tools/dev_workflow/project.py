"""Language-owned templates and recipes, never a replacement guest SDK."""
from __future__ import annotations

from pathlib import Path
import re

from . import paths, snapshot
from .common import HOST_ABI, MAX_DOCUMENT, decode, digest, encode, identifier, integer, members, require, sha

LANGUAGES = {"rust": 544, "c": 545, "typescript": 546, "go": 547, "java": 548, "dotnet": 549}


def validate(value: dict) -> dict:
    members(value, {"schemaVersion", "name", "tenant", "service", "language", "template", "hostAbi",
                    "inputRoots", "exclude", "build", "artifacts", "scenarios"})
    require(value["schemaVersion"] == "latent.dev.project.v1", "project-version")
    for key in ("name", "tenant"):
        identifier(value[key])
    require(isinstance(value["service"], str) and re.fullmatch(r"[a-z][a-z0-9-]*/[a-z][a-z0-9-]*", value["service"]),
            "invalid-service")
    require(value["language"] in LANGUAGES, "unsupported-guest-language")
    template = members(value["template"], {"ownerIssue", "revision", "sha256"})
    require(template["ownerIssue"] == LANGUAGES[value["language"]]
            and isinstance(template["revision"], str) and re.fullmatch(r"[a-f0-9]{40}", template["revision"]),
            "language-template-owner-or-revision")
    sha(template["sha256"])
    require(value["hostAbi"] == HOST_ABI, "incompatible-host-abi")
    for key in ("inputRoots", "exclude"):
        require(isinstance(value[key], list) and len(value[key]) <= 64, "project-path-count")
        for name in value[key]:
            paths.relative(name)
    require(value["inputRoots"], "project-inputs-required")
    require(len(set(map(paths.alias, value["inputRoots"]))) == len(value["inputRoots"]), "duplicate-input-root")
    build = members(value["build"], {"argv", "workingDirectory", "outputRoot", "tools", "target",
                                    "hostTargets", "timeoutSeconds", "maximumOutputBytes"})
    require(build["target"] == "wasm-component", "guest-component-target-required")
    require(isinstance(build["hostTargets"], list) and 0 < len(build["hostTargets"]) <= 4
            and set(build["hostTargets"]) <= {"linux-x86_64", "windows-x86_64"}, "unsupported-guest-build-host")
    require(isinstance(build["argv"], list) and 0 < len(build["argv"]) <= 64, "recipe-argv-limit")
    for argument in build["argv"]:
        require(isinstance(argument, str) and 0 < len(argument) <= 4096 and "\0" not in argument, "recipe-argument")
    for key in ("workingDirectory", "outputRoot"):
        paths.relative(build[key])
    require(isinstance(build["tools"], list) and 0 < len(build["tools"]) <= 16, "recipe-tools-required")
    tool_names = set()
    for tool in build["tools"]:
        members(tool, {"name", "path", "version", "sha256"})
        identifier(tool["name"])
        require(tool["name"] not in tool_names, "duplicate-recipe-tool")
        tool_names.add(tool["name"])
        paths.relative(tool["path"])
        sha(tool["sha256"])
        require(isinstance(tool["version"], str) and 0 < len(tool["version"]) <= 80, "recipe-tool-version")
    require(build["argv"][0] in tool_names, "recipe-executable-must-be-pinned-tool")
    integer(build["timeoutSeconds"], 1, 900)
    integer(build["maximumOutputBytes"], 1, 4 * 1024 * 1024)
    artifacts = members(value["artifacts"], {"component", "capsule", "contracts", "deployment"},
                        {"packageSource", "packageRoot", "evidence"})
    for name in artifacts.values():
        paths.relative(name)
        require(name.startswith(build["outputRoot"] + "/"), "artifact-outside-output-root")
    require(isinstance(value["scenarios"], list) and 0 < len(value["scenarios"]) <= 16, "scenario-file-limit")
    for name in value["scenarios"]:
        paths.relative(name)
    require(all(not paths.excluded(name) for name in value["inputRoots"]), "excluded-input-root")
    # Build output must never become a source input, including a parent input.
    require(not any(build["outputRoot"] == name or build["outputRoot"].startswith(name + "/")
                    for name in value["inputRoots"]), "build-output-overlaps-source-inputs")
    return value


def load(root: Path) -> tuple[dict, str]:
    raw = paths.read(root, "latent.project.json", MAX_DOCUMENT)
    return validate(decode(raw)), digest(raw)


def trust_identity(project: dict) -> str:
    # Source edits can reuse trust; any recipe/tool/path/ABI change invalidates it.
    return digest(encode(validate(project)))


def scaffold(template_root: Path, destination: Path, manifest: dict, expected: str) -> dict:
    """Template bytes must already belong to an authenticated tool inventory."""
    members(manifest, {"schemaVersion", "project", "snapshot"})
    require(manifest["schemaVersion"] == "latent.dev.template.v1", "template-version")
    require(digest(encode(manifest)) == sha(expected), "template-identity-mismatch")
    project = validate(manifest["project"])
    record = manifest["snapshot"]
    snapshot.validate(record)
    require(project["template"]["sha256"] == record["identity"], "template-source-identity-mismatch")
    require("latent.project.json" not in {item["path"] for item in record["files"]}, "template-descriptor-collision")
    content = {item["path"]: paths.read(template_root, item["path"]) for item in record["files"]}
    snapshot.materialize(destination, record, content)
    paths.write_new(destination / "latent.project.json", encode(project))
    if ".gitignore" not in content:
        paths.write_new(destination / ".gitignore", b".latent/\noutput/\n*.log\n")
    return {"project": project["name"], "template": expected, "trustRequired": True}
