using System.Globalization;
using Profile = Latent.Sdk.Profile;

namespace Latent.Sdk.Transport;

public sealed partial class BoundedClient : ILatentClient
{
    public ILatentClient Legacy => this;

    async ValueTask<InvocationOutcome> ILatentClient.InvokeAsync(InvokeRequest request, CancellationToken cancellationToken)
    {
        if (request is null || request.Options is null || request.Options.Budget is null || request.Target is null) throw ClientOptions.Invalid();
        ResourceBudget budget = request.Options.Budget;
        var input = new Profile.InvokeRequest(request.ActivationId, request.ParentActivationId, request.RootActivationId,
            new(request.Target.Tenant, request.Target.Service, request.Target.Contract, request.Target.Function, request.Target.Route),
            request.Payload, request.MediaType, request.Options.DeadlineUnixMillis, request.Options.Priority, request.Options.IdempotencyKey,
            new(budget.CpuFuel, budget.MemoryBytes, budget.ChildCalls, budget.OutboundRequests, budget.StateReadBytes, budget.StateWriteBytes,
                budget.BlobReadBytes, budget.BlobWriteBytes, budget.LogBytes, budget.EffectCount, budget.WallTimeLimitMillis), request.Options.Metadata);
        Profile.InvokeResponse response = (await InvokeAsync(input, new(null), cancellationToken).ConfigureAwait(false)).Value;
        BudgetConsumption consumption = LegacyConsumption(response.Consumption!);
        var receipt = new InvocationReceipt(response.ActivationId, response.RevisionId, response.ReleaseDigest, response.RouteGeneration, consumption, response.PublicationId);
        if (response.Success is Profile.Success success)
            return new InvocationOutcome.Succeeded(new(response.ActivationId, response.RevisionId, response.ReleaseDigest, response.RouteGeneration,
                success.Payload, success.MediaType, success.CommittedStateVersion, success.EffectIds, consumption, success.Metadata, response.PublicationId));
        if (response.DeclaredError is Profile.DeclaredError declared) return new InvocationOutcome.DeclaredFailure(receipt, LegacyDeclared(declared));
        return new InvocationOutcome.PlatformFailure(receipt, LegacyPlatform(response.PlatformFailure!));
    }

    async ValueTask<CancelResponse> ILatentClient.CancelAsync(string activationId, string reason, CancellationToken cancellationToken)
    {
        Profile.ClientResponse<Profile.CancelResponse> response = await CancelAsync(new(activationId, reason), new(null), cancellationToken).ConfigureAwait(false);
        CancelDisposition disposition = response.Value.Disposition.Value switch
        {
            1 => CancelDisposition.Accepted,
            2 => CancelDisposition.AlreadyTerminal,
            3 => CancelDisposition.NotFound,
            _ => throw new Profile.ClientException(new(Profile.FailureCategory.Decode, "legacy cancellation disposition is unsupported", 0, null, true,
                response.Metadata.Outcome, response.Metadata.Identity, response.Metadata.AuditAck, response.Metadata.AuditStatus,
                new("CancelDisposition", response.Value.Disposition.Value.ToString(CultureInfo.InvariantCulture)), response.Metadata.AuditAttemptSequence))
        };
        return new(disposition, response.Value.TerminalState);
    }

    async ValueTask<ActivationStatus> ILatentClient.GetActivationAsync(string activationId, CancellationToken cancellationToken)
    {
        Profile.ActivationStatus response = (await GetActivationAsync(new(activationId), new(null), cancellationToken).ConfigureAwait(false)).Value;
        RetainedInvocationOutcome? outcome = null;
        if (response.Succeeded is Profile.ActivationSuccessSummary success)
            outcome = new RetainedInvocationOutcome.Succeeded(success.CommittedStateVersion, success.EffectIds, success.Metadata);
        if (response.DeclaredError is Profile.DeclaredError declared) outcome = new RetainedInvocationOutcome.DeclaredFailure(LegacyDeclared(declared));
        if (response.PlatformFailure is Profile.PlatformError platform) outcome = new RetainedInvocationOutcome.PlatformFailure(LegacyPlatform(platform));
        return new(response.ActivationId, response.Phase, response.TerminalState, outcome,
            response.FinalConsumption is null ? null : LegacyConsumption(response.FinalConsumption), response.LastUpdatedUnixMillis, response.TerminalAtUnixMillis, response.Metadata);
    }

    private static BudgetConsumption LegacyConsumption(Profile.BudgetConsumption value) => new(value.CpuFuel, value.PeakMemoryBytes, value.WallTimeMicros,
        value.ChildCalls, value.OutboundRequests, value.StateReadBytes, value.StateWriteBytes, value.BlobReadBytes, value.BlobWriteBytes, value.LogBytes, value.EffectCount);
    private static DeclaredError LegacyDeclared(Profile.DeclaredError value) => new(value.Code, value.Message, value.Payload, value.MediaType, value.Metadata);
    private static PlatformFailure LegacyPlatform(Profile.PlatformError value) => new(value.Code, value.Message, value.Retryable,
        value.DetailItems.Select(item => new ErrorDetail(item.Kind, item.Fields)).ToArray());
}
