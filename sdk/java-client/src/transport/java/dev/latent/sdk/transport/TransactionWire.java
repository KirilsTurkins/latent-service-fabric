// Generated from the authoritative Phase 4 transaction descriptors.
package dev.latent.sdk.transport;

import dev.latent.sdk.Transactions;
import com.google.protobuf.ByteString;
import java.util.Map;
import java.util.Optional;

final class TransactionWire {
    private TransactionWire() { }

    static latent.transaction.v1.Transaction.AbortFence toWire(Transactions.AbortFence value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.AbortFence toWire(Transactions.AbortFence value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.AbortFence.newBuilder();
        result.setCommandId(budget.text(value.commandId()));
        result.setAttemptId(budget.text(value.attemptId()));
        result.setTransactionId(budget.text(value.transactionId()));
        result.setOwnerFence(budget.bytes(value.ownerFence()));
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
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.TransactionProfile toWire(Transactions.TransactionProfile value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.TransactionProfile.newBuilder();
        result.setProfile(budget.text(value.profile()));
        result.setHostAbiDigest(budget.text(value.hostAbiDigest()));
        result.setPreparationProfileDigest(budget.text(value.preparationProfileDigest()));
        return result.build();
    }

    static Transactions.TransactionProfile fromWire(latent.transaction.v1.Transaction.TransactionProfile value) {
        return new Transactions.TransactionProfile(
                value.getProfile(),
                value.getHostAbiDigest(),
                value.getPreparationProfileDigest());
    }

    static latent.transaction.v1.Transaction.NamespaceSelector toWire(Transactions.NamespaceSelector value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.NamespaceSelector toWire(Transactions.NamespaceSelector value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.NamespaceSelector.newBuilder();
        result.setTenant(budget.text(value.tenant()));
        result.setNamespace(budget.text(value.namespace()));
        result.setIncarnation(budget.text(value.incarnation()));
        return result.build();
    }

    static Transactions.NamespaceSelector fromWire(latent.transaction.v1.Transaction.NamespaceSelector value) {
        return new Transactions.NamespaceSelector(
                value.getTenant(),
                value.getNamespace(),
                value.getIncarnation());
    }

    static latent.transaction.v1.Transaction.CommandSelector toWire(Transactions.CommandSelector value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.CommandSelector toWire(Transactions.CommandSelector value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.CommandSelector.newBuilder();
        if (value.namespace().isPresent()) result.setNamespace(toWire(value.namespace().get(), budget, depth + 1));
        result.setOperation(budget.text(value.operation()));
        if (value.entity().isPresent()) result.setEntity(budget.text(value.entity().get()));
        result.setClientKey(budget.text(value.clientKey()));
        if (value.sharedRecoveryScope().isPresent()) result.setSharedRecoveryScope(budget.text(value.sharedRecoveryScope().get()));
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
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.LookupCommandRequest toWire(Transactions.LookupCommandRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.LookupCommandRequest.newBuilder();
        if (value.profile().isPresent()) result.setProfile(toWire(value.profile().get(), budget, depth + 1));
        if (value.command().isPresent()) result.setCommand(toWire(value.command().get(), budget, depth + 1));
        if (value.attemptId().isPresent()) result.setAttemptId(budget.text(value.attemptId().get()));
        if (value.authorizationPublication().isPresent()) result.setAuthorizationPublication(Wire.toWire(value.authorizationPublication().get(), budget, depth + 1));
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
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.CancelCommandRequest toWire(Transactions.CancelCommandRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.CancelCommandRequest.newBuilder();
        if (value.command().isPresent()) result.setCommand(toWire(value.command().get(), budget, depth + 1));
        result.setReason(budget.text(value.reason()));
        return result.build();
    }

    static Transactions.CancelCommandRequest fromWire(latent.transaction.v1.Transaction.CancelCommandRequest value) {
        return new Transactions.CancelCommandRequest(
                value.hasCommand() ? Optional.of(fromWire(value.getCommand())) : Optional.empty(),
                value.getReason());
    }

    static latent.transaction.v1.Transaction.CommandKey toWire(Transactions.CommandKey value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.CommandKey toWire(Transactions.CommandKey value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.CommandKey.newBuilder();
        if (value.namespace().isPresent()) result.setNamespace(toWire(value.namespace().get(), budget, depth + 1));
        result.setRecoveryScope(budget.text(value.recoveryScope()));
        result.setOperation(budget.text(value.operation()));
        if (value.entity().isPresent()) result.setEntity(budget.text(value.entity().get()));
        result.setClientKey(budget.text(value.clientKey()));
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
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.SourceIdentity toWire(Transactions.SourceIdentity value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.SourceIdentity.newBuilder();
        result.setPublicationId(budget.text(value.publicationId()));
        result.setRevisionId(budget.text(value.revisionId()));
        result.setReleaseDigest(budget.text(value.releaseDigest()));
        result.setRouteGeneration(budget.scalar(value.routeGeneration()));
        result.setContractDigest(budget.text(value.contractDigest()));
        result.setStateSchema(budget.text(value.stateSchema()));
        result.setInputFormat(budget.text(value.inputFormat()));
        result.setResultFormat(budget.text(value.resultFormat()));
        result.setComponentDigest(budget.text(value.componentDigest()));
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
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.CommitReceipt toWire(Transactions.CommitReceipt value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.CommitReceipt.newBuilder();
        result.setCommandId(budget.text(value.commandId()));
        result.setAttemptId(budget.text(value.attemptId()));
        result.setTransactionId(budget.text(value.transactionId()));
        result.setCommittedVersion(budget.bytes(value.committedVersion()));
        result.setCommittedAtUnixMillis(budget.scalar(value.committedAtUnixMillis()));
        for (var item : budget.list(value.effectIds(), 128)) result.addEffectIds(budget.text(item));
        result.setReceiptId(budget.text(value.receiptId()));
        if (value.source().isPresent()) result.setSource(toWire(value.source().get(), budget, depth + 1));
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
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.LinkedRetention toWire(Transactions.LinkedRetention value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.LinkedRetention.newBuilder();
        result.setRecordFormat(budget.text(value.recordFormat()));
        result.setRecordVersion(budget.scalar(value.recordVersion()));
        if (value.payloadExpiresAtUnixMillis().isPresent()) result.setPayloadExpiresAtUnixMillis(budget.scalar(value.payloadExpiresAtUnixMillis().get()));
        if (value.identityExpiresAtUnixMillis().isPresent()) result.setIdentityExpiresAtUnixMillis(budget.scalar(value.identityExpiresAtUnixMillis().get()));
        if (value.remainingRecoveryMillis().isPresent()) result.setRemainingRecoveryMillis(budget.scalar(value.remainingRecoveryMillis().get()));
        for (var item : budget.list(value.requiredRecordIds(), 256)) result.addRequiredRecordIds(budget.text(item));
        result.setPayloadAvailable(budget.scalar(value.payloadAvailable()));
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
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.CommandInspection toWire(Transactions.CommandInspection value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.CommandInspection.newBuilder();
        if ((value.success().isPresent() ? 1 : 0) + (value.businessRejection().isPresent() ? 1 : 0) + (value.technicalFailure().isPresent() ? 1 : 0) > 1) throw new IllegalArgumentException("contradictory oneof");
        if (value.key().isPresent()) result.setKey(toWire(value.key().get(), budget, depth + 1));
        result.setCommandId(budget.text(value.commandId()));
        result.setAttemptId(budget.text(value.attemptId()));
        result.setFingerprintSha256(budget.bytes(value.fingerprintSha256()));
        result.setOutcomeValue(budget.scalar(value.outcome().value()));
        result.setMetadataDurable(budget.scalar(value.metadataDurable()));
        result.setApplicationStateCommitted(budget.scalar(value.applicationStateCommitted()));
        if (value.source().isPresent()) result.setSource(toWire(value.source().get(), budget, depth + 1));
        if (value.success().isPresent()) result.setSuccess(Wire.toWire(value.success().get(), budget, depth + 1));
        if (value.businessRejection().isPresent()) result.setBusinessRejection(Wire.toWire(value.businessRejection().get(), budget, depth + 1));
        if (value.technicalFailure().isPresent()) result.setTechnicalFailure(Wire.toInvocationPlatformError(value.technicalFailure().get(), budget, depth + 1));
        if (value.commit().isPresent()) result.setCommit(toWire(value.commit().get(), budget, depth + 1));
        if (value.provenAbort().isPresent()) result.setProvenAbort(toWire(value.provenAbort().get(), budget, depth + 1));
        if (value.retention().isPresent()) result.setRetention(toWire(value.retention().get(), budget, depth + 1));
        if (value.cleanupFailure().isPresent()) result.setCleanupFailure(Wire.toInvocationPlatformError(value.cleanupFailure().get(), budget, depth + 1));
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
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.CancelCommandResponse toWire(Transactions.CancelCommandResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.CancelCommandResponse.newBuilder();
        result.setDispositionValue(budget.scalar(value.disposition().value()));
        if (value.command().isPresent()) result.setCommand(toWire(value.command().get(), budget, depth + 1));
        return result.build();
    }

    static Transactions.CancelCommandResponse fromWire(latent.transaction.v1.Transaction.CancelCommandResponse value) {
        return new Transactions.CancelCommandResponse(
                new Transactions.CommandCancelDisposition(value.getDispositionValue()),
                value.hasCommand() ? Optional.of(fromWire(value.getCommand())) : Optional.empty());
    }

    static latent.control.v1.Dispatcher.DispatcherGeneration toWire(Transactions.DispatcherGeneration value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Dispatcher.DispatcherGeneration toWire(Transactions.DispatcherGeneration value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Dispatcher.DispatcherGeneration.newBuilder();
        result.setOwnerEpoch(budget.scalar(value.ownerEpoch()));
        result.setRevision(budget.scalar(value.revision()));
        return result.build();
    }

    static Transactions.DispatcherGeneration fromWire(latent.control.v1.Dispatcher.DispatcherGeneration value) {
        return new Transactions.DispatcherGeneration(
                value.getOwnerEpoch(),
                value.getRevision());
    }

    static latent.control.v1.Dispatcher.ControlDispatcherRequest toWire(Transactions.ControlDispatcherRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Dispatcher.ControlDispatcherRequest toWire(Transactions.ControlDispatcherRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Dispatcher.ControlDispatcherRequest.newBuilder();
        if (value.profile().isPresent()) result.setProfile(toWire(value.profile().get(), budget, depth + 1));
        result.setScopeValue(budget.scalar(value.scope().value()));
        result.setOperationId(budget.text(value.operationId()));
        result.setActionValue(budget.scalar(value.action().value()));
        if (value.expectedGeneration().isPresent()) result.setExpectedGeneration(toWire(value.expectedGeneration().get(), budget, depth + 1));
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
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Dispatcher.DispatcherOperationReceipt toWire(Transactions.DispatcherOperationReceipt value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Dispatcher.DispatcherOperationReceipt.newBuilder();
        result.setOperationId(budget.text(value.operationId()));
        result.setReceiptId(budget.text(value.receiptId()));
        result.setActionValue(budget.scalar(value.action().value()));
        result.setAuthenticatedOperator(budget.text(value.authenticatedOperator()));
        result.setActorTenant(budget.text(value.actorTenant()));
        if (value.beforeGeneration().isPresent()) result.setBeforeGeneration(toWire(value.beforeGeneration().get(), budget, depth + 1));
        if (value.afterGeneration().isPresent()) result.setAfterGeneration(toWire(value.afterGeneration().get(), budget, depth + 1));
        result.setObservedAtUnixMillis(budget.scalar(value.observedAtUnixMillis()));
        result.setClockContinuityProven(budget.scalar(value.clockContinuityProven()));
        result.setRestoreReviewRequired(budget.scalar(value.restoreReviewRequired()));
        result.setDispositionValue(budget.scalar(value.disposition().value()));
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
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Dispatcher.ControlDispatcherResponse toWire(Transactions.ControlDispatcherResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Dispatcher.ControlDispatcherResponse.newBuilder();
        if (value.receipt().isPresent()) result.setReceipt(toWire(value.receipt().get(), budget, depth + 1));
        result.setReplayed(budget.scalar(value.replayed()));
        result.setPublished(budget.scalar(value.published()));
        result.setPaused(budget.scalar(value.paused()));
        if (value.auditAck().isPresent()) result.setAuditAck(Wire.toWire(value.auditAck().get(), budget, depth + 1));
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
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Dispatcher.DispatcherSnapshot toWire(Transactions.DispatcherSnapshot value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Dispatcher.DispatcherSnapshot.newBuilder();
        if (value.generation().isPresent()) result.setGeneration(toWire(value.generation().get(), budget, depth + 1));
        result.setPaused(budget.scalar(value.paused()));
        result.setPendingControl(budget.scalar(value.pendingControl()));
        result.setRestoreReviewRequired(budget.scalar(value.restoreReviewRequired()));
        result.setAdmissionClosed(budget.scalar(value.admissionClosed()));
        result.setQuarantined(budget.scalar(value.quarantined()));
        result.setFailureValue(budget.scalar(value.failure().value()));
        result.setQueued(budget.scalar(value.queued()));
        result.setActiveJobs(budget.scalar(value.activeJobs()));
        result.setRetainedAttemptBytes(budget.scalar(value.retainedAttemptBytes()));
        result.setLiveWorkers(budget.scalar(value.liveWorkers()));
        result.setAcceptedEffects(budget.scalar(value.acceptedEffects()));
        result.setPhysicalOwners(budget.scalar(value.physicalOwners()));
        result.setQuarantinedPhysicalOwners(budget.scalar(value.quarantinedPhysicalOwners()));
        result.setCommandOwners(budget.scalar(value.commandOwners()));
        result.setClaims(budget.scalar(value.claims()));
        result.setPendingEffects(budget.scalar(value.pendingEffects()));
        result.setUncertainEffects(budget.scalar(value.uncertainEffects()));
        result.setBlockedEffects(budget.scalar(value.blockedEffects()));
        result.setDeadLetterEffects(budget.scalar(value.deadLetterEffects()));
        result.setCountsObservedAtUnixMillis(budget.scalar(value.countsObservedAtUnixMillis()));
        result.setClockContinuityProven(budget.scalar(value.clockContinuityProven()));
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

    static latent.transaction.v1.Transaction.GetEffectRequest toWire(Transactions.GetEffectRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.GetEffectRequest toWire(Transactions.GetEffectRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.GetEffectRequest.newBuilder();
        if (value.profile().isPresent()) result.setProfile(toWire(value.profile().get(), budget, depth + 1));
        if (value.command().isPresent()) result.setCommand(toWire(value.command().get(), budget, depth + 1));
        result.setEffectId(budget.text(value.effectId()));
        if (value.authorizationPublication().isPresent()) result.setAuthorizationPublication(Wire.toWire(value.authorizationPublication().get(), budget, depth + 1));
        return result.build();
    }

    static Transactions.GetEffectRequest fromWire(latent.transaction.v1.Transaction.GetEffectRequest value) {
        return new Transactions.GetEffectRequest(
                value.hasProfile() ? Optional.of(fromWire(value.getProfile())) : Optional.empty(),
                value.hasCommand() ? Optional.of(fromWire(value.getCommand())) : Optional.empty(),
                value.getEffectId(),
                value.hasAuthorizationPublication() ? Optional.of(Wire.fromWire(value.getAuthorizationPublication())) : Optional.empty());
    }

    static latent.control.v1.State.PlanEffectMutationRequest toWire(Transactions.PlanEffectMutationRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.State.PlanEffectMutationRequest toWire(Transactions.PlanEffectMutationRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.State.PlanEffectMutationRequest.newBuilder();
        if (value.effect().isPresent()) result.setEffect(toWire(value.effect().get(), budget, depth + 1));
        result.setOperationId(budget.text(value.operationId()));
        result.setMutationValue(budget.scalar(value.mutation().value()));
        result.setExpectedVersion(budget.bytes(value.expectedVersion()));
        result.setExpectedPolicyDigest(budget.text(value.expectedPolicyDigest()));
        result.setReason(budget.text(value.reason()));
        result.setRetryDelayMillis(budget.scalar(value.retryDelayMillis()));
        return result.build();
    }

    static Transactions.PlanEffectMutationRequest fromWire(latent.control.v1.State.PlanEffectMutationRequest value) {
        return new Transactions.PlanEffectMutationRequest(
                value.hasEffect() ? Optional.of(fromWire(value.getEffect())) : Optional.empty(),
                value.getOperationId(),
                new Transactions.StateMutationKind(value.getMutationValue()),
                value.getExpectedVersion().asReadOnlyByteBuffer(),
                value.getExpectedPolicyDigest(),
                value.getReason(),
                value.getRetryDelayMillis());
    }

    static latent.control.v1.State.EffectManagementPlan toWire(Transactions.EffectManagementPlan value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.State.EffectManagementPlan toWire(Transactions.EffectManagementPlan value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.State.EffectManagementPlan.newBuilder();
        if (value.original().isPresent()) result.setOriginal(toWire(value.original().get(), budget, depth + 1));
        result.setPlanDigest(budget.bytes(value.planDigest()));
        result.setManagementSequence(budget.scalar(value.managementSequence()));
        result.setOwnerEpoch(budget.scalar(value.ownerEpoch()));
        result.setClaimGeneration(budget.scalar(value.claimGeneration()));
        result.setDispatchAttempt(budget.scalar(value.dispatchAttempt()));
        result.setExpiresAtUnixMillis(budget.scalar(value.expiresAtUnixMillis()));
        result.setPreparedAtUnixMillis(budget.scalar(value.preparedAtUnixMillis()));
        result.setBeforeValue(budget.scalar(value.before().value()));
        result.setSafetyValue(budget.scalar(value.safety().value()));
        if (value.dedupValidUntilUnixMillis().isPresent()) result.setDedupValidUntilUnixMillis(budget.scalar(value.dedupValidUntilUnixMillis().get()));
        return result.build();
    }

    static Transactions.EffectManagementPlan fromWire(latent.control.v1.State.EffectManagementPlan value) {
        return new Transactions.EffectManagementPlan(
                value.hasOriginal() ? Optional.of(fromWire(value.getOriginal())) : Optional.empty(),
                value.getPlanDigest().asReadOnlyByteBuffer(),
                value.getManagementSequence(),
                value.getOwnerEpoch(),
                value.getClaimGeneration(),
                value.getDispatchAttempt(),
                value.getExpiresAtUnixMillis(),
                value.getPreparedAtUnixMillis(),
                new Transactions.EffectDisposition(value.getBeforeValue()),
                new Transactions.EffectPlanSafety(value.getSafetyValue()),
                value.hasDedupValidUntilUnixMillis() ? Optional.of(value.getDedupValidUntilUnixMillis()) : Optional.empty());
    }

    static latent.control.v1.State.EffectManagementReceiptDetails toWire(Transactions.EffectManagementReceiptDetails value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.State.EffectManagementReceiptDetails toWire(Transactions.EffectManagementReceiptDetails value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.State.EffectManagementReceiptDetails.newBuilder();
        if (value.originalPlan().isPresent()) result.setOriginalPlan(toWire(value.originalPlan().get(), budget, depth + 1));
        result.setBeforeValue(budget.scalar(value.before().value()));
        result.setAfterValue(budget.scalar(value.after().value()));
        result.setFactValue(budget.scalar(value.fact().value()));
        if (value.providerReceipt().isPresent()) result.setProviderReceipt(budget.text(value.providerReceipt().get()));
        if (value.providerObservedAtUnixMillis().isPresent()) result.setProviderObservedAtUnixMillis(budget.scalar(value.providerObservedAtUnixMillis().get()));
        return result.build();
    }

    static Transactions.EffectManagementReceiptDetails fromWire(latent.control.v1.State.EffectManagementReceiptDetails value) {
        return new Transactions.EffectManagementReceiptDetails(
                value.hasOriginalPlan() ? Optional.of(fromWire(value.getOriginalPlan())) : Optional.empty(),
                new Transactions.EffectDisposition(value.getBeforeValue()),
                new Transactions.EffectDisposition(value.getAfterValue()),
                new Transactions.EffectManagementFact(value.getFactValue()),
                value.hasProviderReceipt() ? Optional.of(value.getProviderReceipt()) : Optional.empty(),
                value.hasProviderObservedAtUnixMillis() ? Optional.of(value.getProviderObservedAtUnixMillis()) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.EffectReceipt toWire(Transactions.EffectReceipt value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.EffectReceipt toWire(Transactions.EffectReceipt value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.EffectReceipt.newBuilder();
        result.setEffectId(budget.text(value.effectId()));
        result.setCommandId(budget.text(value.commandId()));
        result.setCommandAttemptId(budget.text(value.commandAttemptId()));
        result.setDispatchAttempt(budget.scalar(value.dispatchAttempt()));
        result.setDispositionValue(budget.scalar(value.disposition().value()));
        if (value.providerReceipt().isPresent()) result.setProviderReceipt(budget.text(value.providerReceipt().get()));
        if (value.failureCode().isPresent()) result.setFailureCode(budget.text(value.failureCode().get()));
        result.setOccurredAtUnixMillis(budget.scalar(value.occurredAtUnixMillis()));
        if (value.retention().isPresent()) result.setRetention(toWire(value.retention().get(), budget, depth + 1));
        if (value.managementOperationReceiptId().isPresent()) result.setManagementOperationReceiptId(budget.text(value.managementOperationReceiptId().get()));
        result.setProviderProfile(budget.text(value.providerProfile()));
        result.setRecordVersion(budget.bytes(value.recordVersion()));
        if (value.ownerEpoch().isPresent()) result.setOwnerEpoch(budget.scalar(value.ownerEpoch().get()));
        if (value.claimGeneration().isPresent()) result.setClaimGeneration(budget.scalar(value.claimGeneration().get()));
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
                value.getProviderProfile(),
                value.getRecordVersion().asReadOnlyByteBuffer(),
                value.hasOwnerEpoch() ? Optional.of(value.getOwnerEpoch()) : Optional.empty(),
                value.hasClaimGeneration() ? Optional.of(value.getClaimGeneration()) : Optional.empty());
    }

    static latent.control.v1.State.EntityInspection toWire(Transactions.EntityInspection value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.State.EntityInspection toWire(Transactions.EntityInspection value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.State.EntityInspection.newBuilder();
        result.setEntity(budget.text(value.entity()));
        result.setVersion(budget.bytes(value.version()));
        return result.build();
    }

    static Transactions.EntityInspection fromWire(latent.control.v1.State.EntityInspection value) {
        return new Transactions.EntityInspection(
                value.getEntity(),
                value.getVersion().asReadOnlyByteBuffer());
    }

    static latent.transaction.v1.Transaction.ExpectedVersion toWire(Transactions.ExpectedVersion value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.ExpectedVersion toWire(Transactions.ExpectedVersion value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.ExpectedVersion.newBuilder();
        if ((value.absent().isPresent() ? 1 : 0) + (value.version().isPresent() ? 1 : 0) > 1) throw new IllegalArgumentException("contradictory oneof");
        result.setKey(budget.bytes(value.key()));
        if (value.absent().isPresent()) result.setAbsent(budget.scalar(value.absent().get()));
        if (value.version().isPresent()) result.setVersion(budget.bytes(value.version().get()));
        return result.build();
    }

    static Transactions.ExpectedVersion fromWire(latent.transaction.v1.Transaction.ExpectedVersion value) {
        return new Transactions.ExpectedVersion(
                value.getKey().asReadOnlyByteBuffer(),
                value.hasAbsent() ? Optional.of(value.getAbsent()) : Optional.empty(),
                value.hasVersion() ? Optional.of(value.getVersion().asReadOnlyByteBuffer()) : Optional.empty());
    }

    static latent.control.v1.Dispatcher.GetDispatcherOperationRequest toWire(Transactions.GetDispatcherOperationRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Dispatcher.GetDispatcherOperationRequest toWire(Transactions.GetDispatcherOperationRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Dispatcher.GetDispatcherOperationRequest.newBuilder();
        if (value.original().isPresent()) result.setOriginal(toWire(value.original().get(), budget, depth + 1));
        return result.build();
    }

    static Transactions.GetDispatcherOperationRequest fromWire(latent.control.v1.Dispatcher.GetDispatcherOperationRequest value) {
        return new Transactions.GetDispatcherOperationRequest(
                value.hasOriginal() ? Optional.of(fromWire(value.getOriginal())) : Optional.empty());
    }

    static latent.control.v1.Dispatcher.GetDispatcherOperationResponse toWire(Transactions.GetDispatcherOperationResponse value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Dispatcher.GetDispatcherOperationResponse toWire(Transactions.GetDispatcherOperationResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Dispatcher.GetDispatcherOperationResponse.newBuilder();
        if (value.receipt().isPresent()) result.setReceipt(toWire(value.receipt().get(), budget, depth + 1));
        if (value.auditAck().isPresent()) result.setAuditAck(Wire.toWire(value.auditAck().get(), budget, depth + 1));
        return result.build();
    }

    static Transactions.GetDispatcherOperationResponse fromWire(latent.control.v1.Dispatcher.GetDispatcherOperationResponse value) {
        return new Transactions.GetDispatcherOperationResponse(
                value.hasReceipt() ? Optional.of(fromWire(value.getReceipt())) : Optional.empty(),
                value.hasAuditAck() ? Optional.of(Wire.fromWire(value.getAuditAck())) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.GetEffectResponse toWire(Transactions.GetEffectResponse value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.GetEffectResponse toWire(Transactions.GetEffectResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.GetEffectResponse.newBuilder();
        if (value.effect().isPresent()) result.setEffect(toWire(value.effect().get(), budget, depth + 1));
        return result.build();
    }

    static Transactions.GetEffectResponse fromWire(latent.transaction.v1.Transaction.GetEffectResponse value) {
        return new Transactions.GetEffectResponse(
                value.hasEffect() ? Optional.of(fromWire(value.getEffect())) : Optional.empty());
    }

    static latent.control.v1.State.InspectNamespaceRequest toWire(Transactions.InspectNamespaceRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.State.InspectNamespaceRequest toWire(Transactions.InspectNamespaceRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.State.InspectNamespaceRequest.newBuilder();
        if (value.profile().isPresent()) result.setProfile(toWire(value.profile().get(), budget, depth + 1));
        if (value.namespace().isPresent()) result.setNamespace(toWire(value.namespace().get(), budget, depth + 1));
        if (value.authorizationPublication().isPresent()) result.setAuthorizationPublication(Wire.toWire(value.authorizationPublication().get(), budget, depth + 1));
        return result.build();
    }

    static Transactions.InspectNamespaceRequest fromWire(latent.control.v1.State.InspectNamespaceRequest value) {
        return new Transactions.InspectNamespaceRequest(
                value.hasProfile() ? Optional.of(fromWire(value.getProfile())) : Optional.empty(),
                value.hasNamespace() ? Optional.of(fromWire(value.getNamespace())) : Optional.empty(),
                value.hasAuthorizationPublication() ? Optional.of(Wire.fromWire(value.getAuthorizationPublication())) : Optional.empty());
    }

    static latent.control.v1.State.GetStateOperationReceiptRequest toWire(Transactions.GetStateOperationReceiptRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.State.GetStateOperationReceiptRequest toWire(Transactions.GetStateOperationReceiptRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.State.GetStateOperationReceiptRequest.newBuilder();
        if (value.namespace().isPresent()) result.setNamespace(toWire(value.namespace().get(), budget, depth + 1));
        result.setOperationId(budget.text(value.operationId()));
        if (value.originalEffectPlan().isPresent()) result.setOriginalEffectPlan(toWire(value.originalEffectPlan().get(), budget, depth + 1));
        return result.build();
    }

    static Transactions.GetStateOperationReceiptRequest fromWire(latent.control.v1.State.GetStateOperationReceiptRequest value) {
        return new Transactions.GetStateOperationReceiptRequest(
                value.hasNamespace() ? Optional.of(fromWire(value.getNamespace())) : Optional.empty(),
                value.getOperationId(),
                value.hasOriginalEffectPlan() ? Optional.of(fromWire(value.getOriginalEffectPlan())) : Optional.empty());
    }

    static latent.control.v1.State.StateOperationReceipt toWire(Transactions.StateOperationReceipt value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.State.StateOperationReceipt toWire(Transactions.StateOperationReceipt value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.State.StateOperationReceipt.newBuilder();
        result.setOperationId(budget.text(value.operationId()));
        result.setReceiptId(budget.text(value.receiptId()));
        result.setMutationValue(budget.scalar(value.mutation().value()));
        if (value.namespace().isPresent()) result.setNamespace(toWire(value.namespace().get(), budget, depth + 1));
        result.setAuthenticatedOperator(budget.text(value.authenticatedOperator()));
        result.setBeforeVersion(budget.bytes(value.beforeVersion()));
        result.setAfterVersion(budget.bytes(value.afterVersion()));
        result.setCompletedAtUnixMillis(budget.scalar(value.completedAtUnixMillis()));
        if (value.recordId().isPresent()) result.setRecordId(budget.text(value.recordId().get()));
        result.setPolicyDigest(budget.text(value.policyDigest()));
        result.setDispositionValue(budget.scalar(value.disposition().value()));
        if (value.effect().isPresent()) result.setEffect(toWire(value.effect().get(), budget, depth + 1));
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
                new Transactions.StateOperationDisposition(value.getDispositionValue()),
                value.hasEffect() ? Optional.of(fromWire(value.getEffect())) : Optional.empty());
    }

    static latent.control.v1.State.NamespaceOperationReceipt toWire(Transactions.NamespaceOperationReceipt value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.State.NamespaceOperationReceipt toWire(Transactions.NamespaceOperationReceipt value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.State.NamespaceOperationReceipt.newBuilder();
        result.setOperationId(budget.text(value.operationId()));
        result.setReceiptId(budget.text(value.receiptId()));
        result.setMutationValue(budget.scalar(value.mutation().value()));
        if (value.namespace().isPresent()) result.setNamespace(toWire(value.namespace().get(), budget, depth + 1));
        result.setAuthenticatedOperator(budget.text(value.authenticatedOperator()));
        if (value.beforeGeneration().isPresent()) result.setBeforeGeneration(budget.scalar(value.beforeGeneration().get()));
        result.setAfterGeneration(budget.scalar(value.afterGeneration()));
        result.setStatusValue(budget.scalar(value.status().value()));
        result.setStateSchema(budget.text(value.stateSchema()));
        result.setDispositionValue(budget.scalar(value.disposition().value()));
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
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.State.GetStateOperationReceiptResponse toWire(Transactions.GetStateOperationReceiptResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.State.GetStateOperationReceiptResponse.newBuilder();
        if (value.receipt().isPresent()) result.setReceipt(toWire(value.receipt().get(), budget, depth + 1));
        if (value.namespaceReceipt().isPresent()) result.setNamespaceReceipt(toWire(value.namespaceReceipt().get(), budget, depth + 1));
        if (value.auditAck().isPresent()) result.setAuditAck(Wire.toWire(value.auditAck().get(), budget, depth + 1));
        return result.build();
    }

    static Transactions.GetStateOperationReceiptResponse fromWire(latent.control.v1.State.GetStateOperationReceiptResponse value) {
        return new Transactions.GetStateOperationReceiptResponse(
                value.hasReceipt() ? Optional.of(fromWire(value.getReceipt())) : Optional.empty(),
                value.hasNamespaceReceipt() ? Optional.of(fromWire(value.getNamespaceReceipt())) : Optional.empty(),
                value.hasAuditAck() ? Optional.of(Wire.fromWire(value.getAuditAck())) : Optional.empty());
    }

    static latent.control.v1.Dispatcher.InspectDispatcherRequest toWire(Transactions.InspectDispatcherRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Dispatcher.InspectDispatcherRequest toWire(Transactions.InspectDispatcherRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Dispatcher.InspectDispatcherRequest.newBuilder();
        if (value.profile().isPresent()) result.setProfile(toWire(value.profile().get(), budget, depth + 1));
        result.setScopeValue(budget.scalar(value.scope().value()));
        return result.build();
    }

    static Transactions.InspectDispatcherRequest fromWire(latent.control.v1.Dispatcher.InspectDispatcherRequest value) {
        return new Transactions.InspectDispatcherRequest(
                value.hasProfile() ? Optional.of(fromWire(value.getProfile())) : Optional.empty(),
                new Transactions.DispatcherScope(value.getScopeValue()));
    }

    static latent.control.v1.Dispatcher.InspectDispatcherResponse toWire(Transactions.InspectDispatcherResponse value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Dispatcher.InspectDispatcherResponse toWire(Transactions.InspectDispatcherResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Dispatcher.InspectDispatcherResponse.newBuilder();
        if (value.dispatcher().isPresent()) result.setDispatcher(toWire(value.dispatcher().get(), budget, depth + 1));
        if (value.auditAck().isPresent()) result.setAuditAck(Wire.toWire(value.auditAck().get(), budget, depth + 1));
        return result.build();
    }

    static Transactions.InspectDispatcherResponse fromWire(latent.control.v1.Dispatcher.InspectDispatcherResponse value) {
        return new Transactions.InspectDispatcherResponse(
                value.hasDispatcher() ? Optional.of(fromWire(value.getDispatcher())) : Optional.empty(),
                value.hasAuditAck() ? Optional.of(Wire.fromWire(value.getAuditAck())) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.ViewIdentity toWire(Transactions.ViewIdentity value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.ViewIdentity toWire(Transactions.ViewIdentity value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.ViewIdentity.newBuilder();
        if (value.namespace().isPresent()) result.setNamespace(toWire(value.namespace().get(), budget, depth + 1));
        result.setVersion(budget.bytes(value.version()));
        result.setStateSchema(budget.text(value.stateSchema()));
        return result.build();
    }

    static Transactions.ViewIdentity fromWire(latent.transaction.v1.Transaction.ViewIdentity value) {
        return new Transactions.ViewIdentity(
                value.hasNamespace() ? Optional.of(fromWire(value.getNamespace())) : Optional.empty(),
                value.getVersion().asReadOnlyByteBuffer(),
                value.getStateSchema());
    }

    static latent.control.v1.State.NamespaceQuota toWire(Transactions.NamespaceQuota value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.State.NamespaceQuota toWire(Transactions.NamespaceQuota value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.State.NamespaceQuota.newBuilder();
        result.setStateKeys(budget.scalar(value.stateKeys()));
        result.setStateBytes(budget.scalar(value.stateBytes()));
        result.setResultRows(budget.scalar(value.resultRows()));
        result.setResultBytes(budget.scalar(value.resultBytes()));
        result.setEffectRows(budget.scalar(value.effectRows()));
        result.setEffectBytes(budget.scalar(value.effectBytes()));
        result.setPayloadBytes(budget.scalar(value.payloadBytes()));
        result.setRecoveryBytes(budget.scalar(value.recoveryBytes()));
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
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.State.NamespaceInspection toWire(Transactions.NamespaceInspection value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.State.NamespaceInspection.newBuilder();
        if (value.view().isPresent()) result.setView(toWire(value.view().get(), budget, depth + 1));
        result.setEncodedStateBytes(budget.scalar(value.encodedStateBytes()));
        result.setCommandCount(budget.scalar(value.commandCount()));
        result.setPendingEffectCount(budget.scalar(value.pendingEffectCount()));
        for (var item : budget.list(value.retainedFormats(), 128)) result.addRetainedFormats(toWire(item, budget, depth + 1));
        result.setEngineProfile(budget.text(value.engineProfile()));
        result.setEngineProfileDigest(budget.text(value.engineProfileDigest()));
        result.setStatusValue(budget.scalar(value.status().value()));
        if (value.quota().isPresent()) result.setQuota(toWire(value.quota().get(), budget, depth + 1));
        result.setGeneration(budget.scalar(value.generation()));
        result.setNamespacePolicyDigest(budget.text(value.namespacePolicyDigest()));
        if (value.policyDigest().isPresent()) result.setPolicyDigest(budget.text(value.policyDigest().get()));
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
                value.getGeneration(),
                value.getNamespacePolicyDigest(),
                value.hasPolicyDigest() ? Optional.of(value.getPolicyDigest()) : Optional.empty());
    }

    static latent.control.v1.State.InspectNamespaceResponse toWire(Transactions.InspectNamespaceResponse value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.State.InspectNamespaceResponse toWire(Transactions.InspectNamespaceResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.State.InspectNamespaceResponse.newBuilder();
        if (value.namespace().isPresent()) result.setNamespace(toWire(value.namespace().get(), budget, depth + 1));
        return result.build();
    }

    static Transactions.InspectNamespaceResponse fromWire(latent.control.v1.State.InspectNamespaceResponse value) {
        return new Transactions.InspectNamespaceResponse(
                value.hasNamespace() ? Optional.of(fromWire(value.getNamespace())) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.RetryAttempt toWire(Transactions.RetryAttempt value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.RetryAttempt toWire(Transactions.RetryAttempt value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.RetryAttempt.newBuilder();
        result.setRequestId(budget.text(value.requestId()));
        if (value.expectedAbort().isPresent()) result.setExpectedAbort(toWire(value.expectedAbort().get(), budget, depth + 1));
        return result.build();
    }

    static Transactions.RetryAttempt fromWire(latent.transaction.v1.Transaction.RetryAttempt value) {
        return new Transactions.RetryAttempt(
                value.getRequestId(),
                value.hasExpectedAbort() ? Optional.of(fromWire(value.getExpectedAbort())) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.InvokeCommandRequest toWire(Transactions.InvokeCommandRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.InvokeCommandRequest toWire(Transactions.InvokeCommandRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.InvokeCommandRequest.newBuilder();
        if (value.profile().isPresent()) result.setProfile(toWire(value.profile().get(), budget, depth + 1));
        if (value.invocation().isPresent()) result.setInvocation(Wire.toWire(value.invocation().get(), budget, depth + 1));
        if (value.command().isPresent()) result.setCommand(toWire(value.command().get(), budget, depth + 1));
        result.setInputFormat(budget.text(value.inputFormat()));
        for (var item : budget.list(value.expectedVersions(), 128)) result.addExpectedVersions(toWire(item, budget, depth + 1));
        if (value.retryAttempt().isPresent()) result.setRetryAttempt(toWire(value.retryAttempt().get(), budget, depth + 1));
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
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.InvokeCommandResponse toWire(Transactions.InvokeCommandResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.InvokeCommandResponse.newBuilder();
        if (value.invocation().isPresent()) result.setInvocation(Wire.toWire(value.invocation().get(), budget, depth + 1));
        if (value.command().isPresent()) result.setCommand(toWire(value.command().get(), budget, depth + 1));
        result.setReplayed(budget.scalar(value.replayed()));
        return result.build();
    }

    static Transactions.InvokeCommandResponse fromWire(latent.transaction.v1.Transaction.InvokeCommandResponse value) {
        return new Transactions.InvokeCommandResponse(
                value.hasInvocation() ? Optional.of(Wire.fromWire(value.getInvocation())) : Optional.empty(),
                value.hasCommand() ? Optional.of(fromWire(value.getCommand())) : Optional.empty(),
                value.getReplayed());
    }

    static latent.transaction.v1.Transaction.PageRequest toWire(Transactions.PageRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.PageRequest toWire(Transactions.PageRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.PageRequest.newBuilder();
        result.setLimit(budget.scalar(value.limit()));
        if (value.cursor().isPresent()) result.setCursor(budget.bytes(value.cursor().get()));
        return result.build();
    }

    static Transactions.PageRequest fromWire(latent.transaction.v1.Transaction.PageRequest value) {
        return new Transactions.PageRequest(
                value.getLimit(),
                value.hasCursor() ? Optional.of(value.getCursor().asReadOnlyByteBuffer()) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.ListEffectHistoryRequest toWire(Transactions.ListEffectHistoryRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.ListEffectHistoryRequest toWire(Transactions.ListEffectHistoryRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.ListEffectHistoryRequest.newBuilder();
        if (value.effect().isPresent()) result.setEffect(toWire(value.effect().get(), budget, depth + 1));
        if (value.page().isPresent()) result.setPage(toWire(value.page().get(), budget, depth + 1));
        return result.build();
    }

    static Transactions.ListEffectHistoryRequest fromWire(latent.transaction.v1.Transaction.ListEffectHistoryRequest value) {
        return new Transactions.ListEffectHistoryRequest(
                value.hasEffect() ? Optional.of(fromWire(value.getEffect())) : Optional.empty(),
                value.hasPage() ? Optional.of(fromWire(value.getPage())) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.PageResponse toWire(Transactions.PageResponse value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.PageResponse toWire(Transactions.PageResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.PageResponse.newBuilder();
        if (value.nextCursor().isPresent()) result.setNextCursor(budget.bytes(value.nextCursor().get()));
        result.setReturnedCount(budget.scalar(value.returnedCount()));
        result.setEncodedBytes(budget.scalar(value.encodedBytes()));
        return result.build();
    }

    static Transactions.PageResponse fromWire(latent.transaction.v1.Transaction.PageResponse value) {
        return new Transactions.PageResponse(
                value.hasNextCursor() ? Optional.of(value.getNextCursor().asReadOnlyByteBuffer()) : Optional.empty(),
                value.getReturnedCount(),
                value.getEncodedBytes());
    }

    static latent.transaction.v1.Transaction.ListEffectHistoryResponse toWire(Transactions.ListEffectHistoryResponse value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.ListEffectHistoryResponse toWire(Transactions.ListEffectHistoryResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.ListEffectHistoryResponse.newBuilder();
        for (var item : budget.list(value.receipts(), 128)) result.addReceipts(toWire(item, budget, depth + 1));
        if (value.page().isPresent()) result.setPage(toWire(value.page().get(), budget, depth + 1));
        return result.build();
    }

    static Transactions.ListEffectHistoryResponse fromWire(latent.transaction.v1.Transaction.ListEffectHistoryResponse value) {
        return new Transactions.ListEffectHistoryResponse(
                value.getReceiptsList().stream().map(item -> fromWire(item)).toList(),
                value.hasPage() ? Optional.of(fromWire(value.getPage())) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.LookupCommandResponse toWire(Transactions.LookupCommandResponse value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.LookupCommandResponse toWire(Transactions.LookupCommandResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.LookupCommandResponse.newBuilder();
        if (value.command().isPresent()) result.setCommand(toWire(value.command().get(), budget, depth + 1));
        return result.build();
    }

    static Transactions.LookupCommandResponse fromWire(latent.transaction.v1.Transaction.LookupCommandResponse value) {
        return new Transactions.LookupCommandResponse(
                value.hasCommand() ? Optional.of(fromWire(value.getCommand())) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.LookupCommitRequest toWire(Transactions.LookupCommitRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.LookupCommitRequest toWire(Transactions.LookupCommitRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.LookupCommitRequest.newBuilder();
        if (value.profile().isPresent()) result.setProfile(toWire(value.profile().get(), budget, depth + 1));
        if (value.command().isPresent()) result.setCommand(toWire(value.command().get(), budget, depth + 1));
        result.setReceiptId(budget.text(value.receiptId()));
        if (value.authorizationPublication().isPresent()) result.setAuthorizationPublication(Wire.toWire(value.authorizationPublication().get(), budget, depth + 1));
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
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.LookupCommitResponse toWire(Transactions.LookupCommitResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.LookupCommitResponse.newBuilder();
        if (value.command().isPresent()) result.setCommand(toWire(value.command().get(), budget, depth + 1));
        return result.build();
    }

    static Transactions.LookupCommitResponse fromWire(latent.transaction.v1.Transaction.LookupCommitResponse value) {
        return new Transactions.LookupCommitResponse(
                value.hasCommand() ? Optional.of(fromWire(value.getCommand())) : Optional.empty());
    }

    static latent.control.v1.State.NamespaceConfiguration toWire(Transactions.NamespaceConfiguration value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.State.NamespaceConfiguration toWire(Transactions.NamespaceConfiguration value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.State.NamespaceConfiguration.newBuilder();
        result.setStateSchema(budget.text(value.stateSchema()));
        if (value.quota().isPresent()) result.setQuota(toWire(value.quota().get(), budget, depth + 1));
        return result.build();
    }

    static Transactions.NamespaceConfiguration fromWire(latent.control.v1.State.NamespaceConfiguration value) {
        return new Transactions.NamespaceConfiguration(
                value.getStateSchema(),
                value.hasQuota() ? Optional.of(fromWire(value.getQuota())) : Optional.empty());
    }

    static latent.control.v1.State.MutateNamespaceRequest toWire(Transactions.MutateNamespaceRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.State.MutateNamespaceRequest toWire(Transactions.MutateNamespaceRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.State.MutateNamespaceRequest.newBuilder();
        if (value.namespace().isPresent()) result.setNamespace(toWire(value.namespace().get(), budget, depth + 1));
        result.setOperationId(budget.text(value.operationId()));
        result.setMutationValue(budget.scalar(value.mutation().value()));
        if (value.expectedGeneration().isPresent()) result.setExpectedGeneration(budget.scalar(value.expectedGeneration().get()));
        if (value.configuration().isPresent()) result.setConfiguration(toWire(value.configuration().get(), budget, depth + 1));
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
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.State.MutateNamespaceResponse toWire(Transactions.MutateNamespaceResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.State.MutateNamespaceResponse.newBuilder();
        if (value.receipt().isPresent()) result.setReceipt(toWire(value.receipt().get(), budget, depth + 1));
        result.setReplayed(budget.scalar(value.replayed()));
        if (value.auditAck().isPresent()) result.setAuditAck(Wire.toWire(value.auditAck().get(), budget, depth + 1));
        return result.build();
    }

    static Transactions.MutateNamespaceResponse fromWire(latent.control.v1.State.MutateNamespaceResponse value) {
        return new Transactions.MutateNamespaceResponse(
                value.hasReceipt() ? Optional.of(fromWire(value.getReceipt())) : Optional.empty(),
                value.getReplayed(),
                value.hasAuditAck() ? Optional.of(Wire.fromWire(value.getAuditAck())) : Optional.empty());
    }

    static latent.control.v1.State.MutateStateRequest toWire(Transactions.MutateStateRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.State.MutateStateRequest toWire(Transactions.MutateStateRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.State.MutateStateRequest.newBuilder();
        if (value.namespace().isPresent()) result.setNamespace(toWire(value.namespace().get(), budget, depth + 1));
        result.setOperationId(budget.text(value.operationId()));
        result.setMutationValue(budget.scalar(value.mutation().value()));
        if (value.recordId().isPresent()) result.setRecordId(budget.text(value.recordId().get()));
        result.setExpectedVersion(budget.bytes(value.expectedVersion()));
        result.setExpectedPolicyDigest(budget.text(value.expectedPolicyDigest()));
        result.setReason(budget.text(value.reason()));
        if (value.effectPlan().isPresent()) result.setEffectPlan(toWire(value.effectPlan().get(), budget, depth + 1));
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
                value.getReason(),
                value.hasEffectPlan() ? Optional.of(fromWire(value.getEffectPlan())) : Optional.empty());
    }

    static latent.control.v1.State.MutateStateResponse toWire(Transactions.MutateStateResponse value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.State.MutateStateResponse toWire(Transactions.MutateStateResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.State.MutateStateResponse.newBuilder();
        if (value.receipt().isPresent()) result.setReceipt(toWire(value.receipt().get(), budget, depth + 1));
        if (value.auditAck().isPresent()) result.setAuditAck(Wire.toWire(value.auditAck().get(), budget, depth + 1));
        result.setReplayed(budget.scalar(value.replayed()));
        return result.build();
    }

    static Transactions.MutateStateResponse fromWire(latent.control.v1.State.MutateStateResponse value) {
        return new Transactions.MutateStateResponse(
                value.hasReceipt() ? Optional.of(fromWire(value.getReceipt())) : Optional.empty(),
                value.hasAuditAck() ? Optional.of(Wire.fromWire(value.getAuditAck())) : Optional.empty(),
                value.getReplayed());
    }

    static latent.control.v1.State.PlanEffectMutationResponse toWire(Transactions.PlanEffectMutationResponse value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.State.PlanEffectMutationResponse toWire(Transactions.PlanEffectMutationResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.State.PlanEffectMutationResponse.newBuilder();
        if (value.plan().isPresent()) result.setPlan(toWire(value.plan().get(), budget, depth + 1));
        result.setReplayed(budget.scalar(value.replayed()));
        if (value.auditAck().isPresent()) result.setAuditAck(Wire.toWire(value.auditAck().get(), budget, depth + 1));
        return result.build();
    }

    static Transactions.PlanEffectMutationResponse fromWire(latent.control.v1.State.PlanEffectMutationResponse value) {
        return new Transactions.PlanEffectMutationResponse(
                value.hasPlan() ? Optional.of(fromWire(value.getPlan())) : Optional.empty(),
                value.getReplayed(),
                value.hasAuditAck() ? Optional.of(Wire.fromWire(value.getAuditAck())) : Optional.empty());
    }

    static latent.transaction.v1.Transaction.QueryRequest toWire(Transactions.QueryRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.QueryRequest toWire(Transactions.QueryRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.QueryRequest.newBuilder();
        if (value.profile().isPresent()) result.setProfile(toWire(value.profile().get(), budget, depth + 1));
        if (value.invocation().isPresent()) result.setInvocation(Wire.toWire(value.invocation().get(), budget, depth + 1));
        if (value.namespace().isPresent()) result.setNamespace(toWire(value.namespace().get(), budget, depth + 1));
        if (value.entity().isPresent()) result.setEntity(budget.text(value.entity().get()));
        if (value.minimumViewVersion().isPresent()) result.setMinimumViewVersion(budget.bytes(value.minimumViewVersion().get()));
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
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.transaction.v1.Transaction.QueryResponse toWire(Transactions.QueryResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.transaction.v1.Transaction.QueryResponse.newBuilder();
        if (value.invocation().isPresent()) result.setInvocation(Wire.toWire(value.invocation().get(), budget, depth + 1));
        if (value.view().isPresent()) result.setView(toWire(value.view().get(), budget, depth + 1));
        if (value.source().isPresent()) result.setSource(toWire(value.source().get(), budget, depth + 1));
        result.setObservedAtUnixMillis(budget.scalar(value.observedAtUnixMillis()));
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
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.State.SelectEntityRequest toWire(Transactions.SelectEntityRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.State.SelectEntityRequest.newBuilder();
        if (value.namespace().isPresent()) result.setNamespace(toWire(value.namespace().get(), budget, depth + 1));
        if (value.prefix().isPresent()) result.setPrefix(budget.bytes(value.prefix().get()));
        if (value.page().isPresent()) result.setPage(toWire(value.page().get(), budget, depth + 1));
        return result.build();
    }

    static Transactions.SelectEntityRequest fromWire(latent.control.v1.State.SelectEntityRequest value) {
        return new Transactions.SelectEntityRequest(
                value.hasNamespace() ? Optional.of(fromWire(value.getNamespace())) : Optional.empty(),
                value.hasPrefix() ? Optional.of(value.getPrefix().asReadOnlyByteBuffer()) : Optional.empty(),
                value.hasPage() ? Optional.of(fromWire(value.getPage())) : Optional.empty());
    }

    static latent.control.v1.State.SelectEntityResponse toWire(Transactions.SelectEntityResponse value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.State.SelectEntityResponse toWire(Transactions.SelectEntityResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.State.SelectEntityResponse.newBuilder();
        for (var item : budget.list(value.entities(), 128)) result.addEntities(toWire(item, budget, depth + 1));
        if (value.page().isPresent()) result.setPage(toWire(value.page().get(), budget, depth + 1));
        return result.build();
    }

    static Transactions.SelectEntityResponse fromWire(latent.control.v1.State.SelectEntityResponse value) {
        return new Transactions.SelectEntityResponse(
                value.getEntitiesList().stream().map(item -> fromWire(item)).toList(),
                value.hasPage() ? Optional.of(fromWire(value.getPage())) : Optional.empty());
    }

}
