package dev.latent.sdk;

import java.nio.ByteBuffer;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.CancellationException;
import java.util.concurrent.CompletableFuture;

/** Explicit Phase 4 operations on the maintained bounded management transport. */
public interface TransactionClient {
    /** Original recovery data grants no authority and never implies automatic retry. */
    record RecoveryIdentity(
            Optional<Transactions.NamespaceSelector> namespace,
            Optional<Transactions.CommandSelector> command,
            Optional<String> activationId,
            Optional<String> operationId,
            Optional<String> attemptId,
            Optional<String> receiptId,
            Optional<String> retryRequestId,
            Optional<String> effectId,
            Optional<ByteBuffer> fingerprintSha256,
            Optional<Transactions.AbortFence> expectedAbort,
            Optional<Management.PublicationRef> authorizationPublication,
            List<Transactions.ExpectedVersion> expectedVersions,
            Optional<Long> expectedGeneration,
            Optional<ByteBuffer> expectedVersion,
            Optional<String> expectedPolicyDigest,
            Optional<Transactions.DispatcherAction> dispatcherAction,
            Optional<Transactions.DispatcherGeneration> dispatcherExpectedGeneration) {
        public RecoveryIdentity {
            expectedVersions = List.copyOf(expectedVersions);
        }

        public static RecoveryIdentity empty() {
            return new RecoveryIdentity(Optional.empty(), Optional.empty(), Optional.empty(),
                    Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty(),
                    Optional.empty(), Optional.empty(), Optional.empty(), List.of(), Optional.empty(),
                    Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty());
        }
    }

    /** Bounded durable metadata; recovery explicitly retrieves application payloads. */
    record CommandObservation(String commandId, String attemptId, Transactions.CommandOutcome outcome,
            boolean metadataDurable, boolean applicationStateCommitted, ByteBuffer fingerprintSha256,
            Optional<Transactions.CommitReceipt> commit, Optional<Transactions.AbortFence> provenAbort,
            Optional<Transactions.SourceIdentity> source, Optional<Transactions.LinkedRetention> retention) { }

    sealed interface ObservedOutcome {
        record Command(CommandObservation command) implements ObservedOutcome { }
        record State(Transactions.StateOperationReceipt receipt) implements ObservedOutcome { }
        record Namespace(Transactions.NamespaceOperationReceipt receipt) implements ObservedOutcome { }
        record Effect(Transactions.EffectReceipt receipt) implements ObservedOutcome { }
        record Dispatcher(Transactions.DispatcherOperationReceipt receipt) implements ObservedOutcome { }
    }

    record ResponseMetadata(Management.ResponseMetadata transport, RecoveryIdentity identity) { }
    record ClientResponse<Response>(Response value, ResponseMetadata metadata) { }
    record ClientFailure(Management.ClientFailure transport, RecoveryIdentity identity,
            Optional<ObservedOutcome> observed) { }

    final class ClientException extends RuntimeException {
        private static final long serialVersionUID = 1L;
        private final transient ClientFailure failure;
        public ClientException(ClientFailure failure) {
            super("bounded transaction RPC failure");
            this.failure = failure;
        }
        public ClientFailure failure() { return failure; }
    }

    final class ClientCancellationException extends CancellationException {
        private static final long serialVersionUID = 1L;
        private final transient ClientFailure failure;
        public ClientCancellationException(ClientFailure failure) {
            super("bounded transaction RPC cancellation");
            this.failure = failure;
        }
        public ClientFailure failure() { return failure; }
    }

    static Optional<ClientFailure> clientFailure(Throwable failure) {
        for (int depth = 0; failure != null && depth < 8; depth++, failure = failure.getCause()) {
            if (failure instanceof ClientException typed) return Optional.of(typed.failure());
            if (failure instanceof ClientCancellationException typed) return Optional.of(typed.failure());
        }
        return Optional.empty();
    }

    CompletableFuture<ClientResponse<Transactions.InvokeCommandResponse>> invokeCommand(
            Transactions.InvokeCommandRequest request, Management.CallOptions options);
    CompletableFuture<ClientResponse<Transactions.QueryResponse>> query(
            Transactions.QueryRequest request, Management.CallOptions options);
    CompletableFuture<ClientResponse<Transactions.LookupCommandResponse>> lookupCommand(
            Transactions.LookupCommandRequest request, Management.CallOptions options);
    CompletableFuture<ClientResponse<Transactions.LookupCommitResponse>> lookupCommit(
            Transactions.LookupCommitRequest request, Management.CallOptions options);
    CompletableFuture<ClientResponse<Transactions.GetEffectResponse>> getEffect(
            Transactions.GetEffectRequest request, Management.CallOptions options);
    CompletableFuture<ClientResponse<Transactions.ListEffectHistoryResponse>> listEffectHistory(
            Transactions.ListEffectHistoryRequest request, Management.CallOptions options);
    CompletableFuture<ClientResponse<Transactions.CancelCommandResponse>> cancelCommand(
            Transactions.CancelCommandRequest request, Management.CallOptions options);
    CompletableFuture<ClientResponse<Transactions.InspectNamespaceResponse>> inspectNamespace(
            Transactions.InspectNamespaceRequest request, Management.CallOptions options);
    CompletableFuture<ClientResponse<Transactions.SelectEntityResponse>> selectEntity(
            Transactions.SelectEntityRequest request, Management.CallOptions options);
    CompletableFuture<ClientResponse<Transactions.MutateNamespaceResponse>> mutateNamespace(
            Transactions.MutateNamespaceRequest request, Management.CallOptions options);
    CompletableFuture<ClientResponse<Transactions.MutateStateResponse>> mutateState(
            Transactions.MutateStateRequest request, Management.CallOptions options);
    CompletableFuture<ClientResponse<Transactions.GetStateOperationReceiptResponse>> getStateOperationReceipt(
            Transactions.GetStateOperationReceiptRequest request, Management.CallOptions options);
    CompletableFuture<ClientResponse<Transactions.InspectDispatcherResponse>> inspectDispatcher(
            Transactions.InspectDispatcherRequest request, Management.CallOptions options);
    CompletableFuture<ClientResponse<Transactions.ControlDispatcherResponse>> controlDispatcher(
            Transactions.ControlDispatcherRequest request, Management.CallOptions options);
    CompletableFuture<ClientResponse<Transactions.GetDispatcherOperationResponse>> getDispatcherOperation(
            Transactions.GetDispatcherOperationRequest request, Management.CallOptions options);
}
