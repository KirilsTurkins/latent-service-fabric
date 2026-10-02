package dev.latent.guest.runtime;

import dev.latent.generated.Bindings;
import java.util.ArrayList;
import java.util.concurrent.Executor;
import java.util.concurrent.TimeUnit;
import java.util.function.Supplier;

/** Private, strict linear ledger for host source controls. Never a guest runtime. */
public final class Activation {
    private static Executor pool;
    private static int queued;
    private static int results;
    private static int executors;
    private static boolean closing;
    private static final ArrayList<Thread> deferred = new ArrayList<>();
    private static final ArrayList<Thread> managed = new ArrayList<>();
    public static volatile String denyNext;

    public interface ManagedPool {
        boolean hasPendingWork();
        void closeAtRoot();
    }
    public static synchronized void manage(ManagedPool pool) { admission(); }
    public static synchronized boolean acceptedContinuation() {
        return deferred.contains(Thread.currentThread()) || managed.contains(Thread.currentThread());
    }
    public static synchronized boolean closing() { return closing; }
    public static void checkpoint() { Thread.yield(); }
    public static synchronized void startManaged(Thread thread) {
        admission();
        managed.add(thread);
        try { thread.start(); }
        catch (Throwable error) { managed.remove(thread); throw error; }
    }

    public static synchronized Executor defaultAsyncExecutor(Supplier<Executor> factory) {
        admission();
        if (pool == null) pool = factory.get();
        return pool;
    }
    private static void admission() {
        if (closing && !acceptedContinuation())
            throw new IllegalStateException("source-control-root-admission-closed");
    }
    public static synchronized void startDeferred(Thread thread) {
        admission();
        if ("Task".equals(denyNext)) {
            denyNext = null;
            throw new IllegalStateException("source-control-task-admission-denied");
        }
        if (deferredOwners() >= 4) throw new IllegalStateException("source-control-original-task-capacity");
        deferred.add(thread);
        try { thread.start(); }
        catch (Throwable error) { deferred.remove(thread); throw error; }
    }
    public static synchronized int deferredOwners() {
        int count = 0;
        for (Thread thread : deferred) if (thread.getState() != Thread.State.TERMINATED) count++;
        return count;
    }
    public static synchronized Thread deferredForControl() { return deferred.getLast(); }
    public static synchronized void closeForControl() { closing = true; }
    public static final class Lease implements AutoCloseable {
        private final Bindings.LatentRuntimeActivationOwnerKind kind;
        private boolean closed;
        Lease(Bindings.LatentRuntimeActivationOwnerKind kind) { this.kind = kind; }
        @Override public void close() {
            synchronized (Activation.class) {
                if (closed) throw new AssertionError("duplicate-physical-retirement");
                closed = true;
                if (kind == Bindings.LatentRuntimeActivationOwnerKind.QueuedWork) queued--;
                else if (kind == Bindings.LatentRuntimeActivationOwnerKind.Result) results--;
                else executors--;
                if (queued < 0 || results < 0 || executors < 0) throw new AssertionError("negative-owner-count");
            }
        }
    }
    public static synchronized Lease owner(Bindings.LatentRuntimeActivationOwnerKind kind) {
        admission();
        if (kind.name().equals(denyNext)) {
            denyNext = null;
            throw new IllegalStateException("source-control-admission-denied");
        }
        if (kind == Bindings.LatentRuntimeActivationOwnerKind.QueuedWork && queued >= 8
                || kind == Bindings.LatentRuntimeActivationOwnerKind.Result && results >= 8
                || kind == Bindings.LatentRuntimeActivationOwnerKind.Executor && executors >= 3)
            throw new IllegalStateException("source-control-original-owner-capacity");
        if (kind == Bindings.LatentRuntimeActivationOwnerKind.QueuedWork) queued++;
        else if (kind == Bindings.LatentRuntimeActivationOwnerKind.Result) results++;
        else executors++;
        return new Lease(kind);
    }
    public static synchronized int queuedOwners() { return queued; }
    public static synchronized int resultOwners() { return results; }
    public static synchronized int executorOwners() { return executors; }
    public static synchronized int owners() { return queued + results + executors; }
    public static void cleanup() throws Exception {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
        while (owners() != 0 && System.nanoTime() < deadline) Thread.sleep(1);
        if (owners() != 0) throw new AssertionError("source-control-unretired-owner");
        for (Thread thread : deferred) {
            thread.join(Math.max(1, TimeUnit.NANOSECONDS.toMillis(deadline - System.nanoTime())));
            if (thread.isAlive()) throw new AssertionError("source-control-unretired-deferred-thread");
        }
        deferred.clear();
        for (Thread thread : managed) {
            thread.join(Math.max(1, TimeUnit.NANOSECONDS.toMillis(deadline - System.nanoTime())));
            if (thread.isAlive()) throw new AssertionError("source-control-unretired-managed-thread");
        }
        managed.clear();
        dev.latent.guest.runtime.concurrent.Executors.cleanup();
        pool = null;
        closing = false;
    }
}
