import java.util.concurrent.CancellationException;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Same terminal-state observations on actual JDK and port; no timing-dependent winner. */
public final class CompletableFutureTimedLateReferenceControl {
    private static int checks;
    private static void require(boolean condition) {
        if (!condition) throw new AssertionError("timed-late-observable-" + checks);
        checks++;
    }
    public static void main(String[] args) throws Exception {
        for (int mode = 0; mode < 4; mode++) {
            CompletableFuture<Integer> future = new CompletableFuture<>();
            AtomicInteger callbacks = new AtomicInteger();
            AtomicReference<Throwable> observed = new AtomicReference<>();
            CompletableFuture<Void> observer = future.handle((value, error) -> {
                callbacks.incrementAndGet(); observed.set(error); return null;
            });
            IllegalStateException original = new IllegalStateException("early-producer-failure");
            if (mode == 0) future.orTimeout(5, TimeUnit.MILLISECONDS);
            else if (mode == 1) future.completeOnTimeout(42, 5, TimeUnit.MILLISECONDS);
            else {
                future.completeOnTimeout(99, Long.MAX_VALUE, TimeUnit.DAYS);
                if (mode == 2) require(future.cancel(true));
                else require(future.completeExceptionally(original));
            }
            observer.get(3, TimeUnit.SECONDS);
            require(future.isDone() && callbacks.get() == 1 && future.getNumberOfDependents() == 0);
            if (mode == 1) require(future.join() == 42 && observed.get() == null && !future.isCompletedExceptionally());
            else if (mode == 2) {
                require(future.isCancelled() && observed.get() instanceof CancellationException);
                try { future.join(); throw new AssertionError("cancelled-join-succeeded"); }
                catch (CancellationException expected) { require(expected == observed.get()); }
            } else {
                require(future.isCompletedExceptionally() && !future.isCancelled());
                require(mode == 0 ? observed.get() instanceof TimeoutException : observed.get() == original);
                try { future.join(); throw new AssertionError("exceptional-join-succeeded"); }
                catch (CompletionException expected) { require(expected.getCause() == observed.get()); }
            }
            Throwable terminal = observed.get();
            require(!future.complete(77));
            require(!future.completeExceptionally(new IllegalArgumentException("late-producer-failure")));
            require(future.cancel(false) == (mode == 2));
            require(callbacks.get() == 1 && observed.get() == terminal && future.getNumberOfDependents() == 0);
            require(future.orTimeout(Long.MAX_VALUE, TimeUnit.DAYS) == future);
            require(future.completeOnTimeout(-1, 0, TimeUnit.NANOSECONDS) == future);
            require(callbacks.get() == 1 && future.getNumberOfDependents() == 0);
            if (mode == 1) require(future.join() == 42);
        }
        System.out.println("COMPLETABLE_TIMED_LATE_REFERENCE PASS observables=" + checks
            + ";settled-before-late-producer;terminal-state-and-cause-retained;single-callback");
    }
}
