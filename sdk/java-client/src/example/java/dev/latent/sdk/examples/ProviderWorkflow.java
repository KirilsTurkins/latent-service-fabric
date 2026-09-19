package dev.latent.sdk.examples;

import com.google.gson.GsonBuilder;
import dev.latent.sdk.Management;
import dev.latent.sdk.transport.RpcClient;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;

public final class ProviderWorkflow {
    private static final java.util.logging.Logger DEPENDENCY_LOGGER = java.util.logging.Logger.getLogger("io.grpc");
    private final ProviderInput input;
    private final Map<String, Boolean> assertions = new LinkedHashMap<>();
    private final ArrayList<String> identities = new ArrayList<>();
    private final long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(80);
    private String stage = "input";

    private ProviderWorkflow(ProviderInput input) { this.input = input; }
    private void require(boolean condition) { ProviderInput.require(condition, stage); }
    private Management.CallOptions options() {
        long remaining = TimeUnit.NANOSECONDS.toMillis(deadline - System.nanoTime());
        require(remaining > 0);
        return new Management.CallOptions(Optional.of(Math.min(3000, remaining)));
    }
    private <Value> Value await(CompletableFuture<Value> future) throws Exception {
        long remaining = deadline - System.nanoTime(); require(remaining > 0);
        return future.get(Math.min(remaining, TimeUnit.SECONDS.toNanos(4)), TimeUnit.NANOSECONDS);
    }
    private Management.ClientFailure failed(CompletableFuture<?> future) throws Exception {
        try { await(future); throw new IllegalStateException(stage); }
        catch (ExecutionException | java.util.concurrent.CancellationException failure) {
            return Management.clientFailure(failure).orElseThrow(() -> new IllegalStateException(stage));
        }
    }
    private void passed(String name) { assertions.put(name, true); }
    private Management.InvokeRequest request(String provider, String suffix, String function, String tenant, boolean exhaustFuel) {
        return input.request(provider, "java-" + suffix, function, tenant, exhaustFuel);
    }
    private void terminal(RpcClient client, String identity) throws Exception {
        long end = Math.min(deadline, System.nanoTime() + TimeUnit.SECONDS.toNanos(3));
        while (System.nanoTime() < end) {
            var response = await(client.getActivation(new Management.GetActivationRequest(identity), options())).value();
            require(response.activationId().equals(identity));
            if (response.terminalState().isPresent()) return;
            Thread.sleep(5);
        }
        throw new IllegalStateException("retained-terminal-expired");
    }

    private void invocations(RpcClient client) throws Exception {
        String tenant = input.field("tenant");
        for (String provider : new String[] {"http", "blob"}) {
            stage = provider + "-guest";
            var response = await(client.invoke(request(provider, provider, null, tenant, false), options())).value();
            input.identity(response, provider, "java-" + provider);
            require(ProviderInput.guest(response) == (provider.equals("http") ? 2201 : 4));
            identities.add("java-" + provider); passed(provider + "Guest");
        }
        stage = "declared-error";
        var declared = await(client.invoke(request("callee", "declared", "fail", tenant, false), options())).value();
        require(declared.declaredError().isPresent()); input.identity(declared, "callee", "java-declared");
        identities.add("java-declared"); passed("declaredError");
        stage = "platform-failure";
        var platform = await(client.invoke(request("callee", "platform", "spin", tenant, true), options())).value();
        require(platform.platformFailure().isPresent()); identities.add("java-platform"); passed("platformFailure");
        stage = "wrong-tenant";
        try (var denied = input.client("foreign", false, false)) {
            require(failed(denied.invoke(request("http", "wrong-tenant", null, "foreign", false), options())).grpcStatus().equals(Optional.of(7)));
            passed("wrongTenant");
        }
        stage = "wrong-credential";
        try (var denied = input.client(tenant, true, false)) {
            require(failed(denied.invoke(request("http", "wrong-auth", null, tenant, false), options())).grpcStatus().equals(Optional.of(16)));
            passed("wrongCredential");
        }
        stage = "response-limit";
        try (var limited = input.client(tenant, false, true)) {
            var failure = failed(limited.invoke(request("http", "limited", null, tenant, false), options()));
            require(failure.dispatched() && failure.outcome().equals(Management.OutcomeKnowledge.UNKNOWN)
                    && !failure.category().equals(Management.FailureCategory.INVALID_REQUEST)
                    && failure.identity().activationId().equals(Optional.of("java-limited")));
            terminal(client, "java-limited"); identities.add("java-limited"); passed("responseLimit");
        }
    }

