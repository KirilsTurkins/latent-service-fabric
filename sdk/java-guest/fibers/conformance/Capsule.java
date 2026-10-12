package dev.latent.app;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.CancellationException;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.time.Duration;
import java.time.temporal.ChronoUnit;
public final class Capsule {
    private static volatile boolean ready;
    private static final ThreadLocal<String> local = new ThreadLocal<>();
    public static volatile boolean lateFlush;
    public static final List<ExecutorService> referencePools = new ArrayList<>();

    private static final class MonitorProbe {
        private boolean released;
        synchronized int await() throws InterruptedException {
            while (!released) wait();
            return reentrant();
        }
        synchronized int reentrant() { return 20; }
        synchronized void release() { released = true; notifyAll(); }
        synchronized int fail() { throw new IllegalArgumentException("original-future-cause"); }
    }
    private static final class ClassMonitor {
        private static boolean released;
        static synchronized int await() throws InterruptedException {
            while (!released) ClassMonitor.class.wait();
            return 20;
        }
        static synchronized void release() { released = true; ClassMonitor.class.notifyAll(); }
    }
    private static final class Resettable extends FutureTask<Integer> {
        Resettable(java.util.concurrent.Callable<Integer> task) { super(task); }
        boolean again() { return runAndReset(); }
    }
    public Long run(Long mode) {
        if (mode == 1) return pools();
        if (mode == 2) return rootReturns();
        if (mode == 3) return cachedAndStandardWaits();
        local.set("root");
        Thread worker = new Thread(() -> {
            if (local.get() != null) throw new IllegalStateException("thread-local-leaked");
            local.set("worker");
            try { Thread.sleep(20); } catch (InterruptedException error) { throw new IllegalStateException(error); }
            ready = true;
        });
        if (worker.isAlive()) throw new IllegalStateException("unstarted-thread-alive");
        worker.start();
        while (!ready) { }
        try { worker.join(); } catch (InterruptedException error) { throw new IllegalStateException(error); }
        if (worker.isAlive() || !"root".equals(local.get())) throw new IllegalStateException("join-or-local");
        return 42L;
    }

    private static void require(boolean value) { if (!value) throw new IllegalStateException("concurrency-observable"); }
    private static Long pools() {
        ExecutorService first = Executors.newSingleThreadExecutor();
        ExecutorService second = Executors.newSingleThreadExecutor();
        ExecutorService parallel = Executors.newFixedThreadPool(2);
        MonitorProbe monitor = new MonitorProbe();
        Object rendezvous = new Object();
        local.set("root");
        try {
            Future<Integer> left = first.submit(() -> {
                require(local.get() == null);
                local.set("first");
                return monitor.await();
            });
            Future<Integer> right = second.submit(() -> {
                require(local.get() == null);
                local.set("second");
                Thread.sleep(20);
                monitor.release();
                return 22;
            });
            require(left.get() + right.get() == 42 && "root".equals(local.get()));
            require(first.submit(() -> "first".equals(local.get())).get());
            require(second.submit(() -> "second".equals(local.get())).get());

            Future<Integer> failed = first.submit(monitor::fail);
            try { failed.get(); throw new IllegalStateException("future-exception-missing"); }
            catch (ExecutionException error) {
                require(error.getCause() instanceof IllegalArgumentException);
                require("original-future-cause".equals(error.getCause().getMessage()));
            }
            // Exception propagation releases the instance method's monitor.
            require(second.submit(monitor::reentrant).get() == 20);
            Future<Integer> staticLeft = first.submit(ClassMonitor::await);
            Future<Integer> staticRight = second.submit(() -> { ClassMonitor.release(); return 22; });
            require(staticLeft.get() + staticRight.get() == 42);

            boolean[] started = {false};
            boolean[] ended = {false};
            Future<Integer> cancelled = first.submit(() -> {
                synchronized (rendezvous) { started[0] = true; rendezvous.notifyAll(); }
                try { Thread.sleep(60_000); return 1; }
                finally { synchronized (rendezvous) { ended[0] = true; rendezvous.notifyAll(); } }
            });
            synchronized (rendezvous) { while (!started[0]) rendezvous.wait(); }
            require(cancelled.cancel(true) && cancelled.isDone() && cancelled.isCancelled());
            try { cancelled.get(); throw new IllegalStateException("future-cancel-missing"); }
            catch (CancellationException expected) { }
            require(first.submit(() -> ended[0] && !Thread.currentThread().isInterrupted()).get());

            boolean[] gate = {false};
            Future<Integer> timed = first.submit(() -> {
                synchronized (rendezvous) { while (!gate[0]) rendezvous.wait(); }
                return 42;
            });
            try { timed.get(1, TimeUnit.MICROSECONDS); throw new IllegalStateException("future-timeout-missing"); }
            catch (TimeoutException expected) { }
            try { timed.get(Long.MIN_VALUE, TimeUnit.NANOSECONDS); throw new IllegalStateException("negative-timeout-missing"); }
            catch (TimeoutException expected) { }
            synchronized (rendezvous) { gate[0] = true; rendezvous.notifyAll(); }
            require(timed.get() == 42);
            Thread.currentThread().interrupt();
            require(timed.get() == 42 && Thread.currentThread().isInterrupted());
            require(Thread.interrupted());

            boolean[] callbackEntered = {false};
            boolean[] callbackReleased = {false};
            FutureTask<Integer> callback = new FutureTask<>(() -> 42) {
                @Override protected void done() {
                    synchronized (rendezvous) {
                        callbackEntered[0] = true;
                        rendezvous.notifyAll();
                        try { while (!callbackReleased[0]) rendezvous.wait(); }
                        catch (InterruptedException error) { throw new IllegalStateException(error); }
                    }
                }
            };
            first.execute(callback);
            synchronized (rendezvous) { while (!callbackEntered[0]) rendezvous.wait(); }
            // Future completion is readable even while done() itself is blocked.
            require(callback.get() == 42 && callback.resultNow() == 42);
            require(callback.state() == Future.State.SUCCESS);
            synchronized (rendezvous) { callbackReleased[0] = true; rendezvous.notifyAll(); }
            require(first.submit(() -> 42).get() == 42);

            require(parallel.<Integer>invokeAny(Arrays.asList(
                () -> { Thread.sleep(60_000); return 1; }, () -> 42)) == 42);
            List<Future<Integer>> ordered = parallel.invokeAll(Arrays.asList(() -> 20, () -> 22));
            require(ordered.get(0).get() + ordered.get(1).get() == 42);
            require(TimeUnit.DAYS.toNanos(Long.MAX_VALUE) == Long.MAX_VALUE);
            require(TimeUnit.DAYS.toNanos(Long.MIN_VALUE) == Long.MIN_VALUE);
            require(TimeUnit.MILLISECONDS.convert(999_999, TimeUnit.NANOSECONDS) == 0);
            return 42L;
        } catch (InterruptedException | ExecutionException error) { throw new IllegalStateException(error); }
        finally { first.close(); second.close(); parallel.close(); }
    }

