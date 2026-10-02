import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Real port bodies and real host threads with the private strict source ledger. */
public final class CompletableFutureTimedOwnerControl {
    private static int checks;
    private static void require(boolean condition) {
        if (!condition) throw new AssertionError("timed-owner-observable-" + checks);
        checks++;
    }
    private static void owners(int queued, int results, int tasks) {
        require(Activation.queuedOwners() == queued && Activation.resultOwners() == results
            && Activation.deferredOwners() == tasks);
    }
    private static void cleanup() throws Exception { Activation.cleanup(); owners(0, 0, 0); }
    private static void await(CountDownLatch latch) {
        try { require(latch.await(3, TimeUnit.SECONDS)); }
        catch (InterruptedException error) { throw new AssertionError(error); }
    }
    public static void main(String[] args) throws Exception {
        AtomicReference<Throwable> threadFailure = new AtomicReference<>();
        Thread.setDefaultUncaughtExceptionHandler((thread, error) -> threadFailure.compareAndSet(null, error));
        owners(0, 0, 0);
        for (String kind : new String[]{"QueuedWork", "Result", "Task"}) {
            CompletableFuture<Integer> pending = new CompletableFuture<>();
            Activation.denyNext = kind;
            try { pending.orTimeout(Long.MAX_VALUE, TimeUnit.DAYS); throw new AssertionError("admission-succeeded"); }
            catch (IllegalStateException expected) { checks++; }
            require(!pending.isDone() && pending.getNumberOfDependents() == 0 && Activation.denyNext == null);
            cleanup();
        }
        for (int outcome = 0; outcome < 3; outcome++) {
            CompletableFuture<Integer> pending = new CompletableFuture<>();
            require(pending.completeOnTimeout(99, Long.MAX_VALUE, TimeUnit.DAYS) == pending);
            owners(2, 1, 1);
            require(pending.getNumberOfDependents() == 1);
            if (outcome == 0) require(pending.complete(42) && pending.join() == 42);
            else if (outcome == 1) {
                IllegalArgumentException original = new IllegalArgumentException("cancelled-timeout-failure");
                require(pending.completeExceptionally(original) && pending.exceptionNow() == original);
            } else require(pending.cancel(true) && pending.isCancelled());
            require(pending.getNumberOfDependents() == 0);
            cleanup();
        }

        CountDownLatch callbackEntered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicInteger callbackCalls = new AtomicInteger();
        CompletableFuture<Integer> target = new CompletableFuture<>();
        target.completeOnTimeout(42, 40, TimeUnit.MILLISECONDS);
        CompletableFuture<Integer> callback = target.thenApply(value -> {
            callbackEntered.countDown();
            await(release);
            require(!Thread.currentThread().isInterrupted());
            callbackCalls.incrementAndGet();
            return value;
        });
        try {
            await(callbackEntered);
            require(target.join() == 42 && !callback.isDone());
            owners(2, 1, 1); // The timer body and running callback are physically held.
            require(!target.cancel(true));
            owners(2, 1, 1);
        } finally { release.countDown(); }
        require(callback.get(3, TimeUnit.SECONDS) == 42 && callbackCalls.get() == 1);
        cleanup();

        CompletableFuture<Integer> accepted = new CompletableFuture<>();
        accepted.completeOnTimeout(41, 250, TimeUnit.MILLISECONDS);
        CompletableFuture<Integer> late = accepted.thenApplyAsync(value -> value + 1);
        Activation.closeForControl();
        CompletableFuture<Integer> fresh = new CompletableFuture<>();
        try { fresh.orTimeout(0, TimeUnit.SECONDS); throw new AssertionError("closed-root-accepted-timer"); }
        catch (IllegalStateException expected) { checks++; }
        require(!fresh.isDone() && fresh.getNumberOfDependents() == 0);
        require(CompletableFuture.completedFuture(42).orTimeout(Long.MAX_VALUE, TimeUnit.DAYS).join() == 42);
        require(late.get(3, TimeUnit.SECONDS) == 42); // Already accepted timer may submit a continuation.
        cleanup();

        @SuppressWarnings("unchecked") CompletableFuture<Integer>[] occupied = new CompletableFuture[4];
        for (int index = 0; index < occupied.length; index++) {
            occupied[index] = new CompletableFuture<>();
            occupied[index].completeOnTimeout(99, Long.MAX_VALUE, TimeUnit.DAYS);
        }
        owners(8, 4, 4); // Original queued-work 8 and root + four Task 5 ceilings.
        CompletableFuture<Integer> excess = new CompletableFuture<>();
        try { excess.orTimeout(0, TimeUnit.SECONDS); throw new AssertionError("original-capacity-expanded"); }
        catch (IllegalStateException expected) { checks++; }
        require(!excess.isDone() && excess.getNumberOfDependents() == 0);
        owners(8, 4, 4);
        for (CompletableFuture<Integer> pending : occupied) require(pending.complete(42));
        cleanup();
        require(threadFailure.get() == null);
        System.out.println("completable-timed-source-owner-observables=" + checks);
    }
}
