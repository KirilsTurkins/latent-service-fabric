package dev.latent.guest.runtime;

import dev.latent.generated.Bindings;
import java.util.ArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Strict host source ledger; this fixture is never a Wasm runtime input. */
public final class Activation {
    private static final ArrayList<ManagedPool> pools = new ArrayList<>();
    private static final ArrayList<Thread> workers = new ArrayList<>();
    private static int queued, executors, queuedAttempts;
    private static volatile boolean closing;
    private static boolean poisoned;
    private static Lease failedQueued, lastFailedQueued;
    public static volatile String failQueuedSettlement;
    public static volatile CountDownLatch queuedSettlementEntered, queuedSettlementRelease;
    public static volatile Runnable onQueuedSettlement;
    public static String denyNext;

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
            synchronized (Activation.class) {
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
        if (poisoned) throw new IllegalStateException("source-poisoned-store");
        if (kind.name().equals(denyNext)) {
            denyNext = null;
            throw new IllegalStateException("source-owner-admission-denied");
        }
        if (kind == Bindings.LatentRuntimeActivationOwnerKind.QueuedWork) queued++;
        else executors++;
        return new Lease(kind);
    }
    public static synchronized void manage(ManagedPool pool) { pools.add(pool); }
    public static synchronized void startManaged(Thread worker, ManagedPool pool) { workers.add(worker); worker.start(); }
    public static boolean alive(Thread worker) { return worker.isAlive(); }
    // The separate real-Activation control verifies physical-owner retirement.
    public static void unmanageRetired(ManagedPool pool) { }
    public static boolean closing() { return closing; }
    public static boolean acceptedContinuation() { return false; }
    public static void checkpoint() { Thread.yield(); }
    public static synchronized int queued() { return queued; }
    public static synchronized int queuedAttempts() { return queuedAttempts; }
    public static synchronized boolean poisoned() { return poisoned; }
    public static synchronized boolean retainedFailedQueued() {
        return failedQueued != null && failedQueued == lastFailedQueued;
    }
    public static synchronized void fenceUncertainQueuedWorkSettlement(Lease owner) {
        if (failedQueued != null) throw new AssertionError("duplicate-failed-owner");
        poisoned = true; failedQueued = owner;
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
