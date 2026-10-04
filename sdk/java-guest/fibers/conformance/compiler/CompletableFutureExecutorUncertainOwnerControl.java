import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.CompletableFuture;
import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionException;

/** No exception from an arbitrary executor is an SDK physical rejection witness. */
public final class CompletableFutureExecutorUncertainOwnerControl {
    private static int checks;
    private static void require(boolean value) {
        if (!value) throw new AssertionError("executor-uncertain-owner-" + checks);
        checks++;
    }
    public static void main(String[] arguments) throws Exception {
        Executor unknown = command -> { throw new RejectedExecutionException("unknown-executor-acceptance"); };
        @SuppressWarnings("unchecked") CompletableFuture<Integer>[] futures = new CompletableFuture[8];
        for (int index = 0; index < futures.length; index++) {
            futures[index] = new CompletableFuture<>();
            try { futures[index].completeAsync(() -> { throw new AssertionError("unknown-supplier"); }, unknown); throw new AssertionError(); }
            catch (RejectedExecutionException observed) { require(observed.getMessage().equals("unknown-executor-acceptance")); }
            require(!futures[index].isDone());
        }
        require(Activation.queuedOwners() == 8 && Activation.resultOwners() == 8);
        CompletableFuture<Integer> overflow = new CompletableFuture<>();
        try { overflow.completeAsync(() -> { throw new AssertionError("overflow-supplier"); }, unknown); throw new AssertionError(); }
        catch (IllegalStateException observed) { require(observed.getMessage().equals("source-control-original-owner-capacity")); }
        require(!overflow.isDone());
        for (CompletableFuture<Integer> future : futures) require(future.cancel(false));
        require(Activation.queuedOwners() == 8 && Activation.resultOwners() == 8);
        try { Activation.cleanup(); throw new AssertionError("unknown-acceptance-cleanup-claimed"); }
        catch (AssertionError observed) { require(observed.getMessage().equals("source-control-unretired-owner")); }
        require(Activation.queuedOwners() == 8 && Activation.resultOwners() == 8);
        // The enclosing bounded JVM owner must physically retire this process.
        // This control deliberately does not claim activation-owner retirement.
        System.out.println("COMPLETABLE_FUTURE_EXECUTOR_UNCERTAIN_OWNER PASS observables=" + checks
            + ";queued=8;results=8;cleanup-denied;activation-retirement-unqualified");
    }
}
