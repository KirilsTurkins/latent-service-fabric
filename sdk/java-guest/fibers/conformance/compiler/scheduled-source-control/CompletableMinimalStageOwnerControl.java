import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.CompletableFuture;
import dev.latent.guest.runtime.concurrent.CompletionStage;
import dev.latent.guest.runtime.concurrent.Executors;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/** Original continuation owners against the private source-ledger double. */
public final class CompletableMinimalStageOwnerControl {
    private static void require(boolean value, String message) { if (!value) throw new AssertionError(message); }
    private static void held(int queue, int result, int executor) {
        require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == queue
            && Activation.count(LatentRuntimeActivationOwnerKind.Result) == result
            && Activation.count(LatentRuntimeActivationOwnerKind.Executor) == executor, "owners");
    }
    private static void copies() {
        var source = new CompletableFuture<Integer>();
        CompletionStage<Integer> view = source.minimalCompletionStage(); held(1, 1, 0);
        var first = view.toCompletableFuture(); var second = view.toCompletableFuture(); held(3, 3, 0);
        require(first.cancel(false), "copy-not-cancelled"); held(2, 2, 0);
        require(source.complete(42) && second.join() == 42 && first.isCancelled(), "copy-result");
        held(0, 0, 0); Activation.idle();
    }
    private static void admission(String mode) {
        var source = new CompletableFuture<Integer>();
        Activation.denyNext = mode.equals("queue") ? "QueuedWork" : "Result";
        if (mode.equals("rollback-denied")) Activation.denyCloseNext = "QueuedWork";
        if (mode.equals("rollback-lost")) Activation.loseCloseAckNext = "QueuedWork";
        try { source.minimalCompletionStage(); throw new AssertionError("admission-not-refused"); }
        catch (IllegalStateException expected) { require("source-owner-admission-denied".equals(expected.getMessage()), "admission-primary"); }
        require(source.getNumberOfDependents() == 0, "failed-view-retained");
        if (mode.equals("rollback-denied") || mode.equals("rollback-lost")) {
            held(mode.equals("rollback-denied") ? 1 : 0, 0, 0);
            require(Activation.poisoned && Activation.retainsFailedQueued() && Activation.failedLeaseAttempts() == 1,
                    "uncertain-rollback-not-fenced");
        } else { held(0, 0, 0); Activation.idle(); }
    }
    private static void copyDenied() {
        CompletionStage<Integer> ready = CompletableFuture.completedStage(42);
        Activation.denyNext = "Result";
        try { ready.toCompletableFuture(); throw new AssertionError("copy-admission-not-refused"); }
        catch (IllegalStateException expected) { require("source-owner-admission-denied".equals(expected.getMessage()), "copy-primary"); }
        held(0, 0, 0);
        require(ready.toCompletableFuture().join() == 42, "view-damaged-by-refusal");
        held(0, 0, 0); Activation.idle();
    }
    private static void running() throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(1);
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicInteger callbacks = new AtomicInteger();
        try {
            var source = new CompletableFuture<Integer>();
            var view = source.minimalCompletionStage();
            var next = view.thenApplyAsync(value -> {
                callbacks.incrementAndGet(); entered.countDown();
                while (true) try { release.await(); return value + 1; } catch (InterruptedException ignored) { }
            }, pool);
            var copy = next.toCompletableFuture();
            require(source.complete(41) && entered.await(5, TimeUnit.SECONDS), "callback-not-started");
            require(copy.cancel(true), "copy-cancellation");
            held(1, 1, 1);
            require(((Activation.ManagedPool)pool).hasPendingWork(), "running-work-not-pending");
            pool.shutdown(); require(!pool.isTerminated(), "retired-before-callback");
            release.countDown(); require(pool.awaitTermination(5, TimeUnit.SECONDS), "termination");
            require(callbacks.get() == 1 && next.toCompletableFuture().join() == 42, "running-stage-result");
            held(0, 0, 0); Activation.idle();
        } finally { release.countDown(); pool.shutdownNow(); }
    }
    public static void main(String[] args) throws Exception {
        switch (args[0]) {
            case "copies" -> copies();
            case "queue", "result", "rollback-denied", "rollback-lost" -> admission(args[0]);
            case "copy-denied" -> copyDenied();
            case "running" -> running();
            default -> throw new IllegalArgumentException("mode");
        }
        System.out.println("COMPLETABLE_MINIMAL_STAGE_OWNER PASS " + args[0]);
    }
}
