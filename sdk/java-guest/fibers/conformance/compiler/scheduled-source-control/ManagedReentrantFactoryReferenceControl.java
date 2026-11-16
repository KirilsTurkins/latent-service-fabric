import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Ordinary JDK and SDK factory observations; no guest execution is implied. */
public final class ManagedReentrantFactoryReferenceControl {
    private static void require(boolean value) { if (!value) throw new AssertionError("managed-factory-reference"); }
    private static ExecutorService create(String kind, ThreadFactory factory) {
        return switch (kind) {
            case "fixed-one" -> Executors.newFixedThreadPool(1, factory);
            case "fixed-two" -> Executors.newFixedThreadPool(2, factory);
            case "single" -> Executors.newSingleThreadExecutor(factory);
            case "cached" -> Executors.newCachedThreadPool(factory);
            default -> throw new IllegalArgumentException(kind);
        };
    }
    private static void control(String kind, boolean parallel) throws Exception {
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicReference<Throwable> callbackError = new AtomicReference<>();
        AtomicInteger factories = new AtomicInteger(), active = new AtomicInteger(), maximum = new AtomicInteger();
        CountDownLatch first = new CountDownLatch(1), both = new CountDownLatch(2);
        CountDownLatch release = new CountDownLatch(1), finished = new CountDownLatch(2);
        Runnable callback = () -> {
            int current = active.incrementAndGet(); maximum.accumulateAndGet(current, Math::max);
            first.countDown(); both.countDown();
            try { if (!release.await(5, TimeUnit.SECONDS)) throw new AssertionError("release-timeout"); }
            catch (Throwable error) { callbackError.set(error); }
            finally { active.decrementAndGet(); finished.countDown(); }
        };
        var pool = create(kind, target -> {
            if (factories.incrementAndGet() == 1) selected.get().execute(callback);
            return new Thread(target);
        });
        selected.set(pool);
        try {
            pool.execute(callback);
            require(first.await(5, TimeUnit.SECONDS));
            boolean bothEntered = both.await(parallel ? 5_000 : 500, TimeUnit.MILLISECONDS);
            require(bothEntered == parallel && maximum.get() == (parallel ? 2 : 1)
                && factories.get() == (parallel ? 2 : 1));
        } finally {
            release.countDown();
            require(finished.await(5, TimeUnit.SECONDS));
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS));
        }
        require(callbackError.get() == null);
    }
    public static void main(String[] args) throws Exception {
        control("fixed-one", false); control("single", false); control("fixed-two", true); control("cached", true);
        System.out.println("MANAGED_REENTRANT_FACTORY PASS fixed-one;single;fixed-two;cached");
    }
}
