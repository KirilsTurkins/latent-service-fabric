import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.Option;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.ScheduledThreadPoolExecutor;
import java.lang.reflect.Field;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/** Actual Activation/scheduled-pool source with private host bindings, not a guest. */
public final class ScheduledExecutorStatusActivationControl {
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
    private static void held(int queue, int result, int executor) {
        require(owners(LatentRuntimeActivationOwnerKind.Task) == 1
            && owners(LatentRuntimeActivationOwnerKind.QueuedWork) == queue
            && owners(LatentRuntimeActivationOwnerKind.Result) == result
            && owners(LatentRuntimeActivationOwnerKind.Executor) == executor, "original-owners");
    }
    public static void main(String[] args) throws Exception {
        Object root = enter();
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicReference<ScheduledThreadPoolExecutor> selected = new AtomicReference<>();
        AtomicReference<Thread> worker = new AtomicReference<>(), inspector = new AtomicReference<>();
        AtomicBoolean visible = new AtomicBoolean(), observed = new AtomicBoolean();
        var pool = new ScheduledThreadPoolExecutor(1, target -> {
            Thread thread = new Thread(() -> {
                try { Activation.starting(Thread.currentThread()); target.run(); }
                finally { Activation.finished(Thread.currentThread()); }
            }, "activation-scheduled-status-worker") {
                @Override public void interrupt() {
                    CountDownLatch started = new CountDownLatch(1), finished = new CountDownLatch(1);
                    Thread probe = new Thread(() -> {
                        started.countDown();
                        try { observed.set(selected.get().isShutdown() && !selected.get().isTerminated()); }
                        finally { finished.countDown(); }
                    }, "activation-scheduled-status-inspector");
                    inspector.set(probe); probe.start();
                    try { await(started, "inspector-not-started"); visible.set(finished.await(2, TimeUnit.SECONDS) && observed.get()); }
                    catch (InterruptedException error) { throw new AssertionError(error); }
                    super.interrupt();
                }
            };
            worker.set(thread); return thread;
        });
        selected.set(pool);
        try {
            var future = pool.submit(() -> {
                entered.countDown();
                while (true) try { release.await(); return 42; } catch (InterruptedException ignored) { }
            });
            await(entered, "callback-not-entered"); held(1, 1, 1);
            require(pool.shutdownNow().isEmpty() && visible.get(), "status-not-visible-in-interrupt");
            require(pool.isShutdown() && !pool.isTerminated(), "running-pool-terminated"); held(1, 1, 1);
            field("rootComplete").setBoolean(null, true); invoke("closeCompletedRoot");
            require((boolean)invoke("pending") && !(boolean)invoke("retireIdlePools"), "root-not-fenced");
            release.countDown(); worker.get().join(5000); inspector.get().join(5000);
            require(!worker.get().isAlive() && !inspector.get().isAlive() && future.get() == 42
                && pool.isTerminated() && owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 0, "physical-retirement");
            held(0, 0, 0); invoke("retireIdlePools");
            require(!(boolean)invoke("pending"), "root-still-pending");
            field("finishingInvocation").setBoolean(null, true);
            var finish = Activation.class.getDeclaredMethod("finishWork", Thread.class, root.getClass(), boolean.class);
            finish.setAccessible(true); finish.invoke(null, null, root, true);
            require(owners(LatentRuntimeActivationOwnerKind.Task) == 0, "root-owner-not-settled");
            invoke("finishInvocation");
        } finally { release.countDown(); pool.shutdown(); }
        System.out.println("SCHEDULED_EXECUTOR_STATUS_ACTIVATION PASS interrupt;owned;root-fenced;retired");
    }
}
