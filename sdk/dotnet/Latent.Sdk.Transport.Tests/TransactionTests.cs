using Google.Protobuf;
using Microsoft.AspNetCore.Http;
using Latent.Sdk.Transport;
using Profile = Latent.Sdk.Profile;
using Tx = Latent.Sdk.Transactions;
using WireControl = global::Latent.Control.V1;
using WireTx = global::Latent.Transaction.V1;

namespace Latent.Sdk.Transport.Tests;

internal static partial class Program
{
    private static readonly string TxDigest = "sha256:" + new string('a', 64);
    private static readonly Profile.PublicationRef TxPublication = new("publication:sha256:" + new string('b', 64), "tenant-a");
    private static readonly Tx.NamespaceSelector TxNamespace = new("tenant-a", "transactional-aggregate", "1");
    private static readonly Tx.CommandSelector TxSelector = new(TxNamespace, "update", "aggregate-a", "business-key-a", null);
    private static readonly Tx.InspectNamespaceRequest TxInspect = new(Tx.CurrentTransactionProfile.Create(), TxNamespace, TxPublication);
    private static Tx.LookupCommandRequest TxLookup(string? attempt = null) => new(Tx.CurrentTransactionProfile.Create(), TxSelector, attempt, TxPublication);
    private static Tx.InvokeCommandRequest TxInvoke() => new(Tx.CurrentTransactionProfile.Create(), Invoke() with { DeadlineUnixMillis = null }, TxSelector, "aggregate-input-v1",
        new[] { new Tx.ExpectedVersion(new byte[] { 0, 255 }, null, new byte[] { 1 }) }, null);
    private static Tx.SourceIdentity TxSource() => new(TxPublication.Id, "revision-a", TxDigest, ulong.MaxValue, TxDigest, TxDigest, "aggregate-input-v1", "aggregate-result-v1", TxDigest);
    private static WireTx.CommandInspection TxWireCommand(int outcome = 2, bool payload = true)
    {
        var source = TxSource();
        var wireSource = (WireTx.SourceIdentity)ProfileCodec.ToWire(source, new WireTx.SourceIdentity());
        var value = new WireTx.CommandInspection
        {
            Key = (WireTx.CommandKey)ProfileCodec.ToWire(new Tx.CommandKey(TxNamespace, "caller:subject-a", TxSelector.Operation, TxSelector.Entity, TxSelector.ClientKey), new WireTx.CommandKey()),
            CommandId = "command-a", AttemptId = "attempt-a", FingerprintSha256 = ByteString.CopyFrom(new byte[32]), Outcome = (WireTx.CommandOutcome)outcome,
            MetadataDurable = true, ApplicationStateCommitted = outcome == 2, Source = wireSource,
            Retention = new() { RecordFormat = "original-command-v1", RecordVersion = 1, PayloadAvailable = payload, RemainingRecoveryMillis = ulong.MaxValue }
        };
        value.Retention.RequiredRecordIds.Add("command-a");
        if (outcome == 2)
        {
            value.Success = payload ? Peer.Success().Success : null;
            value.Commit = new() { CommandId = value.CommandId, AttemptId = value.AttemptId, TransactionId = "transaction-a", ReceiptId = "receipt-a",
                CommittedVersion = ByteString.CopyFrom([1]), CommittedAtUnixMillis = ulong.MaxValue, Source = wireSource.Clone() };
            value.Commit.EffectIds.Add("effect-a");
        }
        if (outcome == 3 && payload) value.BusinessRejection = new() { Code = "business-rejected", Message = "expected rejection", Payload = ByteString.CopyFrom([0, 255]), MediaType = "application/octet-stream" };
        if (outcome == 4)
        {
            value.TechnicalFailure = new() { Code = "cancelled", Message = "physical owner retired" };
            value.ProvenAbort = new() { CommandId = value.CommandId, AttemptId = value.AttemptId, TransactionId = "transaction-a", OwnerFence = ByteString.CopyFrom([1, 2]) };
        }
        // Existing Invoke.Success uses an explicitly present empty stateless version;
        // the transaction receipt carries the separately versioned state identity.
        if (value.Success is not null) value.Success.ClearCommittedStateVersion();
        return value;
    }
    private static WireTx.EffectReceipt TxEffect() => new()
    {
        EffectId = "effect-a", CommandId = "command-a", CommandAttemptId = "attempt-a", ProviderProfile = "approved-provider-v1", DispatchAttempt = 1,
        Disposition = WireTx.EffectDisposition.ProviderAcknowledged, ProviderReceipt = "provider-receipt-a", OccurredAtUnixMillis = ulong.MaxValue
    };
    private static async Task<Tx.TransactionFailure> TxFailure(Task operation, Profile.FailureCategory category)
    {
        try { await operation.WaitAsync(TimeSpan.FromSeconds(4)); }
        catch (Tx.TransactionException failure) { Check(failure.Failure.Transport.Category == category, "unexpected transaction failure category " + failure.Failure.Transport.Category.Value); return failure.Failure; }
        catch (Tx.TransactionCancellationException failure) { Check(failure.Failure.Transport.Category == category, "unexpected transaction cancellation category"); return failure.Failure; }
        throw new InvalidOperationException("expected independent transaction failure facts");
    }

