import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.CompletableFuture;
import dev.latent.guest.runtime.concurrent.CompletionException;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.atomic.AtomicInteger;

/** SDK source and a private ledger; no component or host qualification. */
public final class CompletableDefaultAsyncOwnerControl {
    private static void require(boolean value) { if (!value) throw new AssertionError("default-async-owner"); }
    private static void held(int queue, int result) {
        require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == queue
            && Activation.count(LatentRuntimeActivationOwnerKind.Result) == result
            && Activation.count(LatentRuntimeActivationOwnerKind.Executor) == 0);
    }
    private static void control(String mode) {
        var source = new CompletableDefaultAsyncReferenceControl.Overridden();
        var other = new CompletableFuture<Integer>(); var calls = new AtomicInteger();
        boolean rejected = mode.endsWith("-throw");
        var failure = new RejectedExecutionException("accepted-then-thrown");
        if (rejected) source.held.afterCapture = failure;
        boolean ready = mode.equals("early") || rejected;
        if (ready) { source.complete(5); other.complete(7); }
        CompletableFuture<Void> child = switch (mode) {
            case "accept" -> source.thenAcceptAsync(value -> calls.incrementAndGet());
            case "run", "early", "run-throw" -> source.thenRunAsync(calls::incrementAndGet);
            case "accept-both", "both-throw" -> source.thenAcceptBothAsync(other, (left, right) -> calls.incrementAndGet());
            case "run-both" -> source.runAfterBothAsync(other, calls::incrementAndGet);
            case "accept-either" -> source.acceptEitherAsync(other, value -> calls.incrementAndGet());
            default -> throw new IllegalArgumentException(mode);
        };
        require(source.defaults == 1 && source.factories == 1 && source.overloads == 0); held(1, 1);
        if (!ready) { source.complete(5); other.complete(7); }
        require(source.held.submissions == 1 && calls.get() == 0); held(1, 1);
        if (mode.equals("early")) require(child.complete(null));
        if (rejected) {
            try { child.join(); throw new AssertionError("rejection-not-recorded"); }
            catch (CompletionException error) { require(error.getCause() == failure); }
        } else if (!mode.equals("early")) require(!child.isDone());
        held(1, 1);
        source.held.run();
        require(child.isDone() && calls.get() == (ready ? 0 : 1));
        held(0, 0); Activation.idle();
    }
    private static void nullDefault(boolean invalid, boolean throwing) {
        var source = new CompletableDefaultAsyncReferenceControl.Overridden();
        source.nullDefault = true;
        if (throwing) source.defaultFailure = new IllegalStateException("default-failure");
        var calls = new AtomicInteger(); source.complete(5);
        if (invalid) {
            try { source.thenRunAsync(null); throw new AssertionError("invalid-accepted"); }
            catch (RuntimeException error) {
                require(throwing ? error == source.defaultFailure : error instanceof NullPointerException);
            }
            require(source.factories == 0 && calls.get() == 0);
        } else {
            var child = source.thenRunAsync(calls::incrementAndGet);
            require(child.isDone() && child.join() == null && calls.get() == 1 && source.factories == 1);
        }
        require(source.defaults == 1 && source.overloads == 0 && source.held.submissions == 0);
        held(0, 0); Activation.idle();
    }
    public static void main(String[] args) {
        switch (args[0]) {
            case "null-default" -> nullDefault(false, false);
            case "invalid-null" -> nullDefault(true, false);
            case "invalid-default-throw" -> nullDefault(true, true);
            default -> control(args[0]);
        }
        System.out.println("COMPLETABLE_DEFAULT_ASYNC_OWNER PASS " + args[0]);
    }
}
