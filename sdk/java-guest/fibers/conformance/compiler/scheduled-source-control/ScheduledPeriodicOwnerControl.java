import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.CompletableFuture;
import dev.latent.guest.runtime.concurrent.Executors;
import dev.latent.guest.runtime.concurrent.ScheduledThreadPoolExecutor;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Actual SDK source and private ledger; no signed guest execution. */
public final class ScheduledPeriodicOwnerControl {
    private static void require(boolean value) { if (!value) throw new AssertionError("scheduled-periodic-owner"); }
    private static void held(int queued, int results) {
        require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == queued);
        require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == results);
    }
    private static void await(CountDownLatch latch) throws InterruptedException { require(latch.await(5, TimeUnit.SECONDS)); }
    private static void hold(CountDownLatch entered, CountDownLatch release) {
        entered.countDown();
        while (true) try { release.await(); return; } catch (InterruptedException ignored) { }
    }
    private static void stop(ScheduledThreadPoolExecutor pool) throws InterruptedException {
        pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS));
    }
    private static void entries(List<Runnable> entries, ScheduledFuture<?> task, int count) {
        require(entries.size() == count);
        for (Runnable entry : entries) require(entry == task);
    }
    private static void failNextQueueInsert(ScheduledThreadPoolExecutor pool, boolean after, RuntimeException failure) throws Exception {
        var field = pool.getClass().getDeclaredField("queue"); field.setAccessible(true);
        var old = (java.util.ArrayList<?>)field.get(pool);
        var replacement = new java.util.ArrayList<Object>(old) {
            boolean armed = true;
            @Override public boolean add(Object value) {
                if (armed) {
                    armed = false;
                    if (after) super.add(value);
                    throw failure;
                }
                return super.add(value);
            }
        };
        field.set(pool, replacement);
    }
    private static void failUncertainInsert(ScheduledThreadPoolExecutor pool, RuntimeException failure) throws Exception {
        var field = pool.getClass().getDeclaredField("queue"); field.setAccessible(true);
        var old = (java.util.ArrayList<?>)field.get(pool);
        var replacement = new java.util.ArrayList<Object>(old) {
            @Override public boolean add(Object value) { super.add(value); throw failure; }
            @Override public boolean remove(Object value) { throw new IllegalStateException("uncertain-removal"); }
        };
        field.set(pool, replacement);
    }
    private static void copies() throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        AtomicInteger calls = new AtomicInteger();
        try {
            var future = pool.scheduleAtFixedRate(calls::incrementAndGet, 1, 1, TimeUnit.DAYS);
            held(1, 1); ((Runnable)future).run(); held(2, 1); ((Runnable)future).run(); held(3, 1);
            require(calls.get() == 2 && !future.isDone());
            var returned = pool.shutdownNow(); entries(returned, future, 3);
            require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0);
            returned.get(0).run(); require(future.isCancelled() && calls.get() == 2);
        } finally { stop(pool); }
        Activation.idle();
    }
    private static void denial() throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        AtomicInteger calls = new AtomicInteger();
        try {
            var future = pool.scheduleAtFixedRate(calls::incrementAndGet, 1, 1, TimeUnit.DAYS);
            Activation.denyNext = "QueuedWork";
            try { ((Runnable)future).run(); throw new AssertionError("missing-copy-refusal"); }
            catch (IllegalStateException expected) { require(expected.getMessage().equals("source-owner-admission-denied")); }
            require(calls.get() == 1 && !future.isDone()); held(1, 1);
            ((Runnable)future).run(); require(calls.get() == 2 && !future.isDone()); held(2, 1);
            require(future.cancel(false)); held(0, 0);
        } finally { Activation.denyNext = null; stop(pool); }
        Activation.idle();
    }
    private static void completedFailure() throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        AtomicInteger calls = new AtomicInteger();
        var original = new IllegalStateException("periodic-callback-failure");
        try {
            var future = pool.scheduleAtFixedRate(() -> {
                if (calls.incrementAndGet() == 2) throw original;
            }, 1, 1, TimeUnit.DAYS);
            ((Runnable)future).run(); held(2, 1);
            ((Runnable)future).run();
            require(calls.get() == 2 && future.isDone() && !pool.hasPendingWork()); held(0, 0);
            try { future.get(); throw new AssertionError("missing-callback-failure"); }
            catch (java.util.concurrent.ExecutionException expected) { require(expected.getCause() == original); }
            require(pool.shutdownNow().isEmpty()); require(pool.awaitTermination(5, TimeUnit.SECONDS));
        } finally { stop(pool); }
        Activation.idle();
    }
    private static void failedInsertion() throws Exception {
        for (boolean after : new boolean[]{false, true}) {
            var original = new IllegalStateException("periodic-insertion-failure");
            var empty = new ScheduledThreadPoolExecutor(1);
            try {
                synchronized (empty) { failNextQueueInsert(empty, after, original); }
                try { empty.schedule(() -> { }, 1, TimeUnit.DAYS); throw new AssertionError("missing-initial-failure"); }
                catch (IllegalStateException expected) { require(expected == original); }
                held(0, 0); require(!empty.hasPendingWork());
            } finally { stop(empty); }
            Activation.idle();

            var pool = new ScheduledThreadPoolExecutor(1);
            AtomicInteger calls = new AtomicInteger();
            try {
                var future = pool.scheduleAtFixedRate(calls::incrementAndGet, 1, 1, TimeUnit.DAYS);
                long before = future.getDelay(TimeUnit.HOURS);
                synchronized (pool) { failNextQueueInsert(pool, after, original); }
                try { ((Runnable)future).run(); throw new AssertionError("missing-manual-failure"); }
                catch (IllegalStateException expected) { require(expected == original); }
                require(calls.get() == 1 && !future.isDone()); held(1, 1);
                require(future.getDelay(TimeUnit.HOURS) <= before + 1);
                entries(pool.shutdownNow(), future, 1); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0);
            } finally { stop(pool); }
            Activation.idle();
        }
    }
    private static void failedWorkerRequeue() throws Exception {
        for (boolean after : new boolean[]{false, true}) {
            var original = new IllegalStateException("worker-requeue-failure");
            AtomicReference<Thread> worker = new AtomicReference<>();
            AtomicReference<Throwable> observed = new AtomicReference<>();
            var pool = new ScheduledThreadPoolExecutor(1, target -> {
                Thread thread = new Thread(target); worker.set(thread);
                thread.setUncaughtExceptionHandler((ignored, error) -> observed.set(error)); return thread;
            });
            CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
            AtomicInteger calls = new AtomicInteger();
            try {
                var future = pool.scheduleAtFixedRate(() -> { calls.incrementAndGet(); hold(entered, release); }, 0, 1, TimeUnit.DAYS);
                await(entered); held(1, 1);
                synchronized (pool) { failNextQueueInsert(pool, after, original); }
                release.countDown(); worker.get().join(5000); require(!worker.get().isAlive());
                require(observed.get() == original && calls.get() == 1 && future.isCancelled()); held(0, 0);
                pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS));
            } finally { release.countDown(); stop(pool); }
            Activation.idle();
        }
    }
    private static void uncertainInsertion() throws Exception {
        var original = new IllegalStateException("uncertain-insertion");
        var empty = new ScheduledThreadPoolExecutor(1);
        try {
            synchronized (empty) { failUncertainInsert(empty, original); }
            try { empty.schedule(() -> { }, 1, TimeUnit.DAYS); throw new AssertionError("missing-initial-failure"); }
            catch (IllegalStateException expected) { require(expected == original); }
            held(1, 1); require(empty.hasPendingWork());
            require(empty.shutdownNow().size() == 1); require(empty.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0);
        } finally { stop(empty); }
        Activation.idle();

        var pool = new ScheduledThreadPoolExecutor(1);
        AtomicInteger calls = new AtomicInteger();
        try {
            var future = pool.scheduleAtFixedRate(calls::incrementAndGet, 1, 1, TimeUnit.DAYS);
            synchronized (pool) { failUncertainInsert(pool, original); }
            try { ((Runnable)future).run(); throw new AssertionError("missing-manual-failure"); }
            catch (IllegalStateException expected) { require(expected == original); }
            require(calls.get() == 1 && !future.isDone() && pool.hasPendingWork()); held(2, 1);
            entries(pool.shutdownNow(), future, 2); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0);
        } finally { stop(pool); }
        Activation.idle();
    }
    private static void manualWinsWorker(boolean denyNewCopy) throws Exception {
        CountDownLatch workerGo = new CountDownLatch(1), entered = new CountDownLatch(1), release = new CountDownLatch(1);
        var pool = new ScheduledThreadPoolExecutor(1, target -> new Thread(() -> {
            while (true) try { workerGo.await(); break; } catch (InterruptedException ignored) { }
            target.run();
        }));
        AtomicInteger calls = new AtomicInteger();
        AtomicReference<Throwable> failure = new AtomicReference<>();
        var future = pool.scheduleAtFixedRate(() -> { calls.incrementAndGet(); hold(entered, release); }, 0, 1, TimeUnit.DAYS);
        Thread caller = new Thread((Runnable)future);
        caller.setUncaughtExceptionHandler((thread, error) -> failure.set(error));
        try {
            caller.start(); await(entered); held(1, 1); workerGo.countDown();
            long start = System.nanoTime();
            while (pool.hasPendingWork()) { require(System.nanoTime() - start < TimeUnit.SECONDS.toNanos(5)); Thread.yield(); }
            // The worker consumed its copy without entering the already-running
            // callable. The manual invocation still physically owns the Result.
            held(0, 1); require(calls.get() == 1 && !future.isDone());
            Activation.denyNext = denyNewCopy ? "QueuedWork" : "Result";
            release.countDown(); caller.join(5000); require(!caller.isAlive());
            if (denyNewCopy) {
                require(failure.get() instanceof IllegalStateException
                    && failure.get().getMessage().equals("source-owner-admission-denied") && future.isCancelled());
                held(0, 0);
            } else {
                require(failure.get() == null && "Result".equals(Activation.denyNext)); Activation.denyNext = null;
                held(1, 1); require(!future.isDone());
                entries(pool.shutdownNow(), future, 1); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0);
            }
        } finally { Activation.denyNext = null; workerGo.countDown(); release.countDown(); caller.join(5000); stop(pool); }
        Activation.idle();
    }
    private static void manualStopped(boolean cancel) throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicInteger calls = new AtomicInteger();
        var future = pool.scheduleAtFixedRate(() -> { calls.incrementAndGet(); hold(entered, release); }, 1, 1, TimeUnit.DAYS);
        Thread caller = new Thread((Runnable)future);
        try {
            caller.start(); await(entered); held(1, 1);
            if (cancel) require(future.cancel(false));
            else entries(pool.shutdownNow(), future, 1);
            held(0, 1); release.countDown(); caller.join(5000); require(!caller.isAlive());
            require(calls.get() == 1 && future.isCancelled()); held(0, 0);
        } finally { release.countDown(); caller.join(5000); stop(pool); }
        Activation.idle();
    }
    private static void workerRunning() throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicInteger calls = new AtomicInteger();
        var future = pool.scheduleAtFixedRate(() -> { calls.incrementAndGet(); hold(entered, release); }, 0, 1, TimeUnit.DAYS);
        try {
            await(entered); held(1, 1); ((Runnable)future).run(); held(1, 1);
            require(calls.get() == 1 && future.cancel(false)); held(1, 1);
            release.countDown(); pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0);
        } finally { release.countDown(); stop(pool); }
        Activation.idle();
    }
    private static void managedWrapper() throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        var managed = Executors.newSingleThreadExecutor();
        AtomicInteger calls = new AtomicInteger();
        try {
            var future = pool.scheduleAtFixedRate(calls::incrementAndGet, 1, 1, TimeUnit.DAYS);
            managed.execute((Runnable)future);
            managed.submit(() -> { }).get(5, TimeUnit.SECONDS);
            managed.shutdown(); require(managed.awaitTermination(5, TimeUnit.SECONDS));
            require(calls.get() == 1 && !future.isDone()); held(2, 1);
            entries(pool.shutdownNow(), future, 2); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0);
        } finally {
            managed.shutdownNow(); require(managed.awaitTermination(5, TimeUnit.SECONDS)); stop(pool);
        }
        Activation.idle();
    }
    private static void opaqueRunning() throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicReference<Runnable> saved = new AtomicReference<>();
        AtomicReference<ScheduledFuture<?>> selected = new AtomicReference<>();
        AtomicInteger calls = new AtomicInteger();
        var result = CompletableFuture.supplyAsync(() -> { calls.incrementAndGet(); hold(entered, release); return 42; }, action -> {
            saved.set(action); selected.set(pool.scheduleAtFixedRate(action, 1, 1, TimeUnit.DAYS));
        });
        Thread caller = new Thread((Runnable)selected.get());
        try {
            held(2, 2); caller.start(); await(entered);
            entries(pool.shutdownNow(), selected.get(), 1); held(1, 2);
            release.countDown(); caller.join(5000); require(!caller.isAlive());
            require(result.join() == 42 && calls.get() == 1); held(0, 0);
            saved.get().run(); require(calls.get() == 1); held(0, 0);
        } finally { release.countDown(); caller.join(5000); stop(pool); }
        Activation.idle();
    }
    private static final class CollidingFuture extends dev.latent.guest.runtime.concurrent.FutureTask<Integer> {
        private final AtomicInteger accidentalCalls;
        CollidingFuture(ScheduledThreadPoolExecutor pool, AtomicInteger callbacks, AtomicInteger accidentalCalls) {
            super(() -> { pool.execute(callbacks::incrementAndGet); return 42; });
            this.accidentalCalls = accidentalCalls;
        }
        // Existing application-private methods of these names are unrelated
        // to the package-internal final ownership operations.
        private boolean hasAdditionalPhysicalClaim() { accidentalCalls.incrementAndGet(); return false; }
        private void beginInternalPhysicalClaim() { accidentalCalls.incrementAndGet(); }
        private void endInternalPhysicalClaim() { accidentalCalls.incrementAndGet(); }
        private boolean hasInternalPhysicalClaim() { accidentalCalls.incrementAndGet(); return false; }
    }
    private static void subclassReentrancy() throws Exception {
        var futureClass = dev.latent.guest.runtime.concurrent.FutureTask.class;
        for (String name : new String[]{"beginInternalPhysicalClaim", "endInternalPhysicalClaim", "hasInternalPhysicalClaim"}) {
            int modifiers = futureClass.getDeclaredMethod(name).getModifiers();
            require(java.lang.reflect.Modifier.isFinal(modifiers) && !java.lang.reflect.Modifier.isPublic(modifiers)
                && !java.lang.reflect.Modifier.isProtected(modifiers));
        }
        var pool = new ScheduledThreadPoolExecutor(1);
        AtomicInteger callbacks = new AtomicInteger(), accidental = new AtomicInteger();
        try {
            var nested = new CollidingFuture(pool, callbacks, accidental);
            pool.schedule(nested, 0, TimeUnit.NANOSECONDS).get(5, TimeUnit.SECONDS);
            require(nested.get() == 42);
            pool.submit(() -> { }).get(5, TimeUnit.SECONDS);
            require(callbacks.get() == 1 && accidental.get() == 0);
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0);
        } finally { stop(pool); }
        Activation.idle();
    }
    private static void reentrantFactoryRollback() throws Exception {
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        AtomicReference<ScheduledFuture<?>> selected = new AtomicReference<>();
        var failure = new IllegalStateException("periodic-factory-failure");
        var pool = new ScheduledThreadPoolExecutor(2, target -> {
            int attempt = attempts.incrementAndGet();
            if (attempt == 2) { ((Runnable)selected.get()).run(); throw failure; }
            return new Thread(target);
        });
        try {
            var future = pool.scheduleAtFixedRate(calls::incrementAndGet, 1, 1, TimeUnit.DAYS);
            selected.set(future); long before = future.getDelay(TimeUnit.HOURS);
            try { ((Runnable)future).run(); throw new AssertionError("missing-factory-failure"); }
            catch (IllegalStateException expected) { require(expected == failure); }
            require(attempts.get() == 3 && calls.get() == 2 && !future.isDone());
            require(future.getDelay(TimeUnit.HOURS) >= before + 47); held(2, 1);
            entries(pool.shutdownNow(), future, 2); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0);
        } finally { stop(pool); }
        Activation.idle();
    }
    private static void deniedSettlementRemainsCharged() {
        AtomicReference<ScheduledThreadPoolExecutor> selected = new AtomicReference<>();
        AtomicInteger calls = new AtomicInteger();
        var pool = new ScheduledThreadPoolExecutor(1, target -> {
            selected.get().shutdownNow();
            return new Thread(target);
        });
        selected.set(pool);
        // The scheduled entry's queued lease settles first. Deny the nested
        // action's settlement during reentrant physical removal.
        Activation.denyCloseNext = "QueuedWork"; Activation.denyCloseAfter = 1;
        try { CompletableFuture.supplyAsync(() -> { calls.incrementAndGet(); return 42; }, pool); throw new AssertionError(); }
        catch (IllegalStateException expected) { require(expected.getMessage().equals("source-owner-settlement-denied")); }
        require(calls.get() == 0 && pool.hasPendingWork() && !pool.isTerminated()); held(1, 1);
        require(Activation.poisoned && Activation.retainsFailedQueued() && Activation.failedLeaseAttempts() == 1);
        require(Activation.count(LatentRuntimeActivationOwnerKind.Executor) == 1);
        pool.shutdownNow();
        require(pool.hasPendingWork() && !pool.isTerminated()); held(1, 1);
        require(Activation.failedLeaseAttempts() == 1);
        // The intentionally denied token remains charged until this private
        // test process ends; it is never presented as a clean retirement.
    }
    public static void main(String[] args) throws Exception {
        copies(); denial(); completedFailure(); failedInsertion(); failedWorkerRequeue(); uncertainInsertion();
        manualWinsWorker(false); manualWinsWorker(true); manualStopped(true); manualStopped(false);
        workerRunning(); managedWrapper(); opaqueRunning(); subclassReentrancy(); reentrantFactoryRollback(); deniedSettlementRemainsCharged();
        System.out.println("SCHEDULED_PERIODIC_OWNER PASS copies;denial;completed-failure;insertion;worker-requeue;uncertain-insertion;manual-worker;last-copy-denial;cancel;shutdown;running-worker;managed-wrapper;opaque;subclass-reentrancy;reentrant-factory;denied-settlement-held");
    }
}
