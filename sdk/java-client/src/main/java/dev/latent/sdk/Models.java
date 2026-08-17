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
            Optional<Long> wallDeadlineUnixMillis,
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
            Map<String, String> details) {
    }
}
