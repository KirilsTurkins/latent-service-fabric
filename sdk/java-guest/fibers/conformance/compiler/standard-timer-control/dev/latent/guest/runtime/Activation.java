package dev.latent.guest.runtime;

import dev.latent.generated.Bindings;
import java.util.ArrayList;

/** Strict host source ledger; this fixture is never a Wasm runtime input. */
public final class Activation {
    private static final ArrayList<ManagedPool> pools = new ArrayList<>();
    private static final ArrayList<Thread> workers = new ArrayList<>();
    private static int queued, executors;
    private static volatile boolean closing;
    public static String denyNext;

    public interface ManagedPool {
        boolean hasPendingWork();
        void closeAtRoot();
    }
    public static final class Lease implements AutoCloseable {
        private final Bindings.LatentRuntimeActivationOwnerKind kind;
        private boolean closed;
        Lease(Bindings.LatentRuntimeActivationOwnerKind kind) { this.kind = kind; }
        @Override public void close() {
            synchronized (Activation.class) {
                if (closed) throw new AssertionError("duplicate-source-owner-retirement");
                closed = true;
                if (kind == Bindings.LatentRuntimeActivationOwnerKind.QueuedWork) queued--;
                else executors--;
                if (queued < 0 || executors < 0) throw new AssertionError("negative-source-owner-count");
            }
        }
    }
    public static synchronized Lease owner(Bindings.LatentRuntimeActivationOwnerKind kind) {
        if (kind.name().equals(denyNext)) {
            denyNext = null;
            throw new IllegalStateException("source-owner-admission-denied");
        }
        if (kind == Bindings.LatentRuntimeActivationOwnerKind.QueuedWork) queued++;
        else executors++;
        return new Lease(kind);
    }
    public static synchronized void manage(ManagedPool pool) { pools.add(pool); }
    public static synchronized void startManaged(Thread worker) { workers.add(worker); worker.start(); }
    public static boolean closing() { return closing; }
    public static boolean acceptedContinuation() { return false; }
    public static void checkpoint() { Thread.yield(); }
    public static synchronized int queued() { return queued; }
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