    // A real HTTP/2 serialization peer; this does not claim signed-node execution.
    private static async Task TransactionTwelveOperations()
    {
        await using Peer peer = await Peer.Start(async context =>
        {
            switch (context.Request.Path.Value!.Split('/')[^1])
            {
                case "InvokeCommand":
                    var invoked = await Peer.Read<WireTx.InvokeCommandRequest>(context);
                    Check(invoked.Command.ClientKey == "business-key-a" && invoked.ExpectedVersions[0].Version.Span.SequenceEqual(new byte[] { 1 }), "command identity/precondition changed");
                    var command = TxWireCommand(); command.Success.Payload = ByteString.CopyFrom(new byte[750 * 1024]);
                    var invocation = Peer.Success(); invocation.Success = command.Success.Clone();
                    await Peer.Reply(context, new WireTx.InvokeCommandResponse { Invocation = invocation, Command = command }); break;
                case "Query":
                    await Peer.Read<WireTx.QueryRequest>(context);
                    var queryInvocation = Peer.Success(); queryInvocation.Success.ClearCommittedStateVersion();
                    await Peer.Reply(context, new WireTx.QueryResponse { Invocation = queryInvocation, Source = (WireTx.SourceIdentity)ProfileCodec.ToWire(TxSource(), new WireTx.SourceIdentity()),
                        View = (WireTx.ViewIdentity)ProfileCodec.ToWire(new Tx.ViewIdentity(TxNamespace, new byte[] { 1 }, TxDigest), new WireTx.ViewIdentity()), ObservedAtUnixMillis = ulong.MaxValue }); break;
                case "LookupCommand": await Peer.Read<WireTx.LookupCommandRequest>(context); await Peer.Reply(context, new WireTx.LookupCommandResponse { Command = TxWireCommand() }); break;
                case "LookupCommit": await Peer.Read<WireTx.LookupCommitRequest>(context); await Peer.Reply(context, new WireTx.LookupCommitResponse { Command = TxWireCommand() }); break;
                case "GetEffect": await Peer.Read<WireTx.GetEffectRequest>(context); await Peer.Reply(context, new WireTx.GetEffectResponse { Effect = TxEffect() }); break;
                case "ListEffectHistory":
                    await Peer.Read<WireTx.ListEffectHistoryRequest>(context); var history = new WireTx.ListEffectHistoryResponse { Page = new() { ReturnedCount = 1, EncodedBytes = 128, NextCursor = ByteString.CopyFrom([1]) } };
                    history.Receipts.Add(TxEffect()); await Peer.Reply(context, history); break;
                case "CancelCommand": await Peer.Read<WireTx.CancelCommandRequest>(context); await Peer.Reply(context, new WireTx.CancelCommandResponse { Disposition = WireTx.CommandCancelDisposition.AlreadyCommitted, Command = TxWireCommand() }); break;
                case "InspectNamespace":
                    await Peer.Read<WireControl.InspectNamespaceRequest>(context);
                    await Peer.Reply(context, (WireControl.InspectNamespaceResponse)ProfileCodec.ToWire(new Tx.InspectNamespaceResponse(new(new(TxNamespace, new byte[] { 1 }, TxDigest),
                        1, 1, 1, Array.Empty<Tx.LinkedRetention>(), "redb-v1", TxDigest, Tx.NamespaceStatus.Active, new(1, 4096, 1, 4096, 1, 4096, 4096, 4096), ulong.MaxValue)), new WireControl.InspectNamespaceResponse())); break;
                case "SelectEntity":
                    await Peer.Read<WireControl.SelectEntityRequest>(context);
                    await Peer.Reply(context, (WireControl.SelectEntityResponse)ProfileCodec.ToWire(new Tx.SelectEntityResponse(new[] { new Tx.EntityInspection("aggregate-a", new byte[] { 1 }) }, new(new byte[] { 2 }, 1, 32)), new WireControl.SelectEntityResponse())); break;
                case "MutateState":
                    var mutation = await Peer.Read<WireControl.MutateStateRequest>(context);
                    await Peer.Reply(context, (WireControl.MutateStateResponse)ProfileCodec.ToWire(new Tx.MutateStateResponse(new(mutation.OperationId, "state-receipt-a", Tx.StateMutationKind.CheckpointNamespace,
                        TxNamespace, "operator-a", new byte[] { 1 }, new byte[] { 2 }, ulong.MaxValue, null, TxDigest, Tx.StateOperationDisposition.Committed), new(Profile.AuditAckStatus.Durable, ulong.MaxValue)), new WireControl.MutateStateResponse())); break;
                case "MutateNamespace":
                    var lifecycle = await Peer.Read<WireControl.MutateNamespaceRequest>(context);
                    Check(lifecycle.HasExpectedGeneration && lifecycle.ExpectedGeneration == ulong.MaxValue - 1, "generation precondition lost full width or presence");
                    await Peer.Reply(context, (WireControl.MutateNamespaceResponse)ProfileCodec.ToWire(new Tx.MutateNamespaceResponse(new(lifecycle.OperationId, "namespace-receipt-a", Tx.NamespaceMutationKind.Quiesce,
                        TxNamespace, "operator-a", ulong.MaxValue - 1, ulong.MaxValue, Tx.NamespaceStatus.Quiescing, TxDigest, Tx.StateOperationDisposition.Committed), false, null), new WireControl.MutateNamespaceResponse())); break;
                case "GetStateOperationReceipt":
                    await Peer.Read<WireControl.GetStateOperationReceiptRequest>(context);
                    await Peer.Reply(context, (WireControl.GetStateOperationReceiptResponse)ProfileCodec.ToWire(new Tx.GetStateOperationReceiptResponse(new("state-operation-a", "state-receipt-a", Tx.StateMutationKind.CheckpointNamespace,
                        TxNamespace, "operator-a", new byte[] { 1 }, new byte[] { 2 }, 0, null, TxDigest, Tx.StateOperationDisposition.Committed), null), new WireControl.GetStateOperationReceiptResponse())); break;
                default: throw new InvalidOperationException("unexpected transaction RPC");
            }
        });
        await using BoundedClient client = await BoundedClient.ConnectAsync(Options(peer.Endpoint, response: 2 * 1024 * 1024));
        var invoked = await client.InvokeCommandAsync(TxInvoke(), Defaults);
        Check(invoked.Metadata.Observed!.Command!.Commit!.ReceiptId == "receipt-a" && invoked.Metadata.Identity.CommandId == "command-a", "commit recovery data not independently retained");
        Check(invoked.Metadata.Observed.Command.Success is null && invoked.Metadata.Identity.FingerprintSha256!.Value.Length == 32, "observation retained application body or lost fingerprint");
        Check(invoked.Value.Invocation!.Success!.Payload.Length == 750 * 1024 && invoked.Value.Command!.Success!.Payload.Length == 750 * 1024,
            "valid bounded command/invocation result graph was rejected or truncated");
        var query = await client.QueryAsync(new(Tx.CurrentTransactionProfile.Create(), Invoke(), TxNamespace, null, new byte[] { 1 }), Defaults);
        Check(query.Value.ObservedAtUnixMillis == ulong.MaxValue && query.Metadata.Observed is null, "fresh query created durable command knowledge");
        Check((await client.LookupCommandAsync(TxLookup(), Defaults)).Value.Command!.AttemptId == "attempt-a", "command lookup changed attempt");
        Check((await client.LookupCommitAsync(new(Tx.CurrentTransactionProfile.Create(), TxSelector, "receipt-a", TxPublication), Defaults)).Value.Command!.Commit!.ReceiptId == "receipt-a", "commit lookup association changed");
        var effect = new Tx.GetEffectRequest(Tx.CurrentTransactionProfile.Create(), TxSelector, "effect-a", TxPublication);
        Check((await client.GetEffectAsync(effect, Defaults)).Value.Effect!.OccurredAtUnixMillis == ulong.MaxValue, "effect timestamp narrowed");
        var history = await client.ListEffectHistoryAsync(new(effect, new(16, null)), Defaults);
        Check(history.Value.Receipts.Count == 1 && history.Value.Page!.NextCursor.HasValue, "short page was treated as exhausted");
        Check((await client.CancelCommandAsync(new(TxLookup(), "logical cancellation"), Defaults)).Value.Disposition == Tx.CommandCancelDisposition.AlreadyCommitted, "cancellation disposition collapsed");
        Check((await client.InspectNamespaceAsync(TxInspect, Defaults)).Value.Namespace!.Generation == ulong.MaxValue, "namespace generation narrowed");
        Check((await client.SelectEntityAsync(new(TxInspect, null, new(16, null)), Defaults)).Value.Page!.NextCursor.HasValue, "entity selection drained or lost cursor");
        var state = await client.MutateStateAsync(new(TxInspect, "state-operation-a", Tx.StateMutationKind.CheckpointNamespace, null, new byte[] { 1 }, TxDigest, "checkpoint"), Defaults);
        Check(state.Value.AuditAck!.AttemptSequence == ulong.MaxValue && state.Metadata.Observed!.State!.ReceiptId == "state-receipt-a", "audit/receipt facts changed");
        var lifecycle = await client.MutateNamespaceAsync(new(TxInspect, "namespace-operation-a", Tx.NamespaceMutationKind.Quiesce, ulong.MaxValue - 1, null), Defaults);
        Check(lifecycle.Metadata.Identity.ExpectedGeneration == ulong.MaxValue - 1, "lifecycle precondition was refreshed: " + lifecycle.Metadata.Identity.ExpectedGeneration);
        Check(lifecycle.Value.Receipt!.AfterGeneration == ulong.MaxValue, "lifecycle receipt generation narrowed");
        Check((await client.GetStateOperationReceiptAsync(new(TxInspect, "state-operation-a"), Defaults)).Metadata.Observed!.State!.OperationId == "state-operation-a", "management recovery identity changed");
        Check(peer.Requests.Count == 12 && peer.Requests.Values.All(count => count == 1) && peer.Connections.Count == 1, "transaction operations replayed or replaced the existing connection");
        await client.DisposeAsync(); Check(client.Snapshot().Reaped, "transaction connection did not physically retire");
    }

