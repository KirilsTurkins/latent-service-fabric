"""One bounded history observation; no retry or inference of native commitment."""
from __future__ import annotations

import time

from . import configuration as cfg
from .inputs import require


def _root(value, service):
    if not isinstance(value, dict):
        return None
    result = {}
    for key in ("phase", "terminalState", "principalKind"):
        text = value.get(key)
        result[key] = text if isinstance(text, str) and text.isascii() and len(text) <= 64 else None
    result["targetMatchesCurrentService"] = value.get("targetService") == service
    diagnostic = value.get("diagnostic")
    result["diagnostic"] = None
    if isinstance(diagnostic, dict):
        result["diagnostic"] = {key: diagnostic[key] if type(diagnostic.get(key)) is int
            and 0 <= diagnostic[key] <= 2 ** 31 - 1 else None for key in ("stage", "reason")}
    result["diagnosticIsTerminal"] = value.get("diagnosticIsTerminal") is True
    return result


def observe(client, *, service=cfg.SERVICE):
    require(service in {cfg.SERVICE, cfg.EARLY_HTTP_SERVICE}, "explicit-java-refusal-observer-service")
    summary = {"schemaVersion": "latent.java.http-refusal-observation.v1",
               "requestedService": service,
               "observationAvailable": False, "rootCount": None, "truncated": None, "roots": []}
    try:
        remaining = client.deadline - time.monotonic()
        if remaining <= 0:
            return
        result = client.call("activation", "roots", "--service", service, "--page-size", "8",
                             codes=(0, 2, 3, 4, 5, 6, 130), timeout=min(5, remaining))
        value = result.get("data")
        if result.get("category") == "success" and isinstance(value, dict):
            nodes = value.get("nodes")
            if isinstance(nodes, list) and len(nodes) <= 8:
                summary.update(observationAvailable=True, rootCount=len(nodes),
                    truncated=value.get("nextPageToken") is not None,
                    roots=[_root(row, service) for row in nodes])
    except (ValueError, OSError, RuntimeError, KeyError, TypeError):
        # The original transport/authorization oracle is still raised by caller.
        pass
    try:
        client.evidence.record("http-refusal-stage-observation", summary)
    except (ValueError, OSError):
        pass
