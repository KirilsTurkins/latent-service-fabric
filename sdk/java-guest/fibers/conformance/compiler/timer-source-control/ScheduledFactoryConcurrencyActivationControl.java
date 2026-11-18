import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.Option;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.ScheduledThreadPoolExecutor;
import java.lang.reflect.Field;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Real Activation/scheduler sources with private test bindings, not a guest. */
public final class ScheduledFactoryConcurrencyActivationControl {
    private static void require(boolean value, String message) { if (!value) throw new AssertionError(message); }
    private static void await(CountDownLatch latch, String message) throws InterruptedException {
        require(latch.await(5, TimeUnit.SECONDS), message);
    }
    private static Field field(String name) throws Exception {
        var field = Activation.class.getDeclaredField(name); field.setAccessible(true); return field;
    }
    private static Object invoke(String name) throws Exception {
        var method = Activation.class.getDeclaredMethod(name); method.setAccessible(true); return method.invoke(null);
    }
    @SuppressWarnings("unchecked") private static Object enter() throws Exception {
        field("entered").setBoolean(null, true);
        var token = Bindings.LatentRuntimeActivation.register(LatentRuntimeActivationOwnerKind.Task, Option.none()).value();
        var type = Class.forName("dev.latent.guest.runtime.Activation$Work");
        var constructor = type.getDeclaredConstructor(Bindings.LatentRuntimeActivationToken.class);
        constructor.setAccessible(true);
        Object root = constructor.newInstance(token); field("root").set(null, root);
        ((Map<Thread, Object>)field("threads").get(null)).put(Thread.currentThread(), root);
        return root;
    }
    private static int owners(LatentRuntimeActivationOwnerKind kind) { return Bindings.LatentRuntimeActivation.owners(kind); }
    private static void held(int tasks, int queue, int result, int executor) {
        require(owners(LatentRuntimeActivationOwnerKind.Task) == tasks
            && owners(LatentRuntimeActivationOwnerKind.QueuedWork) == queue
            && owners(LatentRuntimeActivationOwnerKind.Result) == result
            && owners(LatentRuntimeActivationOwnerKind.Executor) == executor, "original-owners");
    }
    private static void withdrawn() throws Exception {
        Object root = enter();
        var entered = new CountDownLatch(1);
        var release = new CountDownLatch(1);
        var created = new AtomicReference<Thread>();
        var future = new AtomicReference<ScheduledFuture<?>>();
        var failure = new AtomicReference<Throwable>();
        var calls = new AtomicInteger();
        var pool = new ScheduledThreadPoolExecutor(1, target -> {
            entered.countDown();
            try { await(release, "factory-release"); }
            catch (InterruptedException error) { throw new AssertionError(error); }
            Thread worker = new Thread(target); created.set(worker); return worker;
        });
        Thread caller = new Thread(() -> {
            try { future.set(pool.schedule(calls::incrementAndGet, 1, TimeUnit.DAYS)); }
            catch (Throwable error) { failure.set(error); }
            finally { Activation.finished(Thread.currentThread()); }
        });
        Activation.starting(caller);
        try {
            caller.start(); await(entered, "factory-not-entered");
            held(2, 1, 1, 1);
            field("rootComplete").setBoolean(null, true); invoke("closeCompletedRoot");
            var removed = pool.shutdownNow();
            require(removed.size() == 1 && !pool.isTerminated() && pool.hasPendingWork()
                && (int)invoke("scanPendingPools") == 1 && (boolean)invoke("pending")
                && !(boolean)invoke("retireIdlePools"), "factory-root-fence");
            held(2, 0, 0, 1);
            release.countDown(); caller.join(5000);
            require(!caller.isAlive() && failure.get() == null && future.get() == removed.get(0)
                && created.get() != null && created.get().getState() == Thread.State.NEW
                && pool.isTerminated() && calls.get() == 0, "startup-retirement");
            held(1, 0, 0, 0); future.get().cancel(false); invoke("retireIdlePools");
            require(!(boolean)invoke("pending"), "root-still-pending");
            field("finishingInvocation").setBoolean(null, true);
            var finish = Activation.class.getDeclaredMethod("finishWork", Thread.class, root.getClass(), boolean.class);
            finish.setAccessible(true); finish.invoke(null, null, root, true);
            held(0, 0, 0, 0); invoke("finishInvocation");
        } finally { release.countDown(); caller.join(5000); pool.shutdown(); }
    }
    private static void registering() throws Exception {
        Object root = enter();
        var entered = new CountDownLatch(1);
        var release = new CountDownLatch(1);
        var calls = new AtomicInteger();
        var attempts = new AtomicInteger();
        var observation = new AtomicReference<Boolean>();
        var observationError = new AtomicReference<Throwable>();
        var failure = new AtomicReference<Throwable>();
        // The JVM source control has real parallel threads. Deliver the root
        // interrupt after closeAtRoot returns, as on the cooperative guest
        // scheduler, rather than racing two owner-settlement attempts.
        class DeferredInterruptThread extends Thread {
            volatile boolean requested;
            DeferredInterruptThread(Runnable target) { super(target); }
            @Override public void interrupt() { requested = true; }
            void deliver() { super.interrupt(); }
        }
        var worker = new AtomicReference<DeferredInterruptThread>();
        var pool = new ScheduledThreadPoolExecutor(1, target -> {
            if (attempts.incrementAndGet() == 1) return null;
            entered.countDown();
            try { await(release, "factory-release"); }
            catch (InterruptedException error) { throw new AssertionError(error); }
            var thread = new DeferredInterruptThread(() -> {
                try { Activation.starting(Thread.currentThread()); target.run(); }
                finally { Activation.finished(Thread.currentThread()); }
            });
            worker.set(thread);
            return thread;
        });
        var future = pool.scheduleAtFixedRate(calls::incrementAndGet, 1, 1, TimeUnit.DAYS);
        Thread manual = new Thread(() -> {
            try { ((Runnable)future).run(); }
            catch (Throwable error) { failure.set(error); }
            finally { Activation.finished(Thread.currentThread()); }
        });
        Activation.starting(manual);
        try {
            manual.start(); await(entered, "manual-factory-not-entered");
            held(2, 2, 1, 1);
            require(future.cancel(false), "periodic-cancel");
            held(2, 0, 1, 1);
            field("rootComplete").setBoolean(null, true); invoke("closeCompletedRoot");
            Bindings.LatentRuntimeActivation.registrationObservation = () -> {
                try {
                    observation.set(pool.hasPendingWork() && (int)invoke("scanPendingPools") == 1
                        && !pool.isRetired() && (boolean)invoke("pending") && !(boolean)invoke("retireIdlePools"));
                } catch (Throwable error) { observationError.set(error); }
            };
            release.countDown(); manual.join(5000);
            require(!manual.isAlive() && failure.get() == null && observationError.get() == null
                && Boolean.TRUE.equals(observation.get()) && calls.get() == 1, "worker-registration-root-fence");
            held(1, 0, 0, 1);
            long idleDeadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
            while (pool.hasPendingWork()) {
                require(System.nanoTime() - idleDeadline < 0, "pool-did-not-become-idle");
                Thread.yield();
            }
            invoke("retireIdlePools");
            require(worker.get().requested, "worker-interrupt-not-requested");
            worker.get().deliver(); worker.get().join(5000);
            require(!worker.get().isAlive() && pool.isRetired()
                && owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 0, "worker-retirement");
            held(1, 0, 0, 0);
            require(!(boolean)invoke("pending"), "root-still-pending");
            field("finishingInvocation").setBoolean(null, true);
            var finish = Activation.class.getDeclaredMethod("finishWork", Thread.class, root.getClass(), boolean.class);
            finish.setAccessible(true); finish.invoke(null, null, root, true);
            held(0, 0, 0, 0); invoke("finishInvocation");
        } finally { release.countDown(); manual.join(5000); pool.shutdown(); }
    }
    public static void main(String[] args) throws Exception {
        switch (args[0]) {
            case "withdrawn" -> withdrawn();
            case "registering" -> registering();
            default -> throw new IllegalArgumentException("mode");
        }
        System.out.println("SCHEDULED_FACTORY_CONCURRENCY_ACTIVATION PASS " + args[0]);
    }
}
