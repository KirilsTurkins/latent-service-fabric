package dev.latent.app;

import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Timer;
import java.util.TimerTask;
import java.util.function.Consumer;
import dev.latent.generated.Bindings;
import java.util.concurrent.CancellationException;
import java.util.concurrent.FutureTask;

/** Ordinary standard APIs; only the reference process owns explicit final cleanup. */
public final class Capsule {
    public static final List<Timer> referenceTimers = new ArrayList<>();
    public static volatile boolean lateCallback;
    public static volatile boolean cancelledCallbackFinished;
    private static final Object gate = new Object();
    private static final ThreadLocal<String> local = new ThreadLocal<>();
    private static volatile Throwable failure;

    private static void require(boolean value) {
        if (!value) throw new IllegalStateException("standard-timer-observable");
    }
    private static Timer timer(String name) {
        Timer timer = new Timer(name, true);
        referenceTimers.add(timer);
        return timer;
    }
    private static TimerTask task(Consumer<TimerTask> action) {
        return new TimerTask() {
            @Override public void run() {
                try { action.accept(this); }
                catch (Throwable error) { failure = error; throw error; }
                finally { synchronized (gate) { gate.notifyAll(); } }
            }
        };
    }
    private static void await(java.util.function.BooleanSupplier condition) {
        long started = System.nanoTime();
        synchronized (gate) {
            while (!condition.getAsBoolean()) {
                if (failure != null) throw new IllegalStateException("timer-callback-failed", failure);
                if (System.nanoTime() - started > 5_000_000_000L) throw new IllegalStateException("timer-control-deadline");
                try { gate.wait(5); } catch (InterruptedException error) { throw new IllegalStateException(error); }
            }
        }
    }
    private static void sleep(long millis) {
        try { Thread.sleep(millis); } catch (InterruptedException error) { throw new IllegalStateException(error); }
    }
    private static void illegal(Runnable action, Class<? extends Throwable> expected) {
        try { action.run(); }
        catch (Throwable error) { require(expected.isInstance(error)); return; }
        throw new IllegalStateException("timer-missing-native-error");
    }

    /** Same ordinary-API scenario in the reference JDK and signed timer component. */
    private static final class InterruptFailureProbe {
        final Object gate = new Object();
        final boolean deliver, interrupt;
        final Throwable interruptFailure;
        final Throwable doneFailure;
        boolean entered, release, getterStarted, getterFinished, getterCancelled, interrupted;
        int doneCalls, finallyCalls, interruptCalls;
        Throwable workerFailure, getterFailure;

