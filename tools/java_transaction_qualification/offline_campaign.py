"""Actual signed Java schema/history and terminal-effect restore observations.

The installed native helper owns review, current authority and final writes.
This conductor supplies original data and records actual outcomes only.
"""
from __future__ import annotations

import copy
from pathlib import Path

from tools.phase2_operator_process import read_json, write_json

from . import configuration as cfg, http, lifecycle, provider, recovery
from .campaign import command_input, precondition, rpc_result
from .inputs import require


def generation(value):
    require(isinstance(value, str) and len(value) <= 20 and value.isascii() and value.isdecimal()
            and value == str(int(value)) and 0 < int(value) < 2**64,
            "original-namespace-generation-required")
    return value


def original_snapshot(value, operation):
    recovery.original_digest(value["snapshotDigest"])
    recovery.original_digest(value["manifestDigest"])
    metadata = value["manifest"]["metadata"]
    require(isinstance(metadata, dict)
            and set(metadata) == {"tenant", "operation_id", "operator_id", "runtime_digest",
                                  "decoder_formats", "required_artifacts"}
            and metadata["tenant"] == cfg.TENANT and metadata["operator_id"] == cfg.OPERATOR
            and metadata["operation_id"] == operation, "original-native-snapshot-attribution")
    # The original manifest is retained verbatim. Its native registry/closure
    # validation is separate from this collector's attribution checks.
    return value


def epoch_advanced(previous, current, dimension):
    old, new = bytes(recovery.original_view(previous)), bytes(recovery.original_view(current))
    require(dimension in {"schema", "recovery"}, "closed-native-history-dimension")
    offset, other = (51, 59) if dimension == "schema" else (59, 51)
    require(new[:43] == old[:43] and new[other:other + 8] == old[other:other + 8]
            and int.from_bytes(new[offset:offset + 8], "little")
                > int.from_bytes(old[offset:offset + 8], "little"), "actual-native-history-epoch-advanced")


def restored_configuration(original, destination):
    require(isinstance(destination, Path) and destination.is_absolute()
            and len(str(destination)) <= 4096 and ".." not in destination.parts
            and not any(ord(character) < 32 or 127 <= ord(character) < 160 for character in str(destination))
            and destination.is_dir() and not destination.is_symlink(), "actual-native-restore-destination")
    require(isinstance(original.get("state"), dict)
            and type(original["state"].get("formatVersion")) is int and original["state"]["formatVersion"] == 1,
            "original-installed-state-configuration")
    settings = copy.deepcopy(original)
    # This selects the actual staged destination; all present-purpose/native
    # validation still runs. It narrows creation and retains every other owner.
    settings["state"]["stateRoot"] = str(destination)
    settings["state"]["createIfMissing"] = False
    return settings


