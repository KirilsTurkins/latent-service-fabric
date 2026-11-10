package dev.latent.guest.runtime.concurrent;

import dev.latent.generated.Bindings;
import dev.latent.guest.runtime.Activation;
import java.util.concurrent.Callable;
import java.util.concurrent.CancellationException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.RunnableFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Host/source and reference-JDK controls, not signed TeaVM guest evidence. */
public final class FutureTaskInterruptFailureControl {
    private static final long LIMIT_NANOS = TimeUnit.SECONDS.toNanos(5);
    private static final Bindings.LatentRuntimeActivationOwnerKind RESULT =
            Bindings.LatentRuntimeActivationOwnerKind.Result;

    private static void require(boolean value, String reason) {
        if (!value) throw new AssertionError(reason);
    }

    private static long remaining(long deadline) {
        return Math.max(0, deadline - System.nanoTime());
    }

    private static void await(CountDownLatch signal, long deadline, String reason)
            throws InterruptedException {
        require(signal.await(remaining(deadline), TimeUnit.NANOSECONDS), reason);
    }

    private static void join(Thread thread, long deadline) throws InterruptedException {
        long left = remaining(deadline);
        if (left != 0) TimeUnit.NANOSECONDS.timedJoin(thread, left);
        require(!thread.isAlive(), "thread-not-retired:" + thread.getName());
    }

    private static void rethrow(Throwable failure) {
        if (failure instanceof RuntimeException runtime) throw runtime;
        if (failure instanceof Error error) throw error;
        throw new AssertionError("unexpected-checked-failure", failure);
    }

    private static RunnableFuture<Integer> task(boolean source, Callable<Integer> body,
            AtomicInteger doneCalls, Throwable doneFailure) {
        Runnable completed = () -> {
            doneCalls.incrementAndGet();
            if (doneFailure != null) rethrow(doneFailure);
        };
        if (source) return new FutureTask<Integer>(body) {
            @Override protected void done() {
                require(!Thread.holdsLock(this), "done-executed-under-future-monitor");
                require(isDone(), "done-before-completion");
                completed.run();
            }
        };
        return new java.util.concurrent.FutureTask<Integer>(body) {
            @Override protected void done() {
                require(!Thread.holdsLock(this), "done-executed-under-future-monitor");
                require(isDone(), "done-before-completion");
                completed.run();
            }
        };
    }

    private static void awaitGetterWait(Thread getter, long deadline) {
        // Actual blocked state, not elapsed sleep or a fixed yield count, is the witness.
        while (getter.getState() != Thread.State.WAITING) {
            require(getter.isAlive(), "getter-exited-before-wait");
            require(remaining(deadline) != 0, "getter-never-blocked");
            Thread.onSpinWait();
        }
    }

    private static void running(boolean source, String mode) throws Exception {
        boolean deliver = mode.startsWith("after") || mode.equals("normal");
        boolean interrupt = !mode.equals("no-interrupt");
        boolean fail = !mode.equals("normal") && !mode.equals("no-interrupt");
        Throwable interruptFailure = (mode.startsWith("before-error") || mode.startsWith("after-error"))
                ? new AssertionError("interrupt-error") : new SecurityException("interrupt-refused");
        Throwable doneFailure = mode.endsWith("done-error") ? new AssertionError("done-failed") : null;
        long deadline = System.nanoTime() + LIMIT_NANOS;
        CountDownLatch entered = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        CountDownLatch waiterFinished = new CountDownLatch(1);
        AtomicInteger doneCalls = new AtomicInteger();
        AtomicInteger finallyCalls = new AtomicInteger();
        AtomicInteger interruptCalls = new AtomicInteger();
        AtomicReference<Throwable> threadFailure = new AtomicReference<>();
        AtomicReference<Throwable> waiterResult = new AtomicReference<>();
        RunnableFuture<Integer> future = task(source, () -> {
            entered.countDown();
            try {
                while (true) {
                    try { release.await(); break; }
                    catch (InterruptedException expected) {
                        // Keep the physical runner alive until the test explicitly releases it.
                    }
                }
                return 42;
            } finally {
                finallyCalls.incrementAndGet();
            }
        }, doneCalls, doneFailure);
        Thread worker = new Thread(future, "future-cancel-worker") {
            @Override public void interrupt() {
                interruptCalls.incrementAndGet();
                if (deliver) super.interrupt();
                if (fail) rethrow(interruptFailure);
            }
        };
        Thread getter = new Thread(() -> {
            try { future.get(); waiterResult.set(new AssertionError("get-returned-a-value")); }
            catch (Throwable result) { waiterResult.set(result); }
            finally { waiterFinished.countDown(); }
        }, "future-cancel-getter");
        worker.setUncaughtExceptionHandler((thread, failure) -> threadFailure.set(failure));
        // Process containment only; successful controls still require joined physical retirement.
        worker.setDaemon(true);
        getter.setDaemon(true);
        worker.start();
        boolean getterStarted = false;
        Throwable observed = null;
        boolean cancelled = false;
        boolean getterWoke = false;
        int doneAtCancel = -1;
        try {
            await(entered, deadline, "callable-never-started");
            getter.start(); getterStarted = true;
            awaitGetterWait(getter, deadline);
            try { cancelled = future.cancel(interrupt); }
            catch (Throwable failure) { observed = failure; }
            doneAtCancel = doneCalls.get();
            getterWoke = waiterFinished.await(remaining(deadline), TimeUnit.NANOSECONDS);
            require(future.isDone() && future.isCancelled(), "cancellation-state-not-published");
            require(future.state() == java.util.concurrent.Future.State.CANCELLED, "wrong-terminal-state");
            require(!future.cancel(true), "second-cancel-accepted");
            require(interruptCalls.get() == (interrupt ? 1 : 0), "interrupt-count");
            if (source) {
                require(Activation.count(RESULT) == 1, "physical-runner-owner-lost");
                require(Activation.closeAttempts(RESULT) == 0, "physical-runner-settled-before-return");
            }
        } finally {
            release.countDown();
            // Reserve a separate bounded cleanup interval; an assertion must not leak test workers.
            long cleanup = System.nanoTime() + LIMIT_NANOS;
            if (getterStarted && getter.isAlive()) getter.interrupt();
            join(worker, cleanup);
            if (getterStarted) join(getter, cleanup);
        }
        require(threadFailure.get() == null, "worker-failed:" + threadFailure.get());
        require(finallyCalls.get() == 1, "callable-finally-not-executed-once");
        require(doneAtCancel == 1 && doneCalls.get() == 1, "done-not-executed-once:done=" + doneAtCancel + ",getterWoke=" + getterWoke);
        require(getterWoke && waiterResult.get() instanceof CancellationException, "blocked-getter-not-notified");
        Throwable expected = doneFailure != null ? doneFailure : fail ? interruptFailure : null;
        require(observed == expected, "wrong-exception-identity");
        require(cancelled == (expected == null), "wrong-cancel-return");
        if (source) {
            require(Activation.closeAttempts(RESULT) == 1, "result-owner-not-settled-once");
            Activation.idle();
        }
    }

