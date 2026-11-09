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
    private static final int TIMER_PROBE_YIELDS = 50_000;
    private static final class TimerProbe {
        final Object gate = new Object();
        final boolean[] held = new boolean[2], released = new boolean[2], done = new boolean[2];
        final Throwable[] failure = new Throwable[2];
        final Thread[] workers = new Thread[2];
        // Temporary failure-only diagnostic. Values are reported by the
        // unchanged exact-result assertion, never accepted as success.
        int firstStage, secondStage;
        int phase;
        void stage(int slot, int stage) {
            synchronized (gate) {
                if (slot == 0) firstStage = stage; else secondStage = stage;
            }
        }
    }
    private static int timerDiagnosticReason(Throwable error) {
        String reason = error.getMessage();
        if ("timer-admission-probe-worker-timeout".equals(reason)) return 1;
        if ("timer-admission-worker".equals(reason)) {
            Throwable cause = error.getCause();
            return cause != null && "timer-admission-probe-worker-release-timeout".equals(cause.getMessage()) ? 2 : 3;
        }
        if ("timer-admission-probe-observe".equals(reason)) return 4;
        if ("timer-admission-probe-two-live".equals(reason)) return 5;
        if ("timer-admission-probe-typed-refusal".equals(reason)) return 6;
        if ("timer-admission-probe-host-refusal".equals(reason)) return 7;
        if ("timer-admission-probe-first-stop".equals(reason)) return 8;
        if ("timer-admission-probe-same-work-retry".equals(reason)) return 9;
        if ("timer-admission-probe-retry-stop".equals(reason)) return 10;
        if ("timer-admission-probe-final-stop".equals(reason)) return 11;
        return 12;
    }
    private static long timerDiagnostic(TimerProbe probe, Throwable error) {
        int flags = 0, first, second;
        synchronized (probe.gate) {
            first = probe.firstStage; second = probe.secondStage;
            if (probe.held[0]) flags |= 1;
            if (probe.held[1]) flags |= 2;
            if (probe.done[0]) flags |= 4;
            if (probe.done[1]) flags |= 8;
            if (probe.failure[0] != null) flags |= 16;
            if (probe.failure[1] != null) flags |= 32;
        }
        // 1,000,000,000 + phase*1,000,000 + worker stages*100,000/10,000
        // + reason*100 + bit flags. Never equal to expected 2,211,210.
        return 1_000_000_000L + probe.phase * 1_000_000L
            + first * 100_000L + second * 10_000L
            + timerDiagnosticReason(error) * 100L + flags;
    }
    private static void timerProbeRequire(boolean value, String reason) {
        if (!value) throw new IllegalStateException("timer-admission-probe-" + reason);
    }
    private static long[] timerObservation() {
        var observed = Bindings.LatentRuntimeActivation.observe();
        timerProbeRequire(!observed.isError(), "observe");
        var value = observed.value();
        return new long[] {value.timers(), value.admissionFailures().bits()};
    }
    private static void timerWorker(TimerProbe probe, int slot) {
        probe.stage(slot, 1); // scheduled, before timer admission
        try (Activation.Lease ignored = Activation.timer(Activation.monotonicMillis() + 60_000)) {
            probe.stage(slot, 2); // timer admission returned
            synchronized (probe.gate) { probe.held[slot] = true; }
            probe.stage(slot, 3); // held flag published
            boolean released = false;
            for (int i = 0; i < TIMER_PROBE_YIELDS; i++) {
                synchronized (probe.gate) { released = probe.released[slot]; }
                if (released) break;
                Thread.yield();
            }
            timerProbeRequire(released, "worker-release-timeout");
        } catch (Throwable error) {
            synchronized (probe.gate) { probe.failure[slot] = error; }
        } finally {
            // Published only after the original timer's close has returned.
            synchronized (probe.gate) { probe.done[slot] = true; }
        }
    }
    private static void awaitTimerWorker(TimerProbe probe, int slot, boolean finished) {
        for (int i = 0; i < TIMER_PROBE_YIELDS; i++) {
            boolean ready;
            synchronized (probe.gate) {
                if (probe.failure[slot] != null)
                    throw new IllegalStateException("timer-admission-worker", probe.failure[slot]);
                ready = finished ? probe.done[slot] : probe.held[slot];
            }
            if (ready && (!finished || !probe.workers[slot].isAlive())) return;
            Thread.yield();
        }
        throw new IllegalStateException("timer-admission-probe-worker-timeout");
    }
    private static void releaseTimerWorker(TimerProbe probe, int slot) {
        synchronized (probe.gate) { probe.released[slot] = true; }
    }
    private static Long timerAdmissionRefusal() {
        TimerProbe probe = new TimerProbe();
        try {
            for (int i = 0; i < 2; i++) {
                probe.phase = i + 1; // construct/start worker 0, then 1
                final int slot = i;
                probe.workers[i] = new Thread(() -> timerWorker(probe, slot), "timer-probe-" + i);
                probe.workers[i].start();
            }
            probe.phase = 3; awaitTimerWorker(probe, 0, false);
            probe.phase = 4; awaitTimerWorker(probe, 1, false);
            probe.phase = 5;
            long[] before = timerObservation();
            timerProbeRequire(before[0] == 2 && before[1] == 0, "two-live");
            boolean refused = false;
            probe.phase = 6;
            try (Activation.Lease unexpected = Activation.timer(Activation.monotonicMillis() + 60_000)) {
                throw new IllegalStateException("timer-admission-probe-expected-refusal");
            } catch (IllegalStateException expected) {
                refused = "activation-runtime-timer-start-ResourceExhausted".equals(expected.getMessage());
            }
            timerProbeRequire(refused, "typed-refusal");
            probe.phase = 7;
            long[] denied = timerObservation();
            timerProbeRequire(denied[0] == before[0] && denied[1] == before[1] + 1, "host-refusal");
            releaseTimerWorker(probe, 0);
            probe.phase = 8;
            awaitTimerWorker(probe, 0, true);
            probe.phase = 9;
            long[] one = timerObservation();
            timerProbeRequire(one[0] == 1 && one[1] == denied[1], "first-stop");
            long[] retried;
            probe.phase = 10;
            try (Activation.Lease retry = Activation.timer(Activation.monotonicMillis() + 60_000)) {
                retried = timerObservation();
                timerProbeRequire(retried[0] == 2 && retried[1] == denied[1], "same-work-retry");
            }
            probe.phase = 11; long[] stopped = timerObservation();
            timerProbeRequire(stopped[0] == 1 && stopped[1] == denied[1], "retry-stop");
            releaseTimerWorker(probe, 1);
            probe.phase = 12;
            awaitTimerWorker(probe, 1, true);
            probe.phase = 13;
            long[] end = timerObservation();
            timerProbeRequire(end[0] == 0 && end[1] == denied[1], "final-stop");
            // Encode the actual snapshots so the signed owner must check them.
            return ((((((before[0] * 10 + denied[0]) * 10 + (denied[1] - before[1])) * 10
                + one[0]) * 10 + retried[0]) * 10 + stopped[0]) * 10 + end[0]);
        } catch (Throwable error) {
            return timerDiagnostic(probe, error);
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
