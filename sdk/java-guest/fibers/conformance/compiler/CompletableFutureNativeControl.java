import java.util.ArrayDeque;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executor;
import java.util.concurrent.Future;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/** Same standard-API observables run against the reference JDK and SDK source port. */
public final class CompletableFutureNativeControl {
    private static int checks;
    private static void require(boolean condition) { checks++; if (!condition) throw new AssertionError(checks); }
    private static final class Queue implements Executor {
        final ArrayDeque<Runnable> work = new ArrayDeque<>();
        @Override public void execute(Runnable command) { work.add(command); }
        void run() { work.removeFirst().run(); }
    }
    private static void await(CountDownLatch latch) {
        try { if (!latch.await(3, TimeUnit.SECONDS)) throw new AssertionError("source-control-watchdog"); }
        catch (InterruptedException error) { throw new AssertionError(error); }
    }
    public static void main(String[] arguments) throws Exception {
        CompletableFuture<Integer> pending = new CompletableFuture<>();
        int[] calls = {0};
        Thread original = Thread.currentThread();
        CompletableFuture<Integer> changed = pending.thenApply(value -> {
            calls[0]++; require(Thread.currentThread() == original); return value + 22;
        });
        require(!pending.isDone() && !changed.isDone() && calls[0] == 0);
        require(pending.complete(20) && !pending.complete(99));
        require(changed.get() == 42 && calls[0] == 1);
        require(pending.getNow(-1) == 20 && changed.resultNow() == 42);
        require(changed.state() == Future.State.SUCCESS);
        require(CompletableFuture.completedFuture(null).join() == null);
        require(new CompletableFuture<Integer>().getNow(7) == 7);

        Queue queue = new Queue();
        CompletableFuture<Integer> queued = CompletableFuture.supplyAsync(() -> { calls[0]++; return 42; }, queue);
        require(!queued.isDone() && calls[0] == 1);
        queue.run(); require(queued.join() == 42 && calls[0] == 2);
        CompletableFuture<Integer> cancelled = CompletableFuture.supplyAsync(() -> { calls[0]++; return 99; }, queue);
        require(cancelled.cancel(true) && cancelled.cancel(false) && cancelled.isCancelled());
        queue.run(); require(calls[0] == 2);
        try { cancelled.get(); throw new AssertionError(); } catch (java.util.concurrent.CancellationException expected) { checks++; }
        CompletableFuture<Integer> cancelledChild = cancelled.thenApply(value -> value + 1);
        require(cancelledChild.isCompletedExceptionally() && !cancelledChild.isCancelled());
        try { cancelledChild.join(); throw new AssertionError(); }
        catch (CompletionException error) { require(error.getCause() instanceof java.util.concurrent.CancellationException); }

        IllegalArgumentException cause = new IllegalArgumentException("original-cause");
        CompletableFuture<Integer> failed = CompletableFuture.failedFuture(cause);
        require(failed.isCompletedExceptionally() && failed.exceptionNow() == cause);
        try { failed.get(); throw new AssertionError(); } catch (ExecutionException error) { require(error.getCause() == cause); }
        try { failed.getNow(0); throw new AssertionError(); } catch (CompletionException error) { require(error.getCause() == cause); }
        require(failed.exceptionally(error -> { require(error == cause); return 42; }).join() == 42);
        require(failed.handle((value, error) -> error == cause ? 42 : 0).join() == 42);
        IllegalStateException secondary = new IllegalStateException("secondary");
        CompletableFuture<Integer> observed = failed.whenComplete((value, error) -> { throw secondary; });
        try { observed.get(); throw new AssertionError(); } catch (ExecutionException error) { require(error.getCause() == cause); }
        require(cause.getSuppressed().length == 1 && cause.getSuppressed()[0] == secondary);
        require(failed.exceptionallyCompose(error -> CompletableFuture.completedFuture(42)).join() == 42);

        CompletableFuture<Integer> inner = new CompletableFuture<>();
        CompletableFuture<Integer> composed = CompletableFuture.completedFuture(20).thenCompose(value -> inner);
        require(!composed.isDone()); inner.complete(42); require(composed.join() == 42);
        CompletionStage<Integer> stage = CompletableFuture.completedFuture(20);
        require(stage.thenApply(value -> value + 22).toCompletableFuture().get() == 42);
        require(CompletableFuture.completedFuture(20).thenCombine(CompletableFuture.completedFuture(22), Integer::sum).join() == 42);
        CompletableFuture<Integer> left = new CompletableFuture<>();
        CompletableFuture<Integer> right = new CompletableFuture<>();
        CompletableFuture<Integer> either = left.applyToEither(right, value -> value + 1);
        right.complete(41); require(either.join() == 42 && !left.isDone());
        require(CompletableFuture.anyOf(left, right).join().equals(41));
        require(CompletableFuture.allOf().isDone() && !CompletableFuture.anyOf().isDone());
        CompletableFuture<Void> all = CompletableFuture.allOf(left, right);
        require(!all.isDone()); left.complete(1); require(all.join() == null);
        int[] callbacks = {0};
        require(right.thenAccept(value -> callbacks[0] += value).thenRun(() -> callbacks[0]++).join() == null);
        require(callbacks[0] == 42);
        require(left.thenAcceptBoth(right, (a, b) -> callbacks[0] = a + b).join() == null && callbacks[0] == 42);
        require(left.runAfterEither(new CompletableFuture<>(), () -> callbacks[0]++).join() == null && callbacks[0] == 43);

        CompletableFuture<Integer> waiting = new CompletableFuture<>();
        for (long allowance : new long[]{0, -1, Long.MIN_VALUE}) {
            try { waiting.get(allowance, TimeUnit.NANOSECONDS); throw new AssertionError(); }
            catch (TimeoutException expected) { checks++; }
        }
        Thread.currentThread().interrupt();
        require(right.get(-1, TimeUnit.NANOSECONDS) == 41 && Thread.currentThread().isInterrupted());
        require(Thread.interrupted());
        Thread.currentThread().interrupt();
        try { waiting.get(); throw new AssertionError(); } catch (InterruptedException expected) { require(!Thread.currentThread().isInterrupted()); }
        CompletableFuture<Integer> completeAsync = CompletableFuture.completedFuture(42);
        require(completeAsync.completeAsync(() -> { throw new AssertionError("completed-supplier-ran"); }, queue) == completeAsync);
        require(queue.work.size() == 1); queue.run(); require(completeAsync.join() == 42);
        Executor reject = command -> { throw new RejectedExecutionException("source-control-denied"); };
        try { CompletableFuture.supplyAsync(() -> 42, reject); throw new AssertionError(); }
        catch (RejectedExecutionException expected) { checks++; }
        CompletableFuture<Integer> rejectedStage = right.thenApplyAsync(value -> value + 1, reject);
        try { rejectedStage.get(); throw new AssertionError(); }
        catch (ExecutionException error) { require(error.getCause() instanceof RejectedExecutionException); }

        ThreadLocal<String> local = new ThreadLocal<>(); local.set("root");
        require(CompletableFuture.supplyAsync(() -> Thread.currentThread() != original && local.get() == null).get());
        require(CompletableFuture.supplyAsync(() -> 20).thenApplyAsync(value -> value + 22).get() == 42);
        require(CompletableFuture.runAsync(() -> { }).thenRunAsync(() -> { }).get() == null);
        require(failed.exceptionallyAsync(error -> 42).get() == 42);
        require(failed.exceptionallyComposeAsync(error -> CompletableFuture.supplyAsync(() -> 42)).get() == 42);
        CountDownLatch started = new CountDownLatch(1), release = new CountDownLatch(1), exited = new CountDownLatch(1);
        boolean[] interrupted = {false};
        CompletableFuture<Integer> running = CompletableFuture.supplyAsync(() -> {
            started.countDown();
            try { release.await(); return 42; }
            catch (InterruptedException error) { interrupted[0] = true; return 0; }
            finally { exited.countDown(); }
        });
        await(started); require(running.cancel(true)); release.countDown(); await(exited);
        require(!interrupted[0] && running.isCancelled());
        System.out.println("COMPLETABLE_FUTURE_SOURCE_CONTROL PASS observables=" + checks);
    }
}
