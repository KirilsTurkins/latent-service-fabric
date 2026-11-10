package dev.latent.guest.runtime;

import dev.latent.generated.Bindings;
import java.util.ArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Strict host source ledger; this fixture is never a Wasm runtime input. */
public final class Activation {
    private static final ArrayList<ManagedPool> pools = new ArrayList<>();
    private static final ArrayList<Thread> workers = new ArrayList<>();
    private static int queued, executors, queuedAttempts, queuedRegistrations;
    // Disabled by default; individual private controls may model a fixed cap.
    private static int queuedLimit = Integer.MAX_VALUE;
    private static volatile boolean closing;
    private static boolean poisoned;
    private static Lease failedQueued, lastFailedQueued, lastFailedExecutor;
    public static volatile String failQueuedSettlement;
    public static volatile CountDownLatch queuedSettlementEntered, queuedSettlementRelease;
    public static volatile Runnable onQueuedSettlement;
    public static String denyNext;
    public static String failManagedStart;
    public static boolean failManage;
    public static String failExecutorSettlement;
    public static IllegalStateException startFailure;
    public static volatile Thread lastWorker, retainedStart;
    public static volatile ManagedPool lastPool;
    public static volatile CountDownLatch executorSettlementEntered, executorSettlementRelease;
    private static int executorAttempts, failedOwnerLinks;
    public static volatile Throwable lastWorkerFailure;

