package dev.latent.guest.runtime;

import dev.latent.generated.Bindings;
import java.util.ArrayList;
import java.util.concurrent.Executor;
import java.util.function.Supplier;

/** Test-only linear observations for actual port source, not the native ledger. */
public final class Activation {
    private static final int[] owners = new int[3];
    private static final int[] closeAttempts = new int[3];
    private static final int[] admissions = new int[3];
    private static final ArrayList<ManagedPool> pools = new ArrayList<>();
    private static final java.util.IdentityHashMap<Thread, ManagedPool> managed = new java.util.IdentityHashMap<>();
    public static String denyNext;
    public static int denyMatchesAfter;
    public static String denyCloseNext;
    public static int denyCloseAfter;
    public static String loseCloseAckNext;
    public static int loseCloseAckAfter;
    public static String closeObservationKind;
    public static Runnable closeObservation;
    public static String admissionObservationKind;
    public static Runnable admissionObservation;
    public static volatile boolean poisoned;
    private static Lease lastFailedLease;
    private static Lease retainedFailedQueued;
    public static boolean retainFailedStart;
    public interface ManagedPool { boolean hasPendingWork(); boolean isRetired(); void closeAtRoot(); }
    public static final class Lease implements AutoCloseable {
        private final int kind;
        private boolean closed;
        private int attempts;
        Lease(int kind) { this.kind = kind; }
        @Override public void close() {
            synchronized (Activation.class) {
                closeAttempts[kind]++;
                attempts++;
                if (closed || owners[kind] <= 0) throw new AssertionError("source-duplicate-owner-retirement");
                if (Bindings.LatentRuntimeActivationOwnerKind.values()[kind].name().equals(closeObservationKind)) {
                    Runnable observation = closeObservation; closeObservation = null; closeObservationKind = null;
                    if (observation != null) observation.run();
                }
                if (Bindings.LatentRuntimeActivationOwnerKind.values()[kind].name().equals(loseCloseAckNext)) {
                    if (loseCloseAckAfter > 0) loseCloseAckAfter--;
                    else {
                        loseCloseAckNext = null; lastFailedLease = this; closed = true; owners[kind]--;
                        throw new IllegalStateException("source-owner-settlement-ack-unknown");
                    }
                }
                if (Bindings.LatentRuntimeActivationOwnerKind.values()[kind].name().equals(denyCloseNext)) {
                    if (denyCloseAfter > 0) denyCloseAfter--;
                    else {
                        denyCloseNext = null;
                        lastFailedLease = this;
                        throw new IllegalStateException("source-owner-settlement-denied");
                    }
                }
                closed = true; owners[kind]--;
            }
        }
    }
    public static synchronized Lease owner(Bindings.LatentRuntimeActivationOwnerKind kind) {
        if (poisoned) throw new IllegalStateException("activation-runtime-poisoned-store");
        if (kind.name().equals(denyNext)) {
            if (denyMatchesAfter > 0) denyMatchesAfter--;
            else {
                denyNext = null;
                throw new IllegalStateException("source-owner-admission-denied");
            }
        }
        owners[kind.ordinal()]++; admissions[kind.ordinal()]++;
        if (kind.name().equals(admissionObservationKind)) {
            Runnable observation = admissionObservation; admissionObservation = null; admissionObservationKind = null;
            if (observation != null) observation.run();
        }
        return new Lease(kind.ordinal());
    }
    public static synchronized int count(Bindings.LatentRuntimeActivationOwnerKind kind) { return owners[kind.ordinal()]; }
    public static synchronized int closeAttempts(Bindings.LatentRuntimeActivationOwnerKind kind) { return closeAttempts[kind.ordinal()]; }
    public static synchronized int admissions(Bindings.LatentRuntimeActivationOwnerKind kind) { return admissions[kind.ordinal()]; }
    public static boolean retainsFailedQueued() { return retainedFailedQueued != null && retainedFailedQueued == lastFailedLease; }
    public static synchronized int failedLeaseAttempts() { return lastFailedLease == null ? 0 : lastFailedLease.attempts; }
    public static void fenceUncertainResultSettlement() { poisoned = true; }
    public static void fenceUncertainQueuedWorkSettlement(Lease owner) { poisoned = true; retainedFailedQueued = owner; }
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
