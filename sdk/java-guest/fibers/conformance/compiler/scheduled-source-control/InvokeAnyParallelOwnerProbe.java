import dev.latent.generated.Bindings;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.Executors;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** A completed winner must not settle a still-running loser's original Result owner. */
public final class InvokeAnyParallelOwnerProbe {
    private static String counts() {
        return Activation.count(Bindings.LatentRuntimeActivationOwnerKind.Executor) + ":"
            + Activation.count(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork) + ":"
            + Activation.count(Bindings.LatentRuntimeActivationOwnerKind.Result);
    }
    private static void await(CountDownLatch latch, String name) throws Exception {
        if (!latch.await(5, TimeUnit.SECONDS)) throw new AssertionError(name);
    }
    public static void main(String[] args) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(2);
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1), returned = new CountDownLatch(1);
        AtomicBoolean physical = new AtomicBoolean();
        AtomicInteger interrupts = new AtomicInteger();
        AtomicReference<Object> outcome = new AtomicReference<>();
        Thread caller = new Thread(() -> {
            Callable<Integer> first = () -> {
                physical.set(true);
                entered.countDown();
                while (release.getCount() != 0) {
                    try { release.await(); }
                    catch (InterruptedException error) { interrupts.incrementAndGet(); }
                }
                physical.set(false);
                return 1;
            };
            Callable<Integer> second = () -> {
                if (!entered.await(5, TimeUnit.SECONDS)) throw new AssertionError("first-not-entered");
                return 42;
            };
            try { outcome.set(pool.invokeAny(List.of(first, second))); }
            catch (Throwable error) { outcome.set(error); }
            finally { returned.countDown(); }
        }, "invoke-any-caller");
        try {
            caller.start();
            await(entered, "entry");
            await(returned, "result");
            caller.join(5000);
            if (caller.isAlive() || !Integer.valueOf(42).equals(outcome.get()) || !physical.get())
                throw new AssertionError("result-or-physical-" + outcome.get());
            long deadline = System.nanoTime() + 5_000_000_000L;
            while (!counts().equals("1:0:1") || interrupts.get() == 0) {
                if (System.nanoTime() - deadline >= 0) throw new AssertionError("original-owners-" + counts() + ":" + interrupts.get());
                Thread.sleep(1);
            }
            String held = counts();
            if (!((Activation.ManagedPool)pool).hasPendingWork()) throw new AssertionError("physical-not-pending");
            pool.shutdown();
            if (pool.isTerminated()) throw new AssertionError("terminated-before-physical-return");
            release.countDown();
            if (!pool.awaitTermination(5, TimeUnit.SECONDS)) throw new AssertionError("termination");
            Activation.idle();
            if (!counts().equals("0:0:0")) throw new AssertionError("retirement-" + counts());
            System.out.println("parallel:result=42:held=" + held + ":pending=true:cancelInterrupt=true:after=0:0:0");
        } finally {
            release.countDown();
            caller.join(5000);
            pool.shutdownNow();
        }
    }
}
