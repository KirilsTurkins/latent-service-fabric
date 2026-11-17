import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** JDK and SDK source observations; no signed guest execution is implied. */
public final class ManagedNullFactoryReferenceControl {
    private static void require(boolean value) { if (!value) throw new AssertionError("managed-null-factory-reference"); }
    private static ExecutorService create(boolean single, ThreadFactory factory) {
        return single ? Executors.newSingleThreadExecutor(factory) : Executors.newFixedThreadPool(1, factory);
    }
    private static void unavailable(boolean single) throws Exception {
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        var pool = create(single, target -> { attempts.incrementAndGet(); return null; });
        Future<?> future = pool.submit(calls::incrementAndGet);
        require(attempts.get() == 2 && !future.isDone() && calls.get() == 0);
        List<Runnable> removed = pool.shutdownNow();
        require(removed.size() == 1 && removed.get(0) == future && !future.isDone());
        require(future.cancel(false) && pool.awaitTermination(5, TimeUnit.SECONDS));
    }
    private static void immediateRecovery(boolean single) throws Exception {
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        var pool = create(single, target -> attempts.incrementAndGet() == 1 ? null : new Thread(target));
        try {
            var future = pool.submit(calls::incrementAndGet);
            future.get(5, TimeUnit.SECONDS);
            require(attempts.get() == 2 && calls.get() == 1);
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
    }
    private static void laterRecovery(boolean single) throws Exception {
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        var pool = create(single, target -> attempts.incrementAndGet() <= 2 ? null : new Thread(target));
        try {
            var first = pool.submit(calls::incrementAndGet);
            require(attempts.get() == 2 && !first.isDone());
            var later = pool.submit(calls::incrementAndGet);
            first.get(5, TimeUnit.SECONDS); later.get(5, TimeUnit.SECONDS);
            require(attempts.get() == 3 && calls.get() == 2);
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
    }
    private static void fallbackThrows(boolean single, boolean asError) throws Exception {
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        CountDownLatch originalRan = new CountDownLatch(1);
        Throwable failure = asError ? new AssertionError("fallback-factory-error") : new IllegalStateException("fallback-factory-failed");
        var pool = create(single, target -> {
            int attempt = attempts.incrementAndGet();
            if (attempt == 1) return null;
            if (attempt == 2) {
                if (failure instanceof Error error) throw error;
                throw (RuntimeException)failure;
            }
            return new Thread(target);
        });
        try {
            try { pool.submit(() -> { calls.incrementAndGet(); originalRan.countDown(); });
                throw new AssertionError("missing-factory-failure"); }
            catch (Throwable observed) { require(observed == failure); }
            require(attempts.get() == 2 && calls.get() == 0);
            pool.submit(() -> {}).get(5, TimeUnit.SECONDS);
            require(originalRan.await(5, TimeUnit.SECONDS) && calls.get() == 1 && attempts.get() == 3);
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
    }
    private static void existingWorker() throws Exception {
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        var pool = Executors.newFixedThreadPool(2, target -> attempts.incrementAndGet() == 1 ? new Thread(target) : null);
        try {
            var first = pool.submit(() -> {
                entered.countDown();
                try { release.await(); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
            });
            require(entered.await(5, TimeUnit.SECONDS));
            var second = pool.submit(calls::incrementAndGet);
            require(attempts.get() == 2 && !second.isDone());
            release.countDown(); first.get(5, TimeUnit.SECONDS); second.get(5, TimeUnit.SECONDS);
            require(calls.get() == 1 && attempts.get() == 2);
        } finally { release.countDown(); pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
    }
    private static void nested() throws Exception {
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicReference<Future<?>> nested = new AtomicReference<>();
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        var pool = Executors.newFixedThreadPool(1, target -> {
            if (attempts.incrementAndGet() == 1) {
                nested.set(selected.get().submit(calls::incrementAndGet));
                return null;
            }
            return new Thread(target);
        });
        selected.set(pool);
        try {
            var outer = pool.submit(calls::incrementAndGet);
            outer.get(5, TimeUnit.SECONDS); nested.get().get(5, TimeUnit.SECONDS);
            require(attempts.get() == 2 && calls.get() == 2);
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
    }
    private static void nestedInitialOrder(boolean single, boolean noWorker) throws Exception {
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicReference<Future<?>> firstNested = new AtomicReference<>(), secondNested = new AtomicReference<>();
        AtomicInteger attempts = new AtomicInteger();
        StringBuffer calls = new StringBuffer();
        var pool = create(single, target -> {
            if (attempts.incrementAndGet() == 1) {
                firstNested.set(selected.get().submit(() -> calls.append('N')));
                secondNested.set(selected.get().submit(() -> calls.append('P')));
                return null;
            }
            return noWorker ? null : new Thread(target);
        });
        selected.set(pool);
        try {
            var outer = pool.submit(() -> calls.append('A'));
            if (noWorker) {
                require(attempts.get() == 2 && calls.length() == 0);
                List<Runnable> removed = pool.shutdownNow();
                require(removed.size() == 3 && removed.get(0) == firstNested.get()
                    && removed.get(1) == secondNested.get() && removed.get(2) == outer);
                require(firstNested.get().cancel(false) && secondNested.get().cancel(false) && outer.cancel(false));
            } else {
                outer.get(5, TimeUnit.SECONDS); firstNested.get().get(5, TimeUnit.SECONDS);
                secondNested.get().get(5, TimeUnit.SECONDS);
                require(attempts.get() == 2 && calls.toString().equals("NPA"));
            }
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
    }
    private static void nestedInitialWithOlder(boolean noWorker) throws Exception {
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicReference<Future<?>> nested = new AtomicReference<>();
        AtomicInteger attempts = new AtomicInteger();
        StringBuffer calls = new StringBuffer();
        var pool = Executors.newFixedThreadPool(1, target -> {
            int attempt = attempts.incrementAndGet();
            if (attempt <= 2) return null;
            if (attempt == 3) {
                nested.set(selected.get().submit(() -> calls.append('N')));
                return null;
            }
            return noWorker ? null : new Thread(target);
        });
        selected.set(pool);
        try {
            var older = pool.submit(() -> calls.append('X'));
            var outer = pool.submit(() -> calls.append('A'));
            if (noWorker) {
                List<Runnable> removed = pool.shutdownNow();
                require(removed.size() == 3 && removed.get(0) == older && removed.get(1) == nested.get()
                    && removed.get(2) == outer && calls.length() == 0);
                require(older.cancel(false) && nested.get().cancel(false) && outer.cancel(false));
            } else {
                older.get(5, TimeUnit.SECONDS); nested.get().get(5, TimeUnit.SECONDS); outer.get(5, TimeUnit.SECONDS);
                require(calls.toString().equals("XNA"));
            }
            require(attempts.get() == 4);
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
    }
    private static void nestedFallbackThrows() throws Exception {
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicReference<Future<?>> nested = new AtomicReference<>();
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        CountDownLatch originalRan = new CountDownLatch(1);
        var failure = new IllegalStateException("nested-fallback-failed");
        var pool = Executors.newFixedThreadPool(1, target -> {
            int attempt = attempts.incrementAndGet();
            if (attempt == 1) return null;
            if (attempt == 2) { nested.set(selected.get().submit(calls::incrementAndGet)); throw failure; }
            return new Thread(target);
        });
        selected.set(pool);
        try {
            try { pool.submit(() -> { calls.incrementAndGet(); originalRan.countDown(); });
                throw new AssertionError("missing-factory-failure"); }
            catch (IllegalStateException observed) { require(observed == failure); }
            require(attempts.get() == 2 && nested.get() != null && !nested.get().isDone());
            pool.submit(() -> {}).get(5, TimeUnit.SECONDS);
            nested.get().get(5, TimeUnit.SECONDS);
            require(originalRan.await(5, TimeUnit.SECONDS) && calls.get() == 2 && attempts.get() == 3);
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
    }
    private static void cached() throws Exception {
        AtomicInteger attempts = new AtomicInteger();
        var pool = Executors.newCachedThreadPool(target -> { attempts.incrementAndGet(); return null; });
        try {
            try { pool.submit(() -> {}); throw new AssertionError("cached-accepted-null"); }
            catch (RejectedExecutionException expected) { require(attempts.get() == 1); }
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
    }
    private static void fallbackCompletable() throws Exception {
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        var failure = new IllegalStateException("fallback-factory-failed");
        var pool = Executors.newFixedThreadPool(1, target -> {
            int attempt = attempts.incrementAndGet();
            if (attempt == 1) return null;
            if (attempt == 2) throw failure;
            return new Thread(target);
        });
        var result = new CompletableFuture<Integer>();
        try {
            try { result.completeAsync(() -> { calls.incrementAndGet(); return 42; }, pool);
                throw new AssertionError("missing-factory-failure"); }
            catch (IllegalStateException observed) { require(observed == failure); }
            require(!result.isDone() && calls.get() == 0 && attempts.get() == 2);
            pool.submit(() -> {}).get(5, TimeUnit.SECONDS);
            require(result.get(5, TimeUnit.SECONDS) == 42 && calls.get() == 1 && attempts.get() == 3);
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
    }
    private static void fallbackLiveThread() throws Exception {
        CountDownLatch liveEntered = new CountDownLatch(1), liveRelease = new CountDownLatch(1), originalRan = new CountDownLatch(1);
        Thread live = new Thread(() -> {
            liveEntered.countDown();
            try { liveRelease.await(); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
        });
        live.start(); require(liveEntered.await(5, TimeUnit.SECONDS));
        AtomicInteger attempts = new AtomicInteger();
        var pool = Executors.newFixedThreadPool(1, target -> {
            int attempt = attempts.incrementAndGet();
            if (attempt == 1) return null;
            return attempt == 2 ? live : new Thread(target);
        });
        try {
            try { pool.submit(originalRan::countDown); throw new AssertionError("accepted-live-thread"); }
            catch (IllegalThreadStateException expected) { require(attempts.get() == 2 && live.isAlive()); }
            pool.submit(() -> {}).get(5, TimeUnit.SECONDS);
            require(originalRan.await(5, TimeUnit.SECONDS) && attempts.get() == 3 && live.isAlive());
        } finally {
            liveRelease.countDown(); live.join(5000); require(!live.isAlive());
            pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS));
        }
    }
    private static void recoveryOrder() throws Exception {
        AtomicInteger attempts = new AtomicInteger();
        StringBuffer calls = new StringBuffer();
        var pool = Executors.newFixedThreadPool(1, target -> attempts.incrementAndGet() <= 2 ? null : new Thread(target));
        try {
            var first = pool.submit(() -> calls.append('A'));
            var later = pool.submit(() -> calls.append('B'));
            first.get(5, TimeUnit.SECONDS); later.get(5, TimeUnit.SECONDS);
            require(attempts.get() == 3 && calls.toString().equals("BA"));
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
    }
    private static void reentrantRecoveryOrder() throws Exception {
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicReference<Future<?>> nested = new AtomicReference<>();
        AtomicInteger attempts = new AtomicInteger();
        StringBuffer calls = new StringBuffer();
        var pool = Executors.newFixedThreadPool(1, target -> {
            int attempt = attempts.incrementAndGet();
            if (attempt <= 2) return null;
            nested.set(selected.get().submit(() -> calls.append('C')));
            return new Thread(target);
        });
        selected.set(pool);
        try {
            var first = pool.submit(() -> calls.append('A'));
            var later = pool.submit(() -> calls.append('B'));
            first.get(5, TimeUnit.SECONDS); later.get(5, TimeUnit.SECONDS); nested.get().get(5, TimeUnit.SECONDS);
            require(attempts.get() == 3 && calls.toString().equals("BAC"));
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
    }
    public static void main(String[] args) throws Exception {
        require(args.length == 1 && (args[0].equals("jdk") || args[0].equals("source")));
        for (boolean single : new boolean[]{false, true}) {
            unavailable(single); immediateRecovery(single); laterRecovery(single); fallbackThrows(single, false); fallbackThrows(single, true);
            nestedInitialOrder(single, false); nestedInitialOrder(single, true);
        }
        existingWorker(); nested(); nestedInitialWithOlder(false); nestedInitialWithOlder(true);
        nestedFallbackThrows(); cached(); fallbackCompletable(); fallbackLiveThread(); recoveryOrder(); reentrantRecoveryOrder();
        System.out.println("MANAGED_NULL_FACTORY PASS fixed;single;two-attempts;recovery;fallback-throw;existing-worker;nested;nested-initial-order;nested-fallback-throw;cached-rejection;completable;live-thread;recovery-order;reentrant-recovery-order");
    }
}
