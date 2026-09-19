package dev.latent.sdk.transport;

import dev.latent.sdk.LatentClient;
import dev.latent.sdk.Management;
import dev.latent.sdk.Models;
import com.google.protobuf.Message;
import io.grpc.ClientCall;
import io.grpc.ClientStreamTracer;
import io.grpc.Deadline;
import io.grpc.DecompressorRegistry;
import io.grpc.ManagedChannel;
import io.grpc.Metadata;
import io.grpc.MethodDescriptor;
import io.grpc.Status;
import io.grpc.netty.shaded.io.grpc.netty.NettyChannelBuilder;
import io.grpc.netty.shaded.io.netty.channel.ChannelOption;
import io.grpc.netty.shaded.io.netty.channel.DefaultSelectStrategyFactory;
import io.grpc.netty.shaded.io.netty.channel.nio.NioEventLoopGroup;
import io.grpc.netty.shaded.io.netty.channel.socket.nio.NioSocketChannel;
import io.grpc.netty.shaded.io.netty.util.concurrent.DefaultEventExecutorChooserFactory;
import io.grpc.netty.shaded.io.netty.util.concurrent.RejectedExecutionHandlers;
import io.grpc.netty.shaded.io.netty.util.concurrent.ThreadPerTaskExecutor;
import java.nio.channels.spi.SelectorProvider;
import java.time.Duration;
import java.util.HashSet;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Function;
import latent.invocation.v1.Invocation;
import latent.invocation.v1.InvocationServiceGrpc;
import latent.control.v1.PolicyOuterClass;
import latent.control.v1.PolicyServiceGrpc;
import latent.control.v1.Capability;
import latent.control.v1.CapabilityServiceGrpc;

@SuppressWarnings("deprecation")
public final class RpcClient implements Management.ClientProfile, LatentClient, AutoCloseable {
    private static final AtomicInteger OWNERS = new AtomicInteger();
    private static final Metadata.Key<String> AUTHORIZATION = Metadata.Key.of("authorization", Metadata.ASCII_STRING_MARSHALLER);
    private final ClientConfig config;
    private final ManagedChannel channel;
    private final NioEventLoopGroup eventLoops;
    private final ThreadPoolExecutor completions;
    private final Set<CallState<?, ?, ?>> active = new HashSet<>();
    private final Set<Thread> threads = java.util.concurrent.ConcurrentHashMap.newKeySet();
    private boolean closing;

    @SuppressWarnings("deprecation")
    public RpcClient(ClientConfig config) {
        this.config = java.util.Objects.requireNonNull(config);
        String prefix = "latent-java-" + OWNERS.incrementAndGet() + "-";
        AtomicInteger sequence = new AtomicInteger();
        ThreadFactory factory = task -> {
            Thread thread = new Thread(task, prefix + sequence.incrementAndGet());
            thread.setDaemon(false);
            threads.add(thread);
            return thread;
        };
        int taskLimit = config.maximumCalls * 32 + 128;
        eventLoops = new NioEventLoopGroup(1, new ThreadPerTaskExecutor(factory),
                DefaultEventExecutorChooserFactory.INSTANCE, SelectorProvider.provider(),
                DefaultSelectStrategyFactory.INSTANCE, RejectedExecutionHandlers.reject(),
                ignored -> new ArrayBlockingQueue<>(taskLimit), ignored -> new ArrayBlockingQueue<>(taskLimit));
        completions = new ThreadPoolExecutor(2, 2, 0, TimeUnit.SECONDS,
                new ArrayBlockingQueue<>(config.maximumCalls), factory, new ThreadPoolExecutor.AbortPolicy());
        try {
            channel = NettyChannelBuilder.forAddress(config.address).usePlaintext()
                    .eventLoopGroup(eventLoops).channelType(NioSocketChannel.class)
                    .withOption(ChannelOption.CONNECT_TIMEOUT_MILLIS, config.connectMillis)
                    .withOption(ChannelOption.TCP_NODELAY, true)
                    .flowControlWindow(65535).maxInboundMessageSize(config.responseBytes)
                    .maxInboundMetadataSize(16384).directExecutor().offloadExecutor(Runnable::run)
                    .proxyDetector(address -> null).disableRetry().maxTraceEvents(0)
                    .decompressorRegistry(DecompressorRegistry.emptyInstance().with(io.grpc.Codec.Identity.NONE, false)).build();
        } catch (RuntimeException failure) {
            eventLoops.shutdownGracefully(0, 1, TimeUnit.SECONDS);
            completions.shutdown();
            throw new IllegalArgumentException("bounded client owner creation failed");
        }
    }

