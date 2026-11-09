import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.CompletableFuture;
import dev.latent.guest.runtime.concurrent.Executors;
import java.lang.reflect.Field;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/** Private faulting ledger around the unchanged SDK source; not guest evidence. */
public final class CompletableFutureQueuedSettlementControl {
    private static void require(boolean value) {
        if (!value) throw new AssertionError("completable-queued-settlement");
    }
    private static void inject(String fault) {
        if (fault.equals("denied")) Activation.denyCloseNext = "QueuedWork";
        else if (fault.equals("lost")) Activation.loseCloseAckNext = "QueuedWork";
        else require(fault.equals("success"));
    }
    private static String settlementError(String fault) {
        return fault.equals("lost") ? "source-owner-settlement-ack-unknown" : "source-owner-settlement-denied";
    }
    private static int accepted(CompletableFuture<?> future) throws Exception {
        Field field = CompletableFuture.class.getDeclaredField("accepted");
        field.setAccessible(true);
        return ((List<?>)field.get(future)).size();
    }
    private static void checkUncertain(String fault, int previousCloses, int resultCount) {
        require(Activation.poisoned && Activation.retainsFailedQueued());
        require(Activation.failedLeaseAttempts() == 1);
        require(Activation.closeAttempts(LatentRuntimeActivationOwnerKind.QueuedWork) == previousCloses + 1);
        require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == (fault.equals("denied") ? 1 : 0));
        require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == resultCount);
        try {
            new CompletableFuture<Integer>().thenApply(value -> value + 1);
            throw new AssertionError("admission-after-uncertain-settlement");
        } catch (IllegalStateException error) {
            require(error.getMessage().equals("activation-runtime-poisoned-store"));
        }
        require(Activation.failedLeaseAttempts() == 1);
        require(Activation.closeAttempts(LatentRuntimeActivationOwnerKind.QueuedWork) == previousCloses + 1);
    }
    private static void direct(String fault) throws Exception {
        var future = new CompletableFuture<Integer>();
        AtomicInteger calls = new AtomicInteger();
        final Runnable[] saved = new Runnable[1];
        future.completeAsync(() -> { calls.incrementAndGet(); return 42; }, command -> saved[0] = command);
        require(saved[0] != null && accepted(future) == 1);
        int previous = Activation.closeAttempts(LatentRuntimeActivationOwnerKind.QueuedWork);
        AtomicInteger reentered = new AtomicInteger();
        // This is a deliberately reentrant private host port, not a claim that
        // production's host import actually invokes a Java callback.
        Activation.closeObservationKind = "QueuedWork";
        Activation.closeObservation = () -> { reentered.incrementAndGet(); saved[0].run(); };
        inject(fault);
        try { saved[0].run(); require(fault.equals("success")); }
        catch (IllegalStateException error) {
            require(!fault.equals("success") && error.getMessage().equals(settlementError(fault)));
        }
        require(future.join() == 42 && calls.get() == 1 && reentered.get() == 1);
        if (fault.equals("success")) {
            require(accepted(future) == 0 && !Activation.poisoned);
            Activation.idle();
        } else {
            checkUncertain(fault, previous, 1);
            require(accepted(future) == 1);
            saved[0].run();
            require(calls.get() == 1 && Activation.failedLeaseAttempts() == 1);
        }
    }
    private static void waiting(String fault) throws Exception {
        var source = new CompletableFuture<Integer>();
        AtomicInteger calls = new AtomicInteger();
        var future = source.thenApply(value -> { calls.incrementAndGet(); return value + 1; });
        require(accepted(future) == 1);
        int previous = Activation.closeAttempts(LatentRuntimeActivationOwnerKind.QueuedWork);
        inject(fault);
        try { require(future.cancel(false)); require(fault.equals("success")); }
        catch (IllegalStateException error) {
            require(!fault.equals("success") && error.getMessage().equals(settlementError(fault)));
        }
        require(future.isCancelled() && source.complete(41) && calls.get() == 0);
        if (fault.equals("success")) {
            require(accepted(future) == 0 && !Activation.poisoned);
            Activation.idle();
        } else {
            checkUncertain(fault, previous, 1);
            require(accepted(future) == 1);
        }
    }
    private static void multiple(String fault) throws Exception {
        var future = new CompletableFuture<Integer>();
        AtomicInteger calls = new AtomicInteger();
        var saved = new java.util.ArrayList<Runnable>();
        future.completeAsync(() -> { calls.incrementAndGet(); return 42; }, saved::add);
        future.completeAsync(() -> { calls.incrementAndGet(); return 43; }, saved::add);
        require(saved.size() == 2 && accepted(future) == 2);
        int previous = Activation.closeAttempts(LatentRuntimeActivationOwnerKind.QueuedWork);
        inject(fault);
        try { saved.get(0).run(); require(fault.equals("success")); }
        catch (IllegalStateException error) {
            require(!fault.equals("success") && error.getMessage().equals(settlementError(fault)));
        }
        require(future.join() == 42 && calls.get() == 1);
        saved.get(1).run();
        require(calls.get() == 1);
        if (fault.equals("success")) {
            require(accepted(future) == 0 && !Activation.poisoned);
            Activation.idle();
        } else {
            // One additional close belongs to the separate already-admitted
            // action. The uncertain original is never attempted a second time.
            checkUncertain(fault, previous + 1, 1);
            require(accepted(future) == 1);
            saved.get(0).run();
            require(calls.get() == 1 && Activation.failedLeaseAttempts() == 1);
        }
    }
    private static final class Withdrawn {
        final CompletableFuture<Integer> future = new CompletableFuture<>();
        final AtomicInteger calls = new AtomicInteger();
        final Runnable action;
        Withdrawn() throws Exception {
            var pool = Executors.newSingleThreadExecutor();
            CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
            try {
                pool.execute(() -> {
                    entered.countDown();
                    while (true) try { release.await(); return; } catch (InterruptedException ignored) { }
                });
                require(entered.await(5, TimeUnit.SECONDS));
                future.completeAsync(() -> { calls.incrementAndGet(); return 42; }, pool);
                List<Runnable> returned = pool.shutdownNow();
                require(returned.size() == 1);
                action = returned.get(0);
            } finally {
                release.countDown();
                pool.shutdownNow();
                require(pool.awaitTermination(5, TimeUnit.SECONDS));
            }
            require(!future.isDone() && accepted(future) == 0);
            Activation.idle();
        }
    }
    private static void readmit(String fault, boolean completed) throws Exception {
        var setup = new Withdrawn();
        int previous = Activation.closeAttempts(LatentRuntimeActivationOwnerKind.QueuedWork);
        if (completed) {
            Activation.admissionObservationKind = "QueuedWork";
            Activation.admissionObservation = () -> require(setup.future.complete(41));
        } else Activation.denyNext = "Result";
        inject(fault);
        try {
            setup.action.run();
            require(completed && fault.equals("success"));
        } catch (IllegalStateException error) {
            String expected = completed ? settlementError(fault) : "source-owner-admission-denied";
            require(error.getMessage().equals(expected));
        }
        require(setup.calls.get() == 0);
        if (completed) require(setup.future.join() == 41);
        else require(!setup.future.isDone());
        if (fault.equals("success")) {
            require(!Activation.poisoned);
            if (!completed) {
                setup.action.run();
                require(setup.future.join() == 42 && setup.calls.get() == 1);
            }
            Activation.idle();
        } else {
            checkUncertain(fault, previous, 0);
            if (completed) setup.action.run();
            else try { setup.action.run(); throw new AssertionError("replay-after-fence"); }
                catch (IllegalStateException error) { require(error.getMessage().equals("activation-runtime-poisoned-store")); }
            require(setup.calls.get() == 0 && Activation.failedLeaseAttempts() == 1);
        }
    }
    public static void main(String[] args) throws Exception {
        require(args.length == 2);
        switch (args[0]) {
            case "direct" -> direct(args[1]);
            case "waiting" -> waiting(args[1]);
            case "multiple" -> multiple(args[1]);
            case "readmit-denied" -> readmit(args[1], false);
            case "readmit-completed" -> readmit(args[1], true);
            default -> throw new AssertionError("unsupported-mode");
        }
        System.out.println("COMPLETABLE_QUEUED_SETTLEMENT PASS " + args[0] + " " + args[1]);
    }
}