    private static async Task TransactionDurableRejectionThroughAuditFailure()
    {
        await using Peer peer = await Peer.Start(async context =>
        {
            await Peer.Read<WireTx.InvokeCommandRequest>(context); var rejected = TxWireCommand(3); var invocation = Peer.Success(); invocation.DeclaredError = rejected.BusinessRejection.Clone();
            context.Response.Headers["latent-audit-attempt"] = "not-an-integer";
            await Peer.Reply(context, new WireTx.InvokeCommandResponse { Command = rejected, Invocation = invocation });
        });
        await using BoundedClient client = await BoundedClient.ConnectAsync(Options(peer.Endpoint));
        var failure = await TxFailure(client.InvokeCommandAsync(TxInvoke(), Defaults).AsTask(), Profile.FailureCategory.Decode);
        Check(failure.Transport.Dispatched && failure.Transport.Outcome == Profile.OutcomeKnowledge.Observed && failure.Observed!.Command!.Outcome == Tx.CommandOutcome.Rejected, "later audit failure erased a durable business rejection");
        Check(!failure.Observed!.Command!.ApplicationStateCommitted && failure.Identity.Command!.ClientKey == "business-key-a" && failure.Identity.ExpectedVersions![0].Version!.Value.Span.SequenceEqual(new byte[] { 1 }), "business rejection implied state commit or refreshed original inputs");
        Check(failure.Observed.Command!.BusinessRejection is null && failure.Observed.Command.ProvenAbort is null && peer.Requests.Values.Single() == 1, "failure retained application payload, forged abort, or resubmitted");
    }

