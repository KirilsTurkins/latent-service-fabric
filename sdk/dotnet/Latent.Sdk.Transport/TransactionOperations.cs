using System.Reflection;
using Google.Protobuf;
using WireControl = global::Latent.Control.V1;
using WireTransaction = global::Latent.Transaction.V1;
using Profile = Latent.Sdk.Profile;
using Tx = Latent.Sdk.Transactions;

namespace Latent.Sdk.Transport;

public sealed partial class BoundedClient : Tx.ITransactionClient
{
    public ValueTask<Tx.TransactionResponse<Tx.InvokeCommandResponse>> InvokeCommandAsync(Tx.InvokeCommandRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default) =>
        ExecuteTransactionAsync<Tx.InvokeCommandResponse, WireTransaction.InvokeCommandRequest, WireTransaction.InvokeCommandResponse>(request, options, cancellationToken,
            (invoker, wire) => new WireTransaction.TransactionService.TransactionServiceClient(invoker).InvokeCommandAsync(wire, cancellationToken: invoker.Token).ResponseAsync);

    public ValueTask<Tx.TransactionResponse<Tx.QueryResponse>> QueryAsync(Tx.QueryRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default) =>
        ExecuteTransactionAsync<Tx.QueryResponse, WireTransaction.QueryRequest, WireTransaction.QueryResponse>(request, options, cancellationToken,
            (invoker, wire) => new WireTransaction.TransactionService.TransactionServiceClient(invoker).QueryAsync(wire, cancellationToken: invoker.Token).ResponseAsync);

    public ValueTask<Tx.TransactionResponse<Tx.LookupCommandResponse>> LookupCommandAsync(Tx.LookupCommandRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default) =>
        ExecuteTransactionAsync<Tx.LookupCommandResponse, WireTransaction.LookupCommandRequest, WireTransaction.LookupCommandResponse>(request, options, cancellationToken,
            (invoker, wire) => new WireTransaction.TransactionService.TransactionServiceClient(invoker).LookupCommandAsync(wire, cancellationToken: invoker.Token).ResponseAsync);

    public ValueTask<Tx.TransactionResponse<Tx.LookupCommitResponse>> LookupCommitAsync(Tx.LookupCommitRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default) =>
        ExecuteTransactionAsync<Tx.LookupCommitResponse, WireTransaction.LookupCommitRequest, WireTransaction.LookupCommitResponse>(request, options, cancellationToken,
            (invoker, wire) => new WireTransaction.TransactionService.TransactionServiceClient(invoker).LookupCommitAsync(wire, cancellationToken: invoker.Token).ResponseAsync);

    public ValueTask<Tx.TransactionResponse<Tx.GetEffectResponse>> GetEffectAsync(Tx.GetEffectRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default) =>
        ExecuteTransactionAsync<Tx.GetEffectResponse, WireTransaction.GetEffectRequest, WireTransaction.GetEffectResponse>(request, options, cancellationToken,
            (invoker, wire) => new WireTransaction.TransactionService.TransactionServiceClient(invoker).GetEffectAsync(wire, cancellationToken: invoker.Token).ResponseAsync);

    public ValueTask<Tx.TransactionResponse<Tx.ListEffectHistoryResponse>> ListEffectHistoryAsync(Tx.ListEffectHistoryRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default) =>
        ExecuteTransactionAsync<Tx.ListEffectHistoryResponse, WireTransaction.ListEffectHistoryRequest, WireTransaction.ListEffectHistoryResponse>(request, options, cancellationToken,
            (invoker, wire) => new WireTransaction.TransactionService.TransactionServiceClient(invoker).ListEffectHistoryAsync(wire, cancellationToken: invoker.Token).ResponseAsync);

    public ValueTask<Tx.TransactionResponse<Tx.CancelCommandResponse>> CancelCommandAsync(Tx.CancelCommandRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default) =>
        ExecuteTransactionAsync<Tx.CancelCommandResponse, WireTransaction.CancelCommandRequest, WireTransaction.CancelCommandResponse>(request, options, cancellationToken,
            (invoker, wire) => new WireTransaction.TransactionService.TransactionServiceClient(invoker).CancelCommandAsync(wire, cancellationToken: invoker.Token).ResponseAsync);

    public ValueTask<Tx.TransactionResponse<Tx.InspectNamespaceResponse>> InspectNamespaceAsync(Tx.InspectNamespaceRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default) =>
        ExecuteTransactionAsync<Tx.InspectNamespaceResponse, WireControl.InspectNamespaceRequest, WireControl.InspectNamespaceResponse>(request, options, cancellationToken,
            (invoker, wire) => new WireControl.StateService.StateServiceClient(invoker).InspectNamespaceAsync(wire, cancellationToken: invoker.Token).ResponseAsync);

    public ValueTask<Tx.TransactionResponse<Tx.MutateNamespaceResponse>> MutateNamespaceAsync(Tx.MutateNamespaceRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default) =>
        ExecuteTransactionAsync<Tx.MutateNamespaceResponse, WireControl.MutateNamespaceRequest, WireControl.MutateNamespaceResponse>(request, options, cancellationToken,
            (invoker, wire) => new WireControl.StateService.StateServiceClient(invoker).MutateNamespaceAsync(wire, cancellationToken: invoker.Token).ResponseAsync);

