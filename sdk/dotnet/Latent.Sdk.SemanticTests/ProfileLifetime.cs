using Profile = Latent.Sdk.Profile;

namespace Latent.Sdk.SemanticTests;

internal static class ProfileLifetime
{
    private static void Check(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }

    private static Profile.ResponseMetadata Metadata(string? operationId, Profile.OutcomeKnowledge outcome) =>
        new(new Profile.RequestIdentity(null, operationId), outcome, null, null, null);

    private static Profile.ClientFailure Failure(string operationId, bool dispatched, Profile.FailureCategory category) =>
        new(category, "local-fixture-failure", null, null, dispatched,
            dispatched ? Profile.OutcomeKnowledge.Unknown : Profile.OutcomeKnowledge.NotDispatched,
            new Profile.RequestIdentity(null, operationId), null, null, null, null);

    private static ValueTask<Profile.ClientResponse<Response>> Reply<Response>(Response value) =>
        ValueTask.FromResult(new Profile.ClientResponse<Response>(value, Metadata(null, Profile.OutcomeKnowledge.Observed)));

    private sealed class FixtureClient : Profile.IClientProfile
    {
        internal int Writes;
        internal int Waiters;
        internal int Cancels;
        internal int Pages;
        private Profile.CapabilityPolicyOperation? receipt;
        private Profile.Policy? policy;

        public ValueTask<Profile.ClientResponse<Profile.InvokeResponse>> InvokeAsync(Profile.InvokeRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default) =>
            Reply(new Profile.InvokeResponse(request.ActivationId!, "revision-a", "component-a", 1,
                new Profile.Success(request.Payload.ToArray(), request.MediaType, null, Array.Empty<string>(), new Dictionary<string, string>()), null, null, null, null));

        public ValueTask<Profile.ClientResponse<Profile.CancelResponse>> CancelAsync(Profile.CancelRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default)
        {
            Cancels++;
            return Reply(new Profile.CancelResponse(Profile.CancelDisposition.Accepted, null));
        }

        public ValueTask<Profile.ClientResponse<Profile.ActivationStatus>> GetActivationAsync(Profile.GetActivationRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default) =>
            Reply(new Profile.ActivationStatus(request.ActivationId, "running", null, 0, new Dictionary<string, string>(), null, null, null, null, null));

        public ValueTask<Profile.ClientResponse<Profile.GetPolicyResponse>> GetPolicyAsync(Profile.GetPolicyRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default) =>
            Reply(new Profile.GetPolicyResponse(policy));

        public ValueTask<Profile.ClientResponse<Profile.ListPoliciesResponse>> ListPoliciesAsync(Profile.ListPoliciesRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default)
        {
            Pages++;
            return Reply(new Profile.ListPoliciesResponse(Array.Empty<Profile.Policy>(), 1, new Profile.PageResponse("opaque-next-page")));
        }

        public ValueTask<Profile.ClientResponse<Profile.ListCapabilitiesResponse>> ListCapabilitiesAsync(Profile.ListCapabilitiesRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default) =>
            Reply(new Profile.ListCapabilitiesResponse(Array.Empty<Profile.CapabilityDescriptor>(), null,
                new Profile.CapabilityInspectionRevision(request.DeploymentId, "revision-a", "component-a", null, 1, 1), null, null, "binding-plan-unavailable"));

        public async ValueTask<Profile.ClientResponse<Profile.ApplyPolicyResponse>> ApplyPolicyAsync(Profile.ApplyPolicyRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default)
        {
            if (cancellationToken.IsCancellationRequested)
                throw new Profile.ClientCancellationException(Failure(request.OperationId, false, Profile.FailureCategory.LocalCancelled), cancellationToken);
            if (options.TimeoutMillis == 0)
                throw new Profile.ClientException(Failure(request.OperationId, false, Profile.FailureCategory.Deadline));
            Check(request.ExpectedGeneration.HasValue && request.OperationId != "" && request.Policy is not null, "explicit mutation precondition");
            if (receipt is not null)
                return new(new Profile.ApplyPolicyResponse(null, receipt), Metadata(request.OperationId, Profile.OutcomeKnowledge.Observed));
            policy = request.Policy!;
            receipt = new Profile.CapabilityPolicyOperation(request.OperationId, "tenant-a", policy.Id, policy.RecordKind, ulong.MaxValue, "digest-a", false);
            Writes++;
            Waiters++;
            try
            {
                await Task.Delay(Timeout.Infinite, cancellationToken);
                throw new InvalidOperationException("fixture requires local cancellation");
            }
            catch (OperationCanceledException)
            {
                throw new Profile.ClientCancellationException(Failure(request.OperationId, true, Profile.FailureCategory.LocalCancelled), cancellationToken);
            }
            finally
            {
                Waiters--;
            }
        }

