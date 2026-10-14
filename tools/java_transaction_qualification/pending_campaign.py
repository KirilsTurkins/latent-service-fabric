"""Signed pending backup, remote acceptance, restored close and no second POST."""
from __future__ import annotations

import copy
from pathlib import Path
import time

from tools.phase2_operator_process import read_json, write_json

from . import http, lifecycle, pending_controls as controls, provider, recovery, restore_installation
from .campaign import command_input, precondition, rpc_result
from .inputs import require
from .offline_campaign import OfflineCampaign, epoch_advanced

KEY = 'java-restored-pending-original'
CLOSE_OPERATION = 'java-explicit-pending-close'


class PendingCampaign(OfflineCampaign):
    def __init__(self, campaign, helper, directory):
        require(campaign.node.current_program == 'pending-close'
                and getattr(campaign.peer, 'current_http', False), 'explicit-current-pending-campaign')
        super().__init__(campaign, helper, directory)
        require(self.current_v2, 'pending-campaign-current-physical-owner')
        self.publication = campaign.publications['put-once-legacy-v1']

    def observation(self):
        value = self.campaign.recipient_observation()
        require(value['posts'] <= 1 and value['mutations'] <= 1 and value['duplicatePosts'] == 0,
                'pending-campaign-original-single-post')
        return value

    def resume(self, view, operation):
        result = self.action({'action': 'resume', 'operationId': operation,
                              'expectedView': recovery.original_view(view)})
        require(set(result) == {'action', 'receipt', 'view', 'replay'} and result['replay'] is False
                and recovery.byte_array(result['receipt'], 8192).startswith(b'NRS\x02'),
                'actual-current-pending-namespace-resume')
        before = bytes(recovery.original_view(view))
        after = bytes(recovery.original_view(result['view']))
        require(after[:43] == before[:43] and after[51:] == before[51:]
                and int.from_bytes(after[43:51], 'little') == int.from_bytes(before[43:51], 'little') + 1,
                'pending-resume-advances-only-namespace-generation')
        return result

    def pending_effect(self, original):
        require(len(original['effect-ids']) == 1, 'original-one-pending-effect')
        effect_id = original['effect-ids'][0]
        value = lifecycle.effect(self.client, self.publication, KEY, effect_id)
        require(value['effectId'] == effect_id and value['commandId'] == original['command-id']
                and value['commandAttemptId'] == original['attempt-id']
                and value['disposition'] == 'EFFECT_DISPOSITION_PENDING' and value['dispatchAttempt'] == 0
                and value['providerReceipt'] is None, 'actual-unattempted-signed-pending-effect')
        return value

    def remote_acceptance(self, original):
        until = min(self.client.deadline, time.monotonic() + 30)
        effect_id = original['effect-ids'][0]
        for _ in range(24):
            observed = self.observation()
            if observed['mutations'] == observed['posts'] == observed['lostRepliesAfterAcceptance'] == 1:
                break
            require(time.monotonic() < until, 'actual-original-remote-acceptance-watchdog')
            time.sleep(min(.1, until - time.monotonic()))
        else:
            raise ValueError('actual-original-remote-acceptance-not-observed')
        # Logical pause alone does not retire the accepted physical attempt.
        pause = controls.control_dispatcher(self.client, 'pause', 'java-pending-after-remote-pause')
        drained = controls.drained_dispatcher(self.client)
        effect = lifecycle.effect(self.client, self.publication, KEY, effect_id)
        require(effect['effectId'] == effect_id and effect['commandId'] == original['command-id']
                and effect['commandAttemptId'] == original['attempt-id']
                and effect['disposition'] in {'EFFECT_DISPOSITION_UNCERTAIN_AFTER_DISPATCH',
                                            'EFFECT_DISPOSITION_RETRY_SCHEDULED'}
                and type(effect['dispatchAttempt']) is int and effect['dispatchAttempt'] >= 1
                and effect['providerReceipt'] is None, 'actual-original-ambiguous-effect-not-acknowledged')
        record = self.campaign.peer_record(effect_id)
        observed = self.observation()
        require(observed['posts'] == observed['mutations'] == observed['retainedRecords'] == 1
                and observed['lostRepliesAfterAcceptance'] == 1, 'original-remote-acceptance-before-restore')
        self.client.evidence.passed('signed-pending-original-remote-acceptance', {
            'pause': pause, 'physicalDrain': drained, 'effect': effect, 'recipient': observed, 'record': record})
        return observed, record

    def restored(self, file, snapshot, original, recipient):
        self.quiesce(self.publication, 'java-pending-restore-quiesce')
        settings = read_json(self.configuration)
        target_identity = restore_installation.requested_identity(settings)
        source_data = Path(settings['dataDirectory'])
        if not source_data.is_absolute():
            source_data = (self.configuration.parent / source_data).resolve(strict=True)
        destination_data = self.directory / 'pending-restored-data'
        checkpoint = self.directory / 'pending-restored-checkpoint'
        copied = restore_installation.catalogs(self.client, self.node, source_data, destination_data,
                                               Path(settings['state']['checkpointRoot']))
        self.client.evidence.record('pending-stopped-catalog-custody-copy', copied)
        destination = destination_data / 'state'
        require(not destination.exists() and not checkpoint.exists(), 'fresh-pending-restore-destination')
        request = {'file': file, 'destinationRoot': str(destination), 'destinationCheckpointRoot': str(checkpoint),
                   'operationId': 'java-explicit-pending-restore', 'snapshotDigest': snapshot['snapshotDigest'],
                    'manifestDigest': snapshot['manifestDigest']}
        if target_identity is not None:
            request['destinationStoreIdentity'] = target_identity
        window = self.action(dict(request, action='inspect-restore'))
        require(window['snapshot']['snapshotDigest'] == snapshot['snapshotDigest']
                and window['snapshot']['manifestDigest'] == snapshot['manifestDigest'],
                'original-pending-restore-window-snapshot')
        acknowledgement = recovery.original_digest(window['windowDigest'])
        restored = self.action(dict(request, action='restore', windowAcknowledgement=acknowledgement))
        require(restored['snapshotDigest'] == snapshot['snapshotDigest']
                and restored['manifestDigest'] == snapshot['manifestDigest'], 'actual-pending-restore-snapshot')
        if target_identity is not None:
            require(restored['destinationIdentity'] == request['destinationStoreIdentity'],
                    'actual-pending-restored-store-identity')
        require(self.observation() == recipient, 'restored-pending-does-not-contact-recipient')
        selected = restore_installation.selection(settings, destination_data, checkpoint,
                                                   identity=(restored['destinationIdentity']
                                                             if target_identity is not None else None))
        self.configuration = self.campaign.full_path.parent / 'pending-restored-node.json'
        write_json(self.configuration, selected)
        self.configuration.chmod(0o600)
        self.client.evidence.record('pending-restored-root-selection', {
            'configuration': str(self.configuration), 'destinationIdentity': restored['destinationIdentity'],
            'stateRoot': str(destination), 'checkpointRoot': str(checkpoint), 'authorityInferred': False})
        self.refresh_authority(selected)
        observed = self.inspect()
        require(self.observation() == recipient, 'pending-reauthorization-does-not-dispatch')
        epoch_advanced(list(http.view_token(original['state-view'])), observed['view'], 'recovery')
        return observed, acknowledgement, restored

    def close_original(self, original, observed, acknowledgement):
        effect_id = original['effect-ids'][0]
        inspected = self.action({'action': 'inspect-close-effects', 'operationId': CLOSE_OPERATION,
            'effectIds': [effect_id], 'reason': 'remote-acceptance-observed-explicit-no-redrive'})
        plan, plan_ack = controls.close_plan(inspected, CLOSE_OPERATION, effect_id, observed['view'], acknowledgement)
        request = {'action': 'close-effects', 'operationId': CLOSE_OPERATION, 'plan': copy.deepcopy(plan),
                   'acknowledgement': plan_ack}
        first = self.action(request)
        receipt = controls.close_receipt(first, plan, plan_ack, replay=False)
        replay = self.action(request)
        require(controls.close_receipt(replay, plan, plan_ack, replay=True) == receipt,
                'original-pending-close-replay-is-immutable')
        reviewed = self.action({'action': 'review'})
        recovery.original_digest(reviewed['reviewDigest'])
        after = self.inspect()
        resumed = self.resume(after['view'], 'java-pending-restored-resume')
        return {'plan': inspected, 'first': first, 'replay': replay, 'review': reviewed, 'resume': resumed}

    def execute(self):
        _, aggregate = self.campaign.query(0)
        require(aggregate['key-version'] == {'none': None}, 'fresh-pending-namespace')
        controls.control_dispatcher(self.client, 'pause', 'java-pending-before-command-pause')
        controls.drained_dispatcher(self.client)
        before = self.observation()
        require(before['posts'] == before['mutations'] == before['retainedRecords'] == 0,
                'fresh-pending-recipient-no-effects')
        original = self.campaign.result(self.campaign.socket('command', original_key=KEY,
            body=command_input(1), condition=precondition(aggregate)))
        require(original['disposition'] == 'committed' and http.aggregate(original)['count'] == '1',
                'actual-signed-pending-java-command')
        self.campaign.originals[KEY] = original
        pending = self.pending_effect(original)
        rpc_result(lifecycle.lookup(self.client, self.publication, KEY), original, self.publication, KEY)
        drained = controls.drained_dispatcher(self.client)
        require(self.observation() == before, 'paused-pending-command-creates-no-provider-request')
        self.quiesce(self.publication, 'java-pending-backup-quiesce')
        observed = self.inspect()
        file, snapshot = self.snapshot('signed-pending.snapshot', 'java-pending-backup')
        require(self.observation() == before, 'pending-backup-precedes-remote-effect')
        original_resume = self.resume(observed['view'], 'java-pending-original-resume')
        provider.private_write(self.campaign.peer.directory / 'mode', b'accept-ambiguous')
        self.node.start(self.configuration, current_session='pending-original-runtime')
        require(controls.inspect_dispatcher(self.client)['paused'] is True,
                'durable-original-dispatcher-pause-preserved')
        controls.control_dispatcher(self.client, 'resume', 'java-pending-original-dispatch-resume')
        recipient, remote_record = self.remote_acceptance(original)
        restored, window, stage = self.restored(file, snapshot, original, recipient)
        closed = self.close_original(original, restored, window)
        require(self.observation() == recipient, 'explicit-pending-close-does-not-send-or-acknowledge')
        self.node.start(self.configuration, current_session='pending-restored-runtime')
        self.campaign.full_path = self.configuration
        self.campaign.query(1)
        retained = self.campaign.original(KEY)
        http.replay(original, retained)
        rpc_result(lifecycle.lookup(self.client, self.publication, KEY), retained, self.publication, KEY)
        effect = lifecycle.effect(self.client, self.publication, KEY, original['effect-ids'][0])
        require(effect['effectId'] == original['effect-ids'][0]
                and effect['disposition'] == 'EFFECT_DISPOSITION_DEAD_LETTERED'
                and effect['dispatchAttempt'] == 0 and effect['providerReceipt'] is None,
                'restored-pending-close-is-abandonment-not-delivery')
        require(self.observation() == recipient and self.campaign.peer_record(effect['effectId']) == remote_record,
                'restored-close-and-original-replay-create-no-second-post')
        require(self.native.calls == 12, 'original-bounded-pending-recovery-sequence')
        self.client.evidence.passed('actual-signed-pending-backup-restore-close', {
            'original': original, 'pending': pending, 'originalPhysicalDrain': drained,
            'snapshot': snapshot, 'originalResume': original_resume, 'remoteRecipient': recipient,
            'restored': stage, 'explicitClose': closed, 'restoredEffect': effect,
            'originalCommandRerun': False, 'recipientDeliveryQualified': False})
        return {'nativeActions': self.native.calls, 'signedPendingRestoreCloseObserved': True,
                'secondPostObserved': False, 'providerAcknowledgementInferred': False}
