package dev.latent.guest.runtime.concurrent;

import dev.latent.generated.Bindings;
import dev.latent.guest.runtime.Activation;
import java.util.Objects;
import java.util.concurrent.Callable;
import java.util.concurrent.CancellationException;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/** Real pending execution, logical cancellation, and physical runner ownership. */
public class FutureTask<V> implements java.util.concurrent.RunnableFuture<V> {
    // Application code may synchronize on a FutureTask independently of its
    // completion and ownership state.
    final Object stateLock = new Object();
    private Callable<V> callable;
    private V value;
    private Throwable failure;
    // A failed task may have a null cause through the protected JDK method.
    private boolean failed;
    private boolean completed;
    private boolean cancelled;
    private Thread runner;
    private Activation.Lease owner;
    private boolean resultSettlementAttempted;
    private int queueCopies;
    private boolean pendingRun;
    private int internalPhysicalClaims;

    public FutureTask(Callable<V> callable) { this.callable = Objects.requireNonNull(callable); }
    public FutureTask(Runnable runnable, V result) {
        Objects.requireNonNull(runnable);
        this.callable = () -> { runnable.run(); return result; };
    }
    private void requireCertainResultOwner() {
        if (resultSettlementAttempted)
            throw new IllegalStateException("activation-future-result-settlement-uncertain");
    }
    boolean accept() {
        synchronized (stateLock) {
            requireCertainResultOwner();
            if (completed || owner != null) return false;
            owner = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.Result);
            return true;
        }
    }
    boolean acceptQueueCopy() {
        synchronized (stateLock) {
            requireCertainResultOwner();
            if (completed) return false;
            if (queueCopies == Integer.MAX_VALUE) throw new java.util.concurrent.RejectedExecutionException("activation-future-queue-copies");
            accept();
            queueCopies++;
            return true;
        }
    }
    final boolean hasQueueCopies() { synchronized (stateLock) { return queueCopies != 0; } }
    void removeQueueCopy(boolean removed) {
        synchronized (stateLock) {
            if (queueCopies <= 0) throw new IllegalStateException("activation-future-queue-copy");
            queueCopies--;
            if (!removed && !completed && runner == null) pendingRun = true;
            // A completed physical run owns its original finally. A subclass run
            // which leaves its future pending is not proof of harmless idle work.
            if (removed && queueCopies == 0 && runner == null && !pendingRun && internalPhysicalClaims == 0 && owner != null) {
                settleResultOnce();
            }
        }
    }
    // Package-internal final operations cannot dispatch into application code
    // while this future's ownership monitor is held.
    final void beginInternalPhysicalClaim() {
        synchronized (stateLock) {
            if (internalPhysicalClaims == Integer.MAX_VALUE)
                throw new java.util.concurrent.RejectedExecutionException("activation-future-physical-claims");
            internalPhysicalClaims++;
        }
    }
    final boolean hasInternalPhysicalClaim() { synchronized (stateLock) { return internalPhysicalClaims != 0; } }
    final void endInternalPhysicalClaim() {
        synchronized (stateLock) {
            if (internalPhysicalClaims <= 0) throw new IllegalStateException("activation-future-physical-claim");
            internalPhysicalClaims--;
            if (runner == null && internalPhysicalClaims == 0 && owner != null
                    && (completed || queueCopies == 0 && !pendingRun)) {
                settleResultOnce();
            }
        }
    }
    private void settleResultOnce() {
        if (owner == null || resultSettlementAttempted) return;
        // The host may have settled even when its acknowledgement is lost.
        // Mark before the call, retain the owner on failure, and never retry it.
        resultSettlementAttempted = true;
        try {
            owner.close(); owner = null; resultSettlementAttempted = false;
        } catch (Throwable error) {
            Activation.fenceUncertainResultSettlement();
            throw error;
        }
    }
    private void releaseIfPhysicalComplete() {
        if (runner == null && completed && internalPhysicalClaims == 0 && owner != null) settleResultOnce();
    }
    @Override public boolean cancel(boolean interrupt) {
        boolean notifyCompletion = false;
        try {
            synchronized (stateLock) {
                if (completed) return false;
                cancelled = completed = true;
                try {
                    if (interrupt && runner != null) runner.interrupt();
                } finally {
                    // A custom Thread.interrupt() may throw before or after
                    // delivery. Cancellation still wakes waiters and runs done().
                    if (runner == null) callable = null;
                    stateLock.notifyAll();
                    releaseIfPhysicalComplete();
                    // Preserve fail-closed behavior if owner settlement fails.
                    notifyCompletion = true;
                }
            }
        } finally {
            if (notifyCompletion) done();
        }
        return true;
    }
    @Override public boolean isCancelled() { synchronized (stateLock) { return cancelled; } }
    @Override public boolean isDone() { synchronized (stateLock) { return completed; } }
    @Override public void run() {
        synchronized (stateLock) {
            if (completed || runner != null) return;
            accept();
            runner = Thread.currentThread();
        }
        try {
            V result;
            try { result = callable.call(); }
            catch (Throwable error) { setException(error); return; }
            // A subclass done() failure belongs to the executing thread's
            // uncaught-exception handler, not to the already completed result.
            set(result);
        }
        finally {
            synchronized (stateLock) { runner = null; callable = null; releaseIfPhysicalComplete(); }
        }
    }
    /** A recurring owner stays pending until a later completion or cancellation. */
    protected boolean runAndReset() {
        synchronized (stateLock) {
            if (completed || runner != null) return false;
            accept();
            runner = Thread.currentThread();
        }
        boolean ran = false;
        try {
            try { callable.call(); ran = true; }
            catch (Throwable error) { setException(error); }
        } finally {
            synchronized (stateLock) { runner = null; if (completed) callable = null; releaseIfPhysicalComplete(); }
        }
        synchronized (stateLock) { return ran && !completed; }
    }
    protected void set(V result) {
        synchronized (stateLock) {
            if (completed) return;
            value = result;
            completed = true;
            stateLock.notifyAll();
            releaseIfPhysicalComplete();
        }
        done();
    }
    protected void setException(Throwable error) {
        synchronized (stateLock) {
            if (completed) return;
            failure = error;
            failed = true;
            completed = true;
            stateLock.notifyAll();
            releaseIfPhysicalComplete();
        }
        done();
    }
    protected void done() { }
    @Override public V get() throws InterruptedException, ExecutionException {
        synchronized (stateLock) {
            if (!completed) {
                if (Thread.interrupted()) throw new InterruptedException();
                while (!completed) stateLock.wait();
            }
            return report();
        }
    }
    @Override public V get(long timeout, TimeUnit unit) throws InterruptedException, ExecutionException, TimeoutException {
        long nanos = Objects.requireNonNull(unit).toNanos(timeout);
        long started = System.nanoTime();
        synchronized (stateLock) {
            if (!completed) {
                if (Thread.interrupted()) throw new InterruptedException();
                if (nanos <= 0) throw new TimeoutException();
                while (!completed) {
                    long remaining = nanos - (System.nanoTime() - started);
                    if (remaining <= 0) throw new TimeoutException();
                    stateLock.wait(remaining / 1_000_000, (int)(remaining % 1_000_000));
                }
            }
            return report();
        }
    }
    private V report() throws ExecutionException {
        if (cancelled) throw new CancellationException();
        if (failed) throw new ExecutionException(failure);
        return value;
    }

    @Override public V resultNow() {
        synchronized (stateLock) {
            if (!completed || cancelled || failed) throw new IllegalStateException();
            return value;
        }
    }
    @Override public Throwable exceptionNow() {
        synchronized (stateLock) {
            if (!completed || cancelled || !failed) throw new IllegalStateException();
            return failure;
        }
    }
    @Override public java.util.concurrent.Future.State state() {
        synchronized (stateLock) {
            if (!completed) return java.util.concurrent.Future.State.RUNNING;
            if (cancelled) return java.util.concurrent.Future.State.CANCELLED;
            return failed ? java.util.concurrent.Future.State.FAILED : java.util.concurrent.Future.State.SUCCESS;
        }
    }
}
