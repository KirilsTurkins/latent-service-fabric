package dev.latent.sdk.transport;

import com.google.protobuf.ByteString;
import io.grpc.Metadata;
import io.grpc.Server;
import io.grpc.ServerCall;
import io.grpc.ServerCallHandler;
import io.grpc.ServerInterceptor;
import io.grpc.ServerInterceptors;
import io.grpc.Status;
import io.grpc.netty.shaded.io.grpc.netty.NettyServerBuilder;
import io.grpc.netty.shaded.io.netty.channel.nio.NioEventLoopGroup;
import io.grpc.netty.shaded.io.netty.channel.socket.nio.NioServerSocketChannel;
import io.grpc.stub.ServerCallStreamObserver;
import io.grpc.stub.StreamObserver;
import java.net.InetSocketAddress;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import latent.invocation.v1.Invocation;
import latent.invocation.v1.InvocationServiceGrpc;
import latent.control.v1.Common;
import latent.control.v1.PolicyOuterClass;
import latent.control.v1.PolicyServiceGrpc;
import latent.control.v1.Capability;
import latent.control.v1.CapabilityServiceGrpc;

@SuppressWarnings("deprecation")
final class TestPeer implements AutoCloseable {
    static final String DIGEST = "sha256:" + "a".repeat(64);
    static final String PUBLICATION = "publication:sha256:" + "b".repeat(64);
    final AtomicInteger invocations = new AtomicInteger();
    final AtomicInteger cancellations = new AtomicInteger();
    final Set<Object> connections = ConcurrentHashMap.newKeySet();
    final Map<String, Invocation.InvokeRequest> requests = new ConcurrentHashMap<>();
    final Map<String, Long> remainingDeadlines = new ConcurrentHashMap<>();
    final Map<String, StreamObserver<Invocation.InvokeResponse>> pending = new ConcurrentHashMap<>();
    final Map<String, Invocation.ActivationStatus> statuses = new ConcurrentHashMap<>();
    final Map<String, PolicyOuterClass.ApplyPolicyRequest> mutations = new ConcurrentHashMap<>();
    final Map<String, PolicyOuterClass.ApplyPolicyResponse> receipts = new ConcurrentHashMap<>();
    final AtomicInteger transportCancelled = new AtomicInteger();
    final NioEventLoopGroup accept = new NioEventLoopGroup(1);
    final NioEventLoopGroup work = new NioEventLoopGroup(1);
    final Server server;
    volatile Invocation.InvokeRequest captured;

    TestPeer() throws Exception {
        ServerInterceptor auth = new ServerInterceptor() {
            @Override public <Request, Response> ServerCall.Listener<Request> interceptCall(ServerCall<Request, Response> call,
                    Metadata headers, ServerCallHandler<Request, Response> next) {
                connections.add(call.getAttributes().get(io.grpc.Grpc.TRANSPORT_ATTR_REMOTE_ADDR));
                String token = headers.get(Metadata.Key.of("authorization", Metadata.ASCII_STRING_MARSHALLER));
                if (!"Bearer test-only-java-token".equals(token)) {
                    call.close(Status.UNAUTHENTICATED.withDescription("not echoed by client"), new Metadata());
                    return new ServerCall.Listener<>() { };
                }
                return next.startCall(call, headers);
            }
        };
        server = NettyServerBuilder.forAddress(new InetSocketAddress("127.0.0.1", 0))
                .bossEventLoopGroup(accept).workerEventLoopGroup(work).channelType(NioServerSocketChannel.class)
                .directExecutor().maxInboundMessageSize(1048576)
                .addService(ServerInterceptors.intercept(new Invocations(), auth))
                .addService(ServerInterceptors.intercept(new Policies(), auth))
                .addService(ServerInterceptors.intercept(new Capabilities(), auth)).build().start();
    }

    String endpoint() { return "http://127.0.0.1:" + server.getPort(); }
    RpcClient client() { return new RpcClient(ClientConfig.loopback(endpoint(), "tenant-a", "test-only-java-token")); }