        InterruptFailureProbe(int mode) {
            interrupt = mode != 7;
            deliver = interrupt && (mode == 6 || (mode & 1) != 0);
            interruptFailure = mode >= 6 ? null : mode < 2 || mode == 4
                    ? new SecurityException("interrupt-refused") : new AssertionError("interrupt-error");
            doneFailure = mode == 4 || mode == 5 ? new AssertionError("done-failed") : null;
        }
        static void raise(Throwable error) {
            if (error instanceof RuntimeException runtime) throw runtime;
            throw (Error) error;
        }
        int call() {
            synchronized (gate) {
                entered = true; gate.notifyAll();
                try {
                    while (!release) {
                        try { gate.wait(); }
                        catch (InterruptedException expected) { interrupted = true; }
                    }
                    interrupted |= Thread.interrupted();
                    return 42;
                } finally { finallyCalls++; }
            }
        }
        void completed() {
            synchronized (gate) {
                doneCalls++;
                // A real sibling must obtain the cancelled result while done()
                // is still running. No Thread.getState or private guest ledger.
                while (!getterFinished) {
                    try { gate.wait(); }
                    catch (InterruptedException error) { throw new IllegalStateException(error); }
                }
            }
            if (doneFailure != null) raise(doneFailure);
        }
        void run() throws InterruptedException {
            FutureTask<Integer> future = new FutureTask<>(this::call) {
                @Override protected void done() { completed(); }
            };
            Thread worker = new Thread(() -> {
                try { future.run(); }
                catch (Throwable error) { synchronized (gate) { workerFailure = error; } }
            }) {
                @Override public void interrupt() {
                    interruptCalls++;
                    if (deliver) super.interrupt();
                    if (interruptFailure != null) raise(interruptFailure);
                }
            };
            Thread getter = new Thread(() -> {
                synchronized (gate) { getterStarted = true; gate.notifyAll(); }
                try {
                    future.get();
                    synchronized (gate) { getterFailure = new IllegalStateException("cancelled-get-returned"); }
                } catch (CancellationException expected) {
                    synchronized (gate) { getterCancelled = true; }
                } catch (Throwable error) {
                    synchronized (gate) { getterFailure = error; }
                } finally {
                    synchronized (gate) { getterFinished = true; gate.notifyAll(); }
                }
            });
            worker.start();
            try {
                synchronized (gate) { while (!entered) gate.wait(); }
                getter.start();
                synchronized (gate) { while (!getterStarted) gate.wait(); }
                Throwable observed = null;
                boolean cancelled = false;
                try { cancelled = future.cancel(interrupt); }
                catch (Throwable error) { observed = error; }
                Throwable expected = doneFailure != null ? doneFailure : interruptFailure;
                require(observed == expected && cancelled == (expected == null));
                require(future.isDone() && future.isCancelled() && !future.cancel(true));
                require(future.state() == java.util.concurrent.Future.State.CANCELLED);
                synchronized (gate) {
                    require(doneCalls == 1 && getterFinished && getterCancelled && getterFailure == null);
                    require(finallyCalls == 0 && worker.isAlive());
                }
            } finally {
                synchronized (gate) { release = true; gate.notifyAll(); }
                // The reference process owns an outer timeout; the signed path
                // keeps its original activation deadline, fuel and owner limits.
                // Failure cleanup must not leave an old unnotified getter alive.
                if (getter.isAlive()) getter.interrupt();
                worker.join(); getter.join();
            }
            synchronized (gate) {
                require(workerFailure == null && finallyCalls == 1 && interrupted == deliver);
                require(doneCalls == 1 && interruptCalls == (interrupt ? 1 : 0));
            }
        }
    }

    public Long run(Long mode) {
        if (mode < 0 || mode > 3) throw new IllegalArgumentException();
        try {
            // Finish and join both probe threads before creating timer workers.
            // Keep the existing signed modes and activation resource ceilings.
            for (int scenario = mode.intValue() * 2; scenario < mode.intValue() * 2 + 2; scenario++)
                new InterruptFailureProbe(scenario).run();
        } catch (InterruptedException error) { throw new IllegalStateException(error); }
        if (mode == 0) return basic();
        if (mode == 1) return recurring();
        if (mode == 2) return acceptedAfterRoot();
        if (mode == 3) { activeTimerOwners(); return cancellation(); }
        throw new IllegalArgumentException();
    }

