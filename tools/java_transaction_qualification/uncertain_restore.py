"""Prepare one real remote-applied/unresolved restore on maintained owners.

This conductor needs the actual current signed Java campaign and its original
policy grants. Source tests cannot qualify this workflow. A pre-send Pending
checkpoint and general multi-tenant backup remain separate required cases.
"""
from __future__ import annotations

from pathlib import Path

from tools.phase2_operator_process import read_json, write_json

from . import http, provider, recovery
from .campaign import command_input, precondition
from .inputs import require
from .offline_campaign import OfflineCampaign, restored_configuration


class UncertainRestoreCampaign(OfflineCampaign):
    def __init__(self, campaign, helper: Path, directory: Path, variant: str):
        require(variant in {"put-once-legacy-v1", "put-once-compatible-v2", "put-once-writer-v2"}
                and variant in campaign.items and variant in campaign.publications,
                "actual-selected-signed-recovery-profile")
        super().__init__(campaign, helper, directory)
        self.writer = variant
        self.publication = campaign.publications[variant]

    def execute(self, count: int):
        require(type(count) is int and 0 <= count < 2**64 - 1, "original-recovery-aggregate-count")
        campaign = self.campaign
        _before, aggregate = campaign.query(count)
        mode = campaign.peer.directory / "mode"
        require(not mode.is_symlink() and provider.mode(campaign.peer.directory) == "reply",
                "original-recipient-reply-mode-before-unresolved-restore")
        if mode.exists():
            # The maintained base campaign owns this existing fault selector;
            # preserve its real recipient and change only the deliberate fault.
            with mode.open("wb") as output:
                output.write(b"accept-ambiguous")
        else:
            provider.private_write(mode, b"accept-ambiguous")
        key = "java-remote-applied-before-unresolved-restore"
        committed = campaign.result(campaign.socket("command", original_key=key,
            body=command_input(1), condition=precondition(aggregate)))
        require(committed["disposition"] == "committed"
                and http.aggregate(committed)["count"] == str(count + 1),
                "actual-original-business-commit-before-recovery")
        original_effect = campaign.wait_effect(self.publication, key, committed,
            "EFFECT_DISPOSITION_UNCERTAIN_AFTER_DISPATCH")
        effect = committed["effect-ids"][0]
        remote = campaign.peer_record(effect)
        require(remote["state"] == "applied",
                "actual-recipient-mutation-with-original-lost-reply")
        self.quiesce(self.publication, "java-unresolved-restore-quiesce")
        # Counter observations become stable only after actual node retirement.
        observed_remote = self.recipient("unresolved-before-snapshot")
        require(observed_remote["appliedRecords"] >= 1,
                "actual-recipient-mutation-retained-after-quiesced-retirement")
        file, snapshot = self.snapshot("unresolved-effect.snapshot", "java-unresolved-effect-backup")
        settings = read_json(self.configuration)
        destination = self.directory / "restored-unresolved-state"
        require(destination.is_absolute() and not destination.exists() and not destination.is_symlink(),
                "fresh-original-unresolved-restore-destination")
        original = {"file": file, "destinationRoot": str(destination),
                    "operationId": "java-unresolved-effect-restore", "snapshotDigest": snapshot["snapshotDigest"]}
        window = self.action(dict(original, action="inspect-restore"))
        require(window["snapshot"]["snapshotDigest"] == snapshot["snapshotDigest"]
                and window["snapshot"]["manifestDigest"] == snapshot["manifestDigest"],
                "same-original-unresolved-recovery-snapshot")
        restored = self.action(dict(original, action="restore",
            windowAcknowledgement=recovery.original_digest(window["windowDigest"])))
        require(restored["snapshotDigest"] == snapshot["snapshotDigest"]
                and restored["manifestDigest"] == snapshot["manifestDigest"],
                "actual-restored-unresolved-history")
        require(self.recipient("unresolved-restored-before-reconciliation") == observed_remote,
                "restored-unresolved-row-does-not-redrive")
        self.configuration = campaign.full_path.parent / "restored-unresolved-node.json"
        write_json(self.configuration, restored_configuration(settings, destination))
        self.configuration.chmod(0o600)
        operation = "java-explicit-unresolved-effect-close"
        inspected = self.action({"action": "inspect-close-effects", "operationId": operation,
            "effectIds": [effect], "reason": "original remote-applied effect requires explicit closure"})
        require(inspected["plan"]["effects"][0]["originalDisposition"] == "Uncertain",
                "actual-original-unresolved-disposition-remains-visible")
        # Exact acknowledged data is sent through the original authenticated
        # operator. The plan/digest alone supplies no native current authority.
        closed = self.action({"action": "close-effects", "operationId": operation,
            "plan": inspected["plan"], "acknowledgement": inspected["planDigest"]})
        require(closed["recoveryRemainsPaused"] is True
                and closed["providerAcknowledgementInferred"] is False,
                "explicit-close-is-not-provider-confirmation-or-resume")
        reviewed = self.action({"action": "review"})
        namespace = self.inspect()
        resumed = self.action({"action": "resume", "operationId": "java-explicit-unresolved-resume",
            "expectedView": recovery.original_view(namespace["view"])})
        self.node.start(self.configuration)
        campaign.full_path = self.configuration
        campaign.query(count + 1)
        replay = campaign.original(key)
        http.replay(committed, replay)
        require(self.recipient("unresolved-after-explicit-resume") == observed_remote
                and campaign.peer_record(effect) == remote,
                "explicit-reconciliation-and-replay-create-no-second-mutation")
        require(self.native.calls == 8, "original-bounded-unresolved-recovery-sequence")
        result = {"nativeActions": self.native.calls, "originalCommand": committed,
                  "originalEffect": original_effect, "snapshot": snapshot, "window": window,
                  "restored": restored, "inspectedPlan": inspected, "closeReceipt": closed,
                  "review": reviewed, "resume": resumed, "originalRecipient": remote,
                  "remoteObservation": observed_remote, "pendingBeforeSendRestoreQualified": False,
                  "generalBackupQualified": False, "providerAcknowledgementInferred": False}
        self.client.evidence.passed("actual-java-remote-applied-unresolved-history-restore", result)
        return result
