// Generated from the authoritative Phase 4 transaction descriptors.
package dev.latent.sdk.transport;

import dev.latent.sdk.Transactions;
import com.google.protobuf.ByteString;
import java.util.Map;
import java.util.Optional;

final class TransactionWire {
    private TransactionWire() { }

    static latent.transaction.v1.Transaction.AbortFence toWire(Transactions.AbortFence value) {
        var result = latent.transaction.v1.Transaction.AbortFence.newBuilder();
        result.setCommandId(value.commandId());
        result.setAttemptId(value.attemptId());
        result.setTransactionId(value.transactionId());
        result.setOwnerFence(ByteString.copyFrom(value.ownerFence().asReadOnlyBuffer()));
        return result.build();
    }

    static Transactions.AbortFence fromWire(latent.transaction.v1.Transaction.AbortFence value) {
        return new Transactions.AbortFence(
                value.getCommandId(),
                value.getAttemptId(),
                value.getTransactionId(),
                value.getOwnerFence().asReadOnlyByteBuffer());
    }

    static latent.transaction.v1.Transaction.TransactionProfile toWire(Transactions.TransactionProfile value) {
        var result = latent.transaction.v1.Transaction.TransactionProfile.newBuilder();
        result.setProfile(value.profile());
        result.setHostAbiDigest(value.hostAbiDigest());
        result.setPreparationProfileDigest(value.preparationProfileDigest());
        return result.build();
    }

    static Transactions.TransactionProfile fromWire(latent.transaction.v1.Transaction.TransactionProfile value) {
        return new Transactions.TransactionProfile(
                value.getProfile(),
                value.getHostAbiDigest(),
                value.getPreparationProfileDigest());
    }

    static latent.transaction.v1.Transaction.NamespaceSelector toWire(Transactions.NamespaceSelector value) {
        var result = latent.transaction.v1.Transaction.NamespaceSelector.newBuilder();
        result.setTenant(value.tenant());
        result.setNamespace(value.namespace());
        result.setIncarnation(value.incarnation());
        return result.build();
    }

    static Transactions.NamespaceSelector fromWire(latent.transaction.v1.Transaction.NamespaceSelector value) {
        return new Transactions.NamespaceSelector(
                value.getTenant(),
                value.getNamespace(),
                value.getIncarnation());
    }

    static latent.transaction.v1.Transaction.CommandSelector toWire(Transactions.CommandSelector value) {
        var result = latent.transaction.v1.Transaction.CommandSelector.newBuilder();
        if (value.namespace().isPresent()) result.setNamespace(toWire(value.namespace().get()));
        result.setOperation(value.operation());
        if (value.entity().isPresent()) result.setEntity(value.entity().get());
        result.setClientKey(value.clientKey());
        if (value.sharedRecoveryScope().isPresent()) result.setSharedRecoveryScope(value.sharedRecoveryScope().get());
        return result.build();
    }

