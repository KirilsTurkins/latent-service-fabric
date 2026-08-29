#!/usr/bin/env python3
"""Validate, plan, and explicitly publish the managed LSF GitHub Wiki.

The Wiki is intentionally published from a developer-controlled local command,
not from a GitHub Actions workflow.  The default mode validates the checked-in
source only.  ``--plan`` may clone the Wiki and show a staged diff, while only
``--apply`` creates a Wiki commit and pushes it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from collections.abc import Iterable, Sequence
import xml.etree.ElementTree as ElementTree


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "wiki" / "pages"
DEFAULT_LEGACY_MANIFEST = ROOT / "wiki" / "legacy-managed-files.txt"
MANIFEST_NAME = ".latent-service-fabric-wiki.json"
MANAGED_MARKER = "<!-- LSF-WIKI-MANAGED -->"
MANIFEST_SCHEMA = "latent-service-fabric.wiki-manifest.v1"
REQUIRED_PAGES = frozenset({"Home.md", "_Sidebar.md", "_Footer.md", "Phase-0-Status.md"})
ALLOWED_SUFFIXES = frozenset({".md", ".svg", ".png", ".jpg", ".jpeg", ".webp"})
IMAGE_LINK = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
WIKI_LINK = re.compile(r"\[\[([^]|#]+)(?:#[^]|]*)?(?:\|[^]]*)?\]\]")
PHASE0_STATUS_MARKER = re.compile(r"<!-- LSF-PHASE0-GATE: (blocked|authorized) -->")
PHASE0_STATUS_PAGES = ("Home.md", "Phase-0-Status.md", "Roadmap.md")


class WikiError(RuntimeError):
    """Raised when a local Wiki operation would be unsafe or incomplete."""


def _run(arguments: Sequence[str], *, cwd: Path | None = None) -> str:
    try:
        completed = subprocess.run(
            arguments,
            cwd=cwd,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        raise WikiError(f"cannot run {arguments[0]!r}: {error}") from error
    if completed.returncode != 0:
        command = " ".join(arguments[:3])
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise WikiError(f"command failed ({command}): {detail}")
    return completed.stdout


def _safe_relative_path(value: str) -> PurePosixPath:
    if "\\" in value or re.match(r"^[A-Za-z]:", value):
        raise WikiError(f"unsafe managed Wiki path: {value!r}")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise WikiError(f"unsafe managed Wiki path: {value!r}")
    if path.parts[0] == ".git":
        raise WikiError(f"managed Wiki path may not address Git metadata: {value!r}")
    return path


def _relative_files(directory: Path) -> list[PurePosixPath]:
    if not directory.is_dir():
        raise WikiError(f"Wiki source directory does not exist: {directory}")
    files: list[PurePosixPath] = []
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        if path.is_symlink():
            raise WikiError(f"Wiki source must not contain symlinks: {path}")
        relative = PurePosixPath(path.relative_to(directory).as_posix())
        _safe_relative_path(relative.as_posix())
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            raise WikiError(f"unsupported managed Wiki file type: {relative}")
        files.append(relative)
    if not files:
        raise WikiError("Wiki source has no files")
    return sorted(files, key=str)


def _source_path(source: Path, relative: PurePosixPath) -> Path:
    return source.joinpath(*relative.parts)


def _validate_image_links(source: Path, relative: PurePosixPath, document: str) -> None:
    for match in IMAGE_LINK.finditer(document):
        if not match.group(1).strip():
            raise WikiError(f"image link in {relative} must have descriptive alt text")
        target = match.group(2).strip()
        if target.startswith(("https://", "http://", "#")):
            continue
        target = target.split("#", maxsplit=1)[0].split("?", maxsplit=1)[0]
        candidate = PurePosixPath(target)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise WikiError(f"image link in {relative} escapes the managed Wiki: {target!r}")
        resolved = _source_path(source, PurePosixPath(relative.parent, candidate))
        if not resolved.is_file():
            raise WikiError(f"image link in {relative} does not exist in Wiki source: {target!r}")


def _validate_markdown_links(
    source: Path,
    relative: PurePosixPath,
    document: str,
    managed_files: set[str],
) -> None:
    """Check local Wiki links and development-branch repository references."""

    for match in MARKDOWN_LINK.finditer(document):
        target = match.group(1).strip()
        if target.startswith("#"):
            continue
        parsed = urlsplit(target)
        if parsed.scheme in {"http", "https"}:
            parts = parsed.path.split("/")
            if (
                parsed.netloc == "github.com"
                and len(parts) >= 6
                and parts[1:3] == ["KirilsTurkins", "latent-service-fabric"]
                and parts[3] in {"blob", "tree"}
                and parts[4] == "development"
            ):
                repository_path = "/".join(parts[5:])
                _safe_relative_path(repository_path)
                candidate = ROOT.joinpath(*PurePosixPath(repository_path).parts)
                exists = candidate.is_file() if parts[3] == "blob" else candidate.is_dir()
                if not exists:
                    raise WikiError(
                        f"repository link in {relative} does not exist on development: {target!r}"
                    )
            continue
        if parsed.scheme or target.startswith("//"):
            continue
        wiki_target = parsed.path
        if not wiki_target:
            continue
        candidate = PurePosixPath(wiki_target)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise WikiError(f"Wiki link in {relative} escapes the managed source: {target!r}")
        relative_target = PurePosixPath(relative.parent, candidate)
        if not relative_target.suffix:
            relative_target = relative_target.with_suffix(".md")
        if relative_target.as_posix() not in managed_files:
            raise WikiError(f"Wiki link in {relative} does not exist in managed source: {target!r}")
    for match in WIKI_LINK.finditer(document):
        wiki_target = PurePosixPath(match.group(1).strip())
        if wiki_target.is_absolute() or ".." in wiki_target.parts:
            raise WikiError(f"Wiki link in {relative} escapes the managed source: {match.group(0)!r}")
        if not wiki_target.suffix:
            wiki_target = wiki_target.with_suffix(".md")
        if wiki_target.as_posix() not in managed_files:
            raise WikiError(f"Wiki link in {relative} does not exist in managed source: {match.group(0)!r}")


def _validate_sidebar_navigation(source: Path, managed_files: set[str]) -> None:
    sidebar = source / "_Sidebar.md"
    document = sidebar.read_text(encoding="utf-8")
    navigation_targets: set[str] = set()
    for match in WIKI_LINK.finditer(document):
        target = PurePosixPath(match.group(1).strip())
        if not target.suffix:
            target = target.with_suffix(".md")
        navigation_targets.add(target.as_posix())

    navigable_pages = {
        path
        for path in managed_files
        if path.endswith(".md") and PurePosixPath(path).name not in {"_Sidebar.md", "_Footer.md"}
    }
    missing = sorted(navigable_pages - navigation_targets)
    if missing:
        raise WikiError(f"managed Wiki pages are missing from the sidebar: {', '.join(missing)}")


def _svg_element_name(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", maxsplit=1)[-1].lower()


def _validate_svg(relative: PurePosixPath, document: str) -> None:
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError as error:
        raise WikiError(f"SVG is not well-formed XML: {relative}: {error}") from error
    if _svg_element_name(root) != "svg":
        raise WikiError(f"SVG document has no svg root: {relative}")
    if root.get("viewBox") is None or root.get("role") != "img":
        raise WikiError(f"SVG is missing basic accessible structure: {relative}")

    title = next((element for element in root if _svg_element_name(element) == "title"), None)
    description = next((element for element in root if _svg_element_name(element) == "desc"), None)
    labelled_by = set(root.get("aria-labelledby", "").split())
    if (
        title is None
        or description is None
        or not title.get("id")
        or not description.get("id")
        or not {title.get("id"), description.get("id")}.issubset(labelled_by)
    ):
        raise WikiError(f"SVG must expose title and description through aria-labelledby: {relative}")

    for element in root.iter():
        element_name = _svg_element_name(element)
        if element_name in {"script", "foreignobject", "image"}:
            raise WikiError(f"SVG contains active or embedded content: {relative}")
        for attribute, value in element.attrib.items():
            attribute_name = attribute.rsplit("}", maxsplit=1)[-1].lower()
            if attribute_name.startswith("on"):
                raise WikiError(f"SVG contains an event handler: {relative}")
            if attribute_name == "href" and value.strip().lower().startswith("javascript:"):
                raise WikiError(f"SVG contains a JavaScript href: {relative}")


def validate_source(source: Path = DEFAULT_SOURCE) -> list[PurePosixPath]:
    """Validate source pages/assets without cloning or mutating the Wiki."""

    files = _relative_files(source)
    names = {path.as_posix() for path in files}
    missing = sorted(REQUIRED_PAGES - names)
    if missing:
        raise WikiError(f"required managed Wiki pages are missing: {', '.join(missing)}")

    for relative in files:
        path = _source_path(source, relative)
        if relative.suffix.lower() == ".md":
            document = path.read_text(encoding="utf-8")
            if not document.startswith(MANAGED_MARKER):
                raise WikiError(f"managed Markdown page is missing its marker: {relative}")
            if "```mermaid" in document.lower():
                raise WikiError(f"Mermaid is not permitted in managed Wiki pages: {relative}")
            if "/blob/release/" in document or "/tree/release/" in document:
                raise WikiError(f"managed Wiki page links the obsolete release branch: {relative}")
            _validate_image_links(source, relative, document)
            _validate_markdown_links(source, relative, document, names)
        elif relative.suffix.lower() == ".svg":
            document = path.read_text(encoding="utf-8")
            _validate_svg(relative, document)
    _validate_sidebar_navigation(source, names)
    return files


def authoritative_phase0_status() -> str:
    """Read the gate status from the canonical completion document."""

    completion = ROOT / "docs" / "phase-0-completion.md"
    try:
        document = completion.read_text(encoding="utf-8")
    except OSError as error:
        raise WikiError(f"cannot read authoritative Phase 0 completion document: {error}") from error
    match = re.search(r"\*\*Gate status:\s*(BLOCKED|AUTHORIZED)\b", document)
    if match is None:
        raise WikiError("cannot determine Phase 0 gate status from the completion document")
    return match.group(1).lower()


def validate_phase0_status_alignment(source: Path = DEFAULT_SOURCE) -> str:
    """Reject a publish whose prominent Wiki status contradicts the repository."""

    status = authoritative_phase0_status()
    for name in PHASE0_STATUS_PAGES:
        page = source / name
        if not page.is_file():
            raise WikiError(f"Phase 0 status page is missing: {name}")
        matches = PHASE0_STATUS_MARKER.findall(page.read_text(encoding="utf-8"))
        if matches != [status]:
            raise WikiError(
                f"Wiki Phase 0 marker in {name} must be exactly {status!r} to match the completion document"
            )
    return status


def _legacy_paths(path: Path) -> set[PurePosixPath]:
    if not path.is_file():
        raise WikiError(f"legacy managed-file list does not exist: {path}")
    paths: set[PurePosixPath] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        paths.add(_safe_relative_path(value))
    return paths


def _load_previous_manifest(wiki_directory: Path) -> set[PurePosixPath]:
    manifest = _wiki_target(wiki_directory, PurePosixPath(MANIFEST_NAME))
    if not manifest.exists():
        return set()
    if manifest.is_symlink():
        raise WikiError(f"Wiki manifest may not be a symlink: {manifest}")
    try:
        document = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise WikiError(f"cannot parse existing Wiki manifest: {error}") from error
    if document.get("schema_version") != MANIFEST_SCHEMA:
        raise WikiError("existing Wiki manifest has an unsupported schema")
    values = document.get("managed_files")
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise WikiError("existing Wiki manifest has invalid managed_files")
    return {_safe_relative_path(value) for value in values}


def _assert_clean_worktree(directory: Path, label: str) -> None:
    status = _run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=directory)
    if status.strip():
        raise WikiError(f"{label} must be clean before --apply")


def _source_revision(source_repository: Path = ROOT) -> str:
    return _run(["git", "rev-parse", "HEAD"], cwd=source_repository).strip()


def _write_manifest(wiki_directory: Path, managed_files: Iterable[PurePosixPath], source_revision: str) -> None:
    document = {
        "schema_version": MANIFEST_SCHEMA,
        "publisher": "tools/update_wiki.py",
        "source_revision": source_revision,
        "managed_files": [path.as_posix() for path in sorted(managed_files, key=str)],
    }
    _wiki_target(wiki_directory, PurePosixPath(MANIFEST_NAME)).write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _wiki_root(wiki_directory: Path) -> Path:
    try:
        root = wiki_directory.resolve(strict=True)
    except OSError as error:
        raise WikiError(f"cannot resolve Wiki checkout: {error}") from error
    if not root.is_dir():
        raise WikiError(f"Wiki checkout is not a directory: {wiki_directory}")
    return root


def _wiki_target(wiki_directory: Path, relative: PurePosixPath) -> Path:
    """Return a managed checkout path without traversing a parent symlink."""

    relative = _safe_relative_path(relative.as_posix())
    root = _wiki_root(wiki_directory)
    target = root.joinpath(*relative.parts)
    parent = root
    for part in relative.parts[:-1]:
        parent = parent / part
        if parent.is_symlink():
            raise WikiError(f"managed Wiki path traverses a symlink: {relative}")
        if parent.exists() and not parent.is_dir():
            raise WikiError(f"managed Wiki path has a non-directory parent: {relative}")
    try:
        target.parent.resolve(strict=False).relative_to(root)
    except ValueError as error:
        raise WikiError(f"managed Wiki path traverses a symlink outside the checkout: {relative}") from error
    except OSError as error:
        raise WikiError(f"cannot resolve managed Wiki path {relative}: {error}") from error
    return target


def _remove_file(wiki_directory: Path, relative: PurePosixPath) -> bool:
    target = _wiki_target(wiki_directory, relative)
    if not target.exists() and not target.is_symlink():
        return False
    if target.is_symlink() or not target.is_file():
        raise WikiError(f"refusing to remove non-regular managed Wiki path: {relative}")
    target.unlink()
    parent = target.parent
    root = _wiki_root(wiki_directory)
    while parent != root and parent.exists() and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent
    return True


def synchronize(
    source: Path,
    wiki_directory: Path,
    legacy_paths: set[PurePosixPath],
    source_revision: str,
) -> tuple[list[PurePosixPath], list[PurePosixPath]]:
    """Synchronize the managed set and return (written, removed) paths.

    Files outside the old/new managed sets are deliberately preserved.
    """

    files = validate_source(source)
    desired = set(files)
    previous = _load_previous_manifest(wiki_directory)
    to_remove = sorted((legacy_paths | previous) - desired, key=str)
    removed = [relative for relative in to_remove if _remove_file(wiki_directory, relative)]

    written: list[PurePosixPath] = []
    for relative in files:
        source_path = _source_path(source, relative)
        destination = _wiki_target(wiki_directory, relative)
        if destination.is_symlink():
            raise WikiError(f"refusing to overwrite symlink in Wiki checkout: {relative}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists() or destination.read_bytes() != source_path.read_bytes():
            shutil.copyfile(source_path, destination)
            written.append(relative)
    _write_manifest(wiki_directory, files, source_revision)
    return written, removed


def _wiki_remote(repository: str) -> str:
    parts = repository.split("/")
    if len(parts) != 2 or not all(parts):
        raise WikiError("--repository must use owner/repository form")
    return f"https://github.com/{repository}.wiki.git"


def _validated_remote(remote: str) -> str:
    """Allow normal HTTPS or SSH remotes while rejecting URL-embedded secrets."""

    if remote.startswith("https://"):
        parsed = urlsplit(remote)
        if parsed.username is not None or parsed.password is not None:
            raise WikiError("embedded Wiki credentials are not allowed; use a credential helper or SSH remote")
        if parsed.netloc == "github.com" and parsed.hostname == "github.com" and re.fullmatch(
            r"/[^/]+/[^/]+\.wiki\.git", parsed.path
        ):
            return remote
    elif re.fullmatch(r"git@github\.com:[^/]+/[^/]+\.wiki\.git", remote):
        return remote
    elif remote.startswith("ssh://"):
        parsed = urlsplit(remote)
        if (
            parsed.username == "git"
            and parsed.password is None
            and parsed.netloc == "git@github.com"
            and parsed.hostname == "github.com"
            and re.fullmatch(r"/[^/]+/[^/]+\.wiki\.git", parsed.path)
        ):
            return remote
    raise WikiError("Wiki remote must be a credential-free GitHub Wiki HTTPS or SSH remote")


def _assert_wiki_remote(wiki_directory: Path, expected_remote: str) -> None:
    actual_remote = _validated_remote(_run(["git", "remote", "get-url", "origin"], cwd=wiki_directory).strip())
    if actual_remote != expected_remote:
        raise WikiError(
            "--wiki-directory origin does not match the selected Wiki remote; "
            "pass --remote with its exact credential-free origin URL"
        )


def _assert_wiki_branch(wiki_directory: Path, expected_branch: str) -> None:
    current_branch = _run(["git", "branch", "--show-current"], cwd=wiki_directory).strip()
    if current_branch != expected_branch:
        raise WikiError(
            f"--wiki-directory must have {expected_branch!r} checked out, found {current_branch or 'detached HEAD'!r}"
        )


def _checkout_wiki(remote: str, branch: str, destination: Path) -> None:
    _run(["git", "clone", "--quiet", remote, str(destination)])
    _run(["git", "switch", branch], cwd=destination)
    _assert_wiki_branch(destination, branch)
    _assert_clean_worktree(destination, "Wiki checkout")


def _staged_changes(wiki_directory: Path) -> str:
    _run(["git", "add", "--all"], cwd=wiki_directory)
    return _run(["git", "diff", "--cached", "--name-status"], cwd=wiki_directory)


def _publish(arguments: argparse.Namespace) -> int:
    source = arguments.source.resolve()
    files = validate_source(source)
    phase0_status = validate_phase0_status_alignment(source)
    print(f"validated {len(files)} managed Wiki files in {source}")
    print(f"Phase 0 status alignment: {phase0_status}")
    if arguments.wiki_directory is not None and not arguments.apply:
        raise WikiError("--wiki-directory is only supported with --apply; --plan always uses a temporary clone")
    if arguments.apply and source != DEFAULT_SOURCE.resolve():
        raise WikiError("--apply only accepts the checked-in wiki/pages source")
    if not arguments.plan and not arguments.apply:
        print("local check complete; no Wiki checkout, commit, or push was attempted")
        return 0

    if arguments.apply:
        _assert_clean_worktree(ROOT, "source repository")

    legacy_paths = _legacy_paths(arguments.legacy_manifest.resolve())
    source_revision = _source_revision()
    remote = _validated_remote(arguments.remote or _wiki_remote(arguments.repository))

    temporary_directory: tempfile.TemporaryDirectory[str] | None = None
    if arguments.wiki_directory is None:
        temporary_directory = tempfile.TemporaryDirectory(prefix="lsf-wiki-")
        wiki_directory = Path(temporary_directory.name) / "wiki"
        _checkout_wiki(remote, arguments.branch, wiki_directory)
    else:
        wiki_directory = arguments.wiki_directory.resolve()
        if not (wiki_directory / ".git").exists():
            raise WikiError(f"--wiki-directory is not a Git checkout: {wiki_directory}")
        _assert_wiki_remote(wiki_directory, remote)
        _assert_wiki_branch(wiki_directory, arguments.branch)
        _assert_clean_worktree(wiki_directory, "Wiki checkout")

    try:
        written, removed = synchronize(source, wiki_directory, legacy_paths, source_revision)
        changes = _staged_changes(wiki_directory)
        if not changes.strip():
            print("Wiki is already current; no commit or push is needed")
            return 0
        print("managed Wiki changes staged locally:")
        print(changes.rstrip())
        print(f"written: {len(written)}, removed legacy managed files: {len(removed)}")
        if not arguments.apply:
            print("plan complete; no Wiki commit or push was attempted")
            return 0

        _run(["git", "config", "user.name", arguments.author_name], cwd=wiki_directory)
        _run(["git", "config", "user.email", arguments.author_email], cwd=wiki_directory)
        _run(["git", "commit", "-m", arguments.message], cwd=wiki_directory)
        _run(["git", "push", "origin", f"HEAD:{arguments.branch}"], cwd=wiki_directory)
        print(f"published managed Wiki files to {arguments.repository}.wiki.git ({arguments.branch})")
        return 0
    finally:
        if temporary_directory is not None:
            temporary_directory.cleanup()


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="clone and stage a local Wiki diff without pushing")
    mode.add_argument("--apply", action="store_true", help="commit and push the managed Wiki diff")
    parser.add_argument(
        "--repository",
        default="KirilsTurkins/latent-service-fabric",
        help="GitHub owner/repository whose Wiki is managed",
    )
    parser.add_argument("--branch", default="master", help="Wiki branch to update")
    parser.add_argument(
        "--remote",
        help="optional HTTPS or SSH Wiki remote; URL-embedded credentials are rejected",
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="checked-in Wiki source directory")
    parser.add_argument(
        "--legacy-manifest",
        type=Path,
        default=DEFAULT_LEGACY_MANIFEST,
        help="known old managed files that may be removed",
    )
    parser.add_argument(
        "--wiki-directory",
        type=Path,
        help="existing clean local Wiki checkout for --apply; otherwise a temporary clone is used",
    )
    parser.add_argument("--message", default="docs(wiki): refresh Phase 0 documentation")
    parser.add_argument("--author-name", default="LSF Wiki publisher")
    parser.add_argument("--author-email", default="41898282+wiki-publisher@users.noreply.github.com")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return _publish(parse_arguments(argv))
    except WikiError as error:
        print(f"Wiki update refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
