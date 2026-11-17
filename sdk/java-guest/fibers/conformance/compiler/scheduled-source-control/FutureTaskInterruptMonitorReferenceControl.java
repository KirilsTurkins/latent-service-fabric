import java.util.concurrent.CancellationException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/** JDK and SDK source comparison; no guest or compiler-model execution. */
public final class FutureTaskInterruptMonitorReferenceControl {
    private static void require(boolean value, String message) { if (!value) throw new AssertionError(message); }
    private static void await(CountDownLatch latch, String message) throws InterruptedException {
        require(latch.await(5, TimeUnit.SECONDS), message);
    }
    private static void visible() throws Exception {
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicBoolean duringInterrupt = new AtomicBoolean(), seen = new AtomicBoolean();
        AtomicReference<Thread> reader = new AtomicReference<>();
        FutureTask<Integer> future = new FutureTask<>(() -> {
            entered.countDown();
            while (true) try { release.await(); return 42; } catch (InterruptedException ignored) { }
        });
        Thread worker = new Thread(future, "future-visible-worker") {
            @Override public void interrupt() {
                CountDownLatch started = new CountDownLatch(1), inspected = new CountDownLatch(1);
                Thread probe = new Thread(() -> {
                    started.countDown();
                    try {
                        if (!future.isDone() || !future.isCancelled() || future.cancel(false) || future.cancel(true)) return;
                        try { future.get(); return; } catch (CancellationException expected) { }
                        seen.set(true);
                    } catch (Exception error) { throw new AssertionError(error); }
                    finally { inspected.countDown(); }
                }, "future-interrupt-inspector");
                reader.set(probe); probe.start();
                try {
                    await(started, "inspector-not-started");
                    duringInterrupt.set(inspected.await(2, TimeUnit.SECONDS) && seen.get());
                } catch (InterruptedException error) { throw new AssertionError(error); }
                super.interrupt();
            }
        };
        try {
            worker.start(); await(entered, "callback-not-started");
            require(future.cancel(true), "cancel-refused");
            require(duringInterrupt.get(), "cancelled-state-locked-by-interrupt-hook");
        } finally {
            release.countDown(); worker.join(5000);
            if (reader.get() != null) reader.get().join(5000);
        }
        require(!worker.isAlive() && (reader.get() == null || !reader.get().isAlive()), "visible-threads-not-retired");
    }
    private static void handoff(boolean reset) throws Exception {
        CountDownLatch entered = new CountDownLatch(1), finishBody = new CountDownLatch(1);
        CountDownLatch returning = new CountDownLatch(1), interruptEntered = new CountDownLatch(1);
        CountDownLatch releaseInterrupt = new CountDownLatch(1), handedOff = new CountDownLatch(1);
        AtomicReference<Throwable> failure = new AtomicReference<>();
        class Repeat extends FutureTask<Integer> {
            Repeat() { super(() -> { entered.countDown(); finishBody.await(); returning.countDown(); return 42; }); }
            boolean cycle() { return runAndReset(); }
        }
        Repeat future = new Repeat();
        Thread worker = new Thread(() -> {
            try { if (reset) future.cycle(); else future.run(); }
            catch (Throwable error) { failure.set(error); }
            finally { handedOff.countDown(); }
        }, "future-handoff-worker") {
            @Override public void interrupt() {
                interruptEntered.countDown();
                try { await(releaseInterrupt, "interrupt-release"); }
                catch (InterruptedException error) { throw new AssertionError(error); }
                super.interrupt();
            }
        };
        Thread canceller = new Thread(() -> {
            try { require(future.cancel(true), "handoff-cancel-refused"); }
            catch (Throwable error) { failure.set(error); }
        }, "future-handoff-canceller");
        try {
            worker.start(); await(entered, "handoff-body-not-started");
            canceller.start(); await(interruptEntered, "interrupt-hook-not-entered");
            finishBody.countDown(); await(returning, "body-not-returning");
            require(!handedOff.await(500, TimeUnit.MILLISECONDS), "worker-reused-before-interrupt-returned");
        } finally {
            finishBody.countDown(); releaseInterrupt.countDown();
            canceller.join(5000); worker.join(5000);
        }
        require(!canceller.isAlive() && !worker.isAlive() && failure.get() == null && future.isCancelled(), "handoff-cleanup");
    }
    public static void main(String[] args) throws Exception {
        visible(); handoff(false); handoff(true);
        System.out.println("FUTURE_TASK_INTERRUPT_MONITOR PASS visible;run-handoff;reset-handoff");
    }
}
