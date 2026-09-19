package dev.latent.sdk.transport;

import dev.latent.sdk.Management;
import com.google.protobuf.ByteString;
import io.grpc.Metadata;
import io.grpc.Status;
import java.nio.ByteBuffer;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.function.BooleanSupplier;
import latent.invocation.v1.Invocation;
import latent.invocation.v1.InvocationServiceGrpc;
import latent.control.v1.Common;
import latent.control.v1.PolicyOuterClass;
import latent.control.v1.PolicyServiceGrpc;

public final class TransportTest {
    static final Management.CallOptions OPTIONS = new Management.CallOptions(Optional.of(2000L));
    private TransportTest() { }

    static void check(boolean value, String name) { if (!value) throw new AssertionError(name); }
    static void until(BooleanSupplier condition) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(3);
        while (!condition.getAsBoolean()) {
            if (System.nanoTime() >= deadline) throw new AssertionError("bounded wait expired");
            Thread.sleep(2);
        }
    }
    static <Value> Value get(CompletableFuture<Value> future) throws Exception { return future.get(4, TimeUnit.SECONDS); }
    static Management.ClientFailure failure(CompletableFuture<?> future) throws Exception {
        try { get(future); throw new AssertionError("expected typed failure"); }
        catch (java.util.concurrent.ExecutionException | java.util.concurrent.CancellationException error) {
            return Management.clientFailure(error).orElseThrow(() -> new AssertionError("lost typed failure", error));
        }
    }
    static Management.InvokeRequest invoke(String identity, String function) {
        return new Management.InvokeRequest(Optional.ofNullable(identity), Optional.empty(), Optional.empty(),
                Optional.of(new Management.InvocationTarget("tenant-a", "echo", "example:echo/api@1.0.0", function, Optional.empty())),
                ByteBuffer.wrap(new byte[] {0, -1}), "application/octet-stream", Optional.empty(), -1, Optional.of(""), Optional.empty(), Map.of());
    }
    static Management.ApplyPolicyRequest policy(String operation) {
        return new Management.ApplyPolicyRequest(Optional.of(new Management.Policy("policy-a",
                Optional.of(new Management.ObjectMetadata("policy-a", Optional.of("tenant-a"), Optional.empty(), Map.of(), Map.of())),
                "{}", 0, "latent-capability-policy-v1", Management.CapabilityPolicyRecordKind.POLICY, "", false)), Optional.of(0L), operation);
    }

    static void allOperationsAndSnapshots() throws Exception {
        try (var peer = new TestPeer(); var client = peer.client()) {
            check(client.snapshot().activeCalls() == 0 && peer.connections.isEmpty(), "lazy connection");
            byte[] bytes = {9, 0, -1, 8};
            ByteBuffer buffer = ByteBuffer.wrap(bytes); buffer.position(1); buffer.limit(3);
            Map<String, String> metadata = new LinkedHashMap<>(); metadata.put("trace", "original");
            var original = invoke(null, "echo");
            var request = new Management.InvokeRequest(original.activationId(), original.parentActivationId(), original.rootActivationId(), original.target(),
                    buffer, original.mediaType(), original.deadlineUnixMillis(), original.priority(), original.idempotencyKey(), original.budget(), metadata);
            var pending = client.invoke(request, OPTIONS);
            bytes[1] = 42; buffer.position(3); metadata.put("trace", "changed");
            Management.ClientResponse<Management.InvokeResponse> response;
            try { response = get(pending); }
            catch (java.util.concurrent.ExecutionException error) {
                throw new AssertionError("controlled peer response: " + Management.clientFailure(error), error);
            }
            check(response.value().routeGeneration() == -1 && response.value().consumption().orElseThrow().cpuFuel() == -1, "full u64 response");
            check(response.metadata().identity().activationId().equals(Optional.of("server-assigned")), "assigned recovery identity");
            check(response.value().success().orElseThrow().payload().equals(ByteBuffer.wrap(new byte[] {0, -1})), "snapshot bytes");
            check(response.value().success().orElseThrow().payload().isReadOnly(), "response buffer ownership");
            check(peer.captured.getMetadataOrThrow("trace").equals("original") && peer.captured.getPriority() == -1, "snapshot metadata and u32");
            check(peer.captured.hasIdempotencyKey() && peer.captured.getIdempotencyKey().isEmpty() && !peer.captured.hasBudget(), "wire presence");
            check(get(client.getActivation(new Management.GetActivationRequest("server-assigned"), OPTIONS)).value().terminalAtUnixMillis().orElseThrow() == -1, "u64 status timestamp remains data");
            check(get(client.cancel(new Management.CancelRequest("server-assigned", "done"), OPTIONS)).value().disposition().value() == 2, "already terminal");
            check(get(client.cancel(new Management.CancelRequest("absent", "none"), OPTIONS)).value().disposition().value() == 3, "not found");
            check(get(client.cancel(new Management.CancelRequest("future", "opaque"), OPTIONS)).value().disposition().value() == -19, "future numeric enum");
            check(get(client.getPolicy(new Management.GetPolicyRequest("policy-a", new Management.CapabilityPolicyRecordKind(91)), OPTIONS)).value().policy().isEmpty(), "missing policy");
            check(get(client.listPolicies(new Management.ListPoliciesRequest(Management.CapabilityPolicyRecordKind.POLICY,
                    Optional.of(new Management.PageRequest(32, Optional.empty()))), OPTIONS)).value().catalogGeneration() == -1, "policy page");
            var inspection = get(client.listCapabilities(new Management.ListCapabilitiesRequest(Optional.empty(), Optional.empty(), Optional.empty(), "deployment-a", false), OPTIONS));
            check(inspection.value().revision().orElseThrow().publicationId().equals(Optional.of(TestPeer.PUBLICATION)), "inspection publication");
            check(inspection.value().capabilities().getFirst().inspection().orElseThrow().providerConfigurationEpoch() == -1, "provider epoch");
            var applied = get(client.applyPolicy(policy("create"), OPTIONS));
            check(applied.value().receipt().orElseThrow().generation() == -1 && applied.metadata().auditAck().isEmpty(), "mutation no invented audit");
            check(get(client.getPolicyOperation(new Management.GetPolicyOperationRequest("create"), OPTIONS)).value().receipt().orElseThrow().operationId().equals("create"), "operation recovery");
            check(get(client.getPolicyOperation(new Management.GetPolicyOperationRequest("missing"), OPTIONS)).metadata().outcome().equals(Management.OutcomeKnowledge.UNKNOWN), "missing receipt remains unknown");
            check(peer.connections.size() == 1, "all eight reuse one physical channel");
        }
    }

    static void localLimitsAndDeadlines() throws Exception {
        try (var peer = new TestPeer(); var client = peer.client()) {
            check(failure(client.invoke(invoke("zero", "echo"), new Management.CallOptions(Optional.of(0L)))).category().equals(Management.FailureCategory.DEADLINE), "zero deadline");
            check(failure(client.invoke(invoke("max", "echo"), new Management.CallOptions(Optional.of(-1L)))).category().equals(Management.FailureCategory.INVALID_REQUEST), "u64 duration checked");
            check(failure(client.listPolicies(new Management.ListPoliciesRequest(Management.CapabilityPolicyRecordKind.POLICY,
                    Optional.of(new Management.PageRequest(0, Optional.empty()))), OPTIONS)).category().equals(Management.FailureCategory.INVALID_REQUEST), "policy zero invalid");
            var mutation = policy("missing-precondition");
            check(failure(client.applyPolicy(new Management.ApplyPolicyRequest(mutation.policy(), Optional.empty(), mutation.operationId()), OPTIONS)).identity().operationId()
                    .equals(Optional.of("missing-precondition")), "invalid mutation retains identity");
            check(peer.connections.isEmpty(), "local validation opens no socket");
            var timed = failure(client.invoke(invoke("timed", "hold"), new Management.CallOptions(Optional.of(200L))));
            check(timed.category().equals(Management.FailureCategory.DEADLINE) && timed.dispatched()
                    && timed.outcome().equals(Management.OutcomeKnowledge.UNKNOWN) && timed.identity().activationId().equals(Optional.of("timed")), "single deadline and uncertainty");
            check(peer.invocations.get() == 1, "no deadline retry");
        }
    }

    static void cancellationCapacityAndShutdown() throws Exception {
        try (var peer = new TestPeer()) {
            var client = new RpcClient(new ClientConfig(peer.endpoint(), "tenant-a", "test-only-java-token", 1, 1048576, 1048576, 2000, 1000, 3000));
            var pending = client.invoke(invoke("held", "hold"), OPTIONS);
            until(() -> peer.pending.containsKey("held"));
            check(failure(client.getActivation(new Management.GetActivationRequest("held"), OPTIONS)).category().equals(Management.FailureCategory.LIMIT), "no queued overload");
            pending.cancel(true);
            check(pending.isCancelled() && failure(pending).identity().activationId().equals(Optional.of("held")), "typed local cancellation");
            until(() -> client.snapshot().activeCalls() == 0 && peer.transportCancelled.get() > 0);
            check(peer.cancellations.get() == 0, "future cancellation does not send Cancel");
            check(get(client.getActivation(new Management.GetActivationRequest("held"), OPTIONS)).value().terminalState().isEmpty(), "local cancel not guest cleanup");
            until(() -> client.snapshot().activeCalls() == 0);
            check(get(client.cancel(new Management.CancelRequest("held", "explicit"), OPTIONS)).value().disposition().value() == 1, "explicit accepted");
            until(() -> client.snapshot().activeCalls() == 0);
            var closing = client.invoke(invoke("closing", "hold"), OPTIONS);
            until(() -> peer.pending.containsKey("closing"));
            check(client.shutdown(Duration.ofSeconds(3)).clean(), "physical channel/executor reaped");
            check(failure(closing).category().equals(Management.FailureCategory.LOCAL_CANCELLED), "outstanding close");
            check(failure(client.invoke(invoke("closed", "echo"), OPTIONS)).outcome().equals(Management.OutcomeKnowledge.NOT_DISPATCHED), "closed owner denies new work");
        }
    }

    static void outcomesAuthAndRecovery() throws Exception {
        try (var peer = new TestPeer(); var client = peer.client()) {
            check(get(client.invoke(invoke("declared", "declared"), OPTIONS)).value().declaredError().isPresent(), "declared not transport failure");
            check(get(client.invoke(invoke("platform", "platform"), OPTIONS)).value().platformFailure().orElseThrow().code().equals("guest-trap"), "platform not declared");
            var unsupported = failure(client.invoke(invoke(null, "future"), OPTIONS));
            check(unsupported.category().equals(Management.FailureCategory.DECODE) && unsupported.unsupportedWireValue().orElseThrow().value().equals("future-code-v2")
                    && unsupported.identity().activationId().equals(Optional.of("server-assigned")), "unknown text raw and identity");
            var lost = failure(client.applyPolicy(policy("lost"), OPTIONS));
            check(lost.outcome().equals(Management.OutcomeKnowledge.UNKNOWN) && lost.identity().operationId().equals(Optional.of("lost")), "lost mutation uncertain");
            check(get(client.getPolicyOperation(new Management.GetPolicyOperationRequest("lost"), OPTIONS)).value().receipt().isPresent(), "lost receipt recovery");
            var create = policy("replay");
            check(get(client.applyPolicy(create, OPTIONS)).value().equals(get(client.applyPolicy(create, OPTIONS)).value()), "exact explicit replay");
            check(failure(client.applyPolicy(new Management.ApplyPolicyRequest(create.policy(), Optional.of(1L), create.operationId()), OPTIONS)).grpcStatus().equals(Optional.of(10)), "incompatible replay conflict");
            try (var denied = new RpcClient(ClientConfig.loopback(peer.endpoint(), "tenant-a", "wrong-token"))) {
                var failure = failure(denied.invoke(invoke("denied", "echo"), OPTIONS));
                check(failure.grpcStatus().equals(Optional.of(16)) && !failure.message().contains("not echoed"), "authentication failure redacted");
            }
        }
    }

    static Metadata audit(String status, String attempt) {
        Metadata result = new Metadata();
        if (status != null) result.put(Protocol.AUDIT_STATUS, status);
        if (attempt != null) result.put(Protocol.AUDIT_ATTEMPT, attempt);
        return result;
    }

    static void rawAuditAndTypedDetails() throws Exception {
        byte[] success = TestPeer.success("audit", ByteString.EMPTY).toByteArray();
        for (String status : new String[] {"durable", "future-state", "future-durable-v2", "outcome-unknown"}) {
            try (var peer = new RawPeer(InvocationServiceGrpc.getInvokeMethod(), request -> new RawPeer.Reply(success, Status.OK,
                    audit(status, "18446744073709551615"), new Metadata())); var client = peer.client()) {
                var metadata = get(client.invoke(invoke("audit", "echo"), OPTIONS)).metadata();
                check(metadata.auditStatus().equals(Optional.of(status)) && metadata.auditAttemptSequence().equals(Optional.of(-1L)), "independent maximum raw audit sequence");
                check(metadata.auditAck().isPresent() == !status.startsWith("future"), "no fabricated unknown acknowledgement");
                check(metadata.outcome().equals(Management.OutcomeKnowledge.OBSERVED), "receipt independent of audit");
            }
        }
        try (var peer = new RawPeer(InvocationServiceGrpc.getInvokeMethod(), request -> new RawPeer.Reply(null, Status.UNAVAILABLE,
                new Metadata(), audit("future-state", "18446744073709551615"))); var client = peer.client()) {
            var failure = failure(client.invoke(invoke("audit", "echo"), OPTIONS));
            check(failure.auditAttemptSequence().equals(Optional.of(-1L)) && failure.auditAck().isEmpty()
                    && failure.auditStatus().equals(Optional.of("future-state")), "failure raw audit facts");
        }
        Metadata duplicate = audit("durable", "1"); duplicate.put(Protocol.AUDIT_STATUS, "disabled");
        try (var peer = new RawPeer(InvocationServiceGrpc.getInvokeMethod(), request -> new RawPeer.Reply(success, Status.OK, duplicate, new Metadata())); var client = peer.client()) {
            var failure = failure(client.invoke(invoke("audit", "echo"), OPTIONS));
            check(failure.category().equals(Management.FailureCategory.DECODE) && failure.outcome().equals(Management.OutcomeKnowledge.OBSERVED), "duplicate audit does not erase observed receipt");
        }
        Metadata typed = new Metadata();
        typed.put(Protocol.DETAILS, Common.PlatformError.newBuilder().setCode("permission-denied").setMessage("redacted").build().toByteArray());
        try (var peer = new RawPeer(PolicyServiceGrpc.getGetPolicyMethod(), request -> new RawPeer.Reply(null, Status.PERMISSION_DENIED, new Metadata(), typed)); var client = peer.client()) {
            check(failure(client.getPolicy(new Management.GetPolicyRequest("policy-a", Management.CapabilityPolicyRecordKind.POLICY), OPTIONS))
                    .platformError().orElseThrow().code().equals("permission-denied"), "typed platform status details");
        }
    }

    static void malformedAndOversizedWire() throws Exception {
        byte[] correct = TestPeer.success("wire", ByteString.EMPTY).toByteArray();
        byte[] contradictory = java.util.Arrays.copyOf(correct, correct.length + 2);
        contradictory[correct.length] = 66; contradictory[correct.length + 1] = 0;
        byte[][] replies = {new byte[] {10, 127, 1}, new byte[] {10, 1, -1}, new byte[0], contradictory};
        for (byte[] reply : replies) {
            try (var peer = new RawPeer(InvocationServiceGrpc.getInvokeMethod(), request -> new RawPeer.Reply(reply, Status.OK, new Metadata(), new Metadata())); var client = peer.client()) {
                var failure = failure(client.invoke(invoke("wire", "echo"), OPTIONS));
                check(failure.category().equals(Management.FailureCategory.DECODE) && failure.identity().activationId().equals(Optional.of("wire")), "malformed wire rejected with identity: " + failure);
            }
        }
        try (var peer = new TestPeer(); var client = new RpcClient(new ClientConfig(peer.endpoint(), "tenant-a", "test-only-java-token", 4, 1048576, 256, 2000, 1000, 3000))) {
            var failure = failure(client.invoke(invoke("oversized", "oversized"), OPTIONS));
            check(failure.grpcStatus().equals(Optional.of(8)) && failure.outcome().equals(Management.OutcomeKnowledge.UNKNOWN), "inbound size bounded");
        }
    }

    public static void main(String[] args) throws Exception {
        FixtureCodecTest.run();
        allOperationsAndSnapshots();
        localLimitsAndDeadlines();
        cancellationCapacityAndShutdown();
        outcomesAuthAndRecovery();
        rawAuditAndTypedDetails();
        malformedAndOversizedWire();
        System.out.println("Java transport: six bounded TCP/protocol suites passed");
    }
}
