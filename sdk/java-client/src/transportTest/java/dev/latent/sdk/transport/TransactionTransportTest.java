package dev.latent.sdk.transport;

import dev.latent.sdk.Management;
import dev.latent.sdk.TransactionClient;
import dev.latent.sdk.Transactions;
import com.google.protobuf.ByteString;
import com.google.protobuf.Message;
import io.grpc.Metadata;
import io.grpc.MethodDescriptor;
import io.grpc.Server;
import io.grpc.ServerCall;
import io.grpc.ServerCallHandler;
import io.grpc.ServerServiceDefinition;
import io.grpc.Status;
import io.grpc.netty.shaded.io.grpc.netty.NettyServerBuilder;
import io.grpc.netty.shaded.io.netty.channel.nio.NioEventLoopGroup;
import io.grpc.netty.shaded.io.netty.channel.socket.nio.NioServerSocketChannel;
import io.grpc.protobuf.ProtoUtils;
import java.net.InetSocketAddress;
import java.nio.ByteBuffer;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import latent.control.v1.Common;
import latent.control.v1.Release;
import latent.control.v1.Dispatcher;
import latent.control.v1.DispatcherServiceGrpc;
import latent.control.v1.State;
import latent.control.v1.StateServiceGrpc;
import latent.invocation.v1.Invocation;
import latent.transaction.v1.Transaction;
import latent.transaction.v1.TransactionServiceGrpc;

