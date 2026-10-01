// Generated from the authoritative transaction client descriptors.
package dev.latent.sdk;

import java.nio.ByteBuffer;
import java.util.List;
import java.util.Map;
import java.util.Optional;

public final class Transactions {
    private Transactions() { }

    public record CommandCancelDisposition(int value) {
        public static final CommandCancelDisposition UNSPECIFIED = new CommandCancelDisposition(0);
        public static final CommandCancelDisposition REQUESTED = new CommandCancelDisposition(1);
        public static final CommandCancelDisposition ALREADY_COMMITTED = new CommandCancelDisposition(2);
        public static final CommandCancelDisposition ALREADY_TERMINAL = new CommandCancelDisposition(3);
        public static final CommandCancelDisposition NOT_FOUND = new CommandCancelDisposition(4);
        public static final CommandCancelDisposition RECOVERY_REQUIRED = new CommandCancelDisposition(5);
    }

    public record CommandOutcome(int value) {
        public static final CommandOutcome UNSPECIFIED = new CommandOutcome(0);
        public static final CommandOutcome IN_PROGRESS = new CommandOutcome(1);
        public static final CommandOutcome COMMITTED = new CommandOutcome(2);
        public static final CommandOutcome REJECTED = new CommandOutcome(3);
        public static final CommandOutcome ABORTED = new CommandOutcome(4);
        public static final CommandOutcome UNKNOWN = new CommandOutcome(5);
        public static final CommandOutcome RECOVERY_REQUIRED = new CommandOutcome(6);
        public static final CommandOutcome EXPIRED = new CommandOutcome(7);
    }

    public record DispatcherAction(int value) {
        public static final DispatcherAction UNSPECIFIED = new DispatcherAction(0);
        public static final DispatcherAction PAUSE = new DispatcherAction(1);
        public static final DispatcherAction RESUME = new DispatcherAction(2);
    }

    public record DispatcherFailure(int value) {
        public static final DispatcherFailure UNSPECIFIED = new DispatcherFailure(0);
        public static final DispatcherFailure NONE = new DispatcherFailure(1);
        public static final DispatcherFailure AUTHORITY = new DispatcherFailure(2);
        public static final DispatcherFailure STORE = new DispatcherFailure(3);
        public static final DispatcherFailure WORKER = new DispatcherFailure(4);
        public static final DispatcherFailure RESTORE_CHECKPOINT = new DispatcherFailure(5);
        public static final DispatcherFailure ADMISSION_CLOSED = new DispatcherFailure(6);
        public static final DispatcherFailure CONFIGURATION = new DispatcherFailure(7);
    }

    public record DispatcherScope(int value) {
        public static final DispatcherScope UNSPECIFIED = new DispatcherScope(0);
        public static final DispatcherScope NODE = new DispatcherScope(1);
    }

    public record EffectDisposition(int value) {
        public static final EffectDisposition UNSPECIFIED = new EffectDisposition(0);
        public static final EffectDisposition PENDING = new EffectDisposition(1);
        public static final EffectDisposition DISPATCHING = new EffectDisposition(2);
        public static final EffectDisposition PROVIDER_ACKNOWLEDGED = new EffectDisposition(3);
        public static final EffectDisposition KNOWN_FAILURE = new EffectDisposition(4);
        public static final EffectDisposition UNCERTAIN_AFTER_DISPATCH = new EffectDisposition(5);
        public static final EffectDisposition EXPIRED = new EffectDisposition(6);
        public static final EffectDisposition POLICY_BLOCKED = new EffectDisposition(7);
        public static final EffectDisposition ADMINISTRATIVELY_TERMINATED = new EffectDisposition(8);
    }

    public record NamespaceMutationKind(int value) {
        public static final NamespaceMutationKind UNSPECIFIED = new NamespaceMutationKind(0);
        public static final NamespaceMutationKind CREATE = new NamespaceMutationKind(1);
        public static final NamespaceMutationKind QUIESCE = new NamespaceMutationKind(2);
        public static final NamespaceMutationKind RETIRE = new NamespaceMutationKind(3);
        public static final NamespaceMutationKind DESTROY = new NamespaceMutationKind(4);
        public static final NamespaceMutationKind RECREATE = new NamespaceMutationKind(5);
    }

