"""Confirm scoped test policy mutations through retained public receipts."""
from __future__ import annotations

import re

from .common import encode, require, sha


STAMP_FIELDS = ("tenant", "id", "recordKind", "generation", "contentDigest", "revoked")


def _generation(value, *, zero=False):
    return (type(value) is str and re.fullmatch(r"0|[1-9][0-9]{0,19}", value) is not None
            and int(value) <= 18446744073709551615 and (zero or value != "0"))


def _same_policy(current, receipt, document):
    return (isinstance(current, dict) and isinstance(receipt, dict)
            and isinstance(document, dict) and isinstance(current.get("document"), dict)
            and all(type(receipt.get(field)) is (bool if field == "revoked" else str)
                    and type(current.get(field)) is type(receipt[field])
                    and current[field] == receipt[field] for field in STAMP_FIELDS)
            and _generation(receipt["generation"])
            and encode(current["document"]) == encode(document))


def settle(root, operation: dict, result: dict) -> None:
    from . import state
    records = state.load(root, "test-policy-receipts.json") if (root / "test-policy-receipts.json").exists() else {}
    receipt = result["data"]["receipt"]
    key = receipt["recordKind"] + ":" + receipt["id"]
    require(key in records or len(records) < 32, "test-policy-retention-limit")
    records[key] = receipt
    state.atomic(root, "test-policy-receipts.json", records)


def apply(root, client, journal, policy_id: str, kind: str, document: dict) -> str:
    from . import state
    require(root.name.startswith("test-") and kind in {"policy", "provider-binding"}, "test-policy-scope")
    records = state.load(root, "test-policy-receipts.json") if (root / "test-policy-receipts.json").exists() else {}
    key = kind + ":" + policy_id
    require(key in records or len(records) < 32, "test-policy-retention-limit")
    observed = client.call("policy", "--kind", kind, "get", "--id", policy_id)
    require(observed.get("outcomeKnown") is True and observed.get("category") in {"success", "not-found"},
            "test-policy-observation-unavailable")
    if key in records:
        existing = observed["data"].get("policy")
        require(observed["category"] == "success" and _same_policy(existing, records[key], document),
                "test-policy-changed-no-overwrite")
        return policy_id
    require(observed["category"] == "not-found", "test-policy-not-owned-no-overwrite")
    state.atomic(root, "selected-test-policy.json", document)
    result = journal.execute("policy", {"policyId": policy_id, "recordKind": kind,
        "document": document, "expectedGeneration": "0"}, lambda operation:
        client.call("policy", "--kind", kind, "apply", "--id", policy_id, "--file", root / "selected-test-policy.json",
                    "--operation-id", operation, "--expected-generation", "0"))
    from .client import successful
    successful(result)
    return policy_id


def confirm(operation: dict, result: dict) -> None:
    intent = operation["intent"]
    receipt = result.get("data", {}).get("receipt")
    policy = result.get("data", {}).get("policy")
    require(isinstance(receipt, dict) and isinstance(policy, dict), "confirmed-policy-and-receipt-required")
    require(receipt.get("operationId") == operation["id"]
            and receipt.get("tenant") == operation["tenant"]
            and receipt.get("id") == intent["policyId"]
            and receipt.get("recordKind") == intent["recordKind"]
            and receipt.get("revoked") is False, "confirmed-policy-scope-mismatch")
    generation = receipt.get("generation")
    require(_generation(generation) and _generation(intent["expectedGeneration"], zero=True)
            and int(generation) > int(intent["expectedGeneration"]), "confirmed-policy-generation")
    sha(receipt.get("contentDigest"))
    require(_same_policy(policy, receipt, intent["document"]), "original-policy-changed-no-replay")


def lookup(client, operation: str) -> dict:
    result = client.call("policy", "operation", "--operation-id", operation)
    if result.get("outcomeKnown") is not True or result.get("category") != "success":
        return result
    receipt = result.get("data", {}).get("receipt")
    require(isinstance(receipt, dict) and receipt.get("operationId") == operation
            and receipt.get("recordKind") in {"policy", "provider-binding"}, "policy-lookup-identity")
    observed = client.call("policy", "--kind", receipt["recordKind"], "get", "--id", receipt["id"])
    require(observed.get("outcomeKnown") is True and observed.get("category") == "success",
            "original-policy-observation-unavailable-no-replay")
    return {**result, "data": {**result["data"], "policy": observed["data"].get("policy")}}
