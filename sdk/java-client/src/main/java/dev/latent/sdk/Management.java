package dev.latent.sdk;

import java.nio.ByteBuffer;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;

public final class Management {
    private Management() { }

    public record AuditAckStatus(int value) {
        public static final AuditAckStatus UNSPECIFIED = new AuditAckStatus(0);
        public static final AuditAckStatus DURABLE = new AuditAckStatus(1);
        public static final AuditAckStatus OUTCOME_UNKNOWN = new AuditAckStatus(2);
        public static final AuditAckStatus AUDIT_UNAVAILABLE = new AuditAckStatus(3);
        public static final AuditAckStatus DISABLED = new AuditAckStatus(4);
    }

    public record CancelDisposition(int value) {
        public static final CancelDisposition UNSPECIFIED = new CancelDisposition(0);
        public static final CancelDisposition ACCEPTED = new CancelDisposition(1);
        public static final CancelDisposition ALREADY_TERMINAL = new CancelDisposition(2);
        public static final CancelDisposition NOT_FOUND = new CancelDisposition(3);
    }

    public record CapabilityPolicyRecordKind(int value) {
        public static final CapabilityPolicyRecordKind UNSPECIFIED = new CapabilityPolicyRecordKind(0);
        public static final CapabilityPolicyRecordKind POLICY = new CapabilityPolicyRecordKind(1);
        public static final CapabilityPolicyRecordKind PROVIDER_BINDING = new CapabilityPolicyRecordKind(2);
    }

    public record FailureCategory(int value) {
        public static final FailureCategory UNSPECIFIED = new FailureCategory(0);
        public static final FailureCategory LOCAL_CANCELLED = new FailureCategory(1);
        public static final FailureCategory DEADLINE = new FailureCategory(2);
        public static final FailureCategory TRANSPORT = new FailureCategory(3);
        public static final FailureCategory RPC = new FailureCategory(4);
        public static final FailureCategory DECODE = new FailureCategory(5);
        public static final FailureCategory LIMIT = new FailureCategory(6);
        public static final FailureCategory INVALID_REQUEST = new FailureCategory(7);
    }

    public record OutcomeKnowledge(int value) {
        public static final OutcomeKnowledge UNSPECIFIED = new OutcomeKnowledge(0);
        public static final OutcomeKnowledge NOT_DISPATCHED = new OutcomeKnowledge(1);
        public static final OutcomeKnowledge UNKNOWN = new OutcomeKnowledge(2);
        public static final OutcomeKnowledge OBSERVED = new OutcomeKnowledge(3);
    }

    public record ResourceBudget(
            long cpuFuel,
            long memoryBytes,
            int childCalls,
            int outboundRequests,
            long stateReadBytes,
            long stateWriteBytes,
            long blobReadBytes,
            long blobWriteBytes,
            long logBytes,
            int effectCount,
            Optional<Long> wallTimeLimitMillis) { }

    public record ErrorDetail(
            String kind,
            Map<String, String> fields) { }

    public record PlatformError(
            String code,
            String message,
            boolean retryable,
            List<ErrorDetail> detailItems) { }

    public record ObjectMetadata(
            String name,
            Optional<String> tenant,
            Optional<String> namespace,
            Map<String, String> labels,
            Map<String, String> annotations) { }

    public record PageRequest(
            int pageSize,
            Optional<String> pageToken) { }

    public record PageResponse(
            Optional<String> nextPageToken) { }

    public record AuditAck(
            AuditAckStatus status,
            Optional<Long> attemptSequence) { }

    public record InvocationTarget(
            String tenant,
            String service,
            String contract,
            String function,
            Optional<String> route) { }

    public record InvokeRequest(
            Optional<String> activationId,
            Optional<String> parentActivationId,
            Optional<String> rootActivationId,
            Optional<InvocationTarget> target,
            ByteBuffer payload,
            String mediaType,
            Optional<Long> deadlineUnixMillis,
            int priority,
            Optional<String> idempotencyKey,
            Optional<ResourceBudget> budget,
            Map<String, String> metadata) { }

