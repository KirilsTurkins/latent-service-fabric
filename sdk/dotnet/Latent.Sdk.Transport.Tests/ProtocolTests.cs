using Google.Protobuf;
using Latent.Sdk.Transport;
using Microsoft.AspNetCore.Http;
using Profile = Latent.Sdk.Profile;
using WireControl = global::Latent.Control.V1;
using WireInvocation = global::Latent.Invocation.V1;

namespace Latent.Sdk.Transport.Tests;

internal static partial class Program
{
    private static async Task LostMutation()
    {
        WireControl.ApplyPolicyRequest? retained = null;
        int mutations = 0;
        await using Peer peer = await Peer.Start(async context =>
        {
            if (context.Request.Path.Value!.EndsWith("/ApplyPolicy"))
            {
                WireControl.ApplyPolicyRequest request = await Peer.Read<WireControl.ApplyPolicyRequest>(context);
                if (++mutations == 1) { retained = request.Clone(); context.Abort(); return; }
                if (!request.Equals(retained)) { await Peer.Error(context, "9"); return; }
                await Peer.Reply(context, new WireControl.ApplyPolicyResponse { Policy = StoredPolicy(), Receipt = Receipt() });
            }
            else
            {
                WireControl.GetPolicyOperationRequest request = await Peer.Read<WireControl.GetPolicyOperationRequest>(context);
                await Peer.Reply(context, new WireControl.GetPolicyOperationResponse { Receipt = retained is not null && request.OperationId == "operation-a" ? Receipt() : null });
            }
        });
        await using BoundedClient first = await BoundedClient.ConnectAsync(Options(peer.Endpoint));
        Profile.ClientFailure lost = await Failure(first.ApplyPolicyAsync(Apply(), Defaults).AsTask(), Profile.FailureCategory.Transport, true);
        Check(retained is not null && mutations == 1 && lost.Identity.OperationId == "operation-a" && lost.Outcome == Profile.OutcomeKnowledge.Unknown, "lost mutation retried or hid retention");
        await first.DisposeAsync();
        await using BoundedClient recovery = await BoundedClient.ConnectAsync(Options(peer.Endpoint));
        Check((await recovery.GetPolicyOperationAsync(new("operation-a"), Defaults)).Value.Receipt!.OperationId == "operation-a", "original receipt lookup failed");
        Check((await recovery.GetPolicyOperationAsync(new("not-retained"), Defaults)).Metadata.Outcome == Profile.OutcomeKnowledge.Unknown, "not-retained became proof of nonexecution");
        await recovery.ApplyPolicyAsync(Apply(), Defaults);
        Profile.ApplyPolicyRequest changed = Apply() with { Policy = Apply().Policy! with { Document = "{\"rules\": []}" } };
        Check((await Failure(recovery.ApplyPolicyAsync(changed, Defaults).AsTask(), Profile.FailureCategory.Rpc, true)).GrpcStatus == 9, "changed replay was silently repaired");
        Check(mutations == 3 && peer.Connections.Count == 2 && first.Snapshot().Reaped, "mutation recovery hid a resend or unreaped owner");
    }

