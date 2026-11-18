import java.util.concurrent.CancellationException;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Standard JDK and SDK observations; no guest execution is implied. */
public final class CompletableObtrudeReferenceControl {
    private static void require(boolean value) { if (!value) throw new AssertionError("completable-obtrude-reference"); }
    private static void exceptional(CompletableFuture<?> future, Throwable error) throws Exception {
        try { future.join(); throw new AssertionError("expected-exception"); }
        catch (CompletionException observed) { require(observed.getCause() == error); }
        try { future.get(); throw new AssertionError("expected-get-exception"); }
        catch (ExecutionException observed) { require(observed.getCause() == error); }
    }
    private static void observers() throws Exception {
        var source = new CompletableFuture<Integer>();
        var calls = new AtomicInteger();
        var before = source.thenApply(value -> { calls.incrementAndGet(); return value + 1; });
        source.obtrudeValue(1);
        require(source.join() == 1 && before.join() == 2 && calls.get() == 1);
        source.obtrudeValue(2);
        require(source.join() == 2 && before.join() == 2 && source.thenApply(value -> value + 1).join() == 3
            && calls.get() == 1);
        var failure = new IllegalStateException("forced");
        source.obtrudeException(failure);
        exceptional(source, failure);
        require(source.exceptionNow() == failure);
        var afterFailure = source.thenApply(value -> { calls.incrementAndGet(); return value; });
        exceptional(afterFailure, failure);
        try { source.obtrudeException(null); throw new AssertionError("null-exception-accepted"); }
        catch (NullPointerException expected) { }
        exceptional(source, failure);
        var wrapped = new CompletionException(failure);
        source.obtrudeException(wrapped);
        try { source.join(); throw new AssertionError("expected-wrapped-exception"); }
        catch (CompletionException observed) { require(observed == wrapped); }
        try { source.get(); throw new AssertionError("expected-unwrapped-exception"); }
        catch (ExecutionException observed) { require(observed.getCause() == failure); }
        source.obtrudeValue(null);
        require(source.join() == null && calls.get() == 1 && before.join() == 2);
        var pending = new CompletableFuture<Integer>();
        var waiting = pending.thenApply(value -> { calls.incrementAndGet(); return value; });
        pending.obtrudeException(failure); exceptional(waiting, failure); require(calls.get() == 1);
    }
    private static void cancellation() throws Exception {
        var source = new CompletableFuture<Integer>();
        var cancellation = new CancellationException("forced-cancellation");
        var callbackError = new AtomicReference<Throwable>();
        var dependent = source.whenComplete((value, error) -> callbackError.set(error));
        source.obtrudeException(cancellation);
        require(source.isCancelled() && callbackError.get() == cancellation);
        try { source.join(); throw new AssertionError("expected-cancellation"); }
        catch (CancellationException observed) { require(observed != cancellation && observed.getCause() == cancellation && observed.getMessage().equals("join")); }
        try { source.get(); throw new AssertionError("expected-get-cancellation"); }
        catch (CancellationException observed) { require(observed != cancellation && observed.getCause() == cancellation && observed.getMessage().equals("get")); }
        try { source.get(0, TimeUnit.SECONDS); throw new AssertionError("expected-timed-get-cancellation"); }
        catch (CancellationException observed) { require(observed != cancellation && observed.getCause() == cancellation && observed.getMessage().equals("get")); }
        try { source.getNow(3); throw new AssertionError("expected-get-now-cancellation"); }
        catch (CancellationException observed) { require(observed != cancellation && observed.getCause() == cancellation && observed.getMessage().equals("getNow")); }
        exceptional(dependent, cancellation);
        source.obtrudeValue(7);
        require(!source.isCancelled() && source.join() == 7);
    }
    private static void overrides() throws Exception {
        class Overridden extends CompletableFuture<Integer> {
            @Override public boolean complete(Integer value) { throw new AssertionError("override-complete"); }
            @Override public boolean completeExceptionally(Throwable error) { throw new AssertionError("override-complete-exceptionally"); }
        }
        var source = new Overridden();
        source.obtrudeValue(8); require(source.join() == 8);
        var failure = new IllegalStateException("forced-override");
        source.obtrudeException(failure); exceptional(source, failure);
    }
    private static void deferred() {
        var queued = new AtomicReference<Runnable>();
        var calls = new AtomicInteger();
        var source = new CompletableFuture<Integer>();
        source.completeAsync(() -> { calls.incrementAndGet(); return 42; }, command -> {
            require(queued.compareAndSet(null, command));
        });
        source.obtrudeValue(7);
        require(source.join() == 7 && queued.get() != null);
        queued.get().run();
        require(source.join() == 7 && calls.get() == 0);
    }
    private static void waitingDestination(boolean fail) throws Exception {
        var source = new CompletableFuture<Integer>(); var calls = new AtomicInteger();
        var destination = source.thenApply(value -> { calls.incrementAndGet(); return value + 1; });
        var forced = new IllegalStateException("forced-destination");
        if (fail) destination.obtrudeException(forced); else destination.obtrudeValue(7);
        source.complete(10);
        require(calls.get() == 0);
        if (fail) exceptional(destination, forced); else require(destination.join() == 7);
    }
    private static void running(boolean fail) throws Exception {
        var entered = new CountDownLatch(1); var release = new CountDownLatch(1);
        var worker = new AtomicReference<Thread>(); var calls = new AtomicInteger();
        var source = new CompletableFuture<Integer>();
        var failure = new IllegalStateException("forced-running");
        try {
            source.completeAsync(() -> {
                calls.incrementAndGet(); entered.countDown();
                try { if (!release.await(5, TimeUnit.SECONDS)) throw new AssertionError("release-timeout"); }
                catch (InterruptedException error) { throw new AssertionError(error); }
                return 42;
            }, command -> { var thread = new Thread(command); worker.set(thread); thread.start(); });
            require(entered.await(5, TimeUnit.SECONDS));
            if (fail) { source.obtrudeException(failure); exceptional(source, failure); }
            else { source.obtrudeValue(7); require(source.join() == 7); }
        } finally {
            release.countDown();
            if (worker.get() != null) { worker.get().join(5000); require(!worker.get().isAlive()); }
        }
        require(calls.get() == 1);
        if (fail) exceptional(source, failure); else require(source.join() == 7);
    }
    public static void main(String[] args) throws Exception {
        observers(); cancellation(); overrides(); deferred(); waitingDestination(false); waitingDestination(true);
        running(false); running(true);
        System.out.println("COMPLETABLE_OBTRUDE_REFERENCE PASS observers;overwrite;exception-identity;cancellation;overrides;deferred;waiting-destination;running");
    }
}
