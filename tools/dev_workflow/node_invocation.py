"""One Invoke, followed only by bounded reads of its original identity on loss."""
from __future__ import annotations

import time

from .common import DevError


def execute(cli, journal, intent: dict, call, deadline: float) -> dict:
    operation = journal.begin("invoke", intent)
    try:
        return journal.finish(operation, call(operation["id"]))
    except (DevError, OSError, ValueError, KeyboardInterrupt) as error:
        # Process cleanup belongs to the client. The original remote operation
        # remains journaled until its actual terminal receipt is confirmed.
        cleanup_unknown = isinstance(error, DevError) and error.uncertain and error.code.startswith("owned-process-")
        recovery = {"disposition": "unknown-retained-original", "queries": 0,
                    "clientCleanup": "unconfirmed" if cleanup_unknown else "owned-client-reaped"}
        until = min(deadline, time.monotonic() + 5)
        for _ in range(0 if cleanup_unknown else 3):
            remaining = until - time.monotonic()
            if remaining <= 0:
                break
            recovery["queries"] += 1
            try:
                value = cli.call("--rpc-timeout-ms", str(max(1, min(1000, int(remaining * 1000)))),
                    "activation", "get", operation["id"], timeout=remaining)
                if value.get("category") == "not-found":
                    # Semantic UNKNOWN is not proof that Invoke did not run.
                    break
                if value.get("data", {}).get("terminalState") is not None:
                    terminal = journal.recover(lambda kind, identity: value)
                    recovery.update(disposition="terminal-receipt-confirmed", terminalState=terminal["data"]["terminalState"],
                                    outcome=terminal["category"])
                    break
            except (DevError, OSError, ValueError) as lookup_error:
                if (isinstance(lookup_error, DevError) and lookup_error.uncertain
                        and lookup_error.code.startswith("owned-process-")):
                    recovery["clientCleanup"] = "unconfirmed"
                    break
            time.sleep(min(0.05, max(0, until - time.monotonic())))
        # Status does not retain successful result bytes or a resolved revision.
        # It can settle ownership but cannot turn a lost test result into a pass.
        return {"category": "transport-failure", "outcomeKnown": False,
                "data": {"activationId": operation["id"], "recovery": recovery},
                "error": {"code": "original-invocation-result-unavailable"}}