    private static async Task MalformedAndBounds()
    {
        byte[] valid = Peer.Packet(Peer.Success().ToByteArray());
        byte[] compressed = valid.ToArray();
        compressed[0] = 1;
        (string Name, byte[] Packet, Profile.FailureCategory Category)[] cases =
        [
            ("compressed", compressed, Profile.FailureCategory.Decode),
            ("extra-frame", valid.Concat(valid).ToArray(), Profile.FailureCategory.Decode),
            ("oversized-prefix", [0, 127, 255, 255, 255], Profile.FailureCategory.Limit),
            ("truncated-frame", [0, 0, 0, 0, 9, 1], Profile.FailureCategory.Transport),
            ("bad-varint", Peer.Packet([255]), Profile.FailureCategory.Decode),
            ("contradictory-oneof", Peer.Packet([42, 0, 58, 0]), Profile.FailureCategory.Decode),
            ("missing-message", [], Profile.FailureCategory.Decode),
            ("missing-status", valid, Profile.FailureCategory.Decode),
            ("duplicate-status", valid, Profile.FailureCategory.Decode),
            ("wrong-media", valid, Profile.FailureCategory.Decode),
            ("redirect", valid, Profile.FailureCategory.Decode),
            ("encoding", valid, Profile.FailureCategory.Decode)
        ];
        foreach (var scenario in cases)
        {
            await using Peer peer = await Peer.Start(async context =>
            {
                context.Response.ContentType = scenario.Name == "wrong-media" ? "application/json" : "application/grpc+proto";
                if (scenario.Name != "missing-status") context.Response.Headers["grpc-status"] = "0";
                if (scenario.Name == "duplicate-status") context.Response.Headers.Append("grpc-status", "0");
                if (scenario.Name == "redirect") { context.Response.StatusCode = 302; context.Response.Headers.Location = "http://127.0.0.1:1"; }
                if (scenario.Name == "encoding") context.Response.Headers["grpc-encoding"] = "gzip";
                await context.Response.Body.WriteAsync(scenario.Packet, context.RequestAborted);
            });
            await using BoundedClient client = await BoundedClient.ConnectAsync(Options(peer.Endpoint));
            await Failure(client.InvokeAsync(Invoke(), Defaults).AsTask(), scenario.Category, true);
            Check(peer.Requests.Values.Sum() == 1, "malformed response caused replay: " + scenario.Name);
        }
        await using Peer limits = await Peer.Start(context =>
        {
            WireInvocation.InvokeResponse response = Peer.Success();
            for (int index = 0; index < 64; index++) response.Success.Metadata.Add("key-" + index, "bounded-value");
            return Peer.Reply(context, response);
        });
        await using BoundedClient bounded = await BoundedClient.ConnectAsync(Options(limits.Endpoint, response: 32));
        await Failure(bounded.InvokeAsync(Invoke(), Defaults).AsTask(), Profile.FailureCategory.Limit, true);
        await using BoundedClient graph = await BoundedClient.ConnectAsync(Options(limits.Endpoint, nodes: 32));
        await Failure(graph.InvokeAsync(Invoke(), Defaults).AsTask(), Profile.FailureCategory.Limit, false);
        await using BoundedClient responseGraph = await BoundedClient.ConnectAsync(Options(limits.Endpoint, nodes: 96));
        await Failure(responseGraph.InvokeAsync(Invoke(), Defaults).AsTask(), Profile.FailureCategory.Limit, true);
        int before = limits.Requests.Values.Sum();
        await Failure(bounded.ApplyPolicyAsync(Apply() with { ExpectedGeneration = null }, Defaults).AsTask(), Profile.FailureCategory.InvalidRequest, false);
        await Failure(bounded.ListPoliciesAsync(new(Profile.CapabilityPolicyRecordKind.Policy, new(0, null)), Defaults).AsTask(), Profile.FailureCategory.InvalidRequest, false);
        await Failure(bounded.ListCapabilitiesAsync(new(null, null, new(129, null), "deployment-a", false), Defaults).AsTask(), Profile.FailureCategory.InvalidRequest, false);
        Check(limits.Requests.Values.Sum() == before, "invalid management boundary dispatched");
    }

