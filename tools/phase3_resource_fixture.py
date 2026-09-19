"""Finite time-window preflight; the real node still verifies every signature."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import time

from tools.ci_rust_artifacts import unique_object
from tools.phase2_operator_process import read_json, require
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_profile import integer


def validity(root, duration, now=None):
    now = int(time.time()) if now is None else integer(now)
    required_until = now + integer(duration) + 10
    policy = read_json(root / "policy.json")
    windows = [{"kind": "policy", "issuedAt": integer(policy["validFrom"]),
                "expiresAt": integer(policy["validUntil"])}]
    for name in ("rust-http", "rust-blob", "rust-callee"):
        directory = root / name / "evidence"
        index = read_json(directory / "index.json")
        for kind in ("signatures", "provenance"):
            entries = index[kind]
            require(0 < len(entries) <= 8, "resource-fixture-evidence-population")
            for entry in entries:
                relative = Path(entry["payload"])
                require(not relative.is_absolute() and ".." not in relative.parts
                        and len(str(relative)) <= 512, "resource-fixture-evidence-path")
                path = directory / relative
                require(path.resolve().is_relative_to(directory.resolve()), "resource-fixture-evidence-path")
                envelope = read_json(path)
                payload = envelope["payload"]
                require(isinstance(payload, str) and len(payload) <= 262144, "resource-fixture-envelope-bound")
                statement = json.loads(base64.b64decode(payload, validate=True), object_pairs_hook=unique_object)
                statement = statement["predicate"] if kind == "provenance" else statement
                windows.append({"kind": kind, "fixture": name, "envelope": file_identity(path),
                                "issuedAt": integer(statement["issuedAt"]),
                                "expiresAt": integer(statement["expiresAt"])})
    return {"checkedUnixSeconds": now, "requiredThroughUnixSeconds": required_until, "windows": windows,
            "sufficient": all(window["issuedAt"] <= now < required_until < window["expiresAt"] for window in windows),
            "trustScope": "untrusted-time-preflight-only-node-still-verifies-signatures"}
