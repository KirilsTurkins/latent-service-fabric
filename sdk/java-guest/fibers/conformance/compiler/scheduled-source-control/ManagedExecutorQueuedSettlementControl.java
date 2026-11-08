import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.Executors;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Real executor source and a faulting test ledger, not a signed guest. */
public final class ManagedExecutorQueuedSettlementControl {
    private static void require(boolean value, String detail) {
        if (!value) throw new AssertionError(detail);
    }
    private static void await(CountDownLatch latch) throws InterruptedException {
        require(latch.await(5, TimeUnit.SECONDS), "control-timeout");
    }
    private static void failSettlement(String kind) {
        if (kind.equals("denied")) Activation.denyCloseNext = "QueuedWork";
        else if (kind.equals("lost")) Activation.loseCloseAckNext = "QueuedWork";
        else throw new IllegalArgumentException("unknown-fault");
    }
    private static void checkFailure(String kind) {
        require(Activation.poisoned, "uncertain-settlement-did-not-poison");
        require(Activation.retainsFailedQueued(), "original-lease-not-rooted");
        require(Activation.failedLeaseAttempts() == 1, "settlement-attempt-count");
        require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork)
                == (kind.equals("denied") ? 1 : 0), "test-host-outcome");
        try {
            Activation.owner(LatentRuntimeActivationOwnerKind.QueuedWork);
            throw new AssertionError("admission-after-poison");
        } catch (IllegalStateException expected) {
            require(expected.getMessage().equals("activation-runtime-poisoned-store"), "wrong-refusal");
        }
    }
    private static void rollback(String kind) throws Exception {
        ExecutorService pool = Executors.newSingleThreadExecutor(task -> null);
        failSettlement(kind);
        try {
            pool.execute(() -> { throw new AssertionError("rejected-work-ran"); });
            throw new AssertionError("expected-rollback-failure");
        } catch (IllegalStateException expected) { }
        checkFailure(kind);
        pool.shutdownNow();
        require(pool.awaitTermination(5, TimeUnit.SECONDS), "rollback-pool-not-terminated");
        require(Activation.failedLeaseAttempts() == 1, "rollback-settlement-retried");
    }
    private static void shutdown(String kind) throws Exception {
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        ExecutorService pool = Executors.newSingleThreadExecutor();
        pool.execute(() -> {
            entered.countDown();
            try { release.await(); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
        });
        await(entered);
        AtomicInteger invoked = new AtomicInteger();
        pool.execute(invoked::incrementAndGet);
        failSettlement(kind);
        try {
            try { pool.shutdownNow(); throw new AssertionError("expected-shutdown-failure"); }
            catch (IllegalStateException expected) { }
            checkFailure(kind);
        } finally { release.countDown(); }
        require(pool.awaitTermination(5, TimeUnit.SECONDS), "shutdown-pool-not-terminated");
        pool.shutdownNow();
        require(invoked.get() == 0 && Activation.failedLeaseAttempts() == 1, "shutdown-settlement-retried");
    }
    private static void dispatch(String kind) throws Exception {
        CountDownLatch failed = new CountDownLatch(1);
        AtomicReference<Throwable> workerError = new AtomicReference<>();
        AtomicInteger invoked = new AtomicInteger();
        ExecutorService pool = Executors.newSingleThreadExecutor(task -> {
            Thread thread = new Thread(task);
            thread.setUncaughtExceptionHandler((ignored, error) -> { workerError.set(error); failed.countDown(); });
            return thread;
        });
        failSettlement(kind);
        pool.execute(invoked::incrementAndGet);
        await(failed);
        require(workerError.get() instanceof IllegalStateException && invoked.get() == 0, "dispatch-not-refused");
        checkFailure(kind);
        pool.shutdownNow();
        require(pool.awaitTermination(5, TimeUnit.SECONDS), "dispatch-pool-not-terminated");
        require(Activation.failedLeaseAttempts() == 1, "dispatch-settlement-retried");
    }
    public static void main(String[] args) throws Exception {
        require(args.length == 2, "usage");
        switch (args[0]) {
            case "rollback" -> rollback(args[1]);
            case "shutdown" -> shutdown(args[1]);
            case "dispatch" -> dispatch(args[1]);
            default -> throw new IllegalArgumentException("unknown-path");
        }
        System.out.println("MANAGED_EXECUTOR_QUEUED_SETTLEMENT PASS " + args[0] + " " + args[1]);
    }
}
