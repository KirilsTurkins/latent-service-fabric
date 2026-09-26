#!/usr/bin/env python3
"""Validate immutable GitHub Action identities in executable workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
import stat
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import workflow_action_yaml
from yaml import YAMLError

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_ROOT = ROOT / ".github" / "workflows"
MAX_WORKFLOW_BYTES = 128 * 1024
FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
OWNER_OR_REPO = re.compile(r"^[A-Za-z0-9_.-]+$")
DOCKER_DIGEST = re.compile(r"^docker://[^\s@]+@sha256:[0-9a-fA-F]{64}$")
MAX_EXECUTABLE_FILES = 256


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    message: str

    def render(self, root: Path = ROOT) -> str:
        try:
            display = self.path.relative_to(root)
        except ValueError:
            display = self.path
        return f"{display}:{self.line}: {self.message}"


def _workflow_paths(root: Path) -> list[Path]:
    workflow_root = root / ".github" / "workflows"
    if not workflow_root.exists():
        return []
    return sorted(
        path
        for path in workflow_root.iterdir()
        if path.name.endswith((".yml", ".yaml"))
    )


def _read_workflow(path: Path) -> tuple[str | None, list[Finding]]:
    try:
        metadata = path.lstat()
    except OSError as error:
        return None, [Finding(path, 1, f"cannot inspect workflow: {error}")]

    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        return None, [Finding(path, 1, "workflow must be an ordinary regular file")]
    if metadata.st_size > MAX_WORKFLOW_BYTES:
        return None, [
            Finding(
                path,
                1,
                f"workflow exceeds {MAX_WORKFLOW_BYTES} byte policy ceiling",
            )
        ]

    try:
        with path.open("rb") as source:
            payload = source.read(MAX_WORKFLOW_BYTES + 1)
        if len(payload) > MAX_WORKFLOW_BYTES:
            return None, [Finding(path, 1, "workflow exceeds byte policy ceiling")]
        return payload.decode("utf-8", errors="strict"), []
    except (OSError, UnicodeDecodeError) as error:
        return None, [Finding(path, 1, f"workflow must be readable UTF-8: {error}")]


def _validate_local(path: Path, line: int, reference: str) -> list[Finding]:
    relative = reference[2:]
    if not relative:
        return [Finding(path, line, "local action reference must name a repository path")]
    parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in parts) or "\\" in relative or ":" in relative:
        return [Finding(path, line, f"unsafe local action reference: {reference}")]
    if "@" in reference:
        return [Finding(path, line, "local action references must not append an @ revision")]
    if "${{" in reference or any(c.isspace() for c in reference):
        return [Finding(path, line, "local action path must be literal")]
    return []


def _validate_external(
    path: Path,
    line: int,
    reference: str,
    comment: str | None,
) -> list[Finding]:
    findings: list[Finding] = []
    if "${{" in reference or "}}" in reference:
        findings.append(
            Finding(path, line, f"dynamic external action reference is not allowed: {reference}")
        )
        return findings

    if reference.startswith("docker://"):
        if not DOCKER_DIGEST.fullmatch(reference):
            findings.append(
                Finding(
                    path,
                    line,
                    "Docker action must use an immutable sha256 digest",
                )
            )
        elif not comment or not comment.strip():
            findings.append(
                Finding(path, line, "pinned external action requires a readable version comment")
            )
        return findings

    if "@" not in reference:
        return [Finding(path, line, f"external action is missing an @ revision: {reference}")]

    target, revision = reference.rsplit("@", 1)
    components = target.split("/")
    if (
        len(components) < 2
        or not all(components[:2])
        or not OWNER_OR_REPO.fullmatch(components[0])
        or not OWNER_OR_REPO.fullmatch(components[1])
        or any(not OWNER_OR_REPO.fullmatch(part) or part in {".", ".."} for part in components[2:])
    ):
        findings.append(Finding(path, line, f"invalid external action target: {target}"))
    if not FULL_SHA.fullmatch(revision):
        findings.append(
            Finding(
                path,
                line,
                f"external action must use a full 40-character commit SHA, not {revision!r}",
            )
        )
    if not comment or not comment.strip():
        findings.append(
            Finding(path, line, "pinned external action requires a readable version comment")
        )
    return findings


def _inspect(path: Path):
    text, findings = _read_workflow(path)
    if text is None:
        return [], findings
    try:
        references = workflow_action_yaml.references(text)
    except (YAMLError, ValueError, RecursionError) as error:
        return [], [Finding(path, 1, f"cannot inspect workflow YAML: {error}")]
    for reference in references:
        if reference.value.startswith(("./", "$/")):
            findings.extend(_validate_local(path, reference.line, reference.value))
        else:
            findings.extend(
                _validate_external(path, reference.line, reference.value, reference.comment)
            )
    return references, findings


def validate_workflow(path: Path) -> tuple[int, list[Finding]]:
    references, findings = _inspect(path)
    return len(references), findings


def _local_dependency(root: Path, reference: str) -> Path:
    relative = PurePosixPath(reference[2:])
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("local action path must not traverse symlinks")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("local action path escapes the repository")
    if path.is_file() and relative.parts[:2] == (".github", "workflows"):
        return path
    candidates = [path / name for name in ("action.yml", "action.yaml")]
    found = [candidate for candidate in candidates if candidate.exists() or candidate.is_symlink()]
    if len(found) != 1:
        raise ValueError("local action must contain exactly one action.yml or action.yaml")
    return found[0]


def validate_repository(root: Path = ROOT) -> tuple[int, int, list[Finding]]:
    for path in (root / ".github", root / ".github" / "workflows"):
        if path.is_symlink():
            return 0, 0, [Finding(path, 1, "workflow directory must not be a symlink")]
    workflow_paths = _workflow_paths(root)
    reference_count = 0
    findings: list[Finding] = []
    pending, seen = list(workflow_paths), set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        if len(seen) >= MAX_EXECUTABLE_FILES:
            findings.append(Finding(path, 1, "too many executable workflow/action files"))
            break
        seen.add(path)
        references, workflow_findings = _inspect(path)
        reference_count += len(references)
        findings.extend(workflow_findings)
        for reference in references:
            if reference.value.startswith(("./", "$/")) and not _validate_local(path, reference.line, reference.value):
                try:
                    pending.append(_local_dependency(root, reference.value))
                except (OSError, ValueError) as error:
                    findings.append(Finding(path, reference.line, str(error)))
    return len(workflow_paths), reference_count, findings


def main() -> int:
    workflow_count, reference_count, findings = validate_repository()
    if findings:
        for finding in findings:
            print(finding.render(), file=sys.stderr)
        return 1
    print(
        f"validated {reference_count} immutable/local action references "
        f"across {workflow_count} workflows"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
