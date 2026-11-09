import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

/** Private-ledger source control; it does not prove physical host retirement. */
public final class ExecutorAwaitTerminationOwnerControl {
    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    private static void running(boolean scheduled) throws Exception {
        ExecutorService executor = scheduled
            ? dev.latent.guest.runtime.concurrent.Executors.newScheduledThreadPool(1)
            : dev.latent.guest.runtime.concurrent.Executors.newFixedThreadPool(1);
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        try {
            Future<Integer> result = executor.submit(() -> {
                entered.countDown();
                release.await();
                return 42;
            });
            require(entered.await(5, TimeUnit.SECONDS), "worker did not enter");
            executor.shutdown();
            require(Activation.count(LatentRuntimeActivationOwnerKind.Executor) == 1, "executor owner absent");
            require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == 1, "running result owner absent");
            Thread.currentThread().interrupt();
            require(!executor.awaitTermination(0, TimeUnit.NANOSECONDS), "running pool reported terminated");
            require(Thread.currentThread().isInterrupted(), "zero-timeout lost interrupt");
            Thread.interrupted();
            require(Activation.count(LatentRuntimeActivationOwnerKind.Executor) == 1, "executor retired early");
            require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == 1, "result retired early");
            Thread.currentThread().interrupt();
            try {
                executor.awaitTermination(10, TimeUnit.SECONDS);
                throw new AssertionError("missing positive-timeout interruption");
            } catch (InterruptedException expected) {
                require(!Thread.currentThread().isInterrupted(), "interrupt not cleared");
            }
            require(Activation.count(LatentRuntimeActivationOwnerKind.Executor) == 1, "interruption retired executor");
            require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == 1, "interruption retired result");
            release.countDown();
            require(result.get(5, TimeUnit.SECONDS) == 42, "callback result");
            require(executor.awaitTermination(5, TimeUnit.SECONDS), "pool did not retire");
        } finally {
            Thread.interrupted();
            release.countDown();
            executor.shutdownNow();
            require(executor.awaitTermination(5, TimeUnit.SECONDS), "cleanup did not retire");
        }
        Activation.idle();
    }
    public static void main(String[] args) throws Exception {
        running(false);
        running(true);
        System.out.println("EXECUTOR_AWAIT_TERMINATION_OWNER PASS managed;scheduled;owners-held-until-worker-return");
    }
}
