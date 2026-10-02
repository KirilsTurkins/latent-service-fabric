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

    public static void ownedSleep(long millis) throws InterruptedException {
        if (millis < 0) throw new IllegalArgumentException();
        if (Thread.interrupted()) throw new InterruptedException();
        // Lease.close can suspend in the typed capability bridge. Keep it in
        // the actual Java wait frame, resumed by the maintained callback, rather
        // than invoking it from an EventQueue callback outside that frame.
        try (Activation.Lease wait = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.Wait);
             Activation.Lease timer = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.Timer)) {
            rawSleep(millis);
        }
    }

    public static void ownedWait(Object object, long millis, int nanos) throws InterruptedException {
        validateWait(millis, nanos);
        try (Activation.Lease wait = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.Wait);
             Activation.Lease timer = millis != 0 || nanos != 0
                 ? Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.Timer) : null) {
            // The original notify/timeout/interrupt callback reacquires the
            // monitor before this frame resumes and releases its owned leases.
            rawWait(object, millis, nanos);
        }
    }

    public static void rawSleep(long millis) throws InterruptedException {
        throw new IllegalStateException("activation-sleep-compiler-hook-required");
    }

    public static void rawWait(Object object, long millis, int nanos) throws InterruptedException {
        throw new IllegalStateException("activation-wait-compiler-hook-required");
    }
}
