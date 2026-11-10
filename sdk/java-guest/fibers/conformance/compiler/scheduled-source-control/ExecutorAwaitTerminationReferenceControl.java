import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Reference JDK and source-port observations; no guest execution is implied. */
public final class ExecutorAwaitTerminationReferenceControl {
    private record Observation(String result, boolean interrupted) { }
    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    private static ExecutorService pool(boolean scheduled) {
        return scheduled ? Executors.newScheduledThreadPool(1) : Executors.newFixedThreadPool(1);
    }
    private static Observation observe(boolean scheduled, long nanos, boolean terminated) throws Exception {
        ExecutorService executor = pool(scheduled);
        try {
            if (terminated) {
                executor.shutdown();
                require(executor.awaitTermination(5, TimeUnit.SECONDS), "pool did not terminate");
            }
            Thread.currentThread().interrupt();
            try {
                return new Observation("returned=" + executor.awaitTermination(nanos, TimeUnit.NANOSECONDS),
                    Thread.currentThread().isInterrupted());
            } catch (InterruptedException expected) {
                return new Observation("InterruptedException", Thread.currentThread().isInterrupted());
            } finally { Thread.interrupted(); }
        } finally {
            executor.shutdownNow();
            require(executor.awaitTermination(5, TimeUnit.SECONDS), "cleanup did not terminate");
        }
    }
    private static void interruptWaiting(boolean scheduled) throws Exception {
        ExecutorService executor = pool(scheduled);
        AtomicReference<String> outcome = new AtomicReference<>("not-finished");
        Thread waiter = new Thread(() -> {
            try { executor.awaitTermination(1, TimeUnit.DAYS); outcome.set("unexpected-return"); }
            catch (InterruptedException error) {
                outcome.set(Thread.currentThread().isInterrupted() ? "interrupt-not-cleared" : "interrupted");
            }
        }, "termination-interrupt-waiter");
        try {
            waiter.start();
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
            while (waiter.getState() != Thread.State.TIMED_WAITING) {
                require(waiter.isAlive() && System.nanoTime() - deadline < 0, "waiter did not block");
                Thread.yield();
            }
            waiter.interrupt();
            waiter.join(5000);
            require(!waiter.isAlive() && "interrupted".equals(outcome.get()), "waiter " + outcome.get());
        } finally {
            executor.shutdownNow();
            require(executor.awaitTermination(5, TimeUnit.SECONDS), "cleanup did not terminate");
            waiter.join(5000);
            require(!waiter.isAlive(), "waiter did not retire");
        }
    }
    private static final class MisreportedPool extends ScheduledThreadPoolExecutor {
        private final boolean reported;
        MisreportedPool(boolean reported, ThreadFactory factory) { super(1, factory); this.reported = reported; }
        @Override public boolean isTerminated() { return reported; }
    }
    private static void overriddenTermination() throws Exception {
        AtomicReference<Thread> worker = new AtomicReference<>();
        MisreportedPool live = new MisreportedPool(true, task -> {
            Thread thread = new Thread(task); worker.set(thread); return thread;
        });
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        try {
            live.execute(() -> {
                entered.countDown();
                try { if (!release.await(5,TimeUnit.SECONDS)) throw new AssertionError("callback-release"); }
                catch (InterruptedException error) { throw new AssertionError(error); }
            });
            require(entered.await(5,TimeUnit.SECONDS), "callback-not-entered");
            live.shutdown();
            require(!live.awaitTermination(0,TimeUnit.NANOSECONDS), "override-falsely-completed-zero");
            require(!live.awaitTermination(10,TimeUnit.MILLISECONDS), "override-falsely-completed-timed");
        } finally {
            release.countDown();
            live.shutdown();
            Thread thread = worker.get();
            if (thread != null) { thread.join(5000); require(!thread.isAlive(), "live-worker-not-retired"); }
        }
        MisreportedPool retired = new MisreportedPool(false, Thread::new);
        retired.shutdown();
        require(retired.awaitTermination(0,TimeUnit.NANOSECONDS), "override-hid-retirement-zero");
        require(retired.awaitTermination(10,TimeUnit.MILLISECONDS), "override-hid-retirement-timed");
    }
    public static void main(String[] args) throws Exception {
        for (boolean scheduled : new boolean[] {false, true}) {
            for (boolean terminated : new boolean[] {false, true}) {
                for (long nanos : new long[] {-1, 0, 1, TimeUnit.SECONDS.toNanos(10)}) {
                    Observation expected = terminated ? new Observation("returned=true", true)
                        : nanos <= 0 ? new Observation("returned=false", true)
                        : new Observation("InterruptedException", false);
                    Observation actual = observe(scheduled, nanos, terminated);
                    require(expected.equals(actual), "scheduled=" + scheduled + " terminated=" + terminated
                        + " nanos=" + nanos + " expected=" + expected + " actual=" + actual);
                }
            }
            interruptWaiting(scheduled);
        }
        overriddenTermination();
        if (args.length == 1 && args[0].equals("source"))
            Class.forName("dev.latent.guest.runtime.Activation").getMethod("idle").invoke(null);
        System.out.println("EXECUTOR_AWAIT_TERMINATION PASS zero;negative;positive;terminated;blocked-interrupt;override");
    }
}