    static Transactions.CommandSelector fromWire(latent.transaction.v1.Transaction.CommandSelector value) {
        return new Transactions.CommandSelector(
                value.hasNamespace() ? Optional.of(fromWire(value.getNamespace())) : Optional.empty(),
                value.getOperation(),
                value.hasEntity() ? Optional.of(value.getEntity()) : Optional.empty(),
                value.getClientKey(),
                value.hasSharedRecoveryScope() ? Optional.of(value.getSharedRecoveryScope()) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.LookupCommandRequest toWire(Transactions.LookupCommandRequest value) {
        var result = latent.transaction.v1.Transaction.LookupCommandRequest.newBuilder();
        if (value.profile().isPresent()) result.setProfile(toWire(value.profile().get()));
        if (value.command().isPresent()) result.setCommand(toWire(value.command().get()));
        if (value.attemptId().isPresent()) result.setAttemptId(value.attemptId().get());
        if (value.authorizationPublication().isPresent()) result.setAuthorizationPublication(Wire.toWire(value.authorizationPublication().get()));
        return result.build();
    }

    static Transactions.LookupCommandRequest fromWire(latent.transaction.v1.Transaction.LookupCommandRequest value) {
        return new Transactions.LookupCommandRequest(
                value.hasProfile() ? Optional.of(fromWire(value.getProfile())) : Optional.empty(),
                value.hasCommand() ? Optional.of(fromWire(value.getCommand())) : Optional.empty(),
                value.hasAttemptId() ? Optional.of(value.getAttemptId()) : Optional.empty(),
                value.hasAuthorizationPublication() ? Optional.of(Wire.fromWire(value.getAuthorizationPublication())) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.CancelCommandRequest toWire(Transactions.CancelCommandRequest value) {
        var result = latent.transaction.v1.Transaction.CancelCommandRequest.newBuilder();
        if (value.command().isPresent()) result.setCommand(toWire(value.command().get()));
        result.setReason(value.reason());
        return result.build();
    }

    static Transactions.CancelCommandRequest fromWire(latent.transaction.v1.Transaction.CancelCommandRequest value) {
        return new Transactions.CancelCommandRequest(
                value.hasCommand() ? Optional.of(fromWire(value.getCommand())) : Optional.empty(),
                value.getReason());
    }

    static latent.transaction.v1.Transaction.CommandKey toWire(Transactions.CommandKey value) {
        var result = latent.transaction.v1.Transaction.CommandKey.newBuilder();
        if (value.namespace().isPresent()) result.setNamespace(toWire(value.namespace().get()));
        result.setRecoveryScope(value.recoveryScope());
        result.setOperation(value.operation());
        if (value.entity().isPresent()) result.setEntity(value.entity().get());
        result.setClientKey(value.clientKey());
        return result.build();
    }

    static Transactions.CommandKey fromWire(latent.transaction.v1.Transaction.CommandKey value) {
        return new Transactions.CommandKey(
                value.hasNamespace() ? Optional.of(fromWire(value.getNamespace())) : Optional.empty(),
                value.getRecoveryScope(),
                value.getOperation(),
                value.hasEntity() ? Optional.of(value.getEntity()) : Optional.empty(),
                value.getClientKey());
    }

    static latent.transaction.v1.Transaction.SourceIdentity toWire(Transactions.SourceIdentity value) {
        var result = latent.transaction.v1.Transaction.SourceIdentity.newBuilder();
        result.setPublicationId(value.publicationId());
        result.setRevisionId(value.revisionId());
        result.setReleaseDigest(value.releaseDigest());
        result.setRouteGeneration(value.routeGeneration());
        result.setContractDigest(value.contractDigest());
        result.setStateSchema(value.stateSchema());
        result.setInputFormat(value.inputFormat());
        result.setResultFormat(value.resultFormat());
        result.setComponentDigest(value.componentDigest());
        return result.build();
    }

    static Transactions.SourceIdentity fromWire(latent.transaction.v1.Transaction.SourceIdentity value) {
        return new Transactions.SourceIdentity(
                value.getPublicationId(),
                value.getRevisionId(),
                value.getReleaseDigest(),
                value.getRouteGeneration(),
                value.getContractDigest(),
                value.getStateSchema(),
                value.getInputFormat(),
                value.getResultFormat(),
                value.getComponentDigest());
    }

    static latent.transaction.v1.Transaction.CommitReceipt toWire(Transactions.CommitReceipt value) {
        var result = latent.transaction.v1.Transaction.CommitReceipt.newBuilder();
        result.setCommandId(value.commandId());
        result.setAttemptId(value.attemptId());
        result.setTransactionId(value.transactionId());
        result.setCommittedVersion(ByteString.copyFrom(value.committedVersion().asReadOnlyBuffer()));
        result.setCommittedAtUnixMillis(value.committedAtUnixMillis());
        for (var item : value.effectIds()) result.addEffectIds(item);
        result.setReceiptId(value.receiptId());
        if (value.source().isPresent()) result.setSource(toWire(value.source().get()));
        return result.build();
    }

    static Transactions.CommitReceipt fromWire(latent.transaction.v1.Transaction.CommitReceipt value) {
        return new Transactions.CommitReceipt(
                value.getCommandId(),
                value.getAttemptId(),
                value.getTransactionId(),
                value.getCommittedVersion().asReadOnlyByteBuffer(),
                value.getCommittedAtUnixMillis(),
                value.getEffectIdsList().stream().map(item -> item).toList(),
                value.getReceiptId(),
                value.hasSource() ? Optional.of(fromWire(value.getSource())) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.LinkedRetention toWire(Transactions.LinkedRetention value) {
        var result = latent.transaction.v1.Transaction.LinkedRetention.newBuilder();
        result.setRecordFormat(value.recordFormat());
        result.setRecordVersion(value.recordVersion());
        if (value.payloadExpiresAtUnixMillis().isPresent()) result.setPayloadExpiresAtUnixMillis(value.payloadExpiresAtUnixMillis().get());
        if (value.identityExpiresAtUnixMillis().isPresent()) result.setIdentityExpiresAtUnixMillis(value.identityExpiresAtUnixMillis().get());
        if (value.remainingRecoveryMillis().isPresent()) result.setRemainingRecoveryMillis(value.remainingRecoveryMillis().get());
        for (var item : value.requiredRecordIds()) result.addRequiredRecordIds(item);
        result.setPayloadAvailable(value.payloadAvailable());
        return result.build();
    }

    static Transactions.LinkedRetention fromWire(latent.transaction.v1.Transaction.LinkedRetention value) {
        return new Transactions.LinkedRetention(
                value.getRecordFormat(),
                value.getRecordVersion(),
                value.hasPayloadExpiresAtUnixMillis() ? Optional.of(value.getPayloadExpiresAtUnixMillis()) : Optional.empty(),
                value.hasIdentityExpiresAtUnixMillis() ? Optional.of(value.getIdentityExpiresAtUnixMillis()) : Optional.empty(),
                value.hasRemainingRecoveryMillis() ? Optional.of(value.getRemainingRecoveryMillis()) : Optional.empty(),
                value.getRequiredRecordIdsList().stream().map(item -> item).toList(),
                value.getPayloadAvailable());
    }

    static latent.transaction.v1.Transaction.CommandInspection toWire(Transactions.CommandInspection value) {
        var result = latent.transaction.v1.Transaction.CommandInspection.newBuilder();
        if ((value.success().isPresent() ? 1 : 0) + (value.businessRejection().isPresent() ? 1 : 0) + (value.technicalFailure().isPresent() ? 1 : 0) > 1) throw new IllegalArgumentException("contradictory oneof");
        if (value.key().isPresent()) result.setKey(toWire(value.key().get()));
        result.setCommandId(value.commandId());
        result.setAttemptId(value.attemptId());
        result.setFingerprintSha256(ByteString.copyFrom(value.fingerprintSha256().asReadOnlyBuffer()));
        result.setOutcomeValue(value.outcome().value());
        result.setMetadataDurable(value.metadataDurable());
        result.setApplicationStateCommitted(value.applicationStateCommitted());
        if (value.source().isPresent()) result.setSource(toWire(value.source().get()));
        if (value.success().isPresent()) result.setSuccess(Wire.toWire(value.success().get()));
        if (value.businessRejection().isPresent()) result.setBusinessRejection(Wire.toWire(value.businessRejection().get()));
        if (value.technicalFailure().isPresent()) result.setTechnicalFailure(Wire.toInvocationPlatformError(value.technicalFailure().get()));
        if (value.commit().isPresent()) result.setCommit(toWire(value.commit().get()));
        if (value.provenAbort().isPresent()) result.setProvenAbort(toWire(value.provenAbort().get()));
        if (value.retention().isPresent()) result.setRetention(toWire(value.retention().get()));
        if (value.cleanupFailure().isPresent()) result.setCleanupFailure(Wire.toInvocationPlatformError(value.cleanupFailure().get()));
        return result.build();
    }

    static Transactions.CommandInspection fromWire(latent.transaction.v1.Transaction.CommandInspection value) {
        return new Transactions.CommandInspection(
                value.hasKey() ? Optional.of(fromWire(value.getKey())) : Optional.empty(),
                value.getCommandId(),
                value.getAttemptId(),
                value.getFingerprintSha256().asReadOnlyByteBuffer(),
                new Transactions.CommandOutcome(value.getOutcomeValue()),
                value.getMetadataDurable(),
                value.getApplicationStateCommitted(),
                value.hasSource() ? Optional.of(fromWire(value.getSource())) : Optional.empty(),
                value.hasSuccess() ? Optional.of(Wire.fromWire(value.getSuccess())) : Optional.empty(),
                value.hasBusinessRejection() ? Optional.of(Wire.fromWire(value.getBusinessRejection())) : Optional.empty(),
                value.hasTechnicalFailure() ? Optional.of(Wire.fromWire(value.getTechnicalFailure())) : Optional.empty(),
                value.hasCommit() ? Optional.of(fromWire(value.getCommit())) : Optional.empty(),
                value.hasProvenAbort() ? Optional.of(fromWire(value.getProvenAbort())) : Optional.empty(),
                value.hasRetention() ? Optional.of(fromWire(value.getRetention())) : Optional.empty(),
                value.hasCleanupFailure() ? Optional.of(Wire.fromWire(value.getCleanupFailure())) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.CancelCommandResponse toWire(Transactions.CancelCommandResponse value) {
        var result = latent.transaction.v1.Transaction.CancelCommandResponse.newBuilder();
        result.setDispositionValue(value.disposition().value());
        if (value.command().isPresent()) result.setCommand(toWire(value.command().get()));
        return result.build();
    }

    static Transactions.CancelCommandResponse fromWire(latent.transaction.v1.Transaction.CancelCommandResponse value) {
        return new Transactions.CancelCommandResponse(
                new Transactions.CommandCancelDisposition(value.getDispositionValue()),
                value.hasCommand() ? Optional.of(fromWire(value.getCommand())) : Optional.empty());
    }

    static latent.control.v1.Dispatcher.DispatcherGeneration toWire(Transactions.DispatcherGeneration value) {
        var result = latent.control.v1.Dispatcher.DispatcherGeneration.newBuilder();
        result.setOwnerEpoch(value.ownerEpoch());
        result.setRevision(value.revision());
        return result.build();
    }

    static Transactions.DispatcherGeneration fromWire(latent.control.v1.Dispatcher.DispatcherGeneration value) {
        return new Transactions.DispatcherGeneration(
                value.getOwnerEpoch(),
                value.getRevision());
    }

    static latent.control.v1.Dispatcher.ControlDispatcherRequest toWire(Transactions.ControlDispatcherRequest value) {
        var result = latent.control.v1.Dispatcher.ControlDispatcherRequest.newBuilder();
        if (value.profile().isPresent()) result.setProfile(toWire(value.profile().get()));
        result.setScopeValue(value.scope().value());
        result.setOperationId(value.operationId());
        result.setActionValue(value.action().value());
        if (value.expectedGeneration().isPresent()) result.setExpectedGeneration(toWire(value.expectedGeneration().get()));
        return result.build();
    }

    static Transactions.ControlDispatcherRequest fromWire(latent.control.v1.Dispatcher.ControlDispatcherRequest value) {
        return new Transactions.ControlDispatcherRequest(
                value.hasProfile() ? Optional.of(fromWire(value.getProfile())) : Optional.empty(),
                new Transactions.DispatcherScope(value.getScopeValue()),
                value.getOperationId(),
                new Transactions.DispatcherAction(value.getActionValue()),
                value.hasExpectedGeneration() ? Optional.of(fromWire(value.getExpectedGeneration())) : Optional.empty());
    }

    static latent.control.v1.Dispatcher.DispatcherOperationReceipt toWire(Transactions.DispatcherOperationReceipt value) {
        var result = latent.control.v1.Dispatcher.DispatcherOperationReceipt.newBuilder();
        result.setOperationId(value.operationId());
        result.setReceiptId(value.receiptId());
        result.setActionValue(value.action().value());
        result.setAuthenticatedOperator(value.authenticatedOperator());
        result.setActorTenant(value.actorTenant());
        if (value.beforeGeneration().isPresent()) result.setBeforeGeneration(toWire(value.beforeGeneration().get()));
        if (value.afterGeneration().isPresent()) result.setAfterGeneration(toWire(value.afterGeneration().get()));
        result.setObservedAtUnixMillis(value.observedAtUnixMillis());
        result.setClockContinuityProven(value.clockContinuityProven());
        result.setRestoreReviewRequired(value.restoreReviewRequired());
        result.setDispositionValue(value.disposition().value());
        return result.build();
    }

    static Transactions.DispatcherOperationReceipt fromWire(latent.control.v1.Dispatcher.DispatcherOperationReceipt value) {
        return new Transactions.DispatcherOperationReceipt(
                value.getOperationId(),
                value.getReceiptId(),
                new Transactions.DispatcherAction(value.getActionValue()),
                value.getAuthenticatedOperator(),
                value.getActorTenant(),
                value.hasBeforeGeneration() ? Optional.of(fromWire(value.getBeforeGeneration())) : Optional.empty(),
                value.hasAfterGeneration() ? Optional.of(fromWire(value.getAfterGeneration())) : Optional.empty(),
                value.getObservedAtUnixMillis(),
                value.getClockContinuityProven(),
                value.getRestoreReviewRequired(),
                new Transactions.StateOperationDisposition(value.getDispositionValue()));
    }

    static latent.control.v1.Dispatcher.ControlDispatcherResponse toWire(Transactions.ControlDispatcherResponse value) {
        var result = latent.control.v1.Dispatcher.ControlDispatcherResponse.newBuilder();
        if (value.receipt().isPresent()) result.setReceipt(toWire(value.receipt().get()));
        result.setReplayed(value.replayed());
        result.setPublished(value.published());
        result.setPaused(value.paused());
        if (value.auditAck().isPresent()) result.setAuditAck(Wire.toWire(value.auditAck().get()));
        return result.build();
    }

    static Transactions.ControlDispatcherResponse fromWire(latent.control.v1.Dispatcher.ControlDispatcherResponse value) {
        return new Transactions.ControlDispatcherResponse(
                value.hasReceipt() ? Optional.of(fromWire(value.getReceipt())) : Optional.empty(),
                value.getReplayed(),
                value.getPublished(),
                value.getPaused(),
                value.hasAuditAck() ? Optional.of(Wire.fromWire(value.getAuditAck())) : Optional.empty());
    }

    static latent.control.v1.Dispatcher.DispatcherSnapshot toWire(Transactions.DispatcherSnapshot value) {
        var result = latent.control.v1.Dispatcher.DispatcherSnapshot.newBuilder();
        if (value.generation().isPresent()) result.setGeneration(toWire(value.generation().get()));
        result.setPaused(value.paused());
        result.setPendingControl(value.pendingControl());
        result.setRestoreReviewRequired(value.restoreReviewRequired());
        result.setAdmissionClosed(value.admissionClosed());
        result.setQuarantined(value.quarantined());
        result.setFailureValue(value.failure().value());
        result.setQueued(value.queued());
        result.setActiveJobs(value.activeJobs());
        result.setRetainedAttemptBytes(value.retainedAttemptBytes());
        result.setLiveWorkers(value.liveWorkers());
        result.setAcceptedEffects(value.acceptedEffects());
        result.setPhysicalOwners(value.physicalOwners());
        result.setQuarantinedPhysicalOwners(value.quarantinedPhysicalOwners());
        result.setCommandOwners(value.commandOwners());
        result.setClaims(value.claims());
        result.setPendingEffects(value.pendingEffects());
        result.setUncertainEffects(value.uncertainEffects());
        result.setBlockedEffects(value.blockedEffects());
        result.setDeadLetterEffects(value.deadLetterEffects());
        result.setCountsObservedAtUnixMillis(value.countsObservedAtUnixMillis());
        result.setClockContinuityProven(value.clockContinuityProven());
        return result.build();
    }

    static Transactions.DispatcherSnapshot fromWire(latent.control.v1.Dispatcher.DispatcherSnapshot value) {
        return new Transactions.DispatcherSnapshot(
                value.hasGeneration() ? Optional.of(fromWire(value.getGeneration())) : Optional.empty(),
                value.getPaused(),
                value.getPendingControl(),
                value.getRestoreReviewRequired(),
                value.getAdmissionClosed(),
                value.getQuarantined(),
                new Transactions.DispatcherFailure(value.getFailureValue()),
                value.getQueued(),
                value.getActiveJobs(),
                value.getRetainedAttemptBytes(),
                value.getLiveWorkers(),
                value.getAcceptedEffects(),
                value.getPhysicalOwners(),
                value.getQuarantinedPhysicalOwners(),
                value.getCommandOwners(),
                value.getClaims(),
                value.getPendingEffects(),
                value.getUncertainEffects(),
                value.getBlockedEffects(),
                value.getDeadLetterEffects(),
                value.getCountsObservedAtUnixMillis(),
                value.getClockContinuityProven());
    }

    static latent.transaction.v1.Transaction.EffectReceipt toWire(Transactions.EffectReceipt value) {
        var result = latent.transaction.v1.Transaction.EffectReceipt.newBuilder();
        result.setEffectId(value.effectId());
        result.setCommandId(value.commandId());
        result.setCommandAttemptId(value.commandAttemptId());
        result.setDispatchAttempt(value.dispatchAttempt());
        result.setDispositionValue(value.disposition().value());
        if (value.providerReceipt().isPresent()) result.setProviderReceipt(value.providerReceipt().get());
        if (value.failureCode().isPresent()) result.setFailureCode(value.failureCode().get());
        result.setOccurredAtUnixMillis(value.occurredAtUnixMillis());
        if (value.retention().isPresent()) result.setRetention(toWire(value.retention().get()));
        if (value.managementOperationReceiptId().isPresent()) result.setManagementOperationReceiptId(value.managementOperationReceiptId().get());
        result.setProviderProfile(value.providerProfile());
        return result.build();
    }

    static Transactions.EffectReceipt fromWire(latent.transaction.v1.Transaction.EffectReceipt value) {
        return new Transactions.EffectReceipt(
                value.getEffectId(),
                value.getCommandId(),
                value.getCommandAttemptId(),
                value.getDispatchAttempt(),
                new Transactions.EffectDisposition(value.getDispositionValue()),
                value.hasProviderReceipt() ? Optional.of(value.getProviderReceipt()) : Optional.empty(),
                value.hasFailureCode() ? Optional.of(value.getFailureCode()) : Optional.empty(),
                value.getOccurredAtUnixMillis(),
                value.hasRetention() ? Optional.of(fromWire(value.getRetention())) : Optional.empty(),
                value.hasManagementOperationReceiptId() ? Optional.of(value.getManagementOperationReceiptId()) : Optional.empty(),
                value.getProviderProfile());
    }

    static latent.control.v1.State.EntityInspection toWire(Transactions.EntityInspection value) {
        var result = latent.control.v1.State.EntityInspection.newBuilder();
        result.setEntity(value.entity());
        result.setVersion(ByteString.copyFrom(value.version().asReadOnlyBuffer()));
        return result.build();
    }

    static Transactions.EntityInspection fromWire(latent.control.v1.State.EntityInspection value) {
        return new Transactions.EntityInspection(
                value.getEntity(),
                value.getVersion().asReadOnlyByteBuffer());
    }

    static latent.transaction.v1.Transaction.ExpectedVersion toWire(Transactions.ExpectedVersion value) {
        var result = latent.transaction.v1.Transaction.ExpectedVersion.newBuilder();
        if ((value.absent().isPresent() ? 1 : 0) + (value.version().isPresent() ? 1 : 0) > 1) throw new IllegalArgumentException("contradictory oneof");
        result.setKey(ByteString.copyFrom(value.key().asReadOnlyBuffer()));
        if (value.absent().isPresent()) result.setAbsent(value.absent().get());
        if (value.version().isPresent()) result.setVersion(ByteString.copyFrom(value.version().get().asReadOnlyBuffer()));
        return result.build();
    }

    static Transactions.ExpectedVersion fromWire(latent.transaction.v1.Transaction.ExpectedVersion value) {
        return new Transactions.ExpectedVersion(
                value.getKey().asReadOnlyByteBuffer(),
                value.hasAbsent() ? Optional.of(value.getAbsent()) : Optional.empty(),
                value.hasVersion() ? Optional.of(value.getVersion().asReadOnlyByteBuffer()) : Optional.empty());
    }

    static latent.control.v1.Dispatcher.GetDispatcherOperationRequest toWire(Transactions.GetDispatcherOperationRequest value) {
        var result = latent.control.v1.Dispatcher.GetDispatcherOperationRequest.newBuilder();
        if (value.original().isPresent()) result.setOriginal(toWire(value.original().get()));
        return result.build();
    }

    static Transactions.GetDispatcherOperationRequest fromWire(latent.control.v1.Dispatcher.GetDispatcherOperationRequest value) {
        return new Transactions.GetDispatcherOperationRequest(
                value.hasOriginal() ? Optional.of(fromWire(value.getOriginal())) : Optional.empty());
    }

    static latent.control.v1.Dispatcher.GetDispatcherOperationResponse toWire(Transactions.GetDispatcherOperationResponse value) {
        var result = latent.control.v1.Dispatcher.GetDispatcherOperationResponse.newBuilder();
        if (value.receipt().isPresent()) result.setReceipt(toWire(value.receipt().get()));
        if (value.auditAck().isPresent()) result.setAuditAck(Wire.toWire(value.auditAck().get()));
        return result.build();
    }

    static Transactions.GetDispatcherOperationResponse fromWire(latent.control.v1.Dispatcher.GetDispatcherOperationResponse value) {
        return new Transactions.GetDispatcherOperationResponse(
                value.hasReceipt() ? Optional.of(fromWire(value.getReceipt())) : Optional.empty(),
                value.hasAuditAck() ? Optional.of(Wire.fromWire(value.getAuditAck())) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.GetEffectRequest toWire(Transactions.GetEffectRequest value) {
        var result = latent.transaction.v1.Transaction.GetEffectRequest.newBuilder();
        if (value.profile().isPresent()) result.setProfile(toWire(value.profile().get()));
        if (value.command().isPresent()) result.setCommand(toWire(value.command().get()));
        result.setEffectId(value.effectId());
        if (value.authorizationPublication().isPresent()) result.setAuthorizationPublication(Wire.toWire(value.authorizationPublication().get()));
        return result.build();
    }

    static Transactions.GetEffectRequest fromWire(latent.transaction.v1.Transaction.GetEffectRequest value) {
        return new Transactions.GetEffectRequest(
                value.hasProfile() ? Optional.of(fromWire(value.getProfile())) : Optional.empty(),
                value.hasCommand() ? Optional.of(fromWire(value.getCommand())) : Optional.empty(),
                value.getEffectId(),
                value.hasAuthorizationPublication() ? Optional.of(Wire.fromWire(value.getAuthorizationPublication())) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.GetEffectResponse toWire(Transactions.GetEffectResponse value) {
        var result = latent.transaction.v1.Transaction.GetEffectResponse.newBuilder();
        if (value.effect().isPresent()) result.setEffect(toWire(value.effect().get()));
        return result.build();
    }

    static Transactions.GetEffectResponse fromWire(latent.transaction.v1.Transaction.GetEffectResponse value) {
        return new Transactions.GetEffectResponse(
                value.hasEffect() ? Optional.of(fromWire(value.getEffect())) : Optional.empty());
    }

    static latent.control.v1.State.InspectNamespaceRequest toWire(Transactions.InspectNamespaceRequest value) {
        var result = latent.control.v1.State.InspectNamespaceRequest.newBuilder();
        if (value.profile().isPresent()) result.setProfile(toWire(value.profile().get()));
        if (value.namespace().isPresent()) result.setNamespace(toWire(value.namespace().get()));
        if (value.authorizationPublication().isPresent()) result.setAuthorizationPublication(Wire.toWire(value.authorizationPublication().get()));
        return result.build();
    }

    static Transactions.InspectNamespaceRequest fromWire(latent.control.v1.State.InspectNamespaceRequest value) {
        return new Transactions.InspectNamespaceRequest(
                value.hasProfile() ? Optional.of(fromWire(value.getProfile())) : Optional.empty(),
                value.hasNamespace() ? Optional.of(fromWire(value.getNamespace())) : Optional.empty(),
                value.hasAuthorizationPublication() ? Optional.of(Wire.fromWire(value.getAuthorizationPublication())) : Optional.empty());
    }

    static latent.control.v1.State.GetStateOperationReceiptRequest toWire(Transactions.GetStateOperationReceiptRequest value) {
        var result = latent.control.v1.State.GetStateOperationReceiptRequest.newBuilder();
        if (value.namespace().isPresent()) result.setNamespace(toWire(value.namespace().get()));
        result.setOperationId(value.operationId());
        return result.build();
    }

    static Transactions.GetStateOperationReceiptRequest fromWire(latent.control.v1.State.GetStateOperationReceiptRequest value) {
        return new Transactions.GetStateOperationReceiptRequest(
                value.hasNamespace() ? Optional.of(fromWire(value.getNamespace())) : Optional.empty(),
                value.getOperationId());
    }

    static latent.control.v1.State.StateOperationReceipt toWire(Transactions.StateOperationReceipt value) {
        var result = latent.control.v1.State.StateOperationReceipt.newBuilder();
        result.setOperationId(value.operationId());
        result.setReceiptId(value.receiptId());
        result.setMutationValue(value.mutation().value());
        if (value.namespace().isPresent()) result.setNamespace(toWire(value.namespace().get()));
        result.setAuthenticatedOperator(value.authenticatedOperator());
        result.setBeforeVersion(ByteString.copyFrom(value.beforeVersion().asReadOnlyBuffer()));
        result.setAfterVersion(ByteString.copyFrom(value.afterVersion().asReadOnlyBuffer()));
        result.setCompletedAtUnixMillis(value.completedAtUnixMillis());
        if (value.recordId().isPresent()) result.setRecordId(value.recordId().get());
        result.setPolicyDigest(value.policyDigest());
        result.setDispositionValue(value.disposition().value());
        return result.build();
    }

    static Transactions.StateOperationReceipt fromWire(latent.control.v1.State.StateOperationReceipt value) {
        return new Transactions.StateOperationReceipt(
                value.getOperationId(),
                value.getReceiptId(),
                new Transactions.StateMutationKind(value.getMutationValue()),
                value.hasNamespace() ? Optional.of(fromWire(value.getNamespace())) : Optional.empty(),
                value.getAuthenticatedOperator(),
                value.getBeforeVersion().asReadOnlyByteBuffer(),
                value.getAfterVersion().asReadOnlyByteBuffer(),
                value.getCompletedAtUnixMillis(),
                value.hasRecordId() ? Optional.of(value.getRecordId()) : Optional.empty(),
                value.getPolicyDigest(),
                new Transactions.StateOperationDisposition(value.getDispositionValue()));
    }

    static latent.control.v1.State.NamespaceOperationReceipt toWire(Transactions.NamespaceOperationReceipt value) {
        var result = latent.control.v1.State.NamespaceOperationReceipt.newBuilder();
        result.setOperationId(value.operationId());
        result.setReceiptId(value.receiptId());
        result.setMutationValue(value.mutation().value());
        if (value.namespace().isPresent()) result.setNamespace(toWire(value.namespace().get()));
        result.setAuthenticatedOperator(value.authenticatedOperator());
        if (value.beforeGeneration().isPresent()) result.setBeforeGeneration(value.beforeGeneration().get());
        result.setAfterGeneration(value.afterGeneration());
        result.setStatusValue(value.status().value());
        result.setStateSchema(value.stateSchema());
        result.setDispositionValue(value.disposition().value());
        return result.build();
    }

    static Transactions.NamespaceOperationReceipt fromWire(latent.control.v1.State.NamespaceOperationReceipt value) {
        return new Transactions.NamespaceOperationReceipt(
                value.getOperationId(),
                value.getReceiptId(),
                new Transactions.NamespaceMutationKind(value.getMutationValue()),
                value.hasNamespace() ? Optional.of(fromWire(value.getNamespace())) : Optional.empty(),
                value.getAuthenticatedOperator(),
                value.hasBeforeGeneration() ? Optional.of(value.getBeforeGeneration()) : Optional.empty(),
                value.getAfterGeneration(),
                new Transactions.NamespaceStatus(value.getStatusValue()),
                value.getStateSchema(),
                new Transactions.StateOperationDisposition(value.getDispositionValue()));
    }

    static latent.control.v1.State.GetStateOperationReceiptResponse toWire(Transactions.GetStateOperationReceiptResponse value) {
        var result = latent.control.v1.State.GetStateOperationReceiptResponse.newBuilder();
        if (value.receipt().isPresent()) result.setReceipt(toWire(value.receipt().get()));
        if (value.namespaceReceipt().isPresent()) result.setNamespaceReceipt(toWire(value.namespaceReceipt().get()));
        return result.build();
    }

    static Transactions.GetStateOperationReceiptResponse fromWire(latent.control.v1.State.GetStateOperationReceiptResponse value) {
        return new Transactions.GetStateOperationReceiptResponse(
                value.hasReceipt() ? Optional.of(fromWire(value.getReceipt())) : Optional.empty(),
                value.hasNamespaceReceipt() ? Optional.of(fromWire(value.getNamespaceReceipt())) : Optional.empty());
    }

    static latent.control.v1.Dispatcher.InspectDispatcherRequest toWire(Transactions.InspectDispatcherRequest value) {
        var result = latent.control.v1.Dispatcher.InspectDispatcherRequest.newBuilder();
        if (value.profile().isPresent()) result.setProfile(toWire(value.profile().get()));
        result.setScopeValue(value.scope().value());
        return result.build();
    }

    static Transactions.InspectDispatcherRequest fromWire(latent.control.v1.Dispatcher.InspectDispatcherRequest value) {
        return new Transactions.InspectDispatcherRequest(
                value.hasProfile() ? Optional.of(fromWire(value.getProfile())) : Optional.empty(),
                new Transactions.DispatcherScope(value.getScopeValue()));
    }

    static latent.control.v1.Dispatcher.InspectDispatcherResponse toWire(Transactions.InspectDispatcherResponse value) {
        var result = latent.control.v1.Dispatcher.InspectDispatcherResponse.newBuilder();
        if (value.dispatcher().isPresent()) result.setDispatcher(toWire(value.dispatcher().get()));
        if (value.auditAck().isPresent()) result.setAuditAck(Wire.toWire(value.auditAck().get()));
        return result.build();
    }

    static Transactions.InspectDispatcherResponse fromWire(latent.control.v1.Dispatcher.InspectDispatcherResponse value) {
        return new Transactions.InspectDispatcherResponse(
                value.hasDispatcher() ? Optional.of(fromWire(value.getDispatcher())) : Optional.empty(),
                value.hasAuditAck() ? Optional.of(Wire.fromWire(value.getAuditAck())) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.ViewIdentity toWire(Transactions.ViewIdentity value) {
        var result = latent.transaction.v1.Transaction.ViewIdentity.newBuilder();
        if (value.namespace().isPresent()) result.setNamespace(toWire(value.namespace().get()));
        result.setVersion(ByteString.copyFrom(value.version().asReadOnlyBuffer()));
        result.setStateSchema(value.stateSchema());
        return result.build();
    }

    static Transactions.ViewIdentity fromWire(latent.transaction.v1.Transaction.ViewIdentity value) {
        return new Transactions.ViewIdentity(
                value.hasNamespace() ? Optional.of(fromWire(value.getNamespace())) : Optional.empty(),
                value.getVersion().asReadOnlyByteBuffer(),
                value.getStateSchema());
    }

    static latent.control.v1.State.NamespaceQuota toWire(Transactions.NamespaceQuota value) {
        var result = latent.control.v1.State.NamespaceQuota.newBuilder();
        result.setStateKeys(value.stateKeys());
        result.setStateBytes(value.stateBytes());
        result.setResultRows(value.resultRows());
        result.setResultBytes(value.resultBytes());
        result.setEffectRows(value.effectRows());
        result.setEffectBytes(value.effectBytes());
        result.setPayloadBytes(value.payloadBytes());
        result.setRecoveryBytes(value.recoveryBytes());
        return result.build();
    }

    static Transactions.NamespaceQuota fromWire(latent.control.v1.State.NamespaceQuota value) {
        return new Transactions.NamespaceQuota(
                value.getStateKeys(),
                value.getStateBytes(),
                value.getResultRows(),
                value.getResultBytes(),
                value.getEffectRows(),
                value.getEffectBytes(),
                value.getPayloadBytes(),
                value.getRecoveryBytes());
    }

    static latent.control.v1.State.NamespaceInspection toWire(Transactions.NamespaceInspection value) {
        var result = latent.control.v1.State.NamespaceInspection.newBuilder();
        if (value.view().isPresent()) result.setView(toWire(value.view().get()));
        result.setEncodedStateBytes(value.encodedStateBytes());
        result.setCommandCount(value.commandCount());
        result.setPendingEffectCount(value.pendingEffectCount());
        for (var item : value.retainedFormats()) result.addRetainedFormats(toWire(item));
        result.setEngineProfile(value.engineProfile());
        result.setEngineProfileDigest(value.engineProfileDigest());
        result.setStatusValue(value.status().value());
        if (value.quota().isPresent()) result.setQuota(toWire(value.quota().get()));
        result.setGeneration(value.generation());
        return result.build();
    }

    static Transactions.NamespaceInspection fromWire(latent.control.v1.State.NamespaceInspection value) {
        return new Transactions.NamespaceInspection(
                value.hasView() ? Optional.of(fromWire(value.getView())) : Optional.empty(),
                value.getEncodedStateBytes(),
                value.getCommandCount(),
                value.getPendingEffectCount(),
                value.getRetainedFormatsList().stream().map(item -> fromWire(item)).toList(),
                value.getEngineProfile(),
                value.getEngineProfileDigest(),
                new Transactions.NamespaceStatus(value.getStatusValue()),
                value.hasQuota() ? Optional.of(fromWire(value.getQuota())) : Optional.empty(),
                value.getGeneration());
    }

    static latent.control.v1.State.InspectNamespaceResponse toWire(Transactions.InspectNamespaceResponse value) {
        var result = latent.control.v1.State.InspectNamespaceResponse.newBuilder();
        if (value.namespace().isPresent()) result.setNamespace(toWire(value.namespace().get()));
        return result.build();
    }

    static Transactions.InspectNamespaceResponse fromWire(latent.control.v1.State.InspectNamespaceResponse value) {
        return new Transactions.InspectNamespaceResponse(
                value.hasNamespace() ? Optional.of(fromWire(value.getNamespace())) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.RetryAttempt toWire(Transactions.RetryAttempt value) {
        var result = latent.transaction.v1.Transaction.RetryAttempt.newBuilder();
        result.setRequestId(value.requestId());
        if (value.expectedAbort().isPresent()) result.setExpectedAbort(toWire(value.expectedAbort().get()));
        return result.build();
    }

    static Transactions.RetryAttempt fromWire(latent.transaction.v1.Transaction.RetryAttempt value) {
        return new Transactions.RetryAttempt(
                value.getRequestId(),
                value.hasExpectedAbort() ? Optional.of(fromWire(value.getExpectedAbort())) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.InvokeCommandRequest toWire(Transactions.InvokeCommandRequest value) {
        var result = latent.transaction.v1.Transaction.InvokeCommandRequest.newBuilder();
        if (value.profile().isPresent()) result.setProfile(toWire(value.profile().get()));
        if (value.invocation().isPresent()) result.setInvocation(Wire.toWire(value.invocation().get()));
        if (value.command().isPresent()) result.setCommand(toWire(value.command().get()));
        result.setInputFormat(value.inputFormat());
        for (var item : value.expectedVersions()) result.addExpectedVersions(toWire(item));
        if (value.retryAttempt().isPresent()) result.setRetryAttempt(toWire(value.retryAttempt().get()));
        return result.build();
    }

    static Transactions.InvokeCommandRequest fromWire(latent.transaction.v1.Transaction.InvokeCommandRequest value) {
        return new Transactions.InvokeCommandRequest(
                value.hasProfile() ? Optional.of(fromWire(value.getProfile())) : Optional.empty(),
                value.hasInvocation() ? Optional.of(Wire.fromWire(value.getInvocation())) : Optional.empty(),
                value.hasCommand() ? Optional.of(fromWire(value.getCommand())) : Optional.empty(),
                value.getInputFormat(),
                value.getExpectedVersionsList().stream().map(item -> fromWire(item)).toList(),
                value.hasRetryAttempt() ? Optional.of(fromWire(value.getRetryAttempt())) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.InvokeCommandResponse toWire(Transactions.InvokeCommandResponse value) {
        var result = latent.transaction.v1.Transaction.InvokeCommandResponse.newBuilder();
        if (value.invocation().isPresent()) result.setInvocation(Wire.toWire(value.invocation().get()));
        if (value.command().isPresent()) result.setCommand(toWire(value.command().get()));
        result.setReplayed(value.replayed());
        return result.build();
    }

    static Transactions.InvokeCommandResponse fromWire(latent.transaction.v1.Transaction.InvokeCommandResponse value) {
        return new Transactions.InvokeCommandResponse(
                value.hasInvocation() ? Optional.of(Wire.fromWire(value.getInvocation())) : Optional.empty(),
                value.hasCommand() ? Optional.of(fromWire(value.getCommand())) : Optional.empty(),
                value.getReplayed());
    }

    static latent.transaction.v1.Transaction.PageRequest toWire(Transactions.PageRequest value) {
        var result = latent.transaction.v1.Transaction.PageRequest.newBuilder();
        result.setLimit(value.limit());
        if (value.cursor().isPresent()) result.setCursor(ByteString.copyFrom(value.cursor().get().asReadOnlyBuffer()));
        return result.build();
    }

    static Transactions.PageRequest fromWire(latent.transaction.v1.Transaction.PageRequest value) {
        return new Transactions.PageRequest(
                value.getLimit(),
                value.hasCursor() ? Optional.of(value.getCursor().asReadOnlyByteBuffer()) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.ListEffectHistoryRequest toWire(Transactions.ListEffectHistoryRequest value) {
        var result = latent.transaction.v1.Transaction.ListEffectHistoryRequest.newBuilder();
        if (value.effect().isPresent()) result.setEffect(toWire(value.effect().get()));
        if (value.page().isPresent()) result.setPage(toWire(value.page().get()));
        return result.build();
    }

    static Transactions.ListEffectHistoryRequest fromWire(latent.transaction.v1.Transaction.ListEffectHistoryRequest value) {
        return new Transactions.ListEffectHistoryRequest(
                value.hasEffect() ? Optional.of(fromWire(value.getEffect())) : Optional.empty(),
                value.hasPage() ? Optional.of(fromWire(value.getPage())) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.PageResponse toWire(Transactions.PageResponse value) {
        var result = latent.transaction.v1.Transaction.PageResponse.newBuilder();
        if (value.nextCursor().isPresent()) result.setNextCursor(ByteString.copyFrom(value.nextCursor().get().asReadOnlyBuffer()));
        result.setReturnedCount(value.returnedCount());
        result.setEncodedBytes(value.encodedBytes());
        return result.build();
    }

    static Transactions.PageResponse fromWire(latent.transaction.v1.Transaction.PageResponse value) {
        return new Transactions.PageResponse(
                value.hasNextCursor() ? Optional.of(value.getNextCursor().asReadOnlyByteBuffer()) : Optional.empty(),
                value.getReturnedCount(),
                value.getEncodedBytes());
    }

    static latent.transaction.v1.Transaction.ListEffectHistoryResponse toWire(Transactions.ListEffectHistoryResponse value) {
        var result = latent.transaction.v1.Transaction.ListEffectHistoryResponse.newBuilder();
        for (var item : value.receipts()) result.addReceipts(toWire(item));
        if (value.page().isPresent()) result.setPage(toWire(value.page().get()));
        return result.build();
    }

    static Transactions.ListEffectHistoryResponse fromWire(latent.transaction.v1.Transaction.ListEffectHistoryResponse value) {
        return new Transactions.ListEffectHistoryResponse(
                value.getReceiptsList().stream().map(item -> fromWire(item)).toList(),
                value.hasPage() ? Optional.of(fromWire(value.getPage())) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.LookupCommandResponse toWire(Transactions.LookupCommandResponse value) {
        var result = latent.transaction.v1.Transaction.LookupCommandResponse.newBuilder();
        if (value.command().isPresent()) result.setCommand(toWire(value.command().get()));
        return result.build();
    }

    static Transactions.LookupCommandResponse fromWire(latent.transaction.v1.Transaction.LookupCommandResponse value) {
        return new Transactions.LookupCommandResponse(
                value.hasCommand() ? Optional.of(fromWire(value.getCommand())) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.LookupCommitRequest toWire(Transactions.LookupCommitRequest value) {
        var result = latent.transaction.v1.Transaction.LookupCommitRequest.newBuilder();
        if (value.profile().isPresent()) result.setProfile(toWire(value.profile().get()));
        if (value.command().isPresent()) result.setCommand(toWire(value.command().get()));
        result.setReceiptId(value.receiptId());
        if (value.authorizationPublication().isPresent()) result.setAuthorizationPublication(Wire.toWire(value.authorizationPublication().get()));
        return result.build();
    }

    static Transactions.LookupCommitRequest fromWire(latent.transaction.v1.Transaction.LookupCommitRequest value) {
        return new Transactions.LookupCommitRequest(
                value.hasProfile() ? Optional.of(fromWire(value.getProfile())) : Optional.empty(),
                value.hasCommand() ? Optional.of(fromWire(value.getCommand())) : Optional.empty(),
                value.getReceiptId(),
                value.hasAuthorizationPublication() ? Optional.of(Wire.fromWire(value.getAuthorizationPublication())) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.LookupCommitResponse toWire(Transactions.LookupCommitResponse value) {
        var result = latent.transaction.v1.Transaction.LookupCommitResponse.newBuilder();
        if (value.command().isPresent()) result.setCommand(toWire(value.command().get()));
        return result.build();
    }

    static Transactions.LookupCommitResponse fromWire(latent.transaction.v1.Transaction.LookupCommitResponse value) {
        return new Transactions.LookupCommitResponse(
                value.hasCommand() ? Optional.of(fromWire(value.getCommand())) : Optional.empty());
    }

    static latent.control.v1.State.NamespaceConfiguration toWire(Transactions.NamespaceConfiguration value) {
        var result = latent.control.v1.State.NamespaceConfiguration.newBuilder();
        result.setStateSchema(value.stateSchema());
        if (value.quota().isPresent()) result.setQuota(toWire(value.quota().get()));
        return result.build();
    }

    static Transactions.NamespaceConfiguration fromWire(latent.control.v1.State.NamespaceConfiguration value) {
        return new Transactions.NamespaceConfiguration(
                value.getStateSchema(),
                value.hasQuota() ? Optional.of(fromWire(value.getQuota())) : Optional.empty());
    }

    static latent.control.v1.State.MutateNamespaceRequest toWire(Transactions.MutateNamespaceRequest value) {
        var result = latent.control.v1.State.MutateNamespaceRequest.newBuilder();
        if (value.namespace().isPresent()) result.setNamespace(toWire(value.namespace().get()));
        result.setOperationId(value.operationId());
        result.setMutationValue(value.mutation().value());
        if (value.expectedGeneration().isPresent()) result.setExpectedGeneration(value.expectedGeneration().get());
        if (value.configuration().isPresent()) result.setConfiguration(toWire(value.configuration().get()));
        return result.build();
    }

    static Transactions.MutateNamespaceRequest fromWire(latent.control.v1.State.MutateNamespaceRequest value) {
        return new Transactions.MutateNamespaceRequest(
                value.hasNamespace() ? Optional.of(fromWire(value.getNamespace())) : Optional.empty(),
                value.getOperationId(),
                new Transactions.NamespaceMutationKind(value.getMutationValue()),
                value.hasExpectedGeneration() ? Optional.of(value.getExpectedGeneration()) : Optional.empty(),
                value.hasConfiguration() ? Optional.of(fromWire(value.getConfiguration())) : Optional.empty());
    }

    static latent.control.v1.State.MutateNamespaceResponse toWire(Transactions.MutateNamespaceResponse value) {
        var result = latent.control.v1.State.MutateNamespaceResponse.newBuilder();
        if (value.receipt().isPresent()) result.setReceipt(toWire(value.receipt().get()));
        result.setReplayed(value.replayed());
        if (value.auditAck().isPresent()) result.setAuditAck(Wire.toWire(value.auditAck().get()));
        return result.build();
    }

    static Transactions.MutateNamespaceResponse fromWire(latent.control.v1.State.MutateNamespaceResponse value) {
        return new Transactions.MutateNamespaceResponse(
                value.hasReceipt() ? Optional.of(fromWire(value.getReceipt())) : Optional.empty(),
                value.getReplayed(),
                value.hasAuditAck() ? Optional.of(Wire.fromWire(value.getAuditAck())) : Optional.empty());
    }

    static latent.control.v1.State.MutateStateRequest toWire(Transactions.MutateStateRequest value) {
        var result = latent.control.v1.State.MutateStateRequest.newBuilder();
        if (value.namespace().isPresent()) result.setNamespace(toWire(value.namespace().get()));
        result.setOperationId(value.operationId());
        result.setMutationValue(value.mutation().value());
        if (value.recordId().isPresent()) result.setRecordId(value.recordId().get());
        result.setExpectedVersion(ByteString.copyFrom(value.expectedVersion().asReadOnlyBuffer()));
        result.setExpectedPolicyDigest(value.expectedPolicyDigest());
        result.setReason(value.reason());
        return result.build();
    }

    static Transactions.MutateStateRequest fromWire(latent.control.v1.State.MutateStateRequest value) {
        return new Transactions.MutateStateRequest(
                value.hasNamespace() ? Optional.of(fromWire(value.getNamespace())) : Optional.empty(),
                value.getOperationId(),
                new Transactions.StateMutationKind(value.getMutationValue()),
                value.hasRecordId() ? Optional.of(value.getRecordId()) : Optional.empty(),
                value.getExpectedVersion().asReadOnlyByteBuffer(),
                value.getExpectedPolicyDigest(),
                value.getReason());
    }

    static latent.control.v1.State.MutateStateResponse toWire(Transactions.MutateStateResponse value) {
        var result = latent.control.v1.State.MutateStateResponse.newBuilder();
        if (value.receipt().isPresent()) result.setReceipt(toWire(value.receipt().get()));
        if (value.auditAck().isPresent()) result.setAuditAck(Wire.toWire(value.auditAck().get()));
        return result.build();
    }

    static Transactions.MutateStateResponse fromWire(latent.control.v1.State.MutateStateResponse value) {
        return new Transactions.MutateStateResponse(
                value.hasReceipt() ? Optional.of(fromWire(value.getReceipt())) : Optional.empty(),
                value.hasAuditAck() ? Optional.of(Wire.fromWire(value.getAuditAck())) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.QueryRequest toWire(Transactions.QueryRequest value) {
        var result = latent.transaction.v1.Transaction.QueryRequest.newBuilder();
        if (value.profile().isPresent()) result.setProfile(toWire(value.profile().get()));
        if (value.invocation().isPresent()) result.setInvocation(Wire.toWire(value.invocation().get()));
        if (value.namespace().isPresent()) result.setNamespace(toWire(value.namespace().get()));
        if (value.entity().isPresent()) result.setEntity(value.entity().get());
        if (value.minimumViewVersion().isPresent()) result.setMinimumViewVersion(ByteString.copyFrom(value.minimumViewVersion().get().asReadOnlyBuffer()));
        return result.build();
    }

    static Transactions.QueryRequest fromWire(latent.transaction.v1.Transaction.QueryRequest value) {
        return new Transactions.QueryRequest(
                value.hasProfile() ? Optional.of(fromWire(value.getProfile())) : Optional.empty(),
                value.hasInvocation() ? Optional.of(Wire.fromWire(value.getInvocation())) : Optional.empty(),
                value.hasNamespace() ? Optional.of(fromWire(value.getNamespace())) : Optional.empty(),
                value.hasEntity() ? Optional.of(value.getEntity()) : Optional.empty(),
                value.hasMinimumViewVersion() ? Optional.of(value.getMinimumViewVersion().asReadOnlyByteBuffer()) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.QueryResponse toWire(Transactions.QueryResponse value) {
        var result = latent.transaction.v1.Transaction.QueryResponse.newBuilder();
        if (value.invocation().isPresent()) result.setInvocation(Wire.toWire(value.invocation().get()));
        if (value.view().isPresent()) result.setView(toWire(value.view().get()));
        if (value.source().isPresent()) result.setSource(toWire(value.source().get()));
        result.setObservedAtUnixMillis(value.observedAtUnixMillis());
        return result.build();
    }

    static Transactions.QueryResponse fromWire(latent.transaction.v1.Transaction.QueryResponse value) {
        return new Transactions.QueryResponse(
                value.hasInvocation() ? Optional.of(Wire.fromWire(value.getInvocation())) : Optional.empty(),
                value.hasView() ? Optional.of(fromWire(value.getView())) : Optional.empty(),
                value.hasSource() ? Optional.of(fromWire(value.getSource())) : Optional.empty(),
                value.getObservedAtUnixMillis());
    }

    static latent.control.v1.State.SelectEntityRequest toWire(Transactions.SelectEntityRequest value) {
        var result = latent.control.v1.State.SelectEntityRequest.newBuilder();
        if (value.namespace().isPresent()) result.setNamespace(toWire(value.namespace().get()));
        if (value.prefix().isPresent()) result.setPrefix(ByteString.copyFrom(value.prefix().get().asReadOnlyBuffer()));
        if (value.page().isPresent()) result.setPage(toWire(value.page().get()));
        return result.build();
    }

    static Transactions.SelectEntityRequest fromWire(latent.control.v1.State.SelectEntityRequest value) {
        return new Transactions.SelectEntityRequest(
                value.hasNamespace() ? Optional.of(fromWire(value.getNamespace())) : Optional.empty(),
                value.hasPrefix() ? Optional.of(value.getPrefix().asReadOnlyByteBuffer()) : Optional.empty(),
                value.hasPage() ? Optional.of(fromWire(value.getPage())) : Optional.empty());
    }

    static latent.control.v1.State.SelectEntityResponse toWire(Transactions.SelectEntityResponse value) {
        var result = latent.control.v1.State.SelectEntityResponse.newBuilder();
        for (var item : value.entities()) result.addEntities(toWire(item));
        if (value.page().isPresent()) result.setPage(toWire(value.page().get()));
        return result.build();
    }

    static Transactions.SelectEntityResponse fromWire(latent.control.v1.State.SelectEntityResponse value) {
        return new Transactions.SelectEntityResponse(
                value.getEntitiesList().stream().map(item -> fromWire(item)).toList(),
                value.hasPage() ? Optional.of(fromWire(value.getPage())) : Optional.empty());
    }

}