    public record BudgetConsumption(
            long cpuFuel,
            long peakMemoryBytes,
            long wallTimeMicros,
            int childCalls,
            int outboundRequests,
            long stateReadBytes,
            long stateWriteBytes,
            long blobReadBytes,
            long blobWriteBytes,
            long logBytes,
            int effectCount) { }

    public record Success(
            ByteBuffer payload,
            String mediaType,
            Optional<String> committedStateVersion,
            List<String> effectIds,
            Map<String, String> metadata) { }

    public record DeclaredError(
            String code,
            String message,
            ByteBuffer payload,
            String mediaType,
            Map<String, String> metadata) { }

    public record InvokeResponse(
            String activationId,
            String revisionId,
            String releaseDigest,
            long routeGeneration,
            Optional<Success> success,
            Optional<DeclaredError> declaredError,
            Optional<PlatformError> platformFailure,
            Optional<BudgetConsumption> consumption,
            Optional<String> publicationId) { }

    public record CancelRequest(
            String activationId,
            String reason) { }

    public record CancelResponse(
            CancelDisposition disposition,
            Optional<String> terminalState) { }

    public record GetActivationRequest(
            String activationId) { }

    public record ActivationSuccessSummary(
            Optional<String> committedStateVersion,
            List<String> effectIds,
            Map<String, String> metadata) { }

    public record ActivationStatus(
            String activationId,
            String phase,
            Optional<String> terminalState,
            long lastUpdatedUnixMillis,
            Map<String, String> metadata,
            Optional<ActivationSuccessSummary> succeeded,
            Optional<DeclaredError> declaredError,
            Optional<PlatformError> platformFailure,
            Optional<BudgetConsumption> finalConsumption,
            Optional<Long> terminalAtUnixMillis) { }

    public record Policy(
            String id,
            Optional<ObjectMetadata> metadata,
            String document,
            long generation,
            String language,
            CapabilityPolicyRecordKind recordKind,
            String contentDigest,
            boolean revoked) { }

    public record ApplyPolicyRequest(
            Optional<Policy> policy,
            Optional<Long> expectedGeneration,
            String operationId) { }

    public record CapabilityPolicyOperation(
            String operationId,
            String tenant,
            String id,
            CapabilityPolicyRecordKind recordKind,
            long generation,
            String contentDigest,
            boolean revoked) { }

    public record ApplyPolicyResponse(
            Optional<Policy> policy,
            Optional<CapabilityPolicyOperation> receipt) { }

    public record GetPolicyRequest(
            String id,
            CapabilityPolicyRecordKind recordKind) { }

    public record GetPolicyResponse(
            Optional<Policy> policy) { }

    public record GetPolicyOperationRequest(
            String operationId) { }

    public record GetPolicyOperationResponse(
            Optional<CapabilityPolicyOperation> receipt) { }

    public record ListPoliciesRequest(
            CapabilityPolicyRecordKind recordKind,
            Optional<PageRequest> page) { }

    public record ListPoliciesResponse(
            List<Policy> policies,
            long catalogGeneration,
            Optional<PageResponse> page) { }

    public record CapabilityInspectionPolicy(
            String id,
            long revision,
            String digest) { }

    public record CapabilityBindingInspection(
            Optional<String> definitionDigest,
            Optional<CapabilityInspectionPolicy> providerBinding,
            List<CapabilityInspectionPolicy> policies,
            String providerProfile,
            String providerConfigurationDigest,
            long providerConfigurationEpoch,
            String state) { }

    public record CapabilityDescriptor(
            String id,
            String contract,
            String provider,
            List<String> operations,
            Map<String, String> attributes,
            Optional<CapabilityBindingInspection> inspection) { }

    public record ListCapabilitiesRequest(
            Optional<String> contractPrefix,
            Optional<String> provider,
            Optional<PageRequest> page,
            String deploymentId,
            boolean includeNodeUsage) { }

    public record CapabilityInspectionRevision(
            String deploymentId,
            String revisionId,
            String componentDigest,
            Optional<String> publicationId,
            long routeGeneration,
            long catalogTransaction) { }

    public record CapabilityResourceUsage(
            String scope,
            Map<String, Long> counters,
            List<String> unavailable) { }

