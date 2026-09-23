"""Persist intent before one mutation; recover only by the original identity."""
from __future__ import annotations

import secrets
from pathlib import Path

from . import state
from .common import DevError, digest, encode, members, require

MAX_HISTORY = 32


class Journal:
    def __init__(self, root: Path, node: str, tenant: str, *, settle=None):
        self.root, self.node, self.tenant = root, node, tenant
        self.settle = settle

    def read(self) -> dict:
        if not (self.root / "operations.json").exists():
            return {"schemaVersion": "latent.dev.operations.v1", "node": self.node,
                    "tenant": self.tenant, "pending": None, "history": []}
        value = state.load(self.root, "operations.json")
        members(value, {"schemaVersion", "node", "tenant", "pending", "history"})
        require(value["schemaVersion"] == "latent.dev.operations.v1" and value["node"] == self.node
                and value["tenant"] == self.tenant, "operation-owner-mismatch")
        require(isinstance(value["history"], list) and len(value["history"]) <= MAX_HISTORY, "operation-history-limit")
        return value

    def begin(self, kind: str, intent: dict) -> dict:
        require(kind in {"release", "deployment", "invoke"}, "operation-kind")
        value = self.read()
        if value["pending"] is not None:
            raise DevError("recover-original-operation-before-new-mutation", uncertain=True)
        operation = {"id": "dev-" + secrets.token_hex(16), "kind": kind, "intent": intent,
                     "requestDigest": digest(encode(intent)), "node": self.node, "tenant": self.tenant,
                     "state": "prepared"}
        value["pending"] = operation
        state.atomic(self.root, "operations.json", value)
        return operation

    def finish(self, operation: dict, result: dict) -> dict:
        value = self.read()
        require(value["pending"] == operation, "operation-journal-conflict")
        if result.get("outcomeKnown") is not True:
            raise DevError("operation-outcome-uncertain-use-recover", uncertain=True)
        # Commit idempotent local consequences before releasing this intent. A
        # crash between the two writes recovers the same ID and repeats only the
        # local metadata write, never the remote operation.
        if self.settle is not None:
            try:
                self.settle(operation, result)
            except DevError as error:
                raise DevError(error.code, uncertain=True) from None
        record = {"id": operation["id"], "kind": operation["kind"], "requestDigest": operation["requestDigest"],
                  "category": result["category"], "resultSha256": digest(encode(result)),
                  "source": operation["intent"].get("source")}
        require(len(encode(record)) <= 4096, "operation-receipt-byte-limit")
        value["history"] = (value["history"] + [record])[-MAX_HISTORY:]
        value["pending"] = None
        state.atomic(self.root, "operations.json", value)
        return result

    def execute(self, kind: str, intent: dict, call) -> dict:
        operation = self.begin(kind, intent)
        # There is deliberately no exception handler that resubmits this call.
        return self.finish(operation, call(operation["id"]))

    def recover(self, lookup) -> dict:
        value = self.read()
        pending = value["pending"]
        require(pending is not None, "no-pending-operation")
        try:
            return self._recover(pending, lookup)
        except DevError as error:
            # Any inconclusive validation still retains the original intent.
            raise DevError(error.code, uncertain=True) from None

    def _recover(self, pending: dict, lookup) -> dict:
        result = lookup(pending["kind"], pending["id"])
        data = result.get("data", {})
        if pending["kind"] != "invoke" and result.get("category") == "success":
            prefix = {"release": "RELEASE", "deployment": "DEPLOYMENT"}[pending["kind"]] + "_OPERATION_LOOKUP_DISPOSITION_"
            disposition = data.get("lookup", data.get("disposition", ""))
            if disposition == prefix + "UNKNOWN":
                raise DevError("original-operation-unknown-or-expired-no-replay", uncertain=True)
            if disposition == prefix + "UNCERTAIN":
                raise DevError("original-operation-durability-uncertain-no-replay", uncertain=True)
        if result.get("outcomeKnown") is not True:
            raise DevError("recovery-transport-outcome-unknown", uncertain=True)
        if pending["kind"] == "invoke":
            require(data.get("activationId") == pending["id"], "recovered-activation-identity")
            require(data.get("terminalState") in {"completed", "failed", "cancelled", "deadline_exceeded"},
                    "activation-cleanup-not-terminal")
        else:
            disposition = data.get("lookup", data.get("disposition", ""))
            receipt = data.get("receipt")
            expected = {"release": "RELEASE_OPERATION_LOOKUP_DISPOSITION_FOUND",
                        "deployment": "DEPLOYMENT_OPERATION_LOOKUP_DISPOSITION_FOUND"}[pending["kind"]]
            if not isinstance(receipt, dict) or disposition != expected:
                raise DevError("original-operation-unknown-or-expired-no-replay", uncertain=True)
            require(receipt.get("operationId") == pending["id"] and receipt.get("tenant") == self.tenant,
                    "recovered-operation-identity")
            for name in ("expectedGeneration", "expectedStateVersion"):
                if name in pending["intent"]:
                    require(receipt.get(name) == pending["intent"][name], "recovered-precondition-mismatch")
            if pending["kind"] == "release" and receipt.get("disposition") == "RELEASE_OPERATION_DISPOSITION_REJECTED":
                result = {**result, "category": "platform-failure", "error": {"code": "original-publication-rejected"}}
        return self.finish(pending, result)
