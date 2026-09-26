using System.Runtime.InteropServices;
using Google.Protobuf;
using Latent.Sdk.Transport;
using Profile = Latent.Sdk.Profile;
using WireControl = global::Latent.Control.V1;
using WireInvocation = global::Latent.Invocation.V1;

namespace Latent.Sdk.Transport.Tests;

internal static partial class Program
{
    private static WireControl.Policy StoredPolicy() => new()
    {
        Id = "policy-a", Metadata = new() { Name = "policy-a", Tenant = "tenant-a" }, Generation = ulong.MaxValue,
        Language = "lsf-capability-policy-v1", RecordKind = WireControl.CapabilityPolicyRecordKind.Policy, ContentDigest = "digest-a", Document = "{\"limit\":18446744073709551615}"
    };

    private static WireControl.CapabilityPolicyOperation Receipt() => new()
    {
        OperationId = "operation-a", Id = "policy-a", Tenant = "tenant-a", Generation = ulong.MaxValue,
        RecordKind = WireControl.CapabilityPolicyRecordKind.Policy, ContentDigest = "digest-a"
    };

    private static async Task EightOperations()
    {
        await using Peer peer = await Peer.Start(async context =>
        {
            switch (context.Request.Path.Value!.Split('/')[^1])
            {
                case "Invoke":
                    WireInvocation.InvokeRequest invoke = await Peer.Read<WireInvocation.InvokeRequest>(context);
                    Check(invoke.Budget.CpuFuel == ulong.MaxValue && invoke.Budget.HasWallTimeLimitMillis && invoke.Budget.WallTimeLimitMillis == 0, "native unsigned/presence request changed");
                    WireInvocation.InvokeResponse response = Peer.Success(invoke.HasActivationId ? invoke.ActivationId : "server-assigned");
                    if (invoke.Target.Function == "declared") response.DeclaredError = new() { Code = "uncertain", Message = "guest-declared", Payload = ByteString.CopyFrom([0, 255]) };
                    if (invoke.Target.Function == "platform") response.PlatformFailure = new() { Code = "future-platform-code", Message = "typed-platform" };
                    await Peer.Reply(context, response);
                    break;
                case "Cancel":
                    WireInvocation.CancelRequest cancel = await Peer.Read<WireInvocation.CancelRequest>(context);
                    var cancelled = new WireInvocation.CancelResponse { Disposition = (WireInvocation.CancelDisposition)int.Parse(cancel.Reason) };
                    if (cancelled.Disposition == WireInvocation.CancelDisposition.AlreadyTerminal) cancelled.TerminalState = "completed";
                    await Peer.Reply(context, cancelled);
                    break;
                case "GetActivation":
                    WireInvocation.GetActivationRequest status = await Peer.Read<WireInvocation.GetActivationRequest>(context);
                    await Peer.Reply(context, new WireInvocation.ActivationStatus { ActivationId = status.ActivationId, Phase = "running", TerminalState = "completed",
                        Succeeded = new() { CommittedStateVersion = "" }, FinalConsumption = new() { BlobWriteBytes = ulong.MaxValue }, TerminalAtUnixMillis = 0 });
                    break;
                case "GetPolicy":
                    await Peer.Read<WireControl.GetPolicyRequest>(context);
                    await Peer.Reply(context, new WireControl.GetPolicyResponse { Policy = StoredPolicy() });
                    break;
                case "ListPolicies":
                    WireControl.ListPoliciesRequest page = await Peer.Read<WireControl.ListPoliciesRequest>(context);
                    Check(page.Page.HasPageToken && page.Page.PageToken == "opaque\0cursor", "opaque policy cursor changed");
                    var policies = new WireControl.ListPoliciesResponse { CatalogGeneration = ulong.MaxValue, Page = new() { NextPageToken = "" } };
                    policies.Policies.Add(StoredPolicy());
                    await Peer.Reply(context, policies);
                    break;
                case "ListCapabilities":
                    await Peer.Read<WireControl.ListCapabilitiesRequest>(context);
                    var capabilities = new WireControl.ListCapabilitiesResponse { State = "sampled", Page = new(), TenantUsage = new() { Scope = "tenant" } };
                    capabilities.TenantUsage.Counters.Add("bytes", ulong.MaxValue);
                    capabilities.TenantUsage.Unavailable.Add("provider");
                    capabilities.Capabilities.Add(new WireControl.CapabilityDescriptor { Id = "http", Provider = "redacted", Inspection = new() { ProviderConfigurationEpoch = ulong.MaxValue, State = "current" } });
                    await Peer.Reply(context, capabilities);
                    break;
                case "ApplyPolicy":
                    WireControl.ApplyPolicyRequest apply = await Peer.Read<WireControl.ApplyPolicyRequest>(context);
                    Check(apply.HasExpectedGeneration && apply.ExpectedGeneration == 0 && apply.OperationId == "operation-a", "mutation precondition or identity changed");
                    await Peer.Reply(context, new WireControl.ApplyPolicyResponse { Policy = StoredPolicy(), Receipt = Receipt() });
                    break;
                case "GetPolicyOperation":
                    WireControl.GetPolicyOperationRequest operation = await Peer.Read<WireControl.GetPolicyOperationRequest>(context);
                    await Peer.Reply(context, new WireControl.GetPolicyOperationResponse { Receipt = operation.OperationId == "operation-a" ? Receipt() : null });
                    break;
                default: throw new InvalidOperationException("unexpected RPC");
            }
        });
        await using BoundedClient client = await BoundedClient.ConnectAsync(Options(peer.Endpoint));
        Profile.ClientResponse<Profile.InvokeResponse> invoked = await client.InvokeAsync(Invoke(), Defaults);
        Check(invoked.Value.Success!.Payload.Span.SequenceEqual(new byte[] { 0, 255, 1, 128 }) && invoked.Value.RouteGeneration == ulong.MaxValue, "response bytes/u64 changed");
        Check(invoked.Metadata.AuditAck is null && invoked.Metadata.AuditStatus is null && invoked.Metadata.AuditAttemptSequence is null, "audit absence was invented");
        for (int disposition = 1; disposition <= 3; disposition++)
        {
            Profile.ClientResponse<Profile.CancelResponse> cancel = await client.CancelAsync(new("activation-a", disposition.ToString()), Defaults);
            Check(cancel.Value.Disposition.Value == disposition, "cancellation dispositions collapsed");
            if (disposition == 3) Check(cancel.Metadata.Outcome == Profile.OutcomeKnowledge.Unknown, "not-found proved nonexecution");
        }
        Profile.ActivationStatus status = (await client.GetActivationAsync(new("activation-a"), Defaults)).Value;
        Check(status.TerminalAtUnixMillis == 0 && status.FinalConsumption!.BlobWriteBytes == ulong.MaxValue, "terminal presence or full width changed");
        Check((await client.GetPolicyAsync(new("policy-a", Profile.CapabilityPolicyRecordKind.Policy), Defaults)).Value.Policy!.Generation == ulong.MaxValue, "policy generation narrowed");
        Profile.ListPoliciesResponse page = (await client.ListPoliciesAsync(new(Profile.CapabilityPolicyRecordKind.Policy, new(1, "opaque\0cursor")), Defaults)).Value;
        Check(page.Policies.Count == 1 && page.Page!.NextPageToken == "", "page presence changed or auto-drained");
        Profile.ListCapabilitiesResponse capabilities = (await client.ListCapabilitiesAsync(new(null, null, null, "deployment-a", false), Defaults)).Value;
        Check(capabilities.TenantUsage!.Counters["bytes"] == ulong.MaxValue && capabilities.TenantUsage.Unavailable.Single() == "provider", "provider counters or absent owner changed");
        Check((await client.ApplyPolicyAsync(Apply(), Defaults)).Value.Receipt!.OperationId == "operation-a", "mutation receipt identity changed");
        Check((await client.GetPolicyOperationAsync(new("operation-a"), Defaults)).Value.Receipt!.Generation == ulong.MaxValue, "operation recovery changed");
        Check((await client.GetPolicyOperationAsync(new("missing"), Defaults)).Metadata.Outcome == Profile.OutcomeKnowledge.Unknown, "missing operation became nonexecution");
        Profile.InvokeResponse second = (await client.InvokeAsync(Invoke(), Defaults)).Value;
        Check(MemoryMarshal.TryGetArray(invoked.Value.Success.Payload, out ArraySegment<byte> firstMemory) && MemoryMarshal.TryGetArray(second.Success!.Payload, out ArraySegment<byte> nextMemory) &&
            !ReferenceEquals(firstMemory.Array, nextMemory.Array), "response buffers alias another call");
        Check((await client.InvokeAsync(Invoke(null), Defaults)).Metadata.Identity.ActivationId == "server-assigned", "assigned identity not retained");
        foreach (string kind in new[] { "success", "declared", "platform" })
        {
            Profile.InvokeRequest input = Invoke() with { Target = Invoke().Target! with { Function = kind } };
            Profile.InvokeResponse outcome = (await client.InvokeAsync(input, Defaults)).Value;
            Check(kind switch { "success" => outcome.Success is not null, "declared" => outcome.DeclaredError is not null,
                _ => outcome.PlatformFailure is not null }, "profile outcome collapsed");
        }
        Check(peer.Requests.Count == 8 && peer.Connections.Count == 1, "eight generated operations did not reuse one TCP connection");
        await client.DisposeAsync();
        Check(client.Snapshot().Reaped, "successful connection did not reap");
    }
}