    public record ListCapabilitiesResponse(
            List<CapabilityDescriptor> capabilities,
            Optional<PageResponse> page,
            Optional<CapabilityInspectionRevision> revision,
            Optional<CapabilityResourceUsage> tenantUsage,
            Optional<CapabilityResourceUsage> nodeUsage,
            String state) { }

    public record CapabilityInspectionCeiling(
            int operations,
            long inputBytes,
            long outputBytes,
            long wallTimeMillis) { }

    public record PublicationRef(
            String id,
            String tenant) { }

    public record ReleaseSelector(
            Optional<String> componentDigest,
            Optional<PublicationRef> publication) { }

    public record PublicationIdentity(
            PublicationRef publication,
            String componentDigest,
            String packageDigest) { }

    public record CallOptions(
            Optional<Long> timeoutMillis) { }

    public record RequestIdentity(
            Optional<String> activationId,
            Optional<String> operationId) { }

    public record UnsupportedWireValue(
            String field,
            String value) { }

    public record ResponseMetadata(
            RequestIdentity identity,
            OutcomeKnowledge outcome,
            Optional<AuditAck> auditAck,
            Optional<String> auditStatus,
            Optional<Long> auditAttemptSequence) { }

    public record ClientFailure(
            FailureCategory category,
            String message,
            Optional<Integer> grpcStatus,
            Optional<PlatformError> platformError,
            boolean dispatched,
            OutcomeKnowledge outcome,
            RequestIdentity identity,
            Optional<AuditAck> auditAck,
            Optional<String> auditStatus,
            Optional<UnsupportedWireValue> unsupportedWireValue,
            Optional<Long> auditAttemptSequence) { }

    public record ClientResponse<Response>(Response value, ResponseMetadata metadata) { }

    public interface ClientProfile {
        CompletableFuture<ClientResponse<InvokeResponse>> invoke(
                InvokeRequest request, CallOptions options);

        CompletableFuture<ClientResponse<CancelResponse>> cancel(
                CancelRequest request, CallOptions options);

        CompletableFuture<ClientResponse<ActivationStatus>> getActivation(
                GetActivationRequest request, CallOptions options);

        CompletableFuture<ClientResponse<GetPolicyResponse>> getPolicy(
                GetPolicyRequest request, CallOptions options);

        CompletableFuture<ClientResponse<ListPoliciesResponse>> listPolicies(
                ListPoliciesRequest request, CallOptions options);

        CompletableFuture<ClientResponse<ListCapabilitiesResponse>> listCapabilities(
                ListCapabilitiesRequest request, CallOptions options);

        CompletableFuture<ClientResponse<ApplyPolicyResponse>> applyPolicy(
                ApplyPolicyRequest request, CallOptions options);

        CompletableFuture<ClientResponse<GetPolicyOperationResponse>> getPolicyOperation(
                GetPolicyOperationRequest request, CallOptions options);

    }

    public static final class ClientException extends RuntimeException {
        private static final long serialVersionUID = 1L;
        private final ClientFailure failure;

        public ClientException(ClientFailure failure) {
            super(failure.message());
            this.failure = failure;
        }

        public ClientFailure failure() { return failure; }
    }

    public static final class ClientCancellationException extends java.util.concurrent.CancellationException {
        private static final long serialVersionUID = 1L;
        private final ClientFailure failure;

        public ClientCancellationException(ClientFailure failure) {
            super(failure.message());
            this.failure = failure;
        }

        public ClientFailure failure() { return failure; }
    }

    public static Optional<ClientFailure> clientFailure(Throwable failure) {
        for (int depth = 0; failure != null && depth < 8; depth++) {
            if (failure instanceof ClientException typed) return Optional.of(typed.failure());
            if (failure instanceof ClientCancellationException typed) return Optional.of(typed.failure());
            failure = failure.getCause();
        }
        return Optional.empty();
    }

    public static long parseU64Decimal(String value) {
        if (!value.matches("0|[1-9][0-9]{0,19}")) throw new NumberFormatException("invalid uint64 decimal");
        return Long.parseUnsignedLong(value);
    }

    public static String formatU64Decimal(long value) { return Long.toUnsignedString(value); }
}
