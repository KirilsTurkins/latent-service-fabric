package dev.latent.app;

import java.util.List;
import java.util.concurrent.CancellationException;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;

/** Ordinary shutdownNow observables; no runtime hooks or application adapter. */
public final class Capsule {
    static void require(boolean value) {
        if (!value) throw new IllegalStateException("shutdown-now-observable");
    }

    static final class Gate {
        private boolean entered, released;
        synchronized int work() {
            entered = true;
            notifyAll();
            while (!released) {
                try { wait(); }
                catch (InterruptedException stopped) { /* shutdownNow does not cancel this task. */ }
            }
            return 42;
        }
        synchronized void entered() throws InterruptedException { while (!entered) wait(); }
        synchronized void release() { released = true; notifyAll(); }
    }

    static final class Scenario implements AutoCloseable {
        final Gate gate = new Gate();
        final ExecutorService pool = Executors.newSingleThreadExecutor();
        final Thread caller = Thread.currentThread();
        int callbacks;
        final CompletableFuture<Integer> supplied, dependent;
        final List<Runnable> returned;

        Scenario() throws InterruptedException, ExecutionException {
            Future<Integer> blocked = pool.submit(gate::work);
            boolean prepared = false;
            try {
                gate.entered();
                supplied = CompletableFuture.supplyAsync(() -> {
                    require(Thread.currentThread() == caller);
                    callbacks++;
                    return 42;
                }, pool);
                dependent = CompletableFuture.completedFuture(20).thenApplyAsync(value -> {
                    require(Thread.currentThread() == caller);
                    callbacks++;
                    return value + 22;
                }, pool);
                returned = pool.shutdownNow();
                require(returned.size() == 2 && returned.get(0) != returned.get(1));
                require(callbacks == 0 && !supplied.isDone() && !dependent.isDone());
                gate.release();
                require(blocked.get() == 42);
                require(pool.awaitTermination(5, TimeUnit.SECONDS) && pool.isTerminated());
                prepared = true;
            } finally {
                if (!prepared) {
                    gate.release();
                    pool.shutdownNow();
                }
            }
        }
        @Override public void close() throws InterruptedException {
            gate.release();
            pool.shutdownNow();
            require(pool.awaitTermination(5, TimeUnit.SECONDS));
        }
    }

    static final class CopiesScenario implements AutoCloseable {
        final Scenario selected;
        final Gate firstGate = new Gate(), secondGate = new Gate();
        final ExecutorService first = Executors.newSingleThreadExecutor();
        final ExecutorService second = Executors.newSingleThreadExecutor();
        final Future<Integer> firstBlock, secondBlock;
        final Runnable shared;
        CopiesScenario(Scenario selected) throws InterruptedException {
            this.selected = selected;
            shared = selected.returned.get(0);
            boolean prepared = false;
            try {
                firstBlock = first.submit(firstGate::work);
                secondBlock = second.submit(secondGate::work);
                firstGate.entered(); secondGate.entered();
                first.execute(shared); second.execute(shared);
                try { selected.pool.execute(shared); throw new AssertionError("missing-rejection"); }
                catch (RejectedExecutionException expected) { }
                require(!selected.supplied.isDone() && selected.callbacks == 0);
                prepared = true;
            } finally { if (!prepared) { firstGate.release(); secondGate.release(); first.shutdownNow(); second.shutdownNow(); } }
        }
        void withdrawOne() throws InterruptedException, ExecutionException {
            List<Runnable> pending = first.shutdownNow();
            require(pending.size() == 1 && pending.get(0) == shared);
            firstGate.release(); require(firstBlock.get() == 42);
            require(first.awaitTermination(5, TimeUnit.SECONDS));
            require(!selected.supplied.isDone() && selected.callbacks == 0);
        }
        void withdrawLast() throws InterruptedException, ExecutionException {
            List<Runnable> pending = second.shutdownNow();
            require(pending.size() == 1 && pending.get(0) == shared);
            secondGate.release(); require(secondBlock.get() == 42);
            require(second.awaitTermination(5, TimeUnit.SECONDS));
            require(!selected.supplied.isDone() && selected.callbacks == 0);
        }
        @Override public void close() throws InterruptedException {
            firstGate.release(); secondGate.release(); first.shutdownNow(); second.shutdownNow();
            require(first.awaitTermination(5, TimeUnit.SECONDS) && second.awaitTermination(5, TimeUnit.SECONDS));
        }
    }

