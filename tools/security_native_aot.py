"""Nonexecuting inventory of the exact reviewed NativeAOT compiler graph.

The standard client NuGet reader intentionally accepts a smaller MSBuild shape.
NativeAOT has an SDK-injected linker dependency and a RID overlay, so it uses an
explicitly reviewed project/configuration/lock identity, never a scanner bypass.
Every resolved package in both framework groups still enters advisory scanning.
"""
from __future__ import annotations

import re
from pathlib import Path

from tools.security_common import decode_json, digest, read_file, require

VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?")


def packages(repo: Path, entry: dict) -> list[tuple[str, str, str]]:
    for path, expected in [(entry["path"], entry["manifest_sha256"]),
                           (entry["lock"], entry["lock_sha256"]),
                           *[(item["path"], item["sha256"]) for item in entry["configuration"]]]:
        require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected),
                "invalid-native-aot-input-digest")
        require(digest(read_file(repo, path, 256 * 1024).replace(b"\r\n", b"\n")) == expected,
                "unreviewed-native-aot-input")
    lock = decode_json(read_file(repo, entry["lock"], 256 * 1024))
    require(isinstance(lock, dict) and set(lock) == {"version", "dependencies"}
            and lock["version"] == 1, "invalid-native-aot-lock")
    groups = lock["dependencies"]
    require(isinstance(groups, dict) and set(groups) == {"net10.0", "net10.0/wasi-wasm"},
            "unreviewed-native-aot-target")
    result = set()
    for group in groups.values():
        require(isinstance(group, dict) and 0 < len(group) <= 128, "native-aot-package-bound")
        names = {name.lower() for name in group}
        require(len(names) == len(group), "duplicate-native-aot-package")
        for name, item in group.items():
            require(re.fullmatch(r"[A-Za-z0-9_.-]+", name) and isinstance(item, dict)
                    and {"type", "resolved", "contentHash"} <= set(item)
                    and set(item) <= {"type", "resolved", "contentHash", "requested", "dependencies"}
                    and item["type"] in {"Direct", "Transitive"}, "invalid-native-aot-package")
            require(isinstance(item["resolved"], str) and VERSION.fullmatch(item["resolved"]),
                    "unresolved-native-aot-version")
            require(isinstance(item["contentHash"], str)
                    and re.fullmatch(r"[A-Za-z0-9+/]{86}==", item["contentHash"]),
                    "invalid-native-aot-package-checksum")
            edges = item.get("dependencies", {})
            require(isinstance(edges, dict) and all(edge.lower() in names for edge in edges),
                    "incomplete-native-aot-graph")
            result.add(("NuGet", name, item["resolved"]))
    return sorted(result)
