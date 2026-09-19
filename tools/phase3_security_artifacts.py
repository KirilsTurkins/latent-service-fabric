"""Exact Cargo/libtest selection for the Phase 3 runtime security matrix."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import time

from tools.ci_rust_artifacts import ArtifactError, unique_object

MAX_INVENTORY_BYTES = 32 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024
MAX_RECORDS = 100_000
MAX_LIST_BYTES = 1024 * 1024
MAX_LINK_PATHS = 256
MAX_FILE_BYTES = 1024 * 1024 * 1024
NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*(?:::[A-Za-z_][A-Za-z_0-9]*)*\Z")


class SecurityError(ArtifactError):
    """Static classification; never include provider output or private paths."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise SecurityError(reason)


@dataclass(frozen=True)
class Artifact:
    executable: Path
    package: Path
    link_paths: tuple[Path, ...]


def file_identity(path: Path, deadline: float, maximum: int = MAX_FILE_BYTES) -> dict:
    require(not path.is_symlink() and path.is_file(), "identity-not-regular-file")
    before = path.stat()
    require(before.st_size <= maximum, "identity-file-limit")
    digest = hashlib.sha256()
    consumed = 0
    with path.open("rb") as source:
        while block := source.read(65536):
            require(time.monotonic() < deadline, "identity-deadline")
            consumed += len(block)
            require(consumed <= maximum, "identity-file-limit")
            digest.update(block)
    after = path.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            and consumed == before.st_size, "identity-file-changed")
    return {"sha256": digest.hexdigest(), "bytes": consumed}


def tree_identity(root: Path, deadline: float) -> dict:
    require(root.is_dir() and not root.is_symlink(), "fixture-not-directory")
    pending = [root]
    entries = []
    total = 0
    visited = 0
    while pending:
        directory = pending.pop()
        require(time.monotonic() < deadline, "identity-deadline")
        for child in directory.iterdir():
            visited += 1
            require(not child.is_symlink(), "fixture-link")
            require(visited <= 4096, "fixture-entry-limit")
            if child.is_dir():
                pending.append(child)
            else:
                identity = file_identity(child, deadline, 32 * 1024 * 1024)
                total += identity["bytes"]
                require(total <= 128 * 1024 * 1024, "fixture-byte-limit")
                entries.append([child.relative_to(root).as_posix(), identity])
    require(entries, "fixture-empty")
    encoded = json.dumps(sorted(entries), separators=(",", ":")).encode()
    return {"sha256": hashlib.sha256(encoded).hexdigest(), "files": len(entries), "bytes": total}


def checked_path(value: object) -> Path:
    require(isinstance(value, str) and 0 < len(value) <= 4096 and "\0" not in value,
            "invalid-artifact-path")
    path = Path(value)
    require(path.is_absolute() and not path.is_symlink(), "invalid-artifact-path")
    return path.resolve(strict=True)


