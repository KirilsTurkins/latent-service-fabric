package dev.latent.app;

import java.util.concurrent.TimeUnit;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executors;
import java.util.concurrent.RejectedExecutionException;
import dev.latent.generated.Bindings;
import dev.latent.guest.runtime.Activation;
import org.apache.commons.lang3.concurrent.TimedSemaphore;

/** Ordinary unchanged published default factory: no executor or timer injection. */
public final class Capsule {
    private static final ThreadLocal<String> local = new ThreadLocal<>();
    private static void require(boolean value) {
        if (!value) throw new IllegalStateException("published-scheduled-observable");
    }
    public Long run(Long mode) {
        if (mode == 9) return standardSleepAdmissionRefusal();
        if (mode == 8) return timerAdmissionRefusal();
        if (mode == 6) return defaultCompletion();
        if (mode == 7) return standardRejection();
        if (mode == 5) {
            boolean original = false;
            try { new TimedSemaphore(0, TimeUnit.MILLISECONDS, 1); }
            catch (IllegalArgumentException expected) { original = true; }
            require(original);
            return 42L;
        }
        TimedSemaphore semaphore = new TimedSemaphore(1, TimeUnit.MILLISECONDS, mode == 1 ? 2 : 1);
        try {
            synchronized (semaphore) {
                require(semaphore.getPeriod() == 1 && semaphore.getUnit() == TimeUnit.MILLISECONDS);
                if (mode == 0) {
                    semaphore.acquire(); semaphore.acquire();
                    require(semaphore.getAcquireCount() == 1);
                } else if (mode == 1) {
                    semaphore.acquire(); semaphore.acquire(); semaphore.acquire();
                    require(semaphore.getAcquireCount() == 1);
                } else if (mode == 2) {
                    require(semaphore.tryAcquire());
                    semaphore.acquire();
                    require(semaphore.getAcquireCount() == 1);
                } else if (mode == 3) {
                    semaphore.setLimit(0);
                    for (int i = 0; i < 4; ++i) semaphore.acquire();
                    require(semaphore.getAcquireCount() == 4);
                } else if (mode == 4) {
                    semaphore.acquire(); semaphore.shutdown(); semaphore.shutdown();
                    require(semaphore.isShutdown());
                    boolean original = false;
                    try { semaphore.tryAcquire(); }
                    catch (IllegalStateException expected) { original = true; }
                    require(original);
                } else throw new IllegalArgumentException("published-scheduled-mode");
                return 42L;
            }
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException(error);
        } finally { semaphore.shutdown(); }
    }
    // This diagnostic uses real SDK timer starts and the real host observation.
    // The JDK reference runs modes 0..7 only; it does not simulate this mode.
    private static final class TimerProbe {
        final Object gate = new Object();
        final boolean[] held = new boolean[2], released = new boolean[2], done = new boolean[2];
        final Throwable[] failure = new Throwable[2];
        final Thread[] workers = new Thread[2];
    }
    private static void timerProbeRequire(boolean value, String reason) {
        if (!value) throw new IllegalStateException("timer-admission-probe-" + reason);
    }
    private static long[] timerObservation() {
        var observed = Bindings.LatentRuntimeActivation.observe();
        timerProbeRequire(!observed.isError(), "observe");
        var value = observed.value();
        return new long[] {value.timers(), value.admissionFailures().bits(), value.waits()};
    }
    private static void timerWorker(TimerProbe probe, int slot) {
        try (Activation.Lease ignored = Activation.timer(Activation.monotonicMillis() + 60_000)) {
            synchronized (probe.gate) {
                probe.held[slot] = true;
                probe.gate.notifyAll();
                while (!probe.released[slot]) probe.gate.wait();
            }
        } catch (Throwable error) {
            synchronized (probe.gate) {
                probe.failure[slot] = error;
                probe.gate.notifyAll();
            }
        } finally {
            // Published only after the original timer's close has returned.
            synchronized (probe.gate) {
                probe.done[slot] = true;
                probe.gate.notifyAll();
            }
        }
    }
    private static void awaitTimerWorker(TimerProbe probe, int slot, boolean finished) {
        if (finished) {
            try { probe.workers[slot].join(); }
            catch (InterruptedException error) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException("timer-admission-join-interrupted", error);
            }
            timerProbeRequire(!probe.workers[slot].isAlive(), "worker-alive-after-join");
        }
        synchronized (probe.gate) {
            try {
                while (!finished && !probe.held[slot] && probe.failure[slot] == null && !probe.done[slot])
                    probe.gate.wait();
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException("timer-admission-wait-interrupted", error);
            }
            if (probe.failure[slot] != null)
                throw new IllegalStateException("timer-admission-worker", probe.failure[slot]);
            timerProbeRequire(finished ? probe.done[slot] : probe.held[slot], "worker-state");
        }
    }
    private static void releaseTimerWorker(TimerProbe probe, int slot) {
        synchronized (probe.gate) {
            probe.released[slot] = true;
            probe.gate.notifyAll();
        }
    }
    private static Long timerAdmissionRefusal() {
        TimerProbe probe = new TimerProbe();
        try {
            for (int i = 0; i < 2; i++) {
                final int slot = i;
                probe.workers[i] = new Thread(() -> timerWorker(probe, slot), "timer-probe-" + i);
                probe.workers[i].start();
            }
            awaitTimerWorker(probe, 0, false);
            awaitTimerWorker(probe, 1, false);
            long[] before = timerObservation();
            timerProbeRequire(before[0] == 2 && before[1] == 0, "two-live");
            boolean refused = false;
            try (Activation.Lease unexpected = Activation.timer(Activation.monotonicMillis() + 60_000)) {
                throw new IllegalStateException("timer-admission-probe-expected-refusal");
            } catch (IllegalStateException expected) {
                refused = "activation-runtime-timer-start-ResourceExhausted".equals(expected.getMessage());
            }
            timerProbeRequire(refused, "typed-refusal");
            long[] denied = timerObservation();
            timerProbeRequire(denied[0] == before[0] && denied[1] == before[1] + 1, "host-refusal");
            releaseTimerWorker(probe, 0);
            awaitTimerWorker(probe, 0, true);
            long[] one = timerObservation();
            timerProbeRequire(one[0] == 1 && one[1] == denied[1], "first-stop");
            long[] retried;
            try (Activation.Lease retry = Activation.timer(Activation.monotonicMillis() + 60_000)) {
                retried = timerObservation();
                timerProbeRequire(retried[0] == 2 && retried[1] == denied[1], "same-work-retry");
            }
            long[] stopped = timerObservation();
            timerProbeRequire(stopped[0] == 1 && stopped[1] == denied[1], "retry-stop");
            releaseTimerWorker(probe, 1);
            awaitTimerWorker(probe, 1, true);
            long[] end = timerObservation();
            timerProbeRequire(end[0] == 0 && end[1] == denied[1], "final-stop");
            // Encode the actual snapshots so the signed owner must check them.
            return ((((((before[0] * 10 + denied[0]) * 10 + (denied[1] - before[1])) * 10
                + one[0]) * 10 + retried[0]) * 10 + stopped[0]) * 10 + end[0]);
        } finally {
            releaseTimerWorker(probe, 0);
            releaseTimerWorker(probe, 1);
        }
    }
    // Ordinary Thread.sleep must return its original Wait if Timer admission
    // is refused, and the same logical thread must be able to try again.
    private static Long standardSleepAdmissionRefusal() {
        TimerProbe probe = new TimerProbe();
        try {
            for (int i = 0; i < 2; i++) {
                final int slot = i;
                probe.workers[i] = new Thread(() -> timerWorker(probe, slot), "sleep-probe-" + i);
                probe.workers[i].start();
            }
            awaitTimerWorker(probe, 0, false);
            awaitTimerWorker(probe, 1, false);
            long[] before = timerObservation();
            timerProbeRequire(before[0] == 2 && before[1] == 0 && before[2] == 2, "sleep-two-held");
            boolean refused = false;
            try {
                Thread.sleep(1);
            } catch (IllegalStateException expected) {
                refused = "activation-runtime-timer-start-ResourceExhausted".equals(expected.getMessage());
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException("sleep-probe-unexpected-interrupt", interrupted);
            }
            timerProbeRequire(refused, "sleep-typed-refusal");
            long[] denied = timerObservation();
            timerProbeRequire(denied[0] == before[0] && denied[1] == before[1] + 1
                && denied[2] == before[2], "sleep-refusal-returned-wait");
            releaseTimerWorker(probe, 0);
            awaitTimerWorker(probe, 0, true);
            long[] one = timerObservation();
            timerProbeRequire(one[0] == 1 && one[1] == denied[1] && one[2] == 1, "sleep-first-stop");
            try { Thread.sleep(1); }
            catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException("sleep-probe-retry-interrupted", interrupted);
            }
            long[] retried = timerObservation();
            timerProbeRequire(retried[0] == 1 && retried[1] == denied[1] && retried[2] == 1,
                "sleep-retry-returned-owners");
            releaseTimerWorker(probe, 1);
            awaitTimerWorker(probe, 1, true);
            long[] end = timerObservation();
            timerProbeRequire(end[0] == 0 && end[1] == denied[1] && end[2] == 0, "sleep-final-stop");
            return (((((before[0] * 10 + before[2]) * 10 + (denied[1] - before[1])) * 10
                + one[0]) * 10 + retried[0]) * 10 + end[0]);
        } finally {
            releaseTimerWorker(probe, 0);
            releaseTimerWorker(probe, 1);
        }
    }
    private static Long defaultCompletion() {
        Thread root = Thread.currentThread();
        Object gate = new Object();
        boolean[] entered = {false}, released = {false};
        local.set("root");
        CompletableFuture<Integer> pending = CompletableFuture.supplyAsync(() -> {
            require(Thread.currentThread() != root && local.get() == null);
            local.set("default-callback");
            synchronized (gate) {
                entered[0] = true; gate.notifyAll();
                try { while (!released[0]) gate.wait(); }
                catch (InterruptedException error) { throw new IllegalStateException(error); }
            }
            return 20;
        });
        try {
            synchronized (gate) {
                while (!entered[0]) gate.wait();
                require(!pending.isDone());
                released[0] = true; gate.notifyAll();
            }
            require(pending.thenApplyAsync(value -> value + 22).get() == 42);
            require("root".equals(local.get()));
            IllegalArgumentException original = new IllegalArgumentException("default-callback-original-error");
            CompletableFuture<Integer> failed = CompletableFuture.supplyAsync(() -> { throw original; });
            try { failed.get(); throw new IllegalStateException("missing-future-error"); }
            catch (ExecutionException expected) { require(expected.getCause() == original); }
            return 42L;
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException(error);
        } catch (ExecutionException error) {
            throw new IllegalStateException(error);
        }
    }
    private static Long standardRejection() {
        Thread root = Thread.currentThread();
        var executor = Executors.newSingleThreadExecutor();
        try {
            require(executor.submit(() -> Thread.currentThread() != root ? 42 : -1).get() == 42);
            executor.shutdown();
            boolean original = false;
            try { executor.submit(() -> { throw new IllegalStateException("rejected-callback-ran"); }); }
            catch (RejectedExecutionException expected) { original = true; }
            require(original && executor.isShutdown());
            require(executor.awaitTermination(1, TimeUnit.SECONDS) && executor.isTerminated());
            return 42L;
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException(error);
        } catch (ExecutionException error) {
            throw new IllegalStateException(error);
        } finally { executor.shutdownNow(); }
    }
}
