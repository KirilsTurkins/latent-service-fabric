import java.util.ArrayList;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/** Actual JDK observations needed before porting delayed dispatch and rejection. */
public final class CompletableFutureDelayedReferenceControl {
    private static int checks;
    private static void require(boolean condition) {
        if (!condition) throw new AssertionError("delayed-reference-" + checks);
        checks++;
    }
    private static void await(CountDownLatch latch) throws Exception { require(latch.await(3, TimeUnit.SECONDS)); }
    private static void npe(Runnable body) {
        try { body.run(); throw new AssertionError("missing-delayed-null-check"); }
        catch (NullPointerException expected) { checks++; }
    }
    private static final class Queue implements Executor {
        final ArrayList<Runnable> tasks = new ArrayList<>();
        final CountDownLatch arrived = new CountDownLatch(1);
        @Override public synchronized void execute(Runnable command) { tasks.add(command); arrived.countDown(); }
        synchronized Runnable remove() { return tasks.removeFirst(); }
        synchronized int size() { return tasks.size(); }
    }
    public static void main(String[] args) throws Exception {
        Queue queue = new Queue();
        npe(() -> CompletableFuture.delayedExecutor(1, null));
        npe(() -> CompletableFuture.delayedExecutor(1, null, queue));
        npe(() -> CompletableFuture.delayedExecutor(1, TimeUnit.SECONDS, null));
        Executor deferred = CompletableFuture.delayedExecutor(60, TimeUnit.MILLISECONDS, queue);
        require(queue.size() == 0);
        AtomicInteger supplierCalls = new AtomicInteger();
        long start = System.nanoTime();
        CompletableFuture<Integer> result = CompletableFuture.supplyAsync(() -> {
            supplierCalls.incrementAndGet(); return 42;
        }, deferred);
        await(queue.arrived);
        require(System.nanoTime() - start >= TimeUnit.MILLISECONDS.toNanos(60));
        require(queue.size() == 1 && supplierCalls.get() == 0 && !result.isDone());
        queue.remove().run();
        require(result.join() == 42 && supplierCalls.get() == 1);

        Queue nullable = new Queue();
        CompletableFuture.delayedExecutor(0, TimeUnit.NANOSECONDS, nullable).execute(null);
        await(nullable.arrived);
        require(nullable.size() == 1 && nullable.remove() == null);

        AtomicInteger rejected = new AtomicInteger();
        CountDownLatch rejection = new CountDownLatch(1);
        Executor denied = command -> {
            rejected.incrementAndGet(); rejection.countDown();
            throw new RejectedExecutionException("delayed-reference-denied");
        };
        CompletableFuture<Integer> unaccepted = CompletableFuture.supplyAsync(() -> {
            supplierCalls.incrementAndGet(); return 99;
        }, CompletableFuture.delayedExecutor(1, TimeUnit.MILLISECONDS, denied));
        await(rejection);
        require(rejected.get() == 1 && !unaccepted.isDone() && supplierCalls.get() == 1);
        require(unaccepted.cancel(false) && unaccepted.isCancelled());

        for (long delay : new long[]{Long.MIN_VALUE, -1, 0}) {
            CountDownLatch invoked = new CountDownLatch(1);
            CompletableFuture.delayedExecutor(delay, TimeUnit.NANOSECONDS, Runnable::run).execute(invoked::countDown);
            await(invoked);
        }
        System.out.println("COMPLETABLE_DELAYED_REFERENCE PASS observables=" + checks
            + ";submission-rejection=future-pending;execute-null=deferred-to-base;delay-start=execute");
    }
}
