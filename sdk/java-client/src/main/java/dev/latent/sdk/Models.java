package dev.latent.sdk;

import java.nio.ByteBuffer;
import java.util.List;
import java.util.Map;
import java.util.Optional;

public final class Models {
    private Models() {
    }

    public record ResourceBudget(
            long cpuFuel,
            long memoryBytes,
            Optional<Long> wallTimeLimitMillis,
            int childCalls,
            int outboundRequests,
            long stateReadBytes,
            long stateWriteBytes,
            long blobReadBytes,
            long blobWriteBytes,
            long logBytes,
            int effectCount) {
    }

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
            int effectCount) {
    }

    public record InvocationTarget(
            String tenant,
            String service,
            String contract,
            String function,
            Optional<String> route) {
    }

    public record InvokeOptions(
            Optional<Long> deadlineUnixMillis,
            byte priority,
            Optional<String> idempotencyKey,
            ResourceBudget budget,
            Map<String, String> metadata) {
    }

    public record InvokeRequest(
            InvocationTarget target,
            ByteBuffer payload,
            String mediaType,
            InvokeOptions options) {
    }

    public record InvokeResponse(
            String activationId,
            String revisionId,
            String releaseDigest,
            long routeGeneration,
            ByteBuffer payload,
            String mediaType,
            Optional<String> committedStateVersion,
            List<String> effectIds,
            BudgetConsumption consumption,
            Map<String, String> metadata) {
    }

    public record PlatformFailure(
            String code,
            String message,
            boolean retryable,
            List<ErrorDetail> details) {
    }

    public record ErrorDetail(
            String kind,
            Map<String, String> fields) {
    }

    public record DeclaredError(
            String code,
            String message,
            ByteBuffer payload,
            String mediaType,
            Map<String, String> metadata) {
    }

    public record InvocationReceipt(
            String activationId,
            String revisionId,
            String releaseDigest,
            long routeGeneration,
            BudgetConsumption consumption) {
    }

    public sealed interface InvocationOutcome permits InvocationSuccess,
            DeclaredInvocationError, PlatformInvocationFailure {
    }

    public record InvocationSuccess(InvokeResponse response) implements InvocationOutcome {
    }

    public record DeclaredInvocationError(
            InvocationReceipt receipt,
            DeclaredError error) implements InvocationOutcome {
    }

    public record PlatformInvocationFailure(
            InvocationReceipt receipt,
            PlatformFailure error) implements InvocationOutcome {
    }

    public enum CancelDisposition {
        ACCEPTED,
        ALREADY_TERMINAL,
        NOT_FOUND
    }

    public record CancelResponse(
            CancelDisposition disposition,
            Optional<String> terminalState) {
    }

    public sealed interface RetainedInvocationOutcome permits ActivationSuccessSummary,
            RetainedDeclaredError, RetainedPlatformFailure {
    }

    public record ActivationSuccessSummary(
            Optional<String> committedStateVersion,
            List<String> effectIds,
            Map<String, String> metadata) implements RetainedInvocationOutcome {
    }

    public record RetainedDeclaredError(DeclaredError error) implements RetainedInvocationOutcome {
    }

    public record RetainedPlatformFailure(PlatformFailure error) implements RetainedInvocationOutcome {
    }

    public record ActivationStatus(
            String activationId,
            String phase,
            Optional<String> terminalState,
            Optional<RetainedInvocationOutcome> terminalOutcome,
            Optional<BudgetConsumption> finalConsumption,
            long lastUpdatedUnixMillis,
            Optional<Long> terminalAtUnixMillis,
            Map<String, String> metadata) {
    }
}
