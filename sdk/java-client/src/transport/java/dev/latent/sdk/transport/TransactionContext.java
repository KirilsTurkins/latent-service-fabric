package dev.latent.sdk.transport;

import dev.latent.sdk.Management;
import dev.latent.sdk.TransactionClient;
import dev.latent.sdk.Transactions;
import java.nio.ByteBuffer;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;

/** Call-owned recovery data. The client never promotes it into an authorization grant. */
final class TransactionContext {
    private volatile TransactionClient.RecoveryIdentity identity = TransactionClient.RecoveryIdentity.empty();
    private volatile Optional<TransactionClient.ObservedOutcome> observation = Optional.empty();

    Management.RequestIdentity transportIdentity() {
        return new Management.RequestIdentity(identity.activationId(), identity.operationId());
    }

    void capture(Object request) {
        try {
            Builder result = new Builder();
            Object inspected = null, command = null;
            switch (request) {
                case Transactions.InvokeCommandRequest value -> {
                    command = value.command().orElse(null);
                    result.activation = value.invocation().flatMap(Management.InvokeRequest::activationId);
                    result.versions = value.expectedVersions().stream().map(TransactionContext::version).toList();
                    if (value.retryAttempt().isPresent()) {
                        var retry = value.retryAttempt().get();
                        result.retry = Optional.of(TransactionProtocol.id(retry.requestId()));
                        result.abort = retry.expectedAbort().map(TransactionContext::abort);
                        result.attempt = result.abort.map(Transactions.AbortFence::attemptId);
                    }
                }
                case Transactions.QueryRequest value -> {
                    result.namespace = value.namespace(); result.activation = value.invocation().flatMap(Management.InvokeRequest::activationId);
                }
                case Transactions.LookupCommandRequest value -> {
                    command = value.command().orElse(null); result.attempt = value.attemptId(); result.publication = value.authorizationPublication();
                }
                case Transactions.LookupCommitRequest value -> {
                    command = value.command().orElse(null); result.receipt = Optional.of(value.receiptId()); result.publication = value.authorizationPublication();
                }
                case Transactions.GetEffectRequest value -> {
                    command = value.command().orElse(null); result.effect = Optional.of(value.effectId()); result.publication = value.authorizationPublication();
                }
                case Transactions.ListEffectHistoryRequest value -> {
                    var selected = value.effect().orElseThrow(); command = selected.command().orElse(null);
                    result.effect = Optional.of(selected.effectId()); result.publication = selected.authorizationPublication();
                }
                case Transactions.CancelCommandRequest value -> {
                    var selected = value.command().orElseThrow(); command = selected.command().orElse(null);
                    result.attempt = selected.attemptId(); result.publication = selected.authorizationPublication();
                }
                case Transactions.InspectNamespaceRequest value -> inspected = value;
                case Transactions.SelectEntityRequest value -> inspected = value.namespace().orElse(null);
                case Transactions.MutateNamespaceRequest value -> {
                    inspected = value.namespace().orElse(null); result.operation = Optional.of(value.operationId()); result.generation = value.expectedGeneration();
                }
                case Transactions.MutateStateRequest value -> {
                    inspected = value.namespace().orElse(null); result.operation = Optional.of(value.operationId());
                    result.version = Optional.of(copy(value.expectedVersion(), 256)); result.policy = Optional.of(value.expectedPolicyDigest());
                }
                case Transactions.GetStateOperationReceiptRequest value -> {
                    inspected = value.namespace().orElse(null); result.operation = Optional.of(value.operationId());
                }
                case Transactions.ControlDispatcherRequest value -> dispatcher(result, value);
                case Transactions.GetDispatcherOperationRequest value -> dispatcher(result, value.original().orElseThrow());
                case Transactions.InspectDispatcherRequest value -> { }
                default -> throw new Protocol.Invalid();
            }
            if (inspected instanceof Transactions.InspectNamespaceRequest value) {
                result.namespace = value.namespace(); result.publication = value.authorizationPublication();
            }
            if (command instanceof Transactions.CommandSelector value) {
                result.namespace = value.namespace(); result.command = Optional.of(value);
                TransactionProtocol.id(value.operation()); TransactionProtocol.id(value.clientKey());
                value.entity().ifPresent(TransactionProtocol::id); value.sharedRecoveryScope().ifPresent(TransactionProtocol::id);
            }
            for (var id : List.of(result.activation, result.operation, result.attempt, result.receipt, result.retry, result.effect)) id.ifPresent(TransactionProtocol::id);
            result.namespace.ifPresent(value -> {
                TransactionProtocol.id(value.tenant()); TransactionProtocol.id(value.namespace()); TransactionProtocol.id(value.incarnation());
            });
            result.publication.ifPresent(value -> { TransactionProtocol.id(value.id()); TransactionProtocol.id(value.tenant()); });
            result.policy.ifPresent(value -> Protocol.require(value.matches("sha256:[0-9a-f]{64}")));
            identity = result.build();
        } catch (RuntimeException failure) { identity = TransactionClient.RecoveryIdentity.empty(); }
    }