    public record Snapshot(int activeCalls, int queuedCompletions, int liveOwnedThreads, boolean closed) { }
    public record ShutdownReport(boolean channelTerminated, boolean eventLoopsTerminated, boolean executorTerminated,
            int activeCalls, int liveOwnedThreads) {
        public boolean clean() { return channelTerminated && eventLoopsTerminated && executorTerminated && activeCalls == 0 && liveOwnedThreads == 0; }
    }

    public synchronized Snapshot snapshot() {
        return new Snapshot(active.size(), completions.getQueue().size(), (int) threads.stream().filter(Thread::isAlive).count(), closing);
    }

    public ShutdownReport shutdown(Duration timeout) throws InterruptedException {
        if (timeout.isNegative() || timeout.isZero() || timeout.compareTo(Duration.ofSeconds(10)) > 0) {
            throw new IllegalArgumentException("shutdown timeout must be positive and at most ten seconds");
        }
        long deadline = System.nanoTime() + timeout.toNanos();
        CallState<?, ?, ?>[] pending;
        synchronized (this) { closing = true; pending = active.toArray(CallState[]::new); }
        for (var state : pending) state.cancel("client closed");
        channel.shutdownNow();
        channel.awaitTermination(Math.max(0, deadline - System.nanoTime()), TimeUnit.NANOSECONDS);
        eventLoops.shutdownGracefully(0, Math.max(1, deadline - System.nanoTime()), TimeUnit.NANOSECONDS);
        eventLoops.terminationFuture().await(Math.max(0, deadline - System.nanoTime()), TimeUnit.NANOSECONDS);
        synchronized (this) { if (active.isEmpty()) completions.shutdown(); }
        if (!threads.contains(Thread.currentThread())) {
            completions.awaitTermination(Math.max(0, deadline - System.nanoTime()), TimeUnit.NANOSECONDS);
            for (var thread : threads) {
                long remaining = deadline - System.nanoTime();
                if (remaining > 0 && thread.isAlive()) thread.join(Math.max(1, TimeUnit.NANOSECONDS.toMillis(remaining)));
            }
        }
        Snapshot state = snapshot();
        return new ShutdownReport(channel.isTerminated(), eventLoops.isTerminated(), completions.isTerminated(), state.activeCalls(), state.liveOwnedThreads());
    }

