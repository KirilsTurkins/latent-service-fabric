import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Compares ordinary JDK and selected SDK behavior, not a signed guest. */
public final class ScheduledFactoryConcurrencyReferenceControl {
    private static void require(boolean value, String label) { if (!value) throw new AssertionError(label); }
    private static void await(CountDownLatch latch, String label) throws InterruptedException {
        require(latch.await(5, TimeUnit.SECONDS), label);
    }
    private static void stop(ScheduledThreadPoolExecutor pool) throws InterruptedException {
        pool.shutdownNow();
        require(pool.awaitTermination(5, TimeUnit.SECONDS), "termination");
    }
    private static void admittedDuringFactory() throws Exception {
        var selected = new AtomicReference<ScheduledThreadPoolExecutor>();
        var helper = new AtomicReference<Thread>();
        var failure = new AtomicReference<Throwable>();
        var accepted = new CountDownLatch(1);
        var ran = new CountDownLatch(2);
        var attempts = new AtomicInteger();
        var pool = new ScheduledThreadPoolExecutor(1, target -> {
            if (attempts.incrementAndGet() == 1) {
                Thread thread = new Thread(() -> {
                    try { selected.get().execute(ran::countDown); }
                    catch (Throwable error) { failure.set(error); }
                    finally { accepted.countDown(); }
                });
                helper.set(thread); thread.start();
                try { await(accepted, "nested-admission-blocked"); }
                catch (InterruptedException error) { throw new AssertionError(error); }
            }
            return new Thread(target);
        });
        selected.set(pool);
        try {
            pool.execute(ran::countDown);
            await(ran, "callbacks");
            helper.get().join(5000);
            require(!helper.get().isAlive() && failure.get() == null && attempts.get() == 1, "nested-work");
        } finally { stop(pool); }
    }
    private static void withdrawnWhileFactoryRuns(boolean throwsFailure) throws Exception {
        var entered = new CountDownLatch(1);
        var release = new CountDownLatch(1);
        var stopped = new CountDownLatch(1);
        var created = new AtomicReference<Thread>();
        var future = new AtomicReference<ScheduledFuture<?>>();
        var removed = new AtomicReference<List<Runnable>>();
        var submitError = new AtomicReference<Throwable>();
        var stopError = new AtomicReference<Throwable>();
        var callbacks = new AtomicInteger();
        var original = new IllegalStateException("factory-failure");
        var pool = new ScheduledThreadPoolExecutor(1, target -> {
            entered.countDown();
            try { await(release, "factory-release"); }
            catch (InterruptedException error) { throw new AssertionError(error); }
            if (throwsFailure) throw original;
            Thread thread = new Thread(target);
            created.set(thread);
            return thread;
        });
        Thread caller = new Thread(() -> {
            try { future.set(pool.schedule(callbacks::incrementAndGet, 1, TimeUnit.DAYS)); }
            catch (Throwable error) { submitError.set(error); }
        });
        Thread stopper = new Thread(() -> {
            try { removed.set(pool.shutdownNow()); }
            catch (Throwable error) { stopError.set(error); }
            finally { stopped.countDown(); }
        });
        try {
            caller.start(); await(entered, "factory-not-entered");
            stopper.start(); await(stopped, "shutdown-blocked-by-factory");
            require(stopError.get() == null && removed.get().size() == 1 && !pool.isTerminated(), "withdrawal");
            release.countDown(); caller.join(5000); stopper.join(5000);
            require(!caller.isAlive() && !stopper.isAlive(), "threads-stuck");
            require(throwsFailure ? submitError.get() == original
                : submitError.get() == null && future.get() == removed.get().get(0), "submission-outcome");
            require(pool.awaitTermination(5, TimeUnit.SECONDS) && callbacks.get() == 0, "withdrawal-termination");
            if (!throwsFailure) require(created.get() != null && !created.get().isAlive(), "late-worker");
            require(removed.get().get(0) instanceof ScheduledFuture<?>
                && !((ScheduledFuture<?>)removed.get().get(0)).isDone(), "returned-future");
            ((ScheduledFuture<?>)removed.get().get(0)).cancel(false);
        } finally {
            release.countDown(); caller.join(5000); stopper.join(5000); stop(pool);
        }
    }
    private static void gracefulPruned() throws Exception {
        var entered = new CountDownLatch(1);
        var release = new CountDownLatch(1);
        var started = new CountDownLatch(1);
        var future = new AtomicReference<ScheduledFuture<?>>();
        var failure = new AtomicReference<Throwable>();
        var calls = new AtomicInteger();
        var pool = new ScheduledThreadPoolExecutor(1, target -> {
            entered.countDown();
            try { await(release, "factory-release"); }
            catch (InterruptedException error) { throw new AssertionError(error); }
            return new Thread(() -> { started.countDown(); target.run(); });
        });
        pool.setExecuteExistingDelayedTasksAfterShutdownPolicy(false);
        Thread caller = new Thread(() -> {
            try { future.set(pool.schedule(calls::incrementAndGet, 1, TimeUnit.DAYS)); }
            catch (Throwable error) { failure.set(error); }
        });
        try {
            caller.start(); await(entered, "factory-not-entered");
            pool.shutdown();
            require(!pool.isTerminated(), "graceful-retired-during-factory");
            release.countDown(); caller.join(5000);
            require(!caller.isAlive() && failure.get() == null && future.get() != null
                && future.get().isCancelled(), "graceful-submission");
            await(started, "graceful-worker-not-started");
            require(pool.awaitTermination(5, TimeUnit.SECONDS) && calls.get() == 0, "graceful-retirement");
        } finally { release.countDown(); caller.join(5000); stop(pool); }
    }
    private static void recoverNested(boolean throwsFailure) throws Exception {
        var entered = new CountDownLatch(1);
        var release = new CountDownLatch(1);
        var attempts = new AtomicInteger();
        var callbacks = new AtomicInteger();
        var original = new IllegalStateException("factory-failure");
        var outer = new AtomicReference<ScheduledFuture<?>>();
        var error = new AtomicReference<Throwable>();
        var pool = new ScheduledThreadPoolExecutor(1, target -> {
            if (attempts.incrementAndGet() == 1) {
                entered.countDown();
                try { await(release, "factory-release"); }
                catch (InterruptedException interrupted) { throw new AssertionError(interrupted); }
                if (throwsFailure) throw original;
                return null;
            }
            return new Thread(target);
        });
        Thread caller = new Thread(() -> {
            try { outer.set(pool.schedule(callbacks::incrementAndGet, 0, TimeUnit.SECONDS)); }
            catch (Throwable failure) { error.set(failure); }
        });
        try {
            caller.start(); await(entered, "factory-not-entered");
            var nested = pool.schedule(callbacks::incrementAndGet, 0, TimeUnit.SECONDS);
            require(!nested.isDone() && attempts.get() == 1, "nested-owned");
            release.countDown(); caller.join(5000);
            require(!caller.isAlive() && (throwsFailure ? error.get() == original : error.get() == null),
                "factory-result");
            var recovery = pool.schedule(callbacks::incrementAndGet, 0, TimeUnit.SECONDS);
            nested.get(5, TimeUnit.SECONDS); recovery.get(5, TimeUnit.SECONDS);
            if (!throwsFailure) outer.get().get(5, TimeUnit.SECONDS);
            require(callbacks.get() == 3 && attempts.get() == 2, "accepted-work-lost");
        } finally { release.countDown(); caller.join(5000); stop(pool); }
    }
    public static void main(String[] args) throws Exception {
        admittedDuringFactory();
        withdrawnWhileFactoryRuns(false);
        withdrawnWhileFactoryRuns(true);
        gracefulPruned();
        recoverNested(false);
        recoverNested(true);
        System.out.println("SCHEDULED_FACTORY_CONCURRENCY PASS nested;shutdown;shutdown-throw;graceful-pruned;null-recovery;throw-recovery");
    }
}
