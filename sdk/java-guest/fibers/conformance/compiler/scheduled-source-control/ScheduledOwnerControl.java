import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Actual maintained source, with deterministic callback/publication barriers. */
public final class ScheduledOwnerControl {
    private static void require(boolean value) { if (!value) throw new AssertionError("scheduled-owner-control"); }
    private static void await(CountDownLatch latch) throws InterruptedException { require(latch.await(5, TimeUnit.SECONDS)); }
    private static void held(int queued, int results) {
        require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == queued);
        require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == results);
    }
    private static void finish(ScheduledThreadPoolExecutor pool) throws InterruptedException {
        pool.shutdownNow();
        require(pool.awaitTermination(5, TimeUnit.SECONDS));
        Activation.idle();
    }
    private static void waiting(Thread worker) {
        long started = System.nanoTime();
        while (worker.getState() != Thread.State.TIMED_WAITING) {
            require(worker.isAlive() && System.nanoTime() - started < TimeUnit.SECONDS.toNanos(5));
            Thread.yield();
        }
    }
    private static Object capturedPool(Runnable target) throws Exception {
        // The factory deliberately retains the actual Runnable after the thread
        // exits, matching the pinned TeaVM Thread target lifetime.
        var capture = target.getClass().getDeclaredFields()[0]; capture.setAccessible(true);
        Object worker = capture.get(target);
        var pool = worker.getClass().getDeclaredField("pool"); pool.setAccessible(true);
        return pool.get(worker);
    }
    private static void clearedWorkerTarget(Runnable target) throws Exception {
        require(capturedPool(target) == null);
        target.run(); // A retained target is inert after retirement.
    }
    private static void rejectedWorkerTargets() throws Exception {
        for (boolean uncertain : new boolean[]{false, true}) {
            AtomicReference<Runnable> target = new AtomicReference<>();
            var failure = new IllegalThreadStateException("source-start-failure");
            var pool = new ScheduledThreadPoolExecutor(1, task -> {
                target.set(task);
                return new Thread(task) { @Override public void start() { throw failure; } };
            });
            // This private fake selects the Activation.alive result; the real
            // Activation control separately checks the owner and Work ledger.
            Activation.retainFailedStart = uncertain;
            try {
                try { pool.schedule(() -> 42, 0, TimeUnit.NANOSECONDS); throw new AssertionError("expected-start-failure"); }
                catch (IllegalThreadStateException error) { require(error == failure); }
                require((capturedPool(target.get()) != null) == uncertain);
            } finally { Activation.retainFailedStart = false; }
            finish(pool);
        }
    }
    private static void workerTargets() throws Exception {
        AtomicReference<Runnable> target = new AtomicReference<>();
        AtomicReference<Thread> worker = new AtomicReference<>();
        java.util.concurrent.ThreadFactory factory = runnable -> {
            target.set(runnable); Thread thread = new Thread(runnable); worker.set(thread); return thread;
        };
        var executor = dev.latent.guest.runtime.concurrent.Executors.newSingleThreadExecutor(factory);
        CountDownLatch ran = new CountDownLatch(1); executor.execute(ran::countDown); await(ran);
        executor.shutdown(); require(executor.awaitTermination(5, TimeUnit.SECONDS));
        worker.get().join(5000); require(!worker.get().isAlive()); clearedWorkerTarget(target.get()); Activation.idle();
        target.set(null); worker.set(null);
        var scheduled = new ScheduledThreadPoolExecutor(1, factory);
        require(scheduled.schedule(() -> 42, 0, TimeUnit.NANOSECONDS).get(5, TimeUnit.SECONDS) == 42);
        scheduled.shutdown(); require(scheduled.awaitTermination(5, TimeUnit.SECONDS));
        worker.get().join(5000); require(!worker.get().isAlive()); clearedWorkerTarget(target.get()); Activation.idle();
    }
    public static void main(String[] arguments) throws Exception {
        ScheduledThreadPoolExecutor pool = new ScheduledThreadPoolExecutor(1);
        for (String denied : new String[]{"QueuedWork", "Result"}) {
            Activation.denyNext = denied;
            try { pool.schedule(() -> { throw new AssertionError("unadmitted-callback"); }, 0, TimeUnit.NANOSECONDS); throw new AssertionError(); }
            catch (IllegalStateException expected) { require(expected.getMessage().equals("source-owner-admission-denied")); }
            held(0, 0);
        }
        require(pool.schedule(() -> 42, -1, TimeUnit.NANOSECONDS).get(5, TimeUnit.SECONDS) == 42);
        finish(pool);

        pool = new ScheduledThreadPoolExecutor(2);
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        var active = pool.scheduleAtFixedRate(() -> {
            entered.countDown();
            boolean interrupted = false;
            while (true) {
                try { release.await(); break; }
                catch (InterruptedException expected) { interrupted = true; }
            }
            if (interrupted) Thread.currentThread().interrupt();
        }, 0, 1, TimeUnit.NANOSECONDS);
        await(entered); held(1, 1);
        require(active.cancel(false) && active.isDone() && active.isCancelled());
        held(1, 1); // Cancellation cannot refund the physically running callback.
        release.countDown();
        finish(pool);

        pool = new ScheduledThreadPoolExecutor(2);
        CountDownLatch twice = new CountDownLatch(2);
        AtomicInteger concurrent = new AtomicInteger(), calls = new AtomicInteger();
        var recurring = pool.scheduleWithFixedDelay(() -> {
            require(concurrent.incrementAndGet() == 1);
            calls.incrementAndGet(); twice.countDown(); concurrent.decrementAndGet();
        }, 0, 1, TimeUnit.NANOSECONDS);
        await(twice); require(calls.get() >= 2);
        recurring.cancel(false); finish(pool);

        pool = new ScheduledThreadPoolExecutor(1);
        var original = new IllegalArgumentException("original-periodic-callback-error");
        AtomicInteger failures = new AtomicInteger();
        var failure = pool.scheduleAtFixedRate(() -> { failures.incrementAndGet(); throw original; }, 0, 1, TimeUnit.NANOSECONDS);
        try { failure.get(5, TimeUnit.SECONDS); throw new AssertionError(); }
        catch (ExecutionException expected) { require(expected.getCause() == original); }
        finish(pool);
        require(failures.get() == 1); // Exceptional periodic execution is not rescheduled.

        for (boolean interrupt : new boolean[]{false, true}) {
            AtomicReference<Thread> actual = new AtomicReference<>();
            pool = new ScheduledThreadPoolExecutor(1, task -> {
                Thread worker = new Thread(task); actual.set(worker); return worker;
            });
            var waiting = pool.schedule(() -> { throw new AssertionError("cancelled-delayed-callback"); }, 1, TimeUnit.DAYS);
            waiting(actual.get()); held(1, 1); // Actual timed monitor wait, not a delay-as-barrier.
            if (interrupt) {
                require(pool.shutdownNow().contains(waiting));
                require(!waiting.isDone());
                waiting.cancel(false);
            } else require(waiting.cancel(false));
            finish(pool);
            actual.get().join(5000);
            require(!actual.get().isAlive());
        }

        pool = new ScheduledThreadPoolExecutor(1);
        pool.setExecuteExistingDelayedTasksAfterShutdownPolicy(false);
        var delayed = pool.schedule(() -> { throw new AssertionError("shutdown-delayed-callback"); }, 1, TimeUnit.DAYS);
        pool.shutdown(); require(delayed.isCancelled());
        require(pool.awaitTermination(5, TimeUnit.SECONDS)); Activation.idle();

        pool = new ScheduledThreadPoolExecutor(1, task -> null);
        try { pool.schedule(() -> { throw new AssertionError("failed-worker-callback"); }, 0, TimeUnit.NANOSECONDS); throw new AssertionError(); }
        catch (java.util.concurrent.RejectedExecutionException expected) { held(0, 0); }
        finish(pool);
        workerTargets();
        rejectedWorkerTargets();
        System.out.println("SCHEDULED_OWNER_CONTROL PASS preadmission;actual-result;running-cancel-held;periodic-nonoverlap;original-error-suppresses-repeat;timed-wait-cancel-and-interrupt;shutdown-policy;factory-rollback;all-retired");
    }
}