    @Override public void close() {
        try {
            if (!shutdown(Duration.ofMillis(config.shutdownMillis)).clean()) throw new IllegalStateException("bounded client shutdown is incomplete");
        } catch (InterruptedException failure) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("bounded client shutdown interrupted");
        }
    }

    @Override public String toString() { return "RpcClient[bounded numeric-loopback, credential=REDACTED]"; }

    private static Management.RequestIdentity recovery(Object request) {
        Optional<String> activation = switch (request) {
            case Management.InvokeRequest value -> value.activationId();
            case Management.CancelRequest value -> Optional.ofNullable(value.activationId());
            case Management.GetActivationRequest value -> Optional.ofNullable(value.activationId());
            default -> Optional.empty();
        };
        Optional<String> operation = switch (request) {
            case Management.ApplyPolicyRequest value -> Optional.ofNullable(value.operationId());
            case Management.GetPolicyOperationRequest value -> Optional.ofNullable(value.operationId());
            default -> Optional.empty();
        };
        return new Management.RequestIdentity(activation.filter(value -> value.length() <= 256), operation.filter(value -> value.length() <= 256));
    }

    private static Management.ClientFailure local(Management.FailureCategory category, Management.RequestIdentity identity) {
        return new Management.ClientFailure(category, "bounded client failure", Optional.empty(), Optional.empty(), false,
                Management.OutcomeKnowledge.NOT_DISPATCHED, identity, Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty());
    }

    private <Request, WireRequest extends Message, WireResponse extends Message, Response> CompletableFuture<Management.ClientResponse<Response>> call(
            Request request, Management.CallOptions options, Function<Request, WireRequest> encode,
            Function<WireRequest, Request> snapshot, MethodDescriptor<WireRequest, WireResponse> method,
            WireResponse prototype, Function<WireResponse, Response> decode) {
        long started = System.nanoTime();
        Management.RequestIdentity identity;
        try { identity = recovery(request); }
        catch (RuntimeException failure) { identity = new Management.RequestIdentity(Optional.empty(), Optional.empty()); }
        synchronized (this) {
            if (closing) return CompletableFuture.failedFuture(new Management.ClientCancellationException(local(Management.FailureCategory.LOCAL_CANCELLED, identity)));
            if (active.size() >= config.maximumCalls) return CompletableFuture.failedFuture(new Management.ClientException(local(Management.FailureCategory.LIMIT, identity)));
            try {
                long millis = options.timeoutMillis().orElse((long) config.timeoutMillis);
                Protocol.require(millis >= 0 && millis <= Long.MAX_VALUE / 1000000);
                millis = Math.min(millis, config.timeoutMillis);
                if (request instanceof Management.InvokeRequest invocation && invocation.deadlineUnixMillis().isPresent()) {
                    long absolute = invocation.deadlineUnixMillis().get();
                    Protocol.require(absolute >= 0);
                    millis = Math.min(millis, Math.max(0, absolute - System.currentTimeMillis()));
                }
                long remaining = TimeUnit.MILLISECONDS.toNanos(millis) - (System.nanoTime() - started);
                if (remaining <= 0) return CompletableFuture.failedFuture(new Management.ClientException(local(Management.FailureCategory.DEADLINE, identity)));
                Deadline deadline = Deadline.after(remaining, TimeUnit.NANOSECONDS);
                int requestLimit = request instanceof Management.ListCapabilitiesRequest ? Math.min(8192, config.requestBytes)
                        : method.getFullMethodName().contains("PolicyService/") ? Math.min(131072, config.requestBytes) : config.requestBytes;
                Protocol.sourceSize(request, requestLimit + 4096L, 0);
                Protocol.request(request, config.tenant);
                WireRequest wire = encode.apply(request);
                if (wire.getSerializedSize() > requestLimit) return CompletableFuture.failedFuture(new Management.ClientException(local(Management.FailureCategory.LIMIT, identity)));
                Request captured = snapshot.apply(wire);
                int responseLimit = request instanceof Management.ListCapabilitiesRequest ? Math.min(131072, config.responseBytes)
                        : method.getFullMethodName().contains("PolicyService/") ? Math.min(1048576, config.responseBytes) : config.responseBytes;
                var checked = method.toBuilder().setResponseMarshaller(Protocol.marshaller(prototype, responseLimit)).build();
                CallState<WireRequest, WireResponse, Response> state = new CallState<>(identity, captured, decode, deadline);
                var settings = io.grpc.CallOptions.DEFAULT.withDeadline(deadline).withMaxInboundMessageSize(responseLimit)
                        .withMaxOutboundMessageSize(requestLimit).withStreamTracerFactory(new ClientStreamTracer.Factory() {
                            @Override public ClientStreamTracer newClientStreamTracer(ClientStreamTracer.StreamInfo info, Metadata headers) {
                                return new ClientStreamTracer() { @Override public void outboundHeaders() { state.dispatched = true; } };
                            }
                        });
                state.transport = channel.newCall(checked, settings);
                active.add(state);
                Metadata headers = new Metadata();
                headers.put(AUTHORIZATION, config.authorization);
                try {
                    state.transport.start(state, headers);
                    state.transport.request(2);
                    state.transport.sendMessage(wire);
                    state.transport.halfClose();
                } catch (RuntimeException failure) {
                    state.transport.cancel("local dispatch failure", null);
                    state.onClose(Status.INTERNAL, new Metadata());
                }
                return state.future;
            } catch (RuntimeException failure) {
                return CompletableFuture.failedFuture(new Management.ClientException(local(Management.FailureCategory.INVALID_REQUEST, identity)));
            }
        }
    }

    private final class CallState<Request extends Message, WireResponse extends Message, Response> extends ClientCall.Listener<WireResponse> {
        private final Object request;
        private final Function<WireResponse, Response> decode;
        private final Deadline deadline;
        private final Metadata metadata = new Metadata();
        private final CompletableFuture<Management.ClientResponse<Response>> future;
        private ClientCall<Request, WireResponse> transport;
        private Management.RequestIdentity identity;
        private Response response;
        private Protocol.Invalid invalid;
        private boolean observed;
        private boolean closed;
        private boolean receivedHeaders;
        private volatile boolean dispatched;
        private volatile String cancellation;

        CallState(Management.RequestIdentity identity, Object request, Function<WireResponse, Response> decode, Deadline deadline) {
            this.identity = identity; this.request = request; this.decode = decode; this.deadline = deadline;
            future = new CompletableFuture<>() {
                @Override public boolean cancel(boolean mayInterruptIfRunning) {
                    if (isDone()) return false;
                    CallState.this.cancel("local cancellation");
                    boolean changed = completeExceptionally(new Management.ClientCancellationException(failure(Management.FailureCategory.LOCAL_CANCELLED, Optional.empty(), Optional.empty())));
                    return changed || isCancelled();
                }
            };
        }

        void cancel(String reason) { cancellation = reason; transport.cancel(reason, null); }

        @Override public synchronized void onHeaders(Metadata headers) {
            metadata.merge(headers); receivedHeaders = true; dispatched = true;
        }

        @Override public synchronized void onMessage(WireResponse value) {
            try {
                Protocol.require(response == null);
                response = decode.apply(value);
                if (identity.activationId().isEmpty()) identity = new Management.RequestIdentity(Protocol.activation(response), identity.operationId());
                observed = Protocol.response(response, request, config.tenant, identity);
            } catch (Protocol.Invalid failure) {
                invalid = failure;
                transport.cancel("invalid response", null);
            } catch (RuntimeException failure) {
                invalid = new Protocol.Invalid();
                transport.cancel("invalid response", null);
            }
        }

        private synchronized Protocol.Audit audit() { return Protocol.audit(metadata); }

        private synchronized Management.ClientFailure failure(Management.FailureCategory category, Optional<Integer> code,
                Optional<Management.PlatformError> platform) {
            Protocol.Audit audit = new Protocol.Audit(Optional.empty(), Optional.empty(), Optional.empty());
            try { audit = audit(); }
            catch (Protocol.Invalid failure) { if (invalid == null) invalid = failure; category = Management.FailureCategory.DECODE; }
            Optional<Management.UnsupportedWireValue> unsupported = invalid == null ? Optional.empty() : invalid.unsupported;
            Optional<String> rawStatus = audit.status().or(() -> unsupported.filter(value -> value.field().equals("audit.status")).map(Management.UnsupportedWireValue::value));
            return new Management.ClientFailure(category, "bounded client failure", code, platform, dispatched,
                    !dispatched ? Management.OutcomeKnowledge.NOT_DISPATCHED : observed ? Management.OutcomeKnowledge.OBSERVED : Management.OutcomeKnowledge.UNKNOWN,
                    identity, audit.ack(), rawStatus, unsupported, audit.attempt());
        }

        @Override public void onClose(Status status, Metadata trailers) {
            Management.ClientResponse<Response> result = null;
            Management.ClientFailure error = null;
            synchronized (this) {
                if (closed) return;
                closed = true;
                metadata.merge(trailers);
                Throwable source = status.getCause();
                for (int depth = 0; source != null && depth < 8; depth++, source = source.getCause()) {
                    if (source instanceof Protocol.Invalid failure) invalid = failure;
                }
                try {
                    Protocol.Audit audit = audit();
                    if (status.isOk() && response != null && invalid == null) {
                        if (deadline.isExpired()) error = failure(Management.FailureCategory.DEADLINE, Optional.empty(), Optional.empty());
                        else result = new Management.ClientResponse<>(response, new Management.ResponseMetadata(identity,
                                observed ? Management.OutcomeKnowledge.OBSERVED : Management.OutcomeKnowledge.UNKNOWN,
                                audit.ack(), audit.status(), audit.attempt()));
                    } else {
                        int code = status.getCode().value();
                        var platform = Protocol.details(metadata, code);
                        if (response == null && invalid == null && Set.of(3, 5, 6, 7, 9, 10, 12, 16).contains(code)) observed = true;
                        if (request instanceof Management.GetPolicyOperationRequest && code == 5) observed = false;
                        if (audit.status().filter(value -> value.equals("outcome-unknown") || value.equals("audit-unavailable")).isPresent() && response == null) observed = false;
                        Management.FailureCategory category = invalid != null || status.isOk() ? Management.FailureCategory.DECODE
                                : cancellation != null ? Management.FailureCategory.LOCAL_CANCELLED
                                : status.getCode() == Status.Code.DEADLINE_EXCEEDED ? Management.FailureCategory.DEADLINE
                                : receivedHeaders || !trailers.keys().isEmpty() ? Management.FailureCategory.RPC : Management.FailureCategory.TRANSPORT;
                        error = failure(category, Optional.of(code), platform);
                    }
                } catch (Protocol.Invalid failure) {
                    invalid = failure;
                    error = failure(Management.FailureCategory.DECODE, Optional.of(status.getCode().value()), Optional.empty());
                }
            }
            var finalResult = result;
            var finalError = error;
            completions.execute(() -> {
                try {
                    if (finalError != null) {
                        if (finalError.category().equals(Management.FailureCategory.LOCAL_CANCELLED)) future.completeExceptionally(new Management.ClientCancellationException(finalError));
                        else future.completeExceptionally(new Management.ClientException(finalError));
                    } else future.complete(finalResult);
                } finally {
                    synchronized (RpcClient.this) {
                        active.remove(this);
                        if (closing && active.isEmpty()) completions.shutdown();
                    }
                }
            });
        }
    }

    @Override public CompletableFuture<Management.ClientResponse<Management.InvokeResponse>> invoke(Management.InvokeRequest request, Management.CallOptions options) {
        return call(request, options, Wire::toWire, Wire::fromWire, InvocationServiceGrpc.getInvokeMethod(), Invocation.InvokeResponse.getDefaultInstance(), Wire::fromWire);
    }
    @Override public CompletableFuture<Management.ClientResponse<Management.CancelResponse>> cancel(Management.CancelRequest request, Management.CallOptions options) {
        return call(request, options, Wire::toWire, Wire::fromWire, InvocationServiceGrpc.getCancelMethod(), Invocation.CancelResponse.getDefaultInstance(), Wire::fromWire);
    }
    @Override public CompletableFuture<Management.ClientResponse<Management.ActivationStatus>> getActivation(Management.GetActivationRequest request, Management.CallOptions options) {
        return call(request, options, Wire::toWire, Wire::fromWire, InvocationServiceGrpc.getGetActivationMethod(), Invocation.ActivationStatus.getDefaultInstance(), Wire::fromWire);
    }
    @Override public CompletableFuture<Management.ClientResponse<Management.GetPolicyResponse>> getPolicy(Management.GetPolicyRequest request, Management.CallOptions options) {
        return call(request, options, Wire::toWire, Wire::fromWire, PolicyServiceGrpc.getGetPolicyMethod(), PolicyOuterClass.GetPolicyResponse.getDefaultInstance(), Wire::fromWire);
    }
    @Override public CompletableFuture<Management.ClientResponse<Management.ListPoliciesResponse>> listPolicies(Management.ListPoliciesRequest request, Management.CallOptions options) {
        return call(request, options, Wire::toWire, Wire::fromWire, PolicyServiceGrpc.getListPoliciesMethod(), PolicyOuterClass.ListPoliciesResponse.getDefaultInstance(), Wire::fromWire);
    }
    @Override public CompletableFuture<Management.ClientResponse<Management.ListCapabilitiesResponse>> listCapabilities(Management.ListCapabilitiesRequest request, Management.CallOptions options) {
        return call(request, options, Wire::toWire, Wire::fromWire, CapabilityServiceGrpc.getListCapabilitiesMethod(), Capability.ListCapabilitiesResponse.getDefaultInstance(), Wire::fromWire);
    }
    @Override public CompletableFuture<Management.ClientResponse<Management.ApplyPolicyResponse>> applyPolicy(Management.ApplyPolicyRequest request, Management.CallOptions options) {
        return call(request, options, Wire::toWire, Wire::fromWire, PolicyServiceGrpc.getApplyPolicyMethod(), PolicyOuterClass.ApplyPolicyResponse.getDefaultInstance(), Wire::fromWire);
    }
    @Override public CompletableFuture<Management.ClientResponse<Management.GetPolicyOperationResponse>> getPolicyOperation(Management.GetPolicyOperationRequest request, Management.CallOptions options) {
        return call(request, options, Wire::toWire, Wire::fromWire, PolicyServiceGrpc.getGetPolicyOperationMethod(), PolicyOuterClass.GetPolicyOperationResponse.getDefaultInstance(), Wire::fromWire);
    }
    @Override public CompletionStage<Models.InvocationOutcome> invoke(Models.InvokeRequest request) { return Legacy.invoke(this, request); }
    @Override public CompletionStage<Models.CancelResponse> cancel(String activationId, String reason) { return Legacy.cancel(this, activationId, reason); }
    @Override public CompletionStage<Models.ActivationStatus> getActivation(String activationId) { return Legacy.getActivation(this, activationId); }
}