class OfflineCampaign:
    def __init__(self, campaign, helper, directory):
        self.campaign, self.directory = campaign, directory
        self.client, self.node = campaign.client, campaign.node
        self.native = recovery.Recovery(self.client, helper, campaign.configuration, directory, self.node)
        self.writer = "put-once-writer-v2"
        self.publication = campaign.publications[self.writer]
        self.configuration = campaign.full_path

    def action(self, request, *, action=None):
        original = self.native.run(self.configuration, self.publication, request)
        result = recovery.require_success(original)
        require(result.get("action") == (action or request["action"]), "actual-native-action-result")
        return result

    def inspect(self):
        result = self.action({"action": "inspect-namespace"})
        recovery.original_view(result["view"])
        return result

    def recipient(self, label):
        observed = provider.observed_recipient(self.campaign.peer.directory / provider.OBSERVATION,
                                              self.campaign.peer.incarnation)
        self.client.evidence.record(label + "-recipient-observation", observed)
        return observed

    def quiesce(self, publication, operation):
        before = lifecycle.inspect_namespace(self.client, publication)
        result = self.client.call("state", "quiesce", *lifecycle.namespace_arguments(publication),
            "--operation-id", operation, "--expected-generation", generation(before["generation"]))
        receipt = result["data"]["receipt"]
        require(result["outcomeKnown"] is True and receipt["operationId"] == operation
                and receipt["authenticatedOperator"] == cfg.OPERATOR
                and result["data"]["auditAcknowledgement"] is not None,
                "actual-current-authorized-quiesce")
        self.client.evidence.passed(operation, {"originalNamespace": before, "actualReceipt": result["data"]})
        self.node.stop()
        lifecycle.admission_lease_interval(self.client)

    def snapshot(self, name, operation):
        file = {"root": str(self.directory), "name": name}
        result = self.action({"action": "snapshot", "operationId": operation, "file": file})
        return file, original_snapshot(result, operation)

    def originals(self, label):
        original_publication = self.campaign.publications["put-once-legacy-v1"]
        for key, outcome in (("java-original-1", "commit"), ("java-original-rejection", "rejection")):
            current = self.campaign.original(key)
            http.replay(self.campaign.originals[key], current)
            record = lifecycle.lookup(self.client, self.publication, key)
            rpc_result(record, current, original_publication, key)
            self.client.evidence.passed(label + "-original-" + outcome,
                {"currentPublication": self.publication, "original": current, "currentInspection": record})

    def schema(self, count):
        before, _ = self.campaign.query(count)
        recipient = self.recipient("schema-before")
        self.quiesce(self.campaign.publications["put-once-compatible-v2"], "java-schema-quiesce")
        observed = self.inspect()
        file, checkpoint = self.snapshot("schema-checkpoint-v1.snapshot", "java-schema-checkpoint")
        migration = {"operationId": "java-schema-v1-to-v2", "file": file,
            "expectedView": recovery.original_view(observed["view"]),
            "checkpointDigest": checkpoint["snapshotDigest"],
            "checkpointManifestDigest": checkpoint["manifestDigest"]}
        staged = self.action(dict(migration, action="stage-migration"), action="migration")
        require(staged["completed"] is False, "actual-native-migration-staged")
        completed = self.action(dict(migration, action="complete-migration"), action="migration")
        require(completed["completed"] is True, "actual-native-migration-completed")
        after = self.inspect()
        epoch_advanced(observed["view"], after["view"], "schema")
        # Capture the quiesced V2 state before any later command. All effects in
        # this profile were already positively acknowledged by the base campaign.
        snapshot_file, snapshot = self.snapshot("restore-checkpoint-v2.snapshot", "java-restore-checkpoint")
        resumed = self.action({"action": "resume", "operationId": "java-schema-resume",
            "expectedView": recovery.original_view(after["view"])})
        self.node.start(self.configuration)
        lifecycle.deploy(self.client, self.campaign.signed, self.campaign.items[self.writer], self.publication,
            self.campaign.proposals["deploymentGrants"], self.campaign.configuration.authority)
        current, _ = self.campaign.query(count)
        self.campaign.refusal("schema-refuses-stale-query-minimum",
            self.campaign.socket("query", minimum=before["state-view"]), {409})
        self.originals("schema")
        require(self.recipient("schema-after") == recipient, "schema-and-replay-create-no-provider-request")
        self.client.evidence.passed("actual-java-schema-migration", {
            "originalView": before, "staged": staged, "completed": completed,
            "resume": resumed, "freshQuery": current})
        return snapshot_file, snapshot, current

    def restore(self, count, file, snapshot, current):
        _, aggregate = self.campaign.query(count)
        key = "java-after-restore-checkpoint"
        changed = self.campaign.result(self.campaign.socket("command", original_key=key,
            body=command_input(1), condition=precondition(aggregate)))
        require(changed["disposition"] == "committed" and http.aggregate(changed)["count"] == str(count + 1),
                "actual-post-backup-java-business-change")
        self.campaign.wait_effect(self.publication, key, changed)
        recipient = self.recipient("restore-before")
        self.campaign.query(count + 1)
        self.quiesce(self.publication, "java-restore-quiesce")
        original_settings = read_json(self.configuration)
        destination = self.directory / "restored-state"
        require(destination.is_absolute() and not destination.exists() and not destination.is_symlink(),
                "fresh-native-restore-destination")
        request = {"file": file, "destinationRoot": str(destination),
            "operationId": "java-explicit-restore", "snapshotDigest": snapshot["snapshotDigest"]}
        window = self.action(dict(request, action="inspect-restore"))
        require(window["snapshot"]["snapshotDigest"] == snapshot["snapshotDigest"]
                and window["snapshot"]["manifestDigest"] == snapshot["manifestDigest"],
                "original-native-restore-window-snapshot")
        acknowledgement = recovery.original_digest(window["windowDigest"])
        restored = self.action(dict(request, action="restore", windowAcknowledgement=acknowledgement))
        require(restored["snapshotDigest"] == snapshot["snapshotDigest"]
                and restored["manifestDigest"] == snapshot["manifestDigest"], "original-native-restored-snapshot")
        require(self.recipient("restored-before-review") == recipient, "restored-history-does-not-redrive-before-review")
        settings = restored_configuration(original_settings, destination)
        self.configuration = self.campaign.full_path.parent / "restored-node.json"
        write_json(self.configuration, settings)
        self.configuration.chmod(0o600)
        self.client.evidence.record("deliberate-restored-root-selection", {
            "configuration": str(self.configuration), "stateRoot": str(destination),
            "originalDestinationIdentity": restored["destinationIdentity"],
            "originalDataDirectory": original_settings["dataDirectory"],
            "creationNarrowed": True, "currentAuthorityInferred": False})
        reviewed = self.action({"action": "review"})
        observed = self.inspect()
        requested = recovery.original_view(observed["view"])
        epoch_advanced(list(http.view_token(current["state-view"])), requested, "recovery")
        resumed = self.action({"action": "resume", "operationId": "java-restored-resume",
            "expectedView": requested})
        self.node.start(self.configuration)
        self.campaign.full_path = self.configuration
        recovered, _ = self.campaign.query(count)
        self.campaign.refusal("restore-refuses-stale-query-minimum",
            self.campaign.socket("query", minimum=current["state-view"]), {409})
        self.originals("restore")
        # The data-loss window is deliberate: this command/effect occurred
        # after the snapshot. Never rerun it or infer a durable abort/not-sent.
        lost = self.campaign.socket("result", original_key=key)
        require(lost["status"] == 404, "post-snapshot-command-history-is-unknown")
        require(self.recipient("restore-after") == recipient, "restored-history-and-replay-create-no-provider-request")
        self.client.evidence.passed("actual-java-terminal-history-restore", {
            "window": window, "acknowledgement": acknowledgement, "restored": restored,
            "review": reviewed, "resume": resumed, "freshQuery": recovered,
            "postBackupOriginal": changed, "postBackupResultStatus": lost["status"],
            "originalCommandRerun": False, "pendingEffectRestoreQualified": False})

    def execute(self):
        count = 2**32 + 3
        file, snapshot, current = self.schema(count)
        self.restore(count, file, snapshot, current)
        require(self.native.calls == 12, "original-bounded-recovery-sequence")
        return {"nativeActions": self.native.calls, "pendingEffectRestoreQualified": False,
                "signedJavaSchemaAndTerminalRestoreObserved": True}