    private static async Task TransactionTransportAbortAndExplicitAttempt()
    {
        int submissions = 0;
        await using Peer peer = await Peer.Start(async context =>
        {
            if (context.Request.Path.Value!.EndsWith("/LookupCommand", StringComparison.Ordinal))
            { await Peer.Read<WireTx.LookupCommandRequest>(context); await Peer.Reply(context, new WireTx.LookupCommandResponse { Command = TxWireCommand(4) }); return; }
            var requested = await Peer.Read<WireTx.InvokeCommandRequest>(context);
            if (Interlocked.Increment(ref submissions) == 1) { await Peer.Error(context, "10"); return; }
            Check(requested.RetryAttempt.RequestId == "explicit-retry-a" && requested.RetryAttempt.ExpectedAbort.OwnerFence.Span.SequenceEqual(new byte[] { 1, 2 }), "explicit attempt lost the proven owner fence");
            var command = TxWireCommand(); var invocation = Peer.Success(); invocation.Success = command.Success.Clone();
            await Peer.Reply(context, new WireTx.InvokeCommandResponse { Command = command, Invocation = invocation });
        });
        await using BoundedClient client = await BoundedClient.ConnectAsync(Options(peer.Endpoint));
        var unknown = await TxFailure(client.InvokeCommandAsync(TxInvoke(), Defaults).AsTask(), Profile.FailureCategory.Rpc);
        Check(unknown.Transport.GrpcStatus == 10 && unknown.Transport.Outcome == Profile.OutcomeKnowledge.Unknown && unknown.Observed is null && submissions == 1, "gRPC ABORTED authorized or submitted another attempt");
        var aborted = await client.LookupCommandAsync(TxLookup(), Defaults);
        Check(aborted.Value.Command!.Outcome == Tx.CommandOutcome.Aborted && aborted.Value.Command.ProvenAbort is not null, "durable abort fence was not preserved");
        var explicitRequest = TxInvoke() with { RetryAttempt = new("explicit-retry-a", aborted.Value.Command.ProvenAbort) };
        var committed = await client.InvokeCommandAsync(explicitRequest, Defaults);
        Check(committed.Metadata.Identity.AttemptId == "attempt-a" && committed.Metadata.Identity.ExpectedAbort!.OwnerFence.Span.SequenceEqual(new byte[] { 1, 2 }) && submissions == 2, "original explicit-attempt identity was silently replaced");
    }

