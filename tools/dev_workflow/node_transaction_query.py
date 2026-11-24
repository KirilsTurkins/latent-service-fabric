"""Run one fresh query against the selected authenticated Phase 4 deployment."""
from __future__ import annotations

import base64
import re
import unicodedata

from . import state
from .common import DevError, integer, members, require

MEDIA_TYPE = "application/vnd.latent.wit-values.v1+json"


def validate(case: dict) -> None:
    selection = members(case["transactionQuery"], {"namespace", "incarnation"},
                        {"route", "entity", "minimumViewVersion"})
    for key in ("namespace", "route", "entity"):
        if key in selection:
            value = selection[key]
            require(isinstance(value, str) and 0 < len(value.encode("utf-8")) <= 256
                    and not any(unicodedata.category(char) == "Cc" for char in value),
                    "transaction-query-scope")
    incarnation = selection["incarnation"]
    require(isinstance(incarnation, str) and re.fullmatch(r"[1-9][0-9]{0,19}", incarnation),
            "transaction-query-incarnation")
    integer(int(incarnation), 1, 2**64 - 1)
    if "minimumViewVersion" in selection:
        token = selection["minimumViewVersion"]
        require(isinstance(token, str) and 0 < len(token) <= 344, "transaction-query-view")
        try:
            raw = base64.b64decode(token, validate=True)
        except ValueError:
            raise DevError("transaction-query-view") from None
        require(0 < len(raw) <= 256 and base64.b64encode(raw).decode("ascii") == token,
                "transaction-query-view")
    require(case["mediaType"] == MEDIA_TYPE and "transactional-state" in case["requires"]
            and "execution" not in case, "transaction-query-profile")


def execute(root, cli, case: dict, raw: bytes, budget: dict) -> dict:
    selection = case["transactionQuery"]
    state.atomic(root, "test-budget.json", {**budget, "stateWriteBytes": 0, "effectCount": 0})
    optional = []
    for key, option in (("route", "--route"), ("entity", "--entity"),
                        ("minimumViewVersion", "--minimum-view-version")):
        if key in selection:
            optional.extend([option, selection[key]])
    result = cli.call(
        "--phase4", "transaction", "query", "--service", case["service"], "--contract", case["contract"],
        "--function", case["function"], "--namespace", selection["namespace"], "--incarnation",
        selection["incarnation"], "--input", "-", "--budget", str(root / "test-budget.json"),
        "--rpc-timeout-ms", str(case["timeoutMillis"] + 1000), *optional, stdin=raw,
        timeout=case["timeoutMillis"] / 1000 + 5,
    )
    data = result["data"]
    if not isinstance(data.get("invocation"), dict):
        return result
    invocation = data["invocation"]
    source = data["source"]
    result_data = {"activationId": invocation["activationId"], "consumption": invocation["consumption"],
                   "transactionView": data["view"], "resolvedRevision": {
                       "publicationId": source["publicationId"], "revisionId": source["revisionId"],
                       "releaseDigest": source["componentDigest"], "routeGeneration": source["routeGeneration"],
                   }}
    body = invocation["result"]
    if body["kind"] in {"success", "business-rejection"}:
        value = body["value"]
        payload = value["payload"]
        projected = {**payload, "mediaType": value["mediaType"],
                     "byteLength": str(len(base64.b64decode(payload["data"], validate=True)))}
        if body["kind"] == "success":
            result_data["payload"] = projected
        else:
            result_data["declaredError"] = {"code": value["code"], "payload": projected}
    return {**result, "data": result_data}
