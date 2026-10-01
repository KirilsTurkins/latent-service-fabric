"""Observe the actual bounded shared HTTP transport without inferring commitment from delivery."""
from __future__ import annotations

import base64
import http.client
import re
import time

from .inputs import decode, require

VALUE_MEDIA = "application/vnd.latent.wit-values.v1+json"
RESULT_MEDIA = "application/vnd.latent.transaction-http.v1+json"
MAX_BODY = 256 * 1024
ERROR_CODES = {"unavailable", "deadline-exceeded", "cancelled", "resource-exhausted",
               "permission-denied", "unauthenticated", "invalid-argument", "not-found",
               "already-exists", "incompatible-contract", "state-conflict", "dependency-failed",
               "guest-trap", "corrupt-artifact", "route-unavailable", "admission-rejected", "internal"}
FIELDS = {"profile", "disposition", "representation", "command-id", "attempt-id", "state-view",
          "effect-ids", "result-expires-at", "delivery-failure", "abort-fence", "result"}


def canonical_base64(value: str, maximum: int) -> bytes:
    require(isinstance(value, str) and len(value) <= 4 * ((maximum + 2) // 3), "bounded-base64-required")
    raw = base64.b64decode(value, validate=True)
    require(len(raw) <= maximum and base64.b64encode(raw).decode() == value, "canonical-base64-required")
    return raw


def view_token(value: str, kind=b"NV") -> bytes:
    raw = canonical_base64(value, 67)
    require(len(raw) == 67 and raw.startswith(kind + b"\x02")
            and all(int.from_bytes(raw[offset:offset + 8], "little") > 0
                    for offset in (35, 43, 51, 59)), "original-format2-view-token-required")
    return raw


def response(status: int, body: bytes, headers: list[tuple[str, str]]) -> dict:
    require(type(status) is int and status in {200, 202, 409, 410, 422, 503}, "transaction-response-status")
    require(len(body) <= MAX_BODY, "transaction-response-byte-bound")
    media = [value for key, value in headers if key.lower() == "content-type"]
    cache = [value for key, value in headers if key.lower() == "cache-control"]
    require(media == [RESULT_MEDIA] and cache == ["no-store"], "host-owned-transaction-response-headers")
    require(not any(key.lower() == "set-cookie" for key, _ in headers), "no-historical-session-material")
    value = decode(body, MAX_BODY)
    require(isinstance(value, dict) and set(value) == FIELDS
            and value["profile"] == "transaction-http-v1", "closed-transaction-response")
    require(value["representation"] in {"application-result", "receipt-only", "status-only"},
            "transaction-response-representation")
    disposition = value["disposition"]
    require(disposition in {"query", "committed", "rejected", "aborted", "in-progress", "recovery-required"},
            "finite-transaction-disposition")
    for name in ("command-id", "attempt-id"):
        raw = value[name]
        require((raw is None) == (disposition == "query")
                and (raw is None or isinstance(raw, str) and re.fullmatch(r"[0-9a-f]{64}", raw)),
                "original-command-attempt-identity")
    require(isinstance(value["effect-ids"], list) and len(value["effect-ids"]) <= 32
            and all(isinstance(item, str) and re.fullmatch(r"[0-9a-f]{64}", item) for item in value["effect-ids"])
            and len(set(value["effect-ids"])) == len(value["effect-ids"]), "original-effect-identities")
    if value["state-view"] is not None:
        view_token(value["state-view"])
    require(disposition != "query" or status in {200, 422} and value["state-view"] is not None
            and not value["effect-ids"] and value["abort-fence"] is None, "fresh-query-has-no-command-or-effects")
    expected = {"committed": 200, "rejected": 422, "aborted": 409,
                "in-progress": 202, "recovery-required": 503}
    require(disposition == "query" or status == expected[disposition]
            or status == 410 and value["representation"] == "receipt-only", "durable-status-association")
    payload = value["result"]
    require((payload is not None) == (value["representation"] == "application-result"),
            "application-result-presence")
    if payload is not None:
        require(isinstance(payload, dict) and set(payload) == {"media-type", "body-base64", "error-code", "error-message"}
                and payload["media-type"] == VALUE_MEDIA, "portable-application-result")
        canonical_base64(payload["body-base64"], 128 * 1024)
        code, message = payload["error-code"], payload["error-message"]
        require((code is None) == (message is None)
                and (code is None or isinstance(code, str) and 0 < len(code.encode()) <= 256
                     and isinstance(message, str) and len(message.encode()) <= 1024),
                "bounded-declared-error")
        require((code is not None) == (status == 422), "declared-error-status")
    expiration = value["result-expires-at"]
    require((expiration is None) == (disposition == "query")
            and (expiration is None or isinstance(expiration, str)
                 and re.fullmatch(r"0|[1-9][0-9]*", expiration)
                 and 0 < int(expiration) <= 2**64 - 1), "original-result-expiration")
    require(value["delivery-failure"] is None or isinstance(value["delivery-failure"], str)
            and value["delivery-failure"] in ERROR_CODES,
            "finite-delivery-failure-code")
    fence = value["abort-fence"]
    require((fence is not None) == (disposition == "aborted"), "actual-abort-proof-presence")
    if fence is not None:
        require(isinstance(fence, dict)
                and set(fence) == {"command-id", "attempt-id", "transaction-id", "owner-fence"}
                and fence["command-id"] == value["command-id"]
                and fence["attempt-id"] == value["attempt-id"]
                and isinstance(fence["transaction-id"], str)
                and re.fullmatch(r"[0-9a-f]{64}", fence["transaction-id"]),
                "original-server-issued-abort-fence")
        require(len(canonical_base64(fence["owner-fence"], 32)) == 32,
                "actual-32-byte-abort-proof")
    return value


def aggregate(value: dict) -> dict:
    payload = value["result"]
    require(payload is not None and payload["error-code"] is None, "successful-aggregate-required")
    frame = decode(canonical_base64(payload["body-base64"], 128 * 1024), 128 * 1024)
    require(isinstance(frame, list) and len(frame) == 1 and isinstance(frame[0], dict)
            and set(frame[0]) == {"ok"}, "actual-wit-result-frame")
    result = frame[0]["ok"]
    require(isinstance(result, dict) and set(result) == {"count", "view-version", "key-version"},
            "actual-java-aggregate-result")
    count = result["count"]
    require(isinstance(count, str) and re.fullmatch(r"0|[1-9][0-9]*", count)
            and int(count) <= 2**64 - 1, "full-width-unsigned-aggregate")
    token = result["view-version"]
    require(isinstance(token, list) and len(token) == 67
            and all(type(item) is int and 0 <= item <= 255 for item in token)
            and bytes(token).startswith(b"NV\x02"), "guest-observed-native-view")
    view_token(base64.b64encode(bytes(token)).decode())
    key = result["key-version"]
    require(isinstance(key, dict) and set(key) in ({"none"}, {"some"}), "absent-versus-present-key-version")
    if "none" in key:
        require(key["none"] is None, "absent-version-is-null")
    else:
        raw = key["some"]
        require(isinstance(raw, list) and len(raw) == 67
                and all(type(item) is int and 0 <= item <= 255 for item in raw)
                and bytes(raw).startswith(b"SV\x02"), "actual-key-version")
        view_token(base64.b64encode(bytes(raw)).decode(), b"SV")
    return result


def replay(original: dict, retained: dict) -> None:
    require(original["disposition"] in {"committed", "rejected"}, "terminal-original-result-required")
    # Current delivery status is independent from original durable identity.
    fields = FIELDS - {"delivery-failure"}
    require(all(retained[field] == original[field] for field in fields),
            "original-result-identity-and-bytes-must-not-change")


def fresh_query(value: dict) -> dict:
    require(value["disposition"] == "query", "ordinary-fresh-query-required")
    result = aggregate(value)
    require(bytes(result["view-version"]) == view_token(value["state-view"]),
            "query-must-report-the-same-native-read-view")
    return result


class Http:
    """One original deadline, finite requests, no transport-triggered mutation retry."""
    def __init__(self, authority: str, deadline: float, *, maximum_requests=96):
        require(re.fullmatch(r"localhost:[1-9][0-9]{0,4}", authority)
                and int(authority.rsplit(":", 1)[1]) <= 65535, "loopback-qualified-authority")
        require(0 < deadline - time.monotonic() <= 1200 and type(maximum_requests) is int
                and 1 <= maximum_requests <= 128, "original-http-campaign-bound")
        self.authority, self.deadline = authority, deadline
        self.maximum_requests, self.requests = maximum_requests, 0

    def request(self, method: str, path: str, *, body: bytes | None = None, headers=(), lose_body=False):
        require(self.requests < self.maximum_requests, "http-campaign-request-bound")
        remaining = self.deadline - time.monotonic()
        require(remaining > 0 and method in {"GET", "HEAD", "POST"}
                and path.startswith("/") and "\r" not in path and "\n" not in path,
                "original-http-campaign-deadline")
        require(body is None or isinstance(body, bytes) and len(body) <= 65536, "original-http-input-bound")
        self.requests += 1
        connection = http.client.HTTPConnection("127.0.0.1", int(self.authority.rsplit(":", 1)[1]),
                                                timeout=min(125, remaining))
        try:
            connection.putrequest(method, path, skip_host=True)
            for key, value in (("Host", self.authority), ("Origin", "http://" + self.authority),
                               ("Content-Type", VALUE_MEDIA), ("Connection", "close"), *headers):
                connection.putheader(key, value)
            if body is not None:
                connection.putheader("Content-Length", str(len(body)))
            connection.endheaders(body)
            result = connection.getresponse()
            observed_headers = result.getheaders()
            if lose_body:
                # Observe only transport headers. Commitment must subsequently
                # be proved by the original current-authorized result lookup.
                return {"status": result.status, "headers": observed_headers, "bodyLost": True}
            data = result.read(MAX_BODY + 1)
            require(len(data) <= MAX_BODY, "actual-http-response-bound")
            return {"status": result.status, "headers": observed_headers, "body": data}
        finally:
            connection.close()