    static <Value> void reply(StreamObserver<Value> observer, Value value) { observer.onNext(value); observer.onCompleted(); }
    static Invocation.InvokeResponse success(String identity, ByteString payload) {
        return Invocation.InvokeResponse.newBuilder().setActivationId(identity).setRevisionId("revision-a").setReleaseDigest(DIGEST)
                .setPublicationId(PUBLICATION).setRouteGeneration(-1).setConsumption(Invocation.BudgetConsumption.newBuilder().setCpuFuel(-1))
                .setSuccess(Invocation.Success.newBuilder().setPayload(payload).setMediaType("application/octet-stream")).build();
    }

    final class Invocations extends InvocationServiceGrpc.InvocationServiceImplBase {
        @Override public void invoke(Invocation.InvokeRequest request, StreamObserver<Invocation.InvokeResponse> observer) {
            invocations.incrementAndGet(); captured = request;
            String identity = request.hasActivationId() ? request.getActivationId() : "server-assigned";
            requests.put(identity, request);
            remainingDeadlines.put(identity, io.grpc.Context.current().getDeadline().timeRemaining(TimeUnit.NANOSECONDS));
            if (!request.getTarget().getTenant().equals("tenant-a")) {
                observer.onError(Status.PERMISSION_DENIED.asRuntimeException()); return;
            }
            var stream = (ServerCallStreamObserver<Invocation.InvokeResponse>) observer;
            stream.setOnCancelHandler(transportCancelled::incrementAndGet);
            String function = request.getTarget().getFunction();
            if (function.equals("hold")) {
                pending.put(identity, observer);
                statuses.put(identity, Invocation.ActivationStatus.newBuilder().setActivationId(identity).setPhase("running").build());
                return;
            }
            var result = success(identity, request.getPayload());
            if (function.equals("declared")) result = result.toBuilder().setDeclaredError(Invocation.DeclaredError.newBuilder()
                    .setCode("expected").setPayload(ByteString.copyFrom(new byte[] {0, -1}))).build();
            if (function.equals("platform")) result = result.toBuilder().setPlatformFailure(Invocation.PlatformError.newBuilder()
                    .setCode("guest-trap").setMessage("guest-failed")).build();
            if (function.equals("future")) result = result.toBuilder().setPlatformFailure(Invocation.PlatformError.newBuilder().setCode("future-code-v2")).build();
            if (function.equals("oversized")) result = success(identity, ByteString.copyFrom(new byte[4096]));
            statuses.put(identity, Invocation.ActivationStatus.newBuilder().setActivationId(identity).setPhase("running")
                    .setTerminalState("completed").setSucceeded(Invocation.ActivationSuccessSummary.getDefaultInstance())
                    .setFinalConsumption(Invocation.BudgetConsumption.getDefaultInstance()).setTerminalAtUnixMillis(-1).build());
            reply(observer, result);
        }

        @Override public void cancel(Invocation.CancelRequest request, StreamObserver<Invocation.CancelResponse> observer) {
            cancellations.incrementAndGet();
            String identity = request.getActivationId();
            if (identity.equals("future")) {
                reply(observer, Invocation.CancelResponse.newBuilder().setDispositionValue(-19).build()); return;
            }
            var waiting = pending.remove(identity);
            if (waiting != null) {
                var failure = Invocation.PlatformError.newBuilder().setCode("cancelled").build();
                statuses.put(identity, Invocation.ActivationStatus.newBuilder().setActivationId(identity).setPhase("running")
                        .setTerminalState("cancelled").setPlatformFailure(failure).setFinalConsumption(Invocation.BudgetConsumption.getDefaultInstance())
                        .setTerminalAtUnixMillis(1).build());
                if (!((ServerCallStreamObserver<Invocation.InvokeResponse>) waiting).isCancelled()) {
                    reply(waiting, success(identity, ByteString.EMPTY).toBuilder().setPlatformFailure(failure).build());
                }
            }
            var result = Invocation.CancelResponse.newBuilder().setDispositionValue(waiting != null ? 1 : statuses.containsKey(identity) ? 2 : 3);
            if (result.getDispositionValue() == 2) result.setTerminalState(statuses.get(identity).getTerminalState());
            reply(observer, result.build());
        }

