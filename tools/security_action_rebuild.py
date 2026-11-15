"""Validate exact action rebuild receipts without promoting old qualification."""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
import re

from tools.security_common import decode_json, read_file, require


def _identity(raw: bytes) -> dict:
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "gitBlob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def _valid_identity(value: object) -> bool:
    return (isinstance(value, dict) and set(value) == {"bytes", "sha256", "gitBlob"}
            and type(value["bytes"]) is int and 0 < value["bytes"] <= 16 * 1024 * 1024
            and isinstance(value["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is not None
            and isinstance(value["gitBlob"], str) and re.fullmatch(r"[0-9a-f]{40}", value["gitBlob"]) is not None)


def verify_rebuild(repo: Path, build: dict, reference: str, runtime: dict) -> None:
    """Bind a byte-authenticated v2 receipt to all selected source and runtime bytes."""
    required = {"schema", "repository", "publishedRevision", "publishedTree", "base", "testedCommit",
                "diagnosticHead", "run", "jobConclusion", "toolchain", "artifact", "validationLog",
                "validation", "sourceFiles", "outputs", "installedSourceAssertions", "previousEvidence", "scope"}
    require(isinstance(build, dict) and set(build) == required and build["schema"] == 2,
            "action-rebuild-schema-drift")
    parts = reference.rsplit("@", 1)
    require(len(parts) == 2 and build["repository"] == parts[0]
            and build["publishedRevision"] == parts[1]
            and all(isinstance(build[k], str) and re.fullmatch(r"[0-9a-f]{40}", build[k]) is not None
                    for k in ("publishedRevision", "publishedTree", "base", "testedCommit", "diagnosticHead"))
            and build["publishedRevision"] != build["base"], "action-rebuild-revision-drift")
    prior = build["previousEvidence"]
    require(isinstance(prior, dict) and prior.get("schema") == 1
            and prior.get("repository") == build["repository"]
            and prior.get("publishedRevision") == build["base"], "action-rebuild-history-drift")
    require(type(build["run"]) is int and build["run"] > 0 and build["jobConclusion"] == "success"
            and build["toolchain"] == {"node": "24.19.0"}
            and _valid_identity(build["validationLog"]), "action-rebuild-execution-drift")
    artifact = build["artifact"]
    require(isinstance(artifact, dict) and set(artifact) == {"id", "bytes", "sha256"}
            and type(artifact["id"]) is int and artifact["id"] > 0
            and type(artifact["bytes"]) is int and 0 < artifact["bytes"] <= 16 * 1024 * 1024
            and isinstance(artifact["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]) is not None,
            "action-rebuild-artifact-drift")
    validation = build["validation"]
    require(isinstance(validation, dict) and set(validation) == {
                "sourceControlsPassed", "xmlRegressionPassed", "unitTests", "unitSuites"}
            and validation["sourceControlsPassed"] is True and validation["xmlRegressionPassed"] is True
            and all(value is None or type(value) is int and value > 0
                    for value in (validation["unitTests"], validation["unitSuites"])),
            "action-rebuild-validation-drift")
    expected = {row.get("source", path): {k: row[k] for k in ("bytes", "sha256", "gitBlob")}
                for path, row in runtime.items()}
    outputs = build["outputs"]
    require(isinstance(outputs, dict) and 0 < len(outputs) <= 16 and outputs == expected
            and all(isinstance(path, str) and path.startswith("dist/")
                    and not {"", ".", ".."} & set(PurePosixPath(path).parts)
                    and _valid_identity(row) for path, row in outputs.items()), "action-rebuild-output-drift")
    action = decode_json(read_file(repo, ".github/security/actions.json"))["actions"].get(reference, {})
    require(action.get("repository") == build["repository"] and action.get("revision") == parts[1]
            and isinstance(action.get("files"), list) and 0 < len(action["files"]) <= 25,
            "action-rebuild-action-binding-drift")
    source_files = build["sourceFiles"]
    require(isinstance(source_files, dict) and set(source_files) == {row["source"] for row in action["files"]}
            and all(_valid_identity(row) for row in source_files.values()), "action-rebuild-input-set-drift")
    for row in action["files"]:
        current = _identity(read_file(repo, row["snapshot"]))
        require(source_files[row["source"]] == current
                and row["sha256"] == row["source_sha256"] == current["sha256"], "action-rebuild-input-drift")
    lock_source = next(row for row in action["files"] if row["source"] == "package-lock.json")
    lock = decode_json(read_file(repo, lock_source["snapshot"]))
    xml = [row for path, row in lock["packages"].items()
           if (row.get("name") or path.rsplit("node_modules/", 1)[-1]) == "fast-xml-parser"]
    require(xml and all(row.get("version") == "5.12.0"
                       and row.get("resolved") == "https://registry.npmjs.org/fast-xml-parser/-/fast-xml-parser-5.12.0.tgz"
                       and isinstance(row.get("integrity"), str) and row["integrity"].startswith("sha512-")
                       for row in xml), "action-rebuild-xml-lock-drift")
    assertions = build["installedSourceAssertions"]
    require(isinstance(assertions, list) and 0 < len(assertions) <= 32
            and all(isinstance(row, dict) and row.get("sourceCommit") == build["diagnosticHead"]
                    and row.get("kind") in {"installed-source-assertion", "installed-minimatch-source-assertion",
                                            "installed-source-verification", "rust-cache-lock-source-assertion",
                                            "installed-upload-source-assertion", "installed-download-source-assertion"}
                    for row in assertions), "action-rebuild-installed-source-drift")
    require(build["scope"] == "Exact source/bundle rebuild and finite controls; no signed SDK or release qualification.",
            "action-rebuild-scope-drift")