/** Actual HTTP/2 peers; these do not replace the independent signed-node matrix. */
public final class TransactionTransportTest {
    private static final String DIGEST = "sha256:" + "a".repeat(64);
    private static final String PUBLICATION = "publication:sha256:" + "b".repeat(64);
    private static final Management.CallOptions OPTIONS = new Management.CallOptions(Optional.of(2000L));
    private static int checks;
    private TransactionTransportTest() { }
    static void check(boolean value, String name) { checks++; if (!value) throw new AssertionError(name); }
    private static <Value> Value get(CompletableFuture<Value> future) throws Exception { return future.get(4, TimeUnit.SECONDS); }
    private static TransactionClient.ClientFailure failure(CompletableFuture<?> future) throws Exception {
        try { get(future); throw new AssertionError("expected typed transaction failure"); }
        catch (java.util.concurrent.ExecutionException | java.util.concurrent.CancellationException error) {
            return TransactionClient.clientFailure(error).orElseThrow(() -> new AssertionError("lost transaction recovery failure", error));
        }
    }
    static Transaction.TransactionProfile profile() { return TransactionWire.toWire(Transactions.currentProfile()); }
    static Transaction.NamespaceSelector namespace() {
        return Transaction.NamespaceSelector.newBuilder().setTenant("tenant-a").setNamespace("transactional-aggregate").setIncarnation("1").build();
    }
    static Transaction.CommandSelector selector() {
        return Transaction.CommandSelector.newBuilder().setNamespace(namespace()).setOperation("update").setEntity("aggregate-a").setClientKey("business-key-a").build();
    }
    static Release.PublicationRef publication() { return Release.PublicationRef.newBuilder().setId(PUBLICATION).setTenant("tenant-a").build(); }
    static State.InspectNamespaceRequest inspect() { return State.InspectNamespaceRequest.newBuilder().setProfile(profile()).setNamespace(namespace()).setAuthorizationPublication(publication()).build(); }
    static Transaction.LookupCommandRequest lookup() { return Transaction.LookupCommandRequest.newBuilder().setProfile(profile()).setCommand(selector()).setAuthorizationPublication(publication()).build(); }
    static Invocation.InvokeRequest invocation() {
        return Invocation.InvokeRequest.newBuilder().setActivationId("activation-a").setTarget(Invocation.InvocationTarget.newBuilder()
                .setTenant("tenant-a").setService("aggregate").setContract("example:aggregate/api@1.0.0").setFunction("update"))
                .setPayload(ByteString.copyFrom(new byte[]{0, -1})).setMediaType("application/octet-stream")
                .setBudget(Invocation.ResourceBudget.newBuilder().setCpuFuel(-1L)).build();
    }
    static Transaction.InvokeCommandRequest invoke() {
        return Transaction.InvokeCommandRequest.newBuilder().setProfile(profile()).setCommand(selector()).setInvocation(invocation())
                .setInputFormat("aggregate-input-v1").addExpectedVersions(Transaction.ExpectedVersion.newBuilder().setKey(ByteString.copyFrom(new byte[]{0, -1})).setVersion(ByteString.copyFrom(new byte[]{1}))).build();
    }
    static Transaction.SourceIdentity source() {
        return Transaction.SourceIdentity.newBuilder().setPublicationId(PUBLICATION).setRevisionId("revision-a").setReleaseDigest(DIGEST)
                .setComponentDigest(DIGEST).setContractDigest(DIGEST).setStateSchema(DIGEST).setRouteGeneration(-1L)
                .setInputFormat("aggregate-input-v1").setResultFormat("aggregate-result-v1").build();
    }
    static Transaction.CommandInspection command(int outcome, boolean payload) {
        var result = Transaction.CommandInspection.newBuilder().setKey(Transaction.CommandKey.newBuilder().setNamespace(namespace())
                .setRecoveryScope("caller:subject-a").setOperation("update").setEntity("aggregate-a").setClientKey("business-key-a"))
                .setCommandId("command-a").setAttemptId("attempt-a").setFingerprintSha256(ByteString.copyFrom(new byte[32]))
                .setOutcomeValue(outcome).setMetadataDurable(true).setSource(source()).setRetention(Transaction.LinkedRetention.newBuilder()
                        .setRecordFormat("command-v1").setRecordVersion(1).setPayloadAvailable(payload).setRemainingRecoveryMillis(-1L).addRequiredRecordIds("command-a"));
        if (outcome == 2) {
            result.setApplicationStateCommitted(true).setCommit(Transaction.CommitReceipt.newBuilder().setCommandId("command-a").setAttemptId("attempt-a")
                    .setTransactionId("transaction-a").setReceiptId("receipt-a").setCommittedVersion(ByteString.copyFrom(new byte[]{1}))
                    .setCommittedAtUnixMillis(-1L).setSource(source()).addEffectIds("effect-a"));
            if (payload) result.setSuccess(Invocation.Success.newBuilder().setPayload(ByteString.copyFrom(new byte[]{0, -1})).setMediaType("application/octet-stream"));
        } else if (outcome == 3 && payload) {
            result.setBusinessRejection(Invocation.DeclaredError.newBuilder().setCode("business-rejected").setMessage("expected rejection")
                    .setPayload(ByteString.copyFrom(new byte[]{0, -1})).setMediaType("application/octet-stream"));
        } else if (outcome == 4) {
            result.setTechnicalFailure(Invocation.PlatformError.newBuilder().setCode("cancelled").setMessage("physical owner retired"))
                    .setProvenAbort(Transaction.AbortFence.newBuilder().setCommandId("command-a").setAttemptId("attempt-a").setTransactionId("transaction-a")
                            .setOwnerFence(ByteString.copyFrom(new byte[]{1, 2})));
        }
        return result.build();
    }
    static Invocation.InvokeResponse invoked(Transaction.CommandInspection command) {
        var result = Invocation.InvokeResponse.newBuilder().setActivationId("activation-a").setRevisionId("revision-a").setPublicationId(PUBLICATION)
                .setReleaseDigest(DIGEST).setRouteGeneration(-1L).setConsumption(Invocation.BudgetConsumption.newBuilder().setCpuFuel(-1L));
        if (command.hasSuccess()) result.setSuccess(command.getSuccess());
        if (command.hasBusinessRejection()) result.setDeclaredError(command.getBusinessRejection());
        if (command.hasTechnicalFailure()) result.setPlatformFailure(command.getTechnicalFailure());
        return result.build();
    }
    static Transaction.ViewIdentity view() { return Transaction.ViewIdentity.newBuilder().setNamespace(namespace()).setVersion(ByteString.copyFrom(new byte[]{1})).setStateSchema(DIGEST).build(); }
    static Transaction.EffectReceipt effect() {
        return Transaction.EffectReceipt.newBuilder().setEffectId("effect-a").setCommandId("command-a").setCommandAttemptId("attempt-a")
                .setProviderProfile("approved-provider-v1").setDispatchAttempt(1).setDispositionValue(3).setProviderReceipt("provider-receipt-a").setOccurredAtUnixMillis(-1L).build();
    }
    static State.StateOperationReceipt stateReceipt() {
        return State.StateOperationReceipt.newBuilder().setOperationId("state-operation-a").setReceiptId("state-receipt-a").setMutationValue(4)
                .setNamespace(namespace()).setAuthenticatedOperator("operator-a").setBeforeVersion(ByteString.copyFrom(new byte[]{1}))
                .setAfterVersion(ByteString.copyFrom(new byte[]{2})).setPolicyDigest(DIGEST).setDispositionValue(1).setCompletedAtUnixMillis(-1L).build();
    }
    static Dispatcher.ControlDispatcherRequest control() {
        return Dispatcher.ControlDispatcherRequest.newBuilder().setProfile(profile()).setScopeValue(1).setOperationId("dispatcher-operation-a")
                .setActionValue(1).setExpectedGeneration(Dispatcher.DispatcherGeneration.newBuilder().setOwnerEpoch(-1L).setRevision(-2L)).build();
    }
    static Dispatcher.DispatcherOperationReceipt dispatcherReceipt(Dispatcher.ControlDispatcherRequest original) {
        return Dispatcher.DispatcherOperationReceipt.newBuilder().setOperationId(original.getOperationId()).setReceiptId("dispatcher-receipt-a")
                .setActionValue(original.getActionValue()).setAuthenticatedOperator("operator-a").setActorTenant("operator-tenant-a")
                .setBeforeGeneration(original.getExpectedGeneration()).setAfterGeneration(original.getExpectedGeneration().toBuilder()
                        .setRevision(original.getExpectedGeneration().getRevision() + 1)).setObservedAtUnixMillis(-1L).setClockContinuityProven(true).setDispositionValue(1).build();
    }

