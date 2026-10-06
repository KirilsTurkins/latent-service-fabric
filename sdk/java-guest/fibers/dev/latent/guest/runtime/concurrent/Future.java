package dev.latent.guest.runtime.concurrent;
import java.util.concurrent.CancellationException;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
public interface Future<V> {
    boolean cancel(boolean mayInterruptIfRunning);
    boolean isCancelled();
    boolean isDone();
    V get() throws InterruptedException, ExecutionException;
    V get(long timeout, TimeUnit unit) throws InterruptedException, ExecutionException, TimeoutException;
    enum State { RUNNING, SUCCESS, FAILED, CANCELLED }
    default V resultNow() {
        if (!isDone() || isCancelled()) throw new IllegalStateException();
        try { return get(); }
        catch (InterruptedException error) { Thread.currentThread().interrupt(); throw new IllegalStateException(error); }
        catch (ExecutionException error) { throw new IllegalStateException(error.getCause()); }
    }
    default Throwable exceptionNow() {
        if (!isDone() || isCancelled()) throw new IllegalStateException();
        try { get(); throw new IllegalStateException(); }
        catch (InterruptedException error) { Thread.currentThread().interrupt(); throw new IllegalStateException(error); }
        catch (ExecutionException error) { return error.getCause(); }
    }
    default State state() {
        if (!isDone()) return State.RUNNING;
        if (isCancelled()) return State.CANCELLED;
        try { get(); return State.SUCCESS; }
        catch (CancellationException error) { return State.CANCELLED; }
        catch (ExecutionException error) { return State.FAILED; }
        catch (InterruptedException error) { Thread.currentThread().interrupt(); throw new IllegalStateException(error); }
    }
}