    private static Long basic() {
        Timer first = timer("timer-first"), second = timer("timer-second");
        taskMonitorCompatibility(first);
        // These invalid calls use existing timers and cannot admit queued work.
        illegal(() -> first.schedule((TimerTask)null, new Date(-1)), IllegalArgumentException.class);
        illegal(() -> first.schedule((TimerTask)null, new Date(-1), 1), IllegalArgumentException.class);
        illegal(() -> first.scheduleAtFixedRate((TimerTask)null, new Date(-1), 1), IllegalArgumentException.class);
        illegal(() -> first.schedule(task(self -> { }), (Date)null, 0), IllegalArgumentException.class);
        illegal(() -> first.scheduleAtFixedRate(task(self -> { }), (Date)null, 0), IllegalArgumentException.class);
        int[] values = {0, 0, 0};
        local.set("root");
        TimerTask once = task(self -> {
            require("timer-first".equals(Thread.currentThread().getName()) && local.get() == null);
            local.set("first");
            synchronized (gate) { values[0] = 20; }
        });
        first.schedule(once, 0);
        second.schedule(task(self -> {
            require("timer-second".equals(Thread.currentThread().getName()) && local.get() == null);
            local.set("second");
            synchronized (gate) { values[1] = 22; }
        }), 1);
        await(() -> values[0] == 20 && values[1] == 22);
        require("root".equals(local.get()) && !once.cancel());
        first.schedule(task(self -> {
            require("first".equals(local.get()) && self.scheduledExecutionTime() == 0);
            synchronized (gate) { values[2] = 1; }
        }), new Date(0));
        await(() -> values[2] == 1);
        TimerTask cancelled = task(self -> { throw new IllegalStateException("cancelled-task-ran"); });
        require(!cancelled.cancel());
        illegal(() -> first.schedule(cancelled, 0), IllegalStateException.class);
        illegal(() -> first.schedule(once, 0), IllegalStateException.class);
        illegal(() -> first.schedule(task(self -> { }), -1), IllegalArgumentException.class);
        illegal(() -> first.schedule(task(self -> { }), Long.MAX_VALUE), IllegalArgumentException.class);
        illegal(() -> first.schedule(task(self -> { }), new Date(-1)), IllegalArgumentException.class);
        illegal(() -> first.schedule(task(self -> { }), 0, 0), IllegalArgumentException.class);
        illegal(() -> first.scheduleAtFixedRate(task(self -> { }), 0, -1), IllegalArgumentException.class);
        illegal(() -> first.schedule(null, 0), NullPointerException.class);
        first.cancel(); first.cancel(); second.cancel();
        illegal(() -> first.schedule((TimerTask)null, 0), IllegalStateException.class);
        illegal(() -> first.scheduleAtFixedRate((TimerTask)null, new Date(0), 1), IllegalStateException.class);
        illegal(() -> first.schedule(task(self -> { }), 0), IllegalStateException.class);
        return 42L;
    }

