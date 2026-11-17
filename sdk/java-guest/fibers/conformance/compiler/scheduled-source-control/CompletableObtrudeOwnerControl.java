import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** SDK source and private ledger; no component or host qualification. */
public final class CompletableObtrudeOwnerControl {
    private static void require(boolean value) { if (!value) throw new AssertionError("completable-obtrude-owner"); }
    private static void held(int queue, int result) {
        require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == queue
            && Activation.count(LatentRuntimeActivationOwnerKind.Result) == result
            && Activation.count(LatentRuntimeActivationOwnerKind.Executor) == 0);
    }
    private static void queued(String fault) throws Exception {
        var target = new AtomicReference<Runnable>(); var calls = new AtomicInteger();
        var result = new CompletableFuture<Integer>();
        result.completeAsync(() -> { calls.incrementAndGet(); return 42; }, command -> require(target.compareAndSet(null, command)));
        held(1, 1);
        result.obtrudeValue(7); result.obtrudeValue(8);
        require(result.join() == 8 && calls.get() == 0); held(1, 1);
        if (!fault.equals("none")) {
            String[] parts = fault.split("-");
            String kind = parts[0].equals("queue") ? "QueuedWork" : "Result";
            if (parts[1].equals("denied")) Activation.denyCloseNext = kind;
            else Activation.loseCloseAckNext = kind;
        }
        try {
            target.get().run();
            require(fault.equals("none"));
        } catch (IllegalStateException error) {
            require(!fault.equals("none") && error.getMessage().startsWith("source-owner-settlement-"));
        }
        require(result.join() == 8 && calls.get() == 0);
        if (fault.equals("none")) { held(0, 0); Activation.idle(); }
        else {
            require(Activation.poisoned && Activation.failedLeaseAttempts() == 1);
            held(fault.equals("queue-denied") ? 1 : 0,
                fault.startsWith("queue-") || fault.equals("result-denied") ? 1 : 0);
            target.get().run();
            require(Activation.failedLeaseAttempts() == 1);
            // Uncertain original ownership remains fenced until Store teardown.
        }
    }
    private static void running(boolean failure) throws Exception {
        var entered = new CountDownLatch(1); var release = new CountDownLatch(1);
        var worker = new AtomicReference<Thread>(); var calls = new AtomicInteger();
        var result = new CompletableFuture<Integer>();
        var forced = new IllegalStateException("forced-running");
        try {
            result.completeAsync(() -> {
                calls.incrementAndGet(); entered.countDown();
                try { if (!release.await(5, TimeUnit.SECONDS)) throw new AssertionError("release-timeout"); }
                catch (InterruptedException error) { throw new AssertionError(error); }
                return 42;
            }, command -> { var thread = new Thread(command); worker.set(thread); thread.start(); });
            require(entered.await(5, TimeUnit.SECONDS)); held(1, 1);
            if (failure) result.obtrudeException(forced); else result.obtrudeValue(7);
            require(result.isDone()); held(1, 1);
        } finally {
            release.countDown();
            if (worker.get() != null) { worker.get().join(5000); require(!worker.get().isAlive()); }
        }
        require(calls.get() == 1);
        if (failure) require(result.exceptionNow() == forced); else require(result.join() == 7);
        held(0, 0); Activation.idle();
    }
    private static void waitingDestination(boolean failure) throws Exception {
        var source = new CompletableFuture<Integer>(); var calls = new AtomicInteger();
        var destination = source.thenApply(value -> { calls.incrementAndGet(); return value + 1; });
        held(1, 1);
        var forced = new IllegalStateException("forced-destination");
        if (failure) destination.obtrudeException(forced); else destination.obtrudeValue(7);
        held(0, 0); require(source.getNumberOfDependents() == 0);
        source.complete(10); require(calls.get() == 0);
        if (failure) require(destination.exceptionNow() == forced); else require(destination.join() == 7);
        Activation.idle();
    }
    public static void main(String[] args) throws Exception {
        switch (args[0]) {
            case "queued" -> queued("none");
            case "queued-queue-denied" -> queued("queue-denied");
            case "queued-queue-lost" -> queued("queue-lost");
            case "queued-result-denied" -> queued("result-denied");
            case "queued-result-lost" -> queued("result-lost");
            case "running-value" -> running(false);
            case "running-error" -> running(true);
            case "waiting-value" -> waitingDestination(false);
            case "waiting-error" -> waitingDestination(true);
            default -> throw new IllegalArgumentException(args[0]);
        }
        System.out.println("COMPLETABLE_OBTRUDE_OWNER PASS " + args[0]);
    }
}
