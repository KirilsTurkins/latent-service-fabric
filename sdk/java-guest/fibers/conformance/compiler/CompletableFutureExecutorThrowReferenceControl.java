import java.util.ArrayDeque;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionException;

/** Actual public behavior for an executor that can throw after queueing. */
public final class CompletableFutureExecutorThrowReferenceControl {
    private static final class Queue implements Executor {
        final ArrayDeque<Runnable> work = new ArrayDeque<>();
        final RuntimeException failure;
        Queue(RuntimeException failure) { this.failure = failure; }
        @Override public void execute(Runnable command) { work.addLast(command); throw failure; }
        void run() { work.removeFirst().run(); }
    }
    private static void require(boolean value) {
        if (!value) throw new AssertionError("executor-throw-control-shape");
    }
    private static String outcome(CompletableFuture<Integer> future, RuntimeException cause) {
        if (!future.isDone()) return "pending";
        try { return "value-" + future.join(); }
        catch (CompletionException failure) {
            require(failure.getCause() == cause);
            return "original-executor-failure";
        }
    }
    private static void record(String scenario, boolean thrown, int queued, boolean before,
            int calls, String outcome) {
        System.out.println("{\"scenario\":\"" + scenario + "\",\"exceptionPropagated\":" + thrown
            + ",\"queuedBeforeRun\":" + queued + ",\"futureDoneBeforeRun\":" + before
            + ",\"supplierCallsAfterRun\":" + calls + ",\"outcomeAfterRun\":\"" + outcome + "\"}");
    }
    private static void supply(boolean rejected) {
        RuntimeException failure = rejected ? new RejectedExecutionException("queued-rejection")
            : new IllegalStateException("queued-generic-throw");
        Queue queue = new Queue(failure);
        int[] calls = {0};
        boolean thrown = false;
        try { CompletableFuture.supplyAsync(() -> { calls[0]++; return 42; }, queue); }
        catch (RuntimeException observed) { require(observed == failure); thrown = true; }
        require(thrown && queue.work.size() == 1 && calls[0] == 0);
        queue.run();
        record(rejected ? "supply-queued-rejection" : "supply-queued-generic-throw",
            thrown, 1, false, calls[0], "future-not-returned");
    }
    private static void complete(boolean rejected) {
        RuntimeException failure = rejected ? new RejectedExecutionException("queued-rejection")
            : new IllegalStateException("queued-generic-throw");
        Queue queue = new Queue(failure);
        int[] calls = {0};
        CompletableFuture<Integer> future = new CompletableFuture<>();
        boolean thrown = false;
        try { future.completeAsync(() -> { calls[0]++; return 42; }, queue); }
        catch (RuntimeException observed) { require(observed == failure); thrown = true; }
        require(thrown && queue.work.size() == 1 && calls[0] == 0);
        boolean before = future.isDone();
        queue.run();
        record(rejected ? "complete-queued-rejection" : "complete-queued-generic-throw",
            thrown, 1, before, calls[0], outcome(future, failure));
    }
    private static void dependent() {
        RuntimeException failure = new RejectedExecutionException("dependent-queued-rejection");
        Queue queue = new Queue(failure);
        int[] calls = {0};
        CompletableFuture<Integer> future = CompletableFuture.completedFuture(20)
            .thenApplyAsync(value -> { calls[0]++; return value + 22; }, queue);
        require(queue.work.size() == 1 && calls[0] == 0);
        boolean before = future.isDone();
        queue.run();
        record("dependent-queued-rejection", false, 1, before, calls[0], outcome(future, failure));
    }
    private static void synchronous() {
        RuntimeException failure = new RejectedExecutionException("synchronous-run-then-rejection");
        int[] calls = {0};
        CompletableFuture<Integer> future = new CompletableFuture<>();
        Executor executor = command -> { command.run(); throw failure; };
        boolean thrown = false;
        try { future.completeAsync(() -> { calls[0]++; return 42; }, executor); }
        catch (RuntimeException observed) { require(observed == failure); thrown = true; }
        require(thrown);
        record("synchronous-run-then-rejection", thrown, 0, future.isDone(), calls[0], outcome(future, failure));
    }
    public static void main(String[] arguments) {
        supply(true);
        supply(false);
        complete(true);
        complete(false);
        dependent();
        synchronous();
    }
}