    static final class OpaqueScenario implements AutoCloseable {
        final Gate gate = new Gate();
        final ExecutorService live = Executors.newSingleThreadExecutor();
        final ExecutorService closed = Executors.newSingleThreadExecutor();
        final Future<Integer> blocked;
        final CompletableFuture<Integer> result;
        Runnable original;
        int callbacks;
        OpaqueScenario() throws InterruptedException {
            boolean prepared = false;
            try {
                closed.shutdown(); require(closed.awaitTermination(5, TimeUnit.SECONDS));
                blocked = live.submit(gate::work); gate.entered();
                result = CompletableFuture.supplyAsync(() -> { callbacks++; return 42; }, command -> {
                    original = command;
                    live.execute(command);
                    try { closed.execute(command); throw new AssertionError("missing-rejection"); }
                    catch (RejectedExecutionException expected) { }
                });
                require(!result.isDone() && callbacks == 0);
                prepared = true;
            } finally { if (!prepared) { gate.release(); live.shutdownNow(); closed.shutdownNow(); } }
        }
        void withdraw() throws InterruptedException, ExecutionException {
            List<Runnable> pending = live.shutdownNow();
            require(pending.size() == 1 && pending.get(0) == original);
            gate.release(); require(blocked.get() == 42);
            require(live.awaitTermination(5, TimeUnit.SECONDS) && !result.isDone());
        }
        void completeFromQueue() throws InterruptedException, ExecutionException {
            gate.release(); require(blocked.get() == 42);
            live.shutdown(); require(live.awaitTermination(5, TimeUnit.SECONDS));
            require(result.join() == 42 && callbacks == 1);
        }
        void replay() {
            original.run(); original.run();
            require(result.join() == 42 && callbacks == 1);
        }
        @Override public void close() throws InterruptedException {
            gate.release(); live.shutdownNow(); closed.shutdownNow();
            require(live.awaitTermination(5, TimeUnit.SECONDS) && closed.awaitTermination(5, TimeUnit.SECONDS));
        }
    }

    static final class RunningScenario implements AutoCloseable {
        final Gate gate = new Gate();
        final ExecutorService pool = Executors.newSingleThreadExecutor();
        final Gate replay = new Gate();
        final CompletableFuture<Integer> running, queued;
        Thread replayThread;
        final List<Runnable> returned;
        int callbacks;

        RunningScenario() throws InterruptedException {
            boolean prepared = false;
            try {
                running = CompletableFuture.supplyAsync(gate::work, pool);
                gate.entered();
                queued = CompletableFuture.supplyAsync(() -> { callbacks++; return replay.work(); }, pool);
                returned = pool.shutdownNow();
                require(returned.size() == 1 && callbacks == 0 && !running.isDone() && !queued.isDone());
                require(running.cancel(false) && running.isCancelled());
                prepared = true;
            } finally {
                if (!prepared) {
                    gate.release();
                    pool.shutdownNow();
                }
            }
        }
        void retireRunning() throws InterruptedException {
            gate.release();
            require(pool.awaitTermination(5, TimeUnit.SECONDS) && pool.isTerminated());
            require(running.isCancelled());
            try { running.join(); throw new AssertionError("missing-cancelled-result"); }
            catch (CancellationException expected) { }
        }
        void replayPending() throws InterruptedException {
            replayThread = new Thread(returned.get(0));
            replayThread.start();
            replay.entered();
            try { pool.execute(returned.get(0)); throw new AssertionError("missing-rejection"); }
            catch (RejectedExecutionException expected) { }
            require(!queued.isDone() && callbacks == 1);
        }
        void retireReplay() throws InterruptedException {
            replay.release();
            replayThread.join(5000);
            require(!replayThread.isAlive() && queued.join() == 42 && callbacks == 1);
            returned.get(0).run();
            require(callbacks == 1);
        }
        @Override public void close() throws InterruptedException {
            gate.release();
            replay.release();
            pool.shutdownNow();
            require(pool.awaitTermination(5, TimeUnit.SECONDS));
            if (replayThread != null) {
                replayThread.join(5000);
                require(!replayThread.isAlive());
            }
        }
    }

    /** Ordinary APIs shared unchanged by the reference JDK and signed guest. */
    static final class CachedHandoffProbe {
        final Object startup = new Object();
        final Thread[] worker = new Thread[1];
        final boolean holdStartup;
        final ExecutorService pool;
        final IllegalArgumentException callbackFailure = new IllegalArgumentException("cached-handoff-callback");
        boolean entered, released;
        int callbacks;

