package dev.latent.guest.runtime;

import dev.latent.generated.Bindings;
import java.util.ArrayList;
import java.util.concurrent.Executor;
import java.util.function.Supplier;

/** Test-only linear observations for actual port source, not the native ledger. */
public final class Activation {
    private static final int[] owners = new int[3];
    private static final ArrayList<ManagedPool> pools = new ArrayList<>();
    private static final java.util.IdentityHashMap<Thread, ManagedPool> managed = new java.util.IdentityHashMap<>();
    public static String denyNext;
    public static int denyMatchesAfter;
    public static String denyCloseNext;
    public static int denyCloseAfter;
    public static boolean retainFailedStart;
    public interface ManagedPool { boolean hasPendingWork(); boolean isRetired(); void closeAtRoot(); }
    public static final class Lease implements AutoCloseable {
        private final int kind;
        private boolean closed;
        Lease(int kind) { this.kind = kind; }
        @Override public void close() {
            synchronized (Activation.class) {
                if (closed || owners[kind] <= 0) throw new AssertionError("source-duplicate-owner-retirement");
                if (Bindings.LatentRuntimeActivationOwnerKind.values()[kind].name().equals(denyCloseNext)) {
                    if (denyCloseAfter > 0) denyCloseAfter--;
                    else {
                        denyCloseNext = null;
                        throw new IllegalStateException("source-owner-settlement-denied");
                    }
                }
                closed = true; owners[kind]--;
            }
        }
    }
    public static synchronized Lease owner(Bindings.LatentRuntimeActivationOwnerKind kind) {
        if (kind.name().equals(denyNext)) {
            if (denyMatchesAfter > 0) denyMatchesAfter--;
            else {
                denyNext = null;
                throw new IllegalStateException("source-owner-admission-denied");
            }
        }
        owners[kind.ordinal()]++;
        return new Lease(kind.ordinal());
    }
    public static synchronized int count(Bindings.LatentRuntimeActivationOwnerKind kind) { return owners[kind.ordinal()]; }
    public static synchronized void manage(ManagedPool pool) { pools.add(pool); }
    public static void startManaged(Thread worker, ManagedPool pool) {
        synchronized (Activation.class) {
            if (managed.containsKey(worker)) throw new IllegalThreadStateException();
            managed.put(worker, pool);
        }
        try { worker.start(); }
        catch (Throwable error) {
            synchronized (Activation.class) { if (!retainFailedStart) managed.remove(worker); }
            throw error;
        }
    }
    public static synchronized boolean ownsManaged(Thread worker, ManagedPool pool) {
        return managed.get(worker) == pool && (retainFailedStart || worker.isAlive());
    }
    public static synchronized boolean runningManaged(Thread worker, ManagedPool pool) {
        return managed.get(worker) == pool && worker.isAlive();
    }
    public static synchronized boolean alive(Thread worker) {
        return managed.containsKey(worker) && (retainFailedStart || worker.isAlive());
    }
    public static synchronized boolean recorded(Thread worker, ManagedPool pool) { return managed.get(worker) == pool; }
    // The separate real-Activation control verifies physical-owner retirement.
    public static void unmanageRetired(ManagedPool pool) { }
    public static boolean closing() { return false; }
    public static boolean acceptedContinuation() { return false; }
    public static void checkpoint() { Thread.yield(); }
    public static Executor defaultAsyncExecutor(Supplier<Executor> factory) { return factory.get(); }
    public static void idle() {
        for (ManagedPool pool : pools) if (pool.hasPendingWork()) throw new AssertionError("source-pending-work");
        synchronized (Activation.class) {
            for (int count : owners) if (count != 0) throw new AssertionError("source-owner-still-held");
        }
    }
}
