import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;

/** This finite JVM observer retires its whole process, not an uncertain producer early. */
public final class CompletableFutureDelayedUncertainControl {
    private static int checks;
    private static void require(boolean condition) {
        if (!condition) throw new AssertionError("uncertain-delayed-" + checks);
        checks++;
    }
    public static void main(String[] args) throws Exception {
        for (int index = 0; index < 2; index++) {
            CountDownLatch rejected = new CountDownLatch(1);
            CompletableFuture<Integer> future = CompletableFuture.supplyAsync(() -> {
                throw new AssertionError("unaccepted-supplier-ran");
            }, CompletableFuture.delayedExecutor(0, TimeUnit.SECONDS, command -> {
                rejected.countDown(); throw new RejectedExecutionException("no-owned-rejection-witness");
            }));
            require(rejected.await(3, TimeUnit.SECONDS));
            require(!future.isDone());
            require(Activation.queuedOwners() == 2 * (index + 1) && Activation.resultOwners() == index + 1
                && Activation.deferredOwners() == index + 1);
            require(future.cancel(true) && future.isCancelled());
            Thread helper = Activation.deferredForControl();
            helper.interrupt(); helper.join(25);
            require(helper.isAlive());
            require(Activation.queuedOwners() == 2 * (index + 1) && Activation.resultOwners() == index + 1
                && Activation.deferredOwners() == index + 1);
        }
        System.out.println("COMPLETABLE_DELAYED_UNCERTAIN PASS observables=" + checks
            + ";owners-held=4queued/2result/2task;termination=whole-owned-JVM");
        System.exit(0);
    }
}
