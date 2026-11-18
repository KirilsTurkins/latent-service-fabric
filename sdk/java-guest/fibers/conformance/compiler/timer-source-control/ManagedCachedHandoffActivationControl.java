import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.Option;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.Executors;
import java.lang.reflect.Field;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Actual Activation and cached pool with private host bindings, not a guest. */
public final class ManagedCachedHandoffActivationControl {
    private static void require(boolean value, String reason) { if (!value) throw new AssertionError(reason); }
    private static void await(CountDownLatch latch, String reason) throws InterruptedException { require(latch.await(5, TimeUnit.SECONDS), reason); }
    private static Field field(String name) throws Exception { var f = Activation.class.getDeclaredField(name); f.setAccessible(true); return f; }
    private static Object invoke(String name) throws Exception { var m = Activation.class.getDeclaredMethod(name); m.setAccessible(true); return m.invoke(null); }
    @SuppressWarnings("unchecked") private static Object enter() throws Exception {
        field("entered").setBoolean(null, true);
        var token = Bindings.LatentRuntimeActivation.register(LatentRuntimeActivationOwnerKind.Task, Option.none()).value();
        var type = Class.forName("dev.latent.guest.runtime.Activation$Work");
        var constructor = type.getDeclaredConstructor(Bindings.LatentRuntimeActivationToken.class); constructor.setAccessible(true);
        Object root = constructor.newInstance(token); field("root").set(null, root);
        ((Map<Thread, Object>)field("threads").get(null)).put(Thread.currentThread(), root); return root;
    }
    private static void held(int tasks, int queue, int result, int executor, int workers) {
        require(Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.Task) == tasks
            && Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.QueuedWork) == queue
            && Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.Result) == result
            && Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.Executor) == executor
            && Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == workers,
            "original-owners");
    }
    private static void closeRoot() throws Exception { field("rootComplete").setBoolean(null, true); invoke("closeCompletedRoot"); }
    private static void finish(Object root) throws Exception {
        require(!(boolean)invoke("pending"), "root-still-pending"); field("finishingInvocation").setBoolean(null, true);
        var finish = Activation.class.getDeclaredMethod("finishWork", Thread.class, root.getClass(), boolean.class);
        finish.setAccessible(true); finish.invoke(null, null, root, true); held(0, 0, 0, 0, 0); invoke("finishInvocation");
    }
    private static void waitIdle(Thread worker) {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
        while (worker.getState() != Thread.State.TIMED_WAITING) {
            require(worker.isAlive() && System.nanoTime() - deadline < 0, "worker-not-idle"); Thread.yield();
        }
    }
    private static Object worker(Runnable target) throws Exception {
        var capture = target.getClass().getDeclaredFields()[0]; capture.setAccessible(true); return capture.get(target);
    }
    private static void single(String mode) throws Exception {
        Object root = enter(); var calls = new AtomicInteger(); var target = new AtomicReference<Runnable>();
        var selected = new AtomicReference<Thread>(); var uncaught = new AtomicReference<Throwable>();
        var failed = new CountDownLatch(1); var marker = new IllegalStateException("lost-queue-ack");
        var pool = Executors.newCachedThreadPool(command -> {
            target.set(command);
            Thread thread = new Thread(() -> {
                try { Activation.starting(Thread.currentThread()); command.run(); }
                catch (Throwable error) {
                    Bindings.LatentRuntimeActivation.denySettle = false;
                    Bindings.LatentRuntimeActivation.settleAcknowledgementFailure = null;
                    throw error;
                } finally { Activation.finished(Thread.currentThread()); }
            });
            thread.setUncaughtExceptionHandler((ignored, error) -> { uncaught.set(error); failed.countDown(); });
            selected.set(thread); return thread;
        });
        try {
            pool.submit(() -> {}).get(5, TimeUnit.SECONDS); waitIdle(selected.get()); held(1, 0, 0, 1, 1);
            Future<Integer> handoff;
            synchronized (pool) {
                handoff = pool.submit(() -> { calls.incrementAndGet(); return 42; }); held(1, 1, 1, 1, 1);
                require(calls.get() == 0 && !handoff.isDone(), "handoff-ran-without-worker");
                var reserved = pool.getClass().getDeclaredField("reservedFirsts"); reserved.setAccessible(true);
                Object item = reserved.get(pool); require(item != null, "handoff-not-rooted");
                var queued = item.getClass().getDeclaredField("queued"); queued.setAccessible(true);
                Object worker = worker(target.get()); var lease = worker.getClass().getDeclaredField("firstLease"); lease.setAccessible(true);
                require(lease.get(worker) == queued.get(item), "handoff-owner-changed");
                if (mode.equals("idle-registry-lost")) {
                    var idle = worker.getClass().getDeclaredField("idle"); idle.setAccessible(true); idle.setBoolean(worker, true);
                }
                closeRoot(); require((int)invoke("scanPendingPools") == 1 && (boolean)invoke("pending")
                    && !(boolean)invoke("retireIdlePools"), "handoff-root-not-fenced");
                if (mode.equals("graceful")) pool.shutdown(); else require(pool.shutdownNow().isEmpty(), "handoff-returned");
                if (mode.equals("cancel")) { require(handoff.cancel(false), "handoff-not-cancelled"); held(1, 1, 0, 1, 1); }
                if (mode.equals("queue-denied")) Bindings.LatentRuntimeActivation.denySettle = true;
                if (mode.equals("queue-lost")) Bindings.LatentRuntimeActivation.settleAcknowledgementFailure = marker;
            }
            if (mode.equals("queue-denied") || mode.equals("queue-lost") || mode.equals("idle-registry-lost")) {
                await(failed, "queue-failure-not-observed"); selected.get().join(5000);
                require(!selected.get().isAlive() && uncaught.get() instanceof IllegalStateException && calls.get() == 0,
                    "failed-handoff-ran");
                held(1, mode.equals("queue-lost") ? 0 : 1, 1, 1, 0);
                if (mode.equals("idle-registry-lost"))
                    require(uncaught.get().getMessage().equals("activation-executor-idle-worker-lost"), "wrong-idle-failure");
                require(field("poisoned").getBoolean(null) && ((Activation.ManagedPool)pool).hasPendingWork()
                    && !pool.isTerminated() && (boolean)invoke("pending") && !(boolean)invoke("retireIdlePools"), "failed-handoff-not-fenced");
                int attempts = Bindings.LatentRuntimeActivation.settlementAttempts;
                pool.shutdownNow(); require(Bindings.LatentRuntimeActivation.settlementAttempts == attempts, "failed-handoff-retried");
                invoke("finishInvocation"); require(field("root").get(null) == root, "failed-handoff-root-lost"); return;
            }
            if (!mode.equals("cancel")) require(handoff.get(5, TimeUnit.SECONDS) == 42, "handoff-not-run");
            selected.get().join(5000);
            require(!selected.get().isAlive() && pool.awaitTermination(5, TimeUnit.SECONDS)
                && calls.get() == (mode.equals("cancel") ? 0 : 1), "handoff-not-retired");
            held(1, 0, 0, 0, 0); invoke("retireIdlePools"); finish(root);
        } finally {
            Bindings.LatentRuntimeActivation.denySettle = false;
            Bindings.LatentRuntimeActivation.settleAcknowledgementFailure = null;
            pool.shutdownNow();
        }
    }
    private static void two() throws Exception {
        Object root = enter(); var started = new CountDownLatch(2); var release = new CountDownLatch(1);
        var threads = new java.util.concurrent.CopyOnWriteArrayList<Thread>(); var calls = new AtomicInteger();
        var pool = Executors.newCachedThreadPool(command -> {
            Thread thread = new Thread(() -> {
                try { Activation.starting(Thread.currentThread()); command.run(); }
                finally { Activation.finished(Thread.currentThread()); }
            });
            threads.add(thread); return thread;
        });
        try {
            Future<?> a = pool.submit(() -> { started.countDown(); try { await(release, "first-release"); } catch (InterruptedException e) { throw new AssertionError(e); } });
            Future<?> b = pool.submit(() -> { started.countDown(); try { await(release, "second-release"); } catch (InterruptedException e) { throw new AssertionError(e); } });
            await(started, "workers-not-running"); release.countDown(); a.get(5, TimeUnit.SECONDS); b.get(5, TimeUnit.SECONDS);
            require(threads.size() == 2, "worker-count"); for (Thread thread : threads) waitIdle(thread); held(1, 0, 0, 1, 2);
            Future<?> first, second;
            synchronized (pool) {
                first = pool.submit(calls::incrementAndGet); second = pool.submit(calls::incrementAndGet); held(1, 2, 2, 1, 2);
                closeRoot(); require((boolean)invoke("pending") && !(boolean)invoke("retireIdlePools"), "handoffs-not-fenced");
                require(pool.shutdownNow().isEmpty() && calls.get() == 0, "handoffs-returned");
            }
            first.get(5, TimeUnit.SECONDS); second.get(5, TimeUnit.SECONDS);
            for (Thread thread : threads) thread.join(5000);
            require(pool.awaitTermination(5, TimeUnit.SECONDS) && calls.get() == 2, "handoffs-not-retired");
            held(1, 0, 0, 0, 0); invoke("retireIdlePools"); finish(root);
        } finally { release.countDown(); pool.shutdownNow(); }
    }
    public static void main(String[] args) throws Exception {
        switch (args[0]) {
            case "graceful", "immediate", "cancel", "queue-denied", "queue-lost", "idle-registry-lost" -> single(args[0]);
            case "two" -> two(); default -> throw new IllegalArgumentException("mode");
        }
        System.out.println("MANAGED_CACHED_HANDOFF_ACTIVATION PASS " + args[0]);
    }
}
