"""Actual HTTP command/query/recovery on the common production owners."""
from __future__ import annotations

import base64
import copy
import json
import time

from tools.static_api.node import policy

from . import configuration as cfg, http, lifecycle, provider
from .evidence import encoded
from .inputs import decode, digest, require


def command_input(delta, reject=False, *, reverse=False):
    require(type(delta) is int and 0 <= delta <= 2**32 - 1 and type(reject) is bool,
            "original-java-update-input")
    record = {"reject": reject, "delta": delta} if reverse else {"delta": delta, "reject": reject}
    return encoded([record])


def precondition(result):
    key = result["key-version"]
    if "none" in key:
        return '"absent"'
    return '"' + base64.b64encode(bytes(key["some"])).decode() + '"'


def rpc_result(record, result, publication, key):
    require(record["commandId"] == result["command-id"] and record["attemptId"] == result["attempt-id"]
            and record["metadataDurable"] is True
            and record["source"]["publicationId"] == publication
            and record["key"]["clientKey"] == key
            and record["outcome"] == ("COMMAND_OUTCOME_COMMITTED" if result["disposition"] == "committed"
                                      else "COMMAND_OUTCOME_REJECTED")
            and record["applicationStateCommitted"] is (result["disposition"] == "committed"),
            "actual-original-durable-command-inspection")
    retained = record["retainedResult"]
    require(retained["kind"] == ("success" if result["disposition"] == "committed" else "business-rejection")
            and retained["value"]["payload"] == {"encoding": "base64", "data": result["result"]["body-base64"]},
            "original-http-and-rpc-application-result-bytes")


