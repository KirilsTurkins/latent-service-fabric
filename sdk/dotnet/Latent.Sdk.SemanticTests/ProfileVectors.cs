using Profile = Latent.Sdk.Profile;

namespace Latent.Sdk.SemanticTests;

internal static class ProfileVectors
{
    private static void Check(bool value, string message)
    {
        if (!value) throw new InvalidOperationException(message);
    }

    private static void Rejects(Action action)
    {
        try { action(); }
        catch (FormatException) { return; }
        catch (OverflowException) { return; }
        throw new InvalidOperationException("uint64 input must be rejected");
    }

    internal static void Run()
    {
        {
            var value = new Profile.InvokeRequest(null, null, null, new Profile.InvocationTarget("tenant-a", "echo", "example:echo/api@1.0.0", "echo", null), new byte[]{0, 1, 2, 255}, "application/octet-stream", null, 0U, null, new Profile.ResourceBudget(18446744073709551615UL, 9223372036854775808UL, 0U, 0U, 0UL, 0UL, 0UL, 0UL, 0UL, 0U, null), new Dictionary<string, string> {{"trace", "redacted"}});
            Check(!(value.ActivationId is not null), "invoke-absent-identity-and-deadlines.activation_id.presence");
            Check(!(value.ParentActivationId is not null), "invoke-absent-identity-and-deadlines.parent_activation_id.presence");
            Check(!(value.RootActivationId is not null), "invoke-absent-identity-and-deadlines.root_activation_id.presence");
            Check(value.Target is not null, "invoke-absent-identity-and-deadlines.target.presence");
            Check(value.Target!.Tenant == "tenant-a", "invoke-absent-identity-and-deadlines.target.tenant");
            Check(value.Target!.Service == "echo", "invoke-absent-identity-and-deadlines.target.service");
            Check(value.Target!.Contract == "example:echo/api@1.0.0", "invoke-absent-identity-and-deadlines.target.contract");
            Check(value.Target!.Function == "echo", "invoke-absent-identity-and-deadlines.target.function");
            Check(!(value.Target!.Route is not null), "invoke-absent-identity-and-deadlines.target.route.presence");
            Check(value.Payload.Length == 4, "invoke-absent-identity-and-deadlines.payload.length");
            Check(value.Payload.Span[0] == 0, "invoke-absent-identity-and-deadlines.payload.0");
            Check(value.Payload.Span[1] == 1, "invoke-absent-identity-and-deadlines.payload.1");
            Check(value.Payload.Span[2] == 2, "invoke-absent-identity-and-deadlines.payload.2");
            Check(value.Payload.Span[3] == 255, "invoke-absent-identity-and-deadlines.payload.3");
            Check(value.MediaType == "application/octet-stream", "invoke-absent-identity-and-deadlines.media_type");
            Check(!(value.DeadlineUnixMillis is not null), "invoke-absent-identity-and-deadlines.deadline_unix_millis.presence");
            Check(value.Priority == 0U, "invoke-absent-identity-and-deadlines.priority");
            Check(!(value.IdempotencyKey is not null), "invoke-absent-identity-and-deadlines.idempotency_key.presence");
            Check(value.Budget is not null, "invoke-absent-identity-and-deadlines.budget.presence");
            Check(value.Budget!.CpuFuel == 18446744073709551615UL, "invoke-absent-identity-and-deadlines.budget.cpu_fuel");
            Check(value.Budget!.MemoryBytes == 9223372036854775808UL, "invoke-absent-identity-and-deadlines.budget.memory_bytes");
            Check(value.Budget!.ChildCalls == 0U, "invoke-absent-identity-and-deadlines.budget.child_calls");
            Check(value.Budget!.OutboundRequests == 0U, "invoke-absent-identity-and-deadlines.budget.outbound_requests");
            Check(value.Budget!.StateReadBytes == 0UL, "invoke-absent-identity-and-deadlines.budget.state_read_bytes");
            Check(value.Budget!.StateWriteBytes == 0UL, "invoke-absent-identity-and-deadlines.budget.state_write_bytes");
            Check(value.Budget!.BlobReadBytes == 0UL, "invoke-absent-identity-and-deadlines.budget.blob_read_bytes");
            Check(value.Budget!.BlobWriteBytes == 0UL, "invoke-absent-identity-and-deadlines.budget.blob_write_bytes");
            Check(value.Budget!.LogBytes == 0UL, "invoke-absent-identity-and-deadlines.budget.log_bytes");
            Check(value.Budget!.EffectCount == 0U, "invoke-absent-identity-and-deadlines.budget.effect_count");
            Check(!(value.Budget!.WallTimeLimitMillis is not null), "invoke-absent-identity-and-deadlines.budget.wall_time_limit_millis.presence");
            Check(value.Metadata.Count == 1, "invoke-absent-identity-and-deadlines.metadata.count");
            Check(value.Metadata["trace"] == "redacted", "invoke-absent-identity-and-deadlines.metadata.0");
        }
        {
            var value = new Profile.InvokeRequest("", "parent-a", "", new Profile.InvocationTarget("", "", "", "", ""), new byte[]{}, "", 0UL, 0U, "", new Profile.ResourceBudget(0UL, 0UL, 0U, 0U, 0UL, 0UL, 0UL, 0UL, 0UL, 0U, 0UL), new Dictionary<string, string> {});
            Check(value.ActivationId is not null, "invoke-present-invalid-and-zero-not-absence.activation_id.presence");
            Check(value.ActivationId! == "", "invoke-present-invalid-and-zero-not-absence.activation_id");
            Check(value.ParentActivationId is not null, "invoke-present-invalid-and-zero-not-absence.parent_activation_id.presence");
            Check(value.ParentActivationId! == "parent-a", "invoke-present-invalid-and-zero-not-absence.parent_activation_id");
            Check(value.RootActivationId is not null, "invoke-present-invalid-and-zero-not-absence.root_activation_id.presence");
            Check(value.RootActivationId! == "", "invoke-present-invalid-and-zero-not-absence.root_activation_id");
            Check(value.Target is not null, "invoke-present-invalid-and-zero-not-absence.target.presence");
            Check(value.Target!.Tenant == "", "invoke-present-invalid-and-zero-not-absence.target.tenant");
            Check(value.Target!.Service == "", "invoke-present-invalid-and-zero-not-absence.target.service");
            Check(value.Target!.Contract == "", "invoke-present-invalid-and-zero-not-absence.target.contract");
            Check(value.Target!.Function == "", "invoke-present-invalid-and-zero-not-absence.target.function");
            Check(value.Target!.Route is not null, "invoke-present-invalid-and-zero-not-absence.target.route.presence");
            Check(value.Target!.Route! == "", "invoke-present-invalid-and-zero-not-absence.target.route");
            Check(value.Payload.Length == 0, "invoke-present-invalid-and-zero-not-absence.payload.length");
            Check(value.MediaType == "", "invoke-present-invalid-and-zero-not-absence.media_type");
            Check(value.DeadlineUnixMillis is not null, "invoke-present-invalid-and-zero-not-absence.deadline_unix_millis.presence");
            Check(value.DeadlineUnixMillis!.Value == 0UL, "invoke-present-invalid-and-zero-not-absence.deadline_unix_millis");
            Check(value.Priority == 0U, "invoke-present-invalid-and-zero-not-absence.priority");
            Check(value.IdempotencyKey is not null, "invoke-present-invalid-and-zero-not-absence.idempotency_key.presence");
            Check(value.IdempotencyKey! == "", "invoke-present-invalid-and-zero-not-absence.idempotency_key");
            Check(value.Budget is not null, "invoke-present-invalid-and-zero-not-absence.budget.presence");
            Check(value.Budget!.CpuFuel == 0UL, "invoke-present-invalid-and-zero-not-absence.budget.cpu_fuel");
            Check(value.Budget!.MemoryBytes == 0UL, "invoke-present-invalid-and-zero-not-absence.budget.memory_bytes");
            Check(value.Budget!.ChildCalls == 0U, "invoke-present-invalid-and-zero-not-absence.budget.child_calls");
            Check(value.Budget!.OutboundRequests == 0U, "invoke-present-invalid-and-zero-not-absence.budget.outbound_requests");
            Check(value.Budget!.StateReadBytes == 0UL, "invoke-present-invalid-and-zero-not-absence.budget.state_read_bytes");
            Check(value.Budget!.StateWriteBytes == 0UL, "invoke-present-invalid-and-zero-not-absence.budget.state_write_bytes");
            Check(value.Budget!.BlobReadBytes == 0UL, "invoke-present-invalid-and-zero-not-absence.budget.blob_read_bytes");
            Check(value.Budget!.BlobWriteBytes == 0UL, "invoke-present-invalid-and-zero-not-absence.budget.blob_write_bytes");
            Check(value.Budget!.LogBytes == 0UL, "invoke-present-invalid-and-zero-not-absence.budget.log_bytes");
            Check(value.Budget!.EffectCount == 0U, "invoke-present-invalid-and-zero-not-absence.budget.effect_count");
            Check(value.Budget!.WallTimeLimitMillis is not null, "invoke-present-invalid-and-zero-not-absence.budget.wall_time_limit_millis.presence");
            Check(value.Budget!.WallTimeLimitMillis!.Value == 0UL, "invoke-present-invalid-and-zero-not-absence.budget.wall_time_limit_millis");
            Check(value.Metadata.Count == 0, "invoke-present-invalid-and-zero-not-absence.metadata.count");
        }
        {
            var value = new Profile.InvokeRequest("activation-a", "parent-a", "root-a", null, new byte[]{}, "", 18446744073709551615UL, 4294967295U, "not-an-authority-or-retry-key", null, new Dictionary<string, string> {});
            Check(value.ActivationId is not null, "invoke-known-identity-full-width-deadline-and-priority.activation_id.presence");
            Check(value.ActivationId! == "activation-a", "invoke-known-identity-full-width-deadline-and-priority.activation_id");
            Check(value.ParentActivationId is not null, "invoke-known-identity-full-width-deadline-and-priority.parent_activation_id.presence");
            Check(value.ParentActivationId! == "parent-a", "invoke-known-identity-full-width-deadline-and-priority.parent_activation_id");
            Check(value.RootActivationId is not null, "invoke-known-identity-full-width-deadline-and-priority.root_activation_id.presence");
            Check(value.RootActivationId! == "root-a", "invoke-known-identity-full-width-deadline-and-priority.root_activation_id");
            Check(!(value.Target is not null), "invoke-known-identity-full-width-deadline-and-priority.target.presence");
            Check(value.Payload.Length == 0, "invoke-known-identity-full-width-deadline-and-priority.payload.length");
            Check(value.MediaType == "", "invoke-known-identity-full-width-deadline-and-priority.media_type");
            Check(value.DeadlineUnixMillis is not null, "invoke-known-identity-full-width-deadline-and-priority.deadline_unix_millis.presence");
            Check(value.DeadlineUnixMillis!.Value == 18446744073709551615UL, "invoke-known-identity-full-width-deadline-and-priority.deadline_unix_millis");
            Check(value.Priority == 4294967295U, "invoke-known-identity-full-width-deadline-and-priority.priority");
            Check(value.IdempotencyKey is not null, "invoke-known-identity-full-width-deadline-and-priority.idempotency_key.presence");
            Check(value.IdempotencyKey! == "not-an-authority-or-retry-key", "invoke-known-identity-full-width-deadline-and-priority.idempotency_key");
            Check(!(value.Budget is not null), "invoke-known-identity-full-width-deadline-and-priority.budget.presence");
            Check(value.Metadata.Count == 0, "invoke-known-identity-full-width-deadline-and-priority.metadata.count");
        }
        {
            var value = new Profile.ResourceBudget(18446744073709551615UL, 18446744073709551615UL, 4294967295U, 4294967295U, 18446744073709551615UL, 18446744073709551615UL, 18446744073709551615UL, 18446744073709551615UL, 18446744073709551615UL, 4294967295U, 18446744073709551615UL);
            Check(value.CpuFuel == 18446744073709551615UL, "full-resource-budget.cpu_fuel");
            Check(value.MemoryBytes == 18446744073709551615UL, "full-resource-budget.memory_bytes");
            Check(value.ChildCalls == 4294967295U, "full-resource-budget.child_calls");
            Check(value.OutboundRequests == 4294967295U, "full-resource-budget.outbound_requests");
            Check(value.StateReadBytes == 18446744073709551615UL, "full-resource-budget.state_read_bytes");
            Check(value.StateWriteBytes == 18446744073709551615UL, "full-resource-budget.state_write_bytes");
            Check(value.BlobReadBytes == 18446744073709551615UL, "full-resource-budget.blob_read_bytes");
            Check(value.BlobWriteBytes == 18446744073709551615UL, "full-resource-budget.blob_write_bytes");
            Check(value.LogBytes == 18446744073709551615UL, "full-resource-budget.log_bytes");
            Check(value.EffectCount == 4294967295U, "full-resource-budget.effect_count");
            Check(value.WallTimeLimitMillis is not null, "full-resource-budget.wall_time_limit_millis.presence");
            Check(value.WallTimeLimitMillis!.Value == 18446744073709551615UL, "full-resource-budget.wall_time_limit_millis");
        }
        {
            var value = new Profile.InvokeResponse("activation-a", "revision-a", "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 18446744073709551615UL, new Profile.Success(new byte[]{0, 1, 2, 255}, "application/octet-stream", "", new string[] {"effect-a", "effect-b"}, new Dictionary<string, string> {{"result", "redacted"}}), null, null, new Profile.BudgetConsumption(18446744073709551615UL, 0UL, 9007199254740993UL, 0U, 0U, 0UL, 0UL, 0UL, 0UL, 0UL, 0U), "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111");
            Check(value.ActivationId == "activation-a", "invoke-success-retains-publication-and-component.activation_id");
            Check(value.RevisionId == "revision-a", "invoke-success-retains-publication-and-component.revision_id");
            Check(value.ReleaseDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "invoke-success-retains-publication-and-component.release_digest");
            Check(value.RouteGeneration == 18446744073709551615UL, "invoke-success-retains-publication-and-component.route_generation");
            Check(value.Success is not null, "invoke-success-retains-publication-and-component.success.presence");
            Check(value.Success!.Payload.Length == 4, "invoke-success-retains-publication-and-component.success.payload.length");
            Check(value.Success!.Payload.Span[0] == 0, "invoke-success-retains-publication-and-component.success.payload.0");
            Check(value.Success!.Payload.Span[1] == 1, "invoke-success-retains-publication-and-component.success.payload.1");
            Check(value.Success!.Payload.Span[2] == 2, "invoke-success-retains-publication-and-component.success.payload.2");
            Check(value.Success!.Payload.Span[3] == 255, "invoke-success-retains-publication-and-component.success.payload.3");
            Check(value.Success!.MediaType == "application/octet-stream", "invoke-success-retains-publication-and-component.success.media_type");
            Check(value.Success!.CommittedStateVersion is not null, "invoke-success-retains-publication-and-component.success.committed_state_version.presence");
            Check(value.Success!.CommittedStateVersion! == "", "invoke-success-retains-publication-and-component.success.committed_state_version");
            Check(value.Success!.EffectIds.Count == 2, "invoke-success-retains-publication-and-component.success.effect_ids.count");
            Check(value.Success!.EffectIds[0] == "effect-a", "invoke-success-retains-publication-and-component.success.effect_ids.0");
            Check(value.Success!.EffectIds[1] == "effect-b", "invoke-success-retains-publication-and-component.success.effect_ids.1");
            Check(value.Success!.Metadata.Count == 1, "invoke-success-retains-publication-and-component.success.metadata.count");
            Check(value.Success!.Metadata["result"] == "redacted", "invoke-success-retains-publication-and-component.success.metadata.0");
            Check(!(value.DeclaredError is not null), "invoke-success-retains-publication-and-component.declared_error.presence");
            Check(!(value.PlatformFailure is not null), "invoke-success-retains-publication-and-component.platform_failure.presence");
            Check(value.Consumption is not null, "invoke-success-retains-publication-and-component.consumption.presence");
            Check(value.Consumption!.CpuFuel == 18446744073709551615UL, "invoke-success-retains-publication-and-component.consumption.cpu_fuel");
            Check(value.Consumption!.PeakMemoryBytes == 0UL, "invoke-success-retains-publication-and-component.consumption.peak_memory_bytes");
            Check(value.Consumption!.WallTimeMicros == 9007199254740993UL, "invoke-success-retains-publication-and-component.consumption.wall_time_micros");
            Check(value.Consumption!.ChildCalls == 0U, "invoke-success-retains-publication-and-component.consumption.child_calls");
            Check(value.Consumption!.OutboundRequests == 0U, "invoke-success-retains-publication-and-component.consumption.outbound_requests");
            Check(value.Consumption!.StateReadBytes == 0UL, "invoke-success-retains-publication-and-component.consumption.state_read_bytes");
            Check(value.Consumption!.StateWriteBytes == 0UL, "invoke-success-retains-publication-and-component.consumption.state_write_bytes");
            Check(value.Consumption!.BlobReadBytes == 0UL, "invoke-success-retains-publication-and-component.consumption.blob_read_bytes");
            Check(value.Consumption!.BlobWriteBytes == 0UL, "invoke-success-retains-publication-and-component.consumption.blob_write_bytes");
            Check(value.Consumption!.LogBytes == 0UL, "invoke-success-retains-publication-and-component.consumption.log_bytes");
            Check(value.Consumption!.EffectCount == 0U, "invoke-success-retains-publication-and-component.consumption.effect_count");
            Check(value.PublicationId is not null, "invoke-success-retains-publication-and-component.publication_id.presence");
            Check(value.PublicationId! == "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", "invoke-success-retains-publication-and-component.publication_id");
        }
        {
            var value = new Profile.InvokeResponse("activation-a", "revision-a", "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 9223372036854775808UL, null, new Profile.DeclaredError("uncertain", "provider outcome unknown", new byte[]{0, 1, 2, 255}, "application/octet-stream", new Dictionary<string, string> {{"contract", "latent:http/streaming@0.3.0"}}), null, new Profile.BudgetConsumption(0UL, 0UL, 0UL, 0U, 0U, 0UL, 0UL, 0UL, 18446744073709551615UL, 0UL, 0U), "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111");
            Check(value.ActivationId == "activation-a", "typed-declared-provider-uncertainty-retains-receipt.activation_id");
            Check(value.RevisionId == "revision-a", "typed-declared-provider-uncertainty-retains-receipt.revision_id");
            Check(value.ReleaseDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "typed-declared-provider-uncertainty-retains-receipt.release_digest");
            Check(value.RouteGeneration == 9223372036854775808UL, "typed-declared-provider-uncertainty-retains-receipt.route_generation");
            Check(!(value.Success is not null), "typed-declared-provider-uncertainty-retains-receipt.success.presence");
            Check(value.DeclaredError is not null, "typed-declared-provider-uncertainty-retains-receipt.declared_error.presence");
            Check(value.DeclaredError!.Code == "uncertain", "typed-declared-provider-uncertainty-retains-receipt.declared_error.code");
            Check(value.DeclaredError!.Message == "provider outcome unknown", "typed-declared-provider-uncertainty-retains-receipt.declared_error.message");
            Check(value.DeclaredError!.Payload.Length == 4, "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.length");
            Check(value.DeclaredError!.Payload.Span[0] == 0, "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.0");
            Check(value.DeclaredError!.Payload.Span[1] == 1, "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.1");
            Check(value.DeclaredError!.Payload.Span[2] == 2, "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.2");
            Check(value.DeclaredError!.Payload.Span[3] == 255, "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.3");
            Check(value.DeclaredError!.MediaType == "application/octet-stream", "typed-declared-provider-uncertainty-retains-receipt.declared_error.media_type");
            Check(value.DeclaredError!.Metadata.Count == 1, "typed-declared-provider-uncertainty-retains-receipt.declared_error.metadata.count");
            Check(value.DeclaredError!.Metadata["contract"] == "latent:http/streaming@0.3.0", "typed-declared-provider-uncertainty-retains-receipt.declared_error.metadata.0");
            Check(!(value.PlatformFailure is not null), "typed-declared-provider-uncertainty-retains-receipt.platform_failure.presence");
            Check(value.Consumption is not null, "typed-declared-provider-uncertainty-retains-receipt.consumption.presence");
            Check(value.Consumption!.CpuFuel == 0UL, "typed-declared-provider-uncertainty-retains-receipt.consumption.cpu_fuel");
            Check(value.Consumption!.PeakMemoryBytes == 0UL, "typed-declared-provider-uncertainty-retains-receipt.consumption.peak_memory_bytes");
            Check(value.Consumption!.WallTimeMicros == 0UL, "typed-declared-provider-uncertainty-retains-receipt.consumption.wall_time_micros");
            Check(value.Consumption!.ChildCalls == 0U, "typed-declared-provider-uncertainty-retains-receipt.consumption.child_calls");
            Check(value.Consumption!.OutboundRequests == 0U, "typed-declared-provider-uncertainty-retains-receipt.consumption.outbound_requests");
            Check(value.Consumption!.StateReadBytes == 0UL, "typed-declared-provider-uncertainty-retains-receipt.consumption.state_read_bytes");
            Check(value.Consumption!.StateWriteBytes == 0UL, "typed-declared-provider-uncertainty-retains-receipt.consumption.state_write_bytes");
            Check(value.Consumption!.BlobReadBytes == 0UL, "typed-declared-provider-uncertainty-retains-receipt.consumption.blob_read_bytes");
            Check(value.Consumption!.BlobWriteBytes == 18446744073709551615UL, "typed-declared-provider-uncertainty-retains-receipt.consumption.blob_write_bytes");
            Check(value.Consumption!.LogBytes == 0UL, "typed-declared-provider-uncertainty-retains-receipt.consumption.log_bytes");
            Check(value.Consumption!.EffectCount == 0U, "typed-declared-provider-uncertainty-retains-receipt.consumption.effect_count");
            Check(value.PublicationId is not null, "typed-declared-provider-uncertainty-retains-receipt.publication_id.presence");
            Check(value.PublicationId! == "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", "typed-declared-provider-uncertainty-retains-receipt.publication_id");
        }
        {
            var value = new Profile.InvokeResponse("activation-a", "", "", 0UL, null, null, new Profile.PlatformError("permission-denied", "capability-provider-failed", false, new Profile.ErrorDetail[] {new Profile.ErrorDetail("capability-observation", new Dictionary<string, string> {{"capability", "latent:http/streaming@0.3.0"}, {"state", "policy-revoked"}}), new Profile.ErrorDetail("future-detail", new Dictionary<string, string> {{"bounded", "preserved"}})}), new Profile.BudgetConsumption(0UL, 0UL, 0UL, 0U, 0U, 0UL, 0UL, 0UL, 0UL, 18446744073709551615UL, 0U), null);
            Check(value.ActivationId == "activation-a", "typed-platform-capability-failure-retains-detail-items.activation_id");
            Check(value.RevisionId == "", "typed-platform-capability-failure-retains-detail-items.revision_id");
            Check(value.ReleaseDigest == "", "typed-platform-capability-failure-retains-detail-items.release_digest");
            Check(value.RouteGeneration == 0UL, "typed-platform-capability-failure-retains-detail-items.route_generation");
            Check(!(value.Success is not null), "typed-platform-capability-failure-retains-detail-items.success.presence");
            Check(!(value.DeclaredError is not null), "typed-platform-capability-failure-retains-detail-items.declared_error.presence");
            Check(value.PlatformFailure is not null, "typed-platform-capability-failure-retains-detail-items.platform_failure.presence");
            Check(value.PlatformFailure!.Code == "permission-denied", "typed-platform-capability-failure-retains-detail-items.platform_failure.code");
            Check(value.PlatformFailure!.Message == "capability-provider-failed", "typed-platform-capability-failure-retains-detail-items.platform_failure.message");
            Check(value.PlatformFailure!.Retryable == false, "typed-platform-capability-failure-retains-detail-items.platform_failure.retryable");
            Check(value.PlatformFailure!.DetailItems.Count == 2, "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.count");
            Check(value.PlatformFailure!.DetailItems[0].Kind == "capability-observation", "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.kind");
            Check(value.PlatformFailure!.DetailItems[0].Fields.Count == 2, "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.fields.count");
            Check(value.PlatformFailure!.DetailItems[0].Fields["capability"] == "latent:http/streaming@0.3.0", "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.fields.0");
            Check(value.PlatformFailure!.DetailItems[0].Fields["state"] == "policy-revoked", "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.fields.1");
            Check(value.PlatformFailure!.DetailItems[1].Kind == "future-detail", "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.1.kind");
            Check(value.PlatformFailure!.DetailItems[1].Fields.Count == 1, "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.1.fields.count");
            Check(value.PlatformFailure!.DetailItems[1].Fields["bounded"] == "preserved", "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.1.fields.0");
            Check(value.Consumption is not null, "typed-platform-capability-failure-retains-detail-items.consumption.presence");
            Check(value.Consumption!.CpuFuel == 0UL, "typed-platform-capability-failure-retains-detail-items.consumption.cpu_fuel");
            Check(value.Consumption!.PeakMemoryBytes == 0UL, "typed-platform-capability-failure-retains-detail-items.consumption.peak_memory_bytes");
            Check(value.Consumption!.WallTimeMicros == 0UL, "typed-platform-capability-failure-retains-detail-items.consumption.wall_time_micros");
            Check(value.Consumption!.ChildCalls == 0U, "typed-platform-capability-failure-retains-detail-items.consumption.child_calls");
            Check(value.Consumption!.OutboundRequests == 0U, "typed-platform-capability-failure-retains-detail-items.consumption.outbound_requests");
            Check(value.Consumption!.StateReadBytes == 0UL, "typed-platform-capability-failure-retains-detail-items.consumption.state_read_bytes");
            Check(value.Consumption!.StateWriteBytes == 0UL, "typed-platform-capability-failure-retains-detail-items.consumption.state_write_bytes");
            Check(value.Consumption!.BlobReadBytes == 0UL, "typed-platform-capability-failure-retains-detail-items.consumption.blob_read_bytes");
            Check(value.Consumption!.BlobWriteBytes == 0UL, "typed-platform-capability-failure-retains-detail-items.consumption.blob_write_bytes");
            Check(value.Consumption!.LogBytes == 18446744073709551615UL, "typed-platform-capability-failure-retains-detail-items.consumption.log_bytes");
            Check(value.Consumption!.EffectCount == 0U, "typed-platform-capability-failure-retains-detail-items.consumption.effect_count");
            Check(!(value.PublicationId is not null), "typed-platform-capability-failure-retains-detail-items.publication_id.presence");
        }
        {
            var value = new Profile.InvokeResponse("activation-a", "", "", 0UL, new Profile.Success(new byte[]{}, "", null, new string[] {}, new Dictionary<string, string> {}), null, null, null, "");
            Check(value.ActivationId == "activation-a", "present-invalid-publication-not-legacy.activation_id");
            Check(value.RevisionId == "", "present-invalid-publication-not-legacy.revision_id");
            Check(value.ReleaseDigest == "", "present-invalid-publication-not-legacy.release_digest");
            Check(value.RouteGeneration == 0UL, "present-invalid-publication-not-legacy.route_generation");
            Check(value.Success is not null, "present-invalid-publication-not-legacy.success.presence");
            Check(value.Success!.Payload.Length == 0, "present-invalid-publication-not-legacy.success.payload.length");
            Check(value.Success!.MediaType == "", "present-invalid-publication-not-legacy.success.media_type");
            Check(!(value.Success!.CommittedStateVersion is not null), "present-invalid-publication-not-legacy.success.committed_state_version.presence");
            Check(value.Success!.EffectIds.Count == 0, "present-invalid-publication-not-legacy.success.effect_ids.count");
            Check(value.Success!.Metadata.Count == 0, "present-invalid-publication-not-legacy.success.metadata.count");
            Check(!(value.DeclaredError is not null), "present-invalid-publication-not-legacy.declared_error.presence");
            Check(!(value.PlatformFailure is not null), "present-invalid-publication-not-legacy.platform_failure.presence");
            Check(!(value.Consumption is not null), "present-invalid-publication-not-legacy.consumption.presence");
            Check(value.PublicationId is not null, "present-invalid-publication-not-legacy.publication_id.presence");
            Check(value.PublicationId! == "", "present-invalid-publication-not-legacy.publication_id");
        }
        {
            var value = new Profile.InvokeResponse("activation-a", "", "", 0UL, new Profile.Success(new byte[]{}, "", null, new string[] {}, new Dictionary<string, string> {}), null, new Profile.PlatformError("internal", "", false, new Profile.ErrorDetail[] {}), null, null);
            Check(value.ActivationId == "activation-a", "contradictory-outcome-retained-for-rejection.activation_id");
            Check(value.RevisionId == "", "contradictory-outcome-retained-for-rejection.revision_id");
            Check(value.ReleaseDigest == "", "contradictory-outcome-retained-for-rejection.release_digest");
            Check(value.RouteGeneration == 0UL, "contradictory-outcome-retained-for-rejection.route_generation");
            Check(value.Success is not null, "contradictory-outcome-retained-for-rejection.success.presence");
            Check(value.Success!.Payload.Length == 0, "contradictory-outcome-retained-for-rejection.success.payload.length");
            Check(value.Success!.MediaType == "", "contradictory-outcome-retained-for-rejection.success.media_type");
            Check(!(value.Success!.CommittedStateVersion is not null), "contradictory-outcome-retained-for-rejection.success.committed_state_version.presence");
            Check(value.Success!.EffectIds.Count == 0, "contradictory-outcome-retained-for-rejection.success.effect_ids.count");
            Check(value.Success!.Metadata.Count == 0, "contradictory-outcome-retained-for-rejection.success.metadata.count");
            Check(!(value.DeclaredError is not null), "contradictory-outcome-retained-for-rejection.declared_error.presence");
            Check(value.PlatformFailure is not null, "contradictory-outcome-retained-for-rejection.platform_failure.presence");
            Check(value.PlatformFailure!.Code == "internal", "contradictory-outcome-retained-for-rejection.platform_failure.code");
            Check(value.PlatformFailure!.Message == "", "contradictory-outcome-retained-for-rejection.platform_failure.message");
            Check(value.PlatformFailure!.Retryable == false, "contradictory-outcome-retained-for-rejection.platform_failure.retryable");
            Check(value.PlatformFailure!.DetailItems.Count == 0, "contradictory-outcome-retained-for-rejection.platform_failure.detail_items.count");
            Check(!(value.Consumption is not null), "contradictory-outcome-retained-for-rejection.consumption.presence");
            Check(!(value.PublicationId is not null), "contradictory-outcome-retained-for-rejection.publication_id.presence");
        }
        {
            var value = new Profile.CancelRequest("activation-a", "caller-requested");
            Check(value.ActivationId == "activation-a", "cancel-request-known-id.activation_id");
            Check(value.Reason == "caller-requested", "cancel-request-known-id.reason");
        }
        {
            var value = new Profile.CancelResponse(new Profile.CancelDisposition(1), null);
            Check(value.Disposition.Value == 1, "cancel-accepted-not-cleanup.disposition");
            Check(!(value.TerminalState is not null), "cancel-accepted-not-cleanup.terminal_state.presence");
        }
        {
            var value = new Profile.CancelResponse(new Profile.CancelDisposition(2), "completed");
            Check(value.Disposition.Value == 2, "cancel-already-terminal.disposition");
            Check(value.TerminalState is not null, "cancel-already-terminal.terminal_state.presence");
            Check(value.TerminalState! == "completed", "cancel-already-terminal.terminal_state");
        }
        {
            var value = new Profile.CancelResponse(new Profile.CancelDisposition(3), null);
            Check(value.Disposition.Value == 3, "cancel-not-found-not-nonexecution.disposition");
            Check(!(value.TerminalState is not null), "cancel-not-found-not-nonexecution.terminal_state.presence");
        }
        {
            var value = new Profile.CancelResponse(new Profile.CancelDisposition(0), "");
            Check(value.Disposition.Value == 0, "cancel-unspecified-not-accepted.disposition");
            Check(value.TerminalState is not null, "cancel-unspecified-not-accepted.terminal_state.presence");
            Check(value.TerminalState! == "", "cancel-unspecified-not-accepted.terminal_state");
        }
        {
            var value = new Profile.CancelResponse(new Profile.CancelDisposition(91), "future-terminal-state");
            Check(value.Disposition.Value == 91, "cancel-unknown-enum.disposition");
            Check(value.TerminalState is not null, "cancel-unknown-enum.terminal_state.presence");
            Check(value.TerminalState! == "future-terminal-state", "cancel-unknown-enum.terminal_state");
        }
        {
            var value = new Profile.CancelResponse(new Profile.CancelDisposition(-2147483648), null);
            Check(value.Disposition.Value == -2147483648, "cancel-negative-enum.disposition");
            Check(!(value.TerminalState is not null), "cancel-negative-enum.terminal_state.presence");
        }
        {
            var value = new Profile.GetActivationRequest("activation-a");
            Check(value.ActivationId == "activation-a", "get-activation-recovery.activation_id");
        }
        {
            var value = new Profile.ActivationStatus("activation-a", "running", null, 18446744073709551615UL, new Dictionary<string, string> {}, null, null, null, null, null);
            Check(value.ActivationId == "activation-a", "activation-running-absent-terminal.activation_id");
            Check(value.Phase == "running", "activation-running-absent-terminal.phase");
            Check(!(value.TerminalState is not null), "activation-running-absent-terminal.terminal_state.presence");
            Check(value.LastUpdatedUnixMillis == 18446744073709551615UL, "activation-running-absent-terminal.last_updated_unix_millis");
            Check(value.Metadata.Count == 0, "activation-running-absent-terminal.metadata.count");
            Check(!(value.Succeeded is not null), "activation-running-absent-terminal.succeeded.presence");
            Check(!(value.DeclaredError is not null), "activation-running-absent-terminal.declared_error.presence");
            Check(!(value.PlatformFailure is not null), "activation-running-absent-terminal.platform_failure.presence");
            Check(!(value.FinalConsumption is not null), "activation-running-absent-terminal.final_consumption.presence");
            Check(!(value.TerminalAtUnixMillis is not null), "activation-running-absent-terminal.terminal_at_unix_millis.presence");
        }
        {
            var value = new Profile.ActivationStatus("activation-a", "terminal", "failed", 0UL, new Dictionary<string, string> {}, null, null, new Profile.PlatformError("resource-exhausted", "capability-capacity", false, new Profile.ErrorDetail[] {new Profile.ErrorDetail("budget", new Dictionary<string, string> {{"resource", "buffer-bytes"}})}), new Profile.BudgetConsumption(0UL, 18446744073709551615UL, 0UL, 0U, 0U, 0UL, 0UL, 0UL, 0UL, 0UL, 0U), 0UL);
            Check(value.ActivationId == "activation-a", "activation-terminal-typed-failure.activation_id");
            Check(value.Phase == "terminal", "activation-terminal-typed-failure.phase");
            Check(value.TerminalState is not null, "activation-terminal-typed-failure.terminal_state.presence");
            Check(value.TerminalState! == "failed", "activation-terminal-typed-failure.terminal_state");
            Check(value.LastUpdatedUnixMillis == 0UL, "activation-terminal-typed-failure.last_updated_unix_millis");
            Check(value.Metadata.Count == 0, "activation-terminal-typed-failure.metadata.count");
            Check(!(value.Succeeded is not null), "activation-terminal-typed-failure.succeeded.presence");
            Check(!(value.DeclaredError is not null), "activation-terminal-typed-failure.declared_error.presence");
            Check(value.PlatformFailure is not null, "activation-terminal-typed-failure.platform_failure.presence");
            Check(value.PlatformFailure!.Code == "resource-exhausted", "activation-terminal-typed-failure.platform_failure.code");
            Check(value.PlatformFailure!.Message == "capability-capacity", "activation-terminal-typed-failure.platform_failure.message");
            Check(value.PlatformFailure!.Retryable == false, "activation-terminal-typed-failure.platform_failure.retryable");
            Check(value.PlatformFailure!.DetailItems.Count == 1, "activation-terminal-typed-failure.platform_failure.detail_items.count");
            Check(value.PlatformFailure!.DetailItems[0].Kind == "budget", "activation-terminal-typed-failure.platform_failure.detail_items.0.kind");
            Check(value.PlatformFailure!.DetailItems[0].Fields.Count == 1, "activation-terminal-typed-failure.platform_failure.detail_items.0.fields.count");
            Check(value.PlatformFailure!.DetailItems[0].Fields["resource"] == "buffer-bytes", "activation-terminal-typed-failure.platform_failure.detail_items.0.fields.0");
            Check(value.FinalConsumption is not null, "activation-terminal-typed-failure.final_consumption.presence");
            Check(value.FinalConsumption!.CpuFuel == 0UL, "activation-terminal-typed-failure.final_consumption.cpu_fuel");
            Check(value.FinalConsumption!.PeakMemoryBytes == 18446744073709551615UL, "activation-terminal-typed-failure.final_consumption.peak_memory_bytes");
            Check(value.FinalConsumption!.WallTimeMicros == 0UL, "activation-terminal-typed-failure.final_consumption.wall_time_micros");
            Check(value.FinalConsumption!.ChildCalls == 0U, "activation-terminal-typed-failure.final_consumption.child_calls");
            Check(value.FinalConsumption!.OutboundRequests == 0U, "activation-terminal-typed-failure.final_consumption.outbound_requests");
            Check(value.FinalConsumption!.StateReadBytes == 0UL, "activation-terminal-typed-failure.final_consumption.state_read_bytes");
            Check(value.FinalConsumption!.StateWriteBytes == 0UL, "activation-terminal-typed-failure.final_consumption.state_write_bytes");
            Check(value.FinalConsumption!.BlobReadBytes == 0UL, "activation-terminal-typed-failure.final_consumption.blob_read_bytes");
            Check(value.FinalConsumption!.BlobWriteBytes == 0UL, "activation-terminal-typed-failure.final_consumption.blob_write_bytes");
            Check(value.FinalConsumption!.LogBytes == 0UL, "activation-terminal-typed-failure.final_consumption.log_bytes");
            Check(value.FinalConsumption!.EffectCount == 0U, "activation-terminal-typed-failure.final_consumption.effect_count");
            Check(value.TerminalAtUnixMillis is not null, "activation-terminal-typed-failure.terminal_at_unix_millis.presence");
            Check(value.TerminalAtUnixMillis!.Value == 0UL, "activation-terminal-typed-failure.terminal_at_unix_millis");
        }
        {
            var value = new Profile.ActivationStatus("activation-a", "terminal", "completed", 0UL, new Dictionary<string, string> {}, new Profile.ActivationSuccessSummary("state-a", new string[] {"effect-a"}, new Dictionary<string, string> {{"retained", "true"}}), null, null, new Profile.BudgetConsumption(0UL, 0UL, 0UL, 0U, 0U, 0UL, 0UL, 0UL, 0UL, 0UL, 4294967295U), 18446744073709551615UL);
            Check(value.ActivationId == "activation-a", "activation-terminal-success-summary.activation_id");
            Check(value.Phase == "terminal", "activation-terminal-success-summary.phase");
            Check(value.TerminalState is not null, "activation-terminal-success-summary.terminal_state.presence");
            Check(value.TerminalState! == "completed", "activation-terminal-success-summary.terminal_state");
            Check(value.LastUpdatedUnixMillis == 0UL, "activation-terminal-success-summary.last_updated_unix_millis");
            Check(value.Metadata.Count == 0, "activation-terminal-success-summary.metadata.count");
            Check(value.Succeeded is not null, "activation-terminal-success-summary.succeeded.presence");
            Check(value.Succeeded!.CommittedStateVersion is not null, "activation-terminal-success-summary.succeeded.committed_state_version.presence");
            Check(value.Succeeded!.CommittedStateVersion! == "state-a", "activation-terminal-success-summary.succeeded.committed_state_version");
            Check(value.Succeeded!.EffectIds.Count == 1, "activation-terminal-success-summary.succeeded.effect_ids.count");
            Check(value.Succeeded!.EffectIds[0] == "effect-a", "activation-terminal-success-summary.succeeded.effect_ids.0");
            Check(value.Succeeded!.Metadata.Count == 1, "activation-terminal-success-summary.succeeded.metadata.count");
            Check(value.Succeeded!.Metadata["retained"] == "true", "activation-terminal-success-summary.succeeded.metadata.0");
            Check(!(value.DeclaredError is not null), "activation-terminal-success-summary.declared_error.presence");
            Check(!(value.PlatformFailure is not null), "activation-terminal-success-summary.platform_failure.presence");
            Check(value.FinalConsumption is not null, "activation-terminal-success-summary.final_consumption.presence");
            Check(value.FinalConsumption!.CpuFuel == 0UL, "activation-terminal-success-summary.final_consumption.cpu_fuel");
            Check(value.FinalConsumption!.PeakMemoryBytes == 0UL, "activation-terminal-success-summary.final_consumption.peak_memory_bytes");
            Check(value.FinalConsumption!.WallTimeMicros == 0UL, "activation-terminal-success-summary.final_consumption.wall_time_micros");
            Check(value.FinalConsumption!.ChildCalls == 0U, "activation-terminal-success-summary.final_consumption.child_calls");
            Check(value.FinalConsumption!.OutboundRequests == 0U, "activation-terminal-success-summary.final_consumption.outbound_requests");
            Check(value.FinalConsumption!.StateReadBytes == 0UL, "activation-terminal-success-summary.final_consumption.state_read_bytes");
            Check(value.FinalConsumption!.StateWriteBytes == 0UL, "activation-terminal-success-summary.final_consumption.state_write_bytes");
            Check(value.FinalConsumption!.BlobReadBytes == 0UL, "activation-terminal-success-summary.final_consumption.blob_read_bytes");
            Check(value.FinalConsumption!.BlobWriteBytes == 0UL, "activation-terminal-success-summary.final_consumption.blob_write_bytes");
            Check(value.FinalConsumption!.LogBytes == 0UL, "activation-terminal-success-summary.final_consumption.log_bytes");
            Check(value.FinalConsumption!.EffectCount == 4294967295U, "activation-terminal-success-summary.final_consumption.effect_count");
            Check(value.TerminalAtUnixMillis is not null, "activation-terminal-success-summary.terminal_at_unix_millis.presence");
            Check(value.TerminalAtUnixMillis!.Value == 18446744073709551615UL, "activation-terminal-success-summary.terminal_at_unix_millis");
        }
        {
            var value = new Profile.GetPolicyResponse(null);
            Check(!(value.Policy is not null), "policy-absence.policy.presence");
        }
        {
            var value = new Profile.GetPolicyRequest("policy-a", new Profile.CapabilityPolicyRecordKind(1));
            Check(value.Id == "policy-a", "policy-record-kind.id");
            Check(value.RecordKind.Value == 1, "policy-record-kind.record_kind");
        }
        {
            var value = new Profile.GetPolicyRequest("binding-a", new Profile.CapabilityPolicyRecordKind(2));
            Check(value.Id == "binding-a", "provider-binding-record-kind.id");
            Check(value.RecordKind.Value == 2, "provider-binding-record-kind.record_kind");
        }
        {
            var value = new Profile.Policy("future-record", new Profile.ObjectMetadata("future-record", "", "", new Dictionary<string, string> {{"sampled", "true"}}, new Dictionary<string, string> {{"descriptive", "not-authority"}}), "", 18446744073709551615UL, "", new Profile.CapabilityPolicyRecordKind(2147483647), "", true);
            Check(value.Id == "future-record", "unknown-policy-kind.id");
            Check(value.Metadata is not null, "unknown-policy-kind.metadata.presence");
            Check(value.Metadata!.Name == "future-record", "unknown-policy-kind.metadata.name");
            Check(value.Metadata!.Tenant is not null, "unknown-policy-kind.metadata.tenant.presence");
            Check(value.Metadata!.Tenant! == "", "unknown-policy-kind.metadata.tenant");
            Check(value.Metadata!.Namespace is not null, "unknown-policy-kind.metadata.namespace.presence");
            Check(value.Metadata!.Namespace! == "", "unknown-policy-kind.metadata.namespace");
            Check(value.Metadata!.Labels.Count == 1, "unknown-policy-kind.metadata.labels.count");
            Check(value.Metadata!.Labels["sampled"] == "true", "unknown-policy-kind.metadata.labels.0");
            Check(value.Metadata!.Annotations.Count == 1, "unknown-policy-kind.metadata.annotations.count");
            Check(value.Metadata!.Annotations["descriptive"] == "not-authority", "unknown-policy-kind.metadata.annotations.0");
            Check(value.Document == "", "unknown-policy-kind.document");
            Check(value.Generation == 18446744073709551615UL, "unknown-policy-kind.generation");
            Check(value.Language == "", "unknown-policy-kind.language");
            Check(value.RecordKind.Value == 2147483647, "unknown-policy-kind.record_kind");
            Check(value.ContentDigest == "", "unknown-policy-kind.content_digest");
            Check(value.Revoked == true, "unknown-policy-kind.revoked");
        }
        {
            var value = new Profile.ApplyPolicyRequest(null, null, "operation-a");
            Check(!(value.Policy is not null), "apply-missing-generation.policy.presence");
            Check(!(value.ExpectedGeneration is not null), "apply-missing-generation.expected_generation.presence");
            Check(value.OperationId == "operation-a", "apply-missing-generation.operation_id");
        }
        {
            var value = new Profile.ApplyPolicyRequest(null, 0UL, "");
            Check(!(value.Policy is not null), "apply-present-empty-operation.policy.presence");
            Check(value.ExpectedGeneration is not null, "apply-present-empty-operation.expected_generation.presence");
            Check(value.ExpectedGeneration!.Value == 0UL, "apply-present-empty-operation.expected_generation");
            Check(value.OperationId == "", "apply-present-empty-operation.operation_id");
        }
        {
            var value = new Profile.ApplyPolicyRequest(new Profile.Policy("policy-a", new Profile.ObjectMetadata("policy-a", "tenant-a", null, new Dictionary<string, string> {}, new Dictionary<string, string> {}), "{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"rules\":[{\"id\":\"deny\",\"effect\":\"deny\",\"principals\":[{\"kind\":\"user\",\"subject\":\"fixture-user\"}],\"services\":[\"echo\"],\"publications\":[\"publication:sha256:1111111111111111111111111111111111111111111111111111111111111111\"],\"capability\":\"latent:secrets/reader@0.1.0\",\"operations\":[\"read\"],\"resources\":{\"kind\":\"secrets\",\"references\":[\"fixture-selector\"]},\"ceiling\":{\"operations\":0,\"inputBytes\":0,\"outputBytes\":0,\"wallTimeMillis\":0}}]}", 0UL, "lsf-capability-policy-v1", new Profile.CapabilityPolicyRecordKind(1), "", false), 0UL, "operation-a");
            Check(value.Policy is not null, "apply-create-policy-zero-generation.policy.presence");
            Check(value.Policy!.Id == "policy-a", "apply-create-policy-zero-generation.policy.id");
            Check(value.Policy!.Metadata is not null, "apply-create-policy-zero-generation.policy.metadata.presence");
            Check(value.Policy!.Metadata!.Name == "policy-a", "apply-create-policy-zero-generation.policy.metadata.name");
            Check(value.Policy!.Metadata!.Tenant is not null, "apply-create-policy-zero-generation.policy.metadata.tenant.presence");
            Check(value.Policy!.Metadata!.Tenant! == "tenant-a", "apply-create-policy-zero-generation.policy.metadata.tenant");
            Check(!(value.Policy!.Metadata!.Namespace is not null), "apply-create-policy-zero-generation.policy.metadata.namespace.presence");
            Check(value.Policy!.Metadata!.Labels.Count == 0, "apply-create-policy-zero-generation.policy.metadata.labels.count");
            Check(value.Policy!.Metadata!.Annotations.Count == 0, "apply-create-policy-zero-generation.policy.metadata.annotations.count");
            Check(value.Policy!.Document == "{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"rules\":[{\"id\":\"deny\",\"effect\":\"deny\",\"principals\":[{\"kind\":\"user\",\"subject\":\"fixture-user\"}],\"services\":[\"echo\"],\"publications\":[\"publication:sha256:1111111111111111111111111111111111111111111111111111111111111111\"],\"capability\":\"latent:secrets/reader@0.1.0\",\"operations\":[\"read\"],\"resources\":{\"kind\":\"secrets\",\"references\":[\"fixture-selector\"]},\"ceiling\":{\"operations\":0,\"inputBytes\":0,\"outputBytes\":0,\"wallTimeMillis\":0}}]}", "apply-create-policy-zero-generation.policy.document");
            Check(value.Policy!.Generation == 0UL, "apply-create-policy-zero-generation.policy.generation");
            Check(value.Policy!.Language == "lsf-capability-policy-v1", "apply-create-policy-zero-generation.policy.language");
            Check(value.Policy!.RecordKind.Value == 1, "apply-create-policy-zero-generation.policy.record_kind");
            Check(value.Policy!.ContentDigest == "", "apply-create-policy-zero-generation.policy.content_digest");
            Check(value.Policy!.Revoked == false, "apply-create-policy-zero-generation.policy.revoked");
            Check(value.ExpectedGeneration is not null, "apply-create-policy-zero-generation.expected_generation.presence");
            Check(value.ExpectedGeneration!.Value == 0UL, "apply-create-policy-zero-generation.expected_generation");
            Check(value.OperationId == "operation-a", "apply-create-policy-zero-generation.operation_id");
        }
        {
            var value = new Profile.ApplyPolicyRequest(new Profile.Policy("binding-a", new Profile.ObjectMetadata("binding-a", "tenant-a", null, new Dictionary<string, string> {}, new Dictionary<string, string> {}), "{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"capability\":\"latent:secrets/reader@0.1.0\",\"providerProfile\":\"local-secrets-v1\",\"configurationDigest\":\"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\",\"configurationEpoch\":18446744073709551615,\"restriction\":{\"operations\":[],\"ceiling\":{\"operations\":0,\"inputBytes\":18446744073709551615,\"outputBytes\":0,\"wallTimeMillis\":0}}}", 0UL, "lsf-provider-binding-v1", new Profile.CapabilityPolicyRecordKind(2), "", false), 18446744073709551615UL, "operation-binding");
            Check(value.Policy is not null, "apply-binding-max-precondition-and-opaque-limit-document.policy.presence");
            Check(value.Policy!.Id == "binding-a", "apply-binding-max-precondition-and-opaque-limit-document.policy.id");
            Check(value.Policy!.Metadata is not null, "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.presence");
            Check(value.Policy!.Metadata!.Name == "binding-a", "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.name");
            Check(value.Policy!.Metadata!.Tenant is not null, "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.tenant.presence");
            Check(value.Policy!.Metadata!.Tenant! == "tenant-a", "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.tenant");
            Check(!(value.Policy!.Metadata!.Namespace is not null), "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.namespace.presence");
            Check(value.Policy!.Metadata!.Labels.Count == 0, "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.labels.count");
            Check(value.Policy!.Metadata!.Annotations.Count == 0, "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.annotations.count");
            Check(value.Policy!.Document == "{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"capability\":\"latent:secrets/reader@0.1.0\",\"providerProfile\":\"local-secrets-v1\",\"configurationDigest\":\"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\",\"configurationEpoch\":18446744073709551615,\"restriction\":{\"operations\":[],\"ceiling\":{\"operations\":0,\"inputBytes\":18446744073709551615,\"outputBytes\":0,\"wallTimeMillis\":0}}}", "apply-binding-max-precondition-and-opaque-limit-document.policy.document");
            Check(value.Policy!.Generation == 0UL, "apply-binding-max-precondition-and-opaque-limit-document.policy.generation");
            Check(value.Policy!.Language == "lsf-provider-binding-v1", "apply-binding-max-precondition-and-opaque-limit-document.policy.language");
            Check(value.Policy!.RecordKind.Value == 2, "apply-binding-max-precondition-and-opaque-limit-document.policy.record_kind");
            Check(value.Policy!.ContentDigest == "", "apply-binding-max-precondition-and-opaque-limit-document.policy.content_digest");
            Check(value.Policy!.Revoked == false, "apply-binding-max-precondition-and-opaque-limit-document.policy.revoked");
            Check(value.ExpectedGeneration is not null, "apply-binding-max-precondition-and-opaque-limit-document.expected_generation.presence");
            Check(value.ExpectedGeneration!.Value == 18446744073709551615UL, "apply-binding-max-precondition-and-opaque-limit-document.expected_generation");
            Check(value.OperationId == "operation-binding", "apply-binding-max-precondition-and-opaque-limit-document.operation_id");
        }
        {
            var value = new Profile.ListPoliciesRequest(new Profile.CapabilityPolicyRecordKind(1), null);
            Check(value.RecordKind.Value == 1, "policy-page-absent.record_kind");
            Check(!(value.Page is not null), "policy-page-absent.page.presence");
        }
        {
            var value = new Profile.ListPoliciesRequest(new Profile.CapabilityPolicyRecordKind(2), new Profile.PageRequest(0U, null));
            Check(value.RecordKind.Value == 2, "policy-page-zero-invalid.record_kind");
            Check(value.Page is not null, "policy-page-zero-invalid.page.presence");
            Check(value.Page!.PageSize == 0U, "policy-page-zero-invalid.page.page_size");
            Check(!(value.Page!.PageToken is not null), "policy-page-zero-invalid.page.page_token.presence");
        }
        {
            var value = new Profile.ListPoliciesRequest(new Profile.CapabilityPolicyRecordKind(1), new Profile.PageRequest(1U, ""));
            Check(value.RecordKind.Value == 1, "policy-page-empty-token-invalid.record_kind");
            Check(value.Page is not null, "policy-page-empty-token-invalid.page.presence");
            Check(value.Page!.PageSize == 1U, "policy-page-empty-token-invalid.page.page_size");
            Check(value.Page!.PageToken is not null, "policy-page-empty-token-invalid.page.page_token.presence");
            Check(value.Page!.PageToken! == "", "policy-page-empty-token-invalid.page.page_token");
        }
        {
            var value = new Profile.ListPoliciesResponse(new Profile.Policy[] {new Profile.Policy("policy-a", null, "", 18446744073709551615UL, "", new Profile.CapabilityPolicyRecordKind(1), "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", true)}, 18446744073709551615UL, new Profile.PageResponse("opaque-policy-cursor"));
            Check(value.Policies.Count == 1, "policy-page-first.policies.count");
            Check(value.Policies[0].Id == "policy-a", "policy-page-first.policies.0.id");
            Check(!(value.Policies[0].Metadata is not null), "policy-page-first.policies.0.metadata.presence");
            Check(value.Policies[0].Document == "", "policy-page-first.policies.0.document");
            Check(value.Policies[0].Generation == 18446744073709551615UL, "policy-page-first.policies.0.generation");
            Check(value.Policies[0].Language == "", "policy-page-first.policies.0.language");
            Check(value.Policies[0].RecordKind.Value == 1, "policy-page-first.policies.0.record_kind");
            Check(value.Policies[0].ContentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "policy-page-first.policies.0.content_digest");
            Check(value.Policies[0].Revoked == true, "policy-page-first.policies.0.revoked");
            Check(value.CatalogGeneration == 18446744073709551615UL, "policy-page-first.catalog_generation");
            Check(value.Page is not null, "policy-page-first.page.presence");
            Check(value.Page!.NextPageToken is not null, "policy-page-first.page.next_page_token.presence");
            Check(value.Page!.NextPageToken! == "opaque-policy-cursor", "policy-page-first.page.next_page_token");
        }
        {
            var value = new Profile.ListPoliciesResponse(new Profile.Policy[] {}, 18446744073709551615UL, new Profile.PageResponse(null));
            Check(value.Policies.Count == 0, "policy-page-last.policies.count");
            Check(value.CatalogGeneration == 18446744073709551615UL, "policy-page-last.catalog_generation");
            Check(value.Page is not null, "policy-page-last.page.presence");
            Check(!(value.Page!.NextPageToken is not null), "policy-page-last.page.next_page_token.presence");
        }
        {
            var value = new Profile.ListPoliciesRequest(new Profile.CapabilityPolicyRecordKind(1), new Profile.PageRequest(1U, "opaque-policy-cursor"));
            Check(value.RecordKind.Value == 1, "policy-next-page-request.record_kind");
            Check(value.Page is not null, "policy-next-page-request.page.presence");
            Check(value.Page!.PageSize == 1U, "policy-next-page-request.page.page_size");
            Check(value.Page!.PageToken is not null, "policy-next-page-request.page.page_token.presence");
            Check(value.Page!.PageToken! == "opaque-policy-cursor", "policy-next-page-request.page.page_token");
        }
        {
            var value = new Profile.ApplyPolicyResponse(new Profile.Policy("policy-a", null, "", 18446744073709551615UL, "", new Profile.CapabilityPolicyRecordKind(1), "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", false), new Profile.CapabilityPolicyOperation("operation-a", "tenant-a", "policy-a", new Profile.CapabilityPolicyRecordKind(1), 18446744073709551615UL, "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", false));
            Check(value.Policy is not null, "apply-retains-original-receipt.policy.presence");
            Check(value.Policy!.Id == "policy-a", "apply-retains-original-receipt.policy.id");
            Check(!(value.Policy!.Metadata is not null), "apply-retains-original-receipt.policy.metadata.presence");
            Check(value.Policy!.Document == "", "apply-retains-original-receipt.policy.document");
            Check(value.Policy!.Generation == 18446744073709551615UL, "apply-retains-original-receipt.policy.generation");
            Check(value.Policy!.Language == "", "apply-retains-original-receipt.policy.language");
            Check(value.Policy!.RecordKind.Value == 1, "apply-retains-original-receipt.policy.record_kind");
            Check(value.Policy!.ContentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "apply-retains-original-receipt.policy.content_digest");
            Check(value.Policy!.Revoked == false, "apply-retains-original-receipt.policy.revoked");
            Check(value.Receipt is not null, "apply-retains-original-receipt.receipt.presence");
            Check(value.Receipt!.OperationId == "operation-a", "apply-retains-original-receipt.receipt.operation_id");
            Check(value.Receipt!.Tenant == "tenant-a", "apply-retains-original-receipt.receipt.tenant");
            Check(value.Receipt!.Id == "policy-a", "apply-retains-original-receipt.receipt.id");
            Check(value.Receipt!.RecordKind.Value == 1, "apply-retains-original-receipt.receipt.record_kind");
            Check(value.Receipt!.Generation == 18446744073709551615UL, "apply-retains-original-receipt.receipt.generation");
            Check(value.Receipt!.ContentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "apply-retains-original-receipt.receipt.content_digest");
            Check(value.Receipt!.Revoked == false, "apply-retains-original-receipt.receipt.revoked");
        }
        {
            var value = new Profile.GetPolicyOperationRequest("operation-a");
            Check(value.OperationId == "operation-a", "get-policy-operation-known-id.operation_id");
        }
        {
            var value = new Profile.GetPolicyOperationResponse(null);
            Check(!(value.Receipt is not null), "operation-recovery-not-retained-is-unknown.receipt.presence");
        }
        {
            var value = new Profile.GetPolicyOperationResponse(new Profile.CapabilityPolicyOperation("operation-a", "tenant-a", "policy-a", new Profile.CapabilityPolicyRecordKind(1), 18446744073709551615UL, "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", false));
            Check(value.Receipt is not null, "operation-recovery-original-receipt.receipt.presence");
            Check(value.Receipt!.OperationId == "operation-a", "operation-recovery-original-receipt.receipt.operation_id");
            Check(value.Receipt!.Tenant == "tenant-a", "operation-recovery-original-receipt.receipt.tenant");
            Check(value.Receipt!.Id == "policy-a", "operation-recovery-original-receipt.receipt.id");
            Check(value.Receipt!.RecordKind.Value == 1, "operation-recovery-original-receipt.receipt.record_kind");
            Check(value.Receipt!.Generation == 18446744073709551615UL, "operation-recovery-original-receipt.receipt.generation");
            Check(value.Receipt!.ContentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "operation-recovery-original-receipt.receipt.content_digest");
            Check(value.Receipt!.Revoked == false, "operation-recovery-original-receipt.receipt.revoked");
        }
        {
            var value = new Profile.ListCapabilitiesRequest(null, null, null, "deployment-a", false);
            Check(!(value.ContractPrefix is not null), "capabilities-absent-page-default.contract_prefix.presence");
            Check(!(value.Provider is not null), "capabilities-absent-page-default.provider.presence");
            Check(!(value.Page is not null), "capabilities-absent-page-default.page.presence");
            Check(value.DeploymentId == "deployment-a", "capabilities-absent-page-default.deployment_id");
            Check(value.IncludeNodeUsage == false, "capabilities-absent-page-default.include_node_usage");
        }
        {
            var value = new Profile.ListCapabilitiesRequest(null, null, new Profile.PageRequest(0U, null), "deployment-a", false);
            Check(!(value.ContractPrefix is not null), "capabilities-zero-page-default.contract_prefix.presence");
            Check(!(value.Provider is not null), "capabilities-zero-page-default.provider.presence");
            Check(value.Page is not null, "capabilities-zero-page-default.page.presence");
            Check(value.Page!.PageSize == 0U, "capabilities-zero-page-default.page.page_size");
            Check(!(value.Page!.PageToken is not null), "capabilities-zero-page-default.page.page_token.presence");
            Check(value.DeploymentId == "deployment-a", "capabilities-zero-page-default.deployment_id");
            Check(value.IncludeNodeUsage == false, "capabilities-zero-page-default.include_node_usage");
        }
        {
            var value = new Profile.ListCapabilitiesRequest("", "", new Profile.PageRequest(128U, null), "deployment-a", true);
            Check(value.ContractPrefix is not null, "capabilities-present-empty-filters.contract_prefix.presence");
            Check(value.ContractPrefix! == "", "capabilities-present-empty-filters.contract_prefix");
            Check(value.Provider is not null, "capabilities-present-empty-filters.provider.presence");
            Check(value.Provider! == "", "capabilities-present-empty-filters.provider");
            Check(value.Page is not null, "capabilities-present-empty-filters.page.presence");
            Check(value.Page!.PageSize == 128U, "capabilities-present-empty-filters.page.page_size");
            Check(!(value.Page!.PageToken is not null), "capabilities-present-empty-filters.page.page_token.presence");
            Check(value.DeploymentId == "deployment-a", "capabilities-present-empty-filters.deployment_id");
            Check(value.IncludeNodeUsage == true, "capabilities-present-empty-filters.include_node_usage");
        }
        {
            var value = new Profile.ListCapabilitiesRequest(null, null, new Profile.PageRequest(1U, null), "", false);
            Check(!(value.ContractPrefix is not null), "capabilities-explicit-deployment-required.contract_prefix.presence");
            Check(!(value.Provider is not null), "capabilities-explicit-deployment-required.provider.presence");
            Check(value.Page is not null, "capabilities-explicit-deployment-required.page.presence");
            Check(value.Page!.PageSize == 1U, "capabilities-explicit-deployment-required.page.page_size");
            Check(!(value.Page!.PageToken is not null), "capabilities-explicit-deployment-required.page.page_token.presence");
            Check(value.DeploymentId == "", "capabilities-explicit-deployment-required.deployment_id");
            Check(value.IncludeNodeUsage == false, "capabilities-explicit-deployment-required.include_node_usage");
        }
        {
            var value = new Profile.ListCapabilitiesRequest(null, null, new Profile.PageRequest(4294967295U, null), "deployment-a", false);
            Check(!(value.ContractPrefix is not null), "capabilities-page-too-large.contract_prefix.presence");
            Check(!(value.Provider is not null), "capabilities-page-too-large.provider.presence");
            Check(value.Page is not null, "capabilities-page-too-large.page.presence");
            Check(value.Page!.PageSize == 4294967295U, "capabilities-page-too-large.page.page_size");
            Check(!(value.Page!.PageToken is not null), "capabilities-page-too-large.page.page_token.presence");
            Check(value.DeploymentId == "deployment-a", "capabilities-page-too-large.deployment_id");
            Check(value.IncludeNodeUsage == false, "capabilities-page-too-large.include_node_usage");
        }
        {
            var value = new Profile.ListCapabilitiesResponse(new Profile.CapabilityDescriptor[] {new Profile.CapabilityDescriptor("latent:secrets/reader@0.1.0", "latent:secrets/reader@0.1.0", "local-secrets-v1", new string[] {"read"}, new Dictionary<string, string> {}, new Profile.CapabilityBindingInspection("", new Profile.CapabilityInspectionPolicy("binding-a", 18446744073709551615UL, "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"), new Profile.CapabilityInspectionPolicy[] {new Profile.CapabilityInspectionPolicy("policy-a", 9223372036854775808UL, "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")}, "local-secrets-v1", "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", 18446744073709551615UL, "provider-configuration-changed")), new Profile.CapabilityDescriptor("future-capability", "future-contract", "future-provider", new string[] {}, new Dictionary<string, string> {{"descriptive", "not-authority"}}, null)}, new Profile.PageResponse("opaque-capability-cursor"), new Profile.CapabilityInspectionRevision("deployment-a", "revision-a", "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", 18446744073709551615UL, 9223372036854775808UL), new Profile.CapabilityResourceUsage("tenant", new Dictionary<string, ulong> {{"sessions", 18446744073709551615UL}, {"calls", 0UL}}, new string[] {"fixture-owner-unavailable"}), null, "sampled");
            Check(value.Capabilities.Count == 2, "redacted-capability-provider-inspection.capabilities.count");
            Check(value.Capabilities[0].Id == "latent:secrets/reader@0.1.0", "redacted-capability-provider-inspection.capabilities.0.id");
            Check(value.Capabilities[0].Contract == "latent:secrets/reader@0.1.0", "redacted-capability-provider-inspection.capabilities.0.contract");
            Check(value.Capabilities[0].Provider == "local-secrets-v1", "redacted-capability-provider-inspection.capabilities.0.provider");
            Check(value.Capabilities[0].Operations.Count == 1, "redacted-capability-provider-inspection.capabilities.0.operations.count");
            Check(value.Capabilities[0].Operations[0] == "read", "redacted-capability-provider-inspection.capabilities.0.operations.0");
            Check(value.Capabilities[0].Attributes.Count == 0, "redacted-capability-provider-inspection.capabilities.0.attributes.count");
            Check(value.Capabilities[0].Inspection is not null, "redacted-capability-provider-inspection.capabilities.0.inspection.presence");
            Check(value.Capabilities[0].Inspection!.DefinitionDigest is not null, "redacted-capability-provider-inspection.capabilities.0.inspection.definition_digest.presence");
            Check(value.Capabilities[0].Inspection!.DefinitionDigest! == "", "redacted-capability-provider-inspection.capabilities.0.inspection.definition_digest");
            Check(value.Capabilities[0].Inspection!.ProviderBinding is not null, "redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.presence");
            Check(value.Capabilities[0].Inspection!.ProviderBinding!.Id == "binding-a", "redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.id");
            Check(value.Capabilities[0].Inspection!.ProviderBinding!.Revision == 18446744073709551615UL, "redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.revision");
            Check(value.Capabilities[0].Inspection!.ProviderBinding!.Digest == "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.digest");
            Check(value.Capabilities[0].Inspection!.Policies.Count == 1, "redacted-capability-provider-inspection.capabilities.0.inspection.policies.count");
            Check(value.Capabilities[0].Inspection!.Policies[0].Id == "policy-a", "redacted-capability-provider-inspection.capabilities.0.inspection.policies.0.id");
            Check(value.Capabilities[0].Inspection!.Policies[0].Revision == 9223372036854775808UL, "redacted-capability-provider-inspection.capabilities.0.inspection.policies.0.revision");
            Check(value.Capabilities[0].Inspection!.Policies[0].Digest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "redacted-capability-provider-inspection.capabilities.0.inspection.policies.0.digest");
            Check(value.Capabilities[0].Inspection!.ProviderProfile == "local-secrets-v1", "redacted-capability-provider-inspection.capabilities.0.inspection.provider_profile");
            Check(value.Capabilities[0].Inspection!.ProviderConfigurationDigest == "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "redacted-capability-provider-inspection.capabilities.0.inspection.provider_configuration_digest");
            Check(value.Capabilities[0].Inspection!.ProviderConfigurationEpoch == 18446744073709551615UL, "redacted-capability-provider-inspection.capabilities.0.inspection.provider_configuration_epoch");
            Check(value.Capabilities[0].Inspection!.State == "provider-configuration-changed", "redacted-capability-provider-inspection.capabilities.0.inspection.state");
            Check(value.Capabilities[1].Id == "future-capability", "redacted-capability-provider-inspection.capabilities.1.id");
            Check(value.Capabilities[1].Contract == "future-contract", "redacted-capability-provider-inspection.capabilities.1.contract");
            Check(value.Capabilities[1].Provider == "future-provider", "redacted-capability-provider-inspection.capabilities.1.provider");
            Check(value.Capabilities[1].Operations.Count == 0, "redacted-capability-provider-inspection.capabilities.1.operations.count");
            Check(value.Capabilities[1].Attributes.Count == 1, "redacted-capability-provider-inspection.capabilities.1.attributes.count");
            Check(value.Capabilities[1].Attributes["descriptive"] == "not-authority", "redacted-capability-provider-inspection.capabilities.1.attributes.0");
            Check(!(value.Capabilities[1].Inspection is not null), "redacted-capability-provider-inspection.capabilities.1.inspection.presence");
            Check(value.Page is not null, "redacted-capability-provider-inspection.page.presence");
            Check(value.Page!.NextPageToken is not null, "redacted-capability-provider-inspection.page.next_page_token.presence");
            Check(value.Page!.NextPageToken! == "opaque-capability-cursor", "redacted-capability-provider-inspection.page.next_page_token");
            Check(value.Revision is not null, "redacted-capability-provider-inspection.revision.presence");
            Check(value.Revision!.DeploymentId == "deployment-a", "redacted-capability-provider-inspection.revision.deployment_id");
            Check(value.Revision!.RevisionId == "revision-a", "redacted-capability-provider-inspection.revision.revision_id");
            Check(value.Revision!.ComponentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "redacted-capability-provider-inspection.revision.component_digest");
            Check(value.Revision!.PublicationId is not null, "redacted-capability-provider-inspection.revision.publication_id.presence");
            Check(value.Revision!.PublicationId! == "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", "redacted-capability-provider-inspection.revision.publication_id");
            Check(value.Revision!.RouteGeneration == 18446744073709551615UL, "redacted-capability-provider-inspection.revision.route_generation");
            Check(value.Revision!.CatalogTransaction == 9223372036854775808UL, "redacted-capability-provider-inspection.revision.catalog_transaction");
            Check(value.TenantUsage is not null, "redacted-capability-provider-inspection.tenant_usage.presence");
            Check(value.TenantUsage!.Scope == "tenant", "redacted-capability-provider-inspection.tenant_usage.scope");
            Check(value.TenantUsage!.Counters.Count == 2, "redacted-capability-provider-inspection.tenant_usage.counters.count");
            Check(value.TenantUsage!.Counters["sessions"] == 18446744073709551615UL, "redacted-capability-provider-inspection.tenant_usage.counters.0");
            Check(value.TenantUsage!.Counters["calls"] == 0UL, "redacted-capability-provider-inspection.tenant_usage.counters.1");
            Check(value.TenantUsage!.Unavailable.Count == 1, "redacted-capability-provider-inspection.tenant_usage.unavailable.count");
            Check(value.TenantUsage!.Unavailable[0] == "fixture-owner-unavailable", "redacted-capability-provider-inspection.tenant_usage.unavailable.0");
            Check(!(value.NodeUsage is not null), "redacted-capability-provider-inspection.node_usage.presence");
            Check(value.State == "sampled", "redacted-capability-provider-inspection.state");
        }
        {
            var value = new Profile.ListCapabilitiesResponse(new Profile.CapabilityDescriptor[] {}, null, null, null, new Profile.CapabilityResourceUsage("node", new Dictionary<string, ulong> {}, new string[] {"provider-pools-no-retained-owner", "audit-owner-not-configured"}), "binding-plan-unavailable");
            Check(value.Capabilities.Count == 0, "missing-provider-plan-not-zero-usage.capabilities.count");
            Check(!(value.Page is not null), "missing-provider-plan-not-zero-usage.page.presence");
            Check(!(value.Revision is not null), "missing-provider-plan-not-zero-usage.revision.presence");
            Check(!(value.TenantUsage is not null), "missing-provider-plan-not-zero-usage.tenant_usage.presence");
            Check(value.NodeUsage is not null, "missing-provider-plan-not-zero-usage.node_usage.presence");
            Check(value.NodeUsage!.Scope == "node", "missing-provider-plan-not-zero-usage.node_usage.scope");
            Check(value.NodeUsage!.Counters.Count == 0, "missing-provider-plan-not-zero-usage.node_usage.counters.count");
            Check(value.NodeUsage!.Unavailable.Count == 2, "missing-provider-plan-not-zero-usage.node_usage.unavailable.count");
            Check(value.NodeUsage!.Unavailable[0] == "provider-pools-no-retained-owner", "missing-provider-plan-not-zero-usage.node_usage.unavailable.0");
            Check(value.NodeUsage!.Unavailable[1] == "audit-owner-not-configured", "missing-provider-plan-not-zero-usage.node_usage.unavailable.1");
            Check(value.State == "binding-plan-unavailable", "missing-provider-plan-not-zero-usage.state");
        }
        {
            var value = new Profile.CapabilityInspectionCeiling(0U, 18446744073709551615UL, 0UL, 18446744073709551615UL);
            Check(value.Operations == 0U, "typed-ceiling-zero-and-max-not-grant.operations");
            Check(value.InputBytes == 18446744073709551615UL, "typed-ceiling-zero-and-max-not-grant.input_bytes");
            Check(value.OutputBytes == 0UL, "typed-ceiling-zero-and-max-not-grant.output_bytes");
            Check(value.WallTimeMillis == 18446744073709551615UL, "typed-ceiling-zero-and-max-not-grant.wall_time_millis");
        }
        {
            var value = new Profile.CallOptions(null);
            Check(!(value.TimeoutMillis is not null), "local-timeout-absent.timeout_millis.presence");
        }
        {
            var value = new Profile.CallOptions(0UL);
            Check(value.TimeoutMillis is not null, "local-timeout-zero.timeout_millis.presence");
            Check(value.TimeoutMillis!.Value == 0UL, "local-timeout-zero.timeout_millis");
        }
        {
            var value = new Profile.CallOptions(18446744073709551615UL);
            Check(value.TimeoutMillis is not null, "local-timeout-max-not-wrapped.timeout_millis.presence");
            Check(value.TimeoutMillis!.Value == 18446744073709551615UL, "local-timeout-max-not-wrapped.timeout_millis");
        }
        {
            var value = new Profile.ClientFailure(new Profile.FailureCategory(1), "local-cancelled", null, null, false, new Profile.OutcomeKnowledge(1), new Profile.RequestIdentity("activation-a", null), null, null, null, null);
            Check(value.Category.Value == 1, "local-cancel-before-dispatch.category");
            Check(value.Message == "local-cancelled", "local-cancel-before-dispatch.message");
            Check(!(value.GrpcStatus is not null), "local-cancel-before-dispatch.grpc_status.presence");
            Check(!(value.PlatformError is not null), "local-cancel-before-dispatch.platform_error.presence");
            Check(value.Dispatched == false, "local-cancel-before-dispatch.dispatched");
            Check(value.Outcome.Value == 1, "local-cancel-before-dispatch.outcome");
            Check(value.Identity.ActivationId is not null, "local-cancel-before-dispatch.identity.activation_id.presence");
            Check(value.Identity.ActivationId! == "activation-a", "local-cancel-before-dispatch.identity.activation_id");
            Check(!(value.Identity.OperationId is not null), "local-cancel-before-dispatch.identity.operation_id.presence");
            Check(!(value.AuditAck is not null), "local-cancel-before-dispatch.audit_ack.presence");
            Check(!(value.AuditStatus is not null), "local-cancel-before-dispatch.audit_status.presence");
            Check(!(value.UnsupportedWireValue is not null), "local-cancel-before-dispatch.unsupported_wire_value.presence");
            Check(!(value.AuditAttemptSequence is not null), "local-cancel-before-dispatch.audit_attempt_sequence.presence");
        }
        {
            var value = new Profile.ClientFailure(new Profile.FailureCategory(2), "deadline", 4, null, true, new Profile.OutcomeKnowledge(2), new Profile.RequestIdentity(null, "operation-a"), new Profile.AuditAck(new Profile.AuditAckStatus(2), 18446744073709551615UL), "outcome-unknown", null, 18446744073709551615UL);
            Check(value.Category.Value == 2, "deadline-after-dispatch-is-uncertain.category");
            Check(value.Message == "deadline", "deadline-after-dispatch-is-uncertain.message");
            Check(value.GrpcStatus is not null, "deadline-after-dispatch-is-uncertain.grpc_status.presence");
            Check(value.GrpcStatus!.Value == 4, "deadline-after-dispatch-is-uncertain.grpc_status");
            Check(!(value.PlatformError is not null), "deadline-after-dispatch-is-uncertain.platform_error.presence");
            Check(value.Dispatched == true, "deadline-after-dispatch-is-uncertain.dispatched");
            Check(value.Outcome.Value == 2, "deadline-after-dispatch-is-uncertain.outcome");
            Check(!(value.Identity.ActivationId is not null), "deadline-after-dispatch-is-uncertain.identity.activation_id.presence");
            Check(value.Identity.OperationId is not null, "deadline-after-dispatch-is-uncertain.identity.operation_id.presence");
            Check(value.Identity.OperationId! == "operation-a", "deadline-after-dispatch-is-uncertain.identity.operation_id");
            Check(value.AuditAck is not null, "deadline-after-dispatch-is-uncertain.audit_ack.presence");
            Check(value.AuditAck!.Status.Value == 2, "deadline-after-dispatch-is-uncertain.audit_ack.status");
            Check(value.AuditAck!.AttemptSequence is not null, "deadline-after-dispatch-is-uncertain.audit_ack.attempt_sequence.presence");
            Check(value.AuditAck!.AttemptSequence!.Value == 18446744073709551615UL, "deadline-after-dispatch-is-uncertain.audit_ack.attempt_sequence");
            Check(value.AuditStatus is not null, "deadline-after-dispatch-is-uncertain.audit_status.presence");
            Check(value.AuditStatus! == "outcome-unknown", "deadline-after-dispatch-is-uncertain.audit_status");
            Check(!(value.UnsupportedWireValue is not null), "deadline-after-dispatch-is-uncertain.unsupported_wire_value.presence");
            Check(value.AuditAttemptSequence is not null, "deadline-after-dispatch-is-uncertain.audit_attempt_sequence.presence");
            Check(value.AuditAttemptSequence!.Value == 18446744073709551615UL, "deadline-after-dispatch-is-uncertain.audit_attempt_sequence");
        }
        {
            var value = new Profile.ClientFailure(new Profile.FailureCategory(4), "capability-policy-conflict", 9, new Profile.PlatformError("state-conflict", "capability-policy-conflict", false, new Profile.ErrorDetail[] {new Profile.ErrorDetail("future-detail", new Dictionary<string, string> {{"value", "retained"}})}), true, new Profile.OutcomeKnowledge(3), new Profile.RequestIdentity(null, "operation-a"), null, null, null, null);
            Check(value.Category.Value == 4, "rpc-conflict-retains-request-identity.category");
            Check(value.Message == "capability-policy-conflict", "rpc-conflict-retains-request-identity.message");
            Check(value.GrpcStatus is not null, "rpc-conflict-retains-request-identity.grpc_status.presence");
            Check(value.GrpcStatus!.Value == 9, "rpc-conflict-retains-request-identity.grpc_status");
            Check(value.PlatformError is not null, "rpc-conflict-retains-request-identity.platform_error.presence");
            Check(value.PlatformError!.Code == "state-conflict", "rpc-conflict-retains-request-identity.platform_error.code");
            Check(value.PlatformError!.Message == "capability-policy-conflict", "rpc-conflict-retains-request-identity.platform_error.message");
            Check(value.PlatformError!.Retryable == false, "rpc-conflict-retains-request-identity.platform_error.retryable");
            Check(value.PlatformError!.DetailItems.Count == 1, "rpc-conflict-retains-request-identity.platform_error.detail_items.count");
            Check(value.PlatformError!.DetailItems[0].Kind == "future-detail", "rpc-conflict-retains-request-identity.platform_error.detail_items.0.kind");
            Check(value.PlatformError!.DetailItems[0].Fields.Count == 1, "rpc-conflict-retains-request-identity.platform_error.detail_items.0.fields.count");
            Check(value.PlatformError!.DetailItems[0].Fields["value"] == "retained", "rpc-conflict-retains-request-identity.platform_error.detail_items.0.fields.0");
            Check(value.Dispatched == true, "rpc-conflict-retains-request-identity.dispatched");
            Check(value.Outcome.Value == 3, "rpc-conflict-retains-request-identity.outcome");
            Check(!(value.Identity.ActivationId is not null), "rpc-conflict-retains-request-identity.identity.activation_id.presence");
            Check(value.Identity.OperationId is not null, "rpc-conflict-retains-request-identity.identity.operation_id.presence");
            Check(value.Identity.OperationId! == "operation-a", "rpc-conflict-retains-request-identity.identity.operation_id");
            Check(!(value.AuditAck is not null), "rpc-conflict-retains-request-identity.audit_ack.presence");
            Check(!(value.AuditStatus is not null), "rpc-conflict-retains-request-identity.audit_status.presence");
            Check(!(value.UnsupportedWireValue is not null), "rpc-conflict-retains-request-identity.unsupported_wire_value.presence");
            Check(!(value.AuditAttemptSequence is not null), "rpc-conflict-retains-request-identity.audit_attempt_sequence.presence");
        }
        {
            var value = new Profile.ClientFailure(new Profile.FailureCategory(5), "invalid-response", null, null, true, new Profile.OutcomeKnowledge(2), new Profile.RequestIdentity("activation-a", "operation-a"), null, null, new Profile.UnsupportedWireValue("phase", "future-phase-not-authority"), null);
            Check(value.Category.Value == 5, "decode-failure-retains-known-identity.category");
            Check(value.Message == "invalid-response", "decode-failure-retains-known-identity.message");
            Check(!(value.GrpcStatus is not null), "decode-failure-retains-known-identity.grpc_status.presence");
            Check(!(value.PlatformError is not null), "decode-failure-retains-known-identity.platform_error.presence");
            Check(value.Dispatched == true, "decode-failure-retains-known-identity.dispatched");
            Check(value.Outcome.Value == 2, "decode-failure-retains-known-identity.outcome");
            Check(value.Identity.ActivationId is not null, "decode-failure-retains-known-identity.identity.activation_id.presence");
            Check(value.Identity.ActivationId! == "activation-a", "decode-failure-retains-known-identity.identity.activation_id");
            Check(value.Identity.OperationId is not null, "decode-failure-retains-known-identity.identity.operation_id.presence");
            Check(value.Identity.OperationId! == "operation-a", "decode-failure-retains-known-identity.identity.operation_id");
            Check(!(value.AuditAck is not null), "decode-failure-retains-known-identity.audit_ack.presence");
            Check(!(value.AuditStatus is not null), "decode-failure-retains-known-identity.audit_status.presence");
            Check(value.UnsupportedWireValue is not null, "decode-failure-retains-known-identity.unsupported_wire_value.presence");
            Check(value.UnsupportedWireValue!.Field == "phase", "decode-failure-retains-known-identity.unsupported_wire_value.field");
            Check(value.UnsupportedWireValue!.Value == "future-phase-not-authority", "decode-failure-retains-known-identity.unsupported_wire_value.value");
            Check(!(value.AuditAttemptSequence is not null), "decode-failure-retains-known-identity.audit_attempt_sequence.presence");
        }
        {
            var value = new Profile.ResponseMetadata(new Profile.RequestIdentity(null, "operation-a"), new Profile.OutcomeKnowledge(3), new Profile.AuditAck(new Profile.AuditAckStatus(2), 18446744073709551615UL), "outcome-unknown", 18446744073709551615UL);
            Check(!(value.Identity.ActivationId is not null), "observed-receipt-audit-outcome-independent.identity.activation_id.presence");
            Check(value.Identity.OperationId is not null, "observed-receipt-audit-outcome-independent.identity.operation_id.presence");
            Check(value.Identity.OperationId! == "operation-a", "observed-receipt-audit-outcome-independent.identity.operation_id");
            Check(value.Outcome.Value == 3, "observed-receipt-audit-outcome-independent.outcome");
            Check(value.AuditAck is not null, "observed-receipt-audit-outcome-independent.audit_ack.presence");
            Check(value.AuditAck!.Status.Value == 2, "observed-receipt-audit-outcome-independent.audit_ack.status");
            Check(value.AuditAck!.AttemptSequence is not null, "observed-receipt-audit-outcome-independent.audit_ack.attempt_sequence.presence");
            Check(value.AuditAck!.AttemptSequence!.Value == 18446744073709551615UL, "observed-receipt-audit-outcome-independent.audit_ack.attempt_sequence");
            Check(value.AuditStatus is not null, "observed-receipt-audit-outcome-independent.audit_status.presence");
            Check(value.AuditStatus! == "outcome-unknown", "observed-receipt-audit-outcome-independent.audit_status");
            Check(value.AuditAttemptSequence is not null, "observed-receipt-audit-outcome-independent.audit_attempt_sequence.presence");
            Check(value.AuditAttemptSequence!.Value == 18446744073709551615UL, "observed-receipt-audit-outcome-independent.audit_attempt_sequence");
        }
        {
            var value = new Profile.ResponseMetadata(new Profile.RequestIdentity(null, "operation-a"), new Profile.OutcomeKnowledge(3), null, null, null);
            Check(!(value.Identity.ActivationId is not null), "policy-response-has-no-fabricated-audit.identity.activation_id.presence");
            Check(value.Identity.OperationId is not null, "policy-response-has-no-fabricated-audit.identity.operation_id.presence");
            Check(value.Identity.OperationId! == "operation-a", "policy-response-has-no-fabricated-audit.identity.operation_id");
            Check(value.Outcome.Value == 3, "policy-response-has-no-fabricated-audit.outcome");
            Check(!(value.AuditAck is not null), "policy-response-has-no-fabricated-audit.audit_ack.presence");
            Check(!(value.AuditStatus is not null), "policy-response-has-no-fabricated-audit.audit_status.presence");
            Check(!(value.AuditAttemptSequence is not null), "policy-response-has-no-fabricated-audit.audit_attempt_sequence.presence");
        }
        {
            var value = new Profile.ResponseMetadata(new Profile.RequestIdentity(null, "operation-a"), new Profile.OutcomeKnowledge(2), null, null, null);
            Check(!(value.Identity.ActivationId is not null), "missing-recovery-keeps-outcome-unknown.identity.activation_id.presence");
            Check(value.Identity.OperationId is not null, "missing-recovery-keeps-outcome-unknown.identity.operation_id.presence");
            Check(value.Identity.OperationId! == "operation-a", "missing-recovery-keeps-outcome-unknown.identity.operation_id");
            Check(value.Outcome.Value == 2, "missing-recovery-keeps-outcome-unknown.outcome");
            Check(!(value.AuditAck is not null), "missing-recovery-keeps-outcome-unknown.audit_ack.presence");
            Check(!(value.AuditStatus is not null), "missing-recovery-keeps-outcome-unknown.audit_status.presence");
            Check(!(value.AuditAttemptSequence is not null), "missing-recovery-keeps-outcome-unknown.audit_attempt_sequence.presence");
        }
        {
            var value = new Profile.ResponseMetadata(new Profile.RequestIdentity(null, "operation-a"), new Profile.OutcomeKnowledge(91), new Profile.AuditAck(new Profile.AuditAckStatus(91), 0UL), "future-audit-status", 0UL);
            Check(!(value.Identity.ActivationId is not null), "unknown-audit-enum-and-status.identity.activation_id.presence");
            Check(value.Identity.OperationId is not null, "unknown-audit-enum-and-status.identity.operation_id.presence");
            Check(value.Identity.OperationId! == "operation-a", "unknown-audit-enum-and-status.identity.operation_id");
            Check(value.Outcome.Value == 91, "unknown-audit-enum-and-status.outcome");
            Check(value.AuditAck is not null, "unknown-audit-enum-and-status.audit_ack.presence");
            Check(value.AuditAck!.Status.Value == 91, "unknown-audit-enum-and-status.audit_ack.status");
            Check(value.AuditAck!.AttemptSequence is not null, "unknown-audit-enum-and-status.audit_ack.attempt_sequence.presence");
            Check(value.AuditAck!.AttemptSequence!.Value == 0UL, "unknown-audit-enum-and-status.audit_ack.attempt_sequence");
            Check(value.AuditStatus is not null, "unknown-audit-enum-and-status.audit_status.presence");
            Check(value.AuditStatus! == "future-audit-status", "unknown-audit-enum-and-status.audit_status");
            Check(value.AuditAttemptSequence is not null, "unknown-audit-enum-and-status.audit_attempt_sequence.presence");
            Check(value.AuditAttemptSequence!.Value == 0UL, "unknown-audit-enum-and-status.audit_attempt_sequence");
        }
        {
            var value = new Profile.ResponseMetadata(new Profile.RequestIdentity(null, "operation-a"), new Profile.OutcomeKnowledge(3), null, "future-state", 18446744073709551615UL);
            Check(!(value.Identity.ActivationId is not null), "unknown-audit-header-and-max-attempt.identity.activation_id.presence");
            Check(value.Identity.OperationId is not null, "unknown-audit-header-and-max-attempt.identity.operation_id.presence");
            Check(value.Identity.OperationId! == "operation-a", "unknown-audit-header-and-max-attempt.identity.operation_id");
            Check(value.Outcome.Value == 3, "unknown-audit-header-and-max-attempt.outcome");
            Check(!(value.AuditAck is not null), "unknown-audit-header-and-max-attempt.audit_ack.presence");
            Check(value.AuditStatus is not null, "unknown-audit-header-and-max-attempt.audit_status.presence");
            Check(value.AuditStatus! == "future-state", "unknown-audit-header-and-max-attempt.audit_status");
            Check(value.AuditAttemptSequence is not null, "unknown-audit-header-and-max-attempt.audit_attempt_sequence.presence");
            Check(value.AuditAttemptSequence!.Value == 18446744073709551615UL, "unknown-audit-header-and-max-attempt.audit_attempt_sequence");
        }
        {
            var value = new Profile.ClientFailure(new Profile.FailureCategory(4), "rpc-failure", 13, null, true, new Profile.OutcomeKnowledge(2), new Profile.RequestIdentity(null, "operation-a"), null, "future-state", null, 18446744073709551615UL);
            Check(value.Category.Value == 4, "failed-rpc-unknown-audit-header-and-max-attempt.category");
            Check(value.Message == "rpc-failure", "failed-rpc-unknown-audit-header-and-max-attempt.message");
            Check(value.GrpcStatus is not null, "failed-rpc-unknown-audit-header-and-max-attempt.grpc_status.presence");
            Check(value.GrpcStatus!.Value == 13, "failed-rpc-unknown-audit-header-and-max-attempt.grpc_status");
            Check(!(value.PlatformError is not null), "failed-rpc-unknown-audit-header-and-max-attempt.platform_error.presence");
            Check(value.Dispatched == true, "failed-rpc-unknown-audit-header-and-max-attempt.dispatched");
            Check(value.Outcome.Value == 2, "failed-rpc-unknown-audit-header-and-max-attempt.outcome");
            Check(!(value.Identity.ActivationId is not null), "failed-rpc-unknown-audit-header-and-max-attempt.identity.activation_id.presence");
            Check(value.Identity.OperationId is not null, "failed-rpc-unknown-audit-header-and-max-attempt.identity.operation_id.presence");
            Check(value.Identity.OperationId! == "operation-a", "failed-rpc-unknown-audit-header-and-max-attempt.identity.operation_id");
            Check(!(value.AuditAck is not null), "failed-rpc-unknown-audit-header-and-max-attempt.audit_ack.presence");
            Check(value.AuditStatus is not null, "failed-rpc-unknown-audit-header-and-max-attempt.audit_status.presence");
            Check(value.AuditStatus! == "future-state", "failed-rpc-unknown-audit-header-and-max-attempt.audit_status");
            Check(!(value.UnsupportedWireValue is not null), "failed-rpc-unknown-audit-header-and-max-attempt.unsupported_wire_value.presence");
            Check(value.AuditAttemptSequence is not null, "failed-rpc-unknown-audit-header-and-max-attempt.audit_attempt_sequence.presence");
            Check(value.AuditAttemptSequence!.Value == 18446744073709551615UL, "failed-rpc-unknown-audit-header-and-max-attempt.audit_attempt_sequence");
        }
        {
            var value = new Profile.AuditAck(new Profile.AuditAckStatus(1), null);
            Check(value.Status.Value == 1, "audit-durable-attempt-absent.status");
            Check(!(value.AttemptSequence is not null), "audit-durable-attempt-absent.attempt_sequence.presence");
        }
        {
            var value = new Profile.AuditAck(new Profile.AuditAckStatus(3), 0UL);
            Check(value.Status.Value == 3, "audit-unavailable-attempt-zero.status");
            Check(value.AttemptSequence is not null, "audit-unavailable-attempt-zero.attempt_sequence.presence");
            Check(value.AttemptSequence!.Value == 0UL, "audit-unavailable-attempt-zero.attempt_sequence");
        }
        {
            var value = new Profile.AuditAck(new Profile.AuditAckStatus(4), null);
            Check(value.Status.Value == 4, "audit-disabled-distinct-from-absence.status");
            Check(!(value.AttemptSequence is not null), "audit-disabled-distinct-from-absence.attempt_sequence.presence");
        }
        {
            var value = new Profile.PublicationRef("", "tenant-a");
            Check(value.Id == "", "publication-reference-invalid-id.id");
            Check(value.Tenant == "tenant-a", "publication-reference-invalid-id.tenant");
        }
        {
            var value = new Profile.PublicationRef("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", "tenant-b");
            Check(value.Id == "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", "publication-reference-tenant-scope.id");
            Check(value.Tenant == "tenant-b", "publication-reference-tenant-scope.tenant");
        }
        {
            var value = new Profile.PublicationIdentity(new Profile.PublicationRef("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", "tenant-a"), "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "sha256:1111111111111111111111111111111111111111111111111111111111111111");
            Check(value.Publication.Id == "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", "publication-original-package.publication.id");
            Check(value.Publication.Tenant == "tenant-a", "publication-original-package.publication.tenant");
            Check(value.ComponentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "publication-original-package.component_digest");
            Check(value.PackageDigest == "sha256:1111111111111111111111111111111111111111111111111111111111111111", "publication-original-package.package_digest");
        }
        {
            var value = new Profile.PublicationIdentity(new Profile.PublicationRef("publication:sha256:2222222222222222222222222222222222222222222222222222222222222222", "tenant-a"), "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "sha256:2222222222222222222222222222222222222222222222222222222222222222");
            Check(value.Publication.Id == "publication:sha256:2222222222222222222222222222222222222222222222222222222222222222", "publication-corrected-package-same-component.publication.id");
            Check(value.Publication.Tenant == "tenant-a", "publication-corrected-package-same-component.publication.tenant");
            Check(value.ComponentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "publication-corrected-package-same-component.component_digest");
            Check(value.PackageDigest == "sha256:2222222222222222222222222222222222222222222222222222222222222222", "publication-corrected-package-same-component.package_digest");
        }
        {
            var value = new Profile.PublicationIdentity(new Profile.PublicationRef("publication:sha256:3333333333333333333333333333333333333333333333333333333333333333", "tenant-b"), "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "sha256:2222222222222222222222222222222222222222222222222222222222222222");
            Check(value.Publication.Id == "publication:sha256:3333333333333333333333333333333333333333333333333333333333333333", "publication-other-tenant-same-package.publication.id");
            Check(value.Publication.Tenant == "tenant-b", "publication-other-tenant-same-package.publication.tenant");
            Check(value.ComponentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "publication-other-tenant-same-package.component_digest");
            Check(value.PackageDigest == "sha256:2222222222222222222222222222222222222222222222222222222222222222", "publication-other-tenant-same-package.package_digest");
        }
        Check(Profile.UnsignedDecimal.Format(Profile.UnsignedDecimal.Parse("0")) == "0", "uint64 roundtrip");
        Check(Profile.UnsignedDecimal.Format(Profile.UnsignedDecimal.Parse("9007199254740993")) == "9007199254740993", "uint64 roundtrip");
        Check(Profile.UnsignedDecimal.Format(Profile.UnsignedDecimal.Parse("9223372036854775808")) == "9223372036854775808", "uint64 roundtrip");
        Check(Profile.UnsignedDecimal.Format(Profile.UnsignedDecimal.Parse("18446744073709551615")) == "18446744073709551615", "uint64 roundtrip");
        Rejects(() => Profile.UnsignedDecimal.Parse("18446744073709551616"));
        Rejects(() => Profile.UnsignedDecimal.Parse("-1"));
        Rejects(() => Profile.UnsignedDecimal.Parse("+1"));
        Rejects(() => Profile.UnsignedDecimal.Parse("01"));
        Rejects(() => Profile.UnsignedDecimal.Parse(" 1"));
        Rejects(() => Profile.UnsignedDecimal.Parse("1 "));
        Rejects(() => Profile.UnsignedDecimal.Parse("1.0"));
        Rejects(() => Profile.UnsignedDecimal.Parse("1e3"));
        Rejects(() => Profile.UnsignedDecimal.Parse(""));
        Rejects(() => Profile.UnsignedDecimal.Parse("1\u0000"));
        Rejects(() => Profile.UnsignedDecimal.Parse("1\n"));
        Rejects(() => Profile.UnsignedDecimal.Parse("1\r\n"));
        Console.WriteLine("shared profile vectors: 67");
    }
}
