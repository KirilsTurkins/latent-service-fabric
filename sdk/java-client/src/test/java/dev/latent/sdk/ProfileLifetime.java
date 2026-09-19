package dev.latent.sdk;

import java.nio.ByteBuffer;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;

final class ProfileLifetime {
    private ProfileLifetime() { }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static Management.ResponseMetadata metadata(String operationId, Management.OutcomeKnowledge outcome) {
        return new Management.ResponseMetadata(new Management.RequestIdentity(Optional.empty(), Optional.ofNullable(operationId)), outcome, Optional.empty(), Optional.empty());
    }

    private static <Response> CompletableFuture<Management.ClientResponse<Response>> ready(Response value) {
        return CompletableFuture.completedFuture(new Management.ClientResponse<>(value, metadata(null, Management.OutcomeKnowledge.OBSERVED)));
    }

    private static Management.ClientFailure failure(String operationId, boolean dispatched, Management.FailureCategory category) {
        return new Management.ClientFailure(category, "local-fixture-failure", Optional.empty(), Optional.empty(), dispatched,
                dispatched ? Management.OutcomeKnowledge.UNKNOWN : Management.OutcomeKnowledge.NOT_DISPATCHED,
                new Management.RequestIdentity(Optional.empty(), Optional.of(operationId)), Optional.empty(), Optional.empty(), Optional.empty());
    }

    private static final class FixtureClient implements Management.ClientProfile {
        private int writes;
        private int waiters;
        private int cancels;
        private int pages;
        private Management.CapabilityPolicyOperation receipt;
        private Management.Policy policy;

        @Override
        public CompletableFuture<Management.ClientResponse<Management.InvokeResponse>> invoke(Management.InvokeRequest request, Management.CallOptions options) {
            byte[] owned = new byte[request.payload().remaining()];
            request.payload().duplicate().get(owned);
            var success = new Management.Success(ByteBuffer.wrap(owned), request.mediaType(), Optional.empty(), List.of(), Map.of());
            return ready(new Management.InvokeResponse(request.activationId().orElseThrow(), "revision-a", "component-a", 1,
                    Optional.of(success), Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty()));
        }

        @Override
        public CompletableFuture<Management.ClientResponse<Management.CancelResponse>> cancel(Management.CancelRequest request, Management.CallOptions options) {
            cancels++;
            return ready(new Management.CancelResponse(Management.CancelDisposition.ACCEPTED, Optional.empty()));
        }

        @Override
        public CompletableFuture<Management.ClientResponse<Management.ActivationStatus>> getActivation(Management.GetActivationRequest request, Management.CallOptions options) {
            return ready(new Management.ActivationStatus(request.activationId(), "running", Optional.empty(), 0, Map.of(),
                    Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty()));
        }

        @Override
        public CompletableFuture<Management.ClientResponse<Management.GetPolicyResponse>> getPolicy(Management.GetPolicyRequest request, Management.CallOptions options) {
            return ready(new Management.GetPolicyResponse(Optional.ofNullable(policy)));
        }

        @Override
        public CompletableFuture<Management.ClientResponse<Management.ListPoliciesResponse>> listPolicies(Management.ListPoliciesRequest request, Management.CallOptions options) {
            pages++;
            return ready(new Management.ListPoliciesResponse(List.of(), 1, Optional.of(new Management.PageResponse(Optional.of("opaque-next-page")))));
        }

        @Override
        public CompletableFuture<Management.ClientResponse<Management.ListCapabilitiesResponse>> listCapabilities(Management.ListCapabilitiesRequest request, Management.CallOptions options) {
            var revision = new Management.CapabilityInspectionRevision(request.deploymentId(), "revision-a", "component-a", Optional.empty(), 1, 1);
            return ready(new Management.ListCapabilitiesResponse(List.of(), Optional.empty(), Optional.of(revision), Optional.empty(), Optional.empty(), "binding-plan-unavailable"));
        }

        @Override
        public CompletableFuture<Management.ClientResponse<Management.ApplyPolicyResponse>> applyPolicy(Management.ApplyPolicyRequest request, Management.CallOptions options) {
            if (options.timeoutMillis().isPresent() && options.timeoutMillis().get() == 0) {
                return CompletableFuture.failedFuture(new Management.ClientException(failure(request.operationId(), false, Management.FailureCategory.DEADLINE)));
            }
            check(request.expectedGeneration().isPresent() && !request.operationId().isEmpty(), "explicit mutation identity and precondition");
            if (receipt != null) return ready(new Management.ApplyPolicyResponse(Optional.empty(), Optional.of(receipt)));
            policy = request.policy().orElseThrow();
            receipt = new Management.CapabilityPolicyOperation(request.operationId(), "tenant-a", policy.id(), policy.recordKind(), -1L, "digest-a", false);
            writes++;
            waiters++;
            return new CompletableFuture<>() {
                @Override
                public boolean cancel(boolean mayInterruptIfRunning) {
                    boolean changed = completeExceptionally(new Management.ClientCancellationException(failure(request.operationId(), true, Management.FailureCategory.LOCAL_CANCELLED)));
                    if (changed) waiters--;
                    return changed;
                }
            };
        }