    public ValueTask<Tx.TransactionResponse<Tx.SelectEntityResponse>> SelectEntityAsync(Tx.SelectEntityRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default) =>
        ExecuteTransactionAsync<Tx.SelectEntityResponse, WireControl.SelectEntityRequest, WireControl.SelectEntityResponse>(request, options, cancellationToken,
            (invoker, wire) => new WireControl.StateService.StateServiceClient(invoker).SelectEntityAsync(wire, cancellationToken: invoker.Token).ResponseAsync);

    public ValueTask<Tx.TransactionResponse<Tx.MutateStateResponse>> MutateStateAsync(Tx.MutateStateRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default) =>
        ExecuteTransactionAsync<Tx.MutateStateResponse, WireControl.MutateStateRequest, WireControl.MutateStateResponse>(request, options, cancellationToken,
            (invoker, wire) => new WireControl.StateService.StateServiceClient(invoker).MutateStateAsync(wire, cancellationToken: invoker.Token).ResponseAsync);

    public ValueTask<Tx.TransactionResponse<Tx.GetStateOperationReceiptResponse>> GetStateOperationReceiptAsync(Tx.GetStateOperationReceiptRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default) =>
        ExecuteTransactionAsync<Tx.GetStateOperationReceiptResponse, WireControl.GetStateOperationReceiptRequest, WireControl.GetStateOperationReceiptResponse>(request, options, cancellationToken,
            (invoker, wire) => new WireControl.StateService.StateServiceClient(invoker).GetStateOperationReceiptAsync(wire, cancellationToken: invoker.Token).ResponseAsync);

    private async ValueTask<Tx.TransactionResponse<Response>> ExecuteTransactionAsync<Response, WireRequest, WireResponse>(object request,
        Profile.CallOptions options, CancellationToken caller, Func<UnaryInvoker, WireRequest, Task<WireResponse>> dispatch)
        where Response : class where WireRequest : IMessage, new() where WireResponse : IMessage
    {
        var state = new CallState(config, request, options, caller, transactional: true);
        using var expiry = new CancellationTokenSource();
        state.Expiry = expiry.Token;
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(caller, lifetime.Token, expiry.Token);
        expiry.CancelAfter(TimeSpan.FromMilliseconds(Math.Ceiling(state.Remaining.TotalMilliseconds)));
        bool admitted = false;
        Response? ownedResponse = null;
        try
        {
            CheckDeadline(state, deadline.Token);
            TransactionRules.Collections(request, new GraphBudget(Math.Min(config.MaxGraphBytes, 8 * 1024 * 1024),
                Math.Min(config.MaxGraphNodes, 4096), deadline.Token));
            TransactionRules.Request(request);
            var wireRequest = (WireRequest)ProfileCodec.ToWire(request, new WireRequest());
            if (wireRequest.CalculateSize() > state.RequestLimit) throw new GraphLimitException();
            // Snapshot before the first await. Caller mutations cannot refresh preconditions or keys.
            object original = ProfileCodec.FromWire(wireRequest, request.GetType());
            state.TransactionIdentity = TransactionRules.IdentitySnapshot(original);
            state.ValidateTransactionResponse = wire =>
            {
                ownedResponse = (Response)ProfileCodec.FromWire((IMessage)wire, typeof(Response));
                TransactionRules.Response(ownedResponse, original, state);
            };
            await AcquireAsync(state, deadline.Token).ConfigureAwait(false);
            admitted = true;
            CheckDeadline(state, deadline.Token);
            await dispatch(new(this, state, deadline.Token), wireRequest).ConfigureAwait(false);
            CheckDeadline(state, deadline.Token);
            return new(ownedResponse!, state.TransactionMetadata);
        }
        catch (Tx.TransactionException) { throw; }
        catch (Tx.TransactionCancellationException) { throw; }
        catch (OperationCanceledException) { throw state.Cancelled(deadline.Token); }
        catch (GraphLimitException) { throw state.Error(Profile.FailureCategory.Limit, "transaction request or response exceeds its bounded graph"); }
        catch (InvalidProtocolBufferException) { throw state.Error(Profile.FailureCategory.Decode, "invalid transaction protobuf response"); }
        catch (TransactionWireValueException failure)
        {
            throw state.Wrap(state.Failure(state.Dispatched ? Profile.FailureCategory.Decode : Profile.FailureCategory.InvalidRequest,
                "unsupported transaction wire value") with { UnsupportedWireValue = failure.Value with { Value = Redact(failure.Value.Value) } });
        }
        catch (Exception failure) when (failure is IOException or HttpRequestException or ObjectDisposedException)
        {
            if (deadline.IsCancellationRequested || state.Remaining == TimeSpan.Zero) throw state.Cancelled(deadline.Token);
            throw state.Error(Profile.FailureCategory.Transport, "owned HTTP/2 connection failed; recover the original transaction identity");
        }
        catch (Exception failure) when (failure is FormatException or ArgumentException or OverflowException or TargetInvocationException or NullReferenceException)
        {
            throw state.Error(state.Dispatched ? Profile.FailureCategory.Decode : Profile.FailureCategory.InvalidRequest, "invalid bounded transaction value");
        }
        finally { if (admitted) Release(state); }
    }
}