        @Override public void getActivation(Invocation.GetActivationRequest request, StreamObserver<Invocation.ActivationStatus> observer) {
            var value = statuses.get(request.getActivationId());
            if (value == null) observer.onError(Status.NOT_FOUND.asRuntimeException()); else reply(observer, value);
        }
    }

    final class Policies extends PolicyServiceGrpc.PolicyServiceImplBase {
        @Override public void applyPolicy(PolicyOuterClass.ApplyPolicyRequest request, StreamObserver<PolicyOuterClass.ApplyPolicyResponse> observer) {
            var original = mutations.putIfAbsent(request.getOperationId(), request);
            if ((original != null && !original.equals(request)) || request.getExpectedGeneration() != 0) {
                observer.onError(Status.ABORTED.asRuntimeException()); return;
            }
            var document = request.getPolicy().toBuilder().setGeneration(-1).setContentDigest(DIGEST).build();
            var receipt = PolicyOuterClass.CapabilityPolicyOperation.newBuilder().setOperationId(request.getOperationId()).setId(document.getId())
                    .setTenant("tenant-a").setGeneration(-1).setRecordKindValue(document.getRecordKindValue()).setContentDigest(DIGEST).build();
            var response = PolicyOuterClass.ApplyPolicyResponse.newBuilder().setPolicy(document).setReceipt(receipt).build();
            receipts.put(request.getOperationId(), response);
            if (request.getOperationId().equals("lost")) observer.onError(Status.UNAVAILABLE.asRuntimeException()); else reply(observer, response);
        }
        @Override public void getPolicy(PolicyOuterClass.GetPolicyRequest request, StreamObserver<PolicyOuterClass.GetPolicyResponse> observer) {
            reply(observer, PolicyOuterClass.GetPolicyResponse.getDefaultInstance());
        }
        @Override public void getPolicyOperation(PolicyOuterClass.GetPolicyOperationRequest request, StreamObserver<PolicyOuterClass.GetPolicyOperationResponse> observer) {
            if (request.getOperationId().equals("retained-missing")) {
                observer.onError(Status.NOT_FOUND.asRuntimeException()); return;
            }
            var value = PolicyOuterClass.GetPolicyOperationResponse.newBuilder();
            var receipt = receipts.get(request.getOperationId());
            if (receipt != null) value.setReceipt(receipt.getReceipt());
            reply(observer, value.build());
        }
        @Override public void listPolicies(PolicyOuterClass.ListPoliciesRequest request, StreamObserver<PolicyOuterClass.ListPoliciesResponse> observer) {
            reply(observer, PolicyOuterClass.ListPoliciesResponse.newBuilder().setCatalogGeneration(-1).setPage(Common.PageResponse.getDefaultInstance()).build());
        }
    }

    final class Capabilities extends CapabilityServiceGrpc.CapabilityServiceImplBase {
        @Override public void listCapabilities(Capability.ListCapabilitiesRequest request, StreamObserver<Capability.ListCapabilitiesResponse> observer) {
            reply(observer, Capability.ListCapabilitiesResponse.newBuilder().setPage(Common.PageResponse.getDefaultInstance())
                    .setTenantUsage(Capability.CapabilityResourceUsage.newBuilder().setScope("tenant").putCounters("active_activations", -1L))
                    .setRevision(Capability.CapabilityInspectionRevision.newBuilder().setDeploymentId(request.getDeploymentId()).setPublicationId(PUBLICATION)
                            .setRouteGeneration(-1).setCatalogTransaction(-1)).addCapabilities(Capability.CapabilityDescriptor.newBuilder().setId("provider")
                            .setInspection(Capability.CapabilityBindingInspection.newBuilder().setProviderConfigurationEpoch(-1))).build());
        }
    }

    @Override public void close() throws Exception {
        server.shutdownNow();
        if (!server.awaitTermination(3, TimeUnit.SECONDS)) throw new AssertionError("peer server not reaped");
        accept.shutdownGracefully(0, 1, TimeUnit.SECONDS).sync();
        work.shutdownGracefully(0, 1, TimeUnit.SECONDS).sync();
    }
}
