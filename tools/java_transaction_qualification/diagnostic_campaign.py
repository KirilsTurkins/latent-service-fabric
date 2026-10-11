"""Observe post-stage failures on the existing command/HTTP/node owners.

Running, request loss, charged counters and process exit are never staging or
abort evidence. A case needs the original host's captured-intent witness,
terminal accounting AND durable server-issued abort fence. Controlled crash
qualification remains separate from this source-only collector.
"""
from __future__ import annotations

import re
import socket
import threading
import time

from . import configuration as cfg, http, lifecycle, provider
from .diagnostic_inputs import LIMITS, NAME
from .inputs import require

WIDE = {"cpuFuel", "peakMemoryBytes", "wallTimeMicros", "stateReadBytes", "stateWriteBytes",
        "blobReadBytes", "blobWriteBytes", "logBytes"}
NARROW = {"childCalls", "outboundRequests", "effectCount"}
# Same value_bytes + captured-intent accounting in StateTransactionHost.stage:
# payload/media/empty metadata + 13-byte codec framing + names + 16 KiB reserve.
STAGE_WRITE_BYTES = len(provider.PAYLOAD) + len("application/octet-stream") + 13 + len("qualified-http") + len("put-once") + 16384
EXPECTED = {"trap": ("guest_trap", "guest-trap", None),
            "fuel": ("resource_exhausted", "resource-exhausted", 11),
            "memory": ("resource_exhausted", "resource-exhausted", 10),
            "cancel": ("cancelled", "cancelled", 15)}
STAGING_FIELDS = {"schemaVersion", "activationSerial", "commandId", "attemptId", "transactionId",
                  "publicationId", "stagedMutations", "capturedIntents", "stateWriteBytes", "observedAtUnixMillis"}


def unsigned(value):
    require(isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]{0,19}", value)
            and int(value) <= 2**64 - 1, "original-terminal-unsigned-consumption")
    return int(value)


def staging_witness(node, record, original=None):
    """Consume privileged original-host evidence; accounting cannot create it."""
    witness = node.get("transactionStaging")
    require(isinstance(witness, dict) and set(witness) == STAGING_FIELDS,
            "actual-host-captured-intent-staging-witness-required")
    require(type(witness["schemaVersion"]) is int and witness["schemaVersion"] == 1
            and unsigned(witness["activationSerial"]) > 0
            and all(isinstance(witness[name], str) and re.fullmatch(r"[0-9a-f]{64}", witness[name])
                    for name in ("commandId", "attemptId", "transactionId"))
            and isinstance(witness["publicationId"], str)
            and re.fullmatch(r"publication:sha256:[0-9a-f]{64}", witness["publicationId"]),
            "original-staging-serial-and-immutable-claim-identity")
    require(isinstance(record, dict) and record.get("metadataDurable") is True
            and isinstance(record.get("source"), dict)
            and witness["commandId"] == record.get("commandId")
            and witness["attemptId"] == record.get("attemptId")
            and witness["publicationId"] == record["source"].get("publicationId"),
            "staging-witness-matches-original-authorized-command")
    proof = record.get("provenAbort")
    if proof is not None:
        require(isinstance(proof, dict) and witness["commandId"] == proof.get("commandId")
                and witness["attemptId"] == proof.get("attemptId")
                and witness["transactionId"] == proof.get("transactionId"),
                "staging-witness-matches-original-abort-transaction")
    grant = node.get("grantedBudget")
    require(isinstance(grant, dict) and set(grant) == set(LIMITS), "actual-original-staging-grant")
    for name, expected in LIMITS.items():
        value = grant[name] if name in NARROW else unsigned(grant[name])
        require(type(value) is int and value == expected, "original-diagnostic-grant-unchanged")
    require(type(witness["stagedMutations"]) is int and witness["stagedMutations"] == 1
            and type(witness["capturedIntents"]) is int and witness["capturedIntents"] == grant["effectCount"] == 1
            and STAGE_WRITE_BYTES < unsigned(witness["stateWriteBytes"]) <= unsigned(grant["stateWriteBytes"])
            and unsigned(witness["observedAtUnixMillis"]) >= unsigned(node["receivedAtUnixMillis"]),
            "actual-post-insertion-state-put-and-captured-intent-progress")
    if original is not None:
        require(witness == original, "original-live-staging-witness-must-survive-terminal-inspection")
    return dict(witness)