        public ValueTask<Profile.ClientResponse<Profile.GetPolicyOperationResponse>> GetPolicyOperationAsync(Profile.GetPolicyOperationRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default)
        {
            var found = receipt?.OperationId == request.OperationId ? receipt : null;
            return ValueTask.FromResult(new Profile.ClientResponse<Profile.GetPolicyOperationResponse>(new(found),
                Metadata(request.OperationId, found is null ? Profile.OutcomeKnowledge.Unknown : Profile.OutcomeKnowledge.Observed)));
        }
    }

    internal static async Task Run()
    {
        var client = new FixtureClient();
        Profile.IClientProfile profile = client;
        var options = new Profile.CallOptions(null);
        var policy = new Profile.Policy("policy-a", null, "{}", 0, "lsf-capability-policy-v1", Profile.CapabilityPolicyRecordKind.Policy, "", false);
        var request = new Profile.ApplyPolicyRequest(policy, 0, "operation-a");
        using var cancellation = new CancellationTokenSource();
        var pending = profile.ApplyPolicyAsync(request, options, cancellation.Token);
        Check(client.Writes == 1 && client.Waiters == 1, "server receipt precedes local completion");
        cancellation.Cancel();
        try
        {
            await pending.AsTask().WaitAsync(TimeSpan.FromSeconds(2));
            throw new InvalidOperationException("cancelled wait must fail");
        }
        catch (Profile.ClientCancellationException cancelled)
        {
            Check(cancelled.Failure.Dispatched && cancelled.Failure.Outcome == Profile.OutcomeKnowledge.Unknown, "local cancellation is not rollback");
            Check(cancelled.Failure.Identity.OperationId == "operation-a", "recovery identity survives");
        }
        Check(client.Waiters == 0 && client.Writes == 1 && client.Cancels == 0, "only local ownership ends");
        var recovered = await profile.GetPolicyOperationAsync(new("operation-a"), options);
        Check(recovered.Value.Receipt?.Generation == ulong.MaxValue && recovered.Metadata.AuditAck is null, "original receipt without invented audit");
        var unknown = await profile.GetPolicyOperationAsync(new("not-retained"), options);
        Check(unknown.Value.Receipt is null && unknown.Metadata.Outcome == Profile.OutcomeKnowledge.Unknown, "missing receipt remains unknown");
        await profile.ApplyPolicyAsync(request, options);
        Check(client.Writes == 1, "explicit replay does not mutate again");
        try
        {
            await profile.ApplyPolicyAsync(request, new(0));
            throw new InvalidOperationException("zero timeout must fail before dispatch");
        }
        catch (Profile.ClientException expired)
        {
            Check(!expired.Failure.Dispatched, "zero timeout stays local");
        }
        byte[] payload = [1, 2];
        var invocation = new Profile.InvokeRequest("activation-a", null, null, null, payload, "application/octet-stream", null, 0, null, null, new Dictionary<string, string>());
        var invoked = await profile.InvokeAsync(invocation, options);
        payload[0] = 99;
        Check(invoked.Value.Success!.Payload.Span[0] == 1, "returned bytes are owned");
        Check((await profile.CancelAsync(new("activation-a", "fixture"), options)).Value.Disposition == Profile.CancelDisposition.Accepted, "explicit remote Cancel");
        Check((await profile.GetActivationAsync(new("activation-a"), options)).Value.Phase == "running", "accepted does not imply cleanup");
        Check((await profile.GetPolicyAsync(new("policy-a", Profile.CapabilityPolicyRecordKind.Policy), options)).Value.Policy?.Id == "policy-a", "policy inspection");
        Check((await profile.ListPoliciesAsync(new(Profile.CapabilityPolicyRecordKind.Policy, new(1, null)), options)).Value.Page?.NextPageToken is not null && client.Pages == 1, "one bounded page without draining");
        Check((await profile.ListCapabilitiesAsync(new(null, null, null, "deployment-a", false), options)).Value.Revision?.DeploymentId == "deployment-a", "explicit deployment");
        Console.WriteLine("shared profile lifetime/recovery: passed");
    }
}
