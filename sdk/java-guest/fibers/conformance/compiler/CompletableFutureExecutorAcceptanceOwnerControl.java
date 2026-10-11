import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.CompletableFuture;
import dev.latent.guest.runtime.concurrent.CompletionException;
import java.util.ArrayDeque;
import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionException;

/** Real port bodies; physical queues and the private original 8/8 ledger bounds. */
public final class CompletableFutureExecutorAcceptanceOwnerControl {
    private static int checks;
    private static void require(boolean value) {
        if (!value) throw new AssertionError("executor-acceptance-owner-" + checks);
        checks++;
    }
    private static void owners(int queued, int results) {
        require(Activation.queuedOwners() == queued && Activation.resultOwners() == results);
    }
    private static final class Queue implements Executor {
        final ArrayDeque<Runnable> tasks = new ArrayDeque<>();
        final RuntimeException failure;
        Queue(RuntimeException failure) { this.failure = failure; }
        @Override public void execute(Runnable command) { tasks.addLast(command); throw failure; }
        void run() { tasks.removeFirst().run(); }
    }
    public static void main(String[] arguments) throws Exception {
        int[] calls = {0};
        for (boolean rejected : new boolean[]{true, false}) {
            RuntimeException failure = rejected ? new RejectedExecutionException("accepted-then-rejected")
                : new IllegalStateException("accepted-then-generic-throw");
            Queue queue = new Queue(failure);
            try { CompletableFuture.supplyAsync(() -> { calls[0]++; return 42; }, queue); throw new AssertionError(); }
            catch (RuntimeException observed) { require(observed == failure); }
            require(queue.tasks.size() == 1); owners(1, 1);
            queue.run(); owners(0, 0);
        }
        require(calls[0] == 2);

        Queue uncertain = new Queue(new RejectedExecutionException("cancel-after-unknown-acceptance"));
        CompletableFuture<Integer> cancelled = new CompletableFuture<>();
        try { cancelled.completeAsync(() -> { calls[0]++; return 99; }, uncertain); throw new AssertionError(); }
        catch (RejectedExecutionException observed) { require(observed == uncertain.failure); }
        require(!cancelled.isDone()); owners(1, 1);
        require(cancelled.cancel(true)); owners(1, 1);
        uncertain.run(); require(calls[0] == 2 && cancelled.isCancelled()); owners(0, 0);

        Queue stages = new Queue(new IllegalStateException("dependent-unknown-acceptance"));
        CompletableFuture<Integer> stage = CompletableFuture.completedFuture(20)
            .thenApplyAsync(value -> { calls[0]++; return value + 22; }, stages);
        require(stage.isCompletedExceptionally()); owners(1, 1);
        try { stage.join(); throw new AssertionError(); }
        catch (CompletionException observed) { require(observed.getCause() == stages.failure); }
        stages.run(); require(calls[0] == 2); owners(0, 0);

        CompletableFuture<Integer> notAccepted = new CompletableFuture<>();
        try { notAccepted.completeAsync(() -> { throw new AssertionError("rejected-supplier"); },
                dev.latent.guest.runtime.concurrent.Executors.rejected()); throw new AssertionError(); }
        catch (RejectedExecutionException expected) { require(!notAccepted.isDone()); }
        owners(0, 0); require(notAccepted.cancel(true)); owners(0, 0);

        Queue bounded = new Queue(new RejectedExecutionException("original-capacity-occupied"));
        @SuppressWarnings("unchecked") CompletableFuture<Integer>[] occupied = new CompletableFuture[8];
        for (int index = 0; index < occupied.length; index++) {
            occupied[index] = new CompletableFuture<>();
            try { occupied[index].completeAsync(() -> { calls[0]++; return 99; }, bounded); throw new AssertionError(); }
            catch (RejectedExecutionException observed) { require(observed == bounded.failure); }
        }
        owners(8, 8); require(bounded.tasks.size() == 8);
        CompletableFuture<Integer> overflow = new CompletableFuture<>();
        try { overflow.completeAsync(() -> { throw new AssertionError("overflow-supplier"); }, bounded); throw new AssertionError(); }
        catch (IllegalStateException observed) { require(observed.getMessage().equals("source-control-original-owner-capacity")); }
        owners(8, 8); require(bounded.tasks.size() == 8 && !overflow.isDone());
        for (CompletableFuture<Integer> future : occupied) require(future.cancel(false));
        owners(8, 8);
        while (!bounded.tasks.isEmpty()) bounded.run();
        require(calls[0] == 2); owners(0, 0);
        Activation.cleanup();
        System.out.println("COMPLETABLE_FUTURE_EXECUTOR_ACCEPTANCE_OWNER PASS observables=" + checks);
    }
}
