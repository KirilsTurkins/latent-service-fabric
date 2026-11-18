import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** JDK and selected SDK observations. No signed-component claim. */
public final class ManagedFirstAdmissionReferenceControl {
    private static void require(boolean value, String message) { if (!value) throw new AssertionError(message); }
    private static void await(CountDownLatch latch, String message) throws InterruptedException {
        require(latch.await(5, TimeUnit.SECONDS), message);
    }
    private static void stop(ExecutorService pool) throws InterruptedException {
        pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS), "pool-not-terminated");
    }
    private static void nestedDuringFactory() throws Exception {
        var selected = new AtomicReference<ExecutorService>();
        var nested = new AtomicReference<Future<?>>();
        var failure = new AtomicReference<Throwable>();
        var accepted = new CountDownLatch(1);
        var calls = new StringBuffer();
        var attempts = new AtomicInteger();
        var pool = Executors.newFixedThreadPool(1, target -> {
            if (attempts.incrementAndGet() == 1) {
                Thread helper = new Thread(() -> {
                    try { nested.set(selected.get().submit(() -> calls.append('B'))); }
                    catch (Throwable error) { failure.set(error); }
                    finally { accepted.countDown(); }
                });
                helper.start();
                try { await(accepted, "nested-admission-blocked"); }
                catch (InterruptedException error) { throw new AssertionError(error); }
            }
            return new Thread(target);
        });
        selected.set(pool);
        try {
            var first = pool.submit(() -> calls.append('A'));
            first.get(5, TimeUnit.SECONDS); nested.get().get(5, TimeUnit.SECONDS);
            require(failure.get() == null && attempts.get() == 1 && calls.toString().equals("AB"),
                "first-and-nested-order");
        } finally { stop(pool); }
    }
    private static void beforeCommit(boolean immediate) throws Exception {
        var entered = new CountDownLatch(1); var release = new CountDownLatch(1);
        var attempts = new AtomicInteger(); var calls = new AtomicInteger();
        var error = new AtomicReference<Throwable>(); var result = new AtomicReference<Future<?>>();
        var created = new AtomicReference<Thread>();
        var pool = Executors.newFixedThreadPool(1, target -> {
            attempts.incrementAndGet(); entered.countDown();
            try { await(release, "factory-release"); } catch (InterruptedException e) { throw new AssertionError(e); }
            Thread thread = new Thread(target); created.set(thread); return thread;
        });
        Thread caller = new Thread(() -> {
            try { result.set(pool.submit(calls::incrementAndGet)); } catch (Throwable failure) { error.set(failure); }
        });
        try {
            caller.start(); await(entered, "factory-not-entered");
            Future<?> nested = pool.submit(calls::incrementAndGet);
            List<Runnable> removed = null;
            if (immediate) removed = pool.shutdownNow(); else pool.shutdown();
            if (immediate) require(removed.size() == 1 && removed.get(0) == nested, "first-exposed");
            require(!pool.isTerminated(), "terminated-during-factory");
            release.countDown(); caller.join(5000);
            require(!caller.isAlive() && error.get() instanceof RejectedExecutionException && result.get() == null,
                "precommit-rejection");
            if (!immediate) {
                require(!nested.isDone() && !pool.isTerminated(), "nested-work-lost");
                removed = pool.shutdownNow();
                require(removed.size() == 1 && removed.get(0) == nested, "graceful-nested-withdrawal");
            }
            require(created.get() != null && created.get().getState() == Thread.State.NEW
                && !nested.isDone() && calls.get() == 0 && attempts.get() == 1
                && pool.awaitTermination(5, TimeUnit.SECONDS), "precommit-outcome");
            require(nested.cancel(false), "nested-cancel");
        } finally { release.countDown(); caller.join(5000); stop(pool); }
    }
    private static void afterCommit() throws Exception {
        var entered = new CountDownLatch(1); var release = new CountDownLatch(1); var calls = new AtomicInteger();
        var pool = Executors.newFixedThreadPool(1, target -> new Thread(() -> {
            entered.countDown();
            while (true) try { release.await(); break; } catch (InterruptedException ignored) { }
            target.run();
        }));
        try {
            Future<Integer> first = pool.submit(calls::incrementAndGet);
            await(entered, "target-not-held");
            require(pool.shutdownNow().isEmpty() && !first.isDone(), "committed-first-exposed");
            release.countDown();
            require(first.get(5, TimeUnit.SECONDS) == 1 && calls.get() == 1
                && pool.awaitTermination(5, TimeUnit.SECONDS), "committed-first-not-run");
        } finally { release.countDown(); stop(pool); }
    }
    private static void nullOrThrow(boolean throwsFailure) throws Exception {
        var entered = new CountDownLatch(1); var release = new CountDownLatch(1);
        var attempts = new AtomicInteger(); var calls = new StringBuffer(); var error = new AtomicReference<Throwable>();
        var outer = new AtomicReference<Future<?>>();
        var marker = new IllegalStateException("factory-failure");
        var pool = Executors.newFixedThreadPool(1, target -> {
            if (attempts.incrementAndGet() == 1) {
                entered.countDown();
                try { await(release, "factory-release"); } catch (InterruptedException e) { throw new AssertionError(e); }
                if (throwsFailure) throw marker;
                return null;
            }
            return new Thread(target);
        });
        Thread caller = new Thread(() -> {
            try { outer.set(pool.submit(() -> calls.append('A'))); } catch (Throwable failure) { error.set(failure); }
        });
        try {
            caller.start(); await(entered, "factory-not-entered");
            Future<?> nested = pool.submit(() -> calls.append('B'));
            require(!nested.isDone() && attempts.get() == 1, "nested-not-pending");
            release.countDown(); caller.join(5000); require(!caller.isAlive(), "caller-stuck");
            if (throwsFailure) {
                require(error.get() == marker && outer.get() == null, "factory-failure-lost");
                pool.submit(() -> calls.append('C')).get(5, TimeUnit.SECONDS);
                nested.get(5, TimeUnit.SECONDS);
                require(calls.toString().equals("CB") && attempts.get() == 2, "throw-recovery-order");
            } else {
                require(error.get() == null && outer.get() != null, "null-factory-rejected");
                nested.get(5, TimeUnit.SECONDS); outer.get().get(5, TimeUnit.SECONDS);
                require(calls.toString().equals("BA") && attempts.get() == 2, "null-fallback-order");
            }
        } finally { release.countDown(); caller.join(5000); stop(pool); }
    }
    private static void fallbackShutdown() throws Exception {
        var entered = new CountDownLatch(1); var release = new CountDownLatch(1);
        var attempts = new AtomicInteger(); var calls = new AtomicInteger(); var error = new AtomicReference<Throwable>();
        var marker = new IllegalStateException("fallback-factory-failure");
        var pool = Executors.newFixedThreadPool(1, target -> {
            if (attempts.incrementAndGet() == 1) return null;
            entered.countDown();
            try { await(release, "fallback-release"); } catch (InterruptedException e) { throw new AssertionError(e); }
            throw marker;
        });
        Thread caller = new Thread(() -> {
            try { pool.execute(calls::incrementAndGet); } catch (Throwable failure) { error.set(failure); }
        });
        try {
            caller.start(); await(entered, "fallback-not-entered");
            List<Runnable> removed = pool.shutdownNow();
            require(removed.size() == 1, "fallback-entry-not-visible");
            release.countDown(); caller.join(5000);
            require(!caller.isAlive() && error.get() == marker && calls.get() == 0
                && pool.awaitTermination(5, TimeUnit.SECONDS), "fallback-failure");
        } finally { release.countDown(); caller.join(5000); stop(pool); }
    }
    private static void committedWithOlderQueue() throws Exception {
        var attempts = new AtomicInteger(); var calls = new AtomicInteger();
        var entered = new CountDownLatch(1); var release = new CountDownLatch(1);
        var pool = Executors.newFixedThreadPool(1, target -> {
            if (attempts.incrementAndGet() <= 2) return null;
            return new Thread(() -> {
                entered.countDown();
                while (true) try { release.await(); break; } catch (InterruptedException ignored) { }
                target.run();
            });
        });
        try {
            var older = pool.submit(calls::incrementAndGet);
            var first = pool.submit(calls::incrementAndGet); await(entered, "worker-not-held");
            var removed = pool.shutdownNow();
            require(removed.size() == 1 && removed.get(0) == older && !first.isDone(), "committed-first-withdrawn");
            release.countDown(); require(first.get(5, TimeUnit.SECONDS).equals(1) && calls.get() == 1,
                "committed-first-not-executed");
            require(older.cancel(false) && pool.awaitTermination(5, TimeUnit.SECONDS), "older-not-settled");
        } finally { release.countDown(); stop(pool); }
    }
    private static void twoCommittedFirsts() throws Exception {
        var attempts = new AtomicInteger(); var calls = new StringBuffer();
        var firstHeld = new CountDownLatch(1); var secondHeld = new CountDownLatch(1);
        var releaseFirst = new CountDownLatch(1); var releaseSecond = new CountDownLatch(1);
        var secondRunning = new CountDownLatch(1); var finishSecond = new CountDownLatch(1);
        var pool = Executors.newFixedThreadPool(2, target -> {
            boolean first = attempts.incrementAndGet() == 1;
            return new Thread(() -> {
                (first ? firstHeld : secondHeld).countDown();
                while (true) try { (first ? releaseFirst : releaseSecond).await(); break; }
                catch (InterruptedException ignored) { }
                target.run();
            });
        });
        try {
            var a = pool.submit(() -> calls.append('A')); await(firstHeld, "first-not-held");
            var b = pool.submit(() -> {
                calls.append('B'); secondRunning.countDown();
                while (true) try { finishSecond.await(); return; } catch (InterruptedException ignored) { }
            });
            await(secondHeld, "second-not-held"); releaseSecond.countDown(); await(secondRunning, "second-not-running");
            require(!a.isDone(), "first-stolen");
            var c = pool.submit(() -> calls.append('C')); releaseFirst.countDown();
            a.get(5, TimeUnit.SECONDS); c.get(5, TimeUnit.SECONDS);
            require(calls.toString().equals("BAC"), "committed-first-order");
            finishSecond.countDown(); b.get(5, TimeUnit.SECONDS);
        } finally { releaseFirst.countDown(); releaseSecond.countDown(); finishSecond.countDown(); stop(pool); }
    }
    private static void nestedWithExistingWorker(boolean shutdown, boolean returnsNull) throws Exception {
        var selected = new AtomicReference<ExecutorService>(); var nested = new AtomicReference<Future<?>>();
        var attempts = new AtomicInteger(); var calls = new StringBuffer();
        var firstEntered = new CountDownLatch(1); var releaseFirst = new CountDownLatch(1); var nestedRan = new CountDownLatch(1);
        var pool = Executors.newFixedThreadPool(2, target -> {
            if (attempts.incrementAndGet() == 1) return new Thread(target);
            nested.set(selected.get().submit(() -> { calls.append('B'); nestedRan.countDown(); }));
            releaseFirst.countDown();
            try { await(nestedRan, "nested-not-run"); } catch (InterruptedException error) { throw new AssertionError(error); }
            require(calls.toString().equals("B"), "uncommitted-first-ran");
            if (shutdown) selected.get().shutdown();
            return returnsNull ? null : new Thread(target);
        });
        selected.set(pool);
        try {
            var first = pool.submit(() -> {
                firstEntered.countDown();
                try { releaseFirst.await(); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
            });
            await(firstEntered, "first-not-running");
            Future<?> outer = null;
            try { outer = pool.submit(() -> calls.append('A')); require(!shutdown, "accepted-after-shutdown"); }
            catch (RejectedExecutionException error) { require(shutdown, "unexpected-rejection"); }
            first.get(5, TimeUnit.SECONDS); nested.get().get(5, TimeUnit.SECONDS);
            if (outer != null) outer.get(5, TimeUnit.SECONDS);
            require(attempts.get() == 2 && calls.toString().equals(shutdown ? "B" : "BA"), "nested-factory-order");
        } finally { releaseFirst.countDown(); stop(pool); }
    }
    public static void main(String[] args) throws Exception {
        nestedDuringFactory(); beforeCommit(false); beforeCommit(true); afterCommit();
        nullOrThrow(false); nullOrThrow(true); fallbackShutdown(); committedWithOlderQueue(); twoCommittedFirsts();
        nestedWithExistingWorker(false, true); nestedWithExistingWorker(true, true); nestedWithExistingWorker(true, false);
        System.out.println("MANAGED_FIRST_ADMISSION PASS nested;graceful;immediate;committed;null;throw;fallback-shutdown;older;two-firsts;active-worker");
    }
}
