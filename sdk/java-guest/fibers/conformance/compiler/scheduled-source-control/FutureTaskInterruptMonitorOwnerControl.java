import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.FutureTask;
import java.util.concurrent.CancellationException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Original Result custody using actual SDK source and a private host double. */
public final class FutureTaskInterruptMonitorOwnerControl {
    private static void require(boolean value, String message) { if (!value) throw new AssertionError(message); }
    private static void await(CountDownLatch latch, String message) throws InterruptedException {
        require(latch.await(5, TimeUnit.SECONDS), message);
    }
    private static void held(int count) {
        require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == count, "result-owner-count");
    }
    private static void handoff(boolean reset) throws Exception {
        CountDownLatch entered = new CountDownLatch(1), finishBody = new CountDownLatch(1);
        CountDownLatch returning = new CountDownLatch(1), interruptEntered = new CountDownLatch(1);
        CountDownLatch releaseInterrupt = new CountDownLatch(1), handedOff = new CountDownLatch(1);
        AtomicReference<Throwable> failure = new AtomicReference<>();
        AtomicInteger done = new AtomicInteger();
        class Repeat extends FutureTask<Integer> {
            Repeat() { super(() -> { entered.countDown(); finishBody.await(); returning.countDown(); return 42; }); }
            boolean cycle() { return runAndReset(); }
            @Override protected void done() { done.incrementAndGet(); }
        }
        Repeat future = new Repeat();
        Thread worker = new Thread(() -> {
            try { if (reset) future.cycle(); else future.run(); }
            catch (Throwable error) { failure.set(error); }
            finally { handedOff.countDown(); }
        }, "owned-future-worker") {
            @Override public void interrupt() {
                interruptEntered.countDown();
                try { await(releaseInterrupt, "interrupt-release"); }
                catch (InterruptedException error) { throw new AssertionError(error); }
                super.interrupt();
            }
        };
        Thread canceller = new Thread(() -> {
            try { require(future.cancel(true), "cancel-refused"); }
            catch (Throwable error) { failure.set(error); }
        }, "owned-future-canceller");
        try {
            worker.start(); await(entered, "callback-not-started"); held(1);
            canceller.start(); await(interruptEntered, "interrupt-not-started");
            require(future.isDone() && future.isCancelled() && !future.cancel(false) && !future.cancel(true), "state-not-visible");
            try { future.get(); throw new AssertionError("cancelled-get-returned"); }
            catch (CancellationException expected) { }
            finishBody.countDown(); await(returning, "body-not-returning");
            require(!handedOff.await(500, TimeUnit.MILLISECONDS), "worker-handoff-before-interrupt");
            held(1);
            require(Activation.closeAttempts(LatentRuntimeActivationOwnerKind.Result) == 0, "owner-retired-before-interrupt");
        } finally {
            finishBody.countDown(); releaseInterrupt.countDown();
            canceller.join(5000); worker.join(5000);
        }
        require(!canceller.isAlive() && !worker.isAlive() && failure.get() == null && done.get() == 1, "handoff-cleanup");
        require(Activation.closeAttempts(LatentRuntimeActivationOwnerKind.Result) == 1, "result-not-settled-once");
        held(0); Activation.idle();
    }
    private static void settlement(boolean lost) throws Exception {
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicReference<Throwable> failure = new AtomicReference<>();
        FutureTask<Integer> future = new FutureTask<>(() -> { entered.countDown(); release.await(); return 42; });
        Thread worker = new Thread(future, "future-settlement-worker") {
            @Override public void interrupt() { /* hold the running callback until explicit release */ }
        };
        worker.setUncaughtExceptionHandler((ignored, error) -> failure.set(error));
        try {
            worker.start(); await(entered, "settlement-body-not-started");
            require(future.cancel(true), "settlement-cancel-refused"); held(1);
            if (lost) Activation.loseCloseAckNext = "Result"; else Activation.denyCloseNext = "Result";
            release.countDown(); worker.join(5000);
            require(!worker.isAlive() && failure.get() instanceof IllegalStateException, "settlement-error-lost");
            require(Activation.poisoned && Activation.failedLeaseAttempts() == 1, "settlement-not-fenced");
            held(lost ? 0 : 1);
            var field = FutureTask.class.getDeclaredField("owner"); field.setAccessible(true);
            require(field.get(future) != null, "original-owner-not-retained");
            require(!future.cancel(false), "completed-cancel-accepted"); future.run();
            require(Activation.failedLeaseAttempts() == 1, "settlement-retried");
        } finally { release.countDown(); worker.join(5000); }
    }
    public static void main(String[] args) throws Exception {
        switch (args[0]) {
            case "run" -> handoff(false);
            case "reset" -> handoff(true);
            case "denied" -> settlement(false);
            case "lost" -> settlement(true);
            default -> throw new IllegalArgumentException("mode");
        }
        System.out.println("FUTURE_TASK_INTERRUPT_MONITOR_OWNER PASS " + args[0]);
    }
}
