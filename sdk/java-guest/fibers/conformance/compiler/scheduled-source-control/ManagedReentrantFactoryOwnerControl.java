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
        AtomicInteger factories = new AtomicInteger(), calls = new AtomicInteger(), outerCalls = new AtomicInteger();
        var failure = new IllegalStateException("managed-factory-failed");
        var pool = Executors.newFixedThreadPool(1, target -> {
            if (factories.incrementAndGet() == 1) {
                nested.set(selected.get().submit(calls::incrementAndGet));
                if (returnsNull) return null;
                throw failure;
            }
            if (returnsNull && factories.get() == 2) return null;
            return new Thread(target);
        });
        selected.set(pool);
        try {
            Future<?> outer = null;
            if (returnsNull) outer = pool.submit(outerCalls::incrementAndGet);
            else {
                try { pool.submit(outerCalls::incrementAndGet); throw new AssertionError("missing-factory-failure"); }
                catch (IllegalStateException error) { require(error == failure); }
            }
            require(factories.get() == (returnsNull ? 2 : 1) && nested.get() != null && !nested.get().isDone()
                && ((Activation.ManagedPool)pool).hasPendingWork());
            held(returnsNull ? 2 : 1, returnsNull ? 2 : 1, 1);
            pool.submit(() -> {}).get(5, TimeUnit.SECONDS);
            nested.get().get(5, TimeUnit.SECONDS);
            if (outer != null) outer.get(5, TimeUnit.SECONDS);
            require(factories.get() == (returnsNull ? 3 : 2) && calls.get() == 1
                && outerCalls.get() == (returnsNull ? 1 : 0));
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
            if (!mode.equals("throw")) pool.submit(() -> { throw new AssertionError("withdrawn-work-ran"); });
            else {
                try { pool.submit(() -> { throw new AssertionError("withdrawn-work-ran"); });
                    throw new AssertionError("missing-factory-failure"); }
                catch (RuntimeException error) { require(error == failure); }
            }
            require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
            var task = (Future<?>)removed.get().get(0);
            require(!task.isDone() && task.cancel(false));
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
        Activation.idle();
    }
    private static void gracefulSole(String mode) throws Exception {
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicReference<Runnable> target = new AtomicReference<>();
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        String[] fault = mode.split("-", 2);
        var pool = Executors.newFixedThreadPool(1, command -> {
            attempts.incrementAndGet(); target.set(command);
            selected.get().shutdown();
            if (fault.length == 2) {
                String kind = switch (fault[0]) { case "queue" -> "QueuedWork"; case "result" -> "Result"; default -> "Executor"; };
                if (fault[1].equals("denied")) Activation.denyCloseNext = kind;
                else Activation.loseCloseAckNext = kind;
            }
            return mode.equals("thread") ? new Thread(command) : null;
        });
        selected.set(pool);
        try { pool.submit(calls::incrementAndGet); throw new AssertionError("accepted-graceful-sole"); }
        catch (RejectedExecutionException expected) { require(expected.getMessage().equals("activation-executor-closed")); }
        require(attempts.get() == 1 && calls.get() == 0 && pool.isShutdown());
        var capture = target.get().getClass().getDeclaredFields()[0]; capture.setAccessible(true);
        Object worker = capture.get(target.get());
        var owner = worker.getClass().getDeclaredField("pool"); owner.setAccessible(true);
        require(owner.get(worker) == null); target.get().run(); require(calls.get() == 0);
        if (fault.length == 1) {
            require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0); Activation.idle();
        } else {
            require(Activation.poisoned && Activation.failedLeaseAttempts() == 1 && !pool.isTerminated());
            held(fault[0].equals("queue") && fault[1].equals("denied") ? 1 : 0,
                fault[0].equals("queue") || fault[0].equals("result") && fault[1].equals("denied") ? 1 : 0,
                fault[0].equals("executor") && fault[1].equals("lost") ? 0 : 1);
            // The uncertain original settlement is not retried; Store teardown owns it.
        }
    }
    private static void gracefulNested(boolean returnsNull) throws Exception {
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicReference<Future<?>> nested = new AtomicReference<>();
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        var pool = Executors.newFixedThreadPool(1, command -> {
            if (attempts.incrementAndGet() == 1) {
                nested.set(selected.get().submit(() -> {
                    calls.incrementAndGet(); entered.countDown();
                    try { release.await(); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
                }));
                selected.get().shutdown(); return returnsNull ? null : new Thread(command);
            }
            return new Thread(command);
        });
        selected.set(pool);
        try {
            var outer = pool.submit(calls::incrementAndGet);
            await(entered);
            if (returnsNull) { require(attempts.get() == 2 && !outer.isDone()); held(1, 2, 1); }
            else { outer.get(5, TimeUnit.SECONDS); require(attempts.get() == 1); held(0, 1, 1); }
            release.countDown(); nested.get().get(5, TimeUnit.SECONDS); outer.get(5, TimeUnit.SECONDS);
            require(calls.get() == 2 && pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
        } finally { release.countDown(); pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
        Activation.idle();
    }
    private static void gracefulSharedResult() throws Exception {
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        var task = new dev.latent.guest.runtime.concurrent.FutureTask<>(() -> {
            entered.countDown();
            while (true) try { release.await(); return 42; } catch (InterruptedException ignored) { }
        });
        var first = Executors.newFixedThreadPool(1);
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        var second = Executors.newFixedThreadPool(1, target -> { selected.get().shutdown(); return null; });
        selected.set(second);
        try {
            first.execute(task); await(entered);
            try { second.execute(task); throw new AssertionError("accepted-graceful-shared-copy"); }
            catch (RejectedExecutionException expected) { }
            require(second.awaitTermination(5, TimeUnit.SECONDS) && !task.isDone()); held(0, 1, 1);
            release.countDown(); require(task.get(5, TimeUnit.SECONDS) == 42);
            first.shutdown(); require(first.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
        } finally {
            release.countDown(); first.shutdownNow(); second.shutdownNow();
            require(first.awaitTermination(5, TimeUnit.SECONDS) && second.awaitTermination(5, TimeUnit.SECONDS));
        }
        Activation.idle();
    }
    private static void gracefulCompletable() throws Exception {
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicInteger calls = new AtomicInteger();
        var pool = Executors.newFixedThreadPool(1, target -> { selected.get().shutdown(); return null; });
        selected.set(pool);
        var result = new dev.latent.guest.runtime.concurrent.CompletableFuture<Integer>();
        try {
            result.completeAsync(() -> { calls.incrementAndGet(); return 42; }, pool);
            throw new AssertionError("accepted-graceful-completable");
        } catch (RejectedExecutionException expected) { }
        require(calls.get() == 0 && !result.isDone() && pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
        require(result.complete(7) && result.get() == 7); Activation.idle();
    }
    private static void gracefulAlreadyRunning(boolean returnsNull) throws Exception {
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        CountDownLatch firstEntered = new CountDownLatch(1), releaseFirst = new CountDownLatch(1);
        CountDownLatch outerEntered = new CountDownLatch(1), releaseOuter = new CountDownLatch(1);
        var pool = Executors.newFixedThreadPool(2, target -> {
            if (attempts.incrementAndGet() == 1) return new Thread(target);
            releaseFirst.countDown();
            Object monitor = selected.get();
            synchronized (monitor) {
                long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
                while (outerEntered.getCount() != 0) {
                    long remaining = deadline - System.nanoTime();
                    if (remaining <= 0) throw new AssertionError("outer-did-not-start");
                    try { TimeUnit.NANOSECONDS.timedWait(monitor, remaining); }
                    catch (InterruptedException error) { throw new AssertionError(error); }
                }
            }
            selected.get().shutdown();
            return returnsNull ? null : new Thread(target);
        });
        selected.set(pool);
        try {
            var first = pool.submit(() -> {
                firstEntered.countDown();
                try { releaseFirst.await(); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
            });
            await(firstEntered);
            var outer = pool.submit(() -> {
                calls.incrementAndGet(); outerEntered.countDown();
                synchronized (selected.get()) { selected.get().notifyAll(); }
                while (true) try { releaseOuter.await(); return; } catch (InterruptedException ignored) { }
            });
            first.get(5, TimeUnit.SECONDS);
            require(attempts.get() == 2 && calls.get() == 1 && !outer.isDone() && pool.isShutdown()); held(0, 1, 1);
            releaseOuter.countDown(); outer.get(5, TimeUnit.SECONDS);
            require(pool.awaitTermination(5, TimeUnit.SECONDS) && calls.get() == 1); held(0, 0, 0);
        } finally {
            releaseFirst.countDown(); releaseOuter.countDown();
            pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS));
        }
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
            case "graceful-null" -> gracefulSole("null");
            case "graceful-thread" -> gracefulSole("thread");
            case "graceful-queue-denied" -> gracefulSole("queue-denied");
            case "graceful-queue-lost" -> gracefulSole("queue-lost");
            case "graceful-result-denied" -> gracefulSole("result-denied");
            case "graceful-result-lost" -> gracefulSole("result-lost");
            case "graceful-executor-denied" -> gracefulSole("executor-denied");
            case "graceful-executor-lost" -> gracefulSole("executor-lost");
            case "graceful-nested" -> gracefulNested(true);
            case "graceful-nested-thread" -> gracefulNested(false);
            case "graceful-shared-result" -> gracefulSharedResult();
            case "graceful-completable" -> gracefulCompletable();
            case "graceful-running-null" -> gracefulAlreadyRunning(true);
            case "graceful-running-thread" -> gracefulAlreadyRunning(false);
            case "uncertain-denied" -> uncertainRetirement("denied");
            case "uncertain-lost" -> uncertainRetirement("lost");
            default -> throw new IllegalArgumentException(mode);
        }
        System.out.println("MANAGED_REENTRANT_FACTORY_OWNER PASS " + mode);
    }
}
