import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Future;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Equal public observations against the JDK and actual SDK sources. */
public final class ScheduledThrowFactoryReferenceControl {
    private static void require(boolean value) { if (!value) throw new AssertionError("throw-factory-reference"); }
    private static void raise(Throwable failure) {
        if (failure instanceof Error error) throw error;
        throw (RuntimeException)failure;
    }
    private static void recover(int core, Throwable failure) throws Exception {
        AtomicInteger attempts = new AtomicInteger();
        StringBuffer calls = new StringBuffer();
        var pool = new ScheduledThreadPoolExecutor(core, target -> {
            if (attempts.getAndIncrement() == 0) raise(failure);
            return new Thread(target);
        });
        try {
            try { pool.schedule(() -> calls.append('1'), 0, TimeUnit.NANOSECONDS); throw new AssertionError("factory-did-not-throw"); }
            catch (Throwable observed) { require(observed == failure); }
            require(calls.isEmpty() && attempts.get() == 1);
            var second = pool.schedule(() -> calls.append('2'), 0, TimeUnit.NANOSECONDS);
            second.get(5, TimeUnit.SECONDS);
            require(attempts.get() == 2 && calls.toString().equals("12"));
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
    }
    private static void withdraw() throws Exception {
        var failure = new IllegalStateException("factory-failed");
        var pool = new ScheduledThreadPoolExecutor(1, target -> { throw failure; });
        try { pool.schedule(() -> { throw new AssertionError("withdrawn-callback-ran"); }, 1, TimeUnit.DAYS);
            throw new AssertionError("factory-did-not-throw"); }
        catch (IllegalStateException observed) { require(observed == failure); }
        List<Runnable> removed = pool.shutdownNow();
        require(removed.size() == 1 && removed.get(0) instanceof Future<?>);
        Future<?> pending = (Future<?>)removed.get(0);
        require(!pending.isDone() && pending.cancel(false) && pool.awaitTermination(5, TimeUnit.SECONDS));
    }
    private static void reentrantShutdown() throws Exception {
        var failure = new IllegalStateException("factory-after-shutdown");
        AtomicReference<ScheduledThreadPoolExecutor> selected = new AtomicReference<>();
        AtomicReference<List<Runnable>> removed = new AtomicReference<>();
        var pool = new ScheduledThreadPoolExecutor(1, target -> {
            removed.set(selected.get().shutdownNow());
            throw failure;
        });
        selected.set(pool);
        try { pool.schedule(() -> { throw new AssertionError("shutdown-callback-ran"); }, 0, TimeUnit.NANOSECONDS);
            throw new AssertionError("factory-did-not-throw"); }
        catch (IllegalStateException observed) { require(observed == failure); }
        require(removed.get().size() == 1 && pool.awaitTermination(5, TimeUnit.SECONDS));
        var task = (Future<?>)removed.get().get(0);
        require(!task.isDone() && task.cancel(false));
    }
    private static void completable() throws Exception {
        var failure = new RejectedExecutionException("factory-failed");
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        var pool = new ScheduledThreadPoolExecutor(1, target -> {
            if (attempts.getAndIncrement() == 0) throw failure;
            return new Thread(target);
        });
        var result = new CompletableFuture<Integer>();
        try {
            try { result.completeAsync(() -> { calls.incrementAndGet(); return 42; }, pool);
                throw new AssertionError("factory-did-not-throw"); }
            catch (RejectedExecutionException observed) { require(observed == failure); }
            require(!result.isDone() && calls.get() == 0);
            pool.schedule(() -> {}, 0, TimeUnit.NANOSECONDS).get(5, TimeUnit.SECONDS);
            require(result.get(5, TimeUnit.SECONDS) == 42 && calls.get() == 1);
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
    }
    private static void submissionApis(boolean periodic) throws Exception {
        var failure = new IllegalStateException("factory-failed");
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        var pool = new ScheduledThreadPoolExecutor(1, target -> {
            if (attempts.getAndIncrement() == 0) throw failure;
            return new Thread(target);
        });
        try {
            try {
                if (periodic) pool.scheduleAtFixedRate(calls::incrementAndGet, 0, 1, TimeUnit.DAYS);
                else pool.submit(calls::incrementAndGet);
                throw new AssertionError("factory-did-not-throw");
            } catch (IllegalStateException observed) { require(observed == failure); }
            pool.schedule(() -> {}, 0, TimeUnit.NANOSECONDS).get(5, TimeUnit.SECONDS);
            require(attempts.get() == 2 && calls.get() == 1);
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
    }
    private static void wakeExisting() throws Exception {
        var failure = new IllegalStateException("second-factory-failed");
        AtomicInteger attempts = new AtomicInteger();
        AtomicReference<Thread> firstWorker = new AtomicReference<>();
        CountDownLatch immediateRan = new CountDownLatch(1);
        var pool = new ScheduledThreadPoolExecutor(2, target -> {
            if (attempts.getAndIncrement() == 0) {
                Thread worker = new Thread(target); firstWorker.set(worker); return worker;
            }
            throw failure;
        });
        try {
            pool.schedule(() -> { throw new AssertionError("delayed-callback-ran"); }, 1, TimeUnit.DAYS);
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
            while (firstWorker.get().getState() != Thread.State.TIMED_WAITING) {
                require(firstWorker.get().isAlive() && System.nanoTime() - deadline < 0);
                Thread.yield();
            }
            try { pool.schedule(immediateRan::countDown, 0, TimeUnit.NANOSECONDS);
                throw new AssertionError("factory-did-not-throw"); }
            catch (IllegalStateException observed) { require(observed == failure); }
            require(immediateRan.await(5, TimeUnit.SECONDS));
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
    }
    public static void main(String[] args) throws Exception {
        for (int core : new int[]{0, 1}) {
            recover(core, new IllegalStateException("factory"));
            recover(core, new RejectedExecutionException("factory-rejected"));
            recover(core, new AssertionError("factory-error"));
        }
        withdraw(); reentrantShutdown(); completable(); submissionApis(false); submissionApis(true); wakeExisting();
        System.out.println("SCHEDULED_THROW_FACTORY PASS accepted;recovery;withdraw;reentrant-shutdown;completable;submission-apis;wake-existing");
    }
}
