import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.CompletableFuture;
import java.util.ArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Actual port bodies and host threads under the private original admission ceilings. */
public final class CompletableFutureDelayedOwnerControl {
    private static int checks;
    private static void require(boolean condition) {
        if (!condition) throw new AssertionError("delayed-owner-observable-" + checks);
        checks++;
    }
    private static void owners(int queued, int results, int tasks) {
        require(Activation.queuedOwners() == queued && Activation.resultOwners() == results
            && Activation.deferredOwners() == tasks && Activation.executorOwners() == 0);
    }
    private static void cleanup() throws Exception { Activation.cleanup(); owners(0, 0, 0); }
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
        AtomicReference<Throwable> failure = new AtomicReference<>();
        Thread.setDefaultUncaughtExceptionHandler((thread, error) -> failure.compareAndSet(null, error));
        AtomicInteger calls = new AtomicInteger();
        Executor unused = CompletableFuture.delayedExecutor(Long.MAX_VALUE, TimeUnit.DAYS);
        require(unused != null && dev.latent.guest.runtime.concurrent.Executors.pools() == 0);
        owners(0, 0, 0);
        for (String kind : new String[]{"QueuedWork", "Result", "Task"}) {
            Queue queue = new Queue();
            Activation.denyNext = kind;
            try {
                CompletableFuture.supplyAsync(() -> { calls.incrementAndGet(); return 42; },
                    CompletableFuture.delayedExecutor(60, TimeUnit.MILLISECONDS, queue));
                throw new AssertionError("delayed-admission-succeeded");
            } catch (IllegalStateException denied) { checks++; }
            require(Activation.denyNext == null && queue.size() == 0 && calls.get() == 0);
            cleanup();
        }

        Queue rawQueue = new Queue();
        CompletableFuture.delayedExecutor(40, TimeUnit.MILLISECONDS, rawQueue).execute(calls::incrementAndGet);
        owners(1, 0, 1);
        await(rawQueue.arrived);
        owners(1, 0, 1);
        require(calls.get() == 0);
        rawQueue.remove().run();
        require(calls.get() == 1);
        cleanup();

        for (int outcome = 0; outcome < 3; outcome++) {
            Queue queue = new Queue();
            CompletableFuture<Integer> future = CompletableFuture.supplyAsync(() -> {
                calls.incrementAndGet(); return 99;
            }, CompletableFuture.delayedExecutor(60, TimeUnit.MILLISECONDS, queue));
            owners(2, 1, 1);
            if (outcome == 0) require(future.cancel(true) && future.isCancelled());
            else if (outcome == 1) require(future.complete(42));
            else require(future.completeExceptionally(new IllegalArgumentException("early-failure")));
            owners(2, 1, 1);
            await(queue.arrived);
            owners(2, 1, 1);
            Thread helper = Activation.deferredForControl();
            helper.interrupt();
            helper.join(25);
            require(helper.isAlive()); // An interrupt cannot refund queued physical work.
            owners(2, 1, 1);
            queue.remove().run();
            require(calls.get() == 1 && future.isDone());
            cleanup();
        }

        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        CompletableFuture<Integer> running = CompletableFuture.supplyAsync(() -> {
            entered.countDown(); await(release);
            require(!Thread.currentThread().isInterrupted()); return 42;
        }, CompletableFuture.delayedExecutor(0, TimeUnit.SECONDS, Runnable::run));
        try {
            await(entered);
            owners(2, 1, 1);
            require(running.cancel(true) && running.isCancelled());
            owners(2, 1, 1);
        } finally { release.countDown(); }
        cleanup();

        for (boolean rejectedType : new boolean[]{false, true}) {
            Queue queue = new Queue();
            CompletableFuture<Integer> uncertain = CompletableFuture.supplyAsync(() -> {
                calls.incrementAndGet(); return 99;
            }, CompletableFuture.delayedExecutor(0, TimeUnit.NANOSECONDS, command -> {
                queue.execute(command);
                if (rejectedType) throw new RejectedExecutionException("queued-then-rejected");
                throw new IllegalStateException("queued-then-failed");
            }));
            await(queue.arrived);
            require(!uncertain.isDone());
            owners(2, 1, 1);
            require(uncertain.cancel(true));
            owners(2, 1, 1);
            queue.remove().run();
            require(uncertain.isCancelled() && calls.get() == 1);
            cleanup();
        }

        @SuppressWarnings("unchecked") CompletableFuture<Integer>[] occupied = new CompletableFuture[4];
        Queue bounded = new Queue();
        for (int index = 0; index < occupied.length; index++)
            occupied[index] = CompletableFuture.supplyAsync(() -> 42,
                CompletableFuture.delayedExecutor(80, TimeUnit.MILLISECONDS, bounded));
        owners(8, 4, 4); // Original QueuedWork 8 and root + four Task 5 bounds.
        try {
            CompletableFuture.supplyAsync(() -> 99, CompletableFuture.delayedExecutor(0, TimeUnit.SECONDS, bounded));
            throw new AssertionError("delayed-capacity-expanded");
        } catch (IllegalStateException denied) { checks++; }
        owners(8, 4, 4);
        long limit = System.nanoTime() + TimeUnit.SECONDS.toNanos(3);
        while (bounded.size() != 4 && System.nanoTime() < limit) Thread.sleep(1);
        require(bounded.size() == 4);
        for (CompletableFuture<Integer> future : occupied) require(future.cancel(false));
        owners(8, 4, 4);
        while (bounded.size() != 0) bounded.remove().run();
        cleanup();

        CompletableFuture<Integer> accepted = CompletableFuture.supplyAsync(() -> 41,
            CompletableFuture.delayedExecutor(60, TimeUnit.MILLISECONDS));
        CompletableFuture<Integer> continuation = accepted.thenApplyAsync(value -> value + 1);
        Activation.closeForControl();
        Executor fresh = CompletableFuture.delayedExecutor(0, TimeUnit.SECONDS);
        try { fresh.execute(() -> { throw new AssertionError("closed-root-delayed-body"); });
              throw new AssertionError("closed-root-admitted-delayed-work"); }
        catch (IllegalStateException denied) { checks++; }
        require(continuation.get(3, TimeUnit.SECONDS) == 42);
        cleanup();

        CompletableFuture<Integer> unsubmitted = CompletableFuture.supplyAsync(() -> {
            calls.incrementAndGet(); return 99;
        }, CompletableFuture.delayedExecutor(60, TimeUnit.MILLISECONDS));
        dev.latent.guest.runtime.concurrent.Executors.failNextFactory = new IllegalStateException("factory-failed-before-execute");
        limit = System.nanoTime() + TimeUnit.SECONDS.toNanos(3);
        while (Activation.owners() != 0 && System.nanoTime() < limit) Thread.sleep(1);
        require(!unsubmitted.isDone() && calls.get() == 1
            && dev.latent.guest.runtime.concurrent.Executors.failNextFactory == null);
        require(unsubmitted.cancel(false));
        cleanup();
        require(failure.get() == null);
        System.out.println("COMPLETABLE_DELAYED_OWNER PASS observables=" + checks + ";physical-retirement=natural");
    }
}
