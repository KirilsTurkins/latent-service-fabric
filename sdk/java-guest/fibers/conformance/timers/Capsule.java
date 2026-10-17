package dev.latent.app;

import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Timer;
import java.util.TimerTask;
import java.util.function.Consumer;

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

    public Long run(Long mode) {
        if (mode == 0) return basic();
        if (mode == 1) return recurring();
        if (mode == 2) return acceptedAfterRoot();
        if (mode == 3) return cancellation();
        throw new IllegalArgumentException();
    }

    private static Long basic() {
        Timer first = timer("timer-first"), second = timer("timer-second");
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
        illegal(() -> first.schedule(task(self -> { }), 0), IllegalStateException.class);
        return 42L;
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
