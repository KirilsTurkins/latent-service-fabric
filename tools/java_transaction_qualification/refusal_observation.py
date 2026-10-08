"""One bounded history observation; no retry or inference of native commitment."""
from __future__ import annotations

import time

from . import configuration as cfg


def _root(value):
    if not isinstance(value, dict):
        return None
    result = {}
    for key in ("phase", "terminalState", "principalKind"):
        text = value.get(key)
        result[key] = text if isinstance(text, str) and text.isascii() and len(text) <= 64 else None
    result["targetMatchesCurrentService"] = value.get("targetService") == cfg.SERVICE
    diagnostic = value.get("diagnostic")
    result["diagnostic"] = None
    if isinstance(diagnostic, dict):
        result["diagnostic"] = {key: diagnostic[key] if type(diagnostic.get(key)) is int
            and 0 <= diagnostic[key] <= 2 ** 31 - 1 else None for key in ("stage", "reason")}
    result["diagnosticIsTerminal"] = value.get("diagnosticIsTerminal") is True
    return result


def observe(client):
    summary = {"schemaVersion": "latent.java.http-refusal-observation.v1",
               "observationAvailable": False, "rootCount": None, "truncated": None, "roots": []}
    try:
        remaining = client.deadline - time.monotonic()
        if remaining <= 0:
            return
        result = client.call("activation", "roots", "--service", cfg.SERVICE, "--page-size", "8",
                             codes=(0, 2, 3, 4, 5, 6, 130), timeout=min(5, remaining))
        value = result.get("data")
        if result.get("category") == "success" and isinstance(value, dict):
            nodes = value.get("nodes")
            if isinstance(nodes, list) and len(nodes) <= 8:
                summary.update(observationAvailable=True, rootCount=len(nodes),
                    truncated=value.get("nextPageToken") is not None,
                    roots=[_root(row) for row in nodes])
    except (ValueError, OSError, RuntimeError, KeyError, TypeError):
        # The original transport/authorization oracle is still raised by caller.
        pass
    try:
        client.evidence.record("http-refusal-stage-observation", summary)
    except (ValueError, OSError):
        pass
