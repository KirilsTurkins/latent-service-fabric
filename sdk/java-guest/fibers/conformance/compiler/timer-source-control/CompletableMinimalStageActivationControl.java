import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.Option;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.CompletableFuture;
import dev.latent.guest.runtime.concurrent.Executors;
import java.lang.reflect.Field;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Actual Activation and Java sources with private host bindings, not a guest. */
public final class CompletableMinimalStageActivationControl {
    private static void require(boolean value, String message) { if (!value) throw new AssertionError(message); }
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
    private static int owners(LatentRuntimeActivationOwnerKind kind) {
        return Bindings.LatentRuntimeActivation.owners(kind);
    }
    private static void held(int queue, int result, int executor) {
        require(owners(LatentRuntimeActivationOwnerKind.Task) == 1
            && owners(LatentRuntimeActivationOwnerKind.QueuedWork) == queue
            && owners(LatentRuntimeActivationOwnerKind.Result) == result
            && owners(LatentRuntimeActivationOwnerKind.Executor) == executor, "owner-custody");
    }
    public static void main(String[] args) throws Exception {
        Object root = enter();
        AtomicReference<Thread> worker = new AtomicReference<>();
        AtomicInteger calls = new AtomicInteger();
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        var pool = Executors.newFixedThreadPool(1, target -> {
            Thread thread = new Thread(() -> {
                try { Activation.starting(Thread.currentThread()); target.run(); }
                finally { Activation.finished(Thread.currentThread()); }
            });
            worker.set(thread); return thread;
        });
        try {
            var source = new CompletableFuture<Integer>();
            var next = source.minimalCompletionStage().thenApplyAsync(value -> {
                calls.incrementAndGet(); entered.countDown();
                while (true) try { release.await(); return value + 1; } catch (InterruptedException ignored) { }
            }, pool);
            var cancelled = next.toCompletableFuture();
            var delivered = next.toCompletableFuture();
            require(source.complete(41) && entered.await(5, TimeUnit.SECONDS), "callback-not-started");
            require(cancelled.cancel(true), "copy-not-cancelled"); held(2, 2, 1);
            require(owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 1, "worker-not-owned");
            pool.shutdown(); field("rootComplete").setBoolean(null, true); invoke("closeCompletedRoot");
            require((boolean)invoke("pending") && !(boolean)invoke("retireIdlePools"), "root-not-fenced");
            release.countDown(); worker.get().join(5000);
            require(!worker.get().isAlive() && calls.get() == 1 && delivered.join() == 42
                && owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 0, "callback-not-retired");
            held(0, 0, 0); invoke("retireIdlePools");
            require(!(boolean)invoke("pending"), "root-still-pending");
            field("finishingInvocation").setBoolean(null, true);
            var finish = Activation.class.getDeclaredMethod("finishWork", Thread.class, root.getClass(), boolean.class);
            finish.setAccessible(true); finish.invoke(null, null, root, true);
            require(owners(LatentRuntimeActivationOwnerKind.Task) == 0, "root-owner-not-settled");
            invoke("finishInvocation");
        } finally { release.countDown(); pool.shutdownNow(); }
        System.out.println("COMPLETABLE_MINIMAL_STAGE_ACTIVATION PASS copy-cancel;running;root-fenced;retired");
    }
}
