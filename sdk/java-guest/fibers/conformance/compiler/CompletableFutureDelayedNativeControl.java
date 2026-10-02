import java.util.ArrayList;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Standard delayed dispatch observations, including terminal futures before dispatch. */
public final class CompletableFutureDelayedNativeControl {
    private static int checks;
    private static void require(boolean condition) {
        if (!condition) throw new AssertionError("delayed-observable-" + checks);
        checks++;
    }
    private static void await(CountDownLatch latch) {
        try { require(latch.await(3, TimeUnit.SECONDS)); }
        catch (InterruptedException error) { throw new AssertionError(error); }
    }
    private static final class Queue implements Executor {
        final ArrayList<Runnable> tasks = new ArrayList<>();
        final CountDownLatch arrived = new CountDownLatch(1);
        @Override public synchronized void execute(Runnable command) { tasks.add(command); arrived.countDown(); }
        synchronized Runnable remove() { return tasks.removeFirst(); }
        synchronized int size() { return tasks.size(); }
    }
    public static void main(String[] args) throws Exception {
        CompletableFutureDelayedReferenceControl.main(args); // All original sixteen observations remain.
        AtomicInteger supplierCalls = new AtomicInteger();
        for (int outcome = 0; outcome < 3; outcome++) {
            Queue queue = new Queue();
            CompletableFuture<Integer> future = CompletableFuture.supplyAsync(() -> {
                supplierCalls.incrementAndGet(); return 99;
            }, CompletableFuture.delayedExecutor(60, TimeUnit.MILLISECONDS, queue));
            require(queue.size() == 0);
            if (outcome == 0) require(future.cancel(true) && future.isCancelled());
            else if (outcome == 1) require(future.complete(42) && future.join() == 42);
            else require(future.completeExceptionally(new IllegalArgumentException("early-terminal")));
            await(queue.arrived); // Terminal state does not suppress the later base-executor call.
            require(queue.size() == 1 && supplierCalls.get() == 0);
            queue.remove().run();
            require(future.isDone() && supplierCalls.get() == 0);
            if (outcome == 0) require(future.isCancelled());
            else if (outcome == 1) require(future.join() == 42);
            else require(future.exceptionNow() instanceof IllegalArgumentException);
        }

        AtomicReference<Thread> baseThread = new AtomicReference<>();
        CountDownLatch ran = new CountDownLatch(1);
        Thread caller = Thread.currentThread();
        CompletableFuture.delayedExecutor(0, TimeUnit.SECONDS, command -> {
            baseThread.set(Thread.currentThread()); command.run();
        }).execute(ran::countDown);
        await(ran);
        require(baseThread.get() != caller);

        CountDownLatch rawRejection = new CountDownLatch(1);
        CompletableFuture.delayedExecutor(-1, TimeUnit.SECONDS, command -> {
            rawRejection.countDown(); throw new RejectedExecutionException("raw-rejection");
        }).execute(() -> { throw new AssertionError("rejected-command-ran"); });
        await(rawRejection);

        Queue uncertain = new Queue();
        Executor acceptedThenFailed = command -> {
            uncertain.execute(command); throw new IllegalStateException("acceptance-is-not-known-from-throw");
        };
        CompletableFuture<Integer> unknown = CompletableFuture.supplyAsync(() -> 42,
            CompletableFuture.delayedExecutor(0, TimeUnit.NANOSECONDS, acceptedThenFailed));
        await(uncertain.arrived);
        require(!unknown.isDone() && uncertain.size() == 1);
        uncertain.remove().run();
        require(unknown.join() == 42);

        Queue rejectedQueue = new Queue();
        CompletableFuture<Integer> rejectedAfterAcceptance = CompletableFuture.supplyAsync(() -> 42,
            CompletableFuture.delayedExecutor(0, TimeUnit.NANOSECONDS, command -> {
                rejectedQueue.execute(command); throw new RejectedExecutionException("queued-then-rejected");
            }));
        await(rejectedQueue.arrived);
        require(!rejectedAfterAcceptance.isDone() && rejectedQueue.size() == 1);
        rejectedQueue.remove().run();
        require(rejectedAfterAcceptance.join() == 42);

        CompletableFuture<Integer> defaultBase = CompletableFuture.supplyAsync(() -> 42,
            CompletableFuture.delayedExecutor(1, TimeUnit.MILLISECONDS));
        require(defaultBase.get(3, TimeUnit.SECONDS) == 42);
        CompletableFuture<Void> run = CompletableFuture.runAsync(() -> supplierCalls.incrementAndGet(),
            CompletableFuture.delayedExecutor(1, TimeUnit.MILLISECONDS));
        require(run.get(3, TimeUnit.SECONDS) == null && supplierCalls.get() == 1);
        require(CompletableFuture.delayedExecutor(Long.MAX_VALUE, TimeUnit.DAYS, Runnable::run) != null);
        System.out.println("COMPLETABLE_DELAYED_NATIVE PASS observables=" + checks
            + ";terminal-before-delay=base-dispatched;supplier-skipped;uncertain-acceptance=retained");
    }
}
