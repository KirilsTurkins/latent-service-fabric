import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.FutureTask;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Pinned JDK comparison; source-control imports alone select the SDK bodies. */
public final class FutureTaskMonitorReferenceControl {
    private interface Action { void run() throws Exception; }
    private static void held(Object monitor, Action action) throws Exception {
        CountDownLatch entered = new CountDownLatch(1), done = new CountDownLatch(1);
        AtomicReference<Throwable> failure = new AtomicReference<>();
        Thread worker = new Thread(() -> {
            entered.countDown();
            try { action.run(); } catch (Throwable error) { failure.set(error); }
            finally { done.countDown(); }
        });
        boolean complete;
        try {
            synchronized (monitor) {
                worker.start();
                if (!entered.await(2, TimeUnit.SECONDS)) throw new AssertionError("worker-not-entered");
                complete = done.await(3, TimeUnit.SECONDS);
            }
        } finally { worker.join(5000); }
        if (worker.isAlive() || failure.get() != null) throw new AssertionError("operation-failed", failure.get());
        if (!complete) throw new AssertionError("future-public-monitor-blocked");
    }
    // ExecutionException(Throwable) calls the supplied cause's toString().
    // A getter must not retain an internal monitor across that user callback.
    private static void failedGetCallback(boolean timed) throws Exception {
        CountDownLatch callback = new CountDownLatch(1), release = new CountDownLatch(1);
        CountDownLatch held = new CountDownLatch(1), inspect = new CountDownLatch(1), inspected = new CountDownLatch(1);
        AtomicReference<Throwable> threadFailure = new AtomicReference<>();
        Throwable cause = new RuntimeException() {
            @Override public String toString() {
                callback.countDown();
                try {
                    if (!release.await(5, TimeUnit.SECONDS)) throw new AssertionError("exception-callback-timeout");
                } catch (InterruptedException error) { throw new AssertionError(error); }
                return "controlled-exception";
            }
        };
        FutureTask<Integer> future = new FutureTask<>(() -> { throw (RuntimeException) cause; });
        future.run();
        Thread holder = new Thread(() -> {
            synchronized (future) {
                held.countDown();
                try {
                    if (!inspect.await(5, TimeUnit.SECONDS)) throw new AssertionError("inspection-timeout");
                    if (!future.isDone()) throw new AssertionError("failure-not-completed");
                } catch (Throwable error) { threadFailure.set(error); }
                finally { inspected.countDown(); }
            }
        }, "exception-future-holder");
        Thread getter = new Thread(() -> {
            try {
                if (timed) future.get(0, TimeUnit.NANOSECONDS); else future.get();
                threadFailure.set(new AssertionError("failed-get-returned"));
            } catch (java.util.concurrent.ExecutionException error) {
                if (error.getCause() != cause) threadFailure.set(new AssertionError("wrong-failure-cause"));
            } catch (Throwable error) { threadFailure.set(error); }
        }, "exception-future-getter");
        boolean independent = false;
        try {
            holder.start();
            if (!held.await(5, TimeUnit.SECONDS)) throw new AssertionError("future-monitor-not-held");
            getter.start();
            if (!callback.await(5, TimeUnit.SECONDS)) throw new AssertionError("exception-callback-not-entered");
            inspect.countDown();
            independent = inspected.await(1, TimeUnit.SECONDS);
        } finally {
            inspect.countDown(); release.countDown();
            holder.join(5000); getter.join(5000);
        }
        if (holder.isAlive() || getter.isAlive() || threadFailure.get() != null)
            throw new AssertionError("exception-get-control-failed", threadFailure.get());
        if (!independent) throw new AssertionError("future-state-locked-by-exception-callback");
    }
    public static void main(String[] args) throws Exception {
        failedGetCallback(false);
        failedGetCallback(true);
        FutureTask<Integer> run = new FutureTask<>(() -> 42);
        held(run, run::run);
        if (run.get() != 42) throw new AssertionError("run-result");
        held(run, () -> { if (run.get() != 42) throw new AssertionError("completed-get"); });
        FutureTask<Integer> cancelled = new FutureTask<>(() -> 42);
        held(cancelled, () -> { if (!cancelled.cancel(false)) throw new AssertionError("cancel-result"); });
        ExecutorService executor = Executors.newSingleThreadExecutor();
        try {
            FutureTask<Integer> queued = new FutureTask<>(() -> 42);
            held(queued, () -> { executor.execute(queued); if (queued.get() != 42) throw new AssertionError("queued-result"); });
        } finally {
            executor.shutdownNow();
            if (!executor.awaitTermination(5,TimeUnit.SECONDS)) throw new AssertionError("executor-not-retired");
        }
        ScheduledThreadPoolExecutor scheduled = new ScheduledThreadPoolExecutor(1);
        try {
            ScheduledFuture<?> future = scheduled.schedule(() -> { throw new AssertionError("cancelled-task-ran"); },
                                                           60, TimeUnit.SECONDS);
            held(future, () -> { if (!future.cancel(false)) throw new AssertionError("scheduled-cancel"); });
        } finally {
            scheduled.shutdownNow();
            if (!scheduled.awaitTermination(5,TimeUnit.SECONDS)) throw new AssertionError("scheduled-not-retired");
        }
        System.out.println("FUTURE_TASK_MONITOR_REFERENCE PASS run;cancel;completed-get;executor;scheduled-cancel;failed-get-callback");
    }
}
