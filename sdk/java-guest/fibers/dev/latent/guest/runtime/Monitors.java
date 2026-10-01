package dev.latent.guest.runtime;

import dev.latent.generated.Bindings;
import org.teavm.interop.AsyncCallback;

/** Maintained monitor continuation hooks installed only by the owned compiler. */
public final class Monitors {
    private Monitors() { }

    public static void beforeWait() throws InterruptedException {
        if (Thread.interrupted()) throw new InterruptedException();
    }

    public static void validateWait(long millis, int nanos) {
        if (millis < 0 || nanos < 0 || nanos > 999999) throw new IllegalArgumentException();
    }

    public static void interruptedWait(Object object, int count, Thread thread, AsyncCallback<Void> callback) {
        restore(thread);
        // Object.wait must regain every level of the original reentrant lock
        // before its InterruptedException becomes visible to application code.
        reacquire(object, count, new AsyncCallback<Void>() {
            @Override public void complete(Void unused) {
                Thread.interrupted();
                callback.error(new InterruptedException());
            }
            @Override public void error(Throwable error) { callback.error(error); }
        });
    }

    public static void restore(Thread thread) {
        throw new IllegalStateException("activation-monitor-compiler-hook-required");
    }

    public static void reacquire(Object object, int count, AsyncCallback<Void> callback) {
        throw new IllegalStateException("activation-monitor-compiler-hook-required");
    }

    public static void sleepNanos(long millis, int nanos) throws InterruptedException {
        validateWait(millis, nanos);
        if (nanos > 0 && millis != Long.MAX_VALUE) millis++;
        Thread.sleep(millis);
    }

    public static long absoluteSleepDeadline(long now, long millis) {
        if (millis < 0) throw new IllegalArgumentException();
        // The original event queue represents absolute instants as signed
        // milliseconds. Saturate at that boundary instead of wrapping into an
        // already elapsed instant; the original activation deadline still wins.
        return now > Long.MAX_VALUE - millis ? Long.MAX_VALUE : now + millis;
    }

    public static long absoluteWaitDeadline(long now, long millis, int nanos) {
        validateWait(millis, nanos);
        if (nanos > 0 && millis != Long.MAX_VALUE) millis++;
        return absoluteSleepDeadline(now, millis);
    }

    public static void interruptedSleep(Thread thread, AsyncCallback<Void> callback) {
        restore(thread);
        Thread.interrupted();
        callback.error(new InterruptedException());
    }

    private static final class OwnedCompletion implements AsyncCallback<Void> {
        private final Activation.Lease wait;
        private final Activation.Lease timer;
        private final AsyncCallback<Void> callback;
        private boolean settled;
        OwnedCompletion(Activation.Lease wait, Activation.Lease timer, AsyncCallback<Void> callback) {
            this.wait = wait;
            this.timer = timer;
            this.callback = callback;
        }
        private void settle() {
            if (settled) throw new IllegalStateException("duplicate-owned-wait-completion");
            settled = true;
            try { if (timer != null) timer.close(); } finally { wait.close(); }
        }
        @Override public void complete(Void unused) { settle(); callback.complete(null); }
        @Override public void error(Throwable error) { settle(); callback.error(error); }
    }

    private static OwnedCompletion accept(boolean timed, AsyncCallback<Void> callback) {
        Activation.Lease wait = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.Wait);
        Activation.Lease timer = null;
        try {
            if (timed) timer = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.Timer);
            return new OwnedCompletion(wait, timer, callback);
        } catch (Throwable error) {
            try { if (timer != null) timer.close(); } finally { wait.close(); }
            throw error;
        }
    }

    public static void ownedSleep(long millis, AsyncCallback<Void> callback) {
        if (millis < 0) { callback.error(new IllegalArgumentException()); return; }
        if (Thread.interrupted()) { callback.error(new InterruptedException()); return; }
        OwnedCompletion completion;
        try { completion = accept(true, callback); }
        catch (Throwable error) { callback.error(error); return; }
        try { rawSleep(millis, completion); }
        catch (Throwable error) { completion.error(error); }
    }

    public static void ownedWait(Object object, long millis, int nanos, AsyncCallback<Void> callback) {
        OwnedCompletion completion;
        try { validateWait(millis, nanos); completion = accept(millis != 0 || nanos != 0, callback); }
        catch (Throwable error) { callback.error(error); return; }
        try { rawWait(object, millis, nanos, completion); }
        catch (Throwable error) { completion.error(error); }
    }

    public static void rawSleep(long millis, AsyncCallback<Void> callback) {
        throw new IllegalStateException("activation-sleep-compiler-hook-required");
    }

    public static void rawWait(Object object, long millis, int nanos, AsyncCallback<Void> callback) {
        throw new IllegalStateException("activation-wait-compiler-hook-required");
    }
}
