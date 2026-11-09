import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Source-port control only; its owner ledger and worker gate are private doubles. */
public final class ExecutorInvokeInterruptOwnerControl {
    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    private static void pending(boolean any) throws Exception {
        CountDownLatch workerReady = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicBoolean admitted = new AtomicBoolean();
        AtomicInteger calls = new AtomicInteger();
        AtomicReference<String> outcome = new AtomicReference<>("not-finished");
        ExecutorService pool = dev.latent.guest.runtime.concurrent.Executors.newFixedThreadPool(1, task ->
            new Thread(() -> {
                workerReady.countDown();
                try { release.await(); }
                catch (InterruptedException error) { Thread.currentThread().interrupt(); }
                task.run();
            }, "preinterrupt-gated-worker"));
        try {
            Activation.admissionObservationKind = "Result";
            Activation.admissionObservation = () -> {
                require(Activation.count(LatentRuntimeActivationOwnerKind.Executor) == 1, "executor owner absent");
                require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == 1, "queued owner absent");
                require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == 1, "result owner absent");
                admitted.set(true);
            };
            Thread caller = new Thread(() -> {
                Thread.currentThread().interrupt();
                try {
                    List<Callable<Integer>> tasks = List.of(() -> { calls.incrementAndGet(); return 42; });
                    if (any) pool.invokeAny(tasks); else pool.invokeAll(tasks);
                    outcome.set("unexpected-return");
                } catch (InterruptedException error) {
                    outcome.set(Thread.currentThread().isInterrupted() ? "interrupt-not-cleared" : "interrupted");
                } catch (Exception error) { outcome.set(error.getClass().getName()); }
            }, "preinterrupt-caller");
            caller.start();
            caller.join(5000);
            require(!caller.isAlive() && "interrupted".equals(outcome.get()), "caller " + outcome.get());
            require(admitted.get(), "result and queued work were not admitted");
            require(workerReady.await(5, TimeUnit.SECONDS), "worker did not start");
            require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == 1, "queued owner retired before drain");
            require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == 0, "cancelled result was not settled");
            require(calls.get() == 0, "cancelled task ran before drain");
        } finally {
            Activation.admissionObservation = null;
            Activation.admissionObservationKind = null;
            release.countDown();
            pool.shutdown();
            require(pool.awaitTermination(5, TimeUnit.SECONDS), "pool did not retire");
        }
        require(calls.get() == 0, "cancelled task ran after drain");
        Activation.idle();
    }
    public static void main(String[] args) throws Exception {
        pending(false);
        pending(true);
        System.out.println("EXECUTOR_INVOKE_INTERRUPT_OWNER PASS all;any;queued-until-drain;result-settled");
    }
}
