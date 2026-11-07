import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.CompletableFuture;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Failed construction never retries an ambiguously settled queue owner. */
public final class CompletableFutureQueuedRollbackControl {
    private static void require(boolean value) { if (!value) throw new AssertionError("completable-queued-rollback"); }
    private static final class PublishedDestination extends CompletableFuture<Integer> {
        final AtomicReference<CompletableFuture<?>> published = new AtomicReference<>();
        final AtomicReference<Throwable> raceFailure = new AtomicReference<>();
        @Override public <U> CompletableFuture<U> newIncompleteFuture() {
            CompletableFuture<U> destination = new CompletableFuture<>();
            published.set(destination);
            Activation.admissionObservationKind = "QueuedWork";
            Activation.admissionObservation = () -> {
                Thread completing = new Thread(() -> {
                    try { require(destination.complete(null)); }
                    catch (Throwable failure) { raceFailure.set(failure); }
                });
                completing.start();
                try { completing.join(5000); }
                catch (InterruptedException error) { throw new AssertionError(error); }
                require(!completing.isAlive() && raceFailure.get() == null);
            };
            require(!destination.isDone());
            return destination;
        }
    }
    private static void inject(boolean unknown) {
        if (unknown) Activation.loseCloseAckNext = "QueuedWork";
        else Activation.denyCloseNext = "QueuedWork";
    }
    private static void retained(boolean unknown) {
        require(Activation.poisoned && Activation.retainsFailedQueued());
        require(Activation.closeAttempts(LatentRuntimeActivationOwnerKind.QueuedWork) == 1);
        require(Activation.failedLeaseAttempts() == 1);
        require(Activation.admissions(LatentRuntimeActivationOwnerKind.QueuedWork) == 1);
        require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == (unknown ? 0 : 1));
        require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == 0);
        for (int i = 0; i < 8; i++) {
            try {
                new CompletableFuture<Integer>().thenApply(value -> value + 1);
                throw new AssertionError("owner-admitted-after-poison");
            } catch (IllegalStateException expected) {
                require(expected.getMessage().equals("activation-runtime-poisoned-store"));
            }
        }
        require(Activation.admissions(LatentRuntimeActivationOwnerKind.QueuedWork) == 1);
        require(Activation.closeAttempts(LatentRuntimeActivationOwnerKind.QueuedWork) == 1);
        require(Activation.failedLeaseAttempts() == 1 && Activation.retainsFailedQueued());
    }
    private static void completed(boolean unknown, boolean fail) {
        PublishedDestination source = new PublishedDestination();
        AtomicInteger calls = new AtomicInteger();
        if (fail) inject(unknown);
        try {
            CompletableFuture<Integer> dependent = source.thenApply(value -> { calls.incrementAndGet(); return value + 1; });
            require(!fail && dependent == source.published.get() && dependent.isDone() && dependent.join() == null);
        } catch (IllegalStateException error) {
            require(fail && error.getMessage().equals(unknown
                ? "source-owner-settlement-ack-unknown" : "source-owner-settlement-denied"));
        }
        require(source.raceFailure.get() == null && source.published.get().isDone());
        require(source.complete(42) && calls.get() == 0);
        if (fail) retained(unknown);
        else {
            require(!Activation.poisoned && !Activation.retainsFailedQueued());
            require(Activation.admissions(LatentRuntimeActivationOwnerKind.QueuedWork) == 1);
            require(Activation.closeAttempts(LatentRuntimeActivationOwnerKind.QueuedWork) == 1);
            require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == 0);
            Activation.idle();
        }
    }
    private static void acceptance(boolean unknown, boolean fail) {
        AtomicInteger calls = new AtomicInteger();
        Activation.denyNext = "Result";
        if (fail) inject(unknown);
        try {
            new CompletableFuture<Integer>().thenApply(value -> { calls.incrementAndGet(); return value + 1; });
            throw new AssertionError("missing-admission-failure");
        } catch (IllegalStateException expected) {
            require(expected.getMessage().equals("source-owner-admission-denied"));
        }
        require(calls.get() == 0);
        if (fail) retained(unknown);
        else {
            require(!Activation.poisoned && !Activation.retainsFailedQueued());
            require(Activation.admissions(LatentRuntimeActivationOwnerKind.QueuedWork) == 1);
            require(Activation.closeAttempts(LatentRuntimeActivationOwnerKind.QueuedWork) == 1);
            require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == 0);
            var normal = new CompletableFuture<Integer>();
            var dependent = normal.thenApply(value -> { calls.incrementAndGet(); return value + 1; });
            normal.complete(41); require(dependent.join() == 42 && calls.get() == 1);
            Activation.idle();
        }
    }
    public static void main(String[] args) {
        require(args.length == 1);
        switch (args[0]) {
            case "refused-completed" -> completed(false, true);
            case "unknown-completed" -> completed(true, true);
            case "success-completed" -> completed(false, false);
            case "refused-acceptance" -> acceptance(false, true);
            case "unknown-acceptance" -> acceptance(true, true);
            case "success-acceptance" -> acceptance(false, false);
            default -> throw new AssertionError("unsupported-mode");
        }
        System.out.println("COMPLETABLE_QUEUED_ROLLBACK PASS " + args[0]);
    }
}