    private void management(RpcClient client) throws Exception {
        stage = "bounded-pages";
        var first = await(client.listPolicies(new Management.ListPoliciesRequest(Management.CapabilityPolicyRecordKind.POLICY,
                Optional.of(new Management.PageRequest(1, Optional.empty()))), options())).value();
        require(first.policies().size() == 1);
        String token = first.page().orElseThrow().nextPageToken().orElseThrow();
        var next = await(client.listPolicies(new Management.ListPoliciesRequest(Management.CapabilityPolicyRecordKind.POLICY,
                Optional.of(new Management.PageRequest(1, Optional.of(token)))), options())).value();
        require(next.policies().size() == 1 && !next.policies().getFirst().id().equals(first.policies().getFirst().id()));
        passed("boundedPages");
        stage = "provider-inspection";
        var providers = await(client.listCapabilities(new Management.ListCapabilitiesRequest(Optional.empty(), Optional.empty(),
                Optional.of(new Management.PageRequest(1, Optional.empty())), input.target("http", "route"), false), options())).value();
        require(providers.capabilities().size() == 1 && providers.capabilities().getFirst().contract().equals("latent:http/client@0.2.0")
                && providers.capabilities().getFirst().inspection().isPresent());
        passed("providerInspection");
        stage = "mutation-receipt";
        var policy = new Management.Policy("java-example-policy", Optional.of(new Management.ObjectMetadata("java-example-policy",
                Optional.of(input.field("tenant")), Optional.empty(), Map.of(), Map.of())), input.field("policyDocument"), 0,
                "lsf-capability-policy-v1", Management.CapabilityPolicyRecordKind.POLICY, "", false);
        var request = new Management.ApplyPolicyRequest(Optional.of(policy), Optional.of(0L), "java-policy-create");
        var created = await(client.applyPolicy(request, options()));
        require(created.metadata().auditAck().isEmpty() && created.metadata().auditStatus().isEmpty()
                && created.metadata().auditAttemptSequence().isEmpty() && created.metadata().outcome().equals(Management.OutcomeKnowledge.OBSERVED));
        var receipt = created.value().receipt().orElseThrow();
        require(receipt.operationId().equals("java-policy-create"));
        var inspected = await(client.getPolicy(new Management.GetPolicyRequest(policy.id(), policy.recordKind()), options())).value();
        require(inspected.policy().orElseThrow().generation() == receipt.generation());
        var recovered = await(client.getPolicyOperation(new Management.GetPolicyOperationRequest("java-policy-create"), options()));
        require(recovered.value().receipt().equals(Optional.of(receipt)));
        var absent = await(client.getPolicyOperation(new Management.GetPolicyOperationRequest("java-unknown-operation"), options()));
        require(absent.value().receipt().isEmpty() && absent.metadata().outcome().equals(Management.OutcomeKnowledge.UNKNOWN));
        passed("mutationReceipt");
        stage = "exact-replay";
        require(await(client.applyPolicy(request, options())).value().receipt().equals(Optional.of(receipt))); passed("exactReplay");
        stage = "precondition-conflict";
        var conflicting = new Management.ApplyPolicyRequest(request.policy(), Optional.of(0L), "java-stale-precondition");
        var failure = failed(client.applyPolicy(conflicting, options()));
        require(failure.category().equals(Management.FailureCategory.RPC) && failure.outcome().equals(Management.OutcomeKnowledge.OBSERVED));
        passed("preconditionConflict");
    }

