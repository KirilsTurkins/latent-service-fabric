"""Actual signed Java schema/history and terminal-effect restore observations.

The installed native helper owns review, current authority and final writes.
This conductor supplies original data and records actual outcomes only.
"""
from __future__ import annotations

import copy
from pathlib import Path

from tools.phase2_operator_process import read_json, write_json

from . import configuration as cfg, http, lifecycle, policies, provider, recovery
from . import restore_authority, restore_installation
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


def restored_resume_request(view, file, snapshot, acknowledgement, migration_operation=None):
    request = {'action': 'resume', 'operationId': 'java-restored-resume',
               'expectedView': recovery.original_view(view)}
    if migration_operation is not None:
        require(migration_operation == 'java-schema-v1-to-v2', 'original-current-migration-operation')
        require(isinstance(file, dict) and set(file) == {'root', 'name'}, 'original-restored-snapshot-file')
        request.update(action='resume-restored-migration', migrationOperationId=migration_operation,
            file=dict(file), snapshotDigest=recovery.original_digest(snapshot['snapshotDigest']),
            manifestDigest=recovery.original_digest(snapshot['manifestDigest']),
            windowAcknowledgement=recovery.original_digest(acknowledgement))
    return request


def restored_migration_result(result, request, review_digest):
    fields = {'action', 'receipt', 'view', 'replay', 'snapshotDigest', 'manifestDigest',
              'windowAcknowledgement', 'reviewDigest', 'resourcePhysicallyRetired'}
    require(isinstance(result, dict) and set(result) == fields
            and result['action'] == request['action'] == 'resume-restored-migration'
            and result['replay'] is False and result['resourcePhysicallyRetired'] is True,
            'closed-first-restored-migration-activation-result')
    receipt = recovery.byte_array(result['receipt'], 8192)
    require(len(receipt) > 4 and receipt.startswith(b'RMA\x01'), 'new-attributed-restored-migration-receipt')
    for field in ('snapshotDigest', 'manifestDigest', 'windowAcknowledgement'):
        require(recovery.original_digest(result[field]) == request[field], 'original-restored-activation-identities')
    require(recovery.original_digest(result['reviewDigest']) == recovery.original_digest(review_digest),
            'current-accepted-restored-review-identity')
    before = bytes(recovery.original_view(request['expectedView']))
    after = bytes(recovery.original_view(result['view']))
    require(after[:43] == before[:43] and after[51:] == before[51:]
            and int.from_bytes(after[43:51], 'little') == int.from_bytes(before[43:51], 'little') + 1,
            'restored-activation-advances-only-namespace-generation')
    return result


