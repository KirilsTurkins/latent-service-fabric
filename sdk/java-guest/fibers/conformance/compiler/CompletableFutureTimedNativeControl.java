import java.util.concurrent.CancellationException;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicInteger;

/** Identical timed-completion observables on the reference JDK and actual port source. */
public final class CompletableFutureTimedNativeControl {
    private static int checks;
    private static void require(boolean condition) {
        if (!condition) throw new AssertionError("timed-observable-" + checks);
        checks++;
    }
    private static void npe(Runnable action) {
        try { action.run(); throw new AssertionError("missing-null-unit-check"); }
        catch (NullPointerException expected) { checks++; }
    }
    private static void failure(CompletableFuture<?> future, Class<?> type) throws Exception {
        try { future.get(3, TimeUnit.SECONDS); throw new AssertionError("timed-failure-succeeded"); }
        catch (ExecutionException expected) { require(type.isInstance(expected.getCause())); }
        try { future.join(); throw new AssertionError("timed-join-succeeded"); }
        catch (CompletionException expected) { require(type.isInstance(expected.getCause())); }
        require(type.isInstance(future.exceptionNow()) && future.isCompletedExceptionally());
    }
    private static void settled(CompletableFuture<?> future) throws Exception {
        future.handle((value, error) -> null).get(3, TimeUnit.SECONDS);
    }
    public static void main(String[] args) throws Exception {
        CompletableFuture<Integer> completed = CompletableFuture.completedFuture(42);
        npe(() -> completed.orTimeout(0, null));
        npe(() -> completed.completeOnTimeout(99, 0, null));
        CompletableFuture<Integer> pending = new CompletableFuture<>();
        npe(() -> pending.orTimeout(1, null));
        npe(() -> pending.completeOnTimeout(null, 1, null));
        require(!pending.isDone() && pending.getNumberOfDependents() == 0);
        for (long delay : new long[]{Long.MIN_VALUE, -1, 0, 1, Long.MAX_VALUE}) {
            require(completed.orTimeout(delay, TimeUnit.NANOSECONDS) == completed);
            require(completed.completeOnTimeout(99, delay, TimeUnit.DAYS) == completed);
            require(completed.join() == 42 && completed.getNumberOfDependents() == 0);
        }

        for (long delay : new long[]{Long.MIN_VALUE, -1, 0, 1}) {
            CompletableFuture<Integer> timed = new CompletableFuture<>();
            require(timed.orTimeout(delay, TimeUnit.NANOSECONDS) == timed);
            failure(timed, TimeoutException.class);
            require(!timed.isCancelled() && timed.getNumberOfDependents() == 0);
            CompletableFuture<Integer> fallback = new CompletableFuture<>();
            require(fallback.completeOnTimeout(42, delay, TimeUnit.NANOSECONDS) == fallback);
            require(fallback.get(3, TimeUnit.SECONDS) == 42 && !fallback.isCompletedExceptionally());
            require(fallback.getNumberOfDependents() == 0);
        }
        CompletableFuture<Integer> nullValue = new CompletableFuture<>();
        require(nullValue.completeOnTimeout(null, 0, TimeUnit.SECONDS) == nullValue);
        require(nullValue.get(3, TimeUnit.SECONDS) == null);

        AtomicInteger callbacks = new AtomicInteger();
        CompletableFuture<Integer> normal = new CompletableFuture<>();
        require(normal.orTimeout(Long.MAX_VALUE, TimeUnit.DAYS) == normal);
        require(normal.getNumberOfDependents() == 1);
        normal.thenRun(callbacks::incrementAndGet);
        require(normal.complete(42));
        require(normal.join() == 42 && callbacks.get() == 1 && normal.getNumberOfDependents() == 0);

        IllegalArgumentException cause = new IllegalArgumentException("original-timed-failure");
        CompletableFuture<Integer> failed = new CompletableFuture<>();
        failed.orTimeout(Long.MAX_VALUE, TimeUnit.DAYS);
        require(failed.completeExceptionally(cause));
        try { failed.get(); throw new AssertionError(); }
        catch (ExecutionException expected) { require(expected.getCause() == cause); }
        require(failed.getNumberOfDependents() == 0);

        CompletableFuture<Integer> cancelled = new CompletableFuture<>();
        cancelled.completeOnTimeout(99, Long.MAX_VALUE, TimeUnit.DAYS);
        require(cancelled.cancel(false) && cancelled.isCancelled());
        try { cancelled.join(); throw new AssertionError(); }
        catch (CancellationException expected) { checks++; }
        require(cancelled.getNumberOfDependents() == 0);

        CompletableFuture<Integer> first = new CompletableFuture<>();
        first.completeOnTimeout(42, 5, TimeUnit.MILLISECONDS);
        first.completeOnTimeout(99, Long.MAX_VALUE, TimeUnit.DAYS);
        require(first.get(3, TimeUnit.SECONDS) == 42);
        settled(first);
        require(first.getNumberOfDependents() == 0);
        CompletableFuture<Integer> exceptionalFirst = new CompletableFuture<>();
        exceptionalFirst.orTimeout(5, TimeUnit.MILLISECONDS);
        exceptionalFirst.completeOnTimeout(99, Long.MAX_VALUE, TimeUnit.DAYS);
        failure(exceptionalFirst, TimeoutException.class);
        settled(exceptionalFirst);
        require(exceptionalFirst.getNumberOfDependents() == 0);

        CompletableFuture<Integer> delayed = new CompletableFuture<>();
        long before = System.nanoTime();
        delayed.completeOnTimeout(42, 60, TimeUnit.MILLISECONDS);
        require(delayed.get(3, TimeUnit.SECONDS) == 42);
        require(System.nanoTime() - before >= TimeUnit.MILLISECONDS.toNanos(60));

        for (int round = 0; round < 16; round++) {
            CompletableFuture<Integer> race = new CompletableFuture<>();
            race.completeOnTimeout(42, 1, TimeUnit.MILLISECONDS);
            Thread producer = new Thread(() -> race.complete(99));
            producer.start();
            int value = race.get(3, TimeUnit.SECONDS);
            producer.join(3_000);
            require(!producer.isAlive() && (value == 42 || value == 99));
            require(!race.complete(-1) && race.join() == value);
            settled(race);
            require(race.getNumberOfDependents() == 0);
        }
        System.out.println("completable-timed-standard-observables=" + checks);
    }
}
