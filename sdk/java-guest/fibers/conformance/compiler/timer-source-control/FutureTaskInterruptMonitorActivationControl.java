import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.Option;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.Executors;
import dev.latent.guest.runtime.concurrent.FutureTask;
import java.lang.reflect.Field;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Real Activation and pool source with private host bindings, not a guest. */
public final class FutureTaskInterruptMonitorActivationControl {
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
        CountDownLatch entered = new CountDownLatch(1), finishBody = new CountDownLatch(1);
        CountDownLatch returning = new CountDownLatch(1), interruptEntered = new CountDownLatch(1);
        CountDownLatch releaseInterrupt = new CountDownLatch(1);
        AtomicReference<Thread> worker = new AtomicReference<>();
        AtomicReference<Throwable> failure = new AtomicReference<>();
        var pool = Executors.newFixedThreadPool(1, target -> {
            Thread thread = new Thread(() -> {
                try { Activation.starting(Thread.currentThread()); target.run(); }
                finally { Activation.finished(Thread.currentThread()); }
            }, "activation-interrupt-worker") {
                @Override public void interrupt() {
                    interruptEntered.countDown();
                    try { await(releaseInterrupt, "interrupt-release"); }
                    catch (InterruptedException error) { throw new AssertionError(error); }
                    super.interrupt();
                }
            };
            worker.set(thread); return thread;
        });
        FutureTask<Integer> future = new FutureTask<>(() -> { entered.countDown(); finishBody.await(); returning.countDown(); return 42; });
        Thread canceller = new Thread(() -> {
            try { require(future.cancel(true), "cancel-refused"); }
            catch (Throwable error) { failure.set(error); }
        }, "activation-interrupt-canceller");
        try {
            pool.execute(future); await(entered, "callback-not-started"); held(0, 1, 1);
            canceller.start(); await(interruptEntered, "interrupt-not-entered");
            require(future.isDone() && future.isCancelled() && !future.cancel(false), "cancel-state-inaccessible");
            finishBody.countDown(); await(returning, "callback-not-returning"); held(0, 1, 1);
            require(owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 1, "worker-not-owned");
            pool.shutdown(); field("rootComplete").setBoolean(null, true); invoke("closeCompletedRoot");
            require((boolean)invoke("pending") && !(boolean)invoke("retireIdlePools"), "root-not-fenced");
            releaseInterrupt.countDown(); canceller.join(5000); worker.get().join(5000);
            require(!canceller.isAlive() && !worker.get().isAlive() && failure.get() == null
                && owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 0, "physical-retirement");
            held(0, 0, 0); invoke("retireIdlePools");
            require(!(boolean)invoke("pending"), "root-still-pending");
            field("finishingInvocation").setBoolean(null, true);
            var finish = Activation.class.getDeclaredMethod("finishWork", Thread.class, root.getClass(), boolean.class);
            finish.setAccessible(true); finish.invoke(null, null, root, true);
            require(owners(LatentRuntimeActivationOwnerKind.Task) == 0, "root-owner-not-settled");
            invoke("finishInvocation");
        } finally { finishBody.countDown(); releaseInterrupt.countDown(); canceller.join(5000); pool.shutdownNow(); }
        System.out.println("FUTURE_TASK_INTERRUPT_MONITOR_ACTIVATION PASS visible;interrupt-pending;root-fenced;retired");
    }
}