    @SuppressWarnings("deprecation")
    private static final class Peer implements AutoCloseable {
        final AtomicInteger calls = new AtomicInteger();
        final Set<Object> connections = ConcurrentHashMap.newKeySet();
        final Map<String, Message> requests = new ConcurrentHashMap<>();
        final CountDownLatch received = new CountDownLatch(1), cancelled = new CountDownLatch(1);
        final NioEventLoopGroup accept = new NioEventLoopGroup(1), work = new NioEventLoopGroup(1);
        final Server server;
        volatile String mode = "normal";
        Peer() throws Exception {
            Map<String, ServerServiceDefinition.Builder> services = new LinkedHashMap<>();
            for (var method : List.of(TransactionServiceGrpc.getInvokeCommandMethod(), TransactionServiceGrpc.getQueryMethod(),
                    TransactionServiceGrpc.getLookupCommandMethod(), TransactionServiceGrpc.getLookupCommitMethod(), TransactionServiceGrpc.getGetEffectMethod(),
                    TransactionServiceGrpc.getListEffectHistoryMethod(), TransactionServiceGrpc.getCancelCommandMethod(), StateServiceGrpc.getInspectNamespaceMethod(),
                    StateServiceGrpc.getSelectEntityMethod(), StateServiceGrpc.getMutateStateMethod(), StateServiceGrpc.getMutateNamespaceMethod(),
                    StateServiceGrpc.getGetStateOperationReceiptMethod(), DispatcherServiceGrpc.getInspectDispatcherMethod(),
                    DispatcherServiceGrpc.getControlDispatcherMethod(), DispatcherServiceGrpc.getGetDispatcherOperationMethod())) {
                add(services.computeIfAbsent(method.getServiceName(), ServerServiceDefinition::builder), method);
            }
            var builder = NettyServerBuilder.forAddress(new InetSocketAddress("127.0.0.1", 0)).bossEventLoopGroup(accept).workerEventLoopGroup(work)
                    .channelType(NioServerSocketChannel.class).directExecutor().maxInboundMessageSize(TransactionProtocol.WIRE_BYTES);
            for (var service : services.values()) builder.addService(service.build());
            server = builder.build().start();
        }
        private <Request, Response> void add(ServerServiceDefinition.Builder service, MethodDescriptor<Request, Response> method) {
            service.addMethod(method, new ServerCallHandler<>() {
                @Override public ServerCall.Listener<Request> startCall(ServerCall<Request, Response> call, Metadata headers) {
                    connections.add(call.getAttributes().get(io.grpc.Grpc.TRANSPORT_ATTR_REMOTE_ADDR));
                    check("Bearer test-only-java-token".equals(headers.get(Metadata.Key.of("authorization", Metadata.ASCII_STRING_MARSHALLER))), "existing auth default");
                    call.request(1);
                    return new ServerCall.Listener<>() {
                        Request request;
                        @Override public void onMessage(Request value) { request = value; }
                        @Override public void onCancel() { cancelled.countDown(); }
                        @SuppressWarnings("unchecked")
                        @Override public void onHalfClose() {
                            String operation = method.getBareMethodName(); calls.incrementAndGet(); requests.put(operation, (Message) request); received.countDown();
                            if (operation.equals("InvokeCommand") && mode.equals("hold")) return;
                            if (operation.equals("InvokeCommand") && (mode.equals("lost") || mode.equals("transport-abort"))) {
                                call.close(mode.equals("lost") ? Status.UNAVAILABLE : Status.ABORTED, new Metadata()); return;
                            }
                            call.sendHeaders(new Metadata()); call.sendMessage((Response) reply(operation, (Message) request)); call.close(Status.OK, new Metadata());
                        }
                    };
                }
            });
        }
        private Message reply(String name, Message request) {
            return switch (name) {
                case "InvokeCommand" -> {
                    var accepted = command(2, true).toBuilder().setSuccess(Invocation.Success.newBuilder().setPayload(ByteString.copyFrom(new byte[750 * 1024])).setMediaType("application/octet-stream")).build();
                    yield Transaction.InvokeCommandResponse.newBuilder().setCommand(accepted).setInvocation(invoked(accepted)).build();
                }
                case "Query" -> Transaction.QueryResponse.newBuilder().setView(view()).setSource(source()).setInvocation(invoked(command(2, true))).setObservedAtUnixMillis(-1L).build();
                case "LookupCommand" -> Transaction.LookupCommandResponse.newBuilder().setCommand(command(mode.equals("rejection") ? 3 : mode.equals("proven-abort") ? 4 : 2, !mode.equals("expired-payload"))).build();
                case "LookupCommit" -> Transaction.LookupCommitResponse.newBuilder().setCommand(command(2, true)).build();
                case "GetEffect" -> Transaction.GetEffectResponse.newBuilder().setEffect(effect()).build();
                case "ListEffectHistory" -> Transaction.ListEffectHistoryResponse.newBuilder().addReceipts(effect()).setPage(Transaction.PageResponse.newBuilder().setReturnedCount(1).setEncodedBytes(128).setNextCursor(ByteString.copyFrom(new byte[]{1}))).build();
                case "CancelCommand" -> Transaction.CancelCommandResponse.newBuilder().setDispositionValue(2).setCommand(command(2, true)).build();
                case "InspectNamespace" -> State.InspectNamespaceResponse.newBuilder().setNamespace(State.NamespaceInspection.newBuilder().setView(view()).setStatusValue(1)
                        .setEngineProfile("redb-v1").setEngineProfileDigest(DIGEST).setGeneration(-1L).setQuota(State.NamespaceQuota.newBuilder().setStateKeys(1)
                                .setStateBytes(4096).setResultRows(1).setResultBytes(4096).setEffectRows(1).setEffectBytes(4096).setPayloadBytes(4096).setRecoveryBytes(4096))).build();
                case "SelectEntity" -> State.SelectEntityResponse.newBuilder().addEntities(State.EntityInspection.newBuilder().setEntity("aggregate-a").setVersion(ByteString.copyFrom(new byte[]{1})))
                        .setPage(Transaction.PageResponse.newBuilder().setReturnedCount(1).setEncodedBytes(32).setNextCursor(ByteString.copyFrom(new byte[]{2}))).build();
                case "MutateState" -> State.MutateStateResponse.newBuilder().setReceipt(stateReceipt()).setAuditAck(Common.AuditAck.newBuilder().setStatusValue(1).setAttemptSequence(-1L)).build();
                case "MutateNamespace" -> State.MutateNamespaceResponse.newBuilder().setReceipt(State.NamespaceOperationReceipt.newBuilder().setOperationId("namespace-operation-a")
                        .setReceiptId("namespace-receipt-a").setMutationValue(2).setNamespace(namespace()).setAuthenticatedOperator("operator-a").setBeforeGeneration(-2L)
                        .setAfterGeneration(-1L).setStatusValue(2).setStateSchema(DIGEST).setDispositionValue(1)).build();
                case "GetStateOperationReceipt" -> State.GetStateOperationReceiptResponse.newBuilder().setReceipt(stateReceipt()).build();
                case "InspectDispatcher" -> Dispatcher.InspectDispatcherResponse.newBuilder().setDispatcher(Dispatcher.DispatcherSnapshot.newBuilder()
                        .setGeneration(Dispatcher.DispatcherGeneration.newBuilder().setOwnerEpoch(-1L).setRevision(-1L)).setPaused(true).setFailureValue(1)
                        .setPhysicalOwners(-1L).setCountsObservedAtUnixMillis(-1L)).build();
                case "ControlDispatcher" -> {
                    var result = Dispatcher.ControlDispatcherResponse.newBuilder().setReceipt(dispatcherReceipt((Dispatcher.ControlDispatcherRequest) request)).setPublished(true).setPaused(true);
                    if (mode.equals("audit")) result.setAuditAck(Common.AuditAck.newBuilder().setStatusValue(91));
                    if (mode.equals("replayed")) result.setReplayed(true);
                    if (mode.equals("not-committed")) result.setReceipt(result.getReceipt().toBuilder().setDispositionValue(2));
                    if (mode.equals("resume-unproven")) result.setReceipt(result.getReceipt().toBuilder().setClockContinuityProven(false));
                    yield result.build();
                }
                case "GetDispatcherOperation" -> Dispatcher.GetDispatcherOperationResponse.newBuilder().setReceipt(dispatcherReceipt(((Dispatcher.GetDispatcherOperationRequest) request).getOriginal())).build();
                default -> throw new AssertionError("unregistered operation");
            };
        }
        RpcClient client() { return new RpcClient(new ClientConfig("http://127.0.0.1:" + server.getPort(), "tenant-a", "test-only-java-token", 4,
                TransactionProtocol.WIRE_BYTES, TransactionProtocol.WIRE_BYTES, 5000, 1000, 3000)); }
        @Override public void close() throws Exception {
            server.shutdownNow(); check(server.awaitTermination(3, TimeUnit.SECONDS), "transaction peer retired");
            accept.shutdownGracefully(0, 1, TimeUnit.SECONDS).sync(); work.shutdownGracefully(0, 1, TimeUnit.SECONDS).sync();
        }
    }