def staged_terminal(status, node, kind, record, original_witness=None):
    require(kind in EXPECTED and status["activationId"] == node["activationId"]
            and status["phase"] == node["phase"] == "running" and node["targetService"] == cfg.SERVICE
            and node["parentActivationId"] is None and node["rootActivationId"] == status["activationId"]
            and node["principalKind"] == "user", "actual-original-terminal-http-root")
    state, code, reason = EXPECTED[kind]
    require(status["terminalState"] == node["terminalState"] == state
            and status["terminalOutcome"]["kind"] == "platform-failure"
            and status["terminalOutcome"]["error"]["code"] == code
            and status["terminalAtUnixMillis"] is not None, "actual-terminal-fault-category")
    require(isinstance(record, dict) and record.get("outcome") == "COMMAND_OUTCOME_ABORTED"
            and record.get("applicationStateCommitted") is False and isinstance(record.get("provenAbort"), dict),
            "original-terminal-durable-abort-required")
    witness = staging_witness(node, record, original_witness)
    require(unsigned(witness["observedAtUnixMillis"]) <= unsigned(status["terminalAtUnixMillis"]),
            "captured-intent-observation-precedes-original-terminal-record")
    consumption, budget = status["finalConsumption"], node["grantedBudget"]
    require(isinstance(consumption, dict) and set(consumption) == WIDE | NARROW
            and isinstance(budget, dict) and set(budget) == set(LIMITS), "actual-original-final-accounting")
    used = {name: unsigned(consumption[name]) for name in WIDE}
    for name in NARROW:
        require(type(consumption[name]) is int and 0 <= consumption[name] <= 2**32 - 1,
                "actual-terminal-narrow-accounting")
        used[name] = consumption[name]
    for name, expected in LIMITS.items():
        value = budget[name] if name in NARROW else unsigned(budget[name])
        require(type(value) is int and value == expected, "original-diagnostic-grant-unchanged")
    require(used["effectCount"] == 1 and used["stateWriteBytes"] > STAGE_WRITE_BYTES
            and 0 < used["cpuFuel"] <= LIMITS["cpuFuel"] and 0 < used["peakMemoryBytes"] <= LIMITS["memoryBytes"]
            and 0 < used["wallTimeMicros"] <= LIMITS["wallTimeLimitMillis"] * 1000
            and used["stateReadBytes"] <= LIMITS["stateReadBytes"]
            and used["stateWriteBytes"] <= LIMITS["stateWriteBytes"]
            and all(used[name] == 0 for name in ("childCalls", "outboundRequests", "blobReadBytes", "blobWriteBytes", "logBytes")),
            "positive-terminal-state-put-and-captured-intent-required")
    require(used["effectCount"] >= witness["capturedIntents"]
            and used["stateWriteBytes"] >= unsigned(witness["stateWriteBytes"]),
            "terminal-accounting-covers-original-captured-intent-witness")
    if reason is not None:
        observation = node["diagnostic"]
        require(node["diagnosticIsTerminal"] is True and isinstance(observation, dict)
                and type(observation["stage"]) is int and type(observation["reason"]) is int
                and observation["stage"] == 5 and observation["reason"] == reason,
                "actual-producer-owned-execution-fault-reason")
    return consumption


