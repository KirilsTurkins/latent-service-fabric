import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.Executors;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Actual executor source and a private faulting host ledger. */
public final class ManagedCachedHandoffOwnerControl {
    private static void require(boolean value, String reason) { if (!value) throw new AssertionError(reason); }
    private static void await(CountDownLatch latch, String reason) throws InterruptedException { require(latch.await(5, TimeUnit.SECONDS), reason); }
    private static void held(int queue, int result, int executor) {
        require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == queue
            && Activation.count(LatentRuntimeActivationOwnerKind.Result) == result
            && Activation.count(LatentRuntimeActivationOwnerKind.Executor) == executor, "original-owners");
    }
    private static Object worker(Runnable target) throws Exception {
        var capture = target.getClass().getDeclaredFields()[0]; capture.setAccessible(true); return capture.get(target);
    }
    private static void inert(Runnable target) throws Exception {
        Object worker = worker(target);
        for (var field : worker.getClass().getDeclaredFields()) if (!field.getType().isPrimitive()) {
            field.setAccessible(true); require(field.get(worker) == null, "retired-worker-reference");
        }
        target.run();
    }
    private static void waitIdle(Thread worker) {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
        while (worker.getState() != Thread.State.TIMED_WAITING) {
            require(worker.isAlive() && System.nanoTime() - deadline < 0, "worker-not-idle"); Thread.yield();
        }
    }
    private static void single(String mode) throws Exception {
        var target = new AtomicReference<Runnable>(); var thread = new AtomicReference<Thread>();
        var uncaught = new AtomicReference<Throwable>(); var failed = new CountDownLatch(1);
        var calls = new AtomicInteger(); var claimObservations = new AtomicInteger(); var marker = new IllegalStateException("interrupt-failure");
        var pool = Executors.newCachedThreadPool(command -> {
            target.set(command);
            Thread worker = new Thread(command) {
                @Override public void interrupt() { super.interrupt(); if (mode.equals("interrupt-throws")) throw marker; }
            };
            worker.setUncaughtExceptionHandler((ignored, error) -> { uncaught.set(error); failed.countDown(); });
            thread.set(worker); return worker;
        });
        try {
            pool.submit(() -> {}).get(5, TimeUnit.SECONDS); waitIdle(thread.get()); held(0, 0, 1);
            Future<Integer> handoff;
            synchronized (pool) {
                handoff = pool.submit(() -> {
                    if (mode.equals("immediate") || mode.equals("graceful"))
                        require(Thread.currentThread().isInterrupted() == mode.equals("immediate"), "handoff-stop-interrupt");
                    calls.incrementAndGet(); return 42;
                });
                held(1, 1, 1); require(calls.get() == 0 && !handoff.isDone(), "handoff-ran-without-worker");
                var itemField = pool.getClass().getDeclaredField("reservedFirsts"); itemField.setAccessible(true);
                Object item = itemField.get(pool); require(item != null, "handoff-not-rooted");
                var queued = item.getClass().getDeclaredField("queued"); queued.setAccessible(true);
                Object worker = worker(target.get()); var lease = worker.getClass().getDeclaredField("firstLease"); lease.setAccessible(true);
                require(lease.get(worker) == queued.get(item), "handoff-owner-changed");
                var queue = pool.getClass().getDeclaredField("queue"); queue.setAccessible(true);
                require(((java.util.ArrayDeque<?>)queue.get(pool)).isEmpty(), "handoff-exposed-in-fifo");
                for (var field : worker.getClass().getDeclaredFields()) if (!field.getType().isPrimitive()
                        && !field.getName().equals("pool") && !field.getName().equals("thread")
                        && !field.getName().equals("firstLease")) {
                    field.setAccessible(true); require(field.get(worker) == null, "worker-retained-task-or-idle-link");
                }
                if (mode.equals("idle-registry-lost")) {
                    // Fault-project a failed idle-list removal after handoff,
                    // before the physical worker can claim the original Item.
                    var idle = worker.getClass().getDeclaredField("idle"); idle.setAccessible(true); idle.setBoolean(worker, true);
                }
                if (mode.equals("graceful")) pool.shutdown();
                else if (mode.equals("interrupt-throws")) {
                    try { pool.shutdownNow(); throw new AssertionError("missing-interrupt-error"); }
                    catch (IllegalStateException error) { require(error == marker, "interrupt-error-lost"); }
                } else require(pool.shutdownNow().isEmpty(), "handoff-returned");
                if (mode.equals("immediate")) {
                    // Project a consumed idle-wait/host-call wakeup before callback entry.
                    Activation.closeObservationKind = "QueuedWork";
                    Activation.closeObservation = () -> {
                        require(Thread.currentThread() == thread.get(), "claim-on-wrong-worker");
                        Thread.interrupted(); claimObservations.incrementAndGet();
                    };
                }
                if (mode.equals("cancel")) { require(handoff.cancel(false), "handoff-not-cancelled"); held(1, 0, 1); }
                if (mode.equals("queue-denied")) Activation.denyCloseNext = "QueuedWork";
                if (mode.equals("queue-lost")) Activation.loseCloseAckNext = "QueuedWork";
                require(!pool.isTerminated() && ((Activation.ManagedPool)pool).hasPendingWork(), "handoff-not-fenced");
            }
            if (mode.equals("idle-registry-lost")) {
                await(failed, "idle-registry-failure-not-observed"); thread.get().join(5000);
                require(!thread.get().isAlive() && uncaught.get() instanceof IllegalStateException
                    && uncaught.get().getMessage().equals("activation-executor-idle-worker-lost") && calls.get() == 0,
                    "unclaimed-handoff-ran");
                held(1, 1, 1); inert(target.get());
                var reserved = pool.getClass().getDeclaredField("reservedFirsts"); reserved.setAccessible(true);
                require(reserved.get(pool) != null && Activation.poisoned && !pool.isTerminated()
                    && ((Activation.ManagedPool)pool).hasPendingWork(), "stranded-handoff-not-rooted");
                pool.shutdownNow(); require(Activation.closeAttempts(LatentRuntimeActivationOwnerKind.QueuedWork) == 1,
                    "stranded-handoff-settled"); // only the earlier warm-up Queue owner settled
                return;
            }
            if (mode.equals("queue-denied") || mode.equals("queue-lost")) {
                await(failed, "handoff-settlement-not-failed"); thread.get().join(5000);
                require(!thread.get().isAlive() && uncaught.get() instanceof IllegalStateException && calls.get() == 0,
                    "failed-claim-ran");
                held(mode.equals("queue-denied") ? 1 : 0, 1, 1); inert(target.get());
                require(Activation.poisoned && Activation.retainsFailedQueued() && Activation.failedLeaseAttempts() == 1
                    && ((Activation.ManagedPool)pool).hasPendingWork() && !pool.isTerminated(), "failed-handoff-not-rooted");
                pool.shutdownNow(); require(Activation.failedLeaseAttempts() == 1, "failed-handoff-retried");
                return;
            }
            if (!mode.equals("cancel")) require(handoff.get(5, TimeUnit.SECONDS) == 42 && calls.get() == 1, "handoff-not-run");
            require(pool.awaitTermination(5, TimeUnit.SECONDS), "pool-not-terminated"); thread.get().join(5000);
            require(!thread.get().isAlive() && calls.get() == (mode.equals("cancel") ? 0 : 1), "handoff-count");
            require(claimObservations.get() == (mode.equals("immediate") ? 1 : 0), "claim-observation-missing");
            held(0, 0, 0); inert(target.get()); Activation.idle();
        } finally {
            try { pool.shutdownNow(); } catch (IllegalStateException error) { if (!mode.equals("interrupt-throws")) throw error; }
        }
    }
    private static void interruptPreparationFailure() throws Exception {
        var target = new AtomicReference<Runnable>(); var thread = new AtomicReference<Thread>();
        var uncaught = new AtomicReference<Throwable>(); var failed = new CountDownLatch(1);
        var calls = new AtomicInteger(); var attempts = new AtomicInteger();
        var marker = new IllegalStateException("handoff-self-interrupt-failed");
        var pool = Executors.newCachedThreadPool(command -> {
            target.set(command);
            Thread worker = new Thread(command) {
                @Override public void interrupt() {
                    if (Thread.currentThread() == this) { attempts.incrementAndGet(); throw marker; }
                    super.interrupt();
                }
            };
            worker.setUncaughtExceptionHandler((ignored, error) -> { uncaught.set(error); failed.countDown(); });
            thread.set(worker); return worker;
        });
        try {
            int initialQueueAttempts = Activation.closeAttempts(LatentRuntimeActivationOwnerKind.QueuedWork);
            pool.submit(() -> {}).get(5, TimeUnit.SECONDS); waitIdle(thread.get());
            var reserved = pool.getClass().getDeclaredField("reservedFirsts"); reserved.setAccessible(true);
            Future<?> handoff; Object original;
            synchronized (pool) {
                handoff = pool.submit(calls::incrementAndGet); original = reserved.get(pool);
                require(original != null && pool.shutdownNow().isEmpty(), "handoff-not-committed");
                Activation.closeObservationKind = "QueuedWork";
                Activation.closeObservation = () -> { Thread.interrupted(); };
            }
            await(failed, "self-interrupt-failure-not-observed"); thread.get().join(5000);
            require(!thread.get().isAlive() && uncaught.get() == marker && attempts.get() == 1,
                "self-interrupt-failure-changed");
            require(calls.get() == 0 && !handoff.isDone() && reserved.get(pool) == original,
                "failed-interrupt-lost-original-item");
            held(0, 1, 1); inert(target.get());
            require(Activation.poisoned && ((Activation.ManagedPool)pool).hasPendingWork()
                && !pool.isTerminated(), "failed-interrupt-not-fenced");
            int queueAttempts = Activation.closeAttempts(LatentRuntimeActivationOwnerKind.QueuedWork);
            require(queueAttempts - initialQueueAttempts == 2, "queue-claim-not-settled-once");
            pool.shutdownNow();
            require(Activation.closeAttempts(LatentRuntimeActivationOwnerKind.QueuedWork) == queueAttempts
                && attempts.get() == 1 && reserved.get(pool) == original, "failed-interrupt-retried");
        } finally { Activation.closeObservation = null; Activation.closeObservationKind = null; pool.shutdownNow(); }
    }
    private static void two() throws Exception {
        var started = new CountDownLatch(2); var release = new CountDownLatch(1);
        var threads = new java.util.concurrent.CopyOnWriteArrayList<Thread>();
        var targets = new java.util.concurrent.CopyOnWriteArrayList<Runnable>(); var calls = new AtomicInteger();
        var pool = Executors.newCachedThreadPool(command -> { targets.add(command); var worker = new Thread(command); threads.add(worker); return worker; });
        try {
            Future<?> a = pool.submit(() -> { started.countDown(); try { await(release, "first-release"); } catch (InterruptedException e) { throw new AssertionError(e); } });
            Future<?> b = pool.submit(() -> { started.countDown(); try { await(release, "second-release"); } catch (InterruptedException e) { throw new AssertionError(e); } });
            await(started, "workers-not-running"); release.countDown(); a.get(5, TimeUnit.SECONDS); b.get(5, TimeUnit.SECONDS);
            require(threads.size() == 2, "worker-count"); for (Thread worker : threads) waitIdle(worker);
            Future<?> first, second;
            synchronized (pool) {
                first = pool.submit(calls::incrementAndGet); second = pool.submit(calls::incrementAndGet);
                held(2, 2, 1); require(calls.get() == 0 && pool.shutdownNow().isEmpty(), "handoffs-exposed");
            }
            first.get(5, TimeUnit.SECONDS); second.get(5, TimeUnit.SECONDS);
            require(pool.awaitTermination(5, TimeUnit.SECONDS) && calls.get() == 2, "handoffs-not-settled");
            for (Thread worker : threads) worker.join(5000); for (Runnable target : targets) inert(target);
            held(0, 0, 0); Activation.idle();
        } finally { release.countDown(); pool.shutdownNow(); }
    }
    private static void notIdle() throws Exception {
        var entered = new CountDownLatch(1); var release = new CountDownLatch(1);
        var attempts = new AtomicInteger(); var calls = new AtomicInteger();
        var pool = Executors.newCachedThreadPool(command -> { attempts.incrementAndGet(); return new Thread(command); });
        Activation.checkpointObservation = () -> {
            entered.countDown(); try { await(release, "checkpoint-release"); } catch (InterruptedException error) { throw new AssertionError(error); }
        };
        try {
            pool.submit(() -> {}).get(5, TimeUnit.SECONDS); await(entered, "checkpoint-not-entered");
            require(pool.submit(calls::incrementAndGet).get(5, TimeUnit.SECONDS) == 1 && attempts.get() == 2,
                "nonwaiting-worker-falsely-idle");
            release.countDown(); pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS), "growth-not-retired");
            held(0, 0, 0); Activation.idle();
        } finally { Activation.checkpointObservation = null; release.countDown(); pool.shutdownNow(); }
    }
    private static void defaultAsync() throws Exception {
        var create = Executors.class.getDeclaredMethod("newDefaultAsyncPool"); create.setAccessible(true);
        var pool = (java.util.concurrent.ExecutorService)create.invoke(null); var calls = new AtomicInteger();
        try {
            pool.submit(() -> {}).get(5, TimeUnit.SECONDS);
            var field = pool.getClass().getDeclaredField("workers"); field.setAccessible(true);
            var workers = (java.util.List<?>)field.get(pool); require(workers.size() == 1, "default-worker-count");
            Thread worker = (Thread)workers.get(0); long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
            while (worker.getState() != Thread.State.WAITING) {
                require(worker.isAlive() && System.nanoTime() - deadline < 0, "default-worker-not-idle"); Thread.yield();
            }
            Future<?> handoff;
            synchronized (pool) {
                handoff = pool.submit(calls::incrementAndGet); held(1, 1, 1);
                require(pool.shutdownNow().isEmpty() && calls.get() == 0, "default-handoff-exposed");
            }
            handoff.get(5, TimeUnit.SECONDS); worker.join(5000);
            require(!worker.isAlive() && pool.awaitTermination(5, TimeUnit.SECONDS) && calls.get() == 1,
                "default-handoff-not-retired");
            held(0, 0, 0); Activation.idle();
        } finally { pool.shutdownNow(); }
    }
    public static void main(String[] args) throws Exception {
        switch (args[0]) {
            case "graceful", "cancel", "queue-denied", "queue-lost", "interrupt-throws", "idle-registry-lost" -> single(args[0]);
            case "immediate" -> { single(args[0]); interruptPreparationFailure(); }
            case "two" -> two(); case "not-idle" -> notIdle(); case "default-async" -> defaultAsync();
            default -> throw new IllegalArgumentException("mode");
        }
        System.out.println("MANAGED_CACHED_HANDOFF_OWNER PASS " + args[0]);
    }
}