    private static void dispatcher(Builder result, Transactions.ControlDispatcherRequest original) {
        TransactionProtocol.id(original.operationId());
        Protocol.require(original.action().equals(Transactions.DispatcherAction.PAUSE) || original.action().equals(Transactions.DispatcherAction.RESUME));
        var generation = original.expectedGeneration().orElseThrow();
        Protocol.require(generation.ownerEpoch() != 0 && generation.revision() != 0);
        result.operation = Optional.of(original.operationId()); result.action = Optional.of(original.action()); result.dispatcherGeneration = Optional.of(generation);
    }
    private static ByteBuffer copy(ByteBuffer value, int maximum) {
        Protocol.require(value.remaining() <= maximum);
        byte[] bytes = new byte[value.remaining()]; value.asReadOnlyBuffer().get(bytes);
        return ByteBuffer.wrap(bytes).asReadOnlyBuffer();
    }
    private static Transactions.ExpectedVersion version(Transactions.ExpectedVersion value) {
        return new Transactions.ExpectedVersion(copy(value.key(), 1024), value.absent(), value.version().map(bytes -> copy(bytes, 256)));
    }
    private static Transactions.AbortFence abort(Transactions.AbortFence value) {
        TransactionProtocol.id(value.commandId()); TransactionProtocol.id(value.attemptId()); TransactionProtocol.id(value.transactionId());
        return new Transactions.AbortFence(value.commandId(), value.attemptId(), value.transactionId(), copy(value.ownerFence(), 256));
    }

    void observe(Object value) {
        Builder next = new Builder(identity);
        if (next.activation.isEmpty()) {
            Optional<Management.InvokeResponse> invoked = switch (value) {
                case Transactions.InvokeCommandResponse result -> result.invocation();
                case Transactions.QueryResponse result -> result.invocation();
                default -> Optional.empty();
            };
            next.activation = invoked.map(Management.InvokeResponse::activationId);
        }
        Object receipt;
        observation = switch (value) {
            case Transactions.InvokeCommandResponse result -> result.command().map(TransactionContext::command);
            case Transactions.LookupCommandResponse result -> result.command().map(TransactionContext::command);
            case Transactions.LookupCommitResponse result -> result.command().map(TransactionContext::command);
            case Transactions.CancelCommandResponse result -> result.command().map(TransactionContext::command);
            case Transactions.MutateStateResponse result -> result.receipt().map(TransactionClient.ObservedOutcome.State::new);
            case Transactions.MutateNamespaceResponse result -> result.receipt().map(TransactionClient.ObservedOutcome.Namespace::new);
            case Transactions.GetStateOperationReceiptResponse result -> result.receipt()
                    .<TransactionClient.ObservedOutcome>map(TransactionClient.ObservedOutcome.State::new)
                    .or(() -> result.namespaceReceipt().map(TransactionClient.ObservedOutcome.Namespace::new));
            case Transactions.GetEffectResponse result -> result.effect().map(TransactionClient.ObservedOutcome.Effect::new);
            case Transactions.ControlDispatcherResponse result -> result.receipt().map(TransactionClient.ObservedOutcome.Dispatcher::new);
            case Transactions.GetDispatcherOperationResponse result -> result.receipt().map(TransactionClient.ObservedOutcome.Dispatcher::new);
            default -> Optional.empty();
        };
        if (observation.orElse(null) instanceof TransactionClient.ObservedOutcome.Command accepted) {
            var observed = accepted.command();
            if (observed.fingerprintSha256().hasRemaining()) next.fingerprint = Optional.of(observed.fingerprintSha256());
            if (next.attempt.isEmpty() && !observed.attemptId().isEmpty()) next.attempt = Optional.of(observed.attemptId());
            if (next.receipt.isEmpty()) next.receipt = observed.commit().map(Transactions.CommitReceipt::receiptId);
        } else if (observation.isPresent()) {
            receipt = switch (observation.get()) {
                case TransactionClient.ObservedOutcome.State accepted -> accepted.receipt();
                case TransactionClient.ObservedOutcome.Namespace accepted -> accepted.receipt();
                case TransactionClient.ObservedOutcome.Dispatcher accepted -> accepted.receipt();
                case TransactionClient.ObservedOutcome.Effect accepted -> accepted.receipt();
                default -> null;
            };
            if (receipt instanceof Transactions.EffectReceipt effect) next.effect = Optional.of(effect.effectId());
            else if (receipt != null) next.receipt = Optional.of((String) TransactionProtocol.part(receipt, "receiptId"));
        }
        identity = next.build();
    }
    private static TransactionClient.ObservedOutcome command(Transactions.CommandInspection value) {
        return new TransactionClient.ObservedOutcome.Command(new TransactionClient.CommandObservation(value.commandId(), value.attemptId(),
                value.outcome(), value.metadataDurable(), value.applicationStateCommitted(), value.fingerprintSha256(), value.commit(),
                value.provenAbort(), value.source(), value.retention()));
    }
    boolean known() {
        if (observation.isEmpty()) return false;
        return switch (observation.orElse(null)) {
            case TransactionClient.ObservedOutcome.Command accepted -> accepted.command().metadataDurable()
                    && SetHolder.TERMINAL.contains(accepted.command().outcome());
            case TransactionClient.ObservedOutcome.State accepted -> SetHolder.DISPOSITIONS.contains(accepted.receipt().disposition());
            case TransactionClient.ObservedOutcome.Namespace accepted -> SetHolder.DISPOSITIONS.contains(accepted.receipt().disposition());
            case TransactionClient.ObservedOutcome.Dispatcher accepted -> accepted.receipt().disposition().equals(Transactions.StateOperationDisposition.COMMITTED);
            default -> false;
        };
    }