    private static async Task TransactionWireBoundsAndOldPayloads()
    {
        await using Peer peer = await Peer.Start(async context =>
        {
            var request = await Peer.Read<WireTx.LookupCommandRequest>(context);
            var command = TxWireCommand(payload: false);
            command.Retention.RecordVersion = 7; command.Retention.RecordFormat = "retained-old-format";
            command.Retention.RequiredRecordIds.Clear(); command.Retention.RequiredRecordIds.Add(Enumerable.Range(0, 256).Select(index => "linked-" + index));
            if (request.HasAttemptId && request.AttemptId == "future") command.Outcome = (WireTx.CommandOutcome)91;
            byte[] bytes = new WireTx.LookupCommandResponse { Command = command }.ToByteArray();
            if (request.HasAttemptId && request.AttemptId == "duplicate") bytes = bytes.Concat(bytes).ToArray();
            if (request.HasAttemptId && request.AttemptId == "expansion")
            {
                var list = new WireTx.ListEffectHistoryResponse(); for (int i = 0; i < 129; i++) list.Receipts.Add(new WireTx.EffectReceipt()); bytes = list.ToByteArray();
            }
            await context.Request.Body.CopyToAsync(Stream.Null, context.RequestAborted);
            context.Response.ContentType = "application/grpc+proto"; context.Response.DeclareTrailer("grpc-status");
            await context.Response.Body.WriteAsync(Peer.Packet(bytes)); context.Response.AppendTrailer("grpc-status", "0");
        });
        await using BoundedClient client = await BoundedClient.ConnectAsync(Options(peer.Endpoint));
        var old = await client.LookupCommandAsync(TxLookup(), Defaults);
        Check(old.Value.Command!.Retention!.RequiredRecordIds.Count == 256 && old.Value.Command.Retention.RecordVersion == 7 && old.Value.Command.Success is null && old.Metadata.Observed!.Command!.Commit is not null, "payload expiry lost old-format identity/receipt");
        var unknown = await TxFailure(client.LookupCommandAsync(TxLookup("future"), Defaults).AsTask(), Profile.FailureCategory.Decode);
        Check(unknown.Transport.UnsupportedWireValue!.Value == "91" && unknown.Observed is null, "unknown enum was narrowed or treated as known receipt");
        var duplicate = await TxFailure(client.LookupCommandAsync(TxLookup("duplicate"), Defaults).AsTask(), Profile.FailureCategory.Decode);
        Check(duplicate.Observed is null, "duplicate wire field produced receipt knowledge");
        var malformed = await TxFailure(client.LookupCommandAsync(TxLookup("expansion"), Defaults).AsTask(), Profile.FailureCategory.Decode);
        Check(malformed.Observed is null, "foreign response owner produced receipt knowledge");
        var budget = new GraphBudget(8 * 1024 * 1024, 4096, CancellationToken.None);
        var oversized = new WireTx.ListEffectHistoryResponse(); for (int i = 0; i < 129; i++) oversized.Receipts.Add(new WireTx.EffectReceipt());
        try { WireShape.Validate(oversized.ToByteArray(), WireTx.ListEffectHistoryResponse.Descriptor, budget, transactional: true); throw new InvalidOperationException("empty records bypassed the bounded page predecode"); }
        catch (GraphLimitException) { Check(true, "empty-record expansion rejected before native allocation"); }
    }

