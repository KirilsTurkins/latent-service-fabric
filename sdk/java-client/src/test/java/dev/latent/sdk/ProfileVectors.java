package dev.latent.sdk;

import java.nio.ByteBuffer;
import java.util.List;
import java.util.Map;
import java.util.Optional;

final class ProfileVectors {
    private ProfileVectors() { }
    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    static void run() {
        {
            Management.InvokeRequest value = new Management.InvokeRequest(Optional.empty(), Optional.empty(), Optional.empty(), Optional.of(new Management.InvocationTarget("tenant-a", "echo", "example:echo/api@1.0.0", "echo", Optional.empty())), ByteBuffer.wrap(new byte[]{(byte)0, (byte)1, (byte)2, (byte)255}), "application/octet-stream", Optional.empty(), Integer.parseUnsignedInt("0"), Optional.empty(), Optional.of(new Management.ResourceBudget(Long.parseUnsignedLong("18446744073709551615"), Long.parseUnsignedLong("9223372036854775808"), Integer.parseUnsignedInt("0"), Integer.parseUnsignedInt("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Integer.parseUnsignedInt("0"), Optional.empty())), Map.ofEntries(Map.entry("trace", "redacted")));
            check(!(value.activationId().isPresent()), "invoke-absent-identity-and-deadlines.activation_id.presence");
            check(!(value.parentActivationId().isPresent()), "invoke-absent-identity-and-deadlines.parent_activation_id.presence");
            check(!(value.rootActivationId().isPresent()), "invoke-absent-identity-and-deadlines.root_activation_id.presence");
            check(value.target().isPresent(), "invoke-absent-identity-and-deadlines.target.presence");
            check(value.target().get().tenant().equals("tenant-a"), "invoke-absent-identity-and-deadlines.target.tenant");
            check(value.target().get().service().equals("echo"), "invoke-absent-identity-and-deadlines.target.service");
            check(value.target().get().contract().equals("example:echo/api@1.0.0"), "invoke-absent-identity-and-deadlines.target.contract");
            check(value.target().get().function().equals("echo"), "invoke-absent-identity-and-deadlines.target.function");
            check(!(value.target().get().route().isPresent()), "invoke-absent-identity-and-deadlines.target.route.presence");
            check(value.payload().remaining() == 4, "invoke-absent-identity-and-deadlines.payload.length");
            check((value.payload().get(0) & 255) == 0, "invoke-absent-identity-and-deadlines.payload.0");
            check((value.payload().get(1) & 255) == 1, "invoke-absent-identity-and-deadlines.payload.1");
            check((value.payload().get(2) & 255) == 2, "invoke-absent-identity-and-deadlines.payload.2");
            check((value.payload().get(3) & 255) == 255, "invoke-absent-identity-and-deadlines.payload.3");
            check(value.mediaType().equals("application/octet-stream"), "invoke-absent-identity-and-deadlines.media_type");
            check(!(value.deadlineUnixMillis().isPresent()), "invoke-absent-identity-and-deadlines.deadline_unix_millis.presence");
            check(value.priority() == Integer.parseUnsignedInt("0"), "invoke-absent-identity-and-deadlines.priority");
            check(!(value.idempotencyKey().isPresent()), "invoke-absent-identity-and-deadlines.idempotency_key.presence");
            check(value.budget().isPresent(), "invoke-absent-identity-and-deadlines.budget.presence");
            check(value.budget().get().cpuFuel() == Long.parseUnsignedLong("18446744073709551615"), "invoke-absent-identity-and-deadlines.budget.cpu_fuel");
            check(value.budget().get().memoryBytes() == Long.parseUnsignedLong("9223372036854775808"), "invoke-absent-identity-and-deadlines.budget.memory_bytes");
            check(value.budget().get().childCalls() == Integer.parseUnsignedInt("0"), "invoke-absent-identity-and-deadlines.budget.child_calls");
            check(value.budget().get().outboundRequests() == Integer.parseUnsignedInt("0"), "invoke-absent-identity-and-deadlines.budget.outbound_requests");
            check(value.budget().get().stateReadBytes() == Long.parseUnsignedLong("0"), "invoke-absent-identity-and-deadlines.budget.state_read_bytes");
            check(value.budget().get().stateWriteBytes() == Long.parseUnsignedLong("0"), "invoke-absent-identity-and-deadlines.budget.state_write_bytes");
            check(value.budget().get().blobReadBytes() == Long.parseUnsignedLong("0"), "invoke-absent-identity-and-deadlines.budget.blob_read_bytes");
            check(value.budget().get().blobWriteBytes() == Long.parseUnsignedLong("0"), "invoke-absent-identity-and-deadlines.budget.blob_write_bytes");
            check(value.budget().get().logBytes() == Long.parseUnsignedLong("0"), "invoke-absent-identity-and-deadlines.budget.log_bytes");
            check(value.budget().get().effectCount() == Integer.parseUnsignedInt("0"), "invoke-absent-identity-and-deadlines.budget.effect_count");
            check(!(value.budget().get().wallTimeLimitMillis().isPresent()), "invoke-absent-identity-and-deadlines.budget.wall_time_limit_millis.presence");
            check(value.metadata().size() == 1, "invoke-absent-identity-and-deadlines.metadata.count");
            check(value.metadata().get("trace").equals("redacted"), "invoke-absent-identity-and-deadlines.metadata.0");
        }
        {
            Management.InvokeRequest value = new Management.InvokeRequest(Optional.of(""), Optional.of("parent-a"), Optional.of(""), Optional.of(new Management.InvocationTarget("", "", "", "", Optional.of(""))), ByteBuffer.wrap(new byte[]{}), "", Optional.of(Long.parseUnsignedLong("0")), Integer.parseUnsignedInt("0"), Optional.of(""), Optional.of(new Management.ResourceBudget(Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Integer.parseUnsignedInt("0"), Integer.parseUnsignedInt("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Integer.parseUnsignedInt("0"), Optional.of(Long.parseUnsignedLong("0")))), Map.ofEntries());
            check(value.activationId().isPresent(), "invoke-present-invalid-and-zero-not-absence.activation_id.presence");
            check(value.activationId().get().equals(""), "invoke-present-invalid-and-zero-not-absence.activation_id");
            check(value.parentActivationId().isPresent(), "invoke-present-invalid-and-zero-not-absence.parent_activation_id.presence");
            check(value.parentActivationId().get().equals("parent-a"), "invoke-present-invalid-and-zero-not-absence.parent_activation_id");
            check(value.rootActivationId().isPresent(), "invoke-present-invalid-and-zero-not-absence.root_activation_id.presence");
            check(value.rootActivationId().get().equals(""), "invoke-present-invalid-and-zero-not-absence.root_activation_id");
            check(value.target().isPresent(), "invoke-present-invalid-and-zero-not-absence.target.presence");
            check(value.target().get().tenant().equals(""), "invoke-present-invalid-and-zero-not-absence.target.tenant");
            check(value.target().get().service().equals(""), "invoke-present-invalid-and-zero-not-absence.target.service");
            check(value.target().get().contract().equals(""), "invoke-present-invalid-and-zero-not-absence.target.contract");
            check(value.target().get().function().equals(""), "invoke-present-invalid-and-zero-not-absence.target.function");
            check(value.target().get().route().isPresent(), "invoke-present-invalid-and-zero-not-absence.target.route.presence");
            check(value.target().get().route().get().equals(""), "invoke-present-invalid-and-zero-not-absence.target.route");
            check(value.payload().remaining() == 0, "invoke-present-invalid-and-zero-not-absence.payload.length");
            check(value.mediaType().equals(""), "invoke-present-invalid-and-zero-not-absence.media_type");
            check(value.deadlineUnixMillis().isPresent(), "invoke-present-invalid-and-zero-not-absence.deadline_unix_millis.presence");
            check(value.deadlineUnixMillis().get() == Long.parseUnsignedLong("0"), "invoke-present-invalid-and-zero-not-absence.deadline_unix_millis");
            check(value.priority() == Integer.parseUnsignedInt("0"), "invoke-present-invalid-and-zero-not-absence.priority");
            check(value.idempotencyKey().isPresent(), "invoke-present-invalid-and-zero-not-absence.idempotency_key.presence");
            check(value.idempotencyKey().get().equals(""), "invoke-present-invalid-and-zero-not-absence.idempotency_key");
            check(value.budget().isPresent(), "invoke-present-invalid-and-zero-not-absence.budget.presence");
            check(value.budget().get().cpuFuel() == Long.parseUnsignedLong("0"), "invoke-present-invalid-and-zero-not-absence.budget.cpu_fuel");
            check(value.budget().get().memoryBytes() == Long.parseUnsignedLong("0"), "invoke-present-invalid-and-zero-not-absence.budget.memory_bytes");
            check(value.budget().get().childCalls() == Integer.parseUnsignedInt("0"), "invoke-present-invalid-and-zero-not-absence.budget.child_calls");
            check(value.budget().get().outboundRequests() == Integer.parseUnsignedInt("0"), "invoke-present-invalid-and-zero-not-absence.budget.outbound_requests");
            check(value.budget().get().stateReadBytes() == Long.parseUnsignedLong("0"), "invoke-present-invalid-and-zero-not-absence.budget.state_read_bytes");
            check(value.budget().get().stateWriteBytes() == Long.parseUnsignedLong("0"), "invoke-present-invalid-and-zero-not-absence.budget.state_write_bytes");
            check(value.budget().get().blobReadBytes() == Long.parseUnsignedLong("0"), "invoke-present-invalid-and-zero-not-absence.budget.blob_read_bytes");
            check(value.budget().get().blobWriteBytes() == Long.parseUnsignedLong("0"), "invoke-present-invalid-and-zero-not-absence.budget.blob_write_bytes");
            check(value.budget().get().logBytes() == Long.parseUnsignedLong("0"), "invoke-present-invalid-and-zero-not-absence.budget.log_bytes");
            check(value.budget().get().effectCount() == Integer.parseUnsignedInt("0"), "invoke-present-invalid-and-zero-not-absence.budget.effect_count");
            check(value.budget().get().wallTimeLimitMillis().isPresent(), "invoke-present-invalid-and-zero-not-absence.budget.wall_time_limit_millis.presence");
            check(value.budget().get().wallTimeLimitMillis().get() == Long.parseUnsignedLong("0"), "invoke-present-invalid-and-zero-not-absence.budget.wall_time_limit_millis");
            check(value.metadata().size() == 0, "invoke-present-invalid-and-zero-not-absence.metadata.count");
        }
        {
            Management.InvokeRequest value = new Management.InvokeRequest(Optional.of("activation-a"), Optional.of("parent-a"), Optional.of("root-a"), Optional.empty(), ByteBuffer.wrap(new byte[]{}), "", Optional.of(Long.parseUnsignedLong("18446744073709551615")), Integer.parseUnsignedInt("4294967295"), Optional.of("not-an-authority-or-retry-key"), Optional.empty(), Map.ofEntries());
            check(value.activationId().isPresent(), "invoke-known-identity-full-width-deadline-and-priority.activation_id.presence");
            check(value.activationId().get().equals("activation-a"), "invoke-known-identity-full-width-deadline-and-priority.activation_id");
            check(value.parentActivationId().isPresent(), "invoke-known-identity-full-width-deadline-and-priority.parent_activation_id.presence");
            check(value.parentActivationId().get().equals("parent-a"), "invoke-known-identity-full-width-deadline-and-priority.parent_activation_id");
            check(value.rootActivationId().isPresent(), "invoke-known-identity-full-width-deadline-and-priority.root_activation_id.presence");
            check(value.rootActivationId().get().equals("root-a"), "invoke-known-identity-full-width-deadline-and-priority.root_activation_id");
            check(!(value.target().isPresent()), "invoke-known-identity-full-width-deadline-and-priority.target.presence");
            check(value.payload().remaining() == 0, "invoke-known-identity-full-width-deadline-and-priority.payload.length");
            check(value.mediaType().equals(""), "invoke-known-identity-full-width-deadline-and-priority.media_type");
            check(value.deadlineUnixMillis().isPresent(), "invoke-known-identity-full-width-deadline-and-priority.deadline_unix_millis.presence");
            check(value.deadlineUnixMillis().get() == Long.parseUnsignedLong("18446744073709551615"), "invoke-known-identity-full-width-deadline-and-priority.deadline_unix_millis");
            check(value.priority() == Integer.parseUnsignedInt("4294967295"), "invoke-known-identity-full-width-deadline-and-priority.priority");
            check(value.idempotencyKey().isPresent(), "invoke-known-identity-full-width-deadline-and-priority.idempotency_key.presence");
            check(value.idempotencyKey().get().equals("not-an-authority-or-retry-key"), "invoke-known-identity-full-width-deadline-and-priority.idempotency_key");
            check(!(value.budget().isPresent()), "invoke-known-identity-full-width-deadline-and-priority.budget.presence");
            check(value.metadata().size() == 0, "invoke-known-identity-full-width-deadline-and-priority.metadata.count");
        }
        {
            Management.ResourceBudget value = new Management.ResourceBudget(Long.parseUnsignedLong("18446744073709551615"), Long.parseUnsignedLong("18446744073709551615"), Integer.parseUnsignedInt("4294967295"), Integer.parseUnsignedInt("4294967295"), Long.parseUnsignedLong("18446744073709551615"), Long.parseUnsignedLong("18446744073709551615"), Long.parseUnsignedLong("18446744073709551615"), Long.parseUnsignedLong("18446744073709551615"), Long.parseUnsignedLong("18446744073709551615"), Integer.parseUnsignedInt("4294967295"), Optional.of(Long.parseUnsignedLong("18446744073709551615")));
            check(value.cpuFuel() == Long.parseUnsignedLong("18446744073709551615"), "full-resource-budget.cpu_fuel");
            check(value.memoryBytes() == Long.parseUnsignedLong("18446744073709551615"), "full-resource-budget.memory_bytes");
            check(value.childCalls() == Integer.parseUnsignedInt("4294967295"), "full-resource-budget.child_calls");
            check(value.outboundRequests() == Integer.parseUnsignedInt("4294967295"), "full-resource-budget.outbound_requests");
            check(value.stateReadBytes() == Long.parseUnsignedLong("18446744073709551615"), "full-resource-budget.state_read_bytes");
            check(value.stateWriteBytes() == Long.parseUnsignedLong("18446744073709551615"), "full-resource-budget.state_write_bytes");
            check(value.blobReadBytes() == Long.parseUnsignedLong("18446744073709551615"), "full-resource-budget.blob_read_bytes");
            check(value.blobWriteBytes() == Long.parseUnsignedLong("18446744073709551615"), "full-resource-budget.blob_write_bytes");
            check(value.logBytes() == Long.parseUnsignedLong("18446744073709551615"), "full-resource-budget.log_bytes");
            check(value.effectCount() == Integer.parseUnsignedInt("4294967295"), "full-resource-budget.effect_count");
            check(value.wallTimeLimitMillis().isPresent(), "full-resource-budget.wall_time_limit_millis.presence");
            check(value.wallTimeLimitMillis().get() == Long.parseUnsignedLong("18446744073709551615"), "full-resource-budget.wall_time_limit_millis");
        }
        {
            Management.InvokeResponse value = new Management.InvokeResponse("activation-a", "revision-a", "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", Long.parseUnsignedLong("18446744073709551615"), Optional.of(new Management.Success(ByteBuffer.wrap(new byte[]{(byte)0, (byte)1, (byte)2, (byte)255}), "application/octet-stream", Optional.of(""), List.of("effect-a", "effect-b"), Map.ofEntries(Map.entry("result", "redacted")))), Optional.empty(), Optional.empty(), Optional.of(new Management.BudgetConsumption(Long.parseUnsignedLong("18446744073709551615"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("9007199254740993"), Integer.parseUnsignedInt("0"), Integer.parseUnsignedInt("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Integer.parseUnsignedInt("0"))), Optional.of("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111"));
            check(value.activationId().equals("activation-a"), "invoke-success-retains-publication-and-component.activation_id");
            check(value.revisionId().equals("revision-a"), "invoke-success-retains-publication-and-component.revision_id");
            check(value.releaseDigest().equals("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), "invoke-success-retains-publication-and-component.release_digest");
            check(value.routeGeneration() == Long.parseUnsignedLong("18446744073709551615"), "invoke-success-retains-publication-and-component.route_generation");
            check(value.success().isPresent(), "invoke-success-retains-publication-and-component.success.presence");
            check(value.success().get().payload().remaining() == 4, "invoke-success-retains-publication-and-component.success.payload.length");
            check((value.success().get().payload().get(0) & 255) == 0, "invoke-success-retains-publication-and-component.success.payload.0");
            check((value.success().get().payload().get(1) & 255) == 1, "invoke-success-retains-publication-and-component.success.payload.1");
            check((value.success().get().payload().get(2) & 255) == 2, "invoke-success-retains-publication-and-component.success.payload.2");
            check((value.success().get().payload().get(3) & 255) == 255, "invoke-success-retains-publication-and-component.success.payload.3");
            check(value.success().get().mediaType().equals("application/octet-stream"), "invoke-success-retains-publication-and-component.success.media_type");
            check(value.success().get().committedStateVersion().isPresent(), "invoke-success-retains-publication-and-component.success.committed_state_version.presence");
            check(value.success().get().committedStateVersion().get().equals(""), "invoke-success-retains-publication-and-component.success.committed_state_version");
            check(value.success().get().effectIds().size() == 2, "invoke-success-retains-publication-and-component.success.effect_ids.count");
            check(value.success().get().effectIds().get(0).equals("effect-a"), "invoke-success-retains-publication-and-component.success.effect_ids.0");
            check(value.success().get().effectIds().get(1).equals("effect-b"), "invoke-success-retains-publication-and-component.success.effect_ids.1");
            check(value.success().get().metadata().size() == 1, "invoke-success-retains-publication-and-component.success.metadata.count");
            check(value.success().get().metadata().get("result").equals("redacted"), "invoke-success-retains-publication-and-component.success.metadata.0");
            check(!(value.declaredError().isPresent()), "invoke-success-retains-publication-and-component.declared_error.presence");
            check(!(value.platformFailure().isPresent()), "invoke-success-retains-publication-and-component.platform_failure.presence");
            check(value.consumption().isPresent(), "invoke-success-retains-publication-and-component.consumption.presence");
            check(value.consumption().get().cpuFuel() == Long.parseUnsignedLong("18446744073709551615"), "invoke-success-retains-publication-and-component.consumption.cpu_fuel");
            check(value.consumption().get().peakMemoryBytes() == Long.parseUnsignedLong("0"), "invoke-success-retains-publication-and-component.consumption.peak_memory_bytes");
            check(value.consumption().get().wallTimeMicros() == Long.parseUnsignedLong("9007199254740993"), "invoke-success-retains-publication-and-component.consumption.wall_time_micros");
            check(value.consumption().get().childCalls() == Integer.parseUnsignedInt("0"), "invoke-success-retains-publication-and-component.consumption.child_calls");
            check(value.consumption().get().outboundRequests() == Integer.parseUnsignedInt("0"), "invoke-success-retains-publication-and-component.consumption.outbound_requests");
            check(value.consumption().get().stateReadBytes() == Long.parseUnsignedLong("0"), "invoke-success-retains-publication-and-component.consumption.state_read_bytes");
            check(value.consumption().get().stateWriteBytes() == Long.parseUnsignedLong("0"), "invoke-success-retains-publication-and-component.consumption.state_write_bytes");
            check(value.consumption().get().blobReadBytes() == Long.parseUnsignedLong("0"), "invoke-success-retains-publication-and-component.consumption.blob_read_bytes");
            check(value.consumption().get().blobWriteBytes() == Long.parseUnsignedLong("0"), "invoke-success-retains-publication-and-component.consumption.blob_write_bytes");
            check(value.consumption().get().logBytes() == Long.parseUnsignedLong("0"), "invoke-success-retains-publication-and-component.consumption.log_bytes");
            check(value.consumption().get().effectCount() == Integer.parseUnsignedInt("0"), "invoke-success-retains-publication-and-component.consumption.effect_count");
            check(value.publicationId().isPresent(), "invoke-success-retains-publication-and-component.publication_id.presence");
            check(value.publicationId().get().equals("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111"), "invoke-success-retains-publication-and-component.publication_id");
        }
        {
            Management.InvokeResponse value = new Management.InvokeResponse("activation-a", "revision-a", "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", Long.parseUnsignedLong("9223372036854775808"), Optional.empty(), Optional.of(new Management.DeclaredError("uncertain", "provider outcome unknown", ByteBuffer.wrap(new byte[]{(byte)0, (byte)1, (byte)2, (byte)255}), "application/octet-stream", Map.ofEntries(Map.entry("contract", "latent:http/streaming@0.3.0")))), Optional.empty(), Optional.of(new Management.BudgetConsumption(Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Integer.parseUnsignedInt("0"), Integer.parseUnsignedInt("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("18446744073709551615"), Long.parseUnsignedLong("0"), Integer.parseUnsignedInt("0"))), Optional.of("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111"));
            check(value.activationId().equals("activation-a"), "typed-declared-provider-uncertainty-retains-receipt.activation_id");
            check(value.revisionId().equals("revision-a"), "typed-declared-provider-uncertainty-retains-receipt.revision_id");
            check(value.releaseDigest().equals("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), "typed-declared-provider-uncertainty-retains-receipt.release_digest");
            check(value.routeGeneration() == Long.parseUnsignedLong("9223372036854775808"), "typed-declared-provider-uncertainty-retains-receipt.route_generation");
            check(!(value.success().isPresent()), "typed-declared-provider-uncertainty-retains-receipt.success.presence");
            check(value.declaredError().isPresent(), "typed-declared-provider-uncertainty-retains-receipt.declared_error.presence");
            check(value.declaredError().get().code().equals("uncertain"), "typed-declared-provider-uncertainty-retains-receipt.declared_error.code");
            check(value.declaredError().get().message().equals("provider outcome unknown"), "typed-declared-provider-uncertainty-retains-receipt.declared_error.message");
            check(value.declaredError().get().payload().remaining() == 4, "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.length");
            check((value.declaredError().get().payload().get(0) & 255) == 0, "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.0");
            check((value.declaredError().get().payload().get(1) & 255) == 1, "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.1");
            check((value.declaredError().get().payload().get(2) & 255) == 2, "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.2");
            check((value.declaredError().get().payload().get(3) & 255) == 255, "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.3");
            check(value.declaredError().get().mediaType().equals("application/octet-stream"), "typed-declared-provider-uncertainty-retains-receipt.declared_error.media_type");
            check(value.declaredError().get().metadata().size() == 1, "typed-declared-provider-uncertainty-retains-receipt.declared_error.metadata.count");
            check(value.declaredError().get().metadata().get("contract").equals("latent:http/streaming@0.3.0"), "typed-declared-provider-uncertainty-retains-receipt.declared_error.metadata.0");
            check(!(value.platformFailure().isPresent()), "typed-declared-provider-uncertainty-retains-receipt.platform_failure.presence");
            check(value.consumption().isPresent(), "typed-declared-provider-uncertainty-retains-receipt.consumption.presence");
            check(value.consumption().get().cpuFuel() == Long.parseUnsignedLong("0"), "typed-declared-provider-uncertainty-retains-receipt.consumption.cpu_fuel");
            check(value.consumption().get().peakMemoryBytes() == Long.parseUnsignedLong("0"), "typed-declared-provider-uncertainty-retains-receipt.consumption.peak_memory_bytes");
            check(value.consumption().get().wallTimeMicros() == Long.parseUnsignedLong("0"), "typed-declared-provider-uncertainty-retains-receipt.consumption.wall_time_micros");
            check(value.consumption().get().childCalls() == Integer.parseUnsignedInt("0"), "typed-declared-provider-uncertainty-retains-receipt.consumption.child_calls");
            check(value.consumption().get().outboundRequests() == Integer.parseUnsignedInt("0"), "typed-declared-provider-uncertainty-retains-receipt.consumption.outbound_requests");
            check(value.consumption().get().stateReadBytes() == Long.parseUnsignedLong("0"), "typed-declared-provider-uncertainty-retains-receipt.consumption.state_read_bytes");
            check(value.consumption().get().stateWriteBytes() == Long.parseUnsignedLong("0"), "typed-declared-provider-uncertainty-retains-receipt.consumption.state_write_bytes");
            check(value.consumption().get().blobReadBytes() == Long.parseUnsignedLong("0"), "typed-declared-provider-uncertainty-retains-receipt.consumption.blob_read_bytes");
            check(value.consumption().get().blobWriteBytes() == Long.parseUnsignedLong("18446744073709551615"), "typed-declared-provider-uncertainty-retains-receipt.consumption.blob_write_bytes");
            check(value.consumption().get().logBytes() == Long.parseUnsignedLong("0"), "typed-declared-provider-uncertainty-retains-receipt.consumption.log_bytes");
            check(value.consumption().get().effectCount() == Integer.parseUnsignedInt("0"), "typed-declared-provider-uncertainty-retains-receipt.consumption.effect_count");
            check(value.publicationId().isPresent(), "typed-declared-provider-uncertainty-retains-receipt.publication_id.presence");
            check(value.publicationId().get().equals("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111"), "typed-declared-provider-uncertainty-retains-receipt.publication_id");
        }
        {
            Management.InvokeResponse value = new Management.InvokeResponse("activation-a", "", "", Long.parseUnsignedLong("0"), Optional.empty(), Optional.empty(), Optional.of(new Management.PlatformError("permission-denied", "capability-provider-failed", false, List.of(new Management.ErrorDetail("capability-observation", Map.ofEntries(Map.entry("capability", "latent:http/streaming@0.3.0"), Map.entry("state", "policy-revoked"))), new Management.ErrorDetail("future-detail", Map.ofEntries(Map.entry("bounded", "preserved")))))), Optional.of(new Management.BudgetConsumption(Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Integer.parseUnsignedInt("0"), Integer.parseUnsignedInt("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("18446744073709551615"), Integer.parseUnsignedInt("0"))), Optional.empty());
            check(value.activationId().equals("activation-a"), "typed-platform-capability-failure-retains-detail-items.activation_id");
            check(value.revisionId().equals(""), "typed-platform-capability-failure-retains-detail-items.revision_id");
            check(value.releaseDigest().equals(""), "typed-platform-capability-failure-retains-detail-items.release_digest");
            check(value.routeGeneration() == Long.parseUnsignedLong("0"), "typed-platform-capability-failure-retains-detail-items.route_generation");
            check(!(value.success().isPresent()), "typed-platform-capability-failure-retains-detail-items.success.presence");
            check(!(value.declaredError().isPresent()), "typed-platform-capability-failure-retains-detail-items.declared_error.presence");
            check(value.platformFailure().isPresent(), "typed-platform-capability-failure-retains-detail-items.platform_failure.presence");
            check(value.platformFailure().get().code().equals("permission-denied"), "typed-platform-capability-failure-retains-detail-items.platform_failure.code");
            check(value.platformFailure().get().message().equals("capability-provider-failed"), "typed-platform-capability-failure-retains-detail-items.platform_failure.message");
            check(value.platformFailure().get().retryable() == false, "typed-platform-capability-failure-retains-detail-items.platform_failure.retryable");
            check(value.platformFailure().get().detailItems().size() == 2, "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.count");
            check(value.platformFailure().get().detailItems().get(0).kind().equals("capability-observation"), "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.kind");
            check(value.platformFailure().get().detailItems().get(0).fields().size() == 2, "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.fields.count");
            check(value.platformFailure().get().detailItems().get(0).fields().get("capability").equals("latent:http/streaming@0.3.0"), "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.fields.0");
            check(value.platformFailure().get().detailItems().get(0).fields().get("state").equals("policy-revoked"), "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.fields.1");
            check(value.platformFailure().get().detailItems().get(1).kind().equals("future-detail"), "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.1.kind");
            check(value.platformFailure().get().detailItems().get(1).fields().size() == 1, "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.1.fields.count");
            check(value.platformFailure().get().detailItems().get(1).fields().get("bounded").equals("preserved"), "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.1.fields.0");
            check(value.consumption().isPresent(), "typed-platform-capability-failure-retains-detail-items.consumption.presence");
            check(value.consumption().get().cpuFuel() == Long.parseUnsignedLong("0"), "typed-platform-capability-failure-retains-detail-items.consumption.cpu_fuel");
            check(value.consumption().get().peakMemoryBytes() == Long.parseUnsignedLong("0"), "typed-platform-capability-failure-retains-detail-items.consumption.peak_memory_bytes");
            check(value.consumption().get().wallTimeMicros() == Long.parseUnsignedLong("0"), "typed-platform-capability-failure-retains-detail-items.consumption.wall_time_micros");
            check(value.consumption().get().childCalls() == Integer.parseUnsignedInt("0"), "typed-platform-capability-failure-retains-detail-items.consumption.child_calls");
            check(value.consumption().get().outboundRequests() == Integer.parseUnsignedInt("0"), "typed-platform-capability-failure-retains-detail-items.consumption.outbound_requests");
            check(value.consumption().get().stateReadBytes() == Long.parseUnsignedLong("0"), "typed-platform-capability-failure-retains-detail-items.consumption.state_read_bytes");
            check(value.consumption().get().stateWriteBytes() == Long.parseUnsignedLong("0"), "typed-platform-capability-failure-retains-detail-items.consumption.state_write_bytes");
            check(value.consumption().get().blobReadBytes() == Long.parseUnsignedLong("0"), "typed-platform-capability-failure-retains-detail-items.consumption.blob_read_bytes");
            check(value.consumption().get().blobWriteBytes() == Long.parseUnsignedLong("0"), "typed-platform-capability-failure-retains-detail-items.consumption.blob_write_bytes");
            check(value.consumption().get().logBytes() == Long.parseUnsignedLong("18446744073709551615"), "typed-platform-capability-failure-retains-detail-items.consumption.log_bytes");
            check(value.consumption().get().effectCount() == Integer.parseUnsignedInt("0"), "typed-platform-capability-failure-retains-detail-items.consumption.effect_count");
            check(!(value.publicationId().isPresent()), "typed-platform-capability-failure-retains-detail-items.publication_id.presence");
        }
        {
            Management.InvokeResponse value = new Management.InvokeResponse("activation-a", "", "", Long.parseUnsignedLong("0"), Optional.of(new Management.Success(ByteBuffer.wrap(new byte[]{}), "", Optional.empty(), List.of(), Map.ofEntries())), Optional.empty(), Optional.empty(), Optional.empty(), Optional.of(""));
            check(value.activationId().equals("activation-a"), "present-invalid-publication-not-legacy.activation_id");
            check(value.revisionId().equals(""), "present-invalid-publication-not-legacy.revision_id");
            check(value.releaseDigest().equals(""), "present-invalid-publication-not-legacy.release_digest");
            check(value.routeGeneration() == Long.parseUnsignedLong("0"), "present-invalid-publication-not-legacy.route_generation");
            check(value.success().isPresent(), "present-invalid-publication-not-legacy.success.presence");
            check(value.success().get().payload().remaining() == 0, "present-invalid-publication-not-legacy.success.payload.length");
            check(value.success().get().mediaType().equals(""), "present-invalid-publication-not-legacy.success.media_type");
            check(!(value.success().get().committedStateVersion().isPresent()), "present-invalid-publication-not-legacy.success.committed_state_version.presence");
            check(value.success().get().effectIds().size() == 0, "present-invalid-publication-not-legacy.success.effect_ids.count");
            check(value.success().get().metadata().size() == 0, "present-invalid-publication-not-legacy.success.metadata.count");
            check(!(value.declaredError().isPresent()), "present-invalid-publication-not-legacy.declared_error.presence");
            check(!(value.platformFailure().isPresent()), "present-invalid-publication-not-legacy.platform_failure.presence");
            check(!(value.consumption().isPresent()), "present-invalid-publication-not-legacy.consumption.presence");
            check(value.publicationId().isPresent(), "present-invalid-publication-not-legacy.publication_id.presence");
            check(value.publicationId().get().equals(""), "present-invalid-publication-not-legacy.publication_id");
        }
        {
            Management.InvokeResponse value = new Management.InvokeResponse("activation-a", "", "", Long.parseUnsignedLong("0"), Optional.of(new Management.Success(ByteBuffer.wrap(new byte[]{}), "", Optional.empty(), List.of(), Map.ofEntries())), Optional.empty(), Optional.of(new Management.PlatformError("internal", "", false, List.of())), Optional.empty(), Optional.empty());
            check(value.activationId().equals("activation-a"), "contradictory-outcome-retained-for-rejection.activation_id");
            check(value.revisionId().equals(""), "contradictory-outcome-retained-for-rejection.revision_id");
            check(value.releaseDigest().equals(""), "contradictory-outcome-retained-for-rejection.release_digest");
            check(value.routeGeneration() == Long.parseUnsignedLong("0"), "contradictory-outcome-retained-for-rejection.route_generation");
            check(value.success().isPresent(), "contradictory-outcome-retained-for-rejection.success.presence");
            check(value.success().get().payload().remaining() == 0, "contradictory-outcome-retained-for-rejection.success.payload.length");
            check(value.success().get().mediaType().equals(""), "contradictory-outcome-retained-for-rejection.success.media_type");
            check(!(value.success().get().committedStateVersion().isPresent()), "contradictory-outcome-retained-for-rejection.success.committed_state_version.presence");
            check(value.success().get().effectIds().size() == 0, "contradictory-outcome-retained-for-rejection.success.effect_ids.count");
            check(value.success().get().metadata().size() == 0, "contradictory-outcome-retained-for-rejection.success.metadata.count");
            check(!(value.declaredError().isPresent()), "contradictory-outcome-retained-for-rejection.declared_error.presence");
            check(value.platformFailure().isPresent(), "contradictory-outcome-retained-for-rejection.platform_failure.presence");
            check(value.platformFailure().get().code().equals("internal"), "contradictory-outcome-retained-for-rejection.platform_failure.code");
            check(value.platformFailure().get().message().equals(""), "contradictory-outcome-retained-for-rejection.platform_failure.message");
            check(value.platformFailure().get().retryable() == false, "contradictory-outcome-retained-for-rejection.platform_failure.retryable");
            check(value.platformFailure().get().detailItems().size() == 0, "contradictory-outcome-retained-for-rejection.platform_failure.detail_items.count");
            check(!(value.consumption().isPresent()), "contradictory-outcome-retained-for-rejection.consumption.presence");
            check(!(value.publicationId().isPresent()), "contradictory-outcome-retained-for-rejection.publication_id.presence");
        }
        {
            Management.CancelRequest value = new Management.CancelRequest("activation-a", "caller-requested");
            check(value.activationId().equals("activation-a"), "cancel-request-known-id.activation_id");
            check(value.reason().equals("caller-requested"), "cancel-request-known-id.reason");
        }
        {
            Management.CancelResponse value = new Management.CancelResponse(new Management.CancelDisposition(1), Optional.empty());
            check(value.disposition().value() == 1, "cancel-accepted-not-cleanup.disposition");
            check(!(value.terminalState().isPresent()), "cancel-accepted-not-cleanup.terminal_state.presence");
        }
        {
            Management.CancelResponse value = new Management.CancelResponse(new Management.CancelDisposition(2), Optional.of("completed"));
            check(value.disposition().value() == 2, "cancel-already-terminal.disposition");
            check(value.terminalState().isPresent(), "cancel-already-terminal.terminal_state.presence");
            check(value.terminalState().get().equals("completed"), "cancel-already-terminal.terminal_state");
        }
        {
            Management.CancelResponse value = new Management.CancelResponse(new Management.CancelDisposition(3), Optional.empty());
            check(value.disposition().value() == 3, "cancel-not-found-not-nonexecution.disposition");
            check(!(value.terminalState().isPresent()), "cancel-not-found-not-nonexecution.terminal_state.presence");
        }
        {
            Management.CancelResponse value = new Management.CancelResponse(new Management.CancelDisposition(0), Optional.of(""));
            check(value.disposition().value() == 0, "cancel-unspecified-not-accepted.disposition");
            check(value.terminalState().isPresent(), "cancel-unspecified-not-accepted.terminal_state.presence");
            check(value.terminalState().get().equals(""), "cancel-unspecified-not-accepted.terminal_state");
        }
        {
            Management.CancelResponse value = new Management.CancelResponse(new Management.CancelDisposition(91), Optional.of("future-terminal-state"));
            check(value.disposition().value() == 91, "cancel-unknown-enum.disposition");
            check(value.terminalState().isPresent(), "cancel-unknown-enum.terminal_state.presence");
            check(value.terminalState().get().equals("future-terminal-state"), "cancel-unknown-enum.terminal_state");
        }
        {
            Management.CancelResponse value = new Management.CancelResponse(new Management.CancelDisposition(-2147483648), Optional.empty());
            check(value.disposition().value() == -2147483648, "cancel-negative-enum.disposition");
            check(!(value.terminalState().isPresent()), "cancel-negative-enum.terminal_state.presence");
        }
        {
            Management.GetActivationRequest value = new Management.GetActivationRequest("activation-a");
            check(value.activationId().equals("activation-a"), "get-activation-recovery.activation_id");
        }
        {
            Management.ActivationStatus value = new Management.ActivationStatus("activation-a", "running", Optional.empty(), Long.parseUnsignedLong("18446744073709551615"), Map.ofEntries(), Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty());
            check(value.activationId().equals("activation-a"), "activation-running-absent-terminal.activation_id");
            check(value.phase().equals("running"), "activation-running-absent-terminal.phase");
            check(!(value.terminalState().isPresent()), "activation-running-absent-terminal.terminal_state.presence");
            check(value.lastUpdatedUnixMillis() == Long.parseUnsignedLong("18446744073709551615"), "activation-running-absent-terminal.last_updated_unix_millis");
            check(value.metadata().size() == 0, "activation-running-absent-terminal.metadata.count");
            check(!(value.succeeded().isPresent()), "activation-running-absent-terminal.succeeded.presence");
            check(!(value.declaredError().isPresent()), "activation-running-absent-terminal.declared_error.presence");
            check(!(value.platformFailure().isPresent()), "activation-running-absent-terminal.platform_failure.presence");
            check(!(value.finalConsumption().isPresent()), "activation-running-absent-terminal.final_consumption.presence");
            check(!(value.terminalAtUnixMillis().isPresent()), "activation-running-absent-terminal.terminal_at_unix_millis.presence");
        }
        {
            Management.ActivationStatus value = new Management.ActivationStatus("activation-a", "terminal", Optional.of("failed"), Long.parseUnsignedLong("0"), Map.ofEntries(), Optional.empty(), Optional.empty(), Optional.of(new Management.PlatformError("resource-exhausted", "capability-capacity", false, List.of(new Management.ErrorDetail("budget", Map.ofEntries(Map.entry("resource", "buffer-bytes")))))), Optional.of(new Management.BudgetConsumption(Long.parseUnsignedLong("0"), Long.parseUnsignedLong("18446744073709551615"), Long.parseUnsignedLong("0"), Integer.parseUnsignedInt("0"), Integer.parseUnsignedInt("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Integer.parseUnsignedInt("0"))), Optional.of(Long.parseUnsignedLong("0")));
            check(value.activationId().equals("activation-a"), "activation-terminal-typed-failure.activation_id");
            check(value.phase().equals("terminal"), "activation-terminal-typed-failure.phase");
            check(value.terminalState().isPresent(), "activation-terminal-typed-failure.terminal_state.presence");
            check(value.terminalState().get().equals("failed"), "activation-terminal-typed-failure.terminal_state");
            check(value.lastUpdatedUnixMillis() == Long.parseUnsignedLong("0"), "activation-terminal-typed-failure.last_updated_unix_millis");
            check(value.metadata().size() == 0, "activation-terminal-typed-failure.metadata.count");
            check(!(value.succeeded().isPresent()), "activation-terminal-typed-failure.succeeded.presence");
            check(!(value.declaredError().isPresent()), "activation-terminal-typed-failure.declared_error.presence");
            check(value.platformFailure().isPresent(), "activation-terminal-typed-failure.platform_failure.presence");
            check(value.platformFailure().get().code().equals("resource-exhausted"), "activation-terminal-typed-failure.platform_failure.code");
            check(value.platformFailure().get().message().equals("capability-capacity"), "activation-terminal-typed-failure.platform_failure.message");
            check(value.platformFailure().get().retryable() == false, "activation-terminal-typed-failure.platform_failure.retryable");
            check(value.platformFailure().get().detailItems().size() == 1, "activation-terminal-typed-failure.platform_failure.detail_items.count");
            check(value.platformFailure().get().detailItems().get(0).kind().equals("budget"), "activation-terminal-typed-failure.platform_failure.detail_items.0.kind");
            check(value.platformFailure().get().detailItems().get(0).fields().size() == 1, "activation-terminal-typed-failure.platform_failure.detail_items.0.fields.count");
            check(value.platformFailure().get().detailItems().get(0).fields().get("resource").equals("buffer-bytes"), "activation-terminal-typed-failure.platform_failure.detail_items.0.fields.0");
            check(value.finalConsumption().isPresent(), "activation-terminal-typed-failure.final_consumption.presence");
            check(value.finalConsumption().get().cpuFuel() == Long.parseUnsignedLong("0"), "activation-terminal-typed-failure.final_consumption.cpu_fuel");
            check(value.finalConsumption().get().peakMemoryBytes() == Long.parseUnsignedLong("18446744073709551615"), "activation-terminal-typed-failure.final_consumption.peak_memory_bytes");
            check(value.finalConsumption().get().wallTimeMicros() == Long.parseUnsignedLong("0"), "activation-terminal-typed-failure.final_consumption.wall_time_micros");
            check(value.finalConsumption().get().childCalls() == Integer.parseUnsignedInt("0"), "activation-terminal-typed-failure.final_consumption.child_calls");
            check(value.finalConsumption().get().outboundRequests() == Integer.parseUnsignedInt("0"), "activation-terminal-typed-failure.final_consumption.outbound_requests");
            check(value.finalConsumption().get().stateReadBytes() == Long.parseUnsignedLong("0"), "activation-terminal-typed-failure.final_consumption.state_read_bytes");
            check(value.finalConsumption().get().stateWriteBytes() == Long.parseUnsignedLong("0"), "activation-terminal-typed-failure.final_consumption.state_write_bytes");
            check(value.finalConsumption().get().blobReadBytes() == Long.parseUnsignedLong("0"), "activation-terminal-typed-failure.final_consumption.blob_read_bytes");
            check(value.finalConsumption().get().blobWriteBytes() == Long.parseUnsignedLong("0"), "activation-terminal-typed-failure.final_consumption.blob_write_bytes");
            check(value.finalConsumption().get().logBytes() == Long.parseUnsignedLong("0"), "activation-terminal-typed-failure.final_consumption.log_bytes");
            check(value.finalConsumption().get().effectCount() == Integer.parseUnsignedInt("0"), "activation-terminal-typed-failure.final_consumption.effect_count");
            check(value.terminalAtUnixMillis().isPresent(), "activation-terminal-typed-failure.terminal_at_unix_millis.presence");
            check(value.terminalAtUnixMillis().get() == Long.parseUnsignedLong("0"), "activation-terminal-typed-failure.terminal_at_unix_millis");
        }
        {
            Management.ActivationStatus value = new Management.ActivationStatus("activation-a", "terminal", Optional.of("completed"), Long.parseUnsignedLong("0"), Map.ofEntries(), Optional.of(new Management.ActivationSuccessSummary(Optional.of("state-a"), List.of("effect-a"), Map.ofEntries(Map.entry("retained", "true")))), Optional.empty(), Optional.empty(), Optional.of(new Management.BudgetConsumption(Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Integer.parseUnsignedInt("0"), Integer.parseUnsignedInt("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("0"), Integer.parseUnsignedInt("4294967295"))), Optional.of(Long.parseUnsignedLong("18446744073709551615")));
            check(value.activationId().equals("activation-a"), "activation-terminal-success-summary.activation_id");
            check(value.phase().equals("terminal"), "activation-terminal-success-summary.phase");
            check(value.terminalState().isPresent(), "activation-terminal-success-summary.terminal_state.presence");
            check(value.terminalState().get().equals("completed"), "activation-terminal-success-summary.terminal_state");
            check(value.lastUpdatedUnixMillis() == Long.parseUnsignedLong("0"), "activation-terminal-success-summary.last_updated_unix_millis");
            check(value.metadata().size() == 0, "activation-terminal-success-summary.metadata.count");
            check(value.succeeded().isPresent(), "activation-terminal-success-summary.succeeded.presence");
            check(value.succeeded().get().committedStateVersion().isPresent(), "activation-terminal-success-summary.succeeded.committed_state_version.presence");
            check(value.succeeded().get().committedStateVersion().get().equals("state-a"), "activation-terminal-success-summary.succeeded.committed_state_version");
            check(value.succeeded().get().effectIds().size() == 1, "activation-terminal-success-summary.succeeded.effect_ids.count");
            check(value.succeeded().get().effectIds().get(0).equals("effect-a"), "activation-terminal-success-summary.succeeded.effect_ids.0");
            check(value.succeeded().get().metadata().size() == 1, "activation-terminal-success-summary.succeeded.metadata.count");
            check(value.succeeded().get().metadata().get("retained").equals("true"), "activation-terminal-success-summary.succeeded.metadata.0");
            check(!(value.declaredError().isPresent()), "activation-terminal-success-summary.declared_error.presence");
            check(!(value.platformFailure().isPresent()), "activation-terminal-success-summary.platform_failure.presence");
            check(value.finalConsumption().isPresent(), "activation-terminal-success-summary.final_consumption.presence");
            check(value.finalConsumption().get().cpuFuel() == Long.parseUnsignedLong("0"), "activation-terminal-success-summary.final_consumption.cpu_fuel");
            check(value.finalConsumption().get().peakMemoryBytes() == Long.parseUnsignedLong("0"), "activation-terminal-success-summary.final_consumption.peak_memory_bytes");
            check(value.finalConsumption().get().wallTimeMicros() == Long.parseUnsignedLong("0"), "activation-terminal-success-summary.final_consumption.wall_time_micros");
            check(value.finalConsumption().get().childCalls() == Integer.parseUnsignedInt("0"), "activation-terminal-success-summary.final_consumption.child_calls");
            check(value.finalConsumption().get().outboundRequests() == Integer.parseUnsignedInt("0"), "activation-terminal-success-summary.final_consumption.outbound_requests");
            check(value.finalConsumption().get().stateReadBytes() == Long.parseUnsignedLong("0"), "activation-terminal-success-summary.final_consumption.state_read_bytes");
            check(value.finalConsumption().get().stateWriteBytes() == Long.parseUnsignedLong("0"), "activation-terminal-success-summary.final_consumption.state_write_bytes");
            check(value.finalConsumption().get().blobReadBytes() == Long.parseUnsignedLong("0"), "activation-terminal-success-summary.final_consumption.blob_read_bytes");
            check(value.finalConsumption().get().blobWriteBytes() == Long.parseUnsignedLong("0"), "activation-terminal-success-summary.final_consumption.blob_write_bytes");
            check(value.finalConsumption().get().logBytes() == Long.parseUnsignedLong("0"), "activation-terminal-success-summary.final_consumption.log_bytes");
            check(value.finalConsumption().get().effectCount() == Integer.parseUnsignedInt("4294967295"), "activation-terminal-success-summary.final_consumption.effect_count");
            check(value.terminalAtUnixMillis().isPresent(), "activation-terminal-success-summary.terminal_at_unix_millis.presence");
            check(value.terminalAtUnixMillis().get() == Long.parseUnsignedLong("18446744073709551615"), "activation-terminal-success-summary.terminal_at_unix_millis");
        }
        {
            Management.GetPolicyResponse value = new Management.GetPolicyResponse(Optional.empty());
            check(!(value.policy().isPresent()), "policy-absence.policy.presence");
        }
        {
            Management.GetPolicyRequest value = new Management.GetPolicyRequest("policy-a", new Management.CapabilityPolicyRecordKind(1));
            check(value.id().equals("policy-a"), "policy-record-kind.id");
            check(value.recordKind().value() == 1, "policy-record-kind.record_kind");
        }
        {
            Management.GetPolicyRequest value = new Management.GetPolicyRequest("binding-a", new Management.CapabilityPolicyRecordKind(2));
            check(value.id().equals("binding-a"), "provider-binding-record-kind.id");
            check(value.recordKind().value() == 2, "provider-binding-record-kind.record_kind");
        }
        {
            Management.Policy value = new Management.Policy("future-record", Optional.of(new Management.ObjectMetadata("future-record", Optional.of(""), Optional.of(""), Map.ofEntries(Map.entry("sampled", "true")), Map.ofEntries(Map.entry("descriptive", "not-authority")))), "", Long.parseUnsignedLong("18446744073709551615"), "", new Management.CapabilityPolicyRecordKind(2147483647), "", true);
            check(value.id().equals("future-record"), "unknown-policy-kind.id");
            check(value.metadata().isPresent(), "unknown-policy-kind.metadata.presence");
            check(value.metadata().get().name().equals("future-record"), "unknown-policy-kind.metadata.name");
            check(value.metadata().get().tenant().isPresent(), "unknown-policy-kind.metadata.tenant.presence");
            check(value.metadata().get().tenant().get().equals(""), "unknown-policy-kind.metadata.tenant");
            check(value.metadata().get().namespace().isPresent(), "unknown-policy-kind.metadata.namespace.presence");
            check(value.metadata().get().namespace().get().equals(""), "unknown-policy-kind.metadata.namespace");
            check(value.metadata().get().labels().size() == 1, "unknown-policy-kind.metadata.labels.count");
            check(value.metadata().get().labels().get("sampled").equals("true"), "unknown-policy-kind.metadata.labels.0");
            check(value.metadata().get().annotations().size() == 1, "unknown-policy-kind.metadata.annotations.count");
            check(value.metadata().get().annotations().get("descriptive").equals("not-authority"), "unknown-policy-kind.metadata.annotations.0");
            check(value.document().equals(""), "unknown-policy-kind.document");
            check(value.generation() == Long.parseUnsignedLong("18446744073709551615"), "unknown-policy-kind.generation");
            check(value.language().equals(""), "unknown-policy-kind.language");
            check(value.recordKind().value() == 2147483647, "unknown-policy-kind.record_kind");
            check(value.contentDigest().equals(""), "unknown-policy-kind.content_digest");
            check(value.revoked() == true, "unknown-policy-kind.revoked");
        }
        {
            Management.ApplyPolicyRequest value = new Management.ApplyPolicyRequest(Optional.empty(), Optional.empty(), "operation-a");
            check(!(value.policy().isPresent()), "apply-missing-generation.policy.presence");
            check(!(value.expectedGeneration().isPresent()), "apply-missing-generation.expected_generation.presence");
            check(value.operationId().equals("operation-a"), "apply-missing-generation.operation_id");
        }
        {
            Management.ApplyPolicyRequest value = new Management.ApplyPolicyRequest(Optional.empty(), Optional.of(Long.parseUnsignedLong("0")), "");
            check(!(value.policy().isPresent()), "apply-present-empty-operation.policy.presence");
            check(value.expectedGeneration().isPresent(), "apply-present-empty-operation.expected_generation.presence");
            check(value.expectedGeneration().get() == Long.parseUnsignedLong("0"), "apply-present-empty-operation.expected_generation");
            check(value.operationId().equals(""), "apply-present-empty-operation.operation_id");
        }
        {
            Management.ApplyPolicyRequest value = new Management.ApplyPolicyRequest(Optional.of(new Management.Policy("policy-a", Optional.of(new Management.ObjectMetadata("policy-a", Optional.of("tenant-a"), Optional.empty(), Map.ofEntries(), Map.ofEntries())), "{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"rules\":[{\"id\":\"deny\",\"effect\":\"deny\",\"principals\":[{\"kind\":\"user\",\"subject\":\"fixture-user\"}],\"services\":[\"echo\"],\"publications\":[\"publication:sha256:1111111111111111111111111111111111111111111111111111111111111111\"],\"capability\":\"latent:secrets/reader@0.1.0\",\"operations\":[\"read\"],\"resources\":{\"kind\":\"secrets\",\"references\":[\"fixture-selector\"]},\"ceiling\":{\"operations\":0,\"inputBytes\":0,\"outputBytes\":0,\"wallTimeMillis\":0}}]}", Long.parseUnsignedLong("0"), "lsf-capability-policy-v1", new Management.CapabilityPolicyRecordKind(1), "", false)), Optional.of(Long.parseUnsignedLong("0")), "operation-a");
            check(value.policy().isPresent(), "apply-create-policy-zero-generation.policy.presence");
            check(value.policy().get().id().equals("policy-a"), "apply-create-policy-zero-generation.policy.id");
            check(value.policy().get().metadata().isPresent(), "apply-create-policy-zero-generation.policy.metadata.presence");
            check(value.policy().get().metadata().get().name().equals("policy-a"), "apply-create-policy-zero-generation.policy.metadata.name");
            check(value.policy().get().metadata().get().tenant().isPresent(), "apply-create-policy-zero-generation.policy.metadata.tenant.presence");
            check(value.policy().get().metadata().get().tenant().get().equals("tenant-a"), "apply-create-policy-zero-generation.policy.metadata.tenant");
            check(!(value.policy().get().metadata().get().namespace().isPresent()), "apply-create-policy-zero-generation.policy.metadata.namespace.presence");
            check(value.policy().get().metadata().get().labels().size() == 0, "apply-create-policy-zero-generation.policy.metadata.labels.count");
            check(value.policy().get().metadata().get().annotations().size() == 0, "apply-create-policy-zero-generation.policy.metadata.annotations.count");
            check(value.policy().get().document().equals("{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"rules\":[{\"id\":\"deny\",\"effect\":\"deny\",\"principals\":[{\"kind\":\"user\",\"subject\":\"fixture-user\"}],\"services\":[\"echo\"],\"publications\":[\"publication:sha256:1111111111111111111111111111111111111111111111111111111111111111\"],\"capability\":\"latent:secrets/reader@0.1.0\",\"operations\":[\"read\"],\"resources\":{\"kind\":\"secrets\",\"references\":[\"fixture-selector\"]},\"ceiling\":{\"operations\":0,\"inputBytes\":0,\"outputBytes\":0,\"wallTimeMillis\":0}}]}"), "apply-create-policy-zero-generation.policy.document");
            check(value.policy().get().generation() == Long.parseUnsignedLong("0"), "apply-create-policy-zero-generation.policy.generation");
            check(value.policy().get().language().equals("lsf-capability-policy-v1"), "apply-create-policy-zero-generation.policy.language");
            check(value.policy().get().recordKind().value() == 1, "apply-create-policy-zero-generation.policy.record_kind");
            check(value.policy().get().contentDigest().equals(""), "apply-create-policy-zero-generation.policy.content_digest");
            check(value.policy().get().revoked() == false, "apply-create-policy-zero-generation.policy.revoked");
            check(value.expectedGeneration().isPresent(), "apply-create-policy-zero-generation.expected_generation.presence");
            check(value.expectedGeneration().get() == Long.parseUnsignedLong("0"), "apply-create-policy-zero-generation.expected_generation");
            check(value.operationId().equals("operation-a"), "apply-create-policy-zero-generation.operation_id");
        }
        {
            Management.ApplyPolicyRequest value = new Management.ApplyPolicyRequest(Optional.of(new Management.Policy("binding-a", Optional.of(new Management.ObjectMetadata("binding-a", Optional.of("tenant-a"), Optional.empty(), Map.ofEntries(), Map.ofEntries())), "{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"capability\":\"latent:secrets/reader@0.1.0\",\"providerProfile\":\"local-secrets-v1\",\"configurationDigest\":\"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\",\"configurationEpoch\":18446744073709551615,\"restriction\":{\"operations\":[],\"ceiling\":{\"operations\":0,\"inputBytes\":18446744073709551615,\"outputBytes\":0,\"wallTimeMillis\":0}}}", Long.parseUnsignedLong("0"), "lsf-provider-binding-v1", new Management.CapabilityPolicyRecordKind(2), "", false)), Optional.of(Long.parseUnsignedLong("18446744073709551615")), "operation-binding");
            check(value.policy().isPresent(), "apply-binding-max-precondition-and-opaque-limit-document.policy.presence");
            check(value.policy().get().id().equals("binding-a"), "apply-binding-max-precondition-and-opaque-limit-document.policy.id");
            check(value.policy().get().metadata().isPresent(), "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.presence");
            check(value.policy().get().metadata().get().name().equals("binding-a"), "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.name");
            check(value.policy().get().metadata().get().tenant().isPresent(), "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.tenant.presence");
            check(value.policy().get().metadata().get().tenant().get().equals("tenant-a"), "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.tenant");
            check(!(value.policy().get().metadata().get().namespace().isPresent()), "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.namespace.presence");
            check(value.policy().get().metadata().get().labels().size() == 0, "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.labels.count");
            check(value.policy().get().metadata().get().annotations().size() == 0, "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.annotations.count");
            check(value.policy().get().document().equals("{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"capability\":\"latent:secrets/reader@0.1.0\",\"providerProfile\":\"local-secrets-v1\",\"configurationDigest\":\"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\",\"configurationEpoch\":18446744073709551615,\"restriction\":{\"operations\":[],\"ceiling\":{\"operations\":0,\"inputBytes\":18446744073709551615,\"outputBytes\":0,\"wallTimeMillis\":0}}}"), "apply-binding-max-precondition-and-opaque-limit-document.policy.document");
            check(value.policy().get().generation() == Long.parseUnsignedLong("0"), "apply-binding-max-precondition-and-opaque-limit-document.policy.generation");
            check(value.policy().get().language().equals("lsf-provider-binding-v1"), "apply-binding-max-precondition-and-opaque-limit-document.policy.language");
            check(value.policy().get().recordKind().value() == 2, "apply-binding-max-precondition-and-opaque-limit-document.policy.record_kind");
            check(value.policy().get().contentDigest().equals(""), "apply-binding-max-precondition-and-opaque-limit-document.policy.content_digest");
            check(value.policy().get().revoked() == false, "apply-binding-max-precondition-and-opaque-limit-document.policy.revoked");
            check(value.expectedGeneration().isPresent(), "apply-binding-max-precondition-and-opaque-limit-document.expected_generation.presence");
            check(value.expectedGeneration().get() == Long.parseUnsignedLong("18446744073709551615"), "apply-binding-max-precondition-and-opaque-limit-document.expected_generation");
            check(value.operationId().equals("operation-binding"), "apply-binding-max-precondition-and-opaque-limit-document.operation_id");
        }
        {
            Management.ListPoliciesRequest value = new Management.ListPoliciesRequest(new Management.CapabilityPolicyRecordKind(1), Optional.empty());
            check(value.recordKind().value() == 1, "policy-page-absent.record_kind");
            check(!(value.page().isPresent()), "policy-page-absent.page.presence");
        }
        {
            Management.ListPoliciesRequest value = new Management.ListPoliciesRequest(new Management.CapabilityPolicyRecordKind(2), Optional.of(new Management.PageRequest(Integer.parseUnsignedInt("0"), Optional.empty())));
            check(value.recordKind().value() == 2, "policy-page-zero-invalid.record_kind");
            check(value.page().isPresent(), "policy-page-zero-invalid.page.presence");
            check(value.page().get().pageSize() == Integer.parseUnsignedInt("0"), "policy-page-zero-invalid.page.page_size");
            check(!(value.page().get().pageToken().isPresent()), "policy-page-zero-invalid.page.page_token.presence");
        }
        {
            Management.ListPoliciesRequest value = new Management.ListPoliciesRequest(new Management.CapabilityPolicyRecordKind(1), Optional.of(new Management.PageRequest(Integer.parseUnsignedInt("1"), Optional.of(""))));
            check(value.recordKind().value() == 1, "policy-page-empty-token-invalid.record_kind");
            check(value.page().isPresent(), "policy-page-empty-token-invalid.page.presence");
            check(value.page().get().pageSize() == Integer.parseUnsignedInt("1"), "policy-page-empty-token-invalid.page.page_size");
            check(value.page().get().pageToken().isPresent(), "policy-page-empty-token-invalid.page.page_token.presence");
            check(value.page().get().pageToken().get().equals(""), "policy-page-empty-token-invalid.page.page_token");
        }
        {
            Management.ListPoliciesResponse value = new Management.ListPoliciesResponse(List.of(new Management.Policy("policy-a", Optional.empty(), "", Long.parseUnsignedLong("18446744073709551615"), "", new Management.CapabilityPolicyRecordKind(1), "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", true)), Long.parseUnsignedLong("18446744073709551615"), Optional.of(new Management.PageResponse(Optional.of("opaque-policy-cursor"))));
            check(value.policies().size() == 1, "policy-page-first.policies.count");
            check(value.policies().get(0).id().equals("policy-a"), "policy-page-first.policies.0.id");
            check(!(value.policies().get(0).metadata().isPresent()), "policy-page-first.policies.0.metadata.presence");
            check(value.policies().get(0).document().equals(""), "policy-page-first.policies.0.document");
            check(value.policies().get(0).generation() == Long.parseUnsignedLong("18446744073709551615"), "policy-page-first.policies.0.generation");
            check(value.policies().get(0).language().equals(""), "policy-page-first.policies.0.language");
            check(value.policies().get(0).recordKind().value() == 1, "policy-page-first.policies.0.record_kind");
            check(value.policies().get(0).contentDigest().equals("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), "policy-page-first.policies.0.content_digest");
            check(value.policies().get(0).revoked() == true, "policy-page-first.policies.0.revoked");
            check(value.catalogGeneration() == Long.parseUnsignedLong("18446744073709551615"), "policy-page-first.catalog_generation");
            check(value.page().isPresent(), "policy-page-first.page.presence");
            check(value.page().get().nextPageToken().isPresent(), "policy-page-first.page.next_page_token.presence");
            check(value.page().get().nextPageToken().get().equals("opaque-policy-cursor"), "policy-page-first.page.next_page_token");
        }
        {
            Management.ListPoliciesResponse value = new Management.ListPoliciesResponse(List.of(), Long.parseUnsignedLong("18446744073709551615"), Optional.of(new Management.PageResponse(Optional.empty())));
            check(value.policies().size() == 0, "policy-page-last.policies.count");
            check(value.catalogGeneration() == Long.parseUnsignedLong("18446744073709551615"), "policy-page-last.catalog_generation");
            check(value.page().isPresent(), "policy-page-last.page.presence");
            check(!(value.page().get().nextPageToken().isPresent()), "policy-page-last.page.next_page_token.presence");
        }
        {
            Management.ListPoliciesRequest value = new Management.ListPoliciesRequest(new Management.CapabilityPolicyRecordKind(1), Optional.of(new Management.PageRequest(Integer.parseUnsignedInt("1"), Optional.of("opaque-policy-cursor"))));
            check(value.recordKind().value() == 1, "policy-next-page-request.record_kind");
            check(value.page().isPresent(), "policy-next-page-request.page.presence");
            check(value.page().get().pageSize() == Integer.parseUnsignedInt("1"), "policy-next-page-request.page.page_size");
            check(value.page().get().pageToken().isPresent(), "policy-next-page-request.page.page_token.presence");
            check(value.page().get().pageToken().get().equals("opaque-policy-cursor"), "policy-next-page-request.page.page_token");
        }
        {
            Management.ApplyPolicyResponse value = new Management.ApplyPolicyResponse(Optional.of(new Management.Policy("policy-a", Optional.empty(), "", Long.parseUnsignedLong("18446744073709551615"), "", new Management.CapabilityPolicyRecordKind(1), "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", false)), Optional.of(new Management.CapabilityPolicyOperation("operation-a", "tenant-a", "policy-a", new Management.CapabilityPolicyRecordKind(1), Long.parseUnsignedLong("18446744073709551615"), "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", false)));
            check(value.policy().isPresent(), "apply-retains-original-receipt.policy.presence");
            check(value.policy().get().id().equals("policy-a"), "apply-retains-original-receipt.policy.id");
            check(!(value.policy().get().metadata().isPresent()), "apply-retains-original-receipt.policy.metadata.presence");
            check(value.policy().get().document().equals(""), "apply-retains-original-receipt.policy.document");
            check(value.policy().get().generation() == Long.parseUnsignedLong("18446744073709551615"), "apply-retains-original-receipt.policy.generation");
            check(value.policy().get().language().equals(""), "apply-retains-original-receipt.policy.language");
            check(value.policy().get().recordKind().value() == 1, "apply-retains-original-receipt.policy.record_kind");
            check(value.policy().get().contentDigest().equals("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), "apply-retains-original-receipt.policy.content_digest");
            check(value.policy().get().revoked() == false, "apply-retains-original-receipt.policy.revoked");
            check(value.receipt().isPresent(), "apply-retains-original-receipt.receipt.presence");
            check(value.receipt().get().operationId().equals("operation-a"), "apply-retains-original-receipt.receipt.operation_id");
            check(value.receipt().get().tenant().equals("tenant-a"), "apply-retains-original-receipt.receipt.tenant");
            check(value.receipt().get().id().equals("policy-a"), "apply-retains-original-receipt.receipt.id");
            check(value.receipt().get().recordKind().value() == 1, "apply-retains-original-receipt.receipt.record_kind");
            check(value.receipt().get().generation() == Long.parseUnsignedLong("18446744073709551615"), "apply-retains-original-receipt.receipt.generation");
            check(value.receipt().get().contentDigest().equals("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), "apply-retains-original-receipt.receipt.content_digest");
            check(value.receipt().get().revoked() == false, "apply-retains-original-receipt.receipt.revoked");
        }
        {
            Management.GetPolicyOperationRequest value = new Management.GetPolicyOperationRequest("operation-a");
            check(value.operationId().equals("operation-a"), "get-policy-operation-known-id.operation_id");
        }
        {
            Management.GetPolicyOperationResponse value = new Management.GetPolicyOperationResponse(Optional.empty());
            check(!(value.receipt().isPresent()), "operation-recovery-not-retained-is-unknown.receipt.presence");
        }
        {
            Management.GetPolicyOperationResponse value = new Management.GetPolicyOperationResponse(Optional.of(new Management.CapabilityPolicyOperation("operation-a", "tenant-a", "policy-a", new Management.CapabilityPolicyRecordKind(1), Long.parseUnsignedLong("18446744073709551615"), "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", false)));
            check(value.receipt().isPresent(), "operation-recovery-original-receipt.receipt.presence");
            check(value.receipt().get().operationId().equals("operation-a"), "operation-recovery-original-receipt.receipt.operation_id");
            check(value.receipt().get().tenant().equals("tenant-a"), "operation-recovery-original-receipt.receipt.tenant");
            check(value.receipt().get().id().equals("policy-a"), "operation-recovery-original-receipt.receipt.id");
            check(value.receipt().get().recordKind().value() == 1, "operation-recovery-original-receipt.receipt.record_kind");
            check(value.receipt().get().generation() == Long.parseUnsignedLong("18446744073709551615"), "operation-recovery-original-receipt.receipt.generation");
            check(value.receipt().get().contentDigest().equals("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), "operation-recovery-original-receipt.receipt.content_digest");
            check(value.receipt().get().revoked() == false, "operation-recovery-original-receipt.receipt.revoked");
        }
        {
            Management.ListCapabilitiesRequest value = new Management.ListCapabilitiesRequest(Optional.empty(), Optional.empty(), Optional.empty(), "deployment-a", false);
            check(!(value.contractPrefix().isPresent()), "capabilities-absent-page-default.contract_prefix.presence");
            check(!(value.provider().isPresent()), "capabilities-absent-page-default.provider.presence");
            check(!(value.page().isPresent()), "capabilities-absent-page-default.page.presence");
            check(value.deploymentId().equals("deployment-a"), "capabilities-absent-page-default.deployment_id");
            check(value.includeNodeUsage() == false, "capabilities-absent-page-default.include_node_usage");
        }
        {
            Management.ListCapabilitiesRequest value = new Management.ListCapabilitiesRequest(Optional.empty(), Optional.empty(), Optional.of(new Management.PageRequest(Integer.parseUnsignedInt("0"), Optional.empty())), "deployment-a", false);
            check(!(value.contractPrefix().isPresent()), "capabilities-zero-page-default.contract_prefix.presence");
            check(!(value.provider().isPresent()), "capabilities-zero-page-default.provider.presence");
            check(value.page().isPresent(), "capabilities-zero-page-default.page.presence");
            check(value.page().get().pageSize() == Integer.parseUnsignedInt("0"), "capabilities-zero-page-default.page.page_size");
            check(!(value.page().get().pageToken().isPresent()), "capabilities-zero-page-default.page.page_token.presence");
            check(value.deploymentId().equals("deployment-a"), "capabilities-zero-page-default.deployment_id");
            check(value.includeNodeUsage() == false, "capabilities-zero-page-default.include_node_usage");
        }
        {
            Management.ListCapabilitiesRequest value = new Management.ListCapabilitiesRequest(Optional.of(""), Optional.of(""), Optional.of(new Management.PageRequest(Integer.parseUnsignedInt("128"), Optional.empty())), "deployment-a", true);
            check(value.contractPrefix().isPresent(), "capabilities-present-empty-filters.contract_prefix.presence");
            check(value.contractPrefix().get().equals(""), "capabilities-present-empty-filters.contract_prefix");
            check(value.provider().isPresent(), "capabilities-present-empty-filters.provider.presence");
            check(value.provider().get().equals(""), "capabilities-present-empty-filters.provider");
            check(value.page().isPresent(), "capabilities-present-empty-filters.page.presence");
            check(value.page().get().pageSize() == Integer.parseUnsignedInt("128"), "capabilities-present-empty-filters.page.page_size");
            check(!(value.page().get().pageToken().isPresent()), "capabilities-present-empty-filters.page.page_token.presence");
            check(value.deploymentId().equals("deployment-a"), "capabilities-present-empty-filters.deployment_id");
            check(value.includeNodeUsage() == true, "capabilities-present-empty-filters.include_node_usage");
        }
        {
            Management.ListCapabilitiesRequest value = new Management.ListCapabilitiesRequest(Optional.empty(), Optional.empty(), Optional.of(new Management.PageRequest(Integer.parseUnsignedInt("1"), Optional.empty())), "", false);
            check(!(value.contractPrefix().isPresent()), "capabilities-explicit-deployment-required.contract_prefix.presence");
            check(!(value.provider().isPresent()), "capabilities-explicit-deployment-required.provider.presence");
            check(value.page().isPresent(), "capabilities-explicit-deployment-required.page.presence");
            check(value.page().get().pageSize() == Integer.parseUnsignedInt("1"), "capabilities-explicit-deployment-required.page.page_size");
            check(!(value.page().get().pageToken().isPresent()), "capabilities-explicit-deployment-required.page.page_token.presence");
            check(value.deploymentId().equals(""), "capabilities-explicit-deployment-required.deployment_id");
            check(value.includeNodeUsage() == false, "capabilities-explicit-deployment-required.include_node_usage");
        }
        {
            Management.ListCapabilitiesRequest value = new Management.ListCapabilitiesRequest(Optional.empty(), Optional.empty(), Optional.of(new Management.PageRequest(Integer.parseUnsignedInt("4294967295"), Optional.empty())), "deployment-a", false);
            check(!(value.contractPrefix().isPresent()), "capabilities-page-too-large.contract_prefix.presence");
            check(!(value.provider().isPresent()), "capabilities-page-too-large.provider.presence");
            check(value.page().isPresent(), "capabilities-page-too-large.page.presence");
            check(value.page().get().pageSize() == Integer.parseUnsignedInt("4294967295"), "capabilities-page-too-large.page.page_size");
            check(!(value.page().get().pageToken().isPresent()), "capabilities-page-too-large.page.page_token.presence");
            check(value.deploymentId().equals("deployment-a"), "capabilities-page-too-large.deployment_id");
            check(value.includeNodeUsage() == false, "capabilities-page-too-large.include_node_usage");
        }
        {
            Management.ListCapabilitiesResponse value = new Management.ListCapabilitiesResponse(List.of(new Management.CapabilityDescriptor("latent:secrets/reader@0.1.0", "latent:secrets/reader@0.1.0", "local-secrets-v1", List.of("read"), Map.ofEntries(), Optional.of(new Management.CapabilityBindingInspection(Optional.of(""), Optional.of(new Management.CapabilityInspectionPolicy("binding-a", Long.parseUnsignedLong("18446744073709551615"), "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")), List.of(new Management.CapabilityInspectionPolicy("policy-a", Long.parseUnsignedLong("9223372036854775808"), "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")), "local-secrets-v1", "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", Long.parseUnsignedLong("18446744073709551615"), "provider-configuration-changed"))), new Management.CapabilityDescriptor("future-capability", "future-contract", "future-provider", List.of(), Map.ofEntries(Map.entry("descriptive", "not-authority")), Optional.empty())), Optional.of(new Management.PageResponse(Optional.of("opaque-capability-cursor"))), Optional.of(new Management.CapabilityInspectionRevision("deployment-a", "revision-a", "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", Optional.of("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111"), Long.parseUnsignedLong("18446744073709551615"), Long.parseUnsignedLong("9223372036854775808"))), Optional.of(new Management.CapabilityResourceUsage("tenant", Map.ofEntries(Map.entry("sessions", Long.parseUnsignedLong("18446744073709551615")), Map.entry("calls", Long.parseUnsignedLong("0"))), List.of("fixture-owner-unavailable"))), Optional.empty(), "sampled");
            check(value.capabilities().size() == 2, "redacted-capability-provider-inspection.capabilities.count");
            check(value.capabilities().get(0).id().equals("latent:secrets/reader@0.1.0"), "redacted-capability-provider-inspection.capabilities.0.id");
            check(value.capabilities().get(0).contract().equals("latent:secrets/reader@0.1.0"), "redacted-capability-provider-inspection.capabilities.0.contract");
            check(value.capabilities().get(0).provider().equals("local-secrets-v1"), "redacted-capability-provider-inspection.capabilities.0.provider");
            check(value.capabilities().get(0).operations().size() == 1, "redacted-capability-provider-inspection.capabilities.0.operations.count");
            check(value.capabilities().get(0).operations().get(0).equals("read"), "redacted-capability-provider-inspection.capabilities.0.operations.0");
            check(value.capabilities().get(0).attributes().size() == 0, "redacted-capability-provider-inspection.capabilities.0.attributes.count");
            check(value.capabilities().get(0).inspection().isPresent(), "redacted-capability-provider-inspection.capabilities.0.inspection.presence");
            check(value.capabilities().get(0).inspection().get().definitionDigest().isPresent(), "redacted-capability-provider-inspection.capabilities.0.inspection.definition_digest.presence");
            check(value.capabilities().get(0).inspection().get().definitionDigest().get().equals(""), "redacted-capability-provider-inspection.capabilities.0.inspection.definition_digest");
            check(value.capabilities().get(0).inspection().get().providerBinding().isPresent(), "redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.presence");
            check(value.capabilities().get(0).inspection().get().providerBinding().get().id().equals("binding-a"), "redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.id");
            check(value.capabilities().get(0).inspection().get().providerBinding().get().revision() == Long.parseUnsignedLong("18446744073709551615"), "redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.revision");
            check(value.capabilities().get(0).inspection().get().providerBinding().get().digest().equals("sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"), "redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.digest");
            check(value.capabilities().get(0).inspection().get().policies().size() == 1, "redacted-capability-provider-inspection.capabilities.0.inspection.policies.count");
            check(value.capabilities().get(0).inspection().get().policies().get(0).id().equals("policy-a"), "redacted-capability-provider-inspection.capabilities.0.inspection.policies.0.id");
            check(value.capabilities().get(0).inspection().get().policies().get(0).revision() == Long.parseUnsignedLong("9223372036854775808"), "redacted-capability-provider-inspection.capabilities.0.inspection.policies.0.revision");
            check(value.capabilities().get(0).inspection().get().policies().get(0).digest().equals("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), "redacted-capability-provider-inspection.capabilities.0.inspection.policies.0.digest");
            check(value.capabilities().get(0).inspection().get().providerProfile().equals("local-secrets-v1"), "redacted-capability-provider-inspection.capabilities.0.inspection.provider_profile");
            check(value.capabilities().get(0).inspection().get().providerConfigurationDigest().equals("sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"), "redacted-capability-provider-inspection.capabilities.0.inspection.provider_configuration_digest");
            check(value.capabilities().get(0).inspection().get().providerConfigurationEpoch() == Long.parseUnsignedLong("18446744073709551615"), "redacted-capability-provider-inspection.capabilities.0.inspection.provider_configuration_epoch");
            check(value.capabilities().get(0).inspection().get().state().equals("provider-configuration-changed"), "redacted-capability-provider-inspection.capabilities.0.inspection.state");
            check(value.capabilities().get(1).id().equals("future-capability"), "redacted-capability-provider-inspection.capabilities.1.id");
            check(value.capabilities().get(1).contract().equals("future-contract"), "redacted-capability-provider-inspection.capabilities.1.contract");
            check(value.capabilities().get(1).provider().equals("future-provider"), "redacted-capability-provider-inspection.capabilities.1.provider");
            check(value.capabilities().get(1).operations().size() == 0, "redacted-capability-provider-inspection.capabilities.1.operations.count");
            check(value.capabilities().get(1).attributes().size() == 1, "redacted-capability-provider-inspection.capabilities.1.attributes.count");
            check(value.capabilities().get(1).attributes().get("descriptive").equals("not-authority"), "redacted-capability-provider-inspection.capabilities.1.attributes.0");
            check(!(value.capabilities().get(1).inspection().isPresent()), "redacted-capability-provider-inspection.capabilities.1.inspection.presence");
            check(value.page().isPresent(), "redacted-capability-provider-inspection.page.presence");
            check(value.page().get().nextPageToken().isPresent(), "redacted-capability-provider-inspection.page.next_page_token.presence");
            check(value.page().get().nextPageToken().get().equals("opaque-capability-cursor"), "redacted-capability-provider-inspection.page.next_page_token");
            check(value.revision().isPresent(), "redacted-capability-provider-inspection.revision.presence");
            check(value.revision().get().deploymentId().equals("deployment-a"), "redacted-capability-provider-inspection.revision.deployment_id");
            check(value.revision().get().revisionId().equals("revision-a"), "redacted-capability-provider-inspection.revision.revision_id");
            check(value.revision().get().componentDigest().equals("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), "redacted-capability-provider-inspection.revision.component_digest");
            check(value.revision().get().publicationId().isPresent(), "redacted-capability-provider-inspection.revision.publication_id.presence");
            check(value.revision().get().publicationId().get().equals("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111"), "redacted-capability-provider-inspection.revision.publication_id");
            check(value.revision().get().routeGeneration() == Long.parseUnsignedLong("18446744073709551615"), "redacted-capability-provider-inspection.revision.route_generation");
            check(value.revision().get().catalogTransaction() == Long.parseUnsignedLong("9223372036854775808"), "redacted-capability-provider-inspection.revision.catalog_transaction");
            check(value.tenantUsage().isPresent(), "redacted-capability-provider-inspection.tenant_usage.presence");
            check(value.tenantUsage().get().scope().equals("tenant"), "redacted-capability-provider-inspection.tenant_usage.scope");
            check(value.tenantUsage().get().counters().size() == 2, "redacted-capability-provider-inspection.tenant_usage.counters.count");
            check(value.tenantUsage().get().counters().get("sessions") == Long.parseUnsignedLong("18446744073709551615"), "redacted-capability-provider-inspection.tenant_usage.counters.0");
            check(value.tenantUsage().get().counters().get("calls") == Long.parseUnsignedLong("0"), "redacted-capability-provider-inspection.tenant_usage.counters.1");
            check(value.tenantUsage().get().unavailable().size() == 1, "redacted-capability-provider-inspection.tenant_usage.unavailable.count");
            check(value.tenantUsage().get().unavailable().get(0).equals("fixture-owner-unavailable"), "redacted-capability-provider-inspection.tenant_usage.unavailable.0");
            check(!(value.nodeUsage().isPresent()), "redacted-capability-provider-inspection.node_usage.presence");
            check(value.state().equals("sampled"), "redacted-capability-provider-inspection.state");
        }
        {
            Management.ListCapabilitiesResponse value = new Management.ListCapabilitiesResponse(List.of(), Optional.empty(), Optional.empty(), Optional.empty(), Optional.of(new Management.CapabilityResourceUsage("node", Map.ofEntries(), List.of("provider-pools-no-retained-owner", "audit-owner-not-configured"))), "binding-plan-unavailable");
            check(value.capabilities().size() == 0, "missing-provider-plan-not-zero-usage.capabilities.count");
            check(!(value.page().isPresent()), "missing-provider-plan-not-zero-usage.page.presence");
            check(!(value.revision().isPresent()), "missing-provider-plan-not-zero-usage.revision.presence");
            check(!(value.tenantUsage().isPresent()), "missing-provider-plan-not-zero-usage.tenant_usage.presence");
            check(value.nodeUsage().isPresent(), "missing-provider-plan-not-zero-usage.node_usage.presence");
            check(value.nodeUsage().get().scope().equals("node"), "missing-provider-plan-not-zero-usage.node_usage.scope");
            check(value.nodeUsage().get().counters().size() == 0, "missing-provider-plan-not-zero-usage.node_usage.counters.count");
            check(value.nodeUsage().get().unavailable().size() == 2, "missing-provider-plan-not-zero-usage.node_usage.unavailable.count");
            check(value.nodeUsage().get().unavailable().get(0).equals("provider-pools-no-retained-owner"), "missing-provider-plan-not-zero-usage.node_usage.unavailable.0");
            check(value.nodeUsage().get().unavailable().get(1).equals("audit-owner-not-configured"), "missing-provider-plan-not-zero-usage.node_usage.unavailable.1");
            check(value.state().equals("binding-plan-unavailable"), "missing-provider-plan-not-zero-usage.state");
        }
        {
            Management.CapabilityInspectionCeiling value = new Management.CapabilityInspectionCeiling(Integer.parseUnsignedInt("0"), Long.parseUnsignedLong("18446744073709551615"), Long.parseUnsignedLong("0"), Long.parseUnsignedLong("18446744073709551615"));
            check(value.operations() == Integer.parseUnsignedInt("0"), "typed-ceiling-zero-and-max-not-grant.operations");
            check(value.inputBytes() == Long.parseUnsignedLong("18446744073709551615"), "typed-ceiling-zero-and-max-not-grant.input_bytes");
            check(value.outputBytes() == Long.parseUnsignedLong("0"), "typed-ceiling-zero-and-max-not-grant.output_bytes");
            check(value.wallTimeMillis() == Long.parseUnsignedLong("18446744073709551615"), "typed-ceiling-zero-and-max-not-grant.wall_time_millis");
        }
        {
            Management.CallOptions value = new Management.CallOptions(Optional.empty());
            check(!(value.timeoutMillis().isPresent()), "local-timeout-absent.timeout_millis.presence");
        }
        {
            Management.CallOptions value = new Management.CallOptions(Optional.of(Long.parseUnsignedLong("0")));
            check(value.timeoutMillis().isPresent(), "local-timeout-zero.timeout_millis.presence");
            check(value.timeoutMillis().get() == Long.parseUnsignedLong("0"), "local-timeout-zero.timeout_millis");
        }
        {
            Management.CallOptions value = new Management.CallOptions(Optional.of(Long.parseUnsignedLong("18446744073709551615")));
            check(value.timeoutMillis().isPresent(), "local-timeout-max-not-wrapped.timeout_millis.presence");
            check(value.timeoutMillis().get() == Long.parseUnsignedLong("18446744073709551615"), "local-timeout-max-not-wrapped.timeout_millis");
        }
        {
            Management.ClientFailure value = new Management.ClientFailure(new Management.FailureCategory(1), "local-cancelled", Optional.empty(), Optional.empty(), false, new Management.OutcomeKnowledge(1), new Management.RequestIdentity(Optional.of("activation-a"), Optional.empty()), Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty());
            check(value.category().value() == 1, "local-cancel-before-dispatch.category");
            check(value.message().equals("local-cancelled"), "local-cancel-before-dispatch.message");
            check(!(value.grpcStatus().isPresent()), "local-cancel-before-dispatch.grpc_status.presence");
            check(!(value.platformError().isPresent()), "local-cancel-before-dispatch.platform_error.presence");
            check(value.dispatched() == false, "local-cancel-before-dispatch.dispatched");
            check(value.outcome().value() == 1, "local-cancel-before-dispatch.outcome");
            check(value.identity().activationId().isPresent(), "local-cancel-before-dispatch.identity.activation_id.presence");
            check(value.identity().activationId().get().equals("activation-a"), "local-cancel-before-dispatch.identity.activation_id");
            check(!(value.identity().operationId().isPresent()), "local-cancel-before-dispatch.identity.operation_id.presence");
            check(!(value.auditAck().isPresent()), "local-cancel-before-dispatch.audit_ack.presence");
            check(!(value.auditStatus().isPresent()), "local-cancel-before-dispatch.audit_status.presence");
            check(!(value.unsupportedWireValue().isPresent()), "local-cancel-before-dispatch.unsupported_wire_value.presence");
            check(!(value.auditAttemptSequence().isPresent()), "local-cancel-before-dispatch.audit_attempt_sequence.presence");
        }
        {
            Management.ClientFailure value = new Management.ClientFailure(new Management.FailureCategory(2), "deadline", Optional.of(4), Optional.empty(), true, new Management.OutcomeKnowledge(2), new Management.RequestIdentity(Optional.empty(), Optional.of("operation-a")), Optional.of(new Management.AuditAck(new Management.AuditAckStatus(2), Optional.of(Long.parseUnsignedLong("18446744073709551615")))), Optional.of("outcome-unknown"), Optional.empty(), Optional.of(Long.parseUnsignedLong("18446744073709551615")));
            check(value.category().value() == 2, "deadline-after-dispatch-is-uncertain.category");
            check(value.message().equals("deadline"), "deadline-after-dispatch-is-uncertain.message");
            check(value.grpcStatus().isPresent(), "deadline-after-dispatch-is-uncertain.grpc_status.presence");
            check(value.grpcStatus().get() == 4, "deadline-after-dispatch-is-uncertain.grpc_status");
            check(!(value.platformError().isPresent()), "deadline-after-dispatch-is-uncertain.platform_error.presence");
            check(value.dispatched() == true, "deadline-after-dispatch-is-uncertain.dispatched");
            check(value.outcome().value() == 2, "deadline-after-dispatch-is-uncertain.outcome");
            check(!(value.identity().activationId().isPresent()), "deadline-after-dispatch-is-uncertain.identity.activation_id.presence");
            check(value.identity().operationId().isPresent(), "deadline-after-dispatch-is-uncertain.identity.operation_id.presence");
            check(value.identity().operationId().get().equals("operation-a"), "deadline-after-dispatch-is-uncertain.identity.operation_id");
            check(value.auditAck().isPresent(), "deadline-after-dispatch-is-uncertain.audit_ack.presence");
            check(value.auditAck().get().status().value() == 2, "deadline-after-dispatch-is-uncertain.audit_ack.status");
            check(value.auditAck().get().attemptSequence().isPresent(), "deadline-after-dispatch-is-uncertain.audit_ack.attempt_sequence.presence");
            check(value.auditAck().get().attemptSequence().get() == Long.parseUnsignedLong("18446744073709551615"), "deadline-after-dispatch-is-uncertain.audit_ack.attempt_sequence");
            check(value.auditStatus().isPresent(), "deadline-after-dispatch-is-uncertain.audit_status.presence");
            check(value.auditStatus().get().equals("outcome-unknown"), "deadline-after-dispatch-is-uncertain.audit_status");
            check(!(value.unsupportedWireValue().isPresent()), "deadline-after-dispatch-is-uncertain.unsupported_wire_value.presence");
            check(value.auditAttemptSequence().isPresent(), "deadline-after-dispatch-is-uncertain.audit_attempt_sequence.presence");
            check(value.auditAttemptSequence().get() == Long.parseUnsignedLong("18446744073709551615"), "deadline-after-dispatch-is-uncertain.audit_attempt_sequence");
        }
        {
            Management.ClientFailure value = new Management.ClientFailure(new Management.FailureCategory(4), "capability-policy-conflict", Optional.of(9), Optional.of(new Management.PlatformError("state-conflict", "capability-policy-conflict", false, List.of(new Management.ErrorDetail("future-detail", Map.ofEntries(Map.entry("value", "retained")))))), true, new Management.OutcomeKnowledge(3), new Management.RequestIdentity(Optional.empty(), Optional.of("operation-a")), Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty());
            check(value.category().value() == 4, "rpc-conflict-retains-request-identity.category");
            check(value.message().equals("capability-policy-conflict"), "rpc-conflict-retains-request-identity.message");
            check(value.grpcStatus().isPresent(), "rpc-conflict-retains-request-identity.grpc_status.presence");
            check(value.grpcStatus().get() == 9, "rpc-conflict-retains-request-identity.grpc_status");
            check(value.platformError().isPresent(), "rpc-conflict-retains-request-identity.platform_error.presence");
            check(value.platformError().get().code().equals("state-conflict"), "rpc-conflict-retains-request-identity.platform_error.code");
            check(value.platformError().get().message().equals("capability-policy-conflict"), "rpc-conflict-retains-request-identity.platform_error.message");
            check(value.platformError().get().retryable() == false, "rpc-conflict-retains-request-identity.platform_error.retryable");
            check(value.platformError().get().detailItems().size() == 1, "rpc-conflict-retains-request-identity.platform_error.detail_items.count");
            check(value.platformError().get().detailItems().get(0).kind().equals("future-detail"), "rpc-conflict-retains-request-identity.platform_error.detail_items.0.kind");
            check(value.platformError().get().detailItems().get(0).fields().size() == 1, "rpc-conflict-retains-request-identity.platform_error.detail_items.0.fields.count");
            check(value.platformError().get().detailItems().get(0).fields().get("value").equals("retained"), "rpc-conflict-retains-request-identity.platform_error.detail_items.0.fields.0");
            check(value.dispatched() == true, "rpc-conflict-retains-request-identity.dispatched");
            check(value.outcome().value() == 3, "rpc-conflict-retains-request-identity.outcome");
            check(!(value.identity().activationId().isPresent()), "rpc-conflict-retains-request-identity.identity.activation_id.presence");
            check(value.identity().operationId().isPresent(), "rpc-conflict-retains-request-identity.identity.operation_id.presence");
            check(value.identity().operationId().get().equals("operation-a"), "rpc-conflict-retains-request-identity.identity.operation_id");
            check(!(value.auditAck().isPresent()), "rpc-conflict-retains-request-identity.audit_ack.presence");
            check(!(value.auditStatus().isPresent()), "rpc-conflict-retains-request-identity.audit_status.presence");
            check(!(value.unsupportedWireValue().isPresent()), "rpc-conflict-retains-request-identity.unsupported_wire_value.presence");
            check(!(value.auditAttemptSequence().isPresent()), "rpc-conflict-retains-request-identity.audit_attempt_sequence.presence");
        }
        {
            Management.ClientFailure value = new Management.ClientFailure(new Management.FailureCategory(5), "invalid-response", Optional.empty(), Optional.empty(), true, new Management.OutcomeKnowledge(2), new Management.RequestIdentity(Optional.of("activation-a"), Optional.of("operation-a")), Optional.empty(), Optional.empty(), Optional.of(new Management.UnsupportedWireValue("phase", "future-phase-not-authority")), Optional.empty());
            check(value.category().value() == 5, "decode-failure-retains-known-identity.category");
            check(value.message().equals("invalid-response"), "decode-failure-retains-known-identity.message");
            check(!(value.grpcStatus().isPresent()), "decode-failure-retains-known-identity.grpc_status.presence");
            check(!(value.platformError().isPresent()), "decode-failure-retains-known-identity.platform_error.presence");
            check(value.dispatched() == true, "decode-failure-retains-known-identity.dispatched");
            check(value.outcome().value() == 2, "decode-failure-retains-known-identity.outcome");
            check(value.identity().activationId().isPresent(), "decode-failure-retains-known-identity.identity.activation_id.presence");
            check(value.identity().activationId().get().equals("activation-a"), "decode-failure-retains-known-identity.identity.activation_id");
            check(value.identity().operationId().isPresent(), "decode-failure-retains-known-identity.identity.operation_id.presence");
            check(value.identity().operationId().get().equals("operation-a"), "decode-failure-retains-known-identity.identity.operation_id");
            check(!(value.auditAck().isPresent()), "decode-failure-retains-known-identity.audit_ack.presence");
            check(!(value.auditStatus().isPresent()), "decode-failure-retains-known-identity.audit_status.presence");
            check(value.unsupportedWireValue().isPresent(), "decode-failure-retains-known-identity.unsupported_wire_value.presence");
            check(value.unsupportedWireValue().get().field().equals("phase"), "decode-failure-retains-known-identity.unsupported_wire_value.field");
            check(value.unsupportedWireValue().get().value().equals("future-phase-not-authority"), "decode-failure-retains-known-identity.unsupported_wire_value.value");
            check(!(value.auditAttemptSequence().isPresent()), "decode-failure-retains-known-identity.audit_attempt_sequence.presence");
        }
        {
            Management.ResponseMetadata value = new Management.ResponseMetadata(new Management.RequestIdentity(Optional.empty(), Optional.of("operation-a")), new Management.OutcomeKnowledge(3), Optional.of(new Management.AuditAck(new Management.AuditAckStatus(2), Optional.of(Long.parseUnsignedLong("18446744073709551615")))), Optional.of("outcome-unknown"), Optional.of(Long.parseUnsignedLong("18446744073709551615")));
            check(!(value.identity().activationId().isPresent()), "observed-receipt-audit-outcome-independent.identity.activation_id.presence");
            check(value.identity().operationId().isPresent(), "observed-receipt-audit-outcome-independent.identity.operation_id.presence");
            check(value.identity().operationId().get().equals("operation-a"), "observed-receipt-audit-outcome-independent.identity.operation_id");
            check(value.outcome().value() == 3, "observed-receipt-audit-outcome-independent.outcome");
            check(value.auditAck().isPresent(), "observed-receipt-audit-outcome-independent.audit_ack.presence");
            check(value.auditAck().get().status().value() == 2, "observed-receipt-audit-outcome-independent.audit_ack.status");
            check(value.auditAck().get().attemptSequence().isPresent(), "observed-receipt-audit-outcome-independent.audit_ack.attempt_sequence.presence");
            check(value.auditAck().get().attemptSequence().get() == Long.parseUnsignedLong("18446744073709551615"), "observed-receipt-audit-outcome-independent.audit_ack.attempt_sequence");
            check(value.auditStatus().isPresent(), "observed-receipt-audit-outcome-independent.audit_status.presence");
            check(value.auditStatus().get().equals("outcome-unknown"), "observed-receipt-audit-outcome-independent.audit_status");
            check(value.auditAttemptSequence().isPresent(), "observed-receipt-audit-outcome-independent.audit_attempt_sequence.presence");
            check(value.auditAttemptSequence().get() == Long.parseUnsignedLong("18446744073709551615"), "observed-receipt-audit-outcome-independent.audit_attempt_sequence");
        }
        {
            Management.ResponseMetadata value = new Management.ResponseMetadata(new Management.RequestIdentity(Optional.empty(), Optional.of("operation-a")), new Management.OutcomeKnowledge(3), Optional.empty(), Optional.empty(), Optional.empty());
            check(!(value.identity().activationId().isPresent()), "policy-response-has-no-fabricated-audit.identity.activation_id.presence");
            check(value.identity().operationId().isPresent(), "policy-response-has-no-fabricated-audit.identity.operation_id.presence");
            check(value.identity().operationId().get().equals("operation-a"), "policy-response-has-no-fabricated-audit.identity.operation_id");
            check(value.outcome().value() == 3, "policy-response-has-no-fabricated-audit.outcome");
            check(!(value.auditAck().isPresent()), "policy-response-has-no-fabricated-audit.audit_ack.presence");
            check(!(value.auditStatus().isPresent()), "policy-response-has-no-fabricated-audit.audit_status.presence");
            check(!(value.auditAttemptSequence().isPresent()), "policy-response-has-no-fabricated-audit.audit_attempt_sequence.presence");
        }
        {
            Management.ResponseMetadata value = new Management.ResponseMetadata(new Management.RequestIdentity(Optional.empty(), Optional.of("operation-a")), new Management.OutcomeKnowledge(2), Optional.empty(), Optional.empty(), Optional.empty());
            check(!(value.identity().activationId().isPresent()), "missing-recovery-keeps-outcome-unknown.identity.activation_id.presence");
            check(value.identity().operationId().isPresent(), "missing-recovery-keeps-outcome-unknown.identity.operation_id.presence");
            check(value.identity().operationId().get().equals("operation-a"), "missing-recovery-keeps-outcome-unknown.identity.operation_id");
            check(value.outcome().value() == 2, "missing-recovery-keeps-outcome-unknown.outcome");
            check(!(value.auditAck().isPresent()), "missing-recovery-keeps-outcome-unknown.audit_ack.presence");
            check(!(value.auditStatus().isPresent()), "missing-recovery-keeps-outcome-unknown.audit_status.presence");
            check(!(value.auditAttemptSequence().isPresent()), "missing-recovery-keeps-outcome-unknown.audit_attempt_sequence.presence");
        }
        {
            Management.ResponseMetadata value = new Management.ResponseMetadata(new Management.RequestIdentity(Optional.empty(), Optional.of("operation-a")), new Management.OutcomeKnowledge(91), Optional.of(new Management.AuditAck(new Management.AuditAckStatus(91), Optional.of(Long.parseUnsignedLong("0")))), Optional.of("future-audit-status"), Optional.of(Long.parseUnsignedLong("0")));
            check(!(value.identity().activationId().isPresent()), "unknown-audit-enum-and-status.identity.activation_id.presence");
            check(value.identity().operationId().isPresent(), "unknown-audit-enum-and-status.identity.operation_id.presence");
            check(value.identity().operationId().get().equals("operation-a"), "unknown-audit-enum-and-status.identity.operation_id");
            check(value.outcome().value() == 91, "unknown-audit-enum-and-status.outcome");
            check(value.auditAck().isPresent(), "unknown-audit-enum-and-status.audit_ack.presence");
            check(value.auditAck().get().status().value() == 91, "unknown-audit-enum-and-status.audit_ack.status");
            check(value.auditAck().get().attemptSequence().isPresent(), "unknown-audit-enum-and-status.audit_ack.attempt_sequence.presence");
            check(value.auditAck().get().attemptSequence().get() == Long.parseUnsignedLong("0"), "unknown-audit-enum-and-status.audit_ack.attempt_sequence");
            check(value.auditStatus().isPresent(), "unknown-audit-enum-and-status.audit_status.presence");
            check(value.auditStatus().get().equals("future-audit-status"), "unknown-audit-enum-and-status.audit_status");
            check(value.auditAttemptSequence().isPresent(), "unknown-audit-enum-and-status.audit_attempt_sequence.presence");
            check(value.auditAttemptSequence().get() == Long.parseUnsignedLong("0"), "unknown-audit-enum-and-status.audit_attempt_sequence");
        }
        {
            Management.ResponseMetadata value = new Management.ResponseMetadata(new Management.RequestIdentity(Optional.empty(), Optional.of("operation-a")), new Management.OutcomeKnowledge(3), Optional.empty(), Optional.of("future-state"), Optional.of(Long.parseUnsignedLong("18446744073709551615")));
            check(!(value.identity().activationId().isPresent()), "unknown-audit-header-and-max-attempt.identity.activation_id.presence");
            check(value.identity().operationId().isPresent(), "unknown-audit-header-and-max-attempt.identity.operation_id.presence");
            check(value.identity().operationId().get().equals("operation-a"), "unknown-audit-header-and-max-attempt.identity.operation_id");
            check(value.outcome().value() == 3, "unknown-audit-header-and-max-attempt.outcome");
            check(!(value.auditAck().isPresent()), "unknown-audit-header-and-max-attempt.audit_ack.presence");
            check(value.auditStatus().isPresent(), "unknown-audit-header-and-max-attempt.audit_status.presence");
            check(value.auditStatus().get().equals("future-state"), "unknown-audit-header-and-max-attempt.audit_status");
            check(value.auditAttemptSequence().isPresent(), "unknown-audit-header-and-max-attempt.audit_attempt_sequence.presence");
            check(value.auditAttemptSequence().get() == Long.parseUnsignedLong("18446744073709551615"), "unknown-audit-header-and-max-attempt.audit_attempt_sequence");
        }
        {
            Management.ClientFailure value = new Management.ClientFailure(new Management.FailureCategory(4), "rpc-failure", Optional.of(13), Optional.empty(), true, new Management.OutcomeKnowledge(2), new Management.RequestIdentity(Optional.empty(), Optional.of("operation-a")), Optional.empty(), Optional.of("future-state"), Optional.empty(), Optional.of(Long.parseUnsignedLong("18446744073709551615")));
            check(value.category().value() == 4, "failed-rpc-unknown-audit-header-and-max-attempt.category");
            check(value.message().equals("rpc-failure"), "failed-rpc-unknown-audit-header-and-max-attempt.message");
            check(value.grpcStatus().isPresent(), "failed-rpc-unknown-audit-header-and-max-attempt.grpc_status.presence");
            check(value.grpcStatus().get() == 13, "failed-rpc-unknown-audit-header-and-max-attempt.grpc_status");
            check(!(value.platformError().isPresent()), "failed-rpc-unknown-audit-header-and-max-attempt.platform_error.presence");
            check(value.dispatched() == true, "failed-rpc-unknown-audit-header-and-max-attempt.dispatched");
            check(value.outcome().value() == 2, "failed-rpc-unknown-audit-header-and-max-attempt.outcome");
            check(!(value.identity().activationId().isPresent()), "failed-rpc-unknown-audit-header-and-max-attempt.identity.activation_id.presence");
            check(value.identity().operationId().isPresent(), "failed-rpc-unknown-audit-header-and-max-attempt.identity.operation_id.presence");
            check(value.identity().operationId().get().equals("operation-a"), "failed-rpc-unknown-audit-header-and-max-attempt.identity.operation_id");
            check(!(value.auditAck().isPresent()), "failed-rpc-unknown-audit-header-and-max-attempt.audit_ack.presence");
            check(value.auditStatus().isPresent(), "failed-rpc-unknown-audit-header-and-max-attempt.audit_status.presence");
            check(value.auditStatus().get().equals("future-state"), "failed-rpc-unknown-audit-header-and-max-attempt.audit_status");
            check(!(value.unsupportedWireValue().isPresent()), "failed-rpc-unknown-audit-header-and-max-attempt.unsupported_wire_value.presence");
            check(value.auditAttemptSequence().isPresent(), "failed-rpc-unknown-audit-header-and-max-attempt.audit_attempt_sequence.presence");
            check(value.auditAttemptSequence().get() == Long.parseUnsignedLong("18446744073709551615"), "failed-rpc-unknown-audit-header-and-max-attempt.audit_attempt_sequence");
        }
        {
            Management.AuditAck value = new Management.AuditAck(new Management.AuditAckStatus(1), Optional.empty());
            check(value.status().value() == 1, "audit-durable-attempt-absent.status");
            check(!(value.attemptSequence().isPresent()), "audit-durable-attempt-absent.attempt_sequence.presence");
        }
        {
            Management.AuditAck value = new Management.AuditAck(new Management.AuditAckStatus(3), Optional.of(Long.parseUnsignedLong("0")));
            check(value.status().value() == 3, "audit-unavailable-attempt-zero.status");
            check(value.attemptSequence().isPresent(), "audit-unavailable-attempt-zero.attempt_sequence.presence");
            check(value.attemptSequence().get() == Long.parseUnsignedLong("0"), "audit-unavailable-attempt-zero.attempt_sequence");
        }
        {
            Management.AuditAck value = new Management.AuditAck(new Management.AuditAckStatus(4), Optional.empty());
            check(value.status().value() == 4, "audit-disabled-distinct-from-absence.status");
            check(!(value.attemptSequence().isPresent()), "audit-disabled-distinct-from-absence.attempt_sequence.presence");
        }
        {
            Management.ReleaseSelector value = new Management.ReleaseSelector(Optional.empty(), Optional.empty());
            check(!(value.componentDigest().isPresent()), "selector-absent-not-fallback.component_digest.presence");
            check(!(value.publication().isPresent()), "selector-absent-not-fallback.publication.presence");
        }
        {
            Management.ReleaseSelector value = new Management.ReleaseSelector(Optional.empty(), Optional.of(new Management.PublicationRef("", "tenant-a")));
            check(!(value.componentDigest().isPresent()), "selector-invalid-present-not-absent.component_digest.presence");
            check(value.publication().isPresent(), "selector-invalid-present-not-absent.publication.presence");
            check(value.publication().get().id().equals(""), "selector-invalid-present-not-absent.publication.id");
            check(value.publication().get().tenant().equals("tenant-a"), "selector-invalid-present-not-absent.publication.tenant");
        }
        {
            Management.ReleaseSelector value = new Management.ReleaseSelector(Optional.of("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), Optional.of(new Management.PublicationRef("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", "tenant-a")));
            check(value.componentDigest().isPresent(), "selector-ambiguous-not-auto-selected.component_digest.presence");
            check(value.componentDigest().get().equals("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), "selector-ambiguous-not-auto-selected.component_digest");
            check(value.publication().isPresent(), "selector-ambiguous-not-auto-selected.publication.presence");
            check(value.publication().get().id().equals("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111"), "selector-ambiguous-not-auto-selected.publication.id");
            check(value.publication().get().tenant().equals("tenant-a"), "selector-ambiguous-not-auto-selected.publication.tenant");
        }
        {
            Management.PublicationIdentity value = new Management.PublicationIdentity(new Management.PublicationRef("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", "tenant-a"), "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "sha256:1111111111111111111111111111111111111111111111111111111111111111");
            check(value.publication().id().equals("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111"), "publication-original-package.publication.id");
            check(value.publication().tenant().equals("tenant-a"), "publication-original-package.publication.tenant");
            check(value.componentDigest().equals("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), "publication-original-package.component_digest");
            check(value.packageDigest().equals("sha256:1111111111111111111111111111111111111111111111111111111111111111"), "publication-original-package.package_digest");
        }
        {
            Management.PublicationIdentity value = new Management.PublicationIdentity(new Management.PublicationRef("publication:sha256:2222222222222222222222222222222222222222222222222222222222222222", "tenant-a"), "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "sha256:2222222222222222222222222222222222222222222222222222222222222222");
            check(value.publication().id().equals("publication:sha256:2222222222222222222222222222222222222222222222222222222222222222"), "publication-corrected-package-same-component.publication.id");
            check(value.publication().tenant().equals("tenant-a"), "publication-corrected-package-same-component.publication.tenant");
            check(value.componentDigest().equals("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), "publication-corrected-package-same-component.component_digest");
            check(value.packageDigest().equals("sha256:2222222222222222222222222222222222222222222222222222222222222222"), "publication-corrected-package-same-component.package_digest");
        }
        {
            Management.PublicationIdentity value = new Management.PublicationIdentity(new Management.PublicationRef("publication:sha256:3333333333333333333333333333333333333333333333333333333333333333", "tenant-b"), "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "sha256:2222222222222222222222222222222222222222222222222222222222222222");
            check(value.publication().id().equals("publication:sha256:3333333333333333333333333333333333333333333333333333333333333333"), "publication-other-tenant-same-package.publication.id");
            check(value.publication().tenant().equals("tenant-b"), "publication-other-tenant-same-package.publication.tenant");
            check(value.componentDigest().equals("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), "publication-other-tenant-same-package.component_digest");
            check(value.packageDigest().equals("sha256:2222222222222222222222222222222222222222222222222222222222222222"), "publication-other-tenant-same-package.package_digest");
        }
        check(Management.formatU64Decimal(Management.parseU64Decimal("0")).equals("0"), "uint64 roundtrip");
        check(Management.formatU64Decimal(Management.parseU64Decimal("9007199254740993")).equals("9007199254740993"), "uint64 roundtrip");
        check(Management.formatU64Decimal(Management.parseU64Decimal("9223372036854775808")).equals("9223372036854775808"), "uint64 roundtrip");
        check(Management.formatU64Decimal(Management.parseU64Decimal("18446744073709551615")).equals("18446744073709551615"), "uint64 roundtrip");
        try { Management.parseU64Decimal("18446744073709551616"); throw new AssertionError("uint64 rejected"); } catch (NumberFormatException expected) { }
        try { Management.parseU64Decimal("-1"); throw new AssertionError("uint64 rejected"); } catch (NumberFormatException expected) { }
        try { Management.parseU64Decimal("+1"); throw new AssertionError("uint64 rejected"); } catch (NumberFormatException expected) { }
        try { Management.parseU64Decimal("01"); throw new AssertionError("uint64 rejected"); } catch (NumberFormatException expected) { }
        try { Management.parseU64Decimal(" 1"); throw new AssertionError("uint64 rejected"); } catch (NumberFormatException expected) { }
        try { Management.parseU64Decimal("1 "); throw new AssertionError("uint64 rejected"); } catch (NumberFormatException expected) { }
        try { Management.parseU64Decimal("1.0"); throw new AssertionError("uint64 rejected"); } catch (NumberFormatException expected) { }
        try { Management.parseU64Decimal("1e3"); throw new AssertionError("uint64 rejected"); } catch (NumberFormatException expected) { }
        try { Management.parseU64Decimal(""); throw new AssertionError("uint64 rejected"); } catch (NumberFormatException expected) { }
        try { Management.parseU64Decimal("1\000"); throw new AssertionError("uint64 rejected"); } catch (NumberFormatException expected) { }
        try { Management.parseU64Decimal("1\n"); throw new AssertionError("uint64 rejected"); } catch (NumberFormatException expected) { }
        try { Management.parseU64Decimal("1\r\n"); throw new AssertionError("uint64 rejected"); } catch (NumberFormatException expected) { }
        System.out.println("shared profile vectors: 68");
    }
}