def aborted(record, result, item, publication, key):
    require(result["disposition"] == "aborted" and result["representation"] == "receipt-only"
            and result["result"] is None and result["state-view"] is None and not result["effect-ids"]
            and result["abort-fence"] is not None and result["delivery-failure"] is None,
            "actual-original-no-state-abort-receipt")
    proof = record["provenAbort"]
    require(record["outcome"] == "COMMAND_OUTCOME_ABORTED" and record["metadataDurable"] is True
            and record["applicationStateCommitted"] is False and record["commit"] is None
            and record["source"]["publicationId"] == publication
            and record["source"]["componentDigest"] == item.component_digest
            and record["key"]["clientKey"] == key and record["key"]["operation"] == "update"
            and record["key"]["namespace"] == {"tenant": cfg.TENANT, "namespace": cfg.NAMESPACE, "incarnation": "1"}
            and proof is not None and proof["ownerFence"]["encoding"] == "base64",
            "actual-current-authorized-original-aborted-command")
    require(proof == {"commandId": result["command-id"], "attemptId": result["attempt-id"],
                      "transactionId": result["abort-fence"]["transaction-id"],
                      "ownerFence": {"encoding": "base64", "data": result["abort-fence"]["owner-fence"]}}
            and record["commandId"] == result["command-id"] and record["attemptId"] == result["attempt-id"],
            "same-original-durable-server-issued-abort-fence")


def unchanged(before, after, recipient_before, recipient_after):
    require(before["count"] == after["count"] and before["key-version"] == after["key-version"],
            "post-stage-abort-preserves-original-business-state")
    require(all(recipient_before[name] == recipient_after[name] == 0 for name in provider.COUNTERS),
            "no-recipient-put-or-external-effect-after-staged-abort")


def roots(client):
    result, cursor = set(), None
    for _ in range(4):
        args = ("--page-token", cursor) if cursor is not None else ()
        value = client.call("activation", "roots", "--service", cfg.SERVICE, "--page-size", "32", *args)["data"]
        require(value["schemaVersion"] == 1 and value["retainedHistoryOnly"] is True
                and not value["cursorExpired"] and value["historyAvailable"] is True
                and isinstance(value["nodes"], list) and len(value["nodes"]) <= 32,
                "actual-bounded-retained-http-root-discovery")
        for row in value["nodes"]:
            identity = row["activationId"]
            require(isinstance(identity, str) and 0 < len(identity.encode()) <= 256
                    and row["rootActivationId"] == identity and row["parentActivationId"] is None
                    and row["targetService"] == cfg.SERVICE and identity not in result,
                    "actual-unique-http-root-lineage")
            result.add(identity)
        cursor = value["nextPageToken"]
        if cursor is None:
            return result
    raise ValueError("retained-http-root-discovery-page-bound")


def root_since(client, before):
    added = roots(client) - before
    require(len(added) == 1, "exactly-one-new-original-http-root")
    return added.pop()


class PendingHttp:
    """One bounded transport owner; stopping it cannot certify command abort."""
    def __init__(self, campaign, **arguments):
        self.lock, self.socket, self.closed, self.retired = threading.Lock(), None, False, False
        self.result, self.failure = None, None
        self.deadline = campaign.client.deadline
        def run():
            try:
                self.result = campaign.socket("command", request_owner=self, **arguments)
            except BaseException as error:
                self.failure = error
        self.thread = threading.Thread(target=run, name="java718-original-request", daemon=False)
        self.thread.start()

    def attach(self, connection):
        with self.lock:
            self.socket = connection
            closed = self.closed
        if closed:
            self.close_socket()
            raise ValueError("original-diagnostic-transport-closed")

    def detach(self):
        with self.lock:
            self.socket, self.retired = None, True

    def close_socket(self):
        with self.lock:
            self.closed = True
            connection = self.socket
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            finally:
                connection.close()

    def complete(self):
        self.thread.join(max(0, min(125, self.deadline - time.monotonic())))
        require(not self.thread.is_alive() and self.retired, "original-http-request-physical-retirement")
        if self.failure is not None:
            raise self.failure
        require(self.result is not None, "actual-original-http-response-required")
        return self.result

    def close(self):
        self.close_socket()
        self.thread.join(2)
        require(not self.thread.is_alive(), "original-http-request-owner-still-live")


