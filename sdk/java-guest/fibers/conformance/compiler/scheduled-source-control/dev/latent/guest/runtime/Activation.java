package dev.latent.guest.runtime;

import dev.latent.generated.Bindings;
import java.util.ArrayList;
import java.util.concurrent.Executor;
import java.util.function.Supplier;

/** Test-only linear observations for actual port source, not the native ledger. */
public final class Activation {
    private static final int[] owners = new int[3];
    private static final ArrayList<ManagedPool> pools = new ArrayList<>();
    public static String denyNext;
    public interface ManagedPool { boolean hasPendingWork(); void closeAtRoot(); }
    public static final class Lease implements AutoCloseable {
        private final int kind;
        private boolean closed;
        Lease(int kind) { this.kind = kind; }
        @Override public void close() {
            synchronized (Activation.class) {
                if (closed || owners[kind] <= 0) throw new AssertionError("source-duplicate-owner-retirement");
                closed = true; owners[kind]--;
            }
        }
    }
    public static synchronized Lease owner(Bindings.LatentRuntimeActivationOwnerKind kind) {
        if (kind.name().equals(denyNext)) {
            denyNext = null;
            throw new IllegalStateException("source-owner-admission-denied");
        }
        owners[kind.ordinal()]++;
        return new Lease(kind.ordinal());
    }
    public static synchronized int count(Bindings.LatentRuntimeActivationOwnerKind kind) { return owners[kind.ordinal()]; }
    public static synchronized void manage(ManagedPool pool) { pools.add(pool); }
    public static void startManaged(Thread worker) { worker.start(); }
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