    <Response> CompletableFuture<TransactionClient.ClientResponse<Response>> wrap(CompletableFuture<Management.ClientResponse<Response>> source) {
        CompletableFuture<TransactionClient.ClientResponse<Response>> future = new CompletableFuture<>() {
            @Override public boolean cancel(boolean interrupt) { return !isDone() && source.cancel(interrupt); }
        };
        source.whenComplete((result, failure) -> {
            if (failure == null) future.complete(new TransactionClient.ClientResponse<>(result.value(), new TransactionClient.ResponseMetadata(result.metadata(), identity)));
            else {
                Management.ClientFailure transport = Management.clientFailure(failure).orElseGet(() -> new Management.ClientFailure(
                        Management.FailureCategory.TRANSPORT, "bounded transaction RPC failure", Optional.empty(), Optional.empty(), true,
                        Management.OutcomeKnowledge.UNKNOWN, transportIdentity(), Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty()));
                var error = new TransactionClient.ClientFailure(transport, identity, observation);
                if (transport.category().equals(Management.FailureCategory.LOCAL_CANCELLED)) future.completeExceptionally(new TransactionClient.ClientCancellationException(error));
                else future.completeExceptionally(new TransactionClient.ClientException(error));
            }
        });
        return future;
    }

    private static final class SetHolder {
        static final java.util.Set<Transactions.CommandOutcome> TERMINAL = java.util.Set.of(
                Transactions.CommandOutcome.COMMITTED, Transactions.CommandOutcome.REJECTED, Transactions.CommandOutcome.ABORTED);
        static final java.util.Set<Transactions.StateOperationDisposition> DISPOSITIONS = java.util.Set.of(
                Transactions.StateOperationDisposition.COMMITTED, Transactions.StateOperationDisposition.CONFLICT, Transactions.StateOperationDisposition.REJECTED);
    }
    private static final class Builder {
        Optional<Transactions.NamespaceSelector> namespace = Optional.empty(); Optional<Transactions.CommandSelector> command = Optional.empty();
        Optional<String> activation = Optional.empty(), operation = Optional.empty(), attempt = Optional.empty(), receipt = Optional.empty(), retry = Optional.empty(), effect = Optional.empty();
        Optional<ByteBuffer> fingerprint = Optional.empty(), version = Optional.empty(); Optional<Transactions.AbortFence> abort = Optional.empty();
        Optional<Management.PublicationRef> publication = Optional.empty(); List<Transactions.ExpectedVersion> versions = List.of();
        Optional<Long> generation = Optional.empty(); Optional<String> policy = Optional.empty(); Optional<Transactions.DispatcherAction> action = Optional.empty();
        Optional<Transactions.DispatcherGeneration> dispatcherGeneration = Optional.empty();
        Builder() { }
        Builder(TransactionClient.RecoveryIdentity value) {
            namespace = value.namespace(); command = value.command(); activation = value.activationId(); operation = value.operationId();
            attempt = value.attemptId(); receipt = value.receiptId(); retry = value.retryRequestId(); effect = value.effectId(); fingerprint = value.fingerprintSha256();
            abort = value.expectedAbort(); publication = value.authorizationPublication(); versions = value.expectedVersions(); generation = value.expectedGeneration();
            version = value.expectedVersion(); policy = value.expectedPolicyDigest(); action = value.dispatcherAction(); dispatcherGeneration = value.dispatcherExpectedGeneration();
        }
        TransactionClient.RecoveryIdentity build() {
            return new TransactionClient.RecoveryIdentity(namespace, command, activation, operation, attempt, receipt, retry, effect, fingerprint, abort,
                    publication, versions, generation, version, policy, action, dispatcherGeneration);
        }
    }
}
