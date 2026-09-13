"""Conservative SPDX attribution subset, without guessing unknown licenses."""
from __future__ import annotations

import json
from pathlib import Path
import re

from tools.build_snapshot import SnapshotError, digest


LICENSE_IDS = Path(__file__).resolve().parent / "data/cyclonedx-1.6/spdx-license-ids.json"
LICENSE_IDS_DIGEST = "sha256:27f8b5e7c6feae722d7947ac30182dc33ce9235ac7932ccdf5ba86156892c372"


def load_license_ids() -> frozenset[str]:
    with LICENSE_IDS.open("rb") as source:
        data = source.read(16 * 1024 + 1)
    if len(data) > 16 * 1024 or digest(data) != LICENSE_IDS_DIGEST:
        raise SnapshotError("pinned SPDX attribution data changed")
    value = json.loads(data)
    return frozenset(value["licenses"])


def license_expression(value: str | None, licenses: frozenset[str]) -> str | None:
    """Keep only known IDs joined by uppercase AND/OR and balanced parentheses.

    WITH, deprecated IDs, custom references and nonstandard Cargo expressions
    remain unavailable; the original manifest digest still records attribution.
    This subset intentionally accepts less than the Rust SPDX validator.
    """
    if (value is None or not value.isascii() or not 1 <= len(value) <= 1024
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        return None
    tokens = re.findall(r"[A-Za-z0-9.-]+|[()]| +|.", value)
    if len(tokens) > 128:
        return None
    expected_operand = True
    depth = 0
    for token in tokens:
        if token.isspace() and token.strip(" ") == "":
            continue
        if expected_operand:
            if token == "(":
                depth += 1
                if depth > 16:
                    return None
            elif token in licenses:
                expected_operand = False
            else:
                return None
        elif token in ("AND", "OR"):
            expected_operand = True
        elif token == ")" and depth:
            depth -= 1
        else:
            return None
    return value if not expected_operand and depth == 0 else None