    private static async Task AuditAndRawStatus()
    {
        string? audit = null;
        string? attempt = null;
        string rpc = "0";
        bool duplicate = false;
        await using Peer peer = await Peer.Start(context =>
        {
            if (audit is not null) context.Response.Headers["latent-audit-status"] = audit;
            if (attempt is not null) context.Response.Headers["latent-audit-attempt"] = attempt;
            if (duplicate) context.Response.Headers.Append("latent-audit-attempt", "0");
            if (rpc != "0")
            {
                var error = new WireControl.PlatformError { Code = "permission-denied", Message = "redact " + Token };
                var item = new WireControl.ErrorDetail { Kind = "bounded" };
                item.Fields.Add("diagnostic", Token);
                error.DetailItems.Add(item);
                context.Response.Headers["grpc-status-details-bin"] = Convert.ToBase64String(error.ToByteArray());
                return Peer.Error(context, rpc);
            }
            if (context.Request.Path.Value!.EndsWith("/Cancel")) return Peer.Reply(context, new WireInvocation.CancelResponse { Disposition = (WireInvocation.CancelDisposition)(-2026) });
            WireControl.Policy policy = StoredPolicy();
            policy.RecordKind = (WireControl.CapabilityPolicyRecordKind)(-2026);
            return Peer.Reply(context, new WireControl.GetPolicyResponse { Policy = policy });
        });
        await using BoundedClient client = await BoundedClient.ConnectAsync(Options(peer.Endpoint));
        foreach (var scenario in new (string? Status, string? Attempt, int? Known)[]
        {
            (null, null, null), ("durable", "0", 1), ("outcome-unknown", "18446744073709551615", 2),
            ("audit-unavailable", null, 3), ("disabled", "0", 4), ("future-state", "18446744073709551615", null), (null, "0", null)
        })
        {
            audit = scenario.Status;
            attempt = scenario.Attempt;
            Profile.ClientResponse<Profile.GetPolicyResponse> response = await client.GetPolicyAsync(new("policy-a", Profile.CapabilityPolicyRecordKind.Policy), Defaults);
            Check(response.Value.Policy!.RecordKind.Value == -2026, "open management enum changed");
            Check(response.Metadata.AuditStatus == audit && response.Metadata.AuditAck?.Status.Value == scenario.Known &&
                response.Metadata.AuditAttemptSequence == (attempt is null ? null : Profile.UnsignedDecimal.Parse(attempt)), "audit absence, raw status, or independent attempt changed");
        }
        audit = "future-state";
        attempt = "18446744073709551615";
        foreach (string raw in new[] { "-2147483648", "-2026", "1", "3", "4", "5", "6", "7", "8", "9", "10", "12", "13", "14", "15", "16", "2026", "2147483647" })
        {
            rpc = raw;
            Profile.ClientFailure failure = await Failure(client.InvokeAsync(Invoke(), Defaults).AsTask(), raw == "4" ? Profile.FailureCategory.Deadline : Profile.FailureCategory.Rpc, true);
            Check(failure.GrpcStatus == int.Parse(raw) && failure.AuditAck is null && failure.AuditAttemptSequence == ulong.MaxValue, "raw RPC/audit evidence changed");
            Check(failure.Outcome == (raw is "3" or "5" or "6" or "7" or "9" or "10" or "12" or "16" ? Profile.OutcomeKnowledge.Observed : Profile.OutcomeKnowledge.Unknown), "RPC rejection knowledge changed");
            Check(failure.PlatformError is not null && !failure.PlatformError.Message.Contains(Token) && failure.PlatformError.DetailItems[0].Fields["diagnostic"] == "[redacted]", "credential was exposed in diagnostics");
        }
        rpc = "5";
        Profile.ClientFailure missing = await Failure(client.GetActivationAsync(new("activation-a"), Defaults).AsTask(), Profile.FailureCategory.Rpc, true);
        Check(missing.Outcome == Profile.OutcomeKnowledge.Unknown, "not-retained activation proved nonexecution");
        missing = await Failure(client.GetPolicyOperationAsync(new("operation-a"), Defaults).AsTask(), Profile.FailureCategory.Rpc, true);
        Check(missing.Outcome == Profile.OutcomeKnowledge.Unknown, "not-retained mutation proved nonexecution");
        rpc = "9";
        foreach (string uncertain in new[] { "outcome-unknown", "audit-unavailable" })
        {
            audit = uncertain;
            Profile.ClientFailure uncertainFailure = await Failure(client.ApplyPolicyAsync(Apply(), Defaults).AsTask(), Profile.FailureCategory.Rpc, true);
            Check(uncertainFailure.Outcome == Profile.OutcomeKnowledge.Unknown && uncertainFailure.AuditStatus == uncertain, "uncertain audit became an observed rejection");
        }
        rpc = "0";
        foreach (string invalid in new[] { "", "01", "-1", "18446744073709551616" })
        {
            attempt = invalid;
            await Failure(client.GetPolicyAsync(new("policy-a", Profile.CapabilityPolicyRecordKind.Policy), Defaults).AsTask(), Profile.FailureCategory.Decode, true);
        }
        attempt = "0";
        duplicate = true;
        await Failure(client.GetPolicyAsync(new("policy-a", Profile.CapabilityPolicyRecordKind.Policy), Defaults).AsTask(), Profile.FailureCategory.Decode, true);
        duplicate = false;
        audit = null;
        attempt = null;
        Check((await client.CancelAsync(new("activation-a", "explicit"), Defaults)).Value.Disposition.Value == -2026, "future cancellation enum was invented as success");
    }
}
