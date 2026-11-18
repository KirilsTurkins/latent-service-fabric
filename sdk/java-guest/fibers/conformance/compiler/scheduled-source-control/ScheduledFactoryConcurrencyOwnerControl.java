import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.ScheduledThreadPoolExecutor;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Actual scheduler source with a fault-injecting private owner ledger. */
public final class ScheduledFactoryConcurrencyOwnerControl {
    private static void require(boolean value, String label) { if (!value) throw new AssertionError(label); }
    private static void await(CountDownLatch latch, String label) throws InterruptedException {
        require(latch.await(5, TimeUnit.SECONDS), label);
    }
    private static void held(int queue, int result, int executor) {
        require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == queue
            && Activation.count(LatentRuntimeActivationOwnerKind.Result) == result
            && Activation.count(LatentRuntimeActivationOwnerKind.Executor) == executor, "owners");
    }
    private static void shutdown(boolean deny) throws Exception {
        var entered = new CountDownLatch(1);
        var release = new CountDownLatch(1);
        var target = new AtomicReference<Runnable>();
        var created = new AtomicReference<Thread>();
        var result = new AtomicReference<ScheduledFuture<?>>();
        var error = new AtomicReference<Throwable>();
        var calls = new AtomicInteger();
        var pool = new ScheduledThreadPoolExecutor(1, runnable -> {
            target.set(runnable); entered.countDown();
            try { await(release, "factory-release"); }
            catch (InterruptedException interrupted) { throw new AssertionError(interrupted); }
            Thread thread = new Thread(runnable); created.set(thread); return thread;
        });
        Thread caller = new Thread(() -> {
            try { result.set(pool.schedule(calls::incrementAndGet, 1, TimeUnit.DAYS)); }
            catch (Throwable failure) { error.set(failure); }
        });
        try {
            caller.start(); await(entered, "factory-not-entered"); held(1, 1, 1);
            require(pool.hasPendingWork(), "reservation-not-pending");
            if (deny) Activation.denyCloseNext = "QueuedWork";
            if (deny) {
                try { pool.shutdownNow(); throw new AssertionError("settlement-not-refused"); }
                catch (IllegalStateException expected) { }
                require(Activation.poisoned && Activation.retainsFailedQueued()
                    && Activation.failedLeaseAttempts() == 1, "failed-settlement");
                held(1, 0, 1);
            } else {
                List<Runnable> removed = pool.shutdownNow();
                require(removed.size() == 1 && !pool.isTerminated() && pool.hasPendingWork(), "early-retirement");
                held(0, 0, 1);
                release.countDown(); caller.join(5000);
                require(!caller.isAlive() && error.get() == null && result.get() == removed.get(0)
                    && pool.awaitTermination(5, TimeUnit.SECONDS), "submission");
                require(created.get() != null && created.get().getState() == Thread.State.NEW, "worker-started-after-stop");
                target.get().run();
                require(calls.get() == 0, "withdrawn-work-ran");
                held(0, 0, 0); result.get().cancel(false); Activation.idle();
            }
        } finally { release.countDown(); caller.join(5000); }
        if (deny) {
            require(!caller.isAlive() && Activation.poisoned && !pool.isTerminated()
                && pool.hasPendingWork() && Activation.failedLeaseAttempts() == 1, "uncertain-owner-lost");
            held(1, 0, 1);
        }
    }
    private static void claimedBeforeStartFailure() throws Exception {
        var firstEntered = new CountDownLatch(1);
        var firstRelease = new CountDownLatch(1);
        var secondFactory = new CountDownLatch(1);
        var factoryRelease = new CountDownLatch(1);
        var secondRan = new CountDownLatch(1);
        var attempts = new AtomicInteger();
        var marker = new IllegalStateException("start-failure");
        var error = new AtomicReference<Throwable>();
        var pool = new ScheduledThreadPoolExecutor(2, target -> {
            if (attempts.incrementAndGet() == 1) return new Thread(target);
            secondFactory.countDown();
            try { await(factoryRelease, "factory-release"); }
            catch (InterruptedException interrupted) { throw new AssertionError(interrupted); }
            return new Thread(target) { @Override public synchronized void start() { throw marker; } };
        });
        var first = pool.submit(() -> {
            firstEntered.countDown();
            try { await(firstRelease, "first-release"); }
            catch (InterruptedException interrupted) { throw new AssertionError(interrupted); }
        });
        Thread caller = new Thread(() -> {
            try { pool.submit(secondRan::countDown); throw new AssertionError("missing-start-failure"); }
            catch (Throwable failure) { error.set(failure); }
        });
        try {
            await(firstEntered, "first-not-running");
            caller.start(); await(secondFactory, "second-factory-not-entered");
            held(2, 2, 1);
            firstRelease.countDown(); await(secondRan, "second-not-claimed");
            first.get(5, TimeUnit.SECONDS);
            long until = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
            while (Activation.count(LatentRuntimeActivationOwnerKind.Result) != 0 && System.nanoTime() < until)
                Thread.yield();
            held(0, 0, 1); require(pool.hasPendingWork(), "factory-reservation-not-pending");
            factoryRelease.countDown(); caller.join(5000);
            require(!caller.isAlive() && error.get() == marker, "original-start-failure");
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS), "termination");
            held(0, 0, 0); Activation.idle();
        } finally { firstRelease.countDown(); factoryRelease.countDown(); caller.join(5000); pool.shutdownNow(); }
    }
    private static void replacementFactory() throws Exception {
        var selected = new AtomicReference<ScheduledThreadPoolExecutor>();
        var firstEntered = new CountDownLatch(1);
        var firstRelease = new CountDownLatch(1);
        var nestedAccepted = new CountDownLatch(1);
        var nestedRan = new CountDownLatch(1);
        var workerFailure = new AtomicReference<Throwable>();
        var helperFailure = new AtomicReference<Throwable>();
        var attempts = new AtomicInteger();
        var marker = new IllegalStateException("synthetic-queue-read-failure");
        var pool = new ScheduledThreadPoolExecutor(1, target -> {
            if (attempts.incrementAndGet() == 1) {
                Thread worker = new Thread(target);
                worker.setUncaughtExceptionHandler((thread, error) -> workerFailure.set(error));
                return worker;
            }
            Thread helper = new Thread(() -> {
                try { selected.get().execute(nestedRan::countDown); }
                catch (Throwable error) { helperFailure.set(error); }
                finally { nestedAccepted.countDown(); }
            });
            helper.start();
            try { await(nestedAccepted, "replacement-nested-admission"); }
            catch (InterruptedException error) { throw new AssertionError(error); }
            return new Thread(target);
        });
        selected.set(pool);
        var first = pool.submit(() -> {
            firstEntered.countDown();
            try { await(firstRelease, "first-release"); }
            catch (InterruptedException error) { throw new AssertionError(error); }
        });
        try {
            await(firstEntered, "first-not-entered");
            class FailingQueue extends java.util.ArrayList<Object> {
                int reads;
                @Override public Object get(int index) {
                    // Let the completed first task's cleanup inspect the
                    // delayed entry, then fail its subsequent queue selection.
                    if (++reads == 2) throw marker;
                    return super.get(index);
                }
            }
            var field = pool.getClass().getDeclaredField("queue"); field.setAccessible(true);
            var original = (java.util.ArrayList<?>)field.get(pool);
            require(original.isEmpty(), "unexpected-queue");
            field.set(pool, new FailingQueue());
            var delayed = pool.schedule(() -> { throw new AssertionError("delayed-ran"); }, 1, TimeUnit.DAYS);
            firstRelease.countDown(); await(nestedRan, "replacement-nested-not-run");
            first.get(5, TimeUnit.SECONDS);
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
            while (workerFailure.get() == null && System.nanoTime() < deadline) Thread.yield();
            require(workerFailure.get() == marker && helperFailure.get() == null && attempts.get() == 2,
                "replacement-factory-outcome");
            List<Runnable> removed = pool.shutdownNow();
            boolean terminated = pool.awaitTermination(5, TimeUnit.SECONDS);
            require(removed.size() == 1 && removed.get(0) == delayed && terminated,
                "replacement-retirement count=" + removed.size() + " terminated=" + terminated
                    + " pending=" + pool.hasPendingWork()
                    + " queue=" + Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork)
                    + " result=" + Activation.count(LatentRuntimeActivationOwnerKind.Result)
                    + " executor=" + Activation.count(LatentRuntimeActivationOwnerKind.Executor));
            delayed.cancel(false); held(0, 0, 0); Activation.idle();
        } finally { firstRelease.countDown(); pool.shutdownNow(); }
    }
    private static void uncertainStart() throws Exception {
        var target = new AtomicReference<Runnable>();
        var selected = new AtomicReference<Thread>();
        var starts = new AtomicInteger();
        var calls = new AtomicInteger();
        var marker = new IllegalStateException("uncertain-start");
        var pool = new ScheduledThreadPoolExecutor(1, runnable -> {
            target.set(runnable);
            Thread thread = new Thread(runnable) {
                @Override public synchronized void start() {
                    if (starts.incrementAndGet() == 1) throw marker;
                    super.start();
                }
            };
            selected.set(thread);
            return thread;
        });
        Activation.retainFailedStart = true;
        try {
            try { pool.schedule(calls::incrementAndGet, 1, TimeUnit.DAYS); throw new AssertionError("missing-start-failure"); }
            catch (IllegalStateException expected) { require(expected == marker, "wrong-start-failure"); }
            held(0, 0, 1);
            require(Activation.ownsManaged(selected.get(), pool) && !pool.isTerminated(), "uncertain-worker-not-retained");
            require(pool.shutdownNow().isEmpty() && !pool.isTerminated(), "uncertain-worker-retired");
            selected.get().start(); selected.get().join(5000);
            require(!selected.get().isAlive() && pool.awaitTermination(5, TimeUnit.SECONDS), "uncertain-worker-not-finished");
            target.get().run();
            require(calls.get() == 0, "retained-target-ran-after-retirement");
            held(0, 0, 0); Activation.idle();
        } finally { Activation.retainFailedStart = false; pool.shutdownNow(); }
    }
    private static void gracefulStartFailure(String mode) throws Exception {
        var entered = new CountDownLatch(1);
        var release = new CountDownLatch(1);
        var failure = new AtomicReference<Throwable>();
        var marker = new IllegalStateException("start-failure");
        var pool = new ScheduledThreadPoolExecutor(1, target -> {
            entered.countDown();
            try { await(release, "factory-release"); }
            catch (InterruptedException interrupted) { throw new AssertionError(interrupted); }
            return new Thread(target) { @Override public synchronized void start() { throw marker; } };
        });
        Thread caller = new Thread(() -> {
            try { pool.schedule(() -> {}, 1, TimeUnit.DAYS); throw new AssertionError("missing-start-failure"); }
            catch (Throwable error) { failure.set(error); }
        });
        try {
            caller.start(); await(entered, "factory-not-entered"); held(1, 1, 1);
            pool.shutdown();
            require(!pool.isTerminated() && pool.hasPendingWork(), "early-retirement");
            if (mode.equals("denied")) Activation.denyCloseNext = "Executor";
            if (mode.equals("lost")) Activation.loseCloseAckNext = "Executor";
            release.countDown(); caller.join(5000);
            require(!caller.isAlive() && failure.get() == marker, "wrong-failure");
            if (mode.equals("ok")) {
                held(0, 0, 0);
                require(pool.isTerminated() && pool.awaitTermination(5, TimeUnit.SECONDS), "missing-executor-retirement");
                Activation.idle();
            } else {
                held(0, 0, mode.equals("denied") ? 1 : 0);
                require(!pool.isTerminated() && Activation.poisoned && Activation.retainsFailedQueued()
                    && Activation.failedLeaseAttempts() == 1, "failed-owner-not-fenced");
                pool.shutdownNow();
                require(Activation.failedLeaseAttempts() == 1 && !pool.isTerminated(), "failed-owner-retried");
            }
        } finally { release.countDown(); caller.join(5000); pool.shutdownNow(); }
    }
    private static void manualPeriodicCancellation() throws Exception {
        var entered = new CountDownLatch(1);
        var release = new CountDownLatch(1);
        var attempts = new AtomicInteger();
        var error = new AtomicReference<Throwable>();
        var calls = new AtomicInteger();
        var pool = new ScheduledThreadPoolExecutor(1, target -> {
            if (attempts.incrementAndGet() == 1) return null;
            entered.countDown();
            try { await(release, "factory-release"); }
            catch (InterruptedException interrupted) { throw new AssertionError(interrupted); }
            return new Thread(target);
        });
        var future = pool.scheduleAtFixedRate(calls::incrementAndGet, 1, 1, TimeUnit.DAYS);
        Thread manual = new Thread(() -> { try { ((Runnable)future).run(); } catch (Throwable failure) { error.set(failure); } });
        try {
            manual.start(); await(entered, "manual-factory-not-entered"); held(2, 1, 1);
            require(future.cancel(false), "periodic-not-cancelled");
            held(0, 1, 1);
            require(pool.shutdownNow().isEmpty() && !pool.isTerminated() && pool.hasPendingWork(), "early-retirement");
            release.countDown(); manual.join(5000);
            require(!manual.isAlive() && error.get() == null && calls.get() == 1
                && pool.awaitTermination(5, TimeUnit.SECONDS), "manual-retirement");
            held(0, 0, 0); Activation.idle();
        } finally { release.countDown(); manual.join(5000); pool.shutdownNow(); }
    }
    public static void main(String[] args) throws Exception {
        switch (args[0]) {
            case "shutdown" -> shutdown(false);
            case "denied" -> shutdown(true);
            case "claim" -> claimedBeforeStartFailure();
            case "replacement" -> replacementFactory();
            case "uncertain-start" -> uncertainStart();
            case "graceful-failure" -> gracefulStartFailure("ok");
            case "graceful-denied" -> gracefulStartFailure("denied");
            case "graceful-lost" -> gracefulStartFailure("lost");
            case "manual" -> manualPeriodicCancellation();
            default -> throw new IllegalArgumentException("mode");
        }
        System.out.println("SCHEDULED_FACTORY_CONCURRENCY_OWNER PASS " + args[0]);
    }
}
