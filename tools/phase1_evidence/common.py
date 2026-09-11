"""Strict JSON, identities, and retained artifact boundaries."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any

PREFIX = "latent.phase1.measurement-"
KINDS = ("scale", "soak", "benchmark")
REPETITIONS = {"scale": 1, "soak": 3, "benchmark": 7}
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_RAW_BYTES = 128 * 1024 * 1024
MAX_ROW_BYTES = 256 * 1024
MAX_ROWS = 1_000_000
MAX_ARTIFACTS = 2048
SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
GIT_HASH = re.compile(r"[0-9a-f]{40}\Z")
DECIMAL = re.compile(r"(?:0|[1-9][0-9]{0,19})\Z")


class EvidenceError(ValueError):
    """Fixed diagnostics omit supplied paths, payloads and credentials."""


ValidationError = EvidenceError


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise EvidenceError(reason)


def fields(value: Any, required: str, optional: str = "") -> dict[str, Any]:
    require(isinstance(value, dict), "invalid-object")
    required_keys, optional_keys = set(required.split()), set(optional.split())
    require(required_keys <= value.keys() <= required_keys | optional_keys, "invalid-fields")
    return value


def uint(value: Any) -> int:
    require(isinstance(value, str) and DECIMAL.fullmatch(value) is not None, "invalid-u64")
    result = int(value)
    require(result <= 2**64 - 1, "invalid-u64")
    return result


def integer(value: Any, minimum: int = 0, maximum: int = 2**32 - 1) -> int:
    require(type(value) is int and minimum <= value <= maximum, "invalid-integer")
    return value


def text(value: Any, maximum: int = 4096, *, empty: bool = False) -> str:
    require(isinstance(value, str), "invalid-string")
    require((empty or bool(value)) and len(value.encode("utf-8")) <= maximum, "invalid-string")
    require("\x00" not in value, "invalid-string")
    return value


def digest(value: Any) -> str:
    require(isinstance(value, str) and SHA256.fullmatch(value) is not None, "invalid-digest")
    return value


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "duplicate-json-key")
        result[key] = value
    return result


def bounded_tree(value: Any, *, depth: int = 0, count: list[int] | None = None) -> None:
    if count is None:
        count = [0]
    count[0] += 1
    require(depth <= 48 and count[0] <= 200_000, "json-structure-limit")
    if isinstance(value, dict):
        require(len(value) <= 4096, "json-object-limit")
        for key, child in value.items():
            text(key, 4096)
            bounded_tree(child, depth=depth + 1, count=count)
    elif isinstance(value, list):
        require(len(value) <= 100_000, "json-array-limit")
        for child in value:
            bounded_tree(child, depth=depth + 1, count=count)
    elif isinstance(value, str):
        text(value, 64 * 1024, empty=True)
    elif isinstance(value, float):
        require(math.isfinite(value), "invalid-json-number")
    else:
        require(value is None or isinstance(value, (bool, int)), "invalid-json-value")


def decode(data: bytes, maximum: int = MAX_DOCUMENT_BYTES) -> Any:
    require(len(data) <= maximum, "json-byte-limit")
    try:
        value = json.loads(data, object_pairs_hook=unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(EvidenceError("invalid-json-number")))
        bounded_tree(value)
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError, OverflowError) as error:
        raise EvidenceError("invalid-json") from error


def read_json(path: Path, maximum: int = MAX_DOCUMENT_BYTES) -> Any:
    try:
        require(stat.S_ISREG(path.stat().st_mode), "not-regular-file")
        with path.open("rb") as source:
            require(stat.S_ISREG(os.fstat(source.fileno()).st_mode), "not-regular-file")
            data = source.read(maximum + 1)
    except OSError as error:
        raise EvidenceError("unreadable-evidence") from error
    return decode(data, maximum)


def artifact_path(root: Path, reference: Any) -> Path:
    fields(reference, "path sha256 bytes")
    digest(reference["sha256"])
    uint(reference["bytes"])
    name = text(reference["path"], 1024)
    parts = PurePosixPath(name)
    require(not parts.is_absolute() and name == parts.as_posix() and "\\" not in name
            and all(part not in (".", "..") and ":" not in part for part in parts.parts), "invalid-artifact-path")
    try:
        path = root.resolve()
        for part in parts.parts:
            path = path / part
            require(not path.is_symlink(), "symlink-artifact")
        require(stat.S_ISREG(path.stat().st_mode), "not-regular-artifact")
    except OSError as error:
        raise EvidenceError("missing-artifact") from error
    return path


def hash_file(path: Path, maximum: int = MAX_RAW_BYTES) -> tuple[str, int]:
    value = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as source:
            before = os.fstat(source.fileno())
            require(stat.S_ISREG(before.st_mode) and before.st_size <= maximum, "artifact-byte-limit")
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                require(size <= maximum, "artifact-byte-limit")
                value.update(chunk)
            after = os.fstat(source.fileno())
            require((before.st_ino, before.st_size, before.st_mtime_ns) ==
                    (after.st_ino, after.st_size, after.st_mtime_ns) and size == before.st_size,
                    "artifact-changed-during-read")
    except OSError as error:
        raise EvidenceError("unreadable-artifact") from error
    return "sha256:" + value.hexdigest(), size


def verify_artifact(root: Path, reference: Any, maximum: int = MAX_RAW_BYTES) -> Path:
    path = artifact_path(root, reference)
    found_digest, found_size = hash_file(path, maximum)
    require(found_digest == reference["sha256"] and found_size == uint(reference["bytes"]), "artifact-identity-mismatch")
    return path


def reference(path: Path, root: Path, maximum: int = MAX_RAW_BYTES) -> dict[str, str]:
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise EvidenceError("artifact-outside-evidence-root") from error
    found_digest, found_size = hash_file(path, maximum)
    return {"path": relative, "sha256": found_digest, "bytes": str(found_size)}


def validate_identity(value: Any) -> None:
    fields(value, "schema source build environment binary fixtures")
    require(value["schema"] == PREFIX + "identity.v1", "invalid-identity-schema")
    source = fields(value["source"], "commit tree dirty cargo_lock_sha256")
    require(all(isinstance(source[key], str) and GIT_HASH.fullmatch(source[key]) for key in ("commit", "tree")), "invalid-source-identity")
    require(type(source["dirty"]) is bool, "invalid-source-dirty")
    digest(source["cargo_lock_sha256"])
    build = fields(value["build"], "profile rustc cargo wasmtime target overrides")
    require(build["profile"] in ("release", "debug"), "invalid-build-profile")
    for key in ("rustc", "cargo", "wasmtime", "target"):
        text(build[key])
    require(isinstance(build["overrides"], dict) and len(build["overrides"]) <= 64, "invalid-build-overrides")
    bounded_tree(build["overrides"])
    environment = fields(value["environment"], "os arch kernel cpu_model logical_cpus memory_total_bytes virtualization allocator cpu_policy load_before")
    for key in ("os", "arch", "kernel", "cpu_model"):
        text(environment[key])
    require(0 < uint(environment["logical_cpus"]) <= 65536 and uint(environment["memory_total_bytes"]) > 0, "invalid-host-capacity")
    require(environment["os"].lower() == "linux", "unsupported-measurement-os")
    for key in ("virtualization", "allocator", "cpu_policy"):
        require(isinstance(environment[key], dict), "invalid-host-observation")
        bounded_tree(environment[key])
    load = environment["load_before"]
    require(isinstance(load, list) and len(load) == 3 and all(type(item) in (int, float)
            and math.isfinite(item) and item >= 0 for item in load), "invalid-load-observation")
    binary = fields(value["binary"], "sha256 bytes")
    digest(binary["sha256"])
    require(0 < uint(binary["bytes"]) <= 1024**3, "invalid-binary-size")
    require(isinstance(value["fixtures"], list) and len(value["fixtures"]) == 3, "invalid-fixtures")
    names = set()
    for item in value["fixtures"]:
        fields(item, "name sha256 bytes")
        name = text(item["name"], 128)
        require(name not in names, "duplicate-fixture")
        names.add(name)
        digest(item["sha256"])
        require(0 < uint(item["bytes"]) <= 16 * 1024 * 1024, "invalid-fixture-size")
    require(names == {"echo", "generic", "capabilities"}, "invalid-fixture-names")


def validate_plan(value: Any) -> None:
    fields(value, "schema profile kind repetition scale_counts route_samples warmup_invocations measured_invocations batch_size concurrency benchmark_samples maximum_run_seconds maximum_output_bytes")
    require(value["schema"] == PREFIX + "plan.v1" and value["profile"] in ("smoke", "full")
            and value["kind"] in KINDS, "invalid-plan")
    integer(value["repetition"], 1, 32)
    require(isinstance(value["scale_counts"], list), "invalid-scale-counts")
    expected = [2, 4] if value["profile"] == "smoke" else [100, 1000, 10000, 100000]
    require(value["scale_counts"] == expected and all(type(x) is int for x in value["scale_counts"]), "invalid-scale-counts")
    minima = ({"route_samples": 16, "warmup_invocations": 4, "measured_invocations": 20,
               "batch_size": 20, "concurrency": 2, "benchmark_samples": 4}
              if value["profile"] == "smoke" else
              {"route_samples": 10000, "warmup_invocations": 1000, "measured_invocations": 100000,
               "batch_size": 1000, "concurrency": 2, "benchmark_samples": 400})
    for key, expected_value in minima.items():
        require(type(value[key]) is int and value[key] == expected_value, "invalid-profile-work")
    require(uint(value["maximum_run_seconds"]) == (90 if value["profile"] == "smoke" else 21600), "invalid-run-watchdog")
    maximum = 8 * 1024 * 1024 if value["profile"] == "smoke" else MAX_RAW_BYTES
    require(uint(value["maximum_output_bytes"]) == maximum, "invalid-output-limit")


def write_json(path: Path, value: Any) -> None:
    data = canonical(value) + b"\n"
    require(len(data) <= MAX_DOCUMENT_BYTES, "output-byte-limit")
    try:
        with path.open("xb") as output:
            output.write(data)
    except OSError as error:
        raise EvidenceError("cannot-create-evidence-output") from error