class OfflineCampaign:
    def __init__(self, campaign, helper, directory):
        self.campaign, self.directory = campaign, directory
        self.client, self.node = campaign.client, campaign.node
        self.current_v2 = read_json(campaign.full_path)["state"]["formatVersion"] == 2
        selection = {} if not self.current_v2 else {
            "sources": recovery.decoder_sources(campaign.items, campaign.publications)}
        self.native = recovery.Recovery(self.client, helper, campaign.configuration, directory, self.node, **selection)
        self.writer = "put-once-writer-v2"
        self.publication = campaign.publications[self.writer]
        self.configuration = campaign.full_path
        self.migration_operation = None

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
        observed = self.campaign.recipient_observation()
        self.client.evidence.record(label + "-recipient-observation", observed)
        return observed

    def quiesce(self, publication, operation):
        before = lifecycle.inspect_namespace(self.client, publication)
        result = self.client.call("state", "quiesce", *lifecycle.namespace_arguments(publication),
            "--operation-id", operation, "--expected-generation", generation(before["generation"]))
        receipt = result["data"]["receipt"]
        require(result["outcomeKnown"] is True and receipt["operationId"] == operation
                and receipt["authenticatedOperator"] == (lifecycle.operator_actor() if self.current_v2 else cfg.OPERATOR)
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
        activation = getattr(self.node, 'current_activation', None)
        if activation is not None:
            self.configuration = activation.select_metadata(self.writer, 'writer-metadata')
        observed = self.inspect()
        file, checkpoint = self.snapshot("schema-checkpoint-v1.snapshot", "java-schema-checkpoint")
        migration = {"operationId": "java-schema-v1-to-v2", "file": file,
            "expectedView": recovery.original_view(observed["view"]),
            "checkpointDigest": checkpoint["snapshotDigest"],
            "checkpointManifestDigest": checkpoint["manifestDigest"]}
        self.migration_operation = migration['operationId']
        staged = self.action(dict(migration, action="stage-migration"),
                             action="stage-migration" if self.current_v2 else "migration")
        require(staged["completed"] is False, "actual-native-migration-staged")
        completed = self.action(dict(migration, action="complete-migration"),
                                action="complete-migration" if self.current_v2 else "migration")
        require(completed["completed"] is True, "actual-native-migration-completed")
        after = self.inspect()
        epoch_advanced(observed["view"], after["view"], "schema")
        # Capture the quiesced V2 state before any later command. All effects in
        # this profile were already positively acknowledged by the base campaign.
        snapshot_file, snapshot = self.snapshot("restore-checkpoint-v2.snapshot", "java-restore-checkpoint")
        resume_request = {"action": "resume", "operationId": "java-schema-resume",
                          "expectedView": recovery.original_view(after["view"])}
        if self.current_v2:
            resume_request.update(action="resume-migration", migrationOperationId=migration["operationId"],
                                  file=file, migrationExpectedView=migration["expectedView"],
                                  checkpointDigest=migration["checkpointDigest"],
                                  checkpointManifestDigest=migration["checkpointManifestDigest"])
        resumed = self.action(resume_request)
        if activation is not None:
            activation.start(self.campaign, self.writer, 'writer-runtime')
        else:
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
        checkpoint_destination = None
        data_destination = None
        if self.current_v2:
            data_destination = self.directory / "restored-data"
            source_data = Path(original_settings["dataDirectory"])
            if not source_data.is_absolute():
                source_data = (self.configuration.parent / source_data).resolve(strict=True)
            copied = restore_installation.catalogs(self.client, self.node,
                source_data, data_destination,
                Path(original_settings["state"]["checkpointRoot"]))
            self.client.evidence.record("stopped-catalog-custody-copy", copied)
            destination = data_destination / "state"
            checkpoint_destination = self.directory / "restored-checkpoint"
        require(destination.is_absolute() and not destination.exists() and not destination.is_symlink(),
                "fresh-native-restore-destination")
        request = {"file": file, "destinationRoot": str(destination),
            "operationId": "java-explicit-restore", "snapshotDigest": snapshot["snapshotDigest"]}
        if self.current_v2:
            request.update(destinationCheckpointRoot=str(checkpoint_destination),
                           manifestDigest=snapshot["manifestDigest"],
                           destinationStoreIdentity=restore_installation.RESTORED_STORE_IDENTITY)
        window = self.action(dict(request, action="inspect-restore"))
        require(window["snapshot"]["snapshotDigest"] == snapshot["snapshotDigest"]
                and window["snapshot"]["manifestDigest"] == snapshot["manifestDigest"],
                "original-native-restore-window-snapshot")
        acknowledgement = recovery.original_digest(window["windowDigest"])
        restored = self.action(dict(request, action="restore", windowAcknowledgement=acknowledgement))
        require(restored["snapshotDigest"] == snapshot["snapshotDigest"]
                and restored["manifestDigest"] == snapshot["manifestDigest"], "original-native-restored-snapshot")
        if self.current_v2:
            require(restored['destinationIdentity'] == request['destinationStoreIdentity'],
                    'actual-restored-store-identity')
        require(self.recipient("restored-before-review") == recipient, "restored-history-does-not-redrive-before-review")
        settings = (restore_installation.selection(original_settings, data_destination, checkpoint_destination,
                                                   identity=restored['destinationIdentity'])
                    if self.current_v2 else restored_configuration(original_settings, destination))
        self.configuration = self.campaign.full_path.parent / "restored-node.json"
        write_json(self.configuration, settings)
        self.configuration.chmod(0o600)
        self.client.evidence.record("deliberate-restored-root-selection", {
            "configuration": str(self.configuration), "stateRoot": str(destination),
            "originalDestinationIdentity": restored["destinationIdentity"],
            "originalDataDirectory": original_settings["dataDirectory"],
            "creationNarrowed": True, "currentAuthorityInferred": False})
        if self.current_v2:
            self.refresh_authority(settings)
        reviewed = self.action({"action": "review"})
        observed = self.inspect()
        requested = recovery.original_view(observed["view"])
        epoch_advanced(list(http.view_token(current["state-view"])), requested, "recovery")
        resume_request = restored_resume_request(requested, file, snapshot, acknowledgement,
            self.migration_operation if getattr(self.node, 'current_activation', None) is not None else None)
        resumed = self.action(resume_request)
        if resume_request['action'] == 'resume-restored-migration':
            restored_migration_result(resumed, resume_request, reviewed['reviewDigest'])
        self.node.start(self.configuration, **({'current_session': 'restored-runtime'}
                        if getattr(self.node, 'current_publication_program', False) else {}))
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

    def refresh_authority(self, settings):
        require(settings["state"]["formatVersion"] == 2 and not settings["state"]["createIfMissing"],
                "current-restored-configuration-required")
        operations = settings["state"]["operations"]
        inspection = self.configuration
        activation = getattr(self.node, 'current_activation', None)
        if activation is not None:
            operations = copy.deepcopy(activation.operations)
            descriptive = copy.deepcopy(settings)
            descriptive['state']['operations'] = operations
            inspection = self.configuration.parent / 'restored-descriptive-hosts.json'
            write_json(inspection, descriptive)
            inspection.chmod(0o600)
        hosts = lifecycle.inspect(self.client, self.node.executable, inspection, operations,
                                  stage="restored-transaction-host-inspection", intent_operation="http")
        diagnostic = len(operations) == 15
        selection = {} if activation is None else {
            'current_http_endpoint': settings['providers']['http']['deferred'][0]}
        proposals = policies.documents(hosts, self.campaign.publications, diagnostic=diagnostic, **selection)
        paused = copy.deepcopy(settings)
        paused["state"]["operations"] = []
        path = self.configuration.parent / "restored-authority-node.json"
        write_json(path, paused)
        path.chmod(0o600)
        self.node.start(path, restore_authority=True)
        try:
            directory = self.directory / "restored-authority-inputs"
            directory.mkdir(mode=0o700)
            program = restore_authority.prepare(self.client, proposals, directory)
            self.client.evidence.record("restored-current-authority-program", program)
            receipts = restore_authority.apply(self.client, proposals, directory, program)
            self.campaign.proposals = proposals
            self.campaign.policy_receipts = receipts
            self.client.evidence.passed("restored-current-authority-mutations", receipts)
        finally:
            self.node.stop()
        lifecycle.admission_lease_interval(self.client)

    def execute(self):
        count = 2**32 + 3
        _, aggregate = self.campaign.query(4)
        key = 'java-before-schema-wide-value'
        changed = self.campaign.result(self.campaign.socket('command', original_key=key,
            body=command_input(2**32 - 1), condition=precondition(aggregate)))
        require(changed['disposition'] == 'committed' and http.aggregate(changed)['count'] == str(count),
                'actual-wide-java-value-before-schema')
        publication = self.campaign.publications['put-once-compatible-v2']
        effect = self.campaign.wait_effect(publication, key, changed)
        rpc_result(lifecycle.lookup(self.client, publication, key), changed, publication, key)
        self.client.evidence.passed('actual-wide-java-value-before-schema', {
            'original': changed, 'effect': effect,
            'recipientAcceptance': self.campaign.peer_record(changed['effect-ids'][0])})
        file, snapshot, current = self.schema(count)
        self.restore(count, file, snapshot, current)
        require(self.native.calls == 12, "original-bounded-recovery-sequence")
        return {"nativeActions": self.native.calls, "pendingEffectRestoreQualified": False,
                "signedJavaSchemaAndTerminalRestoreObserved": True}
