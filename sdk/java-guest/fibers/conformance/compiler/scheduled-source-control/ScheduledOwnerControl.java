import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Actual maintained source, with deterministic callback/publication barriers. */
public final class ScheduledOwnerControl {
    private static void require(boolean value) { if (!value) throw new AssertionError("scheduled-owner-control"); }
    private static void await(CountDownLatch latch) throws InterruptedException { require(latch.await(5, TimeUnit.SECONDS)); }
    private static void held(int queued, int results) {
        require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == queued);
        require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == results);
    }
    private static void finish(java.util.concurrent.ExecutorService pool) throws InterruptedException {
        pool.shutdownNow();
        require(pool.awaitTermination(5, TimeUnit.SECONDS));
        Activation.idle();
    }
    private static void waiting(Thread worker) {
        long started = System.nanoTime();
        while (worker.getState() != Thread.State.TIMED_WAITING) {
            require(worker.isAlive() && System.nanoTime() - started < TimeUnit.SECONDS.toNanos(5));
            Thread.yield();
        }
    }
    private static Object capturedPool(Runnable target) throws Exception {
        // The factory deliberately retains the actual Runnable after the thread
        // exits, matching the pinned TeaVM Thread target lifetime.
        var capture = target.getClass().getDeclaredFields()[0]; capture.setAccessible(true);
        Object worker = capture.get(target);
        var pool = worker.getClass().getDeclaredField("pool"); pool.setAccessible(true);
        return pool.get(worker);
    }
    private static void clearedWorkerTarget(Runnable target) throws Exception {
        require(capturedPool(target) == null);
        target.run(); // A retained target is inert after retirement.
    }
    private static java.util.concurrent.ExecutorService executor(boolean scheduled, java.util.concurrent.ThreadFactory factory) {
        return executor(scheduled, 1, factory);
    }
    private static java.util.concurrent.ExecutorService executor(boolean scheduled, int parallelism, java.util.concurrent.ThreadFactory factory) {
        return scheduled ? new ScheduledThreadPoolExecutor(parallelism, factory)
            : dev.latent.guest.runtime.concurrent.Executors.newFixedThreadPool(parallelism, factory);
    }
    private static class EqualThread extends Thread {
        final AtomicInteger interrupts = new AtomicInteger();
        EqualThread(Runnable task) { super(task); }
        @Override public boolean equals(Object other) { return other instanceof EqualThread; }
        @Override public int hashCode() { return 1; }
        @Override public void interrupt() { interrupts.incrementAndGet(); super.interrupt(); }
    }
    @SuppressWarnings("unchecked")
    private static java.util.List<Thread> workers(java.util.concurrent.ExecutorService pool) throws Exception {
        var field = pool.getClass().getDeclaredField("workers"); field.setAccessible(true);
        return (java.util.List<Thread>)field.get(pool);
    }
    private static void factoryRejectionTargets() throws Exception {
        for (boolean scheduled : new boolean[]{false, true}) for (String mode : new String[]{"null", "throws", "live", "add-before", "add-after"}) {
            AtomicReference<Runnable> target = new AtomicReference<>();
            var original = new IllegalStateException("source-factory-failure-" + mode);
            CountDownLatch liveStarted = new CountDownLatch(1), liveRelease = new CountDownLatch(1);
            Thread live = new Thread(() -> { liveStarted.countDown(); try { liveRelease.await(); } catch (InterruptedException error) { Thread.currentThread().interrupt(); } });
            if (mode.equals("live")) { live.start(); await(liveStarted); }
            var pool = executor(scheduled, task -> {
                target.set(task);
                if (mode.equals("throws")) throw original;
                if (mode.equals("null")) return null;
                if (mode.equals("live")) return live;
                return new Thread(task);
            });
            try {
                if (mode.startsWith("add-")) {
                    var field = pool.getClass().getDeclaredField("workers"); field.setAccessible(true);
                    field.set(pool, new java.util.ArrayList<Thread>() {
                        @Override public boolean add(Thread thread) {
                            if (mode.equals("add-after")) super.add(thread);
                            throw original;
                        }
                    });
                }
                try { pool.execute(() -> { throw new AssertionError("unadmitted-factory-callback"); }); throw new AssertionError("expected-factory-rejection"); }
                catch (RuntimeException error) {
                    if (mode.equals("null") || mode.equals("live")) require(error instanceof java.util.concurrent.RejectedExecutionException);
                    else require(error == original);
                }
                require(target.get() != null && capturedPool(target.get()) == null && workers(pool).isEmpty());
                target.get().run(); held(0, 0);
            } finally {
                liveRelease.countDown(); if (mode.equals("live")) live.join(5000);
                finish(pool);
            }
        }
    }
    private static void earlyFactoryTarget() throws Exception {
        for (boolean scheduled : new boolean[]{false, true}) {
            AtomicReference<Thread> created = new AtomicReference<>(), executed = new AtomicReference<>();
            CountDownLatch done = new CountDownLatch(1);
            var pool = executor(scheduled, task -> {
                task.run(); // Factory invokes the target before returning a Thread.
                Thread thread = new Thread(task); created.set(thread); return thread;
            });
            pool.execute(() -> { executed.set(Thread.currentThread()); done.countDown(); });
            await(done); finish(pool); created.get().join(5000);
            require(executed.get() == created.get());
        }
    }
    private static void failedStartOwnership() throws Exception {
        for (boolean scheduled : new boolean[]{false, true}) for (boolean accepted : new boolean[]{false, true}) {
            AtomicReference<Runnable> target = new AtomicReference<>();
            AtomicReference<Thread> worker = new AtomicReference<>();
            AtomicInteger interrupts = new AtomicInteger();
            var original = new IllegalThreadStateException("source-start-failure");
            var pool = executor(scheduled, task -> {
                target.set(task);
                Thread thread = new Thread(task) {
                    @Override public void start() { if (accepted) super.start(); throw original; }
                    @Override public void interrupt() { interrupts.incrementAndGet(); super.interrupt(); }
                };
                worker.set(thread); return thread;
            });
            // Fake selects the real activation's uncertain-owner outcome; the
            // real-Activation control independently tests physical custody.
            Activation.retainFailedStart = true;
            try {
                try { pool.execute(() -> { throw new AssertionError("rejected-work-ran"); }); throw new AssertionError("expected-start-failure"); }
                catch (IllegalThreadStateException error) { require(error == original); }
                require(workers(pool).contains(worker.get()) && capturedPool(target.get()) == pool);
            } finally { Activation.retainFailedStart = false; }
            ((Activation.ManagedPool)pool).closeAtRoot();
            require(interrupts.get() > 0);
            if (accepted) {
                worker.get().join(5000); require(!worker.get().isAlive());
                require(capturedPool(target.get()) == null);
            } else {
                // A failed rollback retains an unstarted worker indefinitely.
                require(workers(pool).contains(worker.get()) && capturedPool(target.get()) == pool
                    && Activation.count(LatentRuntimeActivationOwnerKind.Executor) == 1);
                workers(pool).remove(worker.get()); // Private fake teardown only.
            }
            finish(pool);
        }
    }
    private static void retirementIteration() throws Exception {
        // Simulate a worker leaving the registry during interrupt. The host
        // source control can run threads in parallel; a reentrant callback can
        // also modify the registry before the coordinator resumes iteration.
        for (boolean scheduled : new boolean[]{false, true}) for (boolean concurrent : new boolean[]{false, true})
                for (int count : new int[]{1, 2, 3}) {
            var pool = executor(scheduled, task -> new Thread(task));
            var registry = workers(pool);
            AtomicInteger remainingInterrupted = new AtomicInteger();
            Thread first = new Thread() {
                @Override public void interrupt() {
                    if (!concurrent) { registry.remove(0); return; }
                    Thread retired = new Thread(() -> registry.remove(0));
                    retired.start();
                    try { retired.join(5000); }
                    catch (InterruptedException error) { Thread.currentThread().interrupt(); throw new AssertionError(error); }
                    require(!retired.isAlive());
                }
            };
            registry.add(first);
            for (int index = 1; index < count; index++) registry.add(new Thread() {
                @Override public void interrupt() { remainingInterrupted.incrementAndGet(); }
            });
            try {
                ((Activation.ManagedPool)pool).closeAtRoot();
                require(remainingInterrupted.get() == count - 1);
                require(registry.size() == count - 1);
                require(Activation.count(LatentRuntimeActivationOwnerKind.Executor) == (count == 1 ? 0 : 1));
            } finally {
                registry.clear(); // Private fake teardown only.
                finish(pool);
            }
        }
    }
    private static void retirementRemovalFailure() throws Exception {
        // A copy-on-write removal can fail before publishing its new array.
        // Keep the original worker and executor owner on that failure.
        for (boolean scheduled : new boolean[]{false, true}) {
            var pool = executor(scheduled, task -> new Thread(task));
            class FailingWorkers extends java.util.concurrent.CopyOnWriteArrayList<Thread> {
                final OutOfMemoryError failure = new OutOfMemoryError("worker-registry-copy");
                @Override public Thread remove(int index) { throw failure; }
            }
            var registry = new FailingWorkers();
            Thread worker = new Thread(); registry.add(worker);
            var field = pool.getClass().getDeclaredField("workers"); field.setAccessible(true); field.set(pool, registry);
            var remove = pool.getClass().getDeclaredMethod("removeWorker", Thread.class); remove.setAccessible(true);
            try {
                try { remove.invoke(pool, worker); throw new AssertionError("expected-registry-failure"); }
                catch (java.lang.reflect.InvocationTargetException error) { require(error.getCause() == registry.failure); }
                require(registry.size() == 1 && registry.get(0) == worker
                    && Activation.count(LatentRuntimeActivationOwnerKind.Executor) == 1);
            } finally {
                registry.clear(); // Private fake teardown only.
                finish(pool);
            }
        }
    }
    private static void duplicateRetainedWorker() throws Exception {
        for (boolean scheduled : new boolean[]{false, true}) {
            AtomicReference<Runnable> first = new AtomicReference<>(), second = new AtomicReference<>();
            var failure = new IllegalThreadStateException("source-first-start-failure");
            Thread shared = new Thread() { @Override public void start() { throw failure; } };
            var pool = executor(scheduled, task -> {
                if (first.get() == null) first.set(task); else second.set(task);
                return shared;
            });
            var start = pool.getClass().getDeclaredMethod("startWorker"); start.setAccessible(true);
            Activation.retainFailedStart = true;
            try {
                try { start.invoke(pool); throw new AssertionError("first-start-succeeded"); }
                catch (java.lang.reflect.InvocationTargetException error) { require(error.getCause() == failure); }
                try { start.invoke(pool); throw new AssertionError("duplicate-start-succeeded"); }
                catch (java.lang.reflect.InvocationTargetException error) { require(error.getCause() instanceof IllegalThreadStateException); }
                require(workers(pool).size() == 1 && workers(pool).get(0) == shared
                    && capturedPool(first.get()) == pool && capturedPool(second.get()) == null);
            } finally { Activation.retainFailedStart = false; }
            ((Activation.ManagedPool)pool).closeAtRoot();
            require(workers(pool).size() == 1); // Original uncertain owner remains.
            workers(pool).remove(shared); // Private fake teardown only.
            finish(pool);
        }
    }
    private static void duplicateLiveAndCompletedWorker() throws Exception {
        for (boolean scheduled : new boolean[]{false, true}) for (boolean completed : new boolean[]{false, true}) {
            AtomicReference<Thread> original = new AtomicReference<>();
            AtomicReference<Runnable> duplicate = new AtomicReference<>();
            CountDownLatch started = new CountDownLatch(1), release = new CountDownLatch(1);
            var pool = executor(scheduled, task -> {
                if (original.get() != null) { duplicate.set(task); return original.get(); }
                Thread thread = new Thread(task); original.set(thread); return thread;
            });
            pool.execute(() -> {
                started.countDown();
                try { release.await(); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
            });
            await(started);
            if (completed) {
                release.countDown(); pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS));
                original.get().join(5000); require(!original.get().isAlive());
            }
            var start = pool.getClass().getDeclaredMethod("startWorker"); start.setAccessible(true);
            try { start.invoke(pool); throw new AssertionError("duplicate-start-succeeded"); }
            catch (java.lang.reflect.InvocationTargetException error) {
                if (completed) require(error.getCause() instanceof IllegalThreadStateException);
                else require(error.getCause() instanceof java.util.concurrent.RejectedExecutionException);
            }
            require(capturedPool(duplicate.get()) == null && Activation.recorded(original.get(), (Activation.ManagedPool)pool));
            if (completed) require(workers(pool).isEmpty());
            else require(workers(pool).size() == 1 && workers(pool).get(0) == original.get());
            release.countDown(); pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS));
            original.get().join(5000); Activation.idle();
        }
    }
    private static void identityRemoval() throws Exception {
        for (boolean scheduled : new boolean[]{false, true}) for (boolean failStart : new boolean[]{false, true}) {
            java.util.ArrayList<EqualThread> created = new java.util.ArrayList<>();
            AtomicReference<Runnable> rejectedTarget = new AtomicReference<>();
            CountDownLatch firstStarted = new CountDownLatch(1), release = new CountDownLatch(1), secondDone = new CountDownLatch(1);
            var original = new IllegalThreadStateException("source-equal-thread-start");
            var pool = executor(scheduled, 2, task -> {
                EqualThread thread;
                if (failStart && !created.isEmpty()) {
                    rejectedTarget.set(task);
                    thread = new EqualThread(task) { @Override public void start() { throw original; } };
                } else thread = new EqualThread(task);
                created.add(thread); return thread;
            });
            pool.execute(() -> {
                firstStarted.countDown();
                while (true) try { release.await(); return; } catch (InterruptedException expected) { }
            });
            await(firstStarted);
            if (failStart) {
                try { pool.execute(secondDone::countDown); throw new AssertionError("expected-equal-thread-failure"); }
                catch (IllegalThreadStateException error) { require(error == original); }
                require(capturedPool(rejectedTarget.get()) == null);
            } else {
                pool.execute(secondDone::countDown); await(secondDone);
                pool.shutdownNow();
                created.get(1).join(5000); require(!created.get(1).isAlive());
            }
            require(created.size() == 2 && created.get(0) != created.get(1) && created.get(0).equals(created.get(1)));
            require(workers(pool).size() == 1 && workers(pool).get(0) == created.get(0));
            int before = created.get(0).interrupts.get();
            ((Activation.ManagedPool)pool).closeAtRoot();
            require(created.get(0).interrupts.get() > before);
            release.countDown(); created.get(0).join(5000); require(!created.get(0).isAlive());
            finish(pool);
        }
    }
    private static void rejectedWorkerTargets() throws Exception {
        for (boolean scheduled : new boolean[]{false, true}) {
            AtomicReference<Runnable> target = new AtomicReference<>();
            var original = new IllegalThreadStateException("source-definite-start-failure");
            var pool = executor(scheduled, task -> {
                target.set(task); return new Thread(task) { @Override public void start() { throw original; } };
            });
            try { pool.execute(() -> { throw new AssertionError("rejected-work-ran"); }); throw new AssertionError("expected-start-failure"); }
            catch (IllegalThreadStateException error) { require(error == original); }
            require(workers(pool).isEmpty() && capturedPool(target.get()) == null);
            finish(pool);
        }
    }
    private static void workerTargets() throws Exception {
        AtomicReference<Runnable> target = new AtomicReference<>();
        AtomicReference<Thread> worker = new AtomicReference<>();
        java.util.concurrent.ThreadFactory factory = runnable -> {
            target.set(runnable); Thread thread = new Thread(runnable); worker.set(thread); return thread;
        };
        var executor = dev.latent.guest.runtime.concurrent.Executors.newSingleThreadExecutor(factory);
        CountDownLatch ran = new CountDownLatch(1); executor.execute(ran::countDown); await(ran);
        executor.shutdown(); require(executor.awaitTermination(5, TimeUnit.SECONDS));
        worker.get().join(5000); require(!worker.get().isAlive()); clearedWorkerTarget(target.get()); Activation.idle();
        target.set(null); worker.set(null);
        var scheduled = new ScheduledThreadPoolExecutor(1, factory);
        require(scheduled.schedule(() -> 42, 0, TimeUnit.NANOSECONDS).get(5, TimeUnit.SECONDS) == 42);
        scheduled.shutdown(); require(scheduled.awaitTermination(5, TimeUnit.SECONDS));
        worker.get().join(5000); require(!worker.get().isAlive()); clearedWorkerTarget(target.get()); Activation.idle();
    }
    public static void main(String[] arguments) throws Exception {
        ScheduledThreadPoolExecutor pool = new ScheduledThreadPoolExecutor(1);
        for (String denied : new String[]{"QueuedWork", "Result"}) {
            Activation.denyNext = denied;
            try { pool.schedule(() -> { throw new AssertionError("unadmitted-callback"); }, 0, TimeUnit.NANOSECONDS); throw new AssertionError(); }
            catch (IllegalStateException expected) { require(expected.getMessage().equals("source-owner-admission-denied")); }
            held(0, 0);
        }
        require(pool.schedule(() -> 42, -1, TimeUnit.NANOSECONDS).get(5, TimeUnit.SECONDS) == 42);
        finish(pool);

        pool = new ScheduledThreadPoolExecutor(2);
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        var active = pool.scheduleAtFixedRate(() -> {
            entered.countDown();
            boolean interrupted = false;
            while (true) {
                try { release.await(); break; }
                catch (InterruptedException expected) { interrupted = true; }
            }
            if (interrupted) Thread.currentThread().interrupt();
        }, 0, 1, TimeUnit.NANOSECONDS);
        await(entered); held(1, 1);
        require(active.cancel(false) && active.isDone() && active.isCancelled());
        held(1, 1); // Cancellation cannot refund the physically running callback.
        release.countDown();
        finish(pool);

        pool = new ScheduledThreadPoolExecutor(2);
        CountDownLatch twice = new CountDownLatch(2);
        AtomicInteger concurrent = new AtomicInteger(), calls = new AtomicInteger();
        var recurring = pool.scheduleWithFixedDelay(() -> {
            require(concurrent.incrementAndGet() == 1);
            calls.incrementAndGet(); twice.countDown(); concurrent.decrementAndGet();
        }, 0, 1, TimeUnit.NANOSECONDS);
        await(twice); require(calls.get() >= 2);
        recurring.cancel(false); finish(pool);

        pool = new ScheduledThreadPoolExecutor(1);
        var original = new IllegalArgumentException("original-periodic-callback-error");
        AtomicInteger failures = new AtomicInteger();
        var failure = pool.scheduleAtFixedRate(() -> { failures.incrementAndGet(); throw original; }, 0, 1, TimeUnit.NANOSECONDS);
        try { failure.get(5, TimeUnit.SECONDS); throw new AssertionError(); }
        catch (ExecutionException expected) { require(expected.getCause() == original); }
        finish(pool);
        require(failures.get() == 1); // Exceptional periodic execution is not rescheduled.

        for (boolean interrupt : new boolean[]{false, true}) {
            AtomicReference<Thread> actual = new AtomicReference<>();
            pool = new ScheduledThreadPoolExecutor(1, task -> {
                Thread worker = new Thread(task); actual.set(worker); return worker;
            });
            var waiting = pool.schedule(() -> { throw new AssertionError("cancelled-delayed-callback"); }, 1, TimeUnit.DAYS);
            waiting(actual.get()); held(1, 1); // Actual timed monitor wait, not a delay-as-barrier.
            if (interrupt) {
                require(pool.shutdownNow().contains(waiting));
                require(!waiting.isDone());
                waiting.cancel(false);
            } else require(waiting.cancel(false));
            finish(pool);
            actual.get().join(5000);
            require(!actual.get().isAlive());
        }

        pool = new ScheduledThreadPoolExecutor(1);
        pool.setExecuteExistingDelayedTasksAfterShutdownPolicy(false);
        var delayed = pool.schedule(() -> { throw new AssertionError("shutdown-delayed-callback"); }, 1, TimeUnit.DAYS);
        pool.shutdown(); require(delayed.isCancelled());
        require(pool.awaitTermination(5, TimeUnit.SECONDS)); Activation.idle();

        pool = new ScheduledThreadPoolExecutor(1, task -> null);
        try { pool.schedule(() -> { throw new AssertionError("failed-worker-callback"); }, 0, TimeUnit.NANOSECONDS); throw new AssertionError(); }
        catch (java.util.concurrent.RejectedExecutionException expected) { held(0, 0); }
        finish(pool);
        workerTargets();
        factoryRejectionTargets();
        earlyFactoryTarget();
        rejectedWorkerTargets();
        failedStartOwnership();
        retirementIteration();
        retirementRemovalFailure();
        duplicateRetainedWorker();
        duplicateLiveAndCompletedWorker();
        identityRemoval();
        System.out.println("SCHEDULED_OWNER_CONTROL PASS preadmission;actual-result;running-cancel-held;periodic-nonoverlap;original-error-suppresses-repeat;timed-wait-cancel-and-interrupt;shutdown-policy;factory-rollback;worker-retirement-snapshot;copy-failure-retained;all-retired");
    }
}
