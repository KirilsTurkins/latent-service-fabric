import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.AbstractExecutorService;
import dev.latent.guest.runtime.concurrent.Executors;
import dev.latent.generated.Bindings;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

public final class InvokeAnyAcceptedThrowOwnerProbe {
    private static String counts() {
        return Activation.count(Bindings.LatentRuntimeActivationOwnerKind.Executor) + ":"
            + Activation.count(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork) + ":"
            + Activation.count(Bindings.LatentRuntimeActivationOwnerKind.Result);
    }
    private static final class AcceptThenThrow extends AbstractExecutorService {
        final ExecutorService pool;
        int calls;
        AcceptThenThrow(ExecutorService pool) { this.pool = pool; }
        @Override public void execute(Runnable work) {
            calls++;
            pool.execute(work);
            throw new RejectedExecutionException("after-accept");
        }
        @Override public void shutdown() { pool.shutdown(); }
        @Override public List<Runnable> shutdownNow() { return pool.shutdownNow(); }
        @Override public boolean isShutdown() { return pool.isShutdown(); }
        @Override public boolean isTerminated() { return pool.isTerminated(); }
        @Override public boolean awaitTermination(long n, TimeUnit u) throws InterruptedException {
            return pool.awaitTermination(n, u);
        }
    }
    public static void main(String[] args) throws Exception {
        CountDownLatch workerReady = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicInteger callbacks = new AtomicInteger();
        ExecutorService pool = Executors.newFixedThreadPool(1, target -> new Thread(() -> {
            workerReady.countDown();
            try { if (!release.await(5, TimeUnit.SECONDS)) throw new AssertionError("release"); }
            catch (InterruptedException error) { throw new AssertionError(error); }
            target.run();
        }, "accepted-worker"));
        AcceptThenThrow executor = new AcceptThenThrow(pool);
        try {
            Callable<Integer> task = () -> { callbacks.incrementAndGet(); return 42; };
            try {
                executor.invokeAny(List.of(task, task));
                throw new AssertionError("expected rejection");
            } catch (RejectedExecutionException expected) {
                if (!"after-accept".equals(expected.getMessage())) throw expected;
            }
            if (!workerReady.await(5, TimeUnit.SECONDS) || executor.calls != 1 || callbacks.get() != 0
                    || !"1:1:0".equals(counts()) || !((Activation.ManagedPool)pool).hasPendingWork())
                throw new AssertionError("accepted-custody-" + counts());
            release.countDown();
            pool.shutdown();
            if (!pool.awaitTermination(5, TimeUnit.SECONDS)) throw new AssertionError("termination");
            Activation.idle();
            if (callbacks.get() != 0 || !"0:0:0".equals(counts())) throw new AssertionError("retirement-" + counts());
            System.out.println("accepted-throw:held=1:1:0:pending=true:callbacks=0:after=0:0:0");
        } finally {
            release.countDown();
            pool.shutdownNow();
        }
    }
}
