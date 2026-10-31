"""Append ordinary test cases without replacing shared suite execution contracts."""
from __future__ import annotations

import json
from pathlib import Path
import re

SCHEMA = "latent.ci.suite-case-fragment.v1"


def extend_suites(suites: list[dict], catalogue: Path) -> None:
    """Load bounded, owner-local additions from `<catalogue-stem>.cases.d`.

    Additions cannot change recipes, limits, ignore state or existing names.
    Discovery still compares the complete effective inventory with actual Cargo
    test listings. Conflicting or stale additions fail instead of deduplicating.
    """
    from tools.ci_suite_inventory import MAX_BYTES, MAX_FRAGMENTS, require, unique_object

    directory = catalogue.with_suffix(".cases.d")
    require(not directory.is_symlink(), "linked-suite-case-fragments")
    if not directory.exists():
        return
    require(directory.is_dir(), "suite-case-fragment-directory")
    paths = []
    for child in directory.iterdir():
        require(len(paths) < MAX_FRAGMENTS, "suite-case-fragment-count")
        require(not child.is_symlink() and child.is_file()
                and re.fullmatch(r"[a-z0-9][a-z0-9_.-]*\.json", child.name),
                "suite-case-fragment-file")
        paths.append(child)
    owners = {row["id"]: row for row in suites}
    require(len(owners) == len(suites), "duplicate-suite-id")
    consumed = 0
    for path in sorted(paths):
        with path.open("rb") as source:
            raw = source.read(MAX_BYTES - consumed + 1)
        consumed += len(raw)
        require(consumed <= MAX_BYTES, "suite-case-fragment-byte-limit")
        fragment = json.loads(raw, object_pairs_hook=unique_object)
        require(isinstance(fragment, dict)
                and set(fragment) == {"schemaVersion", "suiteId", "expectedCases"}
                and fragment["schemaVersion"] == SCHEMA, "suite-case-fragment-contract")
        key, cases = fragment["suiteId"], fragment["expectedCases"]
        require(isinstance(key, str) and key in owners, "suite-case-fragment-owner")
        suite = owners[key]
        require(suite.get("mode") == "libtest", "suite-case-fragment-libtest")
        require(isinstance(cases, list) and cases and all(isinstance(name, str)
                and 0 < len(name.encode("utf-8")) <= 4096
                and not any(ord(char) < 32 for char in name) for name in cases),
                "suite-case-fragment-cases")
        require(len(cases) == len(set(cases)), "duplicate-suite-case-addition")
        existing = suite.get("expectedCases")
        require(isinstance(existing, list)
                and type(suite.get("minimumCases")) is int
                and 0 < suite["minimumCases"] == len(existing), "case-count-contract")
        require(isinstance(suite.get("expectedIgnored"), list)
                and set(suite["expectedIgnored"]) <= set(existing), "ignored-case-contract")
        require(not set(cases).intersection(existing), "duplicate-suite-case-addition")
        suite["expectedCases"] = [*existing, *cases]
        suite["minimumCases"] += len(cases)