    private static void fifteenOperationsAndOwnedSnapshots() throws Exception {
        try (var peer = new Peer(); var client = peer.client()) {
            check(client.snapshot().activeCalls() == 0 && peer.connections.isEmpty(), "lazy same transport");
            var original = TransactionWire.fromWire(invoke());
            byte[] mutable = {1};
            var request = new Transactions.InvokeCommandRequest(original.profile(), original.invocation(), original.command(), original.inputFormat(),
                    List.of(new Transactions.ExpectedVersion(original.expectedVersions().getFirst().key(), Optional.empty(), Optional.of(ByteBuffer.wrap(mutable)))), original.retryAttempt());
            var pending = client.invokeCommand(request, OPTIONS); mutable[0] = 42;
            var invoked = get(pending);
            check(invoked.value().command().orElseThrow().success().orElseThrow().payload().remaining() == 750 * 1024, "large paired body within frozen wire bound");
            check(invoked.value().command().orElseThrow().success().orElseThrow().payload().isReadOnly(), "owned response buffer");
            check(invoked.metadata().identity().expectedVersions().getFirst().version().orElseThrow().get(0) == 1, "original version snapshot");
            check(((Transaction.InvokeCommandRequest) peer.requests.get("InvokeCommand")).getExpectedVersions(0).getVersion().byteAt(0) == 1, "wire snapshot before async dispatch");
            check(get(client.query(TransactionWire.fromWire(Transaction.QueryRequest.newBuilder().setProfile(profile()).setInvocation(invocation()).setNamespace(namespace()).build()), OPTIONS)).value().view().orElseThrow().namespace().orElseThrow().incarnation().equals("1"), "fresh query identity");
            check(get(client.lookupCommand(TransactionWire.fromWire(lookup()), OPTIONS)).value().command().orElseThrow().outcome().equals(Transactions.CommandOutcome.COMMITTED), "committed recovery");
            check(get(client.lookupCommit(TransactionWire.fromWire(Transaction.LookupCommitRequest.newBuilder().setProfile(profile()).setCommand(selector()).setAuthorizationPublication(publication()).setReceiptId("receipt-a").build()), OPTIONS)).metadata().identity().receiptId().equals(Optional.of("receipt-a")), "exact receipt recovery");
            var effectRequest = Transaction.GetEffectRequest.newBuilder().setProfile(profile()).setCommand(selector()).setAuthorizationPublication(publication()).setEffectId("effect-a").build();
            check(get(client.getEffect(TransactionWire.fromWire(effectRequest), OPTIONS)).value().effect().orElseThrow().disposition().equals(Transactions.EffectDisposition.PROVIDER_ACKNOWLEDGED), "provider ack separate outcome");
            var history = get(client.listEffectHistory(TransactionWire.fromWire(Transaction.ListEffectHistoryRequest.newBuilder().setEffect(effectRequest).setPage(Transaction.PageRequest.newBuilder().setLimit(128)).build()), OPTIONS));
            check(history.value().receipts().size() == 1 && history.value().page().orElseThrow().nextCursor().isPresent(), "short bounded page keeps continuation");
            check(get(client.cancelCommand(TransactionWire.fromWire(Transaction.CancelCommandRequest.newBuilder().setCommand(lookup()).setReason("explicit").build()), OPTIONS)).value().disposition().equals(Transactions.CommandCancelDisposition.ALREADY_COMMITTED), "cancel cannot erase commitment");
            check(get(client.inspectNamespace(TransactionWire.fromWire(inspect()), OPTIONS)).value().namespace().orElseThrow().generation() == -1L, "full unsigned generation");
            check(get(client.selectEntity(TransactionWire.fromWire(State.SelectEntityRequest.newBuilder().setNamespace(inspect()).setPage(Transaction.PageRequest.newBuilder().setLimit(128)).build()), OPTIONS)).value().entities().size() == 1, "entity selection");
            check(get(client.mutateState(TransactionWire.fromWire(State.MutateStateRequest.newBuilder().setNamespace(inspect()).setOperationId("state-operation-a").setMutationValue(4)
                    .setExpectedVersion(ByteString.copyFrom(new byte[]{1})).setExpectedPolicyDigest(DIGEST).setReason("explicit").build()), OPTIONS)).metadata().identity().expectedPolicyDigest().equals(Optional.of(DIGEST)), "captured management digest");
            check(get(client.mutateNamespace(TransactionWire.fromWire(State.MutateNamespaceRequest.newBuilder().setNamespace(inspect()).setOperationId("namespace-operation-a").setMutationValue(2).setExpectedGeneration(-2L).build()), OPTIONS)).value().receipt().orElseThrow().afterGeneration() == -1L, "unsigned generation successor");
            check(get(client.getStateOperationReceipt(TransactionWire.fromWire(State.GetStateOperationReceiptRequest.newBuilder().setNamespace(inspect()).setOperationId("state-operation-a").build()), OPTIONS)).value().receipt().orElseThrow().receiptId().equals("state-receipt-a"), "management recovery");
            check(get(client.inspectDispatcher(TransactionWire.fromWire(Dispatcher.InspectDispatcherRequest.newBuilder().setProfile(profile()).setScopeValue(1).build()), OPTIONS)).value().dispatcher().orElseThrow().physicalOwners() == -1L, "unsigned physical count");
            check(get(client.controlDispatcher(TransactionWire.fromWire(control()), OPTIONS)).value().receipt().orElseThrow().afterGeneration().orElseThrow().revision() == -1L, "dispatcher precondition");
            check(get(client.getDispatcherOperation(TransactionWire.fromWire(Dispatcher.GetDispatcherOperationRequest.newBuilder().setOriginal(control()).build()), OPTIONS)).metadata().identity().dispatcherExpectedGeneration().orElseThrow().revision() == -2L, "dispatcher original recovery");
            check(peer.calls.get() == 15 && peer.connections.size() == 1, "all fifteen share one physical connection");
            check(client.shutdown(Duration.ofSeconds(3)).clean(), "finite owner retirement");
        }
    }

