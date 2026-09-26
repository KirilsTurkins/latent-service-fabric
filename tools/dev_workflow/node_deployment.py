"""One test deployment switch; recover a lost reply only by its original receipt."""
from __future__ import annotations

import time

from .common import DevError, require


def switch(cli, journal, deploy, deadline: float) -> dict | None:
    # Never recover an older operation as though it belonged to this switch.
    if journal.read()["pending"] is not None:
        raise DevError("recover-original-operation-before-new-mutation", uncertain=True)
    require(time.monotonic() < deadline, "node-test-run-deadline")
    try:
        deploy()
        return None
    except DevError as error:
        # This error is emitted only after the CLI process returned a structured
        # uncertain result. Do not mask rejected requests, validation failures,
        # interrupted clients or unconfirmed owned-process cleanup.
        if not error.uncertain or error.code != "operation-outcome-uncertain-use-recover":
            raise
        original_error = error
    operation = journal.read()["pending"]
    if operation is None or operation["kind"] != "deployment":
        raise original_error
    until = min(deadline, time.monotonic() + 5)
    for query in range(1, 4):
        remaining = until - time.monotonic()
        if remaining <= 0:
            break
        # These are reads, not retries of deploy/apply. Keep both the RPC and
        # its client inside the original scenario deadline and a finite bound.
        try:
            value = cli.call("--rpc-timeout-ms", str(max(1, min(1000, int(remaining * 1000)))),
                             "deployment", "operation", operation["id"], timeout=remaining)
        except (DevError, OSError, ValueError) as error:
            # Do not start another client when its predecessor's cleanup or
            # response validation is unconfirmed. Retain the original intent.
            code = error.code if isinstance(error, DevError) else "deployment-receipt-read-unavailable"
            raise DevError(code, uncertain=True) from None
        if value.get("outcomeKnown") is not True and value.get("category") in {"transport-failure", "platform-failure"}:
            if query < 3:
                time.sleep(min(0.05, max(0, until - time.monotonic())))
            continue
        # UNKNOWN/expired, uncertain durability, wrong identity/preconditions
        # and mismatched publication/generation all fail closed in the journal
        # and its settlement hook. No second mutation is ever dispatched.
        if journal.read()["pending"] != operation:
            raise DevError("operation-journal-conflict", uncertain=True)
        confirmed = journal.recover(lambda kind, identity: value)
        require(confirmed["category"] == "success", "operator-request-rejected-last-deployment-retained")
        return {"operationId": operation["id"], "queries": query, "disposition": "original-receipt-confirmed"}
    raise original_error