    private static void taskMonitorCompatibility(Timer timer) {
        TimerTask future = task(self -> { throw new IllegalStateException("cancelled-monitor-task-ran"); });
        boolean[] done = {false};
        Thread contender = new Thread(() -> {
            try {
                timer.schedule(future, 60_000);
                future.scheduledExecutionTime();
                require(future.cancel());
            } catch (Throwable error) { failure = error; }
            finally { synchronized (gate) { done[0] = true; gate.notifyAll(); } }
        });
        try {
            // Waiting on the separate gate keeps the public task monitor held.
            synchronized (future) {
                contender.start();
                await(() -> done[0]);
            }
        } finally {
            try { contender.join(); }
            catch (InterruptedException error) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException("timer-monitor-join-interrupted", error);
            }
        }
        if (failure != null) throw new IllegalStateException("timer-monitor-worker-failed", failure);
        int purged = timer.purge();
        require(purged >= 0 && purged <= 1);
    }

    private static Long recurring() {
        Timer rate = timer("fixed-rate"), delay = timer("fixed-delay");
        int[] counts = {0, 0};
        long[] previous = {0, 0};
        rate.scheduleAtFixedRate(task(self -> {
            int count;
            synchronized (gate) {
                count = ++counts[0];
                if (count > 1) require(self.scheduledExecutionTime() - previous[0] == 5);
                previous[0] = self.scheduledExecutionTime();
            }
            if (count == 1) sleep(25);
            if (count == 3) { require(self.cancel() && !self.cancel()); rate.cancel(); }
        }), new Date(System.currentTimeMillis() - 10), 5);
        await(() -> counts[0] == 3);
        delay.schedule(task(self -> {
            int count;
            synchronized (gate) {
                count = ++counts[1];
                if (count == 2) require(self.scheduledExecutionTime() - previous[1] >= 20);
                previous[1] = self.scheduledExecutionTime();
            }
            if (count == 1) sleep(25);
            if (count == 3) { require(self.cancel()); delay.cancel(); }
        }), 0, 5);
        await(() -> counts[0] == 3 && counts[1] == 3);
        sleep(10);
        synchronized (gate) { require(counts[0] == 3 && counts[1] == 3); }
        return 42L;
    }

    private static Long acceptedAfterRoot() {
        timer("unused-idle");
        Timer timer = timer("accepted-after-root");
        timer.schedule(task(self -> { sleep(20); lateCallback = true; }), 10);
        return 42L;
    }

    // The reference JDK uses scripted observations solely to check callback
    // ordering. Only the guest observes the actual host owner counts.
    private static long[] observedOwners() {
        var observed = Bindings.LatentRuntimeActivation.observe();
        require(!observed.isError());
        var value = observed.value();
        return new long[] {value.queuedWork(), value.executors()};
    }
    private static void requireOwners(long[] baseline, long queued, long executors) {
        require(baseline[0] >= 0 && baseline[1] >= 0);
        long[] actual = observedOwners();
        require(actual[0] == baseline[0] + queued && actual[1] == baseline[1] + executors);
    }
    private static void activeTimerOwners() {
        long[] baseline = observedOwners();
        Timer timer = timer("active-owner-witness");
        boolean[] progress = {false, false, false, false};
        Thread[] worker = {null};
        TimerTask periodic = task(self -> {
            synchronized (gate) {
                worker[0] = Thread.currentThread();
                progress[0] = true; gate.notifyAll();
                while (!progress[1]) {
                    try { gate.wait(); }
                    catch (InterruptedException error) { throw new IllegalStateException(error); }
                }
            }
        });
        TimerTask marker = task(self -> {
            synchronized (gate) {
                require(worker[0] == Thread.currentThread());
                progress[2] = true; gate.notifyAll();
                while (!progress[3]) {
                    try { gate.wait(); }
                    catch (InterruptedException error) { throw new IllegalStateException(error); }
                }
                require(!Thread.currentThread().isInterrupted());
            }
        });
        try {
            timer.scheduleAtFixedRate(periodic, 0, 60_000);
            await(() -> progress[0]);
            timer.schedule(marker, 0);
            requireOwners(baseline, 2, 1);
            require(periodic.cancel() && timer.purge() == 1);
            // Purging a running periodic task cannot retire its active owner.
            requireOwners(baseline, 2, 1);
            synchronized (gate) { progress[1] = true; gate.notifyAll(); }
            await(() -> progress[2]);
            // The marker begins only after the first callback and its finally.
            requireOwners(baseline, 1, 1);
            timer.cancel();
            // The already-dequeued one-shot marker still owns its callback.
            requireOwners(baseline, 1, 1);
        } finally {
            timer.cancel();
            synchronized (gate) { progress[1] = progress[3] = true; gate.notifyAll(); }
            if (worker[0] != null) {
                try { worker[0].join(5_000); }
                catch (InterruptedException error) {
                    Thread.currentThread().interrupt();
                    throw new IllegalStateException("timer-owner-join-interrupted", error);
                }
                require(!worker[0].isAlive());
            }
        }
        if (failure != null) throw new IllegalStateException("timer-owner-worker-failed", failure);
        requireOwners(baseline, 0, 0);
    }

    private static Long cancellation() {
        Timer timer = timer("cancel-running");
        boolean[] progress = {false, false};
        TimerTask running = task(self -> {
            synchronized (gate) {
                progress[0] = true; gate.notifyAll();
                while (!progress[1]) {
                    try { gate.wait(); } catch (InterruptedException error) { throw new IllegalStateException(error); }
                }
            }
            sleep(20);
            require(!Thread.currentThread().isInterrupted());
            cancelledCallbackFinished = true;
        });
        timer.schedule(running, 0);
        await(() -> progress[0]);
        timer.cancel();
        require(!running.cancel() && !cancelledCallbackFinished);
        illegal(() -> timer.schedule(task(self -> { }), 0), IllegalStateException.class);
        synchronized (gate) { progress[1] = true; gate.notifyAll(); }

        Timer queued = timer("cancel-queued");
        TimerTask future = task(self -> { throw new IllegalStateException("cancelled-future-ran"); });
        queued.schedule(future, 60_000);
        require(future.cancel() && !future.cancel());
        int purged = queued.purge();
        require(purged >= 0 && purged <= 1);
        queued.cancel();
        return 42L;
    }
}