    private static async Task TransactionOriginalInputsAndCancellation()
    {
        var seen = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        await using Peer peer = await Peer.Start(async context =>
        {
            if (context.Request.Path.Value!.EndsWith("/InvokeCommand", StringComparison.Ordinal))
            { await Peer.Read<WireTx.InvokeCommandRequest>(context); seen.TrySetResult(); await Task.Delay(Timeout.Infinite, context.RequestAborted); }
            else { await Peer.Read<WireTx.LookupCommandRequest>(context); await Peer.Reply(context, new WireTx.LookupCommandResponse { Command = TxWireCommand() }); }
        });
        await using BoundedClient client = await BoundedClient.ConnectAsync(Options(peer.Endpoint));
        byte[] precondition = [1]; var original = TxInvoke() with { ExpectedVersions = new[] { new Tx.ExpectedVersion(new byte[] { 0, 255 }, null, precondition) } };
        using var stop = new CancellationTokenSource(); Task pending = client.InvokeCommandAsync(original, Defaults, stop.Token).AsTask();
        await seen.Task.WaitAsync(TimeSpan.FromSeconds(3)); precondition[0] = 9; stop.Cancel();
        var cancelled = await TxFailure(pending, Profile.FailureCategory.LocalCancelled);
        Check(cancelled.Identity.ExpectedVersions![0].Version!.Value.Span.SequenceEqual(new byte[] { 1 }) && cancelled.Identity.Command!.ClientKey == "business-key-a" && cancelled.Observed is null, "local cancellation refreshed preconditions or fabricated server cleanup");
        await Until(() => client.Snapshot().InFlight == 0 && client.Snapshot().WireStreams == 0);
        var recovered = await client.LookupCommandAsync(TxLookup(), Defaults, CancellationToken.None);
        Check(recovered.Metadata.Observed!.Command!.Commit!.ReceiptId == "receipt-a" && peer.Requests.Values.Sum() == 2, "explicit recovery with new local cancellation scope replayed the command");
    }

    private static async Task TransactionProfileAndDeadlineFailBeforeDispatch()
    {
        await using Peer peer = await Peer.Start(context => Peer.Error(context, "13"));
        await using BoundedClient client = await BoundedClient.ConnectAsync(Options(peer.Endpoint));
        var incompatible = TxInvoke() with { Profile = Tx.CurrentTransactionProfile.Create() with { HostAbiDigest = "future" } };
        var rejected = await TxFailure(client.InvokeCommandAsync(incompatible, Defaults).AsTask(), Profile.FailureCategory.InvalidRequest);
        Check(!rejected.Transport.Dispatched && rejected.Identity.Command!.ClientKey == "business-key-a" && peer.Requests.IsEmpty, "wrong ABI profile reached native dispatch or lost original identity");
        var expired = TxInvoke() with { Invocation = Invoke() with { DeadlineUnixMillis = 0 } };
        var deadline = await TxFailure(client.InvokeCommandAsync(expired, Defaults).AsTask(), Profile.FailureCategory.Deadline);
        Check(!deadline.Transport.Dispatched && deadline.Identity.ExpectedVersions!.Count == 1 && peer.Requests.IsEmpty, "expired original wall deadline was refreshed or dispatched");
    }
}