    private static void durableFormatsAuditAndExplicitRecovery() throws Exception {
        try (var peer = new Peer(); var client = peer.client()) {
            peer.mode = "rejection";
            var rejected = get(client.lookupCommand(TransactionWire.fromWire(lookup()), OPTIONS));
            check(rejected.value().command().orElseThrow().outcome().equals(Transactions.CommandOutcome.REJECTED)
                    && !rejected.value().command().orElseThrow().applicationStateCommitted(), "durable business rejection");
            peer.mode = "expired-payload";
            var expired = get(client.lookupCommand(TransactionWire.fromWire(lookup()), OPTIONS)).value().command().orElseThrow();
            check(expired.success().isEmpty() && !expired.retention().orElseThrow().payloadAvailable() && expired.commit().isPresent(), "retained old success without payload");
            peer.mode = "proven-abort";
            var aborted = get(client.lookupCommand(TransactionWire.fromWire(lookup()), OPTIONS)).value().command().orElseThrow();
            check(aborted.provenAbort().isPresent() && aborted.outcome().equals(Transactions.CommandOutcome.ABORTED), "only durable aborted record carries fence");
            peer.mode = "audit";
            var failed = failure(client.controlDispatcher(TransactionWire.fromWire(control()), OPTIONS));
            check(failed.transport().outcome().equals(Management.OutcomeKnowledge.OBSERVED) && failed.observed().orElseThrow() instanceof TransactionClient.ObservedOutcome.Dispatcher, "independent audit keeps valid primary receipt");
            check(failed.transport().unsupportedWireValue().orElseThrow().value().equals("91") && failed.identity().dispatcherExpectedGeneration().orElseThrow().revision() == -2L, "raw unknown audit and original generation");
            peer.mode = "normal";
            check(get(client.getDispatcherOperation(TransactionWire.fromWire(Dispatcher.GetDispatcherOperationRequest.newBuilder().setOriginal(control()).build()), OPTIONS)).value().receipt().orElseThrow().receiptId().equals("dispatcher-receipt-a"), "explicit receipt lookup");
            for (String mode : List.of("replayed", "not-committed", "resume-unproven")) {
                peer.mode = mode;
                var requested = control().toBuilder().setActionValue(mode.equals("resume-unproven") ? 2 : 1).build();
                check(failure(client.controlDispatcher(TransactionWire.fromWire(requested), OPTIONS)).observed().isEmpty(), "invalid receipt supplies no durable proof");
            }
            int before = peer.calls.get();
            var max = control().toBuilder().setExpectedGeneration(control().getExpectedGeneration().toBuilder().setRevision(-1L)).build();
            var exhausted = failure(client.controlDispatcher(TransactionWire.fromWire(max), OPTIONS));
            check(!exhausted.transport().dispatched() && exhausted.identity().dispatcherExpectedGeneration().orElseThrow().revision() == -1L && peer.calls.get() == before, "no representable successor keeps original CAS without I/O");
        }
    }