        @Override
        public CompletableFuture<Management.ClientResponse<Management.GetPolicyOperationResponse>> getPolicyOperation(Management.GetPolicyOperationRequest request, Management.CallOptions options) {
            var found = Optional.ofNullable(receipt).filter(value -> value.operationId().equals(request.operationId()));
            return CompletableFuture.completedFuture(new Management.ClientResponse<>(new Management.GetPolicyOperationResponse(found),
                    metadata(request.operationId(), found.isPresent() ? Management.OutcomeKnowledge.OBSERVED : Management.OutcomeKnowledge.UNKNOWN)));
        }
    }

    static void run() throws Exception {
        var client = new FixtureClient();
        Management.ClientProfile profile = client;
        var options = new Management.CallOptions(Optional.empty());
        var policy = new Management.Policy("policy-a", Optional.empty(), "{}", 0, "lsf-capability-policy-v1", Management.CapabilityPolicyRecordKind.POLICY, "", false);
        var request = new Management.ApplyPolicyRequest(Optional.of(policy), Optional.of(0L), "operation-a");
        var pending = profile.applyPolicy(request, options);
        check(client.writes == 1 && client.waiters == 1, "server receipt precedes local completion");
        check(pending.cancel(false) && pending.isCancelled(), "local future cancellation");
        try {
            pending.join();
            throw new AssertionError("cancelled wait must fail");
        } catch (java.util.concurrent.CancellationException cancelled) {
            var retained = Management.clientFailure(cancelled).orElseThrow();
            check(retained.dispatched() && retained.outcome().equals(Management.OutcomeKnowledge.UNKNOWN), "local cancellation is not rollback");
            check(retained.identity().operationId().orElseThrow().equals("operation-a"), "original recovery identity");
        }
        check(client.waiters == 0 && client.writes == 1 && client.cancels == 0, "only local ownership ends");
        var recovered = profile.getPolicyOperation(new Management.GetPolicyOperationRequest("operation-a"), options).get(2, TimeUnit.SECONDS);
        check(recovered.value().receipt().orElseThrow().generation() == -1L && recovered.metadata().auditAck().isEmpty(), "u64 receipt and no invented audit");
        var unknown = profile.getPolicyOperation(new Management.GetPolicyOperationRequest("not-retained"), options).get(2, TimeUnit.SECONDS);
        check(unknown.value().receipt().isEmpty() && unknown.metadata().outcome().equals(Management.OutcomeKnowledge.UNKNOWN), "missing receipt is unknown");
        profile.applyPolicy(request, options).get(2, TimeUnit.SECONDS);
        check(client.writes == 1, "explicit replay does not mutate again");
        try {
            profile.applyPolicy(request, new Management.CallOptions(Optional.of(0L))).get(2, TimeUnit.SECONDS);
            throw new AssertionError("zero timeout must fail before dispatch");
        } catch (ExecutionException expired) {
            check(expired.getCause() instanceof Management.ClientException failure && !failure.failure().dispatched(), "typed zero-timeout failure");
        }
        byte[] payload = new byte[]{1, 2};
        var invocation = new Management.InvokeRequest(Optional.of("activation-a"), Optional.empty(), Optional.empty(), Optional.empty(), ByteBuffer.wrap(payload), "application/octet-stream", Optional.empty(), 0, Optional.empty(), Optional.empty(), Map.of());
        var invoked = profile.invoke(invocation, options).get(2, TimeUnit.SECONDS);
        payload[0] = 99;
        check(invoked.value().success().orElseThrow().payload().get(0) == 1, "response owns bytes");
        check(profile.cancel(new Management.CancelRequest("activation-a", "fixture"), options).get(2, TimeUnit.SECONDS).value().disposition().equals(Management.CancelDisposition.ACCEPTED), "explicit remote Cancel");
        check(profile.getActivation(new Management.GetActivationRequest("activation-a"), options).get(2, TimeUnit.SECONDS).value().phase().equals("running"), "accepted does not prove cleanup");
        check(profile.getPolicy(new Management.GetPolicyRequest("policy-a", Management.CapabilityPolicyRecordKind.POLICY), options).get(2, TimeUnit.SECONDS).value().policy().isPresent(), "policy inspection");
        var page = profile.listPolicies(new Management.ListPoliciesRequest(Management.CapabilityPolicyRecordKind.POLICY, Optional.of(new Management.PageRequest(1, Optional.empty()))), options).get(2, TimeUnit.SECONDS);
        check(page.value().page().orElseThrow().nextPageToken().isPresent() && client.pages == 1, "one bounded page without draining");
        var capabilities = profile.listCapabilities(new Management.ListCapabilitiesRequest(Optional.empty(), Optional.empty(), Optional.empty(), "deployment-a", false), options).get(2, TimeUnit.SECONDS);
        check(capabilities.value().revision().orElseThrow().deploymentId().equals("deployment-a"), "selected deployment");
        System.out.println("shared profile lifetime/recovery: passed");
    }
}
