#!/usr/bin/env python3
"""Require six actual SDK receipts from identical node, CLI and guest inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.phase2_operator_process import WorkflowError, read_json, require
from tools.sdk_provider_scenario import ASSERTIONS, LANGUAGES, validate_result


def verify(directory: Path) -> dict:
    shared = None
    languages = {}
    for language in sorted(LANGUAGES):
        path = directory / f"{language}.json"
        require(not path.is_symlink() and path.is_file() and 0 < path.stat().st_size <= 128 * 1024,
                "sdk-matrix-receipt-missing-or-unbounded")
        receipt = read_json(path)
        require(receipt["schemaVersion"] == "latent.sdk.provider.workflow.evidence.v1"
                and receipt["language"] == language
                and receipt["scope"] == "separate-node-authenticated-provider-guests",
                "sdk-matrix-receipt-profile")
        participant = validate_result(receipt["participant"], language)
        identities = receipt["identities"]
        require({"node", "cli", "fixture", "participant0"} <= set(identities)
                and all(isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value)
                        for value in identities.values()), "sdk-matrix-executable-identities")
        current = {name: identities[name] for name in ("node", "cli", "fixture")}
        if shared is None:
            shared = current
        require(current == shared, "sdk-matrix-mixed-node-or-guest-inputs")
        upstream = receipt["upstream"]
        require(set(upstream) == {"requests", "authorized", "unexpected", "holds", "closedHolds"}
                and all(type(value) is int and 0 <= value <= 32 for value in upstream.values())
                and upstream["requests"] == upstream["authorized"] >= 5
                and upstream["unexpected"] == 0 and upstream["holds"] == upstream["closedHolds"] == 4,
                "sdk-matrix-provider-authority-or-reclamation")
        shutdown = receipt["nodeShutdown"]
        require(shutdown["reaped"] is True and shutdown["record"]["clean"] is True
                and shutdown["record"]["report"]["clean"] is True
                and shutdown["record"]["report"]["providers"]["clean"] is True,
                "sdk-matrix-node-not-cleanly-reaped")
        require(receipt["browserQualified"] is False and receipt["installedBundleQualified"] is False,
                "sdk-matrix-invented-qualification")
        languages[language] = {"receiptSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                               "identities": identities, "assertions": len(participant["assertions"]),
                               "activationIds": participant["activationIds"], "upstream": upstream,
                               "nodeCleanlyReaped": True}
    require(set(languages) == LANGUAGES, "sdk-matrix-incomplete")
    return {"schemaVersion": "latent.sdk.provider.matrix.v1", "passed": True,
            "sharedInputs": shared, "assertionsPerLanguage": len(ASSERTIONS), "languages": languages,
            "browserQualified": False, "installedBundleQualified": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.directory), separators=(",", ":")))
    except (WorkflowError, OSError, KeyError, TypeError, ValueError):
        print("sdk-provider-matrix-incomplete-or-invalid", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
