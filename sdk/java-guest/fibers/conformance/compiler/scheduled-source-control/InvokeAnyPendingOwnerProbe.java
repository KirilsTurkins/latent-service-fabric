import dev.latent.generated.Bindings;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.Executors;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** The held worker preserves the original queue entries after invokeAny returns. */
public final class InvokeAnyPendingOwnerProbe {
    private static String counts() {
        return Activation.count(Bindings.LatentRuntimeActivationOwnerKind.Executor) + ":"
            + Activation.count(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork) + ":"
            + Activation.count(Bindings.LatentRuntimeActivationOwnerKind.Result);
    }
    public static void main(String[] args) throws Exception {
        String mode = args[0];
        if (!mode.equals("timeout") && !mode.equals("interrupt")) throw new AssertionError("mode");
        CountDownLatch workerReady = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicInteger calls = new AtomicInteger();
        AtomicReference<String> outcome = new AtomicReference<>();
        ExecutorService pool = Executors.newFixedThreadPool(1, target -> new Thread(() -> {
            workerReady.countDown();
            try { if (!release.await(5, TimeUnit.SECONDS)) throw new AssertionError("release"); }
            catch (InterruptedException error) { throw new AssertionError(error); }
            target.run();
        }, "gated-worker"));
        Thread caller = new Thread(() -> {
            if (mode.equals("interrupt")) Thread.currentThread().interrupt();
            Callable<Integer> first = () -> { calls.incrementAndGet(); return 1; };
            Callable<Integer> second = () -> { calls.incrementAndGet(); return 2; };
            try {
                if (mode.equals("timeout")) pool.invokeAny(List.of(first, second), 0, TimeUnit.NANOSECONDS);
                else pool.invokeAny(List.of(first, second));
                outcome.set("unexpected");
            } catch (InterruptedException error) {
                outcome.set(Thread.currentThread().isInterrupted() ? "flag-not-cleared" : "interrupted");
            } catch (TimeoutException error) { outcome.set("timeout"); }
            catch (Exception error) { outcome.set(error.getClass().getSimpleName()); }
        }, "pending-caller");
        try {
            caller.start();
            caller.join(5000);
            if (caller.isAlive()) throw new AssertionError("caller-not-finished");
            if (!workerReady.await(5, TimeUnit.SECONDS)) throw new AssertionError("worker-not-ready");
            String expected = mode.equals("timeout") ? "timeout" : "interrupted";
            if (!expected.equals(outcome.get()) || calls.get() != 0 || !counts().equals("1:2:0")
                    || !((Activation.ManagedPool)pool).hasPendingWork())
                throw new AssertionError("pending-custody-" + outcome.get() + ":" + counts());
            release.countDown();
            pool.shutdown();
            if (!pool.awaitTermination(5, TimeUnit.SECONDS)) throw new AssertionError("termination");
            Activation.idle();
            if (calls.get() != 0 || !counts().equals("0:0:0")) throw new AssertionError("cancelled-work-retirement");
            System.out.println(mode + ":outcome=" + outcome.get() + ":held=1:2:0:pending=true:after=0:0:0");
        } finally {
            release.countDown();
            caller.join(5000);
            pool.shutdownNow();
        }
    }
}
