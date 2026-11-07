import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.Executors;
import dev.latent.guest.runtime.concurrent.FutureTask;
import dev.latent.guest.runtime.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** A private host ledger observes refusal and acknowledgement loss separately. */
public final class ScheduledFutureResultSettlementControl {
    private static void require(boolean value) { if (!value) throw new AssertionError("future-result-settlement"); }
    private static void await(CountDownLatch latch) throws InterruptedException { require(latch.await(5, TimeUnit.SECONDS)); }
    private static void hold(CountDownLatch entered, CountDownLatch release) {
        entered.countDown();
        while (true) try { release.await(); return; } catch (InterruptedException ignored) { }
    }
    private static void failure(boolean unknown) {
        if (unknown) Activation.loseCloseAckNext = "Result";
        else Activation.denyCloseNext = "Result";
    }
    private static void caught(IllegalStateException error, boolean unknown) {
        require(error.getMessage().equals(unknown ? "source-owner-settlement-ack-unknown" : "source-owner-settlement-denied"));
    }
    private static void resultState(boolean unknown) {
        require(Activation.closeAttempts(LatentRuntimeActivationOwnerKind.Result) == 1);
        require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == (unknown ? 0 : 1));
        require(Activation.poisoned);
    }
    private static void finalClaim(boolean unknown) throws Exception {
        AtomicInteger calls = new AtomicInteger();
        var pool = new ScheduledThreadPoolExecutor(1, target -> { Thread thread = new Thread(target); thread.setDaemon(true); return thread; });
        var future = pool.scheduleAtFixedRate(calls::incrementAndGet, 1, 1, TimeUnit.DAYS);
        failure(unknown);
        try { pool.shutdownNow(); throw new AssertionError("missing-settlement-error"); }
        catch (IllegalStateException error) { caught(error, unknown); }
        require(Activation.closeAttempts(LatentRuntimeActivationOwnerKind.Result) == 1);
        require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == (unknown ? 0 : 1));
        // The stopped wrapper enters and leaves a final physical claim after
        // cancellation. It must not retry the uncertain Result settlement.
        ((Runnable)future).run();
        require(future.isCancelled() && calls.get() == 0 && pool.hasPendingWork());
        resultState(unknown);
    }
    private static void readmission(boolean unknown, boolean success) throws Exception {
        var pool = Executors.newSingleThreadExecutor();
        var next = Executors.newSingleThreadExecutor();
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicInteger calls = new AtomicInteger();
        FutureTask<Integer> future = new FutureTask<>(() -> { calls.incrementAndGet(); return 42; });
        try {
            pool.execute(() -> hold(entered, release)); await(entered); pool.execute(future);
            if (!success) failure(unknown);
            try {
                var returned = pool.shutdownNow();
                require(success && returned.size() == 1 && returned.get(0) == future);
            } catch (IllegalStateException error) {
                require(!success); caught(error, unknown);
            }
            if (success) {
                require(!Activation.poisoned && !future.isDone());
                future.run(); require(future.get() == 42 && calls.get() == 1);
                require(Activation.closeAttempts(LatentRuntimeActivationOwnerKind.Result) == 2);
                require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == 0 && !Activation.poisoned);
            } else {
                resultState(unknown);
                try { future.run(); throw new AssertionError("uncertain-result-ran"); }
                catch (IllegalStateException expected) { require(expected.getMessage().equals("activation-future-result-settlement-uncertain")); }
                try { next.execute(future); throw new AssertionError("uncertain-result-queued"); }
                catch (IllegalStateException expected) { require(expected.getMessage().equals("activation-future-result-settlement-uncertain")); }
                require(!future.isDone() && calls.get() == 0);
                resultState(unknown);
            }
        } finally {
            release.countDown(); pool.shutdownNow(); next.shutdownNow();
            require(pool.awaitTermination(5, TimeUnit.SECONDS) && next.awaitTermination(5, TimeUnit.SECONDS));
        }
    }
    private static final class Controllable extends FutureTask<Integer> {
        Controllable() { super(() -> 41); }
        void complete() { set(42); }
    }
    private static void notifyOnFailure(boolean unknown) throws Exception {
        var pool = Executors.newSingleThreadExecutor();
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1), waiting = new CountDownLatch(1);
        AtomicReference<Object> observed = new AtomicReference<>();
        Controllable future = new Controllable();
        Thread waiter = new Thread(() -> {
            waiting.countDown();
            try { observed.set(future.get()); } catch (Throwable error) { observed.set(error); }
        });
        try {
            pool.execute(() -> hold(entered, release)); await(entered); pool.execute(future);
            waiter.start(); await(waiting);
            long start = System.nanoTime();
            while (waiter.getState() != Thread.State.WAITING) {
                require(waiter.isAlive() && System.nanoTime() - start < TimeUnit.SECONDS.toNanos(5));
                Thread.yield();
            }
            failure(unknown);
            try { future.complete(); throw new AssertionError("missing-settlement-error"); }
            catch (IllegalStateException error) { caught(error, unknown); }
            waiter.join(5000); require(!waiter.isAlive() && Integer.valueOf(42).equals(observed.get()));
            resultState(unknown);
            require(pool.shutdownNow().size() == 1);
            resultState(unknown);
        } finally {
            release.countDown(); waiter.interrupt(); waiter.join(5000); pool.shutdownNow();
            require(pool.awaitTermination(5, TimeUnit.SECONDS));
        }
    }
    private static void nestedWithdrawal(boolean unknown) throws Exception {
        AtomicInteger calls = new AtomicInteger();
        var pool = new ScheduledThreadPoolExecutor(1, target -> { Thread thread = new Thread(target); thread.setDaemon(true); return thread; });
        var inner = new FutureTask<>(() -> { calls.incrementAndGet(); return 42; });
        var wrapper = pool.schedule(inner, 1, TimeUnit.DAYS);
        failure(unknown);
        if (unknown) Activation.loseCloseAckAfter = 1; else Activation.denyCloseAfter = 1;
        try { pool.shutdownNow(); throw new AssertionError("missing-nested-settlement-error"); }
        catch (IllegalStateException error) { caught(error, unknown); }
        // The first Result close belongs to the wrapper; the second is the
        // nested owner, which must not be retried or removed twice.
        require(Activation.closeAttempts(LatentRuntimeActivationOwnerKind.Result) == 2 && Activation.poisoned);
        require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == (unknown ? 0 : 1));
        ((Runnable)wrapper).run(); require(wrapper.isCancelled() && !inner.isDone() && calls.get() == 0);
        try { inner.run(); throw new AssertionError("uncertain-nested-result-ran"); }
        catch (IllegalStateException expected) { require(expected.getMessage().equals("activation-future-result-settlement-uncertain")); }
        require(Activation.closeAttempts(LatentRuntimeActivationOwnerKind.Result) == 2 && Activation.poisoned);
        require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == (unknown ? 0 : 1));
        require(pool.hasPendingWork() && !pool.isTerminated());
    }
    public static void main(String[] args) throws Exception {
        require(args.length == 1);
        switch (args[0]) {
            case "refused-claim" -> finalClaim(false);
            case "unknown-claim" -> finalClaim(true);
            case "refused-readmit" -> readmission(false, false);
            case "unknown-readmit" -> readmission(true, false);
            case "success-readmit" -> readmission(false, true);
            case "refused-notify" -> notifyOnFailure(false);
            case "unknown-notify" -> notifyOnFailure(true);
            case "refused-nested" -> nestedWithdrawal(false);
            case "unknown-nested" -> nestedWithdrawal(true);
            default -> throw new AssertionError("unsupported-mode");
        }
        System.out.println("SCHEDULED_FUTURE_RESULT_SETTLEMENT PASS " + args[0]);
    }
}
