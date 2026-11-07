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
    private Callable<V> callable;
    private V value;
    private Throwable failure;
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
    synchronized boolean accept() {
        if (resultSettlementAttempted)
            throw new IllegalStateException("activation-future-result-settlement-uncertain");
        if (completed || owner != null) return false;
        owner = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.Result);
        return true;
    }
    synchronized boolean acceptQueueCopy() {
        if (completed) return false;
        if (queueCopies == Integer.MAX_VALUE) throw new java.util.concurrent.RejectedExecutionException("activation-future-queue-copies");
        accept();
        queueCopies++;
        return true;
    }
    final synchronized boolean hasQueueCopies() { return queueCopies != 0; }
    synchronized void removeQueueCopy(boolean removed) {
        if (queueCopies <= 0) throw new IllegalStateException("activation-future-queue-copy");
        queueCopies--;
        if (!removed && !completed && runner == null) pendingRun = true;
        // A completed physical run owns its original finally. A subclass run
        // which leaves its future pending is not proof of harmless idle work.
        if (removed && queueCopies == 0 && runner == null && !pendingRun && internalPhysicalClaims == 0 && owner != null) {
            settleResultOnce();
        }
    }
    // Package-internal final operations cannot dispatch into application code
    // while this future's ownership monitor is held.
    final synchronized void beginInternalPhysicalClaim() {
        if (internalPhysicalClaims == Integer.MAX_VALUE)
            throw new java.util.concurrent.RejectedExecutionException("activation-future-physical-claims");
        internalPhysicalClaims++;
    }
    final synchronized boolean hasInternalPhysicalClaim() { return internalPhysicalClaims != 0; }
    final synchronized void endInternalPhysicalClaim() {
        if (internalPhysicalClaims <= 0) throw new IllegalStateException("activation-future-physical-claim");
        internalPhysicalClaims--;
        if (runner == null && internalPhysicalClaims == 0 && owner != null
                && (completed || queueCopies == 0 && !pendingRun)) {
            settleResultOnce();
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
        synchronized (this) {
            if (completed) return false;
            cancelled = completed = true;
            if (interrupt && runner != null) runner.interrupt();
            if (runner == null) callable = null;
            notifyAll();
            releaseIfPhysicalComplete();
        }
        done();
        return true;
    }
    @Override public synchronized boolean isCancelled() { return cancelled; }
    @Override public synchronized boolean isDone() { return completed; }
    @Override public void run() {
        synchronized (this) {
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
            synchronized (this) { runner = null; callable = null; releaseIfPhysicalComplete(); }
        }
    }
    /** A recurring owner stays pending until a later completion or cancellation. */
    protected boolean runAndReset() {
        synchronized (this) {
            if (completed || runner != null) return false;
            accept();
            runner = Thread.currentThread();
        }
        boolean ran = false;
        try {
            try { callable.call(); ran = true; }
            catch (Throwable error) { setException(error); }
        } finally {
            synchronized (this) { runner = null; if (completed) callable = null; releaseIfPhysicalComplete(); }
        }
        synchronized (this) { return ran && !completed; }
    }
    protected void set(V result) {
        synchronized (this) {
            if (completed) return;
            value = result;
            completed = true;
            notifyAll();
            releaseIfPhysicalComplete();
        }
        done();
    }
    protected void setException(Throwable error) {
        Objects.requireNonNull(error);
        synchronized (this) {
            if (completed) return;
            failure = error;
            completed = true;
            notifyAll();
            releaseIfPhysicalComplete();
        }
        done();
    }
    protected void done() { }
    @Override public V get() throws InterruptedException, ExecutionException {
        synchronized (this) {
            if (!completed) {
                if (Thread.interrupted()) throw new InterruptedException();
                while (!completed) wait();
            }
            return report();
        }
    }
    @Override public V get(long timeout, TimeUnit unit) throws InterruptedException, ExecutionException, TimeoutException {
        long nanos = Objects.requireNonNull(unit).toNanos(timeout);
        long started = System.nanoTime();
        synchronized (this) {
            if (!completed) {
                if (Thread.interrupted()) throw new InterruptedException();
                if (nanos <= 0) throw new TimeoutException();
                while (!completed) {
                    long remaining = nanos - (System.nanoTime() - started);
                    if (remaining <= 0) throw new TimeoutException();
                    wait(remaining / 1_000_000, (int)(remaining % 1_000_000));
                }
            }
            return report();
        }
    }
    private V report() throws ExecutionException {
        if (cancelled) throw new CancellationException();
        if (failure != null) throw new ExecutionException(failure);
        return value;
    }

    @Override public synchronized V resultNow() {
        if (!completed || cancelled || failure != null) throw new IllegalStateException();
        return value;
    }
    @Override public synchronized Throwable exceptionNow() {
        if (!completed || cancelled || failure == null) throw new IllegalStateException();
        return failure;
    }
    @Override public synchronized java.util.concurrent.Future.State state() {
        if (!completed) return java.util.concurrent.Future.State.RUNNING;
        if (cancelled) return java.util.concurrent.Future.State.CANCELLED;
        return failure == null ? java.util.concurrent.Future.State.SUCCESS : java.util.concurrent.Future.State.FAILED;
    }
}