    public interface ManagedPool {
        boolean hasPendingWork();
        boolean isRetired();
        void closeAtRoot();
    }
    public static final class Lease implements AutoCloseable {
        private final Bindings.LatentRuntimeActivationOwnerKind kind;
        private boolean closed;
        private boolean hostSettled;
        Lease(Bindings.LatentRuntimeActivationOwnerKind kind) { this.kind = kind; }
        @Override public void close() {
            if (kind == Bindings.LatentRuntimeActivationOwnerKind.Executor
                    && Thread.currentThread() == lastWorker && executorSettlementEntered != null) {
                executorSettlementEntered.countDown();
                try {
                    if (!executorSettlementRelease.await(4, TimeUnit.SECONDS))
                        throw new AssertionError("executor-settlement-release-timeout");
                } catch (InterruptedException error) { throw new AssertionError(error); }
            }
            synchronized (Activation.class) {
                if (kind == Bindings.LatentRuntimeActivationOwnerKind.Executor) {
                    executorAttempts++;
                    if (hostSettled) throw new AssertionError("duplicate-host-settlement");
                    if (failExecutorSettlement != null) {
                        String selected = failExecutorSettlement; failExecutorSettlement = null;
                        lastFailedExecutor = this;
                        if (selected.equals("lost")) { hostSettled = true; executors--; }
                        throw new IllegalStateException("source-executor-settlement-" + selected);
                    }
                }
                if (closed) throw new AssertionError("duplicate-source-owner-retirement");
                if (kind == Bindings.LatentRuntimeActivationOwnerKind.QueuedWork) {
                    queuedAttempts++;
                    if (hostSettled) throw new AssertionError("duplicate-host-settlement");
                    if (onQueuedSettlement != null) onQueuedSettlement.run();
                    if (queuedSettlementEntered != null) {
                        queuedSettlementEntered.countDown();
                        try {
                            if (!queuedSettlementRelease.await(4, TimeUnit.SECONDS))
                                throw new AssertionError("settlement-release-timeout");
                        } catch (InterruptedException error) { throw new AssertionError(error); }
                    }
                    if (failQueuedSettlement != null) {
                        String selected = failQueuedSettlement;
                        failQueuedSettlement = null;
                        lastFailedQueued = this;
                        if (selected.equals("lost")) { hostSettled = true; queued--; }
                        throw new IllegalStateException("source-queued-settlement-" + selected);
                    }
                }
                closed = true;
                if (kind == Bindings.LatentRuntimeActivationOwnerKind.QueuedWork) queued--;
                else executors--;
                if (queued < 0 || executors < 0) throw new AssertionError("negative-source-owner-count");
            }
        }
    }
    public static synchronized Lease owner(Bindings.LatentRuntimeActivationOwnerKind kind) {
        if (kind == Bindings.LatentRuntimeActivationOwnerKind.QueuedWork) queuedRegistrations++;
        if (poisoned) throw new IllegalStateException("source-poisoned-store");
        if (kind.name().equals(denyNext)) {
            denyNext = null;
            throw new IllegalStateException("source-owner-admission-denied");
        }
        if (kind == Bindings.LatentRuntimeActivationOwnerKind.QueuedWork) {
            if (queued >= queuedLimit) throw new IllegalStateException("source-queued-capacity");
            queued++;
        }
        else executors++;
        return new Lease(kind);
    }
    public static synchronized void manage(ManagedPool pool) {
        lastPool = pool;
        if (failManage) { failManage = false; throw startFailure; }
        pools.add(pool);
    }
    public static synchronized boolean poolRegistered(ManagedPool pool) { return pools.contains(pool); }
    public static void startManaged(Thread worker, ManagedPool pool) {
        lastWorker = worker;
        String failure = failManagedStart; failManagedStart = null;
        if ("before".equals(failure)) throw startFailure;
        synchronized (Activation.class) { workers.add(worker); }
        if ("uncertain".equals(failure)) { retainedStart = worker; throw startFailure; }
        if (failure != null && failure.startsWith("finished-"))
            worker.setUncaughtExceptionHandler((thread, error) -> lastWorkerFailure = error);
        worker.start();
        if ("accepted".equals(failure) || failure != null && failure.startsWith("finished-")) {
            long end = System.nanoTime() + 4_000_000_000L;
            while (worker.getState() != Thread.State.WAITING && System.nanoTime() < end) {
                try { Thread.sleep(1); } catch (InterruptedException error) { throw new AssertionError(error); }
            }
            if (worker.getState() != Thread.State.WAITING) throw new AssertionError("source-worker-not-waiting");
            if (failure.startsWith("finished-")) {
                pool.closeAtRoot();
                try { worker.join(5000); } catch (InterruptedException error) { throw new AssertionError(error); }
                if (worker.isAlive() || (failure.equals("finished-ok") ? lastWorkerFailure != null : lastWorkerFailure == null))
                    throw new AssertionError("source-worker-cleanup-missing");
            }
            throw startFailure;
        }
    }
    public static boolean alive(Thread worker) { return worker == retainedStart || worker.isAlive(); }
    public static synchronized int executorAttempts() { return executorAttempts; }
    public static synchronized int failedOwnerLinks() { return failedOwnerLinks; }
    public static synchronized int executors() { return executors; }
    // The separate real-Activation control verifies physical-owner retirement.
    public static void unmanageRetired(ManagedPool pool) { }
    public static boolean closing() { return closing; }
    public static boolean acceptedContinuation() { return false; }
    public static void checkpoint() { Thread.yield(); }
    public static synchronized int queued() { return queued; }
    public static synchronized int queuedAttempts() { return queuedAttempts; }
    public static synchronized int queuedRegistrations() { return queuedRegistrations; }
    public static synchronized void setQueuedLimit(int limit) {
        if (limit < 1 || queued != 0) throw new IllegalStateException("source-queued-limit");
        queuedLimit = limit;
    }
    public static synchronized boolean poisoned() { return poisoned; }
    public static synchronized boolean retainedFailedQueued() {
        return failedQueued != null && failedQueued == lastFailedQueued;
    }
    public static synchronized boolean retainedFailedExecutor() {
        return failedQueued != null && failedQueued == lastFailedExecutor;
    }
    public static synchronized void fenceUncertainQueuedWorkSettlement(Lease owner) {
        if (failedQueued != null) throw new AssertionError("duplicate-failed-owner");
        poisoned = true; failedQueued = owner; failedOwnerLinks++;
    }
    public static synchronized void fenceUncertainResultSettlement() { poisoned = true; }
    public static synchronized boolean retireIfIdle(ManagedPool pool) {
        if (pool.hasPendingWork()) return false;
        pool.closeAtRoot();
        return true;
    }
    public static void joinWorkers() throws Exception {
        Thread[] selected;
        synchronized (Activation.class) { selected = workers.toArray(new Thread[0]); }
        for (Thread worker : selected) {
            worker.join(5000);
            if (worker.isAlive()) throw new AssertionError("source-timer-worker-not-retired");
        }
    }
    public static synchronized int owners() { return queued + executors; }
    public static boolean pending() { for (ManagedPool pool : pools) if (pool.hasPendingWork()) return true; return false; }
    public static void cleanup() throws Exception {
        long started = System.nanoTime();
        while (pending()) {
            if (System.nanoTime() - started > 5_000_000_000L) throw new AssertionError("source-pending-timer-work");
            Thread.sleep(1);
        }
        closing = true;
        for (ManagedPool pool : pools) pool.closeAtRoot();
        for (Thread worker : workers) {
            worker.join(5000);
            if (worker.isAlive()) throw new AssertionError("source-timer-worker-not-retired");
        }
        if (owners() != 0) throw new AssertionError("source-timer-owners-not-retired");
    }
}