class DiagnosticCampaign:
    def __init__(self, campaign, diagnostic):
        self.campaign, self.client, self.input = campaign, campaign.client, diagnostic
        self.publication = campaign.publications[NAME]

    def terminal(self, identity, kind, record, original_witness=None):
        status = self.client.call("activation", "get", identity)["data"]
        tree = self.client.call("activation", "tree", identity, "--page-size", "8")["data"]
        require(tree["schemaVersion"] == 1 and tree["historyAvailable"] is True and not tree["cursorExpired"]
                and tree["nextPageToken"] is None and len(tree["nodes"]) == 1,
                "one-original-terminal-command-activation")
        staged_terminal(status, tree["nodes"][0], kind, record, original_witness)
        return {"status": status, "tree": tree}

    def cancel(self, pending, before, key):
        # Root and durable claim discovery choose the original attempt only.
        # The captured-intent observer must then prove staging BEFORE cancellation.
        until = min(self.client.deadline, time.monotonic() + 10)
        for _ in range(8):
            added = roots(self.client) - before
            require(len(added) <= 1, "unambiguous-original-cancel-root")
            if added:
                identity = added.pop()
                break
            require(pending.thread.is_alive() and time.monotonic() < until, "original-command-not-running-for-cancel")
            time.sleep(0.05)
        else:
            raise ValueError("original-cancel-root-not-observed")
        record = self.original_attempt(pending, key, until)
        require(record["outcome"] == "COMMAND_OUTCOME_IN_PROGRESS" and record["metadataDurable"] is True
                and record["source"]["publicationId"] == self.publication
                and record["source"]["componentDigest"] == self.input.item.component_digest
                and record["key"]["clientKey"] == key, "actual-original-precommit-command-attempt")
        live = self.live_staging(pending, identity, record, until)
        with lifecycle.as_user(self.client):
            result = self.client.call("transaction", "cancel", *lifecycle.namespace_arguments(self.publication),
                "--operation", "update", "--client-key", key, "--attempt-id", record["attemptId"],
                "--reason", "cancelled")["data"]
        require(result["cancellationDisposition"] == "COMMAND_CANCEL_DISPOSITION_REQUESTED"
                and result["command"]["commandId"] == record["commandId"]
                and result["command"]["attemptId"] == record["attemptId"], "one-original-precommit-cancellation-request")
        self.client.evidence.record("diagnostic-cancel-original-request", {"activationId": identity, "original": record,
            "request": result, "livePostStageWitnessObserved": True, "originalStagingWitness": live})
        return identity, live

    def live_staging(self, pending, identity, record, until):
        for _ in range(8):
            require(pending.thread.is_alive() and time.monotonic() < until,
                    "original-command-not-running-for-staging-observation")
            tree = self.client.call("activation", "tree", identity, "--page-size", "8",
                                    timeout=until - time.monotonic())["data"]
            require(time.monotonic() < until and pending.thread.is_alive(),
                    "original-live-staging-observation-within-same-cutoff")
            require(tree["schemaVersion"] == 1 and tree["historyAvailable"] is True
                    and not tree["cursorExpired"] and tree["nextPageToken"] is None and len(tree["nodes"]) == 1,
                    "one-original-live-command-activation")
            node = tree["nodes"][0]
            require(node["activationId"] == node["rootActivationId"] == identity
                    and node["parentActivationId"] is None and node["targetService"] == cfg.SERVICE
                    and node["principalKind"] == "user" and node["terminalState"] is None
                    and node["phase"] in ("admitted", "queued", "materializing", "running"),
                    "original-precommit-root-and-current-live-stage")
            if node.get("transactionStaging") is not None:
                require(node["phase"] == "running", "original-running-captured-intent-host")
                return staging_witness(node, record)
            remaining = until - time.monotonic()
            require(remaining > 0, "original-staging-observation-expired")
            time.sleep(min(0.05, remaining))
        raise ValueError("original-host-captured-intent-not-observed")

    def original_attempt(self, pending, key, until):
        # Root admission precedes preparation and the durable claim. These are
        # finite reads of the same key, never another mutation or new deadline.
        for _ in range(8):
            require(pending.thread.is_alive() and time.monotonic() < until,
                    "original-command-not-running-for-cancel")
            with lifecycle.as_user(self.client):
                observed = self.client.call("transaction", "lookup", *lifecycle.namespace_arguments(self.publication),
                    "--operation", "update", "--client-key", key, codes=(0, 6))
            require(observed["outcomeKnown"] is True, "original-command-lookup-certainty")
            if observed["category"] == "success":
                return observed["data"]["command"]
            require(observed["category"] == "not-found" and observed["data"].get("command") is None,
                    "original-command-lookup-refusal")
            remaining = until - time.monotonic()
            require(remaining > 0, "original-command-not-running-for-cancel")
            time.sleep(min(0.05, remaining))
        raise ValueError("original-durable-attempt-not-observed")

    def case(self, kind, selector):
        from .campaign import command_input, precondition
        c = self.campaign
        _, before_value = c.query(0)
        condition = precondition(before_value)
        before_recipient = provider.observed_recipient(c.peer.directory / provider.OBSERVATION, c.peer.incarnation)
        before_roots = roots(self.client)
        key = "java-post-stage-" + kind
        arguments = {"original_key": key, "body": command_input(int(selector)), "condition": condition}
        live = None
        if kind == "cancel":
            pending = PendingHttp(c, **arguments)
            try:
                identity, live = self.cancel(pending, before_roots, key)
                observed = pending.complete()
            finally:
                pending.close()
        else:
            observed = c.socket("command", **arguments)
            identity = root_since(self.client, before_roots)
        # Preserve actual original transport bytes, but recover disposition
        # solely through the original current-authorized result lookup.
        result = c.original(key)
        record = lifecycle.lookup(self.client, self.publication, key)
        aborted(record, result, self.input.item, self.publication, key)
        terminal = self.terminal(identity, kind, record, live)
        require(record["retainedResult"]["kind"] == "technical-failure"
                and record["retainedResult"]["value"]["code"] == EXPECTED[kind][1],
                "original-durable-fault-code-matches-terminal-producer")
        _, after_value = c.query(0)
        after_recipient = provider.observed_recipient(c.peer.directory / provider.OBSERVATION, c.peer.incarnation)
        unchanged(before_value, after_value, before_recipient, after_recipient)
        return {"originalClientKey": key, "selector": selector, "originalPrecondition": condition,
                "transportStatus": observed["status"], "terminal": terminal, "command": record, "result": result,
                "beforeQuery": before_value, "afterQuery": after_value,
                "beforeRecipient": before_recipient, "afterRecipient": after_recipient}

    def execute(self):
        c = self.campaign
        lifecycle.deploy(self.client, c.signed, self.input.item, self.publication,
                         c.proposals["deploymentGrants"], c.configuration.authority)
        selected = {"trap": "trapAfterStage", "fuel": "loopAfterStage", "cancel": "loopAfterStage"}
        if "memoryAfterStage" in self.input.selectors:
            selected["memory"] = "memoryAfterStage"
        observations = {kind: self.case(kind, self.input.selectors[name]) for kind, name in selected.items()}
        # Original full physical teardown proves release; fresh success uses
        # the same store, current policies, recipient and nonrenewable deadline.
        c.node.stop()
        retired = c.node.shutdown[-1]
        c.node.start(c.full_path)
        legacy = c.items["put-once-legacy-v1"]
        lifecycle.deploy(self.client, c.signed, legacy, c.publications[legacy.name],
                         c.proposals["deploymentGrants"], c.configuration.authority)
        _, fresh = c.query(0)
        for kind, observed in observations.items():
            self.client.evidence.passed("actual-post-stage-" + kind, dict(observed,
                physicalRetirement=retired, freshQueryAfterRetirement=fresh, compiler=self.input.observation(),
                crashBeforeCommitQualified=False))
        qualified = ["trap-and-fuel-after-staging", "cancellation-before-commit"]
        if "memory" in observations:
            qualified.append("memory-exhaustion-before-commit")
        return qualified
