import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.Executors;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Future;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Real executor source with a private ledger and bounded physical barriers. */
public final class ManagedCachedFactoryOwnerControl {
    private static void require(boolean value, String reason) { if (!value) throw new AssertionError(reason); }
    private static void await(CountDownLatch latch, String reason) throws InterruptedException {
        require(latch.await(5, TimeUnit.SECONDS), reason);
    }
    private static void held(int queue, int result, int executor) {
        require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == queue
            && Activation.count(LatentRuntimeActivationOwnerKind.Result) == result
            && Activation.count(LatentRuntimeActivationOwnerKind.Executor) == executor, "original-owners");
    }
    private static Object worker(Runnable target) throws Exception {
        var field = target.getClass().getDeclaredFields()[0]; field.setAccessible(true); return field.get(target);
    }
    private static void inert(Runnable target) throws Exception {
        Object worker = worker(target);
        for (var field : worker.getClass().getDeclaredFields()) if (!field.getType().isPrimitive()) {
            field.setAccessible(true); require(field.get(worker) == null, "retained-worker-reference");
        }
        target.run();
    }
    private static void nested(String mode) throws Exception {
        var factoryEntered = new CountDownLatch(1); var releaseFactory = new CountDownLatch(1);
        var nestedEntered = new CountDownLatch(1); var releaseNested = new CountDownLatch(1);
        var attempts = new AtomicInteger(); var outerCalls = new AtomicInteger(); var nestedCalls = new AtomicInteger();
        var failure = new AtomicReference<Throwable>(); var outer = new AtomicReference<Future<?>>();
        var target = new AtomicReference<Runnable>(); var marker = new IllegalStateException("outer-factory-failure");
        var pool = Executors.newCachedThreadPool(command -> {
            if (attempts.incrementAndGet() == 1) {
                target.set(command); factoryEntered.countDown();
                try { await(releaseFactory, "factory-release"); } catch (InterruptedException error) { throw new AssertionError(error); }
                if (mode.equals("throw")) throw marker;
                if (mode.equals("null")) return null;
            }
            return new Thread(command);
        });
        var caller = new Thread(() -> {
            try { outer.set(pool.submit(outerCalls::incrementAndGet)); } catch (Throwable error) { failure.set(error); }
        });
        try {
            caller.start(); await(factoryEntered, "factory-not-entered"); held(1, 1, 1);
            Future<?> nested = pool.submit(() -> {
                nestedCalls.incrementAndGet(); nestedEntered.countDown();
                while (true) try { releaseNested.await(); return; } catch (InterruptedException ignored) { }
            });
            await(nestedEntered, "nested-not-running"); held(1, 2, 1);
            require(attempts.get() == 2 && ((Activation.ManagedPool)pool).hasPendingWork(), "nested-growth-or-fence");
            if (mode.equals("graceful")) pool.shutdown();
            if (mode.equals("immediate") || mode.equals("denied") || mode.equals("lost"))
                require(pool.shutdownNow().isEmpty(), "hidden-first-exposed");
            if (mode.equals("denied")) Activation.denyCloseNext = "QueuedWork";
            if (mode.equals("lost")) Activation.loseCloseAckNext = "QueuedWork";
            releaseFactory.countDown(); caller.join(5000);
            require(!caller.isAlive() && outer.get() == null
                && (mode.equals("throw") ? failure.get() == marker : failure.get() instanceof RejectedExecutionException),
                "outer-failure-lost");
            inert(target.get());
            if (mode.equals("denied") || mode.equals("lost")) {
                held(mode.equals("denied") ? 1 : 0, 2, 1);
                require(Activation.poisoned && Activation.retainsFailedQueued() && Activation.failedLeaseAttempts() == 1
                    && ((Activation.ManagedPool)pool).hasPendingWork() && !pool.isTerminated(), "uncertain-first-not-rooted");
                releaseNested.countDown(); nested.get(5, TimeUnit.SECONDS);
                pool.shutdownNow();
                long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
                while (Activation.count(LatentRuntimeActivationOwnerKind.Result) != 1) {
                    require(System.nanoTime() - deadline < 0, "nested-result-not-retired"); Thread.yield();
                }
                held(mode.equals("denied") ? 1 : 0, 1, 1);
                require(Activation.failedLeaseAttempts() == 1 && !pool.isTerminated(), "uncertain-settlement-retried");
                return;
            }
            held(0, 1, 1); require(!nested.isDone() && outerCalls.get() == 0 && nestedCalls.get() == 1, "nested-lost");
            releaseNested.countDown(); nested.get(5, TimeUnit.SECONDS);
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS), "nested-not-retired");
            held(0, 0, 0); Activation.idle();
        } finally { releaseFactory.countDown(); releaseNested.countDown(); caller.join(5000); pool.shutdownNow(); }
    }
    private static void startFailure(boolean uncertain) throws Exception {
        var target = new AtomicReference<Runnable>(); var selected = new AtomicReference<Thread>();
        var starts = new AtomicInteger(); var calls = new AtomicInteger(); var marker = new IllegalStateException("start-failure");
        var pool = Executors.newCachedThreadPool(command -> {
            target.set(command);
            Thread thread = new Thread(command) {
                @Override public synchronized void start() { if (starts.incrementAndGet() == 1) throw marker; super.start(); }
            };
            selected.set(thread); return thread;
        });
        Activation.retainFailedStart = uncertain;
        try {
            try { pool.submit(calls::incrementAndGet); throw new AssertionError("start-failure-missing"); }
            catch (IllegalStateException error) { require(error == marker, "start-error-lost"); }
            if (uncertain) {
                held(1, 1, 1); require(Activation.ownsManaged(selected.get(), (Activation.ManagedPool)pool)
                    && ((Activation.ManagedPool)pool).hasPendingWork() && pool.shutdownNow().isEmpty(), "uncertain-start-exposed");
                selected.get().start(); selected.get().join(5000);
                require(!selected.get().isAlive() && calls.get() == 1 && pool.awaitTermination(5, TimeUnit.SECONDS), "uncertain-start-not-settled");
            } else {
                held(0, 0, 1); inert(target.get());
                require(pool.shutdownNow().isEmpty() && pool.awaitTermination(5, TimeUnit.SECONDS) && calls.get() == 0,
                    "definite-start-not-retired");
            }
            held(0, 0, 0); inert(target.get()); Activation.idle();
        } finally { Activation.retainFailedStart = false; pool.shutdownNow(); }
    }
    private static void duplicate() throws Exception {
        var entered = new CountDownLatch(1); var release = new CountDownLatch(1);
        var firstTarget = new AtomicReference<Runnable>(); var secondTarget = new AtomicReference<Runnable>();
        var selected = new AtomicReference<Thread>(); var result = new AtomicReference<Future<?>>();
        var failure = new AtomicReference<Throwable>(); var attempts = new AtomicInteger(); var calls = new AtomicInteger();
        var pool = Executors.newCachedThreadPool(command -> {
            if (attempts.incrementAndGet() == 1) {
                firstTarget.set(command);
                Thread thread = new Thread(command) {
                    @Override public synchronized void start() {
                        entered.countDown();
                        try { await(release, "start-release"); } catch (InterruptedException error) { throw new AssertionError(error); }
                        super.start();
                    }
                };
                selected.set(thread); return thread;
            }
            secondTarget.set(command); return selected.get();
        });
        var caller = new Thread(() -> {
            try { result.set(pool.submit(calls::incrementAndGet)); } catch (Throwable error) { failure.set(error); }
        });
        try {
            caller.start(); await(entered, "first-start-not-held"); held(1, 1, 1);
            try { pool.submit(calls::incrementAndGet); throw new AssertionError("duplicate-accepted"); }
            catch (IllegalThreadStateException expected) { }
            inert(secondTarget.get()); held(1, 1, 1);
            require(pool.shutdownNow().isEmpty() && ((Activation.ManagedPool)pool).hasPendingWork(), "original-first-exposed");
            release.countDown(); caller.join(5000);
            require(!caller.isAlive() && failure.get() == null && result.get() != null, "original-start-failed");
            result.get().get(5, TimeUnit.SECONDS);
            require(pool.awaitTermination(5, TimeUnit.SECONDS) && calls.get() == 1, "original-first-not-settled");
            held(0, 0, 0); inert(firstTarget.get()); Activation.idle();
        } finally { release.countDown(); caller.join(5000); pool.shutdownNow(); }
    }
    private static void liveThread() throws Exception {
        var entered = new CountDownLatch(1); var release = new CountDownLatch(1);
        var target = new AtomicReference<Runnable>(); var interrupts = new AtomicInteger(); var calls = new AtomicInteger();
        Thread live = new Thread(() -> {
            entered.countDown();
            try { release.await(); } catch (InterruptedException ignored) { }
        }) { @Override public void interrupt() { interrupts.incrementAndGet(); super.interrupt(); } };
        live.start(); await(entered, "live-thread-not-started");
        var pool = Executors.newCachedThreadPool(command -> { target.set(command); return live; });
        try {
            try { pool.submit(calls::incrementAndGet); throw new AssertionError("live-thread-accepted"); }
            catch (IllegalThreadStateException expected) { }
            held(0, 0, 1); inert(target.get());
            require(pool.shutdownNow().isEmpty() && pool.awaitTermination(5, TimeUnit.SECONDS)
                && live.isAlive() && interrupts.get() == 0 && calls.get() == 0, "live-thread-custody");
            held(0, 0, 0); Activation.idle();
        } finally { release.countDown(); live.join(5000); pool.shutdownNow(); }
    }
    private static void replacement(String mode) throws Exception {
        var entered = new CountDownLatch(1); var release = new CountDownLatch(1);
        var helperAccepted = new CountDownLatch(1); var helperRan = new CountDownLatch(1);
        var attempts = new AtomicInteger(); var calls = new AtomicInteger();
        var selected = new AtomicReference<java.util.concurrent.ExecutorService>(); var helper = new AtomicReference<Future<?>>();
        var helperFailure = new AtomicReference<Throwable>(); var workerFailure = new AtomicReference<Throwable>();
        var marker = new IllegalStateException("first-worker-checkpoint");
        var factoryFailure = new IllegalStateException("replacement-factory-failure");
        var pool = Executors.newCachedThreadPool(target -> {
            int attempt = attempts.incrementAndGet();
            if (attempt == 2) {
                if (mode.equals("null")) return null;
                if (mode.equals("throw")) throw factoryFailure;
                var thread = new Thread(() -> {
                    try { helper.set(selected.get().submit(() -> { calls.incrementAndGet(); helperRan.countDown(); })); }
                    catch (Throwable error) { helperFailure.set(error); }
                    finally { helperAccepted.countDown(); }
                });
                thread.start();
                try { await(helperAccepted, "replacement-helper-blocked"); }
                catch (InterruptedException error) { throw new AssertionError(error); }
            }
            Thread thread = new Thread(target); thread.setUncaughtExceptionHandler((ignored, error) -> workerFailure.set(error)); return thread;
        });
        selected.set(pool);
        // Project the existing maximum-worker branch without allocating an
        // unbounded number of real workers. At this synthetic bound, the
        // reentrant helper must be accepted while the replacement is starting.
        var limit = pool.getClass().getDeclaredField("parallelism"); limit.setAccessible(true); limit.setInt(pool, 1);
        Activation.checkpointObservation = () -> {
            entered.countDown();
            try { await(release, "checkpoint-release"); } catch (InterruptedException error) { throw new AssertionError(error); }
            throw marker;
        };
        try {
            pool.submit(() -> {}).get(5, TimeUnit.SECONDS); await(entered, "checkpoint-not-entered");
            var retained = pool.submit(calls::incrementAndGet); held(1, 1, 1);
            require(!retained.isDone() && attempts.get() == 1, "idle-transfer-not-queued");
            release.countDown();
            if (mode.equals("success")) {
                await(helperRan, "helper-not-run"); retained.get(5, TimeUnit.SECONDS); helper.get().get(5, TimeUnit.SECONDS);
                require(helperFailure.get() == null && attempts.get() == 2 && calls.get() == 2, "replacement-growth");
                pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS), "replacement-not-retired");
                held(0, 0, 0); Activation.idle();
            } else {
                long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
                while (workerFailure.get() == null) { require(System.nanoTime() - deadline < 0, "replacement-failure-not-observed"); Thread.yield(); }
                require(mode.equals("throw") ? workerFailure.get() == factoryFailure
                    : workerFailure.get() instanceof RejectedExecutionException, "wrong-replacement-failure");
                held(1, 1, 1); require(((Activation.ManagedPool)pool).hasPendingWork(), "retained-work-not-rooted");
                var removed = pool.shutdownNow(); require(removed.size() == 1 && removed.get(0) == retained && retained.cancel(false), "retained-work-not-withdrawn");
                require(pool.awaitTermination(5, TimeUnit.SECONDS), "withdrawn-work-not-retired"); held(0, 0, 0); Activation.idle();
            }
        } finally { Activation.checkpointObservation = null; release.countDown(); pool.shutdownNow(); }
    }
    public static void main(String[] args) throws Exception {
        switch (args[0]) {
            case "graceful", "immediate", "denied", "lost", "null", "throw" -> nested(args[0]);
            case "definite-start" -> startFailure(false); case "uncertain-start" -> startFailure(true);
            case "duplicate" -> duplicate();
            case "live-thread" -> liveThread();
            case "replacement" -> replacement("success"); case "replacement-null" -> replacement("null");
            case "replacement-throw" -> replacement("throw");
            default -> throw new IllegalArgumentException("mode");
        }
        System.out.println("MANAGED_CACHED_FACTORY_OWNER PASS " + args[0]);
    }
}
