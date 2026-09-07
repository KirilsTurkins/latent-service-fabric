package dev.latent.sdk;

import java.nio.ByteBuffer;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;

/** Executable interface-contract checks without JUnit or a network service. */
public final class InvocationIdentityTest {
    private InvocationIdentityTest() { }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static <T> T await(CompletionStage<T> operation) throws Exception {
        return operation.toCompletableFuture().get(5, TimeUnit.SECONDS);
    }

    private static void rejects(CompletionStage<?> operation, Class<? extends Throwable> expected)
            throws Exception {
        try {
            await(operation);
            throw new AssertionError("operation must fail");
        } catch (ExecutionException failure) {
            check(expected.isInstance(failure.getCause()), "transport and server errors remain distinct");
        }
    }

    private static Models.InvokeRequest absent() {
        var target = new Models.InvocationTarget("tenant", "echo", "example:echo/api@1.0.0",
                "echo", Optional.empty());
        var budget = new Models.ResourceBudget(1, 1, Optional.empty(), 0, 0, 0, 0, 0, 0, 0, 0);
        var options = new Models.InvokeOptions(Optional.empty(), (byte) 0,
                Optional.of("separate-key"), budget, Map.of());
        // Preserve source compatibility with the original constructor.
        return new Models.InvokeRequest(target, ByteBuffer.wrap(new byte[] {1}),
                "application/octet-stream", options);
    }

    private static Models.InvokeRequest request(Optional<String> id, Optional<String> root,
            Optional<String> parent) {
        var base = absent();
        return new Models.InvokeRequest(base.target(), base.payload(), base.mediaType(), base.options(),
                id, root, parent);
    }

    private static void pendingCancellation() throws Exception {
        var server = new FakeClient();
        LatentClient client = server;
        var sent = request(Optional.of("known"), Optional.empty(), Optional.empty());
        var pending = client.invoke(sent);
        check(await(client.getActivation("known")).phase().equals("running"), "status before terminal");
        check(!pending.toCompletableFuture().isDone(), "known identity while invoke remains pending");
        check(server.entries.get("known").root.equals("known"), "server defaults root to effective ID");
        server.failNextCancel = true;
        rejects(client.cancel("known", "stop"), FakeClient.TransportFailure.class);
        var accepted = await(client.cancel("known", "stop"));
        check(accepted.disposition() == Models.CancelDisposition.ACCEPTED
                && accepted.terminalState().isEmpty(), "accepted disposition");
        check(!pending.toCompletableFuture().isDone(), "cancel acknowledgment is not terminal completion");
        server.finish("known", false);
        var outcome = await(pending);
        check(outcome instanceof Models.PlatformInvocationFailure failure
                && failure.error().code().equals("cancelled"), "typed cancellation outcome");
        var already = await(client.cancel("known", "again"));
        check(already.disposition() == Models.CancelDisposition.ALREADY_TERMINAL
                && already.terminalState().orElseThrow().equals("cancelled"), "terminal state preserved");
        var missing = await(client.cancel("missing", "stop"));
        check(missing.disposition() == Models.CancelDisposition.NOT_FOUND
                && missing.terminalState().isEmpty(), "not-found disposition");
        check(server.requests.size() == 1 && server.requests.get(0) == sent, "no identity rewrite or retry");
    }

    private static void lostResponse() throws Exception {
        var server = new FakeClient();
        LatentClient client = server;
        var pending = client.invoke(request(Optional.of("recoverable"), Optional.empty(), Optional.empty()));
        server.finish("recoverable", true);
        rejects(pending, FakeClient.TransportFailure.class);
        var status = await(client.getActivation("recoverable"));
        check(status.terminalState().orElseThrow().equals("completed")
                && status.terminalOutcome().orElseThrow() instanceof Models.ActivationSuccessSummary,
                "recover retained success using the caller-known ID");
        check(server.requests.size() == 1, "status recovery must not reinvoke");
    }

    private static void optionalIdentity() throws Exception {
        var server = new FakeClient();
        var absent = absent();
        var pending = server.invoke(absent);
        check(absent.activationId().isEmpty() && absent.rootActivationId().isEmpty()
                && absent.parentActivationId().isEmpty(), "absence preserved for server assignment");
        check(server.entries.get("server-assigned-1").root.equals("server-assigned-1")
                && server.entries.get("server-assigned-1").parent.isEmpty(), "server root default");
        server.finish("server-assigned-1", false);
        check(await(pending) instanceof Models.InvocationSuccess success
                && success.response().activationId().equals("server-assigned-1"), "server-assigned response ID");
        var explicit = request(Optional.of("child"), Optional.of("root"), Optional.of("parent"));
        var child = server.invoke(explicit);
        check(server.requests.get(1) == explicit && server.entries.get("child").root.equals("root")
                && server.entries.get("child").parent.equals(Optional.of("parent")),
                "explicit lineage remains unchanged claims");
        server.finish("child", false);
        await(child);
        for (var invalid : List.of(
                request(Optional.of(""), Optional.empty(), Optional.empty()),
                request(Optional.empty(), Optional.of(""), Optional.empty()),
                request(Optional.empty(), Optional.of("root"), Optional.of("")),
                request(Optional.of("orphan"), Optional.empty(), Optional.of("parent")))) {
            rejects(server.invoke(invalid), FakeClient.ServerRejection.class);
            check(server.requests.getLast() == invalid, "present empty and missing root reach server unchanged");
        }
    }

    public static void main(String[] args) throws Exception {
        pendingCancellation();
        lostResponse();
        optionalIdentity();
        System.out.println("Java invocation identity semantic fixtures passed");
    }
}
