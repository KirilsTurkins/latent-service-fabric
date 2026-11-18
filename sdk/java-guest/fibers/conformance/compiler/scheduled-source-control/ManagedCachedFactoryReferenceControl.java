import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** JDK 25 and selected SDK observations; no component qualification. */
public final class ManagedCachedFactoryReferenceControl {
    private static void require(boolean value, String reason) { if (!value) throw new AssertionError(reason); }
    private static void await(CountDownLatch latch, String reason) throws InterruptedException {
        require(latch.await(5, TimeUnit.SECONDS), reason);
    }
    private static void stop(ExecutorService pool) throws InterruptedException {
        pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS), "pool-not-terminated");
    }
    private static void nestedAcrossFactory() throws Exception {
        var selected = new AtomicReference<ExecutorService>(); var nested = new AtomicReference<Future<?>>();
        var failure = new AtomicReference<Throwable>(); var accepted = new CountDownLatch(1);
        var nestedRan = new CountDownLatch(1); var attempts = new AtomicInteger(); var calls = new StringBuffer();
        var pool = Executors.newCachedThreadPool(target -> {
            if (attempts.incrementAndGet() == 1) {
                Thread helper = new Thread(() -> {
                    try { nested.set(selected.get().submit(() -> { calls.append('B'); nestedRan.countDown(); })); }
                    catch (Throwable error) { failure.set(error); }
                    finally { accepted.countDown(); }
                });
                helper.start();
                try { await(accepted, "nested-admission-blocked"); await(nestedRan, "nested-callback-blocked"); }
                catch (InterruptedException error) { throw new AssertionError(error); }
            }
            return new Thread(target);
        });
        selected.set(pool);
        try {
            var outer = pool.submit(() -> calls.append('A'));
            outer.get(5, TimeUnit.SECONDS); nested.get().get(5, TimeUnit.SECONDS);
            require(failure.get() == null && attempts.get() == 2 && calls.toString().equals("BA"), "nested-growth-order");
        } finally { stop(pool); }
    }
    private static void duringFactory(boolean immediate, String outcome) throws Exception {
        var entered = new CountDownLatch(1); var releaseFactory = new CountDownLatch(1);
        var nestedEntered = new CountDownLatch(1); var releaseNested = new CountDownLatch(1);
        var attempts = new AtomicInteger(); var outerCalls = new AtomicInteger(); var nestedCalls = new AtomicInteger();
        var failure = new AtomicReference<Throwable>(); var outer = new AtomicReference<Future<?>>();
        var marker = new IllegalStateException("cached-factory-failure");
        var pool = Executors.newCachedThreadPool(target -> {
            if (attempts.incrementAndGet() == 1) {
                entered.countDown();
                try { await(releaseFactory, "factory-not-released"); } catch (InterruptedException error) { throw new AssertionError(error); }
                if (outcome.equals("throw")) throw marker;
                if (outcome.equals("null")) return null;
            }
            return new Thread(target);
        });
        var caller = new Thread(() -> {
            try { outer.set(pool.submit(outerCalls::incrementAndGet)); }
            catch (Throwable error) { failure.set(error); }
        });
        try {
            caller.start(); await(entered, "outer-factory-not-entered");
            Future<?> nested = pool.submit(() -> {
                nestedCalls.incrementAndGet(); nestedEntered.countDown();
                while (true) try { releaseNested.await(); return; } catch (InterruptedException ignored) { }
            });
            await(nestedEntered, "nested-not-running");
            if (immediate) require(pool.shutdownNow().isEmpty(), "hidden-first-exposed"); else pool.shutdown();
            require(!pool.isTerminated(), "pool-retired-with-factory-and-callback");
            releaseFactory.countDown(); caller.join(5000);
            require(!caller.isAlive() && outer.get() == null
                && (outcome.equals("throw") ? failure.get() == marker : failure.get() instanceof RejectedExecutionException),
                "wrong-outer-shutdown-outcome");
            require(!nested.isDone() && outerCalls.get() == 0 && nestedCalls.get() == 1, "nested-custody");
            releaseNested.countDown(); nested.get(5, TimeUnit.SECONDS);
            require(pool.awaitTermination(5, TimeUnit.SECONDS) && attempts.get() == 2, "shutdown-not-retired");
        } finally { releaseFactory.countDown(); releaseNested.countDown(); caller.join(5000); stop(pool); }
    }
    private static void noWorkerFailure(boolean throwsFailure) throws Exception {
        var attempts = new AtomicInteger(); var calls = new AtomicInteger();
        var marker = new IllegalStateException("cached-factory-failure");
        var pool = Executors.newCachedThreadPool(target -> {
            attempts.incrementAndGet(); if (throwsFailure) throw marker; return null;
        });
        try {
            try { pool.submit(calls::incrementAndGet); throw new AssertionError("unavailable-factory-accepted"); }
            catch (RuntimeException error) {
                require(throwsFailure ? error == marker : error instanceof RejectedExecutionException, "wrong-factory-refusal");
            }
            require(attempts.get() == 1 && calls.get() == 0 && pool.shutdownNow().isEmpty(), "rejected-task-visible");
        } finally { stop(pool); }
    }
    private static void committedFirst() throws Exception {
        var entered = new CountDownLatch(1); var release = new CountDownLatch(1); var calls = new AtomicInteger();
        var pool = Executors.newCachedThreadPool(target -> new Thread(() -> {
            entered.countDown();
            while (true) try { release.await(); break; } catch (InterruptedException ignored) { }
            target.run();
        }));
        try {
            var result = pool.submit(calls::incrementAndGet); await(entered, "worker-not-held");
            require(pool.shutdownNow().isEmpty() && !result.isDone(), "committed-first-exposed");
            release.countDown(); require(result.get(5, TimeUnit.SECONDS).equals(1) && calls.get() == 1, "committed-first-lost");
        } finally { release.countDown(); stop(pool); }
    }
    private static void idleReuse() throws Exception {
        var attempts = new AtomicInteger(); var thread = new AtomicReference<Thread>();
        var pool = Executors.newCachedThreadPool(target -> { attempts.incrementAndGet(); var t = new Thread(target); thread.set(t); return t; });
        try {
            var first = pool.submit(() -> Thread.currentThread()); Thread original = first.get(5, TimeUnit.SECONDS);
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
            while (thread.get().getState() != Thread.State.TIMED_WAITING) {
                require(thread.get().isAlive() && System.nanoTime() - deadline < 0, "worker-not-idle"); Thread.yield();
            }
            var second = pool.submit(() -> Thread.currentThread());
            require(second.get(5, TimeUnit.SECONDS) == original && attempts.get() == 1, "idle-worker-not-reused");
        } finally { stop(pool); }
    }
    private static void growth() throws Exception {
        var entered = new CountDownLatch(1); var release = new CountDownLatch(1); var attempts = new AtomicInteger();
        var pool = Executors.newCachedThreadPool(target -> { attempts.incrementAndGet(); return new Thread(target); });
        try {
            var first = pool.submit(() -> { entered.countDown(); await(release, "first-not-released"); return Thread.currentThread(); });
            await(entered, "first-not-running"); var second = pool.submit(() -> Thread.currentThread());
            Thread other = second.get(5, TimeUnit.SECONDS); release.countDown();
            require(first.get(5, TimeUnit.SECONDS) != other && attempts.get() == 2, "busy-worker-not-grown");
        } finally { release.countDown(); stop(pool); }
    }
    private static void concurrentReservations() throws Exception {
        var enteredOne = new CountDownLatch(1); var enteredTwo = new CountDownLatch(1); var release = new CountDownLatch(1);
        var attempts = new AtomicInteger(); var calls = new AtomicInteger(); var failure = new AtomicReference<Throwable>();
        var first = new AtomicReference<Future<?>>(); var second = new AtomicReference<Future<?>>();
        var pool = Executors.newCachedThreadPool(target -> {
            int attempt = attempts.incrementAndGet();
            if (attempt <= 2) {
                (attempt == 1 ? enteredOne : enteredTwo).countDown();
                try { await(release, "reserved-factories-not-released"); } catch (InterruptedException error) { throw new AssertionError(error); }
            }
            return new Thread(target);
        });
        Thread one = new Thread(() -> { try { first.set(pool.submit(calls::incrementAndGet)); } catch (Throwable error) { failure.set(error); } });
        Thread two = new Thread(() -> { try { second.set(pool.submit(calls::incrementAndGet)); } catch (Throwable error) { failure.set(error); } });
        try {
            one.start(); await(enteredOne, "first-factory-not-entered");
            two.start(); await(enteredTwo, "second-factory-not-entered");
            require(pool.submit(calls::incrementAndGet).get(5, TimeUnit.SECONDS).equals(1) && attempts.get() == 3,
                "concurrent-reservation-blocked-growth");
            release.countDown(); one.join(5000); two.join(5000);
            require(!one.isAlive() && !two.isAlive() && failure.get() == null && first.get() != null && second.get() != null,
                "reserved-submission-failed");
            first.get().get(5, TimeUnit.SECONDS); second.get().get(5, TimeUnit.SECONDS);
            require(calls.get() == 3, "reserved-submission-not-run-once");
        } finally { release.countDown(); one.join(5000); two.join(5000); stop(pool); }
    }
    private static void idleShutdownDifference(boolean reference) throws Exception {
        var thread = new AtomicReference<Thread>(); var calls = new AtomicInteger();
        var entered = new CountDownLatch(1); var release = new CountDownLatch(1);
        var pool = Executors.newCachedThreadPool(target -> { var worker = new Thread(target); thread.set(worker); return worker; });
        try {
            pool.submit(() -> {}).get(5, TimeUnit.SECONDS);
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
            while (thread.get().getState() != Thread.State.TIMED_WAITING) {
                require(thread.get().isAlive() && System.nanoTime() - deadline < 0, "handoff-worker-not-idle"); Thread.yield();
            }
            Future<?> second; List<Runnable> removed;
            synchronized (pool) {
                second = pool.submit(() -> {
                    calls.incrementAndGet(); entered.countDown();
                    while (true) try { release.await(); return; } catch (InterruptedException ignored) { }
                });
                removed = pool.shutdownNow();
            }
            if (reference) {
                require(removed.isEmpty(), "jdk-idle-handoff-returned"); await(entered, "jdk-handoff-not-run");
                release.countDown(); second.get(5, TimeUnit.SECONDS); require(calls.get() == 1, "jdk-handoff-lost");
            } else {
                require(removed.size() == 1 && removed.get(0) == second && !second.isDone() && calls.get() == 0,
                    "sdk-idle-queue-not-withdrawn");
                require(second.cancel(false), "sdk-withdrawn-task-not-cancellable");
            }
        } finally { release.countDown(); stop(pool); }
    }
    private static void liveThread() throws Exception {
        var entered = new CountDownLatch(1); var release = new CountDownLatch(1);
        var interrupts = new AtomicInteger(); var calls = new AtomicInteger();
        Thread live = new Thread(() -> {
            entered.countDown();
            try { release.await(); } catch (InterruptedException ignored) { }
        }) { @Override public void interrupt() { interrupts.incrementAndGet(); super.interrupt(); } };
        live.start(); await(entered, "live-thread-not-started");
        var pool = Executors.newCachedThreadPool(target -> live);
        try {
            try { pool.submit(calls::incrementAndGet); throw new AssertionError("live-thread-accepted"); }
            catch (IllegalThreadStateException expected) { }
            require(pool.shutdownNow().isEmpty() && pool.awaitTermination(5, TimeUnit.SECONDS)
                && live.isAlive() && interrupts.get() == 0 && calls.get() == 0, "live-thread-custody");
        } finally { release.countDown(); live.join(5000); stop(pool); }
    }
    public static void main(String[] args) throws Exception {
        require(args.length == 1 && (args[0].equals("jdk") || args[0].equals("source")), "profile");
        nestedAcrossFactory();
        for (boolean immediate : new boolean[]{false, true}) for (String outcome : List.of("thread", "null", "throw"))
            duringFactory(immediate, outcome);
        noWorkerFailure(false); noWorkerFailure(true); committedFirst(); idleReuse(); growth(); concurrentReservations();
        idleShutdownDifference(args[0].equals("jdk")); liveThread();
        System.out.println("MANAGED_CACHED_FACTORY PASS nested;shutdown-thread-null-throw;refusal;committed;idle-reuse;growth;concurrent-reservations;idle-shutdown-difference;live-thread");
    }
}