    private static void lostResponseAndCancellationNeverResubmit() throws Exception {
        for (String mode : List.of("lost", "transport-abort", "hold")) {
            try (var peer = new Peer(); var client = peer.client()) {
                peer.mode = mode;
                var pending = client.invokeCommand(TransactionWire.fromWire(invoke()), OPTIONS);
                check(peer.received.await(2, TimeUnit.SECONDS), "actual dispatch readiness");
                if (mode.equals("hold")) { check(pending.cancel(false), "local cancellation"); check(peer.cancelled.await(2, TimeUnit.SECONDS), "physical cancellation readiness"); }
                var failed = failure(pending);
                check(failed.transport().outcome().equals(Management.OutcomeKnowledge.UNKNOWN) && failed.observed().isEmpty() && failed.identity().expectedAbort().isEmpty(), "transport cannot invent technical abort");
                check(failed.identity().activationId().equals(Optional.of("activation-a")) && failed.identity().command().orElseThrow().clientKey().equals("business-key-a"), "original stable business identity");
                check(peer.calls.get() == 1, "no automatic mutation resubmission");
                peer.mode = "normal";
                check(get(client.lookupCommand(TransactionWire.fromWire(lookup()), OPTIONS)).value().command().orElseThrow().outcome().equals(Transactions.CommandOutcome.COMMITTED), "recovery uses fresh live call");
                check(peer.calls.get() == 2 && client.shutdown(Duration.ofSeconds(3)).clean(), "explicit recovery and finite drain");
            }
        }
    }

