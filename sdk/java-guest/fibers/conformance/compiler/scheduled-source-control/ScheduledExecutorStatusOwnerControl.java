import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/** Actual scheduled-pool source and a private host-ledger double. */
public final class ScheduledExecutorStatusOwnerControl {
    private static void require(boolean value, String message) { if (!value) throw new AssertionError(message); }
    private static void await(CountDownLatch latch, String message) throws InterruptedException {
        require(latch.await(5, TimeUnit.SECONDS), message);
    }
    private static void failure(boolean lost) {
        var pool = new ScheduledThreadPoolExecutor(1);
        if (lost) Activation.loseCloseAckNext = "Executor"; else Activation.denyCloseNext = "Executor";
        try { pool.shutdown(); throw new AssertionError("settlement-not-refused"); }
        catch (IllegalStateException expected) { }
        require(pool.isShutdown() && !pool.isTerminated() && Activation.poisoned, "uncertain-status");
        require(Activation.failedLeaseAttempts() == 1 && Activation.count(LatentRuntimeActivationOwnerKind.Executor) == (lost ? 0 : 1),
                "uncertain-owner");
        pool.shutdown();
        require(!pool.isTerminated() && Activation.failedLeaseAttempts() == 1, "uncertain-retry");
    }
    private static void inflight() throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1), inspected = new CountDownLatch(1);
        AtomicBoolean status = new AtomicBoolean();
        AtomicReference<Throwable> failure = new AtomicReference<>();
        Activation.closeObservationKind = "Executor";
        Activation.closeObservation = () -> {
            entered.countDown();
            try { await(release, "settlement-release"); } catch (InterruptedException error) { throw new AssertionError(error); }
        };
        Thread closer = new Thread(() -> { try { pool.shutdown(); } catch (Throwable error) { failure.set(error); } });
        Thread reader = new Thread(() -> {
            try { status.set(pool.isShutdown() && !pool.isTerminated()); }
            catch (Throwable error) { failure.set(error); }
            finally { inspected.countDown(); }
        });
        boolean visible;
        try {
            closer.start(); await(entered, "settlement-not-entered");
            reader.start(); visible = inspected.await(2, TimeUnit.SECONDS) && status.get();
        } finally {
            release.countDown(); closer.join(5000); reader.join(5000);
        }
        require(visible && !closer.isAlive() && !reader.isAlive() && failure.get() == null, "inflight-status");
        require(pool.isShutdown() && pool.isTerminated()
            && Activation.closeAttempts(LatentRuntimeActivationOwnerKind.Executor) == 1, "settled-status");
        Activation.idle();
    }
    private static void running() throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        try {
            var future = pool.submit(() -> { entered.countDown(); release.await(); return 42; });
            await(entered, "running-not-entered"); pool.shutdown();
            require(pool.isShutdown() && !pool.isTerminated() && pool.hasPendingWork(), "running-status");
            require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == 1
                && Activation.count(LatentRuntimeActivationOwnerKind.Result) == 1
                && Activation.count(LatentRuntimeActivationOwnerKind.Executor) == 1, "running-owners");
            release.countDown(); require(future.get(5, TimeUnit.SECONDS) == 42, "future-result");
            require(pool.awaitTermination(5, TimeUnit.SECONDS) && pool.isTerminated(), "running-not-retired");
            Activation.idle();
        } finally { release.countDown(); pool.shutdownNow(); }
    }
    public static void main(String[] args) throws Exception {
        switch (args[0]) {
            case "denied" -> failure(false);
            case "lost" -> failure(true);
            case "inflight" -> inflight();
            case "running" -> running();
            default -> throw new IllegalArgumentException("mode");
        }
        System.out.println("SCHEDULED_EXECUTOR_STATUS_OWNER PASS " + args[0]);
    }
}
