"""Bounded read-only evidence after a capsule result fails its assertion."""
from __future__ import annotations

import json

from tools.phase2_operator_process import require, write_json

MAX_PAGES = 8
MAX_BYTES = 262144


def capture(client, result):
    """Keep the failed attempt; never retry invocation or change its result.

    The ordinary operator client enforces the experiment's original deadline,
    cancellation, control-count and output-retention limits. This private test
    receipt contains only the existing redacted CLI audit projection.
    """
    diagnostics = {"activation": result["activation"], "audit": [], "auditComplete": False}
    try:
        # Use the invocation's host timestamp, with a small overlap for the
        # audit accepted-at boundary. Do not scan older unrelated test history.
        since = max(0, int(result["startedAtUnixMillis"]) - 1000)
        token, seen = None, set()
        for _ in range(MAX_PAGES):
            command = ("audit", "query", "--scope", "tenant", "--page-size", "64",
                       "--from-unix-millis", str(since))
            if token is not None:
                command += ("--page-token", token)
            page = client._control_call(*command, codes=(0, 2, 3, 4, 5, 6, 130))
            require(len(json.dumps(diagnostics).encode()) + len(json.dumps(page).encode()) <= MAX_BYTES,
                    "authoring-invocation-diagnostic-retention")
            diagnostics["audit"].append(page)
            if page["category"] != "success":
                break
            token = page["data"]["page"]["nextPageToken"]
            if token is None:
                diagnostics["auditComplete"] = True
                break
            require(isinstance(token, str) and token not in seen, "authoring-invocation-diagnostic-cycle")
            seen.add(token)
    except Exception as error:
        # Preserve the original assertion even if the node or audit is already
        # unavailable. Exception text may contain private input and is omitted.
        diagnostics["diagnosticFailure"] = type(error).__name__
    try:
        encoded = json.dumps(diagnostics).encode()
        require(len(encoded) <= MAX_BYTES, "authoring-invocation-diagnostic-retention")
        client.retained += len(encoded)
        require(client.retained <= 4 * 1024 * 1024, "authoring-control-retention")
        write_json(client.evidence / "unexpected-invocation-diagnostics.json", diagnostics)
    except Exception:
        # A failed diagnostic write must not replace the failed invocation.
        pass
