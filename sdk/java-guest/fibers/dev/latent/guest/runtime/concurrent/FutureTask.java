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

    public FutureTask(Callable<V> callable) { this.callable = Objects.requireNonNull(callable); }
    public FutureTask(Runnable runnable, V result) {
        Objects.requireNonNull(runnable);
        this.callable = () -> { runnable.run(); return result; };
    }
    synchronized boolean accept() {
        if (completed || owner != null) return false;
        owner = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.Result);
        return true;
    }
    synchronized void rejectAcceptance() {
        if (runner == null && owner != null) { owner.close(); owner = null; }
    }
    private void releaseIfPhysicalComplete() {
        if (runner == null && completed && owner != null) { owner.close(); owner = null; }
    }
    @Override public boolean cancel(boolean interrupt) {
        synchronized (this) {
            if (completed) return false;
            cancelled = completed = true;
            if (interrupt && runner != null) runner.interrupt();
            if (runner == null) callable = null;
            releaseIfPhysicalComplete();
            notifyAll();
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
            releaseIfPhysicalComplete();
            notifyAll();
        }
        done();
    }
    protected void setException(Throwable error) {
        Objects.requireNonNull(error);
        synchronized (this) {
            if (completed) return;
            failure = error;
            completed = true;
            releaseIfPhysicalComplete();
            notifyAll();
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
