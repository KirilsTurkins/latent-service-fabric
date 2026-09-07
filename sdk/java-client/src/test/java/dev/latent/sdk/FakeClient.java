package dev.latent.sdk;

import java.nio.ByteBuffer;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;

/** Test-only server policy and interface fixture; this is not an SDK transport. */
final class FakeClient implements LatentClient {
    static final class TransportFailure extends RuntimeException {
        TransportFailure(String message) { super(message); }
    }

    static final class ServerRejection extends RuntimeException {
        ServerRejection(String message) { super(message); }
    }

    private static final Models.BudgetConsumption CONSUMPTION =
            new Models.BudgetConsumption(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);
    private static final Models.PlatformFailure CANCELLED =
            new Models.PlatformFailure("cancelled", "fixture cancellation", false, List.of());

    static final class Entry {
        final String root;
        final Optional<String> parent;
        final CompletableFuture<Models.InvocationOutcome> response = new CompletableFuture<>();
        Models.ActivationStatus status;
        boolean cancelRequested;

        Entry(String id, Models.InvokeRequest request) {
            root = request.rootActivationId().orElse(id);
            parent = request.parentActivationId();
            status = new Models.ActivationStatus(id, "running", Optional.empty(), Optional.empty(),
                    Optional.empty(), 1, Optional.empty(), Map.of());
        }
    }

    final List<Models.InvokeRequest> requests = new ArrayList<>();
    final Map<String, Entry> entries = new HashMap<>();
    boolean failNextCancel;

    @Override
    public CompletableFuture<Models.InvocationOutcome> invoke(Models.InvokeRequest request) {
        requests.add(request);
        boolean empty = List.of(request.activationId(), request.rootActivationId(), request.parentActivationId())
                .stream().anyMatch(value -> value.isPresent() && value.get().isEmpty());
        if (empty || (request.parentActivationId().isPresent() && request.rootActivationId().isEmpty())) {
            return CompletableFuture.failedFuture(new ServerRejection("invalid-argument"));
        }
        // Assignment belongs to this fake server after observing the unchanged request.
        String id = request.activationId().orElse("server-assigned-" + requests.size());
        if (entries.containsKey(id)) {
            return CompletableFuture.failedFuture(new ServerRejection("already-exists"));
        }
        Entry entry = new Entry(id, request);
        entries.put(id, entry);
        return entry.response;
    }

    @Override
    public CompletableFuture<Models.CancelResponse> cancel(String id, String reason) {
        if (failNextCancel) {
            failNextCancel = false;
            return CompletableFuture.failedFuture(new TransportFailure("cancel transport unavailable"));
        }
        Entry entry = entries.get(id);
        if (entry == null) {
            return CompletableFuture.completedFuture(
                    new Models.CancelResponse(Models.CancelDisposition.NOT_FOUND, Optional.empty()));
        }
        if (entry.status.terminalState().isPresent()) {
            return CompletableFuture.completedFuture(new Models.CancelResponse(
                    Models.CancelDisposition.ALREADY_TERMINAL, entry.status.terminalState()));
        }
        entry.cancelRequested = true;
        return CompletableFuture.completedFuture(
                new Models.CancelResponse(Models.CancelDisposition.ACCEPTED, Optional.empty()));
    }

    @Override
    public CompletableFuture<Models.ActivationStatus> getActivation(String id) {
        Entry entry = entries.get(id);
        return entry == null
                ? CompletableFuture.failedFuture(new ServerRejection("not-found"))
                : CompletableFuture.completedFuture(entry.status);
    }

    void finish(String id, boolean loseResponse) {
        Entry entry = entries.get(id);
        if (entry == null) throw new AssertionError("missing fixture activation");
        String terminal = entry.cancelRequested ? "cancelled" : "completed";
        Models.RetainedInvocationOutcome retained = entry.cancelRequested
                ? new Models.RetainedPlatformFailure(CANCELLED)
                : new Models.ActivationSuccessSummary(Optional.empty(), List.of(), Map.of());
        entry.status = new Models.ActivationStatus(id, entry.cancelRequested ? "running" : "committed", Optional.of(terminal),
                Optional.of(retained), Optional.of(CONSUMPTION), 2, Optional.of(2L), Map.of());
        if (loseResponse) {
            entry.response.completeExceptionally(new TransportFailure("invoke response lost after completion"));
        } else if (entry.cancelRequested) {
            entry.response.complete(new Models.PlatformInvocationFailure(
                    new Models.InvocationReceipt(id, "r", "d", 1, CONSUMPTION), CANCELLED));
        } else {
            entry.response.complete(new Models.InvocationSuccess(new Models.InvokeResponse(
                    id, "r", "d", 1, ByteBuffer.allocate(0), "application/octet-stream",
                    Optional.empty(), List.of(), CONSUMPTION, Map.of())));
        }
    }
}
