using Google.Protobuf;
using Latent.Sdk.Transport;
using Profile = Latent.Sdk.Profile;
using Tx = Latent.Sdk.Transactions;
using Wire = global::Latent.Control.V1;

namespace Latent.Sdk.Transport.Tests;

internal static partial class Program
{
    private static async Task<Tx.TransactionFailure> TransactionFailure(Task operation, Profile.FailureCategory category, bool dispatched)
    {
        var failure = await TxFailure(operation, category); Check(failure.Transport.Dispatched == dispatched, "effect dispatch evidence changed"); return failure;
    }
    private static Tx.PlanEffectMutationRequest TxEffectMutation() => new(new(Tx.CurrentTransactionProfile.Create(), TxSelector, new string('a', 64), TxPublication),
        "effect-operation-a", Tx.StateMutationKind.RetryKnownFailedEffect, Enumerable.Repeat((byte)1, 32).ToArray(), TxDigest, "explicit redrive", 100);
    private static Tx.EffectManagementPlan TxEffectPlan(Tx.PlanEffectMutationRequest original) => new(original, Enumerable.Repeat((byte)2, 32).ToArray(),
        1, ulong.MaxValue, 1, 1, 2000, 1000, Tx.EffectDisposition.KnownFailure, Tx.EffectPlanSafety.KnownNonexecution, null);
    private static Tx.StateOperationReceipt TxEffectReceipt(Tx.EffectManagementPlan plan) => new(plan.Original!.OperationId, "effect-management-receipt",
        plan.Original.Mutation, TxNamespace, "operator-a", plan.Original.ExpectedVersion, Enumerable.Repeat((byte)3, 32).ToArray(), 1500,
        plan.Original.Effect!.EffectId, TxDigest, Tx.StateOperationDisposition.Committed,
        new(plan, plan.Before, Tx.EffectDisposition.RetryScheduled, Tx.EffectManagementFact.RedriveScheduled, null, null));

    private static async Task TransactionEffectPlanOriginalCasAndFacts()
    {
        await using Peer peer = await Peer.Start(async context =>
        {
            switch (context.Request.Path.Value!.Split('/')[^1])
            {
                case "PlanEffectMutation":
                    var original = (Tx.PlanEffectMutationRequest)ProfileCodec.FromWire(await Peer.Read<Wire.PlanEffectMutationRequest>(context), typeof(Tx.PlanEffectMutationRequest));
                    var plan = TxEffectPlan(original);
                    if (original.Reason == "bad-window") plan = plan with { ExpiresAtUnixMillis = 31001 };
                    await Peer.Reply(context, (Wire.PlanEffectMutationResponse)ProfileCodec.ToWire(new Tx.PlanEffectMutationResponse(plan, false,
                        original.Reason == "bad-audit" ? new(new(91), null) : null), new Wire.PlanEffectMutationResponse())); break;
                case "MutateState":
                    var mutation = (Tx.MutateStateRequest)ProfileCodec.FromWire(await Peer.Read<Wire.MutateStateRequest>(context), typeof(Tx.MutateStateRequest));
                    var receipt = TxEffectReceipt(mutation.EffectPlan!);
                    if (mutation.Reason == "forged-fact") receipt = receipt with { Effect = receipt.Effect! with { Fact = Tx.EffectManagementFact.ProviderConfirmed, ProviderReceipt = "forged-provider", ProviderObservedAtUnixMillis = 1400 } };
                    await Peer.Reply(context, (Wire.MutateStateResponse)ProfileCodec.ToWire(new Tx.MutateStateResponse(receipt, null, false), new Wire.MutateStateResponse())); break;
                case "GetStateOperationReceipt":
                    var recovery = (Tx.GetStateOperationReceiptRequest)ProfileCodec.FromWire(await Peer.Read<Wire.GetStateOperationReceiptRequest>(context), typeof(Tx.GetStateOperationReceiptRequest));
                    Check(recovery.Namespace!.AuthorizationPublication != recovery.OriginalEffectPlan!.Original!.Effect!.AuthorizationPublication, "recovery rewrote original publication");
                    await Peer.Reply(context, (Wire.GetStateOperationReceiptResponse)ProfileCodec.ToWire(new Tx.GetStateOperationReceiptResponse(TxEffectReceipt(recovery.OriginalEffectPlan), null, null), new Wire.GetStateOperationReceiptResponse())); break;
                default: throw new InvalidOperationException("unexpected effect RPC");
            }
        });
        await using BoundedClient client = await BoundedClient.ConnectAsync(Options(peer.Endpoint));
        var prepared = await client.PlanEffectMutationAsync(TxEffectMutation(), Defaults);
        Check(prepared.Metadata.Transport.Outcome == Profile.OutcomeKnowledge.Unknown && prepared.Metadata.Observed!.EffectPlan is not null, "plan supplied accepted outcome knowledge");
        var plan = prepared.Value.Plan!; var original = plan.Original!;
        var request = new Tx.MutateStateRequest(TxInspect, original.OperationId, original.Mutation, original.Effect!.EffectId,
            original.ExpectedVersion, original.ExpectedPolicyDigest, original.Reason, plan);
        var accepted = await client.MutateStateAsync(request, Defaults);
        Check(accepted.Metadata.Transport.Outcome == Profile.OutcomeKnowledge.Observed && accepted.Value.Receipt!.Effect!.Fact == Tx.EffectManagementFact.RedriveScheduled, "redrive receipt became provider confirmation");
        var current = TxInspect with { AuthorizationPublication = TxPublication with { Id = "publication:sha256:" + new string('c', 64) } };
        var recovered = await client.GetStateOperationReceiptAsync(new(current, original.OperationId, plan), Defaults);
        Check(recovered.Metadata.Identity.AuthorizationPublication == current.AuthorizationPublication && recovered.Metadata.Identity.EffectMutation!.Effect!.AuthorizationPublication == TxPublication,
            "fresh authority changed immutable plan recovery identity");
        int sent = peer.Requests.Values.Sum();
        await TransactionFailure(client.MutateStateAsync(request with { EffectPlan = null }, Defaults).AsTask(), Profile.FailureCategory.InvalidRequest, false);
        await TransactionFailure(client.MutateStateAsync(request with { ExpectedVersion = new byte[32] }, Defaults).AsTask(), Profile.FailureCategory.InvalidRequest, false);
        Check(peer.Requests.Values.Sum() == sent, "invalid plan dispatched");
        var audit = await TransactionFailure(client.PlanEffectMutationAsync(TxEffectMutation() with { Reason = "bad-audit" }, Defaults).AsTask(), Profile.FailureCategory.Decode, true);
        Check(audit.Transport.Outcome == Profile.OutcomeKnowledge.Unknown && audit.Observed!.EffectPlan is not null && audit.Identity.EffectPlan!.Original!.Reason == "bad-audit", "audit failure erased plan or made mutation known");
        await TransactionFailure(client.PlanEffectMutationAsync(TxEffectMutation() with { Reason = "bad-window" }, Defaults).AsTask(), Profile.FailureCategory.Decode, true);
        var forged = TxEffectPlan(TxEffectMutation() with { Reason = "forged-fact" });
        var failed = await TransactionFailure(client.MutateStateAsync(request with { Reason = "forged-fact", EffectPlan = forged }, Defaults).AsTask(), Profile.FailureCategory.Decode, true);
        Check(failed.Observed is null && peer.Requests.Values.Sum() == 6 && peer.Connections.Count == 1, "unsafe fact became observed or operation replayed");
    }
}
