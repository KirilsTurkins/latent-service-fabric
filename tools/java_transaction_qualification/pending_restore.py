"""Separate signed Java unresolved-effect restore programme; no native authority.

The external recipient applies once while the native outcome remains Uncertain.
The installed V3 owner supplies the exact close plan, authorization and receipt.
The independent native golden covers a literal Pending row; this programme keeps
its actual Uncertain disposition instead of inventing another observation.
"""
from __future__ import annotations

import copy
import re

from tools.phase2_operator_process import read_json, write_json

from . import configuration as cfg, http, lifecycle, provider, recovery
from .campaign import command_input, precondition, rpc_result
from .evidence import encoded
from .inputs import require
from .offline_campaign import OfflineCampaign, epoch_advanced, restored_configuration

PLAN_FIELDS = {"schemaVersion", "operatorId", "operationId", "scope", "expectedView",
               "expectedGuard", "lossWindowDigest", "reason", "effects"}
SELECTION_FIELDS = {"effectId", "originalDigest", "payloadDigest", "historyDigest",
                    "originalDisposition", "originalClockMillis"}
REASON = "abandon restored unresolved work after independently observed remote application"


def positive(value):
    require(type(value) is int and 0 < value < 2**64, "native-original-positive-counter")
    return value


def close_plan(value, operation, effect, view):
    require(isinstance(value, dict) and set(value) == {
        "action", "plan", "planDigest", "proposedOutcome", "recoveryRemainsPaused"}
        and value["action"] == "inspect-close-effects"
        and value["proposedOutcome"] == "closed-without-redrive"
        and value["recoveryRemainsPaused"] is True, "original-native-close-inspection")
    plan = value["plan"]
    require(isinstance(plan, dict) and set(plan) == PLAN_FIELDS
        and plan["schemaVersion"] == "lsf.effect-recovery-close.v1"
        and plan["operatorId"] == cfg.OPERATOR and plan["operationId"] == operation
        and plan["scope"] == {"tenant": cfg.TENANT, "namespace": cfg.NAMESPACE, "incarnation": 1}
        and type(plan["scope"]["incarnation"]) is int and plan["reason"] == REASON,
        "original-native-close-attribution")
    require(recovery.original_view(plan["expectedView"]) == recovery.original_view(view),
            "original-native-close-view")
    guard = recovery.byte_array(plan["expectedGuard"], 2048)
    require(guard and len(encoded(plan)) <= 12288, "native-original-bounded-close-plan")
    for name in ("lossWindowDigest",):
        require(any(recovery.byte_array(plan[name], 32)) and len(plan[name]) == 32,
                "native-original-close-digest")
    rows = plan["effects"]
    require(isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict)
        and set(rows[0]) == SELECTION_FIELDS and rows[0]["effectId"] == effect
        and isinstance(effect, str) and re.fullmatch(r"[0-9a-f]{64}", effect)
        and rows[0]["originalDisposition"] == "Uncertain", "actual-restored-uncertain-selection")
    positive(rows[0]["originalClockMillis"])
    for name in ("originalDigest", "payloadDigest", "historyDigest"):
        require(len(rows[0][name]) == 32 and any(recovery.byte_array(rows[0][name], 32)),
                "native-original-close-digest")
    recovery.original_digest(value["planDigest"])
    return plan


def close_receipt(value, inspected):
    require(isinstance(value, dict) and set(value) == {
        "action", "receipt", "recoveryRemainsPaused", "providerAcknowledgementInferred"}
        and value["action"] == "close-effects" and value["recoveryRemainsPaused"] is True
        and value["providerAcknowledgementInferred"] is False, "original-native-close-outcome")
    receipt = value["receipt"]
    require(isinstance(receipt, dict) and set(receipt) == {
        "schemaVersion", "outcome", "plan", "acknowledgement", "observedAtMillis"}
        and receipt["schemaVersion"] == "lsf.effect-recovery-close.v1"
        and receipt["outcome"] == "closed-without-redrive"
        and receipt["plan"] == inspected["plan"], "original-native-close-receipt")
    require(recovery.byte_array(receipt["acknowledgement"], 32)
        == bytes.fromhex(inspected["planDigest"][7:]), "original-native-close-acknowledgement")
    require(positive(receipt["observedAtMillis"])
        >= receipt["plan"]["effects"][0]["originalClockMillis"], "native-original-close-clock")
    return receipt


def wrong_ack_refused(value):
    require(value["operationSucceeded"] is False and value["result"] is None
        and value["failure"] is not None, "actual-wrong-close-ack-refused")
    detail = value["failure"].get("failure", {})
    require(value["failure"].get("stage") == "review"
        and detail == {"owner": "storage", "reason": "unavailable"},
        "wrong-ack-needs-original-native-review-refusal")
    retired = value["retirement"]
    require(retired is not None and retired["clean"] and retired["physicallyRetired"]
        and retired["liveWorkers"] == retired["acceptedJobs"] == 0
        and type(retired["threadsJoined"]) is int and retired["threadsJoined"] > 0
        and value["catalogsRetired"], "actual-wrong-ack-owner-retired")


