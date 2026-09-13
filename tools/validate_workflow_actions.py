#!/usr/bin/env python3
"""Validate immutable GitHub Action identities in executable workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_ROOT = ROOT / ".github" / "workflows"
MAX_WORKFLOW_BYTES = 128 * 1024
FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
OWNER_OR_REPO = re.compile(r"^[A-Za-z0-9_.-]+$")
DOCKER_DIGEST = re.compile(r"^docker://[^\s@]+@sha256:[0-9a-fA-F]{64}$")
USES_LINE = re.compile(
    r"^\s*(?:-\s*)?uses\s*:\s*(?P<value>[^#]+?)(?:\s+#\s*(?P<comment>.+))?\s*$"
)


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
        payload = path.read_bytes()
        return payload.decode("utf-8", errors="strict"), []
    except (OSError, UnicodeDecodeError) as error:
        return None, [Finding(path, 1, f"workflow must be readable UTF-8: {error}")]


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _validate_local(path: Path, line: int, reference: str) -> list[Finding]:
    relative = reference[2:]
    if not relative:
        return [Finding(path, line, "local action reference must name a repository path")]
    parts = PurePosixPath(relative).parts
    if any(part in {"", ".", ".."} for part in parts):
        return [Finding(path, line, f"unsafe local action reference: {reference}")]
    if "@" in reference:
        return [Finding(path, line, "local action references must not append an @ revision")]
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


def validate_workflow(path: Path) -> tuple[int, list[Finding]]:
    text, findings = _read_workflow(path)
    if text is None:
        return 0, findings

    references = 0
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        match = USES_LINE.fullmatch(line)
        if not match:
            if re.match(r"^\s*(?:-\s*)?uses\s*:", line):
                findings.append(Finding(path, line_number, "cannot parse uses: reference safely"))
            continue

        reference = _unquote(match.group("value").strip())
        comment = match.group("comment")
        references += 1
        if reference.startswith("./"):
            findings.extend(_validate_local(path, line_number, reference))
        else:
            findings.extend(
                _validate_external(path, line_number, reference, comment)
            )

    return references, findings


def validate_repository(root: Path = ROOT) -> tuple[int, int, list[Finding]]:
    workflow_paths = _workflow_paths(root)
    reference_count = 0
    findings: list[Finding] = []
    for path in workflow_paths:
        references, workflow_findings = validate_workflow(path)
        reference_count += references
        findings.extend(workflow_findings)
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
