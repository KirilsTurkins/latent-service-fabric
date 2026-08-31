#!/usr/bin/env python3
"""Validate the checked-in Phase 1 Protobuf FileDescriptorSet contract.

The contract is generated from Buf's JSON FileDescriptorSet output with source
locations omitted. Comparing this normalized descriptor rather than parsing
source text protects every descriptor-semantic change in the module: field
types and cardinality, oneof membership, map entries, enum numbering, service
signatures, reservations, and newly added or removed descriptors.
"""

from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "api" / "proto" / "phase1-descriptor-contract.json"


def normalize_value(value: Any) -> Any:
    """Drop location-only data while preserving the descriptor's semantics."""

    if isinstance(value, dict):
        return {
            key: normalize_value(child)
            for key, child in value.items()
            if key != "sourceCodeInfo"
        }
    if isinstance(value, list):
        return [normalize_value(item) for item in value]
    return value


def normalize_descriptor(descriptor: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic, source-location-free FileDescriptorSet."""

    files = descriptor.get("file")
    if not isinstance(files, list):
        raise ValueError("descriptor does not contain a FileDescriptorSet file list")

    normalized_files = [normalize_value(file_descriptor) for file_descriptor in files]
    if any(not isinstance(file_descriptor, dict) for file_descriptor in normalized_files):
        raise ValueError("descriptor contains a malformed file descriptor")

    return {
        "file": sorted(
            normalized_files,
            key=lambda file_descriptor: str(file_descriptor.get("name", "")),
        )
    }


def canonical_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def validate_descriptor(descriptor: dict[str, Any], golden: dict[str, Any]) -> None:
    actual = normalize_descriptor(descriptor)
    expected = normalize_descriptor(golden)
    if actual == expected:
        return

    difference = "".join(
        difflib.unified_diff(
            canonical_json(expected).splitlines(keepends=True),
            canonical_json(actual).splitlines(keepends=True),
            fromfile=str(GOLDEN),
            tofile="current FileDescriptorSet",
        )
    )
    raise ValueError(
        "Phase 1 descriptor contract changed. Update the compatibility record "
        "and golden deliberately if this is intended.\n"
        f"{difference}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "descriptor",
        type=Path,
        help="Buf JSON FileDescriptorSet generated with --as-file-descriptor-set",
    )
    parser.add_argument(
        "--print-normalized",
        action="store_true",
        help="print normalized descriptor JSON for deliberate golden review",
    )
    parser.add_argument(
        "--print-compact",
        action="store_true",
        help="print compact normalized descriptor JSON for golden generation",
    )
    args = parser.parse_args()

    descriptor = json.loads(args.descriptor.read_text(encoding="utf-8"))
    normalized = normalize_descriptor(descriptor)
    if args.print_normalized:
        print(canonical_json(normalized), end="")
        return
    if args.print_compact:
        print(json.dumps(normalized, sort_keys=True, separators=(",", ":")))
        return

    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    validate_descriptor(descriptor, golden)
    print("validated Phase 1 descriptor contract")


if __name__ == "__main__":
    main()
