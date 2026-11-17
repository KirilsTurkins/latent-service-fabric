import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.CompletableFuture;
import dev.latent.guest.runtime.concurrent.Executors;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Future;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Managed source and private ledger; no host or guest qualification. */
public final class ManagedNullFactoryOwnerControl {
    private static void require(boolean value) { if (!value) throw new AssertionError("managed-null-factory-owner"); }
    private static void held(int queue, int result, int executor) {
        require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == queue
            && Activation.count(LatentRuntimeActivationOwnerKind.Result) == result
            && Activation.count(LatentRuntimeActivationOwnerKind.Executor) == executor);
    }
    private static void await(CountDownLatch latch) throws InterruptedException { require(latch.await(5, TimeUnit.SECONDS)); }
    private static void inert(Runnable target) throws Exception {
        var capture = target.getClass().getDeclaredFields()[0]; capture.setAccessible(true);
        Object worker = capture.get(target);
        var field = worker.getClass().getDeclaredField("pool"); field.setAccessible(true);
        require(field.get(worker) == null); target.run();
    }
    private static void unavailable() throws Exception {
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        AtomicReference<Runnable> first = new AtomicReference<>(), second = new AtomicReference<>();
        var pool = Executors.newFixedThreadPool(1, target -> {
            if (attempts.incrementAndGet() == 1) first.set(target); else second.set(target);
            return null;
        });
        var future = pool.submit(calls::incrementAndGet);
        require(attempts.get() == 2 && !future.isDone() && ((Activation.ManagedPool)pool).hasPendingWork());
        held(1, 1, 1); inert(first.get()); inert(second.get()); require(calls.get() == 0);
        List<Runnable> removed = pool.shutdownNow();
        require(removed.size() == 1 && removed.get(0) == future && !future.isDone());
        require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
        require(future.cancel(false)); Activation.idle();
    }
    private static void recovery(boolean later) throws Exception {
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        var pool = Executors.newFixedThreadPool(1, target -> attempts.incrementAndGet() <= (later ? 2 : 1) ? null : new Thread(target));
        try {
            var first = pool.submit(() -> {
                calls.incrementAndGet(); entered.countDown();
                try { release.await(); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
            });
            Future<?> second = null;
            if (later) {
                require(attempts.get() == 2 && !first.isDone()); held(1, 1, 1);
                second = pool.submit(calls::incrementAndGet);
            }
            await(entered);
            require(attempts.get() == (later ? 3 : 2));
            held(later ? 1 : 0, later ? 2 : 1, 1);
            release.countDown(); first.get(5, TimeUnit.SECONDS);
            if (second != null) second.get(5, TimeUnit.SECONDS);
            require(calls.get() == (later ? 2 : 1));
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
        } finally { release.countDown(); pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
        Activation.idle();
    }
    private static void fallbackThrow() throws Exception {
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        CountDownLatch originalRan = new CountDownLatch(1);
        var failure = new IllegalStateException("fallback-factory-failed");
        var pool = Executors.newFixedThreadPool(1, target -> {
            int attempt = attempts.incrementAndGet();
            if (attempt == 1) return null;
            if (attempt == 2) throw failure;
            return new Thread(target);
        });
        try {
            try { pool.submit(() -> { calls.incrementAndGet(); originalRan.countDown(); }); throw new AssertionError("missing-fallback-failure"); }
            catch (IllegalStateException error) { require(error == failure); }
            require(attempts.get() == 2 && calls.get() == 0 && ((Activation.ManagedPool)pool).hasPendingWork());
            held(1, 1, 1);
            pool.submit(() -> {}).get(5, TimeUnit.SECONDS); await(originalRan);
            require(calls.get() == 1 && attempts.get() == 3);
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
        Activation.idle();
    }
    private static void cached() throws Exception {
        AtomicInteger attempts = new AtomicInteger();
        var pool = Executors.newCachedThreadPool(target -> { attempts.incrementAndGet(); return null; });
        try {
            try { pool.submit(() -> {}); throw new AssertionError("cached-accepted-null"); }
            catch (RejectedExecutionException expected) { require(attempts.get() == 1); }
            held(0, 0, 1);
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
        held(0, 0, 0); Activation.idle();
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
            await(entered); held(0, 1, 1);
            var second = pool.submit(calls::incrementAndGet);
            require(attempts.get() == 2 && !second.isDone()); held(1, 2, 1);
            release.countDown(); first.get(5, TimeUnit.SECONDS); second.get(5, TimeUnit.SECONDS);
            require(calls.get() == 1 && attempts.get() == 2);
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
        } finally { release.countDown(); pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
        Activation.idle();
    }
    private static void nestedFallbackThrow() throws Exception {
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicReference<Future<?>> nested = new AtomicReference<>();
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        CountDownLatch originalRan = new CountDownLatch(1);
        var failure = new IllegalStateException("nested-fallback-failed");
        var pool = Executors.newFixedThreadPool(1, target -> {
            int attempt = attempts.incrementAndGet();
            if (attempt == 1) return null;
            if (attempt == 2) {
                nested.set(selected.get().submit(calls::incrementAndGet));
                held(2, 2, 1);
                throw failure;
            }
            return new Thread(target);
        });
        selected.set(pool);
        try {
            try { pool.submit(() -> { calls.incrementAndGet(); originalRan.countDown(); });
                throw new AssertionError("missing-factory-failure"); }
            catch (IllegalStateException error) { require(error == failure); }
            require(attempts.get() == 2 && nested.get() != null && !nested.get().isDone());
            held(2, 2, 1);
            pool.submit(() -> {}).get(5, TimeUnit.SECONDS);
            nested.get().get(5, TimeUnit.SECONDS); await(originalRan);
            require(calls.get() == 2 && attempts.get() == 3);
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
        Activation.idle();
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
            catch (IllegalStateException error) { require(error == failure); }
            require(!result.isDone() && calls.get() == 0 && attempts.get() == 2); held(2, 1, 1);
            pool.submit(() -> {}).get(5, TimeUnit.SECONDS);
            require(result.get(5, TimeUnit.SECONDS) == 42 && calls.get() == 1 && attempts.get() == 3);
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
        Activation.idle();
    }
    private static void fallbackStartFailure(boolean uncertain) throws Exception {
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        AtomicReference<Thread> worker = new AtomicReference<>();
        AtomicReference<Runnable> target = new AtomicReference<>();
        var failure = new IllegalStateException("fallback-worker-start-failed");
        var pool = Executors.newFixedThreadPool(1, command -> {
            int attempt = attempts.incrementAndGet();
            if (attempt == 1) return null;
            if (attempt == 2) {
                target.set(command);
                Thread thread = new Thread(command) { @Override public void start() { throw failure; } };
                worker.set(thread); return thread;
            }
            return new Thread(command);
        });
        Activation.retainFailedStart = uncertain;
        try {
            try { pool.submit(calls::incrementAndGet); throw new AssertionError("missing-start-failure"); }
            catch (IllegalStateException error) { require(error == failure); }
            require(attempts.get() == 2 && calls.get() == 0 && ((Activation.ManagedPool)pool).hasPendingWork());
            held(1, 1, 1);
            if (uncertain) {
                require(Activation.recorded(worker.get(), (Activation.ManagedPool)pool));
                var capture = target.get().getClass().getDeclaredFields()[0]; capture.setAccessible(true);
                Object heldWorker = capture.get(target.get());
                var owner = heldWorker.getClass().getDeclaredField("pool"); owner.setAccessible(true);
                require(owner.get(heldWorker) == pool);
                List<Runnable> removed = pool.shutdownNow();
                require(removed.size() == 1 && !((Future<?>)removed.get(0)).isDone());
                held(0, 0, 1); require(!pool.isTerminated() && ((Future<?>)removed.get(0)).cancel(false));
                // The uncertain worker and executor remain owned until teardown.
                return;
            }
            inert(target.get());
            pool.submit(() -> {}).get(5, TimeUnit.SECONDS);
            require(attempts.get() == 3 && calls.get() == 1);
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
        } finally {
            Activation.retainFailedStart = false;
            if (!uncertain) { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
        }
        Activation.idle();
    }
    private static void fallbackLiveThread() throws Exception {
        CountDownLatch liveEntered = new CountDownLatch(1), liveRelease = new CountDownLatch(1), originalRan = new CountDownLatch(1);
        Thread live = new Thread(() -> {
            liveEntered.countDown();
            try { liveRelease.await(); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
        });
        live.start(); await(liveEntered);
        AtomicInteger attempts = new AtomicInteger();
        var pool = Executors.newFixedThreadPool(1, target -> {
            int attempt = attempts.incrementAndGet();
            if (attempt == 1) return null;
            return attempt == 2 ? live : new Thread(target);
        });
        try {
            try { pool.submit(originalRan::countDown); throw new AssertionError("accepted-live-thread"); }
            catch (IllegalThreadStateException expected) { require(attempts.get() == 2 && live.isAlive()); }
            held(1, 1, 1);
            pool.submit(() -> {}).get(5, TimeUnit.SECONDS); await(originalRan);
            require(attempts.get() == 3 && live.isAlive() && !live.isInterrupted());
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
        } finally {
            liveRelease.countDown(); live.join(5000); require(!live.isAlive());
            pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS));
        }
        Activation.idle();
    }
    private static void fallbackShutdown(String fault) throws Exception {
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicReference<List<Runnable>> removed = new AtomicReference<>();
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        var failure = new IllegalStateException("factory-after-shutdown");
        var pool = Executors.newFixedThreadPool(1, target -> {
            if (attempts.incrementAndGet() == 1) return null;
            if (fault.equals("denied")) Activation.denyCloseNext = "QueuedWork";
            if (fault.equals("lost")) Activation.loseCloseAckNext = "QueuedWork";
            removed.set(selected.get().shutdownNow());
            held(0, 0, 1);
            require(((Activation.ManagedPool)selected.get()).hasPendingWork());
            throw failure;
        });
        selected.set(pool);
        try {
            try { pool.submit(calls::incrementAndGet); throw new AssertionError("missing-shutdown-failure"); }
            catch (IllegalStateException error) {
                require(fault.equals("none") ? error == failure : error.getMessage().startsWith("source-owner-settlement-"));
            }
            require(attempts.get() == 2 && calls.get() == 0);
            if (fault.equals("none")) {
                require(removed.get().size() == 1 && pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
                var future = (Future<?>)removed.get().get(0);
                require(!future.isDone() && future.cancel(false)); Activation.idle();
            } else {
                require(Activation.poisoned && Activation.retainsFailedQueued() && Activation.failedLeaseAttempts() == 1);
                held(fault.equals("denied") ? 1 : 0, 1, 0);
                pool.shutdownNow();
                require(Activation.failedLeaseAttempts() == 1);
                // The original uncertain queued and result owners remain charged until Store teardown.
            }
        } finally { pool.shutdownNow(); }
    }
    public static void main(String[] args) throws Exception {
        String mode = args[0];
        switch (mode) {
            case "unavailable" -> unavailable();
            case "immediate-recovery" -> recovery(false);
            case "later-recovery" -> recovery(true);
            case "fallback-throw" -> fallbackThrow();
            case "nested-fallback-throw" -> nestedFallbackThrow();
            case "fallback-completable" -> fallbackCompletable();
            case "fallback-start-failure" -> fallbackStartFailure(false);
            case "fallback-start-uncertain" -> fallbackStartFailure(true);
            case "fallback-live-thread" -> fallbackLiveThread();
            case "cached-null" -> cached();
            case "existing-worker" -> existingWorker();
            case "fallback-shutdown" -> fallbackShutdown("none");
            case "fallback-denied" -> fallbackShutdown("denied");
            case "fallback-lost" -> fallbackShutdown("lost");
            default -> throw new IllegalArgumentException(mode);
        }
        System.out.println("MANAGED_NULL_FACTORY_OWNER PASS " + mode);
    }
}