class PendingRestore(OfflineCampaign):
    def __init__(self, campaign, helper, directory):
        super().__init__(campaign, helper, directory)
        self.writer = "put-once-legacy-v1"
        self.publication = campaign.publications[self.writer]

    def execute(self):
        campaign = self.campaign
        lifecycle.deploy(self.client, campaign.signed, campaign.items[self.writer], self.publication,
            campaign.proposals["deploymentGrants"], campaign.configuration.authority)
        _, aggregate = campaign.query(0)
        mode = campaign.peer.directory / "mode"
        provider.private_write(mode, b"accept-ambiguous")
        key = "java-pending-restore-original"
        original = campaign.result(campaign.socket("command", original_key=key,
            body=command_input(1), condition=precondition(aggregate)))
        require(original["disposition"] == "committed" and http.aggregate(original)["count"] == "1",
                "actual-signed-java-pending-commit")
        unresolved = campaign.wait_effect(self.publication, key, original,
            "EFFECT_DISPOSITION_UNCERTAIN_AFTER_DISPATCH")
        effect = original["effect-ids"][0]
        rpc_result(lifecycle.lookup(self.client, self.publication, key), original, self.publication, key)
        campaign.peer_record(effect)
        self.quiesce(self.publication, "java-pending-before-backup")
        observed = self.inspect()  # 1
        file, snapshot = self.snapshot("uncertain-before-ack.snapshot", "java-pending-checkpoint")  # 2
        self.action({"action": "resume", "operationId": "java-pending-original-resume",
            "expectedView": recovery.original_view(observed["view"])})  # 3
        with mode.open("wb") as output:
            output.write(b"reply")
        self.node.start(self.configuration)
        http.replay(original, campaign.original(key))
        campaign.query(1)
        acknowledged = campaign.wait_effect(self.publication, key, original)
        self.quiesce(self.publication, "java-pending-before-restore")
        recipient = self.recipient("pending-before-restore")
        require(recipient["appliedRecords"] == 1, "actual-single-remote-application")

        destination = self.directory / "restored-pending-state"
        require(destination.is_absolute() and not destination.exists() and not destination.is_symlink(),
                "fresh-native-pending-restore-destination")
        request = {"file": file, "destinationRoot": str(destination),
                   "operationId": "java-pending-explicit-restore", "snapshotDigest": snapshot["snapshotDigest"]}
        window = self.action(dict(request, action="inspect-restore"))  # 4
        require(window["snapshot"]["snapshotDigest"] == snapshot["snapshotDigest"]
            and window["snapshot"]["manifestDigest"] == snapshot["manifestDigest"], "original-native-pending-window")
        restored = self.action(dict(request, action="restore",
            windowAcknowledgement=recovery.original_digest(window["windowDigest"])))  # 5
        require(restored["snapshotDigest"] == snapshot["snapshotDigest"]
            and restored["manifestDigest"] == snapshot["manifestDigest"], "original-native-pending-snapshot")
        settings = restored_configuration(read_json(self.configuration), destination)
        self.configuration = campaign.full_path.parent / "restored-pending-node.json"
        write_json(self.configuration, settings)
        self.configuration.chmod(0o600)
        current = self.inspect()  # 6
        epoch_advanced(observed["view"], current["view"], "recovery")
        operation = "java-explicit-close-restored-uncertain"
        inspected = self.action({"action": "inspect-close-effects", "operationId": operation,
            "effectIds": [effect], "reason": REASON})  # 7
        plan = close_plan(inspected, operation, effect, current["view"])
        close = {"action": "close-effects", "operationId": operation, "plan": plan,
                 "acknowledgement": inspected["planDigest"]}
        wrong = copy.deepcopy(close)
        wrong["acknowledgement"] = "sha256:" + ("1" if inspected["planDigest"] != "sha256:" + "1" * 64 else "2") * 64
        denied = self.native.run(self.configuration, self.publication, wrong)  # 8
        wrong_ack_refused(denied)
        closed = self.action(close)  # 9
        receipt = close_receipt(closed, inspected)
        repeated = self.action(close)  # 10
        require(close_receipt(repeated, inspected) == receipt, "exact-original-close-receipt-replay")
        # The installed review can accept retained effects only after the exact
        # original unresolved row has its current-authorized close receipt.
        reviewed = self.action({"action": "review"})  # 11
        resumed = self.action({"action": "resume", "operationId": "java-pending-restored-resume",
            "expectedView": recovery.original_view(plan["expectedView"])})  # 12
        require(self.native.calls == 12, "original-bounded-pending-recovery-sequence")
        require(self.recipient("pending-closed-before-resume") == recipient, "offline-close-creates-no-provider-request")
        campaign.full_path = self.configuration
        for phase in ("resume", "same-root-reopen"):
            self.node.start(self.configuration)
            http.replay(original, campaign.original(key))
            campaign.query(1)
            closed_effect = campaign.wait_effect(self.publication, key, original,
                "EFFECT_DISPOSITION_DEAD_LETTERED")
            self.node.stop()
            lifecycle.admission_lease_interval(self.client)
            require(self.recipient("pending-after-" + phase) == recipient,
                    "closed-restored-effect-creates-no-provider-request")
            self.client.evidence.passed("java-pending-close-" + phase, {
                "originalCommand": original, "originalEffect": closed_effect,
                "recipient": recipient, "samePhysicalRoot": str(destination)})
        self.client.evidence.passed("actual-java-unresolved-effect-restore-close", {
            "originalCommand": original, "unresolvedBeforeSnapshot": unresolved,
            "originalAcknowledgementAfterSnapshot": acknowledged, "snapshot": snapshot,
            "restoreWindow": window, "restored": restored, "review": reviewed,
            "inspectedPlan": inspected, "wrongAcknowledgementRefusal": denied,
            "originalClose": closed, "closeReplay": repeated, "resume": resumed,
            "actualRestoredDisposition": "Uncertain", "providerAcknowledgementInferred": False,
            "originalCommandRerun": False, "secondRemoteApplication": False})
        return {"nativeActions": self.native.calls, "pendingEffectRestoreQualified": True,
                "actualRestoredDisposition": "Uncertain", "exactPendingRowQualified": False,
                "signedJavaSchemaAndTerminalRestoreObserved": False}
