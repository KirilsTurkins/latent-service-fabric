"""Bind every executable external action to a reviewed dependency snapshot."""
from __future__ import annotations

from pathlib import Path
import re
import yaml

from tools import workflow_action_yaml
from tools import security_deploy_pages, security_attest
from tools.security_common import SecurityError, decode_json, digest, read_file, require

RECORD = ".github/security/actions.json"
PREFIX = ".github/security/actions/"


def references(payload: bytes):
    try:
        return workflow_action_yaml.references(payload.decode())
    except (yaml.YAMLError, ValueError, UnicodeError, RecursionError):
        raise SecurityError("invalid-action-graph-yaml") from None


def verify(repo: Path, paths: list[str]) -> list[dict]:
    pending = [path for path in paths if path.startswith(".github/workflows/")
               and path.endswith((".yml", ".yaml"))]
    if not pending:
        return []
    configuration = decode_json(read_file(repo, RECORD))
    require(configuration.get("schema") == 1, "invalid-action-graph-policy")
    actions = configuration.get("actions")
    require(isinstance(actions, dict) and 0 < len(actions) <= 64, "invalid-action-graph-count")
    seen_files, seen_actions, records = set(), set(), []
    while pending:
        path = pending.pop()
        if path in seen_files:
            continue
        seen_files.add(path)
        require(len(seen_files) <= 320, "action-graph-file-limit")
        for reference in references(read_file(repo, path, 128 * 1024)):
            value = reference.value
            if value.startswith(("./", "$/")):
                directory = value[2:]
                if directory.startswith(".github/workflows/") and directory in paths:
                    pending.append(directory)
                    continue
                candidates = [directory + "/" + name for name in ("action.yml", "action.yaml")
                              if directory + "/" + name in paths]
                require(len(candidates) == 1, "unresolved-local-action-graph")
                pending.extend(candidates)
                continue
            # Identify the offending source without echoing an untrusted action
            # value. All policy/refusal checks remain mandatory.
            require(value in actions,
                    f"unreviewed-external-action-graph:{path}:{reference.line}")
            if value in seen_actions:
                continue
            seen_actions.add(value)
            row = actions[value]
            require(isinstance(row, dict) and isinstance(row.get("files"), list)
                    and (1 <= len(row["files"]) <= 6 or len(row["files"]) in {8, 16, 25})
                    and isinstance(row.get("metadata"), dict),
                    "invalid-action-graph-binding")
            source, revision = value.rsplit("@", 1)
            if source == "KirilsTurkins/lsf-bytecodealliance-actions/wasm-tools/setup":
                require(value == ("KirilsTurkins/lsf-bytecodealliance-actions/wasm-tools/setup@"
                                  "1ce6e3461b7d83b4b5a5a6557870b4fdfd4386ce")
                        and len(row["files"]) == 4
                        and {item.get("source") for item in row["files"]} == {
                            "wasm-tools/setup/action.yml", "package.json", "package-lock.json",
                            ".lsf-source/verify-installed-deepmerge.mjs"},
                        "unreviewed-additional-action-source")
            if len(row["files"]) == 5:
                require(source == "KirilsTurkins/lsf-setup-python"
                        and {item.get("source") for item in row["files"]} == {
                            "action.yml", "package.json", "package-lock.json",
                            ".lsf-source/verify-installed-deepmerge.mjs", ".lsf-source/verify-installed-minimatch.mjs"},
                        "unreviewed-additional-action-source")
            if len(row["files"]) == 6 and source == "KirilsTurkins/lsf-upload-artifact":
                require(value == "KirilsTurkins/lsf-upload-artifact@c37718fd4e24a4c372572ce4f21b3969a72ba8dc"
                        and {item.get("source") for item in row["files"]} == {
                            "action.yml", "package.json", "package-lock.json",
                            ".lsf-source/verify-installed-deepmerge.mjs", ".lsf-source/verify-upload-sources.mjs",
                            ".lsf-source/upload-source.test.mjs"}, "unreviewed-additional-action-source")
            elif len(row["files"]) == 6 and source == "KirilsTurkins/lsf-download-artifact":
                require(value == "KirilsTurkins/lsf-download-artifact@fc27fb5305d2042f110912a9d6a2924a98084389"
                        and {item.get("source") for item in row["files"]} == {
                            "action.yml", "package.json", "package-lock.json",
                            ".lsf-source/verify-installed-deepmerge.mjs", ".lsf-source/verify-download-sources.mjs",
                            ".lsf-source/download-source.test.mjs"}, "unreviewed-additional-action-source")
            elif len(row["files"]) == 6:
                require(value in {"KirilsTurkins/lsf-setup-java@8aaa4ea8191b36cb3f394e91d099da0d31dc02c2",
                                  "KirilsTurkins/lsf-setup-dotnet@2382c9e63a3b678b643c7e715d023e7fa42fbbef",
                                  "KirilsTurkins/lsf-setup-node@791d25988f7dc57f537b82342f7af452cd59cd6a",
                                  "KirilsTurkins/lsf-setup-go@92a5903f5ff2b45e67c517d23c18501025a55a12"}
                        and {item.get("source") for item in row["files"]} == {
                            "action.yml", "package.json", "package-lock.json", ".lsf-source/minimatch-bounds.test.mjs",
                            ".lsf-source/verify-installed-deepmerge.mjs", ".lsf-source/verify-installed-minimatch.mjs"},
                        "unreviewed-additional-action-source")
            if len(row["files"]) == 8:
                require(value == "KirilsTurkins/lsf-rust-cache@653972653a76770ab9b45cca67e4db8221bed334"
                        and {item.get("source") for item in row["files"]} == {
                            "action.yml", "package.json", "package-lock.json",
                            ".lsf-source/verify-installed-deepmerge.mjs", ".lsf-source/verify-installed-minimatch.mjs",
                            ".lsf-source/minimatch-bounds.test.mjs", ".lsf-source/verify-rust-cache-lock.mjs",
                            ".lsf-source/rust-cache-lock.test.mjs"}, "unreviewed-additional-action-source")
            if len(row["files"]) == 16:
                require(value == security_deploy_pages.REFERENCE
                        and all(isinstance(item, dict) for item in row["files"])
                        and {item.get("source") for item in row["files"]} == set(security_deploy_pages.ACTION_INPUTS),
                        "unreviewed-additional-action-source")
            if len(row["files"]) == 25:
                require(value == security_attest.REFERENCE
                        and all(isinstance(item, dict) for item in row["files"])
                        and {item.get("source") for item in row["files"]} == set(security_attest.ACTION_INPUTS),
                        "unreviewed-additional-action-source")
            require(re.fullmatch(r"[0-9a-f]{40}", revision) is not None
                    and row["revision"] == revision and row["repository"] == "/".join(source.split("/")[:2]),
                    "action-graph-revision-drift")
            expected_metadata = "/".join(source.split("/")[2:] + ["action.yml"])
            require(row["metadata"]["source"] == expected_metadata, "action-entrypoint-drift")
            for item in row["files"]:
                require(item["snapshot"].startswith(PREFIX)
                        and digest(read_file(repo, item["snapshot"])) == item["sha256"],
                        "action-dependency-snapshot-drift")
            require(row["metadata"] in row["files"], "missing-action-metadata-binding")
            require(row["kind"] in {"npm", "composite"}, "unreviewed-action-implementation")
            if row["kind"] == "npm":
                require({item["source"] for item in row["files"]} >= {"package.json", "package-lock.json"},
                        "incomplete-action-dependency-graph")
            metadata = yaml.load(read_file(repo, row["metadata"]["snapshot"]), Loader=yaml.BaseLoader)
            using = metadata.get("runs", {}).get("using")
            require((row["kind"] == "npm" and using == "node24")
                    or (row["kind"] == "composite" and using == "composite"),
                    "action-runtime-graph-mismatch")
            pending.append(row["metadata"]["snapshot"])
            records.append({"path": row["metadata"]["snapshot"], "reference": value, "coverage": "reviewed-external-action-graph",
                            "upstream": row["upstream_repository"], "packages": 0})
    require(seen_actions == set(actions), "unused-or-stale-action-graph")
    return records
