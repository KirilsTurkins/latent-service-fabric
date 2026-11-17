import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Real scheduled executor source with an explicit faulting test ledger. */
public final class ScheduledQueuedSettlementControl {
    private static void require(boolean value, String detail) {
        if (!value) throw new AssertionError(detail);
    }
    private static void failSettlement(String kind) {
        if (kind.equals("denied")) Activation.denyCloseNext = "QueuedWork";
        else if (kind.equals("lost")) Activation.loseCloseAckNext = "QueuedWork";
        else throw new IllegalArgumentException("unknown-fault");
    }
    private static void checkFailure() {
        require(Activation.failedLeaseAttempts() == 1, "queued-settlement-retried");
        require(Activation.poisoned, "uncertain-settlement-did-not-poison");
        require(Activation.retainsFailedQueued(), "original-lease-not-rooted");
        try {
            Activation.owner(LatentRuntimeActivationOwnerKind.QueuedWork);
            throw new AssertionError("admission-after-poison");
        } catch (IllegalStateException expected) {
            require(expected.getMessage().equals("activation-runtime-poisoned-store"), "wrong-refusal");
        }
    }
    private static int held() { return Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork); }
    private static void preentry(String fault) throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        AtomicInteger calls = new AtomicInteger();
        Activation.denyNext = "Result";
        failSettlement(fault);
        try {
            try { pool.schedule(calls::incrementAndGet, 1, TimeUnit.DAYS); throw new AssertionError("missing-result-refusal"); }
            catch (IllegalStateException expected) { require(expected.getMessage().equals("source-owner-admission-denied"), "wrong-original-error"); }
            require(calls.get() == 0 && !pool.hasPendingWork(), "preentry-work-was-installed");
            checkFailure();
            require(held() == (fault.equals("denied") ? 1 : 0), "preentry-host-outcome");
            pool.shutdownNow();
            require(pool.awaitTermination(5, TimeUnit.SECONDS), "preentry-pool-not-terminated");
            require(Activation.failedLeaseAttempts() == 1, "preentry-retried");
        } finally { pool.shutdownNow(); }
    }
    private static void insertion(String fault, boolean after) throws Exception {
        AtomicInteger calls = new AtomicInteger();
        AtomicReference<Thread> worker = new AtomicReference<>();
        var failure = new IllegalStateException("queued-insertion-failure");
        var pool = new ScheduledThreadPoolExecutor(1, target -> {
            Thread thread = new Thread(target); worker.set(thread); return thread;
        });
        try {
            ScheduledFuture<?> original = pool.schedule(calls::incrementAndGet, 1, TimeUnit.DAYS);
            var field = pool.getClass().getDeclaredField("queue"); field.setAccessible(true);
            synchronized (pool) {
                var prior = (java.util.ArrayList<?>)field.get(pool);
                field.set(pool, new java.util.ArrayList<Object>(prior) {
                    @Override public boolean add(Object value) {
                        if (after) super.add(value);
                        throw failure;
                    }
                });
            }
            failSettlement(fault);
            try { pool.schedule(calls::incrementAndGet, 1, TimeUnit.DAYS); throw new AssertionError("missing-insert-failure"); }
            catch (IllegalStateException expected) { require(expected == failure, "wrong-insert-error"); }
            require(calls.get() == 0 && pool.hasPendingWork(), "insertion-work-lost");
            require(held() == (fault.equals("denied") ? 2 : 1)
                    && Activation.count(LatentRuntimeActivationOwnerKind.Result) == 2, "insertion-custody-before-stop");
            checkFailure();
            var returned = pool.shutdownNow();
            require(returned.size() == 1 && returned.get(0) == original, "original-queue-copy-lost");
            require(pool.hasPendingWork() && held() == (fault.equals("denied") ? 1 : 0)
                    && Activation.count(LatentRuntimeActivationOwnerKind.Result) == 1, "insertion-refunded-early");
            require(calls.get() == 0 && Activation.failedLeaseAttempts() == 1, "insertion-replayed");
        } finally {
            pool.shutdownNow();
            Thread thread = worker.get(); if (thread != null) { thread.join(5000); require(!thread.isAlive(), "insert-worker-not-stopped"); }
        }
    }
    private static void requeue(String fault) throws Exception {
        AtomicInteger factories = new AtomicInteger(), calls = new AtomicInteger();
        AtomicReference<Thread> worker = new AtomicReference<>();
        var original = new IllegalStateException("requeue-worker-start-error");
        var pool = new ScheduledThreadPoolExecutor(2, target -> {
            if (factories.incrementAndGet() == 2) {
                failSettlement(fault);
                // Model a failure after the factory returned, so the new copy
                // still takes the rollback/uncertain-settlement path.
                return new Thread(target) { @Override public void start() { throw original; } };
            }
            Thread thread = new Thread(target); worker.set(thread); return thread;
        });
        try {
            ScheduledFuture<?> future = pool.scheduleAtFixedRate(calls::incrementAndGet, 1, 1, TimeUnit.DAYS);
            try { ((Runnable)future).run(); throw new AssertionError("missing-requeue-failure"); }
            catch (IllegalStateException expected) { require(expected == original, "wrong-worker-start-error"); }
            require(factories.get() == 2 && calls.get() == 1 && !future.isDone(), "unexpected-requeue-effects");
            require(pool.hasPendingWork() && held() == (fault.equals("denied") ? 2 : 1), "requeue-custody-before-stop");
            checkFailure();
            require(pool.shutdownNow().size() == 1, "original-queue-copy-lost");
            require(pool.hasPendingWork() && held() == (fault.equals("denied") ? 1 : 0), "uncertain-copy-refunded");
            require(Activation.failedLeaseAttempts() == 1 && calls.get() == 1, "requeue-replayed");
        } finally {
            pool.shutdownNow();
            Thread thread = worker.get(); if (thread != null) { thread.join(5000); require(!thread.isAlive(), "worker-not-stopped"); }
        }
    }
    private static void cancellation(String fault) throws Exception {
        AtomicInteger calls = new AtomicInteger();
        var pool = new ScheduledThreadPoolExecutor(1);
        try {
            ScheduledFuture<?> future = pool.scheduleAtFixedRate(calls::incrementAndGet, 1, 1, TimeUnit.DAYS);
            failSettlement(fault);
            try { future.cancel(false); throw new AssertionError("missing-cancel-failure"); }
            catch (IllegalStateException expected) { require(expected.getMessage().startsWith("source-owner-settlement-"), "wrong-cancel-error"); }
            require(calls.get() == 0 && future.isCancelled() && pool.hasPendingWork(), "cancel-lost-custody");
            checkFailure();
            require(held() == (fault.equals("denied") ? 1 : 0), "cancel-host-outcome");
            pool.shutdownNow();
            require(pool.hasPendingWork() && Activation.failedLeaseAttempts() == 1, "cancel-retried");
        } finally { pool.shutdownNow(); }
    }
    private static void factoryWithdrawal(String fault) throws Exception {
        AtomicInteger factories = new AtomicInteger(), calls = new AtomicInteger();
        AtomicReference<ScheduledThreadPoolExecutor> selected = new AtomicReference<>();
        var pool = new ScheduledThreadPoolExecutor(1, target -> {
            if (factories.incrementAndGet() == 1) return null;
            failSettlement(fault);
            selected.get().shutdownNow();
            throw new AssertionError("withdrawal-should-have-failed");
        });
        selected.set(pool);
        try {
            var future = pool.scheduleAtFixedRate(calls::incrementAndGet, 1, 1, TimeUnit.DAYS);
            try { ((Runnable)future).run(); throw new AssertionError("missing-withdrawal-failure"); }
            catch (IllegalStateException error) {
                require(error.getMessage().startsWith("source-owner-settlement-"), "wrong-withdrawal-error");
            }
            require(factories.get() == 2 && calls.get() == 1 && !future.isDone() && pool.hasPendingWork(),
                "factory-withdrawal-lost-custody");
            require(held() == (fault.equals("denied") ? 2 : 1)
                && Activation.count(LatentRuntimeActivationOwnerKind.Result) == 1, "factory-withdrawal-host-outcome");
            checkFailure();
            var remaining = pool.shutdownNow();
            require(remaining.size() == 1 && remaining.get(0) == future, "factory-withdrawal-lost-original-copy");
            require(pool.hasPendingWork() && held() == (fault.equals("denied") ? 1 : 0)
                && Activation.count(LatentRuntimeActivationOwnerKind.Result) == 0
                && Activation.count(LatentRuntimeActivationOwnerKind.Executor) == 1, "factory-withdrawal-refunded-uncertain");
            require(Activation.failedLeaseAttempts() == 1 && future.cancel(false), "factory-withdrawal-retried");
        } finally { pool.shutdownNow(); }
    }
    private static void reentryModel(String fault) throws Exception {
        AtomicInteger calls = new AtomicInteger();
        var pool = new ScheduledThreadPoolExecutor(1);
        try {
            ScheduledFuture<?> future = pool.scheduleAtFixedRate(calls::incrementAndGet, 1, 1, TimeUnit.DAYS);
            // The test ledger models cancellation at the admission boundary.
            // This does not establish that a guest host import is reentrant.
            Activation.admissionObservationKind = "QueuedWork";
            Activation.admissionObservation = () -> { require(future.cancel(false), "modeled-cancel-failed"); failSettlement(fault); };
            try { ((Runnable)future).run(); throw new AssertionError("missing-modeled-settlement-failure"); }
            catch (IllegalStateException expected) { require(expected.getMessage().startsWith("source-owner-settlement-"), "wrong-modeled-error"); }
            require(calls.get() == 1 && future.isCancelled() && !pool.hasPendingWork(), "modeled-cancel-effects");
            checkFailure();
            require(held() == (fault.equals("denied") ? 1 : 0), "modeled-host-outcome");
            pool.shutdownNow();
            require(pool.awaitTermination(5, TimeUnit.SECONDS), "modeled-pool-not-terminated");
            require(Activation.failedLeaseAttempts() == 1 && calls.get() == 1, "modeled-settlement-retried");
        } finally { pool.shutdownNow(); }
    }
    public static void main(String[] args) throws Exception {
        require(args.length == 2, "usage");
        switch (args[0]) {
            case "preentry" -> preentry(args[1]);
            case "insert-before" -> insertion(args[1], false);
            case "insert-after" -> insertion(args[1], true);
            case "requeue" -> requeue(args[1]);
            case "factory-withdrawal" -> factoryWithdrawal(args[1]);
            case "cancel" -> cancellation(args[1]);
            case "reentry-model" -> reentryModel(args[1]);
            default -> throw new IllegalArgumentException("unknown-path");
        }
        System.out.println("SCHEDULED_QUEUED_SETTLEMENT PASS " + args[0] + " " + args[1]);
    }
}
