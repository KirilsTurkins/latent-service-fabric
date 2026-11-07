import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.CompletableFuture;
import dev.latent.guest.runtime.concurrent.Executors;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Private host ledger: a lost acknowledgement is distinct from refusal. */
public final class CompletableFutureResultSettlementControl {
    private static void require(boolean value) { if (!value) throw new AssertionError("completable-result-settlement"); }
    private static void await(CountDownLatch latch) throws InterruptedException { require(latch.await(5, TimeUnit.SECONDS)); }
    private static void hold(CountDownLatch entered, CountDownLatch release) {
        entered.countDown();
        while (true) try { release.await(); return; } catch (InterruptedException ignored) { }
    }
    private static void fail(boolean unknown) {
        if (unknown) Activation.loseCloseAckNext = "Result";
        else Activation.denyCloseNext = "Result";
    }
    private static void caught(IllegalStateException error, boolean unknown) {
        require(error.getMessage().equals(unknown ? "source-owner-settlement-ack-unknown" : "source-owner-settlement-denied"));
    }
    private static void state(boolean unknown) {
        require(Activation.closeAttempts(LatentRuntimeActivationOwnerKind.Result) == 1);
        require(Activation.failedLeaseAttempts() == 1 && Activation.poisoned);
        require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == (unknown ? 0 : 1));
        require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == 0);
    }
    private static void reject(CompletableFuture<Integer> future, AtomicInteger calls) {
        try { future.completeAsync(() -> { calls.incrementAndGet(); return 99; }, Runnable::run); throw new AssertionError("uncertain-owner-reused"); }
        catch (IllegalStateException expected) { require(expected.getMessage().equals("activation-completable-result-settlement-uncertain")); }
    }
    private static void direct(boolean unknown) {
        var future = new CompletableFuture<Integer>(); AtomicInteger calls = new AtomicInteger();
        fail(unknown);
        try { future.completeAsync(() -> { calls.incrementAndGet(); return 42; }, Runnable::run); throw new AssertionError("missing-settlement-error"); }
        catch (IllegalStateException error) { caught(error, unknown); }
        require(future.join() == 42 && calls.get() == 1); state(unknown);
        reject(future, calls); require(future.join() == 42 && calls.get() == 1); state(unknown);
    }
    private static void multiple(boolean unknown) {
        var future = new CompletableFuture<Integer>(); AtomicInteger calls = new AtomicInteger();
        List<Runnable> accepted = new ArrayList<>();
        future.completeAsync(() -> { calls.incrementAndGet(); return 42; }, accepted::add);
        future.completeAsync(() -> { calls.incrementAndGet(); return 43; }, accepted::add);
        require(accepted.size() == 2 && Activation.count(LatentRuntimeActivationOwnerKind.Result) == 1);
        accepted.get(0).run();
        require(future.join() == 42 && calls.get() == 1 && Activation.closeAttempts(LatentRuntimeActivationOwnerKind.Result) == 0);
        require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == 1);
        fail(unknown);
        try { accepted.get(1).run(); throw new AssertionError("missing-settlement-error"); }
        catch (IllegalStateException error) { caught(error, unknown); }
        require(future.join() == 42 && calls.get() == 1); state(unknown);
        accepted.get(0).run(); reject(future, calls); require(calls.get() == 1); state(unknown);
    }
    private static void failAcceptedInsert(CompletableFuture<Integer> future, RuntimeException failure) throws Exception {
        var field = CompletableFuture.class.getDeclaredField("accepted"); field.setAccessible(true);
        var old = (ArrayList<?>)field.get(future);
        field.set(future, new ArrayList<Object>(old) {
            @Override public boolean add(Object value) { throw failure; }
        });
    }
    private static void rollback(boolean unknown) throws Exception {
        var future = new CompletableFuture<Integer>(); AtomicInteger calls = new AtomicInteger();
        var original = new IllegalStateException("original-acceptance-failure");
        failAcceptedInsert(future, original); fail(unknown);
        try { future.completeAsync(() -> { calls.incrementAndGet(); return 42; }, Runnable::run); throw new AssertionError("missing-acceptance-error"); }
        catch (IllegalStateException error) { require(error == original); }
        require(!future.isDone() && calls.get() == 0); state(unknown);
        reject(future, calls); require(!future.isDone() && calls.get() == 0); state(unknown);
    }
    private static void existingAction() throws Exception {
        var future = new CompletableFuture<Integer>(); AtomicInteger calls = new AtomicInteger();
        AtomicReference<Runnable> accepted = new AtomicReference<>();
        future.completeAsync(() -> { calls.incrementAndGet(); return 42; }, accepted::set);
        var original = new IllegalStateException("later-acceptance-failure");
        failAcceptedInsert(future, original);
        try { future.completeAsync(() -> { calls.incrementAndGet(); return 43; }, Runnable::run); throw new AssertionError(); }
        catch (IllegalStateException error) { require(error == original); }
        require(!future.isDone() && calls.get() == 0 && !Activation.poisoned);
        require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == 1);
        require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == 1);
        accepted.get().run(); require(future.join() == 42 && calls.get() == 1);
        require(Activation.closeAttempts(LatentRuntimeActivationOwnerKind.Result) == 1);
        require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == 0 && !Activation.poisoned);
        Activation.idle();
    }
    private static void running(boolean unknown) throws Exception {
        AtomicReference<Thread> worker = new AtomicReference<>(); AtomicReference<Throwable> observed = new AtomicReference<>();
        var pool = Executors.newSingleThreadExecutor(target -> {
            Thread thread = new Thread(target); worker.set(thread);
            thread.setUncaughtExceptionHandler((ignored, error) -> observed.set(error)); return thread;
        });
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicInteger calls = new AtomicInteger(); var future = new CompletableFuture<Integer>();
        try {
            future.completeAsync(() -> { calls.incrementAndGet(); hold(entered, release); return 42; }, pool);
            await(entered); require(future.cancel(false) && future.isCancelled());
            require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == 1);
            require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == 1);
            fail(unknown); release.countDown(); worker.get().join(5000); require(!worker.get().isAlive());
            require(observed.get() instanceof IllegalStateException); caught((IllegalStateException)observed.get(), unknown);
            require(future.isCancelled() && calls.get() == 1); state(unknown);
            reject(future, calls); require(future.isCancelled() && calls.get() == 1); state(unknown);
        } finally { release.countDown(); pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
    }
    private static void completedSuccess() {
        var future = new CompletableFuture<Integer>(); AtomicInteger calls = new AtomicInteger();
        future.completeAsync(() -> { calls.incrementAndGet(); return 42; }, Runnable::run);
        future.completeAsync(() -> { calls.incrementAndGet(); return 43; }, Runnable::run);
        require(future.join() == 42 && calls.get() == 1 && !Activation.poisoned);
        require(Activation.closeAttempts(LatentRuntimeActivationOwnerKind.Result) == 2);
        require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == 0);
        require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == 0); Activation.idle();
    }
    private static void pendingReplay() throws Exception {
        var pool = Executors.newSingleThreadExecutor();
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicInteger calls = new AtomicInteger(); var future = new CompletableFuture<Integer>();
        try {
            pool.execute(() -> hold(entered, release)); await(entered);
            future.completeAsync(() -> { calls.incrementAndGet(); return 42; }, pool);
            var returned = pool.shutdownNow(); require(returned.size() == 1 && !future.isDone());
            release.countDown(); require(pool.awaitTermination(5, TimeUnit.SECONDS));
            require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == 0);
            returned.get(0).run(); returned.get(0).run();
            require(future.join() == 42 && calls.get() == 1 && !Activation.poisoned);
            require(Activation.closeAttempts(LatentRuntimeActivationOwnerKind.Result) == 2);
            require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == 0);
        } finally { release.countDown(); pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
        Activation.idle();
    }
    private static void reentrantSettlement() {
        var future = new CompletableFuture<Integer>(); AtomicInteger calls = new AtomicInteger();
        AtomicReference<Throwable> blocked = new AtomicReference<>();
        Activation.closeObservationKind = "Result";
        Activation.closeObservation = () -> {
            try { future.completeAsync(() -> { calls.incrementAndGet(); return 99; }, Runnable::run); }
            catch (Throwable error) { blocked.set(error); }
        };
        future.completeAsync(() -> { calls.incrementAndGet(); return 42; }, Runnable::run);
        require(blocked.get() instanceof IllegalStateException
            && blocked.get().getMessage().equals("activation-completable-result-settlement-uncertain"));
        require(future.join() == 42 && calls.get() == 1 && !Activation.poisoned);
        future.completeAsync(() -> { calls.incrementAndGet(); return 43; }, Runnable::run);
        require(future.join() == 42 && calls.get() == 1 && !Activation.poisoned);
        require(Activation.closeAttempts(LatentRuntimeActivationOwnerKind.Result) == 2);
        require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == 0); Activation.idle();
    }
    public static void main(String[] args) throws Exception {
        require(args.length == 1);
        switch (args[0]) {
            case "refused-direct" -> direct(false);
            case "unknown-direct" -> direct(true);
            case "refused-multiple" -> multiple(false);
            case "unknown-multiple" -> multiple(true);
            case "refused-rollback" -> rollback(false);
            case "unknown-rollback" -> rollback(true);
            case "refused-running" -> running(false);
            case "unknown-running" -> running(true);
            case "completed-success" -> completedSuccess();
            case "pending-replay" -> pendingReplay();
            case "existing-action" -> existingAction();
            case "reentrant-settlement" -> reentrantSettlement();
            default -> throw new AssertionError("unsupported-mode");
        }
        System.out.println("COMPLETABLE_RESULT_SETTLEMENT PASS " + args[0]);
    }
}