    public record NamespaceStatus(int value) {
        public static final NamespaceStatus UNSPECIFIED = new NamespaceStatus(0);
        public static final NamespaceStatus ACTIVE = new NamespaceStatus(1);
        public static final NamespaceStatus QUIESCING = new NamespaceStatus(2);
        public static final NamespaceStatus RETIRED = new NamespaceStatus(3);
        public static final NamespaceStatus TOMBSTONE = new NamespaceStatus(4);
    }

    public record StateMutationKind(int value) {
        public static final StateMutationKind UNSPECIFIED = new StateMutationKind(0);
        public static final StateMutationKind RETRY_KNOWN_FAILED_EFFECT = new StateMutationKind(1);
        public static final StateMutationKind TERMINATE_EFFECT = new StateMutationKind(2);
        public static final StateMutationKind PURGE_EXPIRED_PAYLOAD = new StateMutationKind(3);
        public static final StateMutationKind CHECKPOINT_NAMESPACE = new StateMutationKind(4);
    }

    public record StateOperationDisposition(int value) {
        public static final StateOperationDisposition UNSPECIFIED = new StateOperationDisposition(0);
        public static final StateOperationDisposition COMMITTED = new StateOperationDisposition(1);
        public static final StateOperationDisposition CONFLICT = new StateOperationDisposition(2);
        public static final StateOperationDisposition REJECTED = new StateOperationDisposition(3);
        public static final StateOperationDisposition UNKNOWN = new StateOperationDisposition(4);
        public static final StateOperationDisposition RECOVERY_REQUIRED = new StateOperationDisposition(5);
    }

    public record AbortFence(
            String commandId,
            String attemptId,
            String transactionId,
            ByteBuffer ownerFence) { }

    public record TransactionProfile(
            String profile,
            String hostAbiDigest,
            String preparationProfileDigest) { }

    public record NamespaceSelector(
            String tenant,
            String namespace,
            String incarnation) { }

    public record CommandSelector(
            Optional<NamespaceSelector> namespace,
            String operation,
            Optional<String> entity,
            String clientKey,
            Optional<String> sharedRecoveryScope) { }

    public record LookupCommandRequest(
            Optional<TransactionProfile> profile,
            Optional<CommandSelector> command,
            Optional<String> attemptId,
            Optional<Management.PublicationRef> authorizationPublication) { }

    public record CancelCommandRequest(
            Optional<LookupCommandRequest> command,
            String reason) { }

    public record CommandKey(
            Optional<NamespaceSelector> namespace,
            String recoveryScope,
            String operation,
            Optional<String> entity,
            String clientKey) { }

    public record SourceIdentity(
            String publicationId,
            String revisionId,
            String releaseDigest,
            long routeGeneration,
            String contractDigest,
            String stateSchema,
            String inputFormat,
            String resultFormat,
            String componentDigest) { }

    public record CommitReceipt(
            String commandId,
            String attemptId,
            String transactionId,
            ByteBuffer committedVersion,
            long committedAtUnixMillis,
            List<String> effectIds,
            String receiptId,
            Optional<SourceIdentity> source) { }

    public record LinkedRetention(
            String recordFormat,
            int recordVersion,
            Optional<Long> payloadExpiresAtUnixMillis,
            Optional<Long> identityExpiresAtUnixMillis,
            Optional<Long> remainingRecoveryMillis,
            List<String> requiredRecordIds,
            boolean payloadAvailable) { }

    public record CommandInspection(
            Optional<CommandKey> key,
            String commandId,
            String attemptId,
            ByteBuffer fingerprintSha256,
            CommandOutcome outcome,
            boolean metadataDurable,
            boolean applicationStateCommitted,
            Optional<SourceIdentity> source,
            Optional<Management.Success> success,
            Optional<Management.DeclaredError> businessRejection,
            Optional<Management.PlatformError> technicalFailure,
            Optional<CommitReceipt> commit,
            Optional<AbortFence> provenAbort,
            Optional<LinkedRetention> retention,
            Optional<Management.PlatformError> cleanupFailure) { }

    public record CancelCommandResponse(
            CommandCancelDisposition disposition,
            Optional<CommandInspection> command) { }

    public record DispatcherGeneration(
            long ownerEpoch,
            long revision) { }

