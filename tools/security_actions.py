"""Bind every executable external action to a reviewed dependency snapshot."""
from __future__ import annotations

from pathlib import Path
import re
import yaml

from tools import workflow_action_yaml
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
            require(value in actions, "unreviewed-external-action-graph")
            if value in seen_actions:
                continue
            seen_actions.add(value)
            row = actions[value]
            require(isinstance(row, dict) and isinstance(row.get("files"), list)
                    and 1 <= len(row["files"]) <= 4 and isinstance(row.get("metadata"), dict),
                    "invalid-action-graph-binding")
            source, revision = value.rsplit("@", 1)
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