def read_inventory(path: Path, repo: Path, groups: tuple) -> dict[str, Artifact]:
    repo = repo.resolve(strict=True)
    target_root = (repo / "target").resolve(strict=True)
    executable_root = (target_root / "debug/deps").resolve(strict=True)
    expected = {}
    for group in groups:
        manifest = (repo / group.manifest).resolve(strict=True)
        key = (manifest, group.target, group.kind)
        expected.setdefault(key, []).append(group)
    found = {}
    links = set()
    finished = False
    consumed = 0
    records = 0
    with path.open("rb") as source:
        while raw := source.readline(MAX_LINE_BYTES + 1):
            records += 1
            consumed += len(raw)
            require(len(raw) <= MAX_LINE_BYTES and consumed <= MAX_INVENTORY_BYTES
                    and records <= MAX_RECORDS, "inventory-limit")
            if not raw.strip():
                continue
            require(not finished, "inventory-after-build-finished")
            entry = json.loads(raw, object_pairs_hook=unique_object)
            require(isinstance(entry, dict), "inventory-record")
            reason = entry.get("reason")
            if reason == "build-finished":
                require(entry.get("success") is True, "cargo-build-failed")
                finished = True
            elif reason == "build-script-executed":
                values = entry.get("linked_paths", [])
                require(isinstance(values, list) and len(values) <= MAX_LINK_PATHS,
                        "inventory-link-limit")
                for value in values:
                    require(isinstance(value, str) and len(value) <= 4096, "inventory-link-path")
                    candidate = Path(value.split("=", 1)[-1])
                    if candidate.is_absolute():
                        candidate = candidate.resolve()
                        if candidate.is_relative_to(target_root):
                            links.add(candidate)
                    require(len(links) <= MAX_LINK_PATHS, "inventory-link-limit")
            elif reason == "compiler-artifact":
                manifest_value = entry.get("manifest_path")
                require(isinstance(manifest_value, str) and len(manifest_value) <= 4096,
                        "inventory-manifest")
                manifest = Path(manifest_value).resolve()
                target = entry.get("target")
                profile = entry.get("profile")
                require(isinstance(target, dict) and isinstance(profile, dict), "inventory-target")
                if profile.get("test") is not True:
                    continue
                kinds = target.get("kind")
                if kinds not in (["lib"], ["test"]):
                    continue
                key = (manifest, target.get("name"), kinds[0])
                if key not in expected:
                    continue
                executable = checked_path(entry.get("executable"))
                require(executable.is_file() and executable.is_relative_to(executable_root),
                        "executable-outside-deps")
                actual_source = checked_path(target.get("src_path"))
                for group in expected[key]:
                    require(actual_source == (manifest.parent / group.source).resolve(strict=True),
                            "wrong-harness-source")
                    require(group.key not in found, "ambiguous-test-artifact")
                    found[group.key] = (executable, manifest.parent)
    require(finished and len(found) == len(groups), "missing-successful-test-artifact")
    return {key: Artifact(executable, package, tuple(sorted(links)))
            for key, (executable, package) in found.items()}


def listing(raw: bytes) -> frozenset[str]:
    require(len(raw) <= MAX_LIST_BYTES, "test-list-limit")
    names = set()
    summary = None
    for line in raw.decode("utf-8", errors="strict").splitlines():
        if not line:
            continue
        require(summary is None, "test-list-after-summary")
        if line.endswith(": test"):
            name = line[:-6]
            require(NAME.fullmatch(name) is not None and name not in names, "test-list-name")
            names.add(name)
        else:
            match = re.fullmatch(r"(\d+) tests?, 0 benchmarks?", line)
            require(match is not None, "test-list-record")
            summary = int(match[1])
    require(summary == len(names), "test-list-count")
    return frozenset(names)


def validate_selection(group, available: frozenset[str], ignored: frozenset[str]) -> None:
    expected = frozenset(case.name for case in group.cases)
    require(expected and expected.issubset(available), "missing-selected-test")
    require(ignored.issubset(available), "ignored-test-not-listed")
    require(expected & ignored == frozenset(case.name for case in group.cases if case.ignored),
            "unexpected-test-ignore-state")


def validate_result(raw: bytes, name: str, *, emitted_record: bytes | None = None) -> None:
    if emitted_record is not None:
        require(0 < len(emitted_record) <= 4096 and b"\n" not in emitted_record
                and b"\r" not in emitted_record, "child-receipt-output")
        prefix = f"test {name} ... ".encode()
        interleaved = prefix + emitted_record + b"\nok\n"
        require(raw.count(interleaved) == 1 and raw.count(emitted_record) == 1, "child-receipt-output")
        raw = raw.replace(interleaved, prefix + b"ok\n", 1)
    lines = raw.decode("utf-8", errors="strict").splitlines()
    outcomes = [line for line in lines if line.startswith("test ") and not line.startswith("test result:")]
    require(outcomes == [f"test {name} ... ok"], "missing-exact-test-result")
    results = [line for line in lines if line.startswith("test result:")]
    require(len(results) == 1 and re.fullmatch(
        r"test result: ok\. 1 passed; 0 failed; 0 ignored; 0 measured; \d+ filtered out; finished in [0-9.]+s",
        results[0]) is not None, "test-result-count")


def validate_custom(raw: bytes, marker: str) -> None:
    lines = raw.decode("utf-8", errors="strict").splitlines()
    require(lines == [marker], "custom-harness-result")