    public record ControlDispatcherRequest(
            Optional<TransactionProfile> profile,
            DispatcherScope scope,
            String operationId,
            DispatcherAction action,
            Optional<DispatcherGeneration> expectedGeneration) { }

    public record DispatcherOperationReceipt(
            String operationId,
            String receiptId,
            DispatcherAction action,
            String authenticatedOperator,
            String actorTenant,
            Optional<DispatcherGeneration> beforeGeneration,
            Optional<DispatcherGeneration> afterGeneration,
            long observedAtUnixMillis,
            boolean clockContinuityProven,
            boolean restoreReviewRequired,
            StateOperationDisposition disposition) { }

    public record ControlDispatcherResponse(
            Optional<DispatcherOperationReceipt> receipt,
            boolean replayed,
            boolean published,
            boolean paused,
            Optional<Management.AuditAck> auditAck) { }

    public record DispatcherSnapshot(
            Optional<DispatcherGeneration> generation,
            boolean paused,
            boolean pendingControl,
            boolean restoreReviewRequired,
            boolean admissionClosed,
            boolean quarantined,
            DispatcherFailure failure,
            long queued,
            long activeJobs,
            long retainedAttemptBytes,
            long liveWorkers,
            long acceptedEffects,
            long physicalOwners,
            long quarantinedPhysicalOwners,
            long commandOwners,
            long claims,
            long pendingEffects,
            long uncertainEffects,
            long blockedEffects,
            long deadLetterEffects,
            long countsObservedAtUnixMillis,
            boolean clockContinuityProven) { }

    public record EffectReceipt(
            String effectId,
            String commandId,
            String commandAttemptId,
            int dispatchAttempt,
            EffectDisposition disposition,
            Optional<String> providerReceipt,
            Optional<String> failureCode,
            long occurredAtUnixMillis,
            Optional<LinkedRetention> retention,
            Optional<String> managementOperationReceiptId,
            String providerProfile) { }

    public record EntityInspection(
            String entity,
            ByteBuffer version) { }

    public record ExpectedVersion(
            ByteBuffer key,
            Optional<Boolean> absent,
            Optional<ByteBuffer> version) { }

    public record GetDispatcherOperationRequest(
            Optional<ControlDispatcherRequest> original) { }

    public record GetDispatcherOperationResponse(
            Optional<DispatcherOperationReceipt> receipt,
            Optional<Management.AuditAck> auditAck) { }

    public record GetEffectRequest(
            Optional<TransactionProfile> profile,
            Optional<CommandSelector> command,
            String effectId,
            Optional<Management.PublicationRef> authorizationPublication) { }

    public record GetEffectResponse(
            Optional<EffectReceipt> effect) { }

    public record InspectNamespaceRequest(
            Optional<TransactionProfile> profile,
            Optional<NamespaceSelector> namespace,
            Optional<Management.PublicationRef> authorizationPublication) { }

    public record GetStateOperationReceiptRequest(
            Optional<InspectNamespaceRequest> namespace,
            String operationId) { }

    public record StateOperationReceipt(
            String operationId,
            String receiptId,
            StateMutationKind mutation,
            Optional<NamespaceSelector> namespace,
            String authenticatedOperator,
            ByteBuffer beforeVersion,
            ByteBuffer afterVersion,
            long completedAtUnixMillis,
            Optional<String> recordId,
            String policyDigest,
            StateOperationDisposition disposition) { }

    public record NamespaceOperationReceipt(
            String operationId,
            String receiptId,
            NamespaceMutationKind mutation,
            Optional<NamespaceSelector> namespace,
            String authenticatedOperator,
            Optional<Long> beforeGeneration,
            long afterGeneration,
            NamespaceStatus status,
            String stateSchema,
            StateOperationDisposition disposition) { }

    public record GetStateOperationReceiptResponse(
            Optional<StateOperationReceipt> receipt,
            Optional<NamespaceOperationReceipt> namespaceReceipt) { }

    public record InspectDispatcherRequest(
            Optional<TransactionProfile> profile,
            DispatcherScope scope) { }

    public record InspectDispatcherResponse(
            Optional<DispatcherSnapshot> dispatcher,
            Optional<Management.AuditAck> auditAck) { }

    public record ViewIdentity(
            Optional<NamespaceSelector> namespace,
            ByteBuffer version,
            String stateSchema) { }