    private static void malformedAndUnknownResponses() throws Exception {
        var requested = TransactionWire.fromWire(Transaction.ListEffectHistoryRequest.newBuilder().setEffect(Transaction.GetEffectRequest.newBuilder()
                .setProfile(profile()).setCommand(selector()).setAuthorizationPublication(publication()).setEffectId("effect-a"))
                .setPage(Transaction.PageRequest.newBuilder().setLimit(128)).build());
        byte[] expansion = new byte[129 * 2]; for (int index = 0; index < expansion.length; index += 2) expansion[index] = 10;
        try (var peer = new RawPeer(TransactionServiceGrpc.getListEffectHistoryMethod(), request -> new RawPeer.Reply(expansion, Status.OK, new Metadata(), new Metadata())); var client = peer.client()) {
            check(failure(client.listEffectHistory(requested, OPTIONS)).transport().category().equals(Management.FailureCategory.DECODE), "predecode expansion denied");
        }
        for (byte[] raw : List.of(Transaction.LookupCommandResponse.newBuilder().setCommand(command(91, true)).build().toByteArray(), new byte[]{10, 0, 10, 0}, new byte[]{10, 2, 18, 1, -1})) {
            try (var peer = new RawPeer(TransactionServiceGrpc.getLookupCommandMethod(), request -> new RawPeer.Reply(raw, Status.OK, new Metadata(), new Metadata())); var client = peer.client()) {
                var failed = failure(client.lookupCommand(TransactionWire.fromWire(lookup()), OPTIONS));
                check(failed.observed().isEmpty(), "malformed/future command cannot prove outcome");
                if (raw.length > 20) check(failed.transport().unsupportedWireValue().orElseThrow().value().equals("91"), "unknown enum retained losslessly");
            }
        }
        var swapped = Transaction.QueryResponse.newBuilder().setView(view()).setSource(source()).setInvocation(invoked(command(2, true)).toBuilder().setActivationId("substituted")).build().toByteArray();
        try (var peer = new RawPeer(TransactionServiceGrpc.getQueryMethod(), request -> new RawPeer.Reply(swapped, Status.OK, new Metadata(), new Metadata())); var client = peer.client()) {
            var requestedQuery = Transaction.QueryRequest.newBuilder().setProfile(profile()).setInvocation(invocation()).setNamespace(namespace()).build();
            check(failure(client.query(TransactionWire.fromWire(requestedQuery), OPTIONS)).observed().isEmpty(), "activation substitution denied");
        }
        var retained = command(2, false).toBuilder().setRetention(command(2, false).getRetention().toBuilder().clearRequiredRecordIds()
                .addAllRequiredRecordIds(java.util.stream.IntStream.range(0, 256).mapToObj(index -> "required-" + index).toList())).build();
        try (var peer = new RawPeer(TransactionServiceGrpc.getLookupCommandMethod(), request -> new RawPeer.Reply(
                Transaction.LookupCommandResponse.newBuilder().setCommand(retained).build().toByteArray(), Status.OK, new Metadata(), new Metadata())); var client = peer.client()) {
            check(get(client.lookupCommand(TransactionWire.fromWire(lookup()), OPTIONS)).value().command().orElseThrow().retention().orElseThrow().requiredRecordIds().size() == 256,
                    "separate linked-retention bound survives predecode");
        }
        try (var peer = new RawPeer(TransactionServiceGrpc.getLookupCommandMethod(), request -> new RawPeer.Reply(new byte[4096], Status.OK, new Metadata(), new Metadata()));
                var client = new RpcClient(new ClientConfig(peer.endpoint(), "tenant-a", "test-only-java-token", 2, 1024, 256, 2000, 500, 2000))) {
            var oversized = failure(client.lookupCommand(TransactionWire.fromWire(lookup()), OPTIONS));
            check(oversized.observed().isEmpty() && oversized.transport().outcome().equals(Management.OutcomeKnowledge.UNKNOWN), "oversized response cannot prove commitment");
        }
    }

