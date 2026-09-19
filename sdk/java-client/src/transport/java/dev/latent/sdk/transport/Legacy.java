package dev.latent.sdk.transport;

import dev.latent.sdk.Management;
import dev.latent.sdk.Models;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;
import java.util.function.Function;

final class Legacy {
    private static final Management.CallOptions DEFAULT = new Management.CallOptions(Optional.empty());
    private Legacy() { }

    static <Source, Target> CompletableFuture<Target> mapped(CompletableFuture<Source> source, Function<Source, Target> convert) {
        var target = new CompletableFuture<Target>() {
            @Override public boolean cancel(boolean mayInterruptIfRunning) { return source.cancel(mayInterruptIfRunning); }
        };
        source.whenComplete((value, error) -> {
            if (error != null) target.completeExceptionally(error);
            else {
                try { target.complete(convert.apply(value)); }
                catch (RuntimeException failure) { target.completeExceptionally(failure); }
            }
        });
        return target;
    }

    static CompletableFuture<Models.InvocationOutcome> invoke(RpcClient client, Models.InvokeRequest request) {
        var target = request.target();
        var options = request.options();
        var budget = options.budget();
        var portable = new Management.InvokeRequest(request.activationId(), request.parentActivationId(), request.rootActivationId(),
                Optional.of(new Management.InvocationTarget(target.tenant(), target.service(), target.contract(), target.function(), target.route())),
                request.payload(), request.mediaType(), options.deadlineUnixMillis(), Byte.toUnsignedInt(options.priority()), options.idempotencyKey(),
                Optional.of(new Management.ResourceBudget(budget.cpuFuel(), budget.memoryBytes(), budget.childCalls(), budget.outboundRequests(),
                        budget.stateReadBytes(), budget.stateWriteBytes(), budget.blobReadBytes(), budget.blobWriteBytes(), budget.logBytes(),
                        budget.effectCount(), budget.wallTimeLimitMillis())), options.metadata());
        return mapped(client.invoke(portable, DEFAULT), response -> outcome(response.value()));
    }

    static Models.BudgetConsumption consumption(Management.BudgetConsumption value) {
        return new Models.BudgetConsumption(value.cpuFuel(), value.peakMemoryBytes(), value.wallTimeMicros(), value.childCalls(),
                value.outboundRequests(), value.stateReadBytes(), value.stateWriteBytes(), value.blobReadBytes(), value.blobWriteBytes(),
                value.logBytes(), value.effectCount());
    }

    static Models.DeclaredError declared(Management.DeclaredError value) {
        return new Models.DeclaredError(value.code(), value.message(), value.payload(), value.mediaType(), value.metadata());
    }

    static Models.PlatformFailure platform(Management.PlatformError value) {
        return new Models.PlatformFailure(value.code(), value.message(), value.retryable(), value.detailItems().stream()
                .map(detail -> new Models.ErrorDetail(detail.kind(), detail.fields())).toList());
    }

    static Models.InvocationOutcome outcome(Management.InvokeResponse response) {
        var consumption = consumption(response.consumption().orElseThrow());
        if (response.success().isPresent()) {
            var result = response.success().get();
            return new Models.InvocationSuccess(new Models.InvokeResponse(response.activationId(), response.revisionId(), response.releaseDigest(),
                    response.routeGeneration(), result.payload(), result.mediaType(), result.committedStateVersion(), result.effectIds(), consumption,
                    result.metadata(), response.publicationId()));
        }
        var receipt = new Models.InvocationReceipt(response.activationId(), response.revisionId(), response.releaseDigest(), response.routeGeneration(),
                consumption, response.publicationId());
        if (response.declaredError().isPresent()) return new Models.DeclaredInvocationError(receipt, declared(response.declaredError().get()));
        return new Models.PlatformInvocationFailure(receipt, platform(response.platformFailure().orElseThrow()));
    }

    static CompletableFuture<Models.CancelResponse> cancel(RpcClient client, String identity, String reason) {
        return mapped(client.cancel(new Management.CancelRequest(identity, reason), DEFAULT), response -> {
            var value = response.value();
            Models.CancelDisposition disposition = switch (value.disposition().value()) {
                case 1 -> Models.CancelDisposition.ACCEPTED;
                case 2 -> Models.CancelDisposition.ALREADY_TERMINAL;
                case 3 -> Models.CancelDisposition.NOT_FOUND;
                default -> throw new Management.ClientException(new Management.ClientFailure(Management.FailureCategory.DECODE,
                        "unsupported cancellation disposition", Optional.empty(), Optional.empty(), true, response.metadata().outcome(),
                        response.metadata().identity(), response.metadata().auditAck(), response.metadata().auditStatus(),
                        Optional.of(new Management.UnsupportedWireValue("cancel.disposition", Integer.toString(value.disposition().value()))),
                        response.metadata().auditAttemptSequence()));
            };
            return new Models.CancelResponse(disposition, value.terminalState());
        });
    }

    static CompletableFuture<Models.ActivationStatus> getActivation(RpcClient client, String identity) {
        return mapped(client.getActivation(new Management.GetActivationRequest(identity), DEFAULT), response -> {
            var value = response.value();
            Optional<Models.RetainedInvocationOutcome> outcome = Optional.empty();
            if (value.succeeded().isPresent()) {
                var success = value.succeeded().get();
                outcome = Optional.of(new Models.ActivationSuccessSummary(success.committedStateVersion(), success.effectIds(), success.metadata()));
            } else if (value.declaredError().isPresent()) outcome = Optional.of(new Models.RetainedDeclaredError(declared(value.declaredError().get())));
            else if (value.platformFailure().isPresent()) outcome = Optional.of(new Models.RetainedPlatformFailure(platform(value.platformFailure().get())));
            return new Models.ActivationStatus(value.activationId(), value.phase(), value.terminalState(), outcome,
                    value.finalConsumption().map(Legacy::consumption), value.lastUpdatedUnixMillis(), value.terminalAtUnixMillis(), value.metadata());
        });
    }
}
