import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.Executors;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Future;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Real managed-executor source with a private faulting ledger, not a guest. */
public final class ManagedReentrantFactoryOwnerControl {
    private static void require(boolean value) { if (!value) throw new AssertionError("managed-factory-owner"); }
    private static void held(int queue, int result, int executor) {
        require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == queue
            && Activation.count(LatentRuntimeActivationOwnerKind.Result) == result
            && Activation.count(LatentRuntimeActivationOwnerKind.Executor) == executor);
    }
    private static void await(CountDownLatch latch) throws InterruptedException { require(latch.await(5, TimeUnit.SECONDS)); }
    private static void capacity() throws Exception {
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicReference<Future<?>> nested = new AtomicReference<>();
        AtomicInteger factories = new AtomicInteger(), active = new AtomicInteger(), maximum = new AtomicInteger();
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        Runnable callback = () -> {
            int now = active.incrementAndGet(); maximum.accumulateAndGet(now, Math::max); entered.countDown();
            try { release.await(); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
            finally { active.decrementAndGet(); }
        };
        var pool = Executors.newFixedThreadPool(1, target -> {
            require(factories.incrementAndGet() == 1);
            nested.set(selected.get().submit(callback));
            held(2, 2, 1);
            require(((Activation.ManagedPool)selected.get()).hasPendingWork());
            return new Thread(target);
        });
        selected.set(pool);
        try {
            var outer = pool.submit(callback);
            await(entered); held(1, 2, 1);
            require(factories.get() == 1 && maximum.get() == 1 && !nested.get().isDone());
            release.countDown();
            outer.get(5, TimeUnit.SECONDS); nested.get().get(5, TimeUnit.SECONDS);
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
        } finally { release.countDown(); pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
        Activation.idle();
    }
    private static void nestedFailure(boolean returnsNull) throws Exception {
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicReference<Future<?>> nested = new AtomicReference<>();
        AtomicInteger factories = new AtomicInteger(), calls = new AtomicInteger();
        var failure = new IllegalStateException("managed-factory-failed");
        var pool = Executors.newFixedThreadPool(1, target -> {
            if (factories.incrementAndGet() == 1) {
                nested.set(selected.get().submit(calls::incrementAndGet));
                if (returnsNull) return null;
                throw failure;
            }
            return new Thread(target);
        });
        selected.set(pool);
        try {
            try { pool.submit(() -> { throw new AssertionError("withdrawn-outer-ran"); });
                throw new AssertionError("missing-factory-failure"); }
            catch (RuntimeException error) { require(returnsNull ? error instanceof RejectedExecutionException : error == failure); }
            require(factories.get() == 1 && nested.get() != null && !nested.get().isDone()
                && ((Activation.ManagedPool)pool).hasPendingWork());
            held(1, 1, 1);
            pool.submit(() -> {}).get(5, TimeUnit.SECONDS);
            nested.get().get(5, TimeUnit.SECONDS);
            require(factories.get() == 2 && calls.get() == 1);
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
        Activation.idle();
    }
    private static void nestedShutdown(String mode) throws Exception {
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicReference<List<Runnable>> removed = new AtomicReference<>();
        var failure = new IllegalStateException("managed-factory-after-shutdown");
        var pool = Executors.newFixedThreadPool(1, target -> {
            ExecutorService current = selected.get();
            removed.set(current.shutdownNow());
            require(removed.get().size() == 1);
            held(0, 0, 1);
            var managed = (Activation.ManagedPool)current;
            require(managed.hasPendingWork() && !managed.isRetired());
            managed.closeAtRoot();
            require(managed.hasPendingWork() && !managed.isRetired());
            if (mode.equals("throw")) throw failure;
            if (mode.equals("null")) return null;
            return new Thread(target);
        });
        selected.set(pool);
        try {
            if (mode.equals("thread")) pool.submit(() -> { throw new AssertionError("withdrawn-work-ran"); });
            else {
                try { pool.submit(() -> { throw new AssertionError("withdrawn-work-ran"); });
                    throw new AssertionError("missing-factory-failure"); }
                catch (RuntimeException error) { require(mode.equals("null") ? error instanceof RejectedExecutionException : error == failure); }
            }
            require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
            var task = (Future<?>)removed.get().get(0);
            require(!task.isDone() && task.cancel(false));
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
        Activation.idle();
    }
    private static void uncertainRetirement(String fault) throws Exception {
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        var original = new IllegalStateException("factory-after-shutdown");
        var pool = Executors.newFixedThreadPool(1, target -> {
            require(selected.get().shutdownNow().size() == 1);
            held(0, 0, 1);
            if (fault.equals("denied")) Activation.denyCloseNext = "Executor";
            else Activation.loseCloseAckNext = "Executor";
            throw original;
        });
        selected.set(pool);
        try { pool.submit(() -> {}); throw new AssertionError("missing-factory-failure"); }
        catch (IllegalStateException error) { require(error == original); }
        var owner = pool.getClass().getDeclaredField("owner"); owner.setAccessible(true);
        require(Activation.poisoned && Activation.retainsOwner((Activation.Lease)owner.get(pool))
            && Activation.closeAttempts(LatentRuntimeActivationOwnerKind.Executor) == 1
            && Activation.failedLeaseAttempts() == 1);
        held(0, 0, fault.equals("denied") ? 1 : 0);
        pool.shutdownNow();
        require(!pool.isTerminated() && Activation.failedLeaseAttempts() == 1);
        // The uncertain original owner remains rooted until Store teardown.
    }
    public static void main(String[] args) throws Exception {
        String mode = args[0];
        switch (mode) {
            case "capacity" -> capacity();
            case "nested-throw" -> nestedFailure(false);
            case "nested-null" -> nestedFailure(true);
            case "shutdown-thread" -> nestedShutdown("thread");
            case "shutdown-null" -> nestedShutdown("null");
            case "shutdown-throw" -> nestedShutdown("throw");
            case "uncertain-denied" -> uncertainRetirement("denied");
            case "uncertain-lost" -> uncertainRetirement("lost");
            default -> throw new IllegalArgumentException(mode);
        }
        System.out.println("MANAGED_REENTRANT_FACTORY_OWNER PASS " + mode);
    }
}