        CachedHandoffProbe(boolean holdStartup) {
            this.holdStartup = holdStartup;
            pool = Executors.newCachedThreadPool(command -> {
                // Refuse growth rather than pretending that a yield/sleep proves
                // an idle worker. Successful later admission must reuse this one.
                if (worker[0] != null) return null;
                worker[0] = new Thread(() -> {
                    if (this.holdStartup) {
                        synchronized (startup) {
                            entered = true; startup.notifyAll();
                            while (!released) {
                                try { startup.wait(); }
                                catch (InterruptedException consumed) { }
                            }
                        }
                        // Deliberately consume the startup stop wakeup. The pool
                        // must restore it before the already committed callback.
                        Thread.interrupted();
                    }
                    command.run();
                });
                return worker[0];
            });
        }
        int callback(int mode) {
            // This monitor also holds back the JDK callback, whose internal
            // pool lock is not the public executor monitor used by the SDK.
            synchronized (pool) {
                require(Thread.currentThread() == worker[0]);
                require(Thread.currentThread().isInterrupted() == (mode != 1));
                callbacks++;
                if (mode == 2) throw callbackFailure;
                return 42;
            }
        }
        void releaseStartup() {
            synchronized (startup) { released = true; startup.notifyAll(); }
        }
        void run(int mode) throws InterruptedException, ExecutionException {
            try {
                Future<Integer> accepted;
                if (holdStartup) {
                    accepted = pool.submit(() -> callback(mode));
                    long end = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
                    synchronized (startup) {
                        while (!entered) {
                            long left = end - System.nanoTime();
                            require(left > 0);
                            startup.wait(left / 1_000_000, (int)(left % 1_000_000));
                        }
                    }
                    require(pool.shutdownNow().isEmpty() && !accepted.isDone());
                    releaseStartup();
                } else {
                    require(pool.submit(() -> 42).get(5, TimeUnit.SECONDS) == 42);
                    accepted = null;
                    long end = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
                    while (accepted == null) {
                        synchronized (pool) {
                            try { accepted = pool.submit(() -> callback(mode)); }
                            catch (RejectedExecutionException notIdle) {
                                require(!pool.isShutdown());
                            }
                            if (accepted != null) {
                                require(!accepted.isDone() && callbacks == 0);
                                if (mode == 1) pool.shutdown();
                                else require(pool.shutdownNow().isEmpty());
                            }
                        }
                        if (accepted == null) {
                            require(System.nanoTime() - end < 0);
                            Thread.yield(); // Scheduling only, never the handoff witness.
                        }
                    }
                }
                try {
                    require(accepted.get(5, TimeUnit.SECONDS) == 42 && mode != 2);
                } catch (ExecutionException error) {
                    if (mode != 2) throw error;
                    require(error.getCause() == callbackFailure);
                }
                require(pool.awaitTermination(5, TimeUnit.SECONDS) && pool.isTerminated());
                worker[0].join(5000);
                require(!worker[0].isAlive() && callbacks == 1);
                require(pool.shutdownNow().isEmpty());
            } catch (java.util.concurrent.TimeoutException error) {
                throw new IllegalStateException("cached-handoff-deadline", error);
            } finally {
                releaseStartup();
                pool.shutdownNow();
                require(pool.awaitTermination(5, TimeUnit.SECONDS));
                if (worker[0] != null) {
                    worker[0].join(5000);
                    require(!worker[0].isAlive());
                }
            }
        }
    }

    public Long run(Long mode) {
        try {
            new CachedHandoffProbe(mode == 3).run(mode.intValue());
            if (mode == 3) {
                try (RunningScenario selected = new RunningScenario()) {
                    selected.retireRunning();
                    selected.replayPending();
                    selected.retireReplay();
                }
            } else {
                try (Scenario selected = new Scenario()) {
                    if (mode == 0) {
                        // Removed promises stay pending, but cannot retain
                        // accepted execution after their only queue is gone.
                        require(!selected.supplied.isDone() && !selected.dependent.isDone());
                    } else if (mode == 1) {
                        try (CopiesScenario copies = new CopiesScenario(selected)) {
                            copies.withdrawOne(); copies.withdrawLast();
                        }
                        for (Runnable task : selected.returned) { task.run(); task.run(); }
                        require(selected.supplied.join() == 42 && selected.dependent.join() == 42);
                        require(selected.callbacks == 2);
                        try (OpaqueScenario opaque = new OpaqueScenario()) { opaque.completeFromQueue(); }
                    } else if (mode == 2) {
                        require(selected.supplied.cancel(false));
                        for (Runnable task : selected.returned) task.run();
                        require(selected.supplied.isCancelled() && selected.dependent.join() == 42);
                        require(selected.callbacks == 1);
                    } else throw new IllegalArgumentException("shutdown-now-mode");
                }
            }
            return 42L;
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException(error);
        } catch (ExecutionException error) { throw new IllegalStateException(error); }
    }
}