    private static void inactive(boolean source, String mode) throws Exception {
        AtomicInteger bodyCalls = new AtomicInteger();
        AtomicInteger doneCalls = new AtomicInteger();
        RunnableFuture<Integer> future = task(source, () -> {
            bodyCalls.incrementAndGet();
            if (mode.equals("failed")) throw new IllegalArgumentException("body-failed");
            return 42;
        }, doneCalls, null);
        if (mode.equals("pending")) {
            require(future.cancel(true), "pending-cancel-refused");
            require(!future.cancel(false), "duplicate-pending-cancel");
            future.run();
            try { future.get(); throw new AssertionError("cancelled-get-returned"); }
            catch (CancellationException expected) { }
            require(bodyCalls.get() == 0, "cancelled-body-executed");
        } else {
            future.run();
            require(!future.cancel(true), "terminal-cancel-accepted");
            if (mode.equals("completed")) require(future.get() == 42, "result-changed");
            else {
                try { future.get(); throw new AssertionError("failed-get-returned"); }
                catch (ExecutionException expected) {
                    require(expected.getCause() instanceof IllegalArgumentException, "failure-changed");
                }
            }
            require(bodyCalls.get() == 1, "body-count");
        }
        require(doneCalls.get() == 1, "inactive-done-count");
        if (source) Activation.idle();
    }

    private static void uncertainSettlement(String mode) {
        AtomicInteger doneCalls = new AtomicInteger();
        FutureTask<Integer> future = new FutureTask<Integer>(() -> 42) {
            @Override protected void done() { doneCalls.incrementAndGet(); }
        };
        require(future.accept(), "owner-not-admitted");
        boolean lost = mode.equals("lost-ack");
        if (lost) Activation.loseCloseAckNext = "Result";
        else Activation.denyCloseNext = "Result";
        try { future.cancel(false); throw new AssertionError("uncertain-settlement-accepted"); }
        catch (IllegalStateException expected) {
            require(expected.getMessage().equals(lost
                    ? "source-owner-settlement-ack-unknown" : "source-owner-settlement-denied"),
                    "wrong-settlement-failure");
        }
        require(Activation.poisoned, "uncertain-settlement-not-fenced");
        require(Activation.failedLeaseAttempts() == 1, "settlement-retried");
        require(Activation.count(RESULT) == (lost ? 0 : 1), "uncertain-owner-count");
        require(doneCalls.get() == 0, "done-ran-after-uncertain-owner-settlement");
        require(!future.cancel(true), "uncertain-cancel-repeated");
        future.run();
        require(Activation.failedLeaseAttempts() == 1, "late-settlement-retry");
        require(doneCalls.get() == 0, "late-done-after-uncertain-settlement");
    }

    public static void main(String[] args) throws Exception {
        require(args.length == 2, "usage: source|jdk mode");
        require(args[0].equals("source") || args[0].equals("jdk"), "unknown-implementation");
        boolean source = args[0].equals("source");
        String mode = args[1];
        switch (mode) {
            case "before-runtime", "after-runtime", "before-error", "after-error",
                 "before-runtime-done-error", "after-error-done-error", "normal", "no-interrupt" ->
                    running(source, mode);
            case "pending", "completed", "failed" -> inactive(source, mode);
            case "refused", "lost-ack" -> {
                require(source, "settlement-controls-require-source");
                uncertainSettlement(mode);
            }
            default -> throw new AssertionError("unknown-mode:" + mode);
        }
        System.out.println("future-cancel-interrupt " + args[0] + " " + mode + " passed");
    }
}
