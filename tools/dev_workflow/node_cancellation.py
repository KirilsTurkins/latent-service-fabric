"""Cancel one observed running activation; never replay Invoke or Cancel."""
from __future__ import annotations

import time

from . import state
from .common import DevError, require


class Cancellation:
    def __init__(self, root, cli, activation, deadline):
        self.root, self.cli = root, cli
        self.deadline = min(deadline, time.monotonic() + 5)
        self.next_read = 0.0
        self.stopped = False
        self.report = {"activationId": activation, "trigger": "observed-running", "lookups": 0,
                       "runningObserved": False, "cancelCalls": 0, "disposition": "not-sent",
                       "confirmed": False, "terminalState": None}

    def save(self):
        # One bounded current record. It supplements the still-pending Invoke
        # intent, and recovery never dispatches a cancellation from this file.
        state.atomic(self.root, "test-cancellation.json", self.report)

    def check(self):
        now = time.monotonic()
        if self.stopped or now < self.next_read:
            return
        if now >= self.deadline or self.report["lookups"] >= 64:
            self.stopped = True
            self.report["disposition"] = "running-not-observed-within-bound"
            self.save()
            return
        self.next_read = now + 0.05
        self.report["lookups"] += 1
        activation = self.report["activationId"]
        remaining = min(1, self.deadline - now)
        value = self.cli.call("--rpc-timeout-ms", str(max(1, int(remaining * 800))),
                              "activation", "get", activation, timeout=remaining)
        if value.get("category") == "not-found":
            # The first read may precede ingress. Only bounded reads of this
            # original identity follow; this is never permission to re-invoke.
            return
        data = value.get("data", {})
        require(value.get("outcomeKnown") is True and value.get("category") == "success"
                and data.get("activationId") == activation, "cancellation-status-unconfirmed")
        if data.get("terminalState") is not None:
            self.stopped = True
            self.report["disposition"] = "terminal-before-cancel"
            self.save()
            return
        if data.get("phase") != "running":
            return
        self.stopped = True
        self.report.update(runningObserved=True, disposition="prepared-original-cancel")
        self.save()  # durable intent before the only Cancel dispatch
        remaining = min(1, self.deadline - time.monotonic())
        require(remaining > 0, "cancellation-deadline-before-dispatch")
        self.report["cancelCalls"] = 1
        try:
            cancelled = self.cli.call("--rpc-timeout-ms", str(max(1, int(remaining * 800))),
                "activation", "cancel", activation, "--reason", "explicit-development-scenario",
                timeout=remaining)
        except (DevError, OSError, ValueError, KeyboardInterrupt):
            self.report["disposition"] = "cancel-response-unavailable-no-replay"
            self.save()
            raise
        result = cancelled.get("data", {})
        require(cancelled.get("outcomeKnown") is True and result.get("activationId") == activation,
                "cancellation-response-unconfirmed")
        disposition = result.get("disposition")
        require(disposition in {"accepted", "already_terminal", "not_found"}, "cancellation-disposition")
        self.report["disposition"] = disposition
        self.save()

    def finish(self, result):
        data = result.get("data", {})
        self.report["terminalState"] = data.get("terminalState")
        self.report["confirmed"] = (self.report["runningObserved"] and self.report["cancelCalls"] == 1
            and self.report["disposition"] == "accepted" and result.get("outcomeKnown") is True
            and data.get("activationId") == self.report["activationId"]
            and result.get("category") == "platform-failure" and data.get("terminalState") == "cancelled"
            and result.get("error", {}).get("code") == "cancelled")
        self.save()
        return dict(self.report)
