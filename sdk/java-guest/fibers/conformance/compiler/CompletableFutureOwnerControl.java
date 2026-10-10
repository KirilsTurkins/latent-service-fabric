import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.CompletableFuture;
import dev.latent.guest.runtime.concurrent.CompletionException;
import java.util.ArrayDeque;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Execute actual port source with the private strict ledger, never guest bindings. */
public final class CompletableFutureOwnerControl {
    private static int checks;
    private static void require(boolean value) {
        if (!value) throw new AssertionError("owner-observable-" + checks);
        checks++;
    }
    private static void owners(int queued, int results) {
        require(Activation.queuedOwners() == queued && Activation.resultOwners() == results);
    }
    private static void await(CountDownLatch latch) throws Exception {
        require(latch.await(5, TimeUnit.SECONDS));
    }
    private static void join(Thread thread) throws Exception {
        thread.join(5_000);
        require(!thread.isAlive());
    }
    private static final class Queue implements Executor {
        private final ArrayDeque<Runnable> tasks = new ArrayDeque<>();
        @Override public synchronized void execute(Runnable task) { tasks.add(task); }
        synchronized int size() { return tasks.size(); }
        void run() {
            Runnable task;
            synchronized (this) { task = tasks.remove(); }
            task.run();
        }
    }
    public static void main(String[] args) throws Exception {
        AtomicReference<Throwable> threadFailure = new AtomicReference<>();
        Thread.setDefaultUncaughtExceptionHandler((thread, error) -> threadFailure.compareAndSet(null, error));
        owners(0, 0);
        Queue queue = new Queue();
        AtomicInteger calls = new AtomicInteger();
        require(dev.latent.guest.runtime.concurrent.Executors.pools() == 0);
        CompletableFuture<Integer> failedInput = CompletableFuture.failedFuture(new IllegalStateException("original-input"));
        Executor defaultExecutor = failedInput.defaultExecutor();
        require(defaultExecutor == failedInput.defaultExecutor());
        require(dev.latent.guest.runtime.concurrent.Executors.pools() == 0);
        CompletableFuture<Integer> failedDefault = failedInput.thenApplyAsync(value -> {
            throw new AssertionError("failed-default-callback");
        });
        require(failedDefault.isCompletedExceptionally()); owners(0, 0);
        require(dev.latent.guest.runtime.concurrent.Executors.pools() == 0);
        CompletableFuture<Integer> defaultResult = CompletableFuture.supplyAsync(() -> 42);
        require(defaultResult.get() == 42);
        require(dev.latent.guest.runtime.concurrent.Executors.pools() == 1);
        Activation.cleanup(); owners(0, 0);
        require(dev.latent.guest.runtime.concurrent.Executors.pools() == 0);
        CompletableFuture<Integer> failureInput = new CompletableFuture<>();
        CompletableFuture<Integer> failureRelay = failureInput.thenApplyAsync(value -> {
            throw new AssertionError("failed-pending-callback");
        }, queue);
        owners(1, 1);
        failureInput.completeExceptionally(new IllegalArgumentException("pending-input-failure"));
        require(failureRelay.isCompletedExceptionally() && queue.size() == 0);
        owners(0, 0); require(failureInput.getNumberOfDependents() == 0);
        CompletableFuture<Integer> readyFailure = failedInput.thenCombineAsync(
            CompletableFuture.completedFuture(42), Integer::sum, queue);
        owners(1, 1); require(queue.size() == 1 && !readyFailure.isDone());
        queue.run(); owners(0, 0); require(readyFailure.isCompletedExceptionally());
        CompletableFuture<Integer> queued = CompletableFuture.supplyAsync(() -> {
            calls.incrementAndGet(); return 42;
        }, queue);
        owners(1, 1);
        require(queued.cancel(true) && queued.isCancelled());
        owners(1, 1); // Logical cancellation cannot refund physically queued work.
        require(queue.size() == 1);
        queue.run(); owners(0, 0); require(calls.get() == 0);

        CompletableFuture<Integer> pending = new CompletableFuture<>();
        CompletableFuture<Integer> waiting = pending.thenApply(value -> {
            calls.incrementAndGet(); return value + 1;
        });
        owners(1, 1); require(pending.getNumberOfDependents() == 1);
        require(waiting.cancel(false)); owners(0, 0);
        require(pending.getNumberOfDependents() == 0);
        pending.complete(41); require(calls.get() == 0);

        CompletableFuture<Integer> first = new CompletableFuture<>();
        CompletableFuture<Integer> second = new CompletableFuture<>();
        CompletableFuture<?>[] array = {first, second};
        CompletableFuture<Object> any = CompletableFuture.anyOf(array);
        array[0] = CompletableFuture.completedFuture(-1);
        owners(1, 1); second.complete(42);
        require(any.join().equals(42)); owners(0, 0);
        require(first.getNumberOfDependents() == 0 && second.getNumberOfDependents() == 0);
        require(CompletableFuture.anyOf(first, CompletableFuture.completedFuture(42)).join().equals(42));
        owners(0, 0); require(first.getNumberOfDependents() == 0);
        second = new CompletableFuture<>();
        CompletableFuture<Void> all = CompletableFuture.allOf(first, second, first);
        owners(1, 1); require(all.cancel(true)); owners(0, 0);
        require(first.getNumberOfDependents() == 0 && second.getNumberOfDependents() == 0);
        first.complete(1); second.complete(2); owners(0, 0);

        CompletableFuture<Integer> inner = new CompletableFuture<>();
        CompletableFuture<Integer> composed = CompletableFuture.completedFuture(1).thenCompose(value -> inner);
        owners(1, 1); require(!composed.isDone());
        inner.complete(42); require(composed.join() == 42); owners(0, 0);
        CompletableFuture<Integer> done = CompletableFuture.completedFuture(42);
        done.completeAsync(() -> { throw new AssertionError("already-completed-supplier"); }, queue);
        owners(1, 1); queue.run(); owners(0, 0);

        for (String kind : new String[]{"QueuedWork", "Result"}) {
            Activation.denyNext = kind;
            try { CompletableFuture.supplyAsync(() -> 42, queue); throw new AssertionError("admission-accepted"); }
            catch (IllegalStateException denied) { require(denied.getMessage().equals("source-control-admission-denied")); }
            owners(0, 0); require(queue.size() == 0);
        }
        Executor reject = dev.latent.guest.runtime.concurrent.Executors.rejected();
        try { CompletableFuture.supplyAsync(() -> 42, reject); throw new AssertionError("rejection-accepted"); }
        catch (RejectedExecutionException expected) { checks++; }
        owners(0, 0);
        CompletableFuture<Integer> rejected = done.thenApplyAsync(value -> value + 1, reject);
        try { rejected.join(); throw new AssertionError("rejection-not-published"); }
        catch (CompletionException expected) { require(expected.getCause() instanceof RejectedExecutionException); }
        owners(0, 0);

        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        Thread[] worker = {null};
        boolean[] interrupted = {false};
        Executor physical = task -> { worker[0] = new Thread(task); worker[0].start(); };
        CompletableFuture<Integer> running = CompletableFuture.supplyAsync(() -> {
            entered.countDown();
            try { release.await(); return 42; }
            catch (InterruptedException error) { interrupted[0] = true; return -1; }
        }, physical);
        try {
            await(entered); owners(1, 1);
            require(running.cancel(true)); owners(1, 1);
        } finally { release.countDown(); }
        join(worker[0]); require(!interrupted[0] && running.isCancelled()); owners(0, 0);

        // Concurrent terminal outcomes and listener removal must close each lease once.
        for (int iteration = 0; iteration < 32; iteration++) {
            CompletableFuture<Integer> source = new CompletableFuture<>();
            AtomicInteger callbacks = new AtomicInteger();
            CompletableFuture<Integer> child = source.thenApply(value -> {
                callbacks.incrementAndGet(); return value;
            });
            CountDownLatch start = new CountDownLatch(1);
            Thread complete = new Thread(() -> {
                try { start.await(); source.complete(42); }
                catch (InterruptedException error) { throw new AssertionError(error); }
            });
            Thread cancel = new Thread(() -> {
                try { start.await(); source.cancel(true); }
                catch (InterruptedException error) { throw new AssertionError(error); }
            });
            complete.start(); cancel.start(); start.countDown(); join(complete); join(cancel);
            require(child.isDone() && callbacks.get() <= 1);
            if (source.isCancelled()) require(callbacks.get() == 0 && child.isCompletedExceptionally());
            else require(child.join() == 42 && callbacks.get() == 1);
            owners(0, 0); require(source.getNumberOfDependents() == 0);

            CompletableFuture<Integer> racedInput = new CompletableFuture<>();
            CompletableFuture<Integer> racedOutput = racedInput.thenApplyAsync(value -> {
                callbacks.incrementAndGet(); return value;
            }, queue);
            Thread publish = new Thread(() -> racedInput.complete(42));
            Thread remove = new Thread(() -> racedOutput.cancel(false));
            publish.start(); remove.start(); join(publish); join(remove);
            while (queue.size() != 0) queue.run();
            require(racedOutput.isDone()); owners(0, 0);
            require(racedInput.getNumberOfDependents() == 0);
        }
        if (threadFailure.get() != null) throw new AssertionError("physical-worker-failure", threadFailure.get());
        require(Activation.owners() == 0);
        System.out.println("COMPLETABLE_FUTURE_OWNER_CONTROL PASS observables=" + checks + ";raceRounds=32");
    }
}