    private static void localProfilesPresenceAndBounds() throws Exception {
        try (var peer = new Peer(); var client = peer.client()) {
            var wrongProfile = invoke().toBuilder().setProfile(profile().toBuilder().setHostAbiDigest("sha256:" + "c".repeat(64))).build();
            check(!failure(client.invokeCommand(TransactionWire.fromWire(wrongProfile), OPTIONS)).transport().dispatched(), "stale ABI profile rejected before mutation");
            var wrongTenant = lookup().toBuilder().setCommand(selector().toBuilder().setNamespace(namespace().toBuilder().setTenant("other-tenant"))).build();
            check(!failure(client.lookupCommand(TransactionWire.fromWire(wrongTenant), OPTIONS)).transport().dispatched(), "tenant convenience value grants no access");
            var presentFalse = invoke().toBuilder().clearExpectedVersions().addExpectedVersions(Transaction.ExpectedVersion.newBuilder().setKey(ByteString.EMPTY).setAbsent(false)).build();
            var mapped = TransactionWire.fromWire(presentFalse);
            check(mapped.expectedVersions().getFirst().absent().equals(Optional.of(false)), "false retains presence through generated bridge");
            check(!failure(client.invokeCommand(mapped, OPTIONS)).transport().dispatched(), "explicit absent false is not valid stale-edit evidence");
            var expansion = invoke().toBuilder().clearExpectedVersions().addAllExpectedVersions(java.util.Collections.nCopies(129,
                    Transaction.ExpectedVersion.newBuilder().setAbsent(true).build())).build();
            check(!failure(client.invokeCommand(TransactionWire.fromWire(expansion), OPTIONS)).transport().dispatched(), "preconversion collection expansion denied");
            var zero = failure(client.invokeCommand(TransactionWire.fromWire(invoke()), new Management.CallOptions(Optional.of(0L))));
            check(zero.transport().category().equals(Management.FailureCategory.DEADLINE) && zero.identity().activationId().equals(Optional.of("activation-a"))
                    && zero.identity().expectedVersions().getFirst().version().orElseThrow().get(0) == 1, "zero deadline keeps original recovery without dispatch");
            check(peer.calls.get() == 0 && peer.connections.isEmpty(), "local checks open no channel");
        }
    }

    public static void main(String[] args) throws Exception {
        fifteenOperationsAndOwnedSnapshots(); durableFormatsAuditAndExplicitRecovery(); lostResponseAndCancellationNeverResubmit(); malformedAndUnknownResponses(); localProfilesPresenceAndBounds();
        System.out.println("Java transactions: five bounded transport suites; " + checks + " checks passed");
    }
}
