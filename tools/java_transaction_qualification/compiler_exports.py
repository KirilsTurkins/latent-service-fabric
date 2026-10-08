"""Verify retained compiler bytes and a separate, explicitly pinned export seal.

The original process receipt remains immutable, including its pre-export False
flag. The export seal proves availability of bytes; neither record grants native
authority or proves signed guest execution.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat

from tools.rust_capsule_project import read_file

from .inputs import TOOL_PRODUCER_SOURCE, decode, digest, require

PATHS = {"put-once-values": "capture/put-once-values",
         "forbidden-child": "capture/forbidden-child",
         "put-once-diagnostics": "diagnostic-capture/put-once-diagnostics"}
MAX_FILES = 8192
MAX_EXPORT_BYTES = 256 * 1024 * 1024
MAX_FILE_BYTES = 32 * 1024 * 1024
CENSUS_FIELDS = {"sourceCommit", "attempt", "sourceVolumeReadOnly", "files", "bytes",
                 "compilerOnly", "signedExecutionQualified"}
IDENTITY_FIELDS = {"path", "componentDigest", "componentBytes", "companionDigest", "requirementsDigest",
                   "compilerInputsDigest", "sourceDigest", "sourceArchiveDigest", "recipeDigest", "actualImports"}


def regular(path: Path, directory=False):
    info = path.lstat()
    require(not path.is_symlink() and not getattr(info, "st_file_attributes", 0) & 1024
            and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
                 and info.st_nlink == 1), "original-export-regular-single-link-input")
    return info


def pinned(path: Path, expected: str, maximum: int):
    require(isinstance(path, Path) and path.is_absolute()
            and isinstance(expected, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", expected),
            "explicit-compiler-export-path-and-digest")
    regular(path)
    raw = read_file(path, maximum)
    require(digest(raw) == expected, "original-compiler-export-digest")
    return raw


@dataclass(frozen=True)
class ExportedCapture:
    files: dict
    identity: dict
    process: bytes
    seal: bytes
    census: bytes

    def observation(self):
        return {"originalProcessReceiptDigest": digest(self.process),
                "verifiedExportReceiptDigest": digest(self.seal), "exportCensusDigest": digest(self.census),
                "originalProcessExportAvailable": False, "verifiedExportAvailable": True,
                "signedNodeExecutionQualified": False}


def load(root: Path, process_path: Path, process_digest: str, seal_path: Path, seal_digest: str,
         census_path: Path, census_digest: str, source: str, variant: str):
    require(variant in PATHS and isinstance(root, Path) and root.is_absolute()
            and isinstance(source, str) and re.fullmatch(r"[0-9a-f]{40}", source),
            "explicit-original-compiler-export-selection")
    regular(root, directory=True)
    process_raw = pinned(process_path, process_digest, 262144)
    seal_raw = pinned(seal_path, seal_digest, 262144)
    census_raw = pinned(census_path, census_digest, 4 * 1024 * 1024)
    process, seal, census = decode(process_raw), decode(seal_raw), decode(census_raw, 4 * 1024 * 1024)
    require(process.get("schemaVersion") == "latent.java.transaction-value-compiler-process.v1"
            and process.get("sourceCommit") == seal.get("sourceCommit") == census.get("sourceCommit") == source
            and process.get("originalToolProducer") == seal.get("originalToolProducer") == TOOL_PRODUCER_SOURCE
            and process.get("compilerOnly") is True and process.get("compiled") is True
            and process.get("componentExportAvailable") is False
            and process.get("signedNodeExecutionQualified") is False
            and process.get("admissionRejectionQualified") is False
            and process.get("priorResultsReused") is False and process.get("publicToolsReadOnly") is True
            and process.get("originalPerVariantCompilerDeadlineSeconds") == 900
            and process.get("originalPerCommandOutputBytes") == 4194304,
            "original-pre-export-compiler-receipt-required")
    require(seal.get("compilerProcessReceiptDigest") == process_digest.removeprefix("sha256:")
            and seal.get("exportCensusDigest") == census_digest.removeprefix("sha256:")
            and seal.get("compilerOnly") is True and seal.get("componentExportAvailable") is True
            and seal.get("signedNodeExecutionQualified") is False
            and seal.get("admissionRejectionQualified") is False,
            "separately-sealed-export-is-not-runtime-proof")
    owner = seal.get("compilerOwnerState")
    require(isinstance(owner, dict) and owner.get("Status") == "exited" and owner.get("Running") is False
            and type(owner.get("Pid")) is int and owner["Pid"] == 0
            and type(owner.get("ExitCode")) is int and owner["ExitCode"] == 0
            and owner.get("OOMKilled") is False, "original-compiler-physical-retirement")
    identities = process.get("captures")
    require(isinstance(identities, dict) and set(identities) == set(PATHS)
            and identities == seal.get("captures"), "original-three-capture-export-association")
    for name, identity in identities.items():
        require(isinstance(identity, dict) and set(identity) == IDENTITY_FIELDS
                and identity["path"] == PATHS[name] and type(identity["componentBytes"]) is int
                and 0 < identity["componentBytes"] <= MAX_FILE_BYTES,
                "closed-original-compiler-capture-identity")
    require(set(census) == CENSUS_FIELDS and census["sourceVolumeReadOnly"] is True
            and census["compilerOnly"] is True and census["signedExecutionQualified"] is False
            and isinstance(census["files"], list) and 0 < len(census["files"]) <= MAX_FILES
            and type(census["bytes"]) is int and 0 < census["bytes"] <= MAX_EXPORT_BYTES,
            "bounded-original-export-census")
    seen, selected, total = set(), {}, 0
    prefix = PATHS[variant] + "/"
    for row in census["files"]:
        require(isinstance(row, dict) and set(row) == {"path", "bytes", "digest"},
                "closed-original-export-census-row")
        name = row["path"]
        require(isinstance(name, str) and len(name.encode()) <= 1024 and "\\" not in name and ":" not in name
                and 0 < len(name.split("/")) <= 32 and all(p not in {"", ".", ".."} for p in name.split("/"))
                and not any(ord(c) < 32 or ord(c) == 127 for c in name)
                and any(name.startswith(path + "/") for path in PATHS.values())
                and name.casefold() not in seen and type(row["bytes"]) is int
                and 0 <= row["bytes"] <= MAX_FILE_BYTES
                and isinstance(row["digest"], str) and re.fullmatch(r"[0-9a-f]{64}", row["digest"]),
                "original-export-name-size-and-digest-bound")
        seen.add(name.casefold())
        path = root
        parts = name.split("/")
        for part in parts[:-1]:
            path /= part
            regular(path, directory=True)
        path /= parts[-1]
        require(regular(path).st_size == row["bytes"], "original-export-file-size")
        raw = read_file(path, MAX_FILE_BYTES)
        require(digest(raw) == "sha256:" + row["digest"], "original-export-file-content")
        total += len(raw)
        require(total <= MAX_EXPORT_BYTES, "original-export-total-byte-bound")
        if name.startswith(prefix):
            selected[name[len(prefix):]] = raw
    require(total == census["bytes"], "original-export-exact-census-total")
    observed, directory_count = set(), 0
    for directory, directories, names in os.walk(root, followlinks=False):
        parent = Path(directory)
        regular(parent, directory=True)
        relative = parent.relative_to(root)
        directory_count += 1
        require(directory_count <= MAX_FILES * 32 and len(relative.parts) <= 32
                and len(relative.as_posix().encode()) <= 1024,
                "original-export-directory-count-and-depth-bound")
        for name in directories:
            regular(parent / name, directory=True)
        for name in names:
            path = parent / name
            regular(path)
            relative = path.relative_to(root).as_posix().casefold()
            require(relative in seen and relative not in observed and len(observed) < MAX_FILES,
                    "unlisted-or-duplicate-original-export-file")
            observed.add(relative)
    require(observed == seen, "complete-original-export-census")
    require(selected and "report.json" in selected and "compiled/component.wasm" in selected,
            "original-selected-compiler-materials")
    identity = identities[variant]
    require(len(selected["compiled/component.wasm"]) == identity["componentBytes"],
            "original-export-component-byte-identity")
    for field, path in (("componentDigest", "compiled/component.wasm"), ("companionDigest", "project/transaction-binding.json"),
                        ("compilerInputsDigest", "compiler-inputs.json"), ("sourceDigest", "source-inputs.json"),
                        ("sourceArchiveDigest", "source.tar.gz"), ("recipeDigest", "recipe-inputs.json")):
        require(path in selected and digest(selected[path]) == identity[field],
                "original-export-material-identity")
    if identity["requirementsDigest"] is not None:
        require(digest(selected["project/deferred-http-requirements.json"]) == identity["requirementsDigest"],
                "original-export-requirements-identity")
    return ExportedCapture(selected, identity, process_raw, seal_raw, census_raw)
