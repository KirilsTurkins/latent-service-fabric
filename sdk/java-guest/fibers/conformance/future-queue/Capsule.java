package dev.latent.app;

import java.util.List;
import java.util.concurrent.CancellationException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.FutureTask;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/** Ordinary FutureTask queue semantics plus one explicit bounded-result outcome. */
public final class Capsule {
    static void require(boolean value) { if (!value) throw new IllegalStateException("future-queue-observable"); }
    static final class Gate {
        private boolean entered, released;
        synchronized void work() {
            entered = true; notifyAll();
            while (!released) {
                try { wait(); } catch (InterruptedException expected) { }
            }
        }
        synchronized void entered() throws InterruptedException { while (!entered) wait(); }
        synchronized void release() { released = true; notifyAll(); }
    }
    static final class Pair implements AutoCloseable {
        final Gate firstGate = new Gate(), secondGate = new Gate();
        final ExecutorService first = Executors.newSingleThreadExecutor(), second = Executors.newSingleThreadExecutor();
        final FutureTask<Integer> target;
        int calls;
        Pair() throws InterruptedException {
            boolean prepared = false;
            try {
                first.execute(firstGate::work); second.execute(secondGate::work);
                firstGate.entered(); secondGate.entered();
                target = new FutureTask<>(() -> { calls++; return 42; });
                first.execute(target); second.execute(target);
                prepared = true;
            } finally { if (!prepared) { firstGate.release(); secondGate.release(); first.shutdownNow(); second.shutdownNow(); } }
        }
        void withdrawFirst() throws InterruptedException {
            List<Runnable> pending = first.shutdownNow();
            require(pending.size() == 1 && pending.get(0) == target);
            firstGate.release(); require(first.awaitTermination(5, TimeUnit.SECONDS));
            require(!target.isDone() && calls == 0);
        }
        void withdrawLast() throws InterruptedException {
            List<Runnable> pending = second.shutdownNow();
            require(pending.size() == 1 && pending.get(0) == target);
            secondGate.release(); require(second.awaitTermination(5, TimeUnit.SECONDS));
            require(!target.isDone() && calls == 0);
        }
        @Override public void close() throws InterruptedException {
            firstGate.release(); secondGate.release(); first.shutdownNow(); second.shutdownNow();
            require(first.awaitTermination(5, TimeUnit.SECONDS) && second.awaitTermination(5, TimeUnit.SECONDS));
        }
    }
    static final class Running implements AutoCloseable {
        final Gate gate = new Gate(), queuedGate = new Gate();
        final ExecutorService runningPool = Executors.newSingleThreadExecutor(), queuedPool = Executors.newSingleThreadExecutor();
        final FutureTask<Integer> target;
        int calls;
        Running() throws InterruptedException {
            boolean prepared = false;
            try {
                queuedPool.execute(queuedGate::work); queuedGate.entered();
                target = new FutureTask<>(() -> { calls++; gate.work(); return 42; });
                runningPool.execute(target); gate.entered(); queuedPool.execute(target);
                List<Runnable> pending = queuedPool.shutdownNow();
                require(pending.size() == 1 && pending.get(0) == target);
                queuedGate.release(); require(queuedPool.awaitTermination(5, TimeUnit.SECONDS));
                require(target.cancel(false) && target.isCancelled() && calls == 1);
                prepared = true;
            } finally { if (!prepared) { gate.release(); queuedGate.release(); runningPool.shutdownNow(); queuedPool.shutdownNow(); } }
        }
        void finish() throws InterruptedException {
            gate.release(); runningPool.shutdown(); require(runningPool.awaitTermination(5, TimeUnit.SECONDS));
            require(target.isCancelled() && calls == 1);
            try { target.get(); throw new AssertionError("missing-cancel"); }
            catch (CancellationException expected) { }
            catch (java.util.concurrent.ExecutionException wrong) { throw new AssertionError(wrong); }
        }
        @Override public void close() throws InterruptedException {
            gate.release(); queuedGate.release(); runningPool.shutdownNow(); queuedPool.shutdownNow();
            require(runningPool.awaitTermination(5, TimeUnit.SECONDS) && queuedPool.awaitTermination(5, TimeUnit.SECONDS));
        }
    }
    static final class ScheduledCopy implements AutoCloseable {
        final Gate gate = new Gate();
        final ExecutorService pool = Executors.newSingleThreadExecutor();
        final ScheduledThreadPoolExecutor timer = new ScheduledThreadPoolExecutor(1);
        final FutureTask<?> target;
        int calls;
        ScheduledCopy() throws InterruptedException {
            boolean prepared = false;
            try {
                pool.execute(gate::work); gate.entered();
                target = (FutureTask<?>)timer.schedule(() -> { calls++; }, 1, TimeUnit.DAYS);
                pool.execute(target);
                List<Runnable> pending = pool.shutdownNow();
                require(pending.size() == 1 && pending.get(0) == target);
                gate.release(); require(pool.awaitTermination(5, TimeUnit.SECONDS));
                require(!target.isDone() && calls == 0);
                prepared = true;
            } finally { if (!prepared) { gate.release(); pool.shutdownNow(); timer.shutdownNow(); } }
        }
        void withdrawLast() throws InterruptedException {
            List<Runnable> pending = timer.shutdownNow();
            require(pending.size() == 1 && pending.get(0) == target && !target.isDone() && calls == 0);
            require(timer.awaitTermination(5, TimeUnit.SECONDS));
        }
        @Override public void close() throws InterruptedException {
            gate.release(); pool.shutdownNow(); timer.shutdownNow();
            require(pool.awaitTermination(5, TimeUnit.SECONDS) && timer.awaitTermination(5, TimeUnit.SECONDS));
        }
    }
    public Long run(Long mode) {
        try {
            if (mode == 0) {
                try (Pair selected = new Pair()) {
                    selected.withdrawFirst();
                    FutureTask<Integer> extra = new FutureTask<>(() -> 41);
                    boolean denied = false;
                    try { selected.second.execute(extra); }
                    catch (IllegalStateException error) {
                        if (!"activation-runtime-register-ResourceExhausted".equals(error.getMessage())) throw error;
                        denied = true;
                    }
                    selected.secondGate.release(); selected.second.shutdown();
                    require(selected.second.awaitTermination(5, TimeUnit.SECONDS));
                    require(selected.target.get() == 42 && selected.calls == 1);
                    require(denied ? !extra.isDone() : extra.get() == 41);
                    return denied ? 42L : 41L;
                }
            } else if (mode == 1) {
                try (Pair selected = new Pair()) {
                    selected.withdrawFirst(); selected.withdrawLast();
                    selected.target.run(); selected.target.run();
                    require(selected.target.get() == 42 && selected.calls == 1);
                }
            } else if (mode == 2) {
                try (Running selected = new Running()) { selected.finish(); }
            } else if (mode == 3) {
                try (ScheduledCopy selected = new ScheduledCopy()) { selected.withdrawLast(); }
            } else throw new IllegalArgumentException("future-queue-mode");
            return 42L;
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt(); throw new IllegalStateException(error);
        } catch (java.util.concurrent.ExecutionException error) { throw new IllegalStateException(error); }
    }
}
