import java.util.concurrent.CancellationException;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Actual ordinary cancellation reporting, without any timer or executor creation. */
public final class CompletableFutureCancellationReferenceControl {
    private static int checks;
    private static void require(boolean condition) {
        if (!condition) throw new AssertionError("cancel-report-observable-" + checks);
        checks++;
    }
    public static void main(String[] args) throws Exception {
        for (int mode = 0; mode < 2; mode++) {
            CompletableFuture<Integer> future = new CompletableFuture<>();
            AtomicReference<Throwable> stored = new AtomicReference<>();
            AtomicInteger callbacks = new AtomicInteger();
            CompletableFuture<Void> observation = future.handle((value, error) -> {
                stored.set(error); callbacks.incrementAndGet(); return null;
            });
            IllegalArgumentException original = new IllegalArgumentException("external-cancellation-cause");
            CancellationException supplied = new CancellationException("external-cancellation");
            supplied.initCause(original);
            require(mode == 0 ? future.cancel(true) : future.completeExceptionally(supplied));
            observation.get(3, TimeUnit.SECONDS);
            require(future.isCancelled() && future.isCompletedExceptionally() && callbacks.get() == 1);
            require(future.getNumberOfDependents() == 0 && stored.get() instanceof CancellationException);
            if (mode == 1) require(stored.get() == supplied && stored.get().getCause() == original);
            CancellationException previous = null;
            for (int form = 0; form < 4; form++) {
                try {
                    switch (form) {
                        case 0 -> future.get();
                        case 1 -> future.get(3, TimeUnit.SECONDS);
                        case 2 -> future.join();
                        case 3 -> future.getNow(null);
                        default -> throw new AssertionError();
                    }
                    throw new AssertionError("cancelled-read-succeeded");
                } catch (CancellationException expected) {
                    require(expected != stored.get() && expected.getCause() == stored.get());
                    require(expected != previous);
                    require(expected.getMessage().equals(form < 2 ? "get" : form == 2 ? "join" : "getNow"));
                    previous = expected;
                }
            }
            require(!future.complete(42) && !future.completeExceptionally(new IllegalStateException("late")));
            require(future.cancel(false) && callbacks.get() == 1 && future.getNumberOfDependents() == 0);
            future.handle((value, error) -> { require(error == stored.get()); return null; }).get(3, TimeUnit.SECONDS);
            require(stored.get() instanceof CancellationException && callbacks.get() == 1);
            if (mode == 1) require(supplied.getCause() == original);
        }
        System.out.println("COMPLETABLE_CANCELLATION_REFERENCE PASS observables=" + checks
            + ";public-wrappers=fresh;stored-cause-and-method-details;late-callback-cause-preserved;timers=0;executors=0");
    }
}