    private static Long rootReturns() {
        ExecutorService idle = Executors.newSingleThreadExecutor();
        ExecutorService pending = Executors.newSingleThreadExecutor();
        referencePools.add(idle);
        referencePools.add(pending);
        try { require(idle.submit(() -> 1).get() == 1); }
        catch (InterruptedException | ExecutionException error) { throw new IllegalStateException(error); }
        pending.execute(() -> {
            try { Thread.sleep(30); }
            catch (InterruptedException error) { throw new IllegalStateException(error); }
            // An accepted pending task may still submit its necessary flush to
            // the otherwise idle pool after the original root has returned.
            idle.execute(() -> lateFlush = true);
        });
        // The activation retires idle pools and drains the accepted pending task
        // after this return. The application supplies no shutdown hook.
        return 42L;
    }

    private static Long cachedAndStandardWaits() {
        try {
            require(TimeUnit.NANOSECONDS.convert(Duration.ofSeconds(-1, 999_999_999)) == -1);
            require(TimeUnit.MICROSECONDS.convert(Duration.ofSeconds(-1, 999_999_999)) == 0);
            require(TimeUnit.SECONDS.convert(Duration.ofSeconds(-2, 500_000_000)) == -1);
            require(TimeUnit.NANOSECONDS.convert(Duration.ofSeconds(Long.MAX_VALUE)) == Long.MAX_VALUE);
            require(TimeUnit.NANOSECONDS.convert(Duration.ofSeconds(Long.MIN_VALUE)) == Long.MIN_VALUE);
            for (TimeUnit unit : TimeUnit.values()) require(TimeUnit.of(unit.toChronoUnit()) == unit);
            try { TimeUnit.of(ChronoUnit.MONTHS); throw new IllegalStateException("unsupported-time-unit-missing"); }
            catch (IllegalArgumentException expected) { }

            int[] repetitions = {0};
            Resettable repeated = new Resettable(() -> ++repetitions[0]);
            require(repeated.again() && repeated.again() && !repeated.isDone());
            repeated.run();
            require(repeated.get() == 3 && !repeated.again());
            Resettable failed = new Resettable(() -> { throw new IllegalArgumentException("reset-cause"); });
            require(!failed.again() && failed.isDone());
            try { failed.get(); throw new IllegalStateException("reset-error-missing"); }
            catch (ExecutionException error) { require(error.getCause() instanceof IllegalArgumentException); }

            Thread unstarted = new Thread(() -> { });
            Thread.currentThread().interrupt();
            unstarted.join();
            require(Thread.currentThread().isInterrupted());
            try { Thread.sleep(-1); throw new IllegalStateException("negative-sleep-missing"); }
            catch (IllegalArgumentException expected) { require(Thread.currentThread().isInterrupted()); }
            try { Thread.sleep(0); throw new IllegalStateException("interrupted-sleep-missing"); }
            catch (InterruptedException expected) { require(!Thread.currentThread().isInterrupted()); }
            Thread.sleep(0, 1);
            Object validation = new Object();
            try { validation.wait(-1, 0); throw new IllegalStateException("negative-wait-missing"); }
            catch (IllegalArgumentException expected) { }
            synchronized (validation) {
                try { validation.wait(0, 1_000_000); throw new IllegalStateException("nanos-wait-missing"); }
                catch (IllegalArgumentException expected) { }
            }

            Object rendezvous = new Object();
            boolean[] release = {false};
            ExecutorService cached = Executors.newCachedThreadPool();
            referencePools.add(cached);
            Future<Integer> first = cached.submit(() -> {
                synchronized (rendezvous) { while (!release[0]) rendezvous.wait(); }
                return 20;
            });
            Future<Integer> second = cached.submit(() -> {
                synchronized (rendezvous) { release[0] = true; rendezvous.notifyAll(); }
                return 22;
            });
            require(first.get() + second.get() == 42);
            // The activation retires idle cached workers. This unchanged source
            // intentionally supplies no application shutdown hook.
            return 42L;
        } catch (InterruptedException | ExecutionException error) { throw new IllegalStateException(error); }
    }
}