    public record NamespaceQuota(
            long stateKeys,
            long stateBytes,
            long resultRows,
            long resultBytes,
            long effectRows,
            long effectBytes,
            long payloadBytes,
            long recoveryBytes) { }

    public record NamespaceInspection(
            Optional<ViewIdentity> view,
            long encodedStateBytes,
            long commandCount,
            long pendingEffectCount,
            List<LinkedRetention> retainedFormats,
            String engineProfile,
            String engineProfileDigest,
            NamespaceStatus status,
            Optional<NamespaceQuota> quota,
            long generation) { }

    public record InspectNamespaceResponse(
            Optional<NamespaceInspection> namespace) { }

    public record RetryAttempt(
            String requestId,
            Optional<AbortFence> expectedAbort) { }

    public record InvokeCommandRequest(
            Optional<TransactionProfile> profile,
            Optional<Management.InvokeRequest> invocation,
            Optional<CommandSelector> command,
            String inputFormat,
            List<ExpectedVersion> expectedVersions,
            Optional<RetryAttempt> retryAttempt) { }

    public record InvokeCommandResponse(
            Optional<Management.InvokeResponse> invocation,
            Optional<CommandInspection> command,
            boolean replayed) { }

    public record PageRequest(
            int limit,
            Optional<ByteBuffer> cursor) { }

    public record ListEffectHistoryRequest(
            Optional<GetEffectRequest> effect,
            Optional<PageRequest> page) { }

    public record PageResponse(
            Optional<ByteBuffer> nextCursor,
            int returnedCount,
            long encodedBytes) { }

    public record ListEffectHistoryResponse(
            List<EffectReceipt> receipts,
            Optional<PageResponse> page) { }

    public record LookupCommandResponse(
            Optional<CommandInspection> command) { }

    public record LookupCommitRequest(
            Optional<TransactionProfile> profile,
            Optional<CommandSelector> command,
            String receiptId,
            Optional<Management.PublicationRef> authorizationPublication) { }

    public record LookupCommitResponse(
            Optional<CommandInspection> command) { }

    public record NamespaceConfiguration(
            String stateSchema,
            Optional<NamespaceQuota> quota) { }

    public record MutateNamespaceRequest(
            Optional<InspectNamespaceRequest> namespace,
            String operationId,
            NamespaceMutationKind mutation,
            Optional<Long> expectedGeneration,
            Optional<NamespaceConfiguration> configuration) { }

    public record MutateNamespaceResponse(
            Optional<NamespaceOperationReceipt> receipt,
            boolean replayed,
            Optional<Management.AuditAck> auditAck) { }

    public record MutateStateRequest(
            Optional<InspectNamespaceRequest> namespace,
            String operationId,
            StateMutationKind mutation,
            Optional<String> recordId,
            ByteBuffer expectedVersion,
            String expectedPolicyDigest,
            String reason) { }

    public record MutateStateResponse(
            Optional<StateOperationReceipt> receipt,
            Optional<Management.AuditAck> auditAck) { }

    public record QueryRequest(
            Optional<TransactionProfile> profile,
            Optional<Management.InvokeRequest> invocation,
            Optional<NamespaceSelector> namespace,
            Optional<String> entity,
            Optional<ByteBuffer> minimumViewVersion) { }

    public record QueryResponse(
            Optional<Management.InvokeResponse> invocation,
            Optional<ViewIdentity> view,
            Optional<SourceIdentity> source,
            long observedAtUnixMillis) { }

    public record SelectEntityRequest(
            Optional<InspectNamespaceRequest> namespace,
            Optional<ByteBuffer> prefix,
            Optional<PageRequest> page) { }

    public record SelectEntityResponse(
            List<EntityInspection> entities,
            Optional<PageResponse> page) { }

    /** Constructs a protocol descriptor; this value grants no authority. */
    public static TransactionProfile currentProfile() {
        return new TransactionProfile("lsf-transaction-v1", "sha256:3b85f790f85ab23d36e492d7bd4a04a1b8aab87fc6f67dd7d7498bcf28129d35", "sha256:6acd7a248633dd01c9cdcbf8a1ed33fc5e6aa1d2edb09b7d89e53fda594b5507");
    }
}