    private void mode(String value) throws Exception {
        Path root = Path.of(input.field("controlDirectory"));
        Path temporary = root.resolve("mode-java.tmp");
        Files.writeString(temporary, value, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
        Files.move(temporary, root.resolve("mode"), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
    }

    private void marker(String prefix, String token, CompletableFuture<?> pending) throws Exception {
        Path path = Path.of(input.field("controlDirectory")).resolve(prefix + "-" + token);
        long end = Math.min(deadline, System.nanoTime() + TimeUnit.SECONDS.toNanos(3));
        while (System.nanoTime() < end) {
            if (Files.exists(path, LinkOption.NOFOLLOW_LINKS)) {
                require(Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)); return;
            }
            if (pending != null && pending.isDone()) throw new IllegalStateException("held-call-finished-before-provider-start");
            Thread.sleep(2);
        }
        throw new IllegalStateException("provider-rendezvous-expired");
    }

    private void held(RpcClient client, RpcClient observer, String kind) throws Exception {
        stage = "held-" + kind;
        String identity = "java-" + kind;
        String token = "hold-" + identity;
        mode(token);
        var pending = client.invoke(request("http", kind, null, input.field("tenant"), false),
                new Management.CallOptions(Optional.of(kind.equals("deadline") ? 500L : 3000L)));
        marker("started", token, pending); identities.add(identity);
        require(await(observer.getActivation(new Management.GetActivationRequest(identity), options())).value().terminalState().isEmpty());
        switch (kind) {
            case "local-cancel" -> {
                pending.cancel(true);
                var failure = failed(pending);
                require(pending.isCancelled() && failure.category().equals(Management.FailureCategory.LOCAL_CANCELLED)
                        && failure.identity().activationId().equals(Optional.of(identity)));
                var cancelled = await(observer.cancel(new Management.CancelRequest(identity, "explicit recovery"), options())).value();
                require(cancelled.disposition().equals(Management.CancelDisposition.ACCEPTED) || cancelled.disposition().equals(Management.CancelDisposition.ALREADY_TERMINAL));
                passed("localCancellation"); passed("lostResponseStatus");
            }
            case "explicit-cancel" -> {
                require(await(observer.cancel(new Management.CancelRequest(identity, "explicit request"), options())).value().disposition().equals(Management.CancelDisposition.ACCEPTED));
                try { require(await(pending).value().platformFailure().orElseThrow().code().equals("cancelled")); }
                catch (ExecutionException failure) {
                    var code = Management.clientFailure(failure).orElseThrow().grpcStatus();
                    require(code.equals(Optional.of(1)) || code.equals(Optional.of(4)));
                }
                passed("explicitCancellation");
            }
            case "deadline" -> {
                var failure = failed(pending);
                require(failure.category().equals(Management.FailureCategory.DEADLINE) && failure.identity().activationId().equals(Optional.of(identity)));
                passed("absoluteDeadline");
            }
            case "shutdown" -> {
                require(client.shutdown(Duration.ofSeconds(3)).clean());
                require(failed(pending).category().equals(Management.FailureCategory.LOCAL_CANCELLED));
                passed("shutdownOutstanding");
            }
            default -> throw new IllegalStateException("unknown-hold");
        }
        marker("closed", token, null); mode("reply"); terminal(observer, identity);
    }

    private Map<String, Object> execute() throws Exception {
        try (var client = input.client(input.field("tenant"), false, false); var observer = input.client(input.field("tenant"), false, false)) {
            invocations(client); management(client);
            for (String kind : new String[] {"local-cancel", "explicit-cancel", "deadline", "shutdown"}) held(client, observer, kind);
            require(client.shutdown(Duration.ofSeconds(3)).clean() && observer.shutdown(Duration.ofSeconds(3)).clean());
            passed("clientOwnersReaped");
            require(assertions.size() == 18 && identities.size() == 9);
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("schemaVersion", "latent.sdk.provider.workflow.result.v1"); result.put("language", "java");
            result.put("assertions", assertions); result.put("activationIds", identities); result.put("operationId", "java-policy-create");
            result.put("auditAttempt", null); result.put("transport", "numeric-loopback-http2-protobuf-v1");
            return result;
        }
    }

    public static void main(String[] args) {
        DEPENDENCY_LOGGER.setLevel(java.util.logging.Level.OFF);
        ProviderWorkflow workflow = null;
        try {
            ProviderInput.require(args.length == 2 && args[0].equals("--config"), "configuration-arguments");
            workflow = new ProviderWorkflow(new ProviderInput(Path.of(args[1])));
            System.out.println(new GsonBuilder().serializeNulls().create().toJson(workflow.execute()));
        } catch (Exception failure) {
            String stage = workflow == null ? "input" : workflow.stage;
            Map<String, Object> diagnostic = new LinkedHashMap<>();
            diagnostic.put("stage", "java-participant"); diagnostic.put("reason", stage);
            Management.clientFailure(failure).ifPresent(value -> {
                diagnostic.put("category", value.category().value());
                value.grpcStatus().ifPresent(code -> diagnostic.put("grpcStatus", code));
            });
            System.err.println(new GsonBuilder().create().toJson(diagnostic));
            System.exit(1);
        }
    }
}
