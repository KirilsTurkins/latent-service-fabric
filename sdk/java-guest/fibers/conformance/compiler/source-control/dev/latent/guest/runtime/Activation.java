package dev.latent.guest.runtime;

import dev.latent.generated.Bindings;
import java.util.concurrent.Executor;
import java.util.concurrent.TimeUnit;
import java.util.function.Supplier;

/** Private, strict linear ledger for host source controls. Never a guest runtime. */
public final class Activation {
    private static Executor pool;
    private static int queued;
    private static int results;
    public static String denyNext;

    public static synchronized Executor defaultAsyncExecutor(Supplier<Executor> factory) {
        if (pool == null) pool = factory.get();
        return pool;
    }
    public static final class Lease implements AutoCloseable {
        private final Bindings.LatentRuntimeActivationOwnerKind kind;
        private boolean closed;
        Lease(Bindings.LatentRuntimeActivationOwnerKind kind) { this.kind = kind; }
        @Override public void close() {
            synchronized (Activation.class) {
                if (closed) throw new AssertionError("duplicate-physical-retirement");
                closed = true;
                if (kind == Bindings.LatentRuntimeActivationOwnerKind.QueuedWork) queued--;
                else results--;
                if (queued < 0 || results < 0) throw new AssertionError("negative-owner-count");
            }
        }
    }
    public static synchronized Lease owner(Bindings.LatentRuntimeActivationOwnerKind kind) {
        if (kind.name().equals(denyNext)) {
            denyNext = null;
            throw new IllegalStateException("source-control-admission-denied");
        }
        if (kind == Bindings.LatentRuntimeActivationOwnerKind.QueuedWork) queued++;
        else results++;
        return new Lease(kind);
    }
    public static synchronized int queuedOwners() { return queued; }
    public static synchronized int resultOwners() { return results; }
    public static synchronized int owners() { return queued + results; }
    public static void cleanup() throws Exception {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
        while (owners() != 0 && System.nanoTime() < deadline) Thread.sleep(1);
        if (owners() != 0) throw new AssertionError("source-control-unretired-owner");
        dev.latent.guest.runtime.concurrent.Executors.cleanup();
        pool = null;
    }
}