class Campaign:
    def __init__(self, client, configuration, full_path, signed, items, publications,
                 proposals, policy_receipts, peer, node):
        self.client, self.configuration, self.signed = client, configuration, signed
        self.items = {item.name: item for item in items}
        self.publications, self.proposals, self.policy_receipts = publications, proposals, policy_receipts
        self.peer, self.node = peer, node
        self.full_path = full_path
        self.transport = http.Http(configuration.authority, client.deadline)
        self.originals = {}
        self.request_count = 0

    def socket(self, mode, *, original_key=None, body=None, condition=None, subject=cfg.ALICE,
               lose_body=False, path=None, minimum=None):
        headers = [("Authorization", "Bearer " + cfg.TOKENS[subject])]
        if original_key is not None:
            headers.append(("Idempotency-Key", original_key))
        if condition is not None:
            headers.append(("If-Match", condition))
        if minimum is not None:
            headers.append(("If-State-View", minimum))
        self.request_count += 1
        self.client.evidence.record(f"http-{self.request_count:03d}-input", {
            "mode": mode, "subject": subject, "originalClientKey": original_key,
            "originalPrecondition": condition, "minimumView": minimum, "path": path or lifecycle.PATHS[mode],
            "bodyBase64": None if body is None else base64.b64encode(body).decode()})
        result = self.transport.request("POST" if mode == "command" else "GET", path or lifecycle.PATHS[mode],
            body=body, headers=headers, lose_body=lose_body)
        raw = result.get("body")
        if raw is not None:
            self.client.evidence.write(f"http-{self.request_count:03d}.body", raw)
        self.client.evidence.record(f"http-{self.request_count:03d}-response", {
            "status": result["status"], "headers": result["headers"], "bodyLost": result.get("bodyLost", False)})
        return result

    def result(self, observed):
        require("body" in observed, "response-loss-cannot-supply-application-result")
        return http.response(observed["status"], observed["body"], observed["headers"])

    def query(self, count, *, minimum=None, original_key=None):
        value = self.result(self.socket("query", minimum=minimum, original_key=original_key))
        result = http.fresh_query(value)
        require(result["count"] == str(count), "actual-fresh-java-aggregate-value")
        return value, result

    def original(self, key):
        return self.result(self.socket("result", original_key=key))

    def refusal(self, name, observed, statuses):
        bodies = {403: {b"", b"Forbidden\n"}, 409: {b"", b"Conflict\n"}}
        require(observed["status"] in statuses and observed.get("body") in bodies[observed["status"]],
                "actual-redacted-http-platform-refusal")
        self.client.evidence.passed(name, {"status": observed["status"], "platformBodyBytes": len(observed["body"]),
                                         "applicationDataDisclosed": False})

    def wait_effect(self, publication, key, result, disposition="EFFECT_DISPOSITION_PROVIDER_ACKNOWLEDGED"):
        require(result["disposition"] == "committed" and len(result["effect-ids"]) == 1,
                "actual-one-retained-effect")
        until = min(self.client.deadline, time.monotonic() + 30)
        for _ in range(24):
            actual = lifecycle.effect(self.client, publication, key, result["effect-ids"][0])
            require(actual["effectId"] == result["effect-ids"][0]
                    and actual["commandId"] == result["command-id"]
                    and actual["commandAttemptId"] == result["attempt-id"], "actual-effect-command-link")
            if actual["disposition"] == disposition:
                return actual
            require(time.monotonic() < until, "actual-effect-disposition-watchdog")
            time.sleep(min(0.1, until - time.monotonic()))
        raise ValueError("actual-effect-disposition-not-observed")

    def peer_record(self, effect_id):
        row = provider.retained_record(self.peer.directory / (effect_id + ".json"), self.peer.incarnation, effect_id)
        require(row["state"] == "applied" and row["bodySha256"] == digest(provider.PAYLOAD)[7:],
                "actual-original-recipient-acceptance")
        return row

    def execute(self):
        legacy = "put-once-legacy-v1"
        publication = self.publications[legacy]
        lifecycle.deploy(self.client, self.signed, self.items[legacy], publication,
                         self.proposals["deploymentGrants"], self.configuration.authority)
        before = lifecycle.inspect_namespace(self.client, publication)
        view, initial = self.query(0)
        self.initial_view = view["state-view"]
        require(initial["key-version"] == {"none": None}, "fresh-namespace-key-is-absent")
        self.query(0, original_key="query-is-not-a-command")
        after = lifecycle.inspect_namespace(self.client, publication)
        require(before["commandCount"] == after["commandCount"] == "0", "fresh-query-creates-no-command-rows")
        self.client.evidence.passed("fresh-query-no-command", {"before": before, "after": after, "query": view})
        self._lost_and_duplicate(publication, initial)
        self._rejection(publication)
        self._isolation_and_preconditions(publication)
        self._policy_change(publication)
        self._scan(publication)
        self._compatible(publication)
        self._ambiguous_restart()
        self._retained_cancellation()
        self._unsigned_boundary()
        self.client.evidence.passed("fresh-java-invocations", {"httpRequests": self.transport.requests,
            "originalSourceDigest": self.items[legacy].source_digest,
            "freshInvocationGuard": "original-enter-counter", "guestCompilerInvoked": False})
        return {"httpRequests": self.transport.requests,
                "originalCommands": {key: value for key, value in self.originals.items()}}

    def _lost_and_duplicate(self, publication, initial):
        key, condition = "java-original-1", precondition(initial)
        lost = self.socket("command", original_key=key, body=command_input(1), condition=condition, lose_body=True)
        require(lost["status"] == 200 and lost["bodyLost"] is True, "actual-command-response-body-loss")
        value = self.original(key)
        require(value["disposition"] == "committed" and http.aggregate(value)["count"] == "1",
                "lost-response-original-commit-recovery")
        record = lifecycle.lookup(self.client, publication, key)
        rpc_result(record, value, publication, key)
        actual_effect = self.wait_effect(publication, key, value)
        peer = self.peer_record(value["effect-ids"][0])
        self.originals[key] = value
        self.client.evidence.passed("lost-response-after-commit", {"http": value, "command": record,
            "effect": actual_effect, "recipientAcceptance": peer, "recipientDeliveryQualified": False})
        duplicate = self.result(self.socket("command", original_key=key,
            body=command_input(1, reverse=True), condition=condition))
        http.replay(value, duplicate)
        require(self.peer_record(value["effect-ids"][0]) == peer, "duplicate-preserves-original-effect-acceptance")
        self.client.evidence.passed("canonical-duplicate-original", {"original": value, "replay": duplicate})
        self.refusal("changed-input-same-id", self.socket("command", original_key=key,
            body=command_input(2), condition=condition), {409})
        http.replay(value, self.original(key))
        self.query(1)
        minimum, _ = self.query(1, minimum=self.initial_view)
        self.client.evidence.passed("fresh-query-original-minimum", {"requestedMinimum": self.initial_view,
            "freshObservedSnapshot": minimum})

    def _rejection(self, publication):
        _, current = self.query(1)
        key, condition = "java-original-rejection", precondition(current)
        rejected = self.result(self.socket("command", original_key=key, body=command_input(5, True), condition=condition))
        require(rejected["disposition"] == "rejected" and not rejected["effect-ids"]
                and decode(http.canonical_base64(rejected["result"]["body-base64"], 131072)) == [{"err": "rejected"}],
                "actual-declared-business-rejection")
        record = lifecycle.lookup(self.client, publication, key)
        rpc_result(record, rejected, publication, key)
        self.originals[key] = rejected
        self.query(1)
        next_key = "java-original-2"
        committed = self.result(self.socket("command", original_key=next_key,
            body=command_input(2), condition=condition))
        require(committed["disposition"] == "committed" and http.aggregate(committed)["count"] == "3",
                "subsequent-original-business-change")
        self.wait_effect(publication, next_key, committed)
        self.originals[next_key] = committed
        replayed = self.result(self.socket("command", original_key=key,
            body=command_input(5, True, reverse=True), condition=condition))
        http.replay(rejected, replayed)
        self.query(3)
        self.client.evidence.passed("declared-rejection-after-change", {"original": rejected,
            "originalInspection": record, "businessChanged": committed, "rejectionReplay": replayed})

    def _isolation_and_preconditions(self, publication):
        _, current = self.query(3)
        stale = self.socket("command", original_key="java-stale", body=command_input(1), condition='"absent"')
        if stale["body"][:1] == b"{":
            rejected = self.result(stale)
            require(rejected["disposition"] == "aborted" and not rejected["effect-ids"]
                    and rejected["abort-fence"] is not None, "stale-edit-original-abort-proof")
            self.client.evidence.passed("stale-original-key-version", {"actualKnownNotCommitted": rejected})
        else:
            self.refusal("stale-original-key-version", stale, {409})
        before = lifecycle.inspect_namespace(self.client, publication)
        for subject in (cfg.BOB, cfg.FOREIGN):
            self.refusal("result-isolation-" + ("caller" if subject == cfg.BOB else "tenant"),
                         self.socket("result", original_key="java-original-1", subject=subject), {403})
            self.refusal("command-isolation-" + ("caller" if subject == cfg.BOB else "tenant"),
                         self.socket("command", original_key="java-isolated-" + subject,
                             body=command_input(1), condition=precondition(current), subject=subject), {403})
        self.query(3)
        actual = lifecycle.inspect_namespace(self.client, publication)
        require(actual["commandCount"] == before["commandCount"], "foreign-caller-creates-no-command-row")
        self.client.evidence.passed("isolation-preserves-durable-rows", {"before": before, "after": actual})

    def _policy_change(self, publication):
        original = self.proposals["policies"][cfg.STATE_POLICY]
        denied = copy.deepcopy(original)
        denied["rules"][0]["operations"].remove("read-result")
        generation = self.policy_receipts[cfg.STATE_POLICY]["generation"]
        revoked = policy(self.client, "policy", cfg.STATE_POLICY, denied, generation)
        self.refusal("current-result-read-revocation", self.socket("result", original_key="java-original-1"), {403})
        restored = policy(self.client, "policy", cfg.STATE_POLICY, original, revoked["generation"])
        self.policy_receipts[cfg.STATE_POLICY] = restored
        retained = self.original("java-original-1")
        http.replay(self.originals["java-original-1"], retained)
        self.client.evidence.passed("explicit-current-read-restoration", {"revocation": revoked,
            "restoration": restored, "original": retained,
            "currentInspection": lifecycle.lookup(self.client, publication, "java-original-1")})

    def _scan(self, publication):
        before = lifecycle.inspect_namespace(self.client, publication)
        frame = encoded([list(b"aggregate/"), 1, {"none": None}])
        path = lifecycle.PATHS["scan"] + "?input=" + base64.urlsafe_b64encode(frame).decode().rstrip("=")
        observed = self.result(self.socket("scan", path=path))
        actual = decode(http.canonical_base64(observed["result"]["body-base64"], 131072))
        require(isinstance(actual, list) and len(actual) == 1 and set(actual[0]) == {"ok"}, "actual-scan-result")
        result = actual[0]["ok"]
        require(set(result) == {"count", "encoded-bytes", "view-version", "next-cursor"}
                and type(result["count"]) is int and result["count"] == 1
                and isinstance(result["encoded-bytes"], str) and 0 < int(result["encoded-bytes"]) <= 4194304
                and bytes(result["view-version"]) == http.view_token(observed["state-view"]),
                "actual-bounded-native-scan-view")
        after = lifecycle.inspect_namespace(self.client, publication)
        require(after["commandCount"] == before["commandCount"], "scan-creates-no-command-row")
        self.client.evidence.passed("bounded-native-scan", {"query": observed, "before": before, "after": after})

    def _compatible(self, original_publication):
        compatible = "put-once-compatible-v2"
        require(lifecycle.schema(self.items[compatible]) == lifecycle.schema(self.items["put-once-legacy-v1"]),
                "actual-compatible-original-schema")
        publication = self.publications[compatible]
        lifecycle.deploy(self.client, self.signed, self.items[compatible], publication,
                         self.proposals["deploymentGrants"], self.configuration.authority)
        for key in ("java-original-1", "java-original-rejection"):
            retained = self.original(key)
            http.replay(self.originals[key], retained)
            record = lifecycle.lookup(self.client, publication, key)
            rpc_result(record, retained, original_publication, key)
            self.client.evidence.passed("compatible-original-" + ("commit" if key.endswith("1") else "rejection"),
                                        {"currentPublication": publication, "original": retained, "inspection": record})
        duplicate = self.result(self.socket("command", original_key="java-original-1",
            body=command_input(1, reverse=True), condition='"absent"'))
        http.replay(self.originals["java-original-1"], duplicate)
        self.client.evidence.passed("compatible-original-command-duplicate", {
            "currentPublication": publication, "retainedOriginalResult": duplicate})
        self.query(3)

    def _ambiguous_restart(self):
        publication = self.publications["put-once-compatible-v2"]
        _, current = self.query(3)
        # A controlled external fixture loses both the accepted PUT reply and
        # its status lookup. It cannot confer platform authority or commitment.
        mode = self.peer.directory / "mode"
        provider.private_write(mode, b"accept-ambiguous")
        key = "java-original-ambiguous"
        committed = self.result(self.socket("command", original_key=key,
            body=command_input(1), condition=precondition(current)))
        require(committed["disposition"] == "committed" and http.aggregate(committed)["count"] == "4",
                "actual-commit-before-uncertain-dispatch")
        actual = self.wait_effect(publication, key, committed, "EFFECT_DISPOSITION_UNCERTAIN_AFTER_DISPATCH")
        peer = self.peer_record(committed["effect-ids"][0])
        self.originals[key] = committed
        self.client.evidence.passed("ambiguous-provider-acceptance", {"commit": committed,
            "effect": actual, "recipientAcceptance": peer, "recipientDeliveryQualified": False})
        self.node.crash()
        # Changing only the external fault permits the existing native status
        # lookup. The same original IDs/receipt/horizon remain authoritative.
        with mode.open("wb") as output:
            output.write(b"reply")
        self.node.start(self.full_path)
        http.replay(committed, self.original(key))
        self.query(4)
        recovered = self.wait_effect(publication, key, committed)
        require(self.peer_record(committed["effect-ids"][0]) == peer, "restart-preserves-original-provider-acceptance")
        rpc_result(lifecycle.lookup(self.client, publication, key), committed, publication, key)
        self.client.evidence.passed("crash-restart-original-recovery", {"original": committed,
            "effectBefore": actual, "effectAfter": recovered, "recipientAcceptance": peer})

    def _retained_cancellation(self):
        key = "java-original-1"
        original = self.originals[key]
        publication = self.publications["put-once-compatible-v2"]
        with lifecycle.as_user(self.client):
            result = self.client.call("transaction", "cancel", *lifecycle.namespace_arguments(publication),
                "--operation", "update", "--client-key", key, "--attempt-id", original["attempt-id"],
                "--reason", "cancelled")["data"]
        rpc_result(result["command"], original, self.publications["put-once-legacy-v1"], key)
        http.replay(original, self.original(key))
        self.query(4)
        self.client.evidence.passed("cancellation-after-commit", result)

    def _unsigned_boundary(self):
        publication = self.publications["put-once-compatible-v2"]
        _, current = self.query(4)
        key = "java-original-unsigned-boundary"
        value = self.result(self.socket("command", original_key=key,
            body=command_input(2**32 - 1), condition=precondition(current)))
        require(value["disposition"] == "committed" and http.aggregate(value)["count"] == str(2**32 + 3),
                "actual-u32-maximum-input-and-u64-state-result")
        self.wait_effect(publication, key, value)
        self.originals[key] = value
        fresh, aggregate = self.query(2**32 + 3)
        require("some" in aggregate["key-version"], "actual-present-native-key-version")
        self.client.evidence.passed("unsigned-input-wide-state-result", {"original": value, "freshQuery": fresh,
            "u32Input": 2**32 - 1, "u64Result": str(2**32 + 3), "u64MaximumQualified": False})
