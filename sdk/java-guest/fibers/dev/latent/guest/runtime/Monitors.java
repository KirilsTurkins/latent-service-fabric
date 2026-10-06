package dev.latent.guest.runtime;

import org.teavm.interop.AsyncCallback;

/** Maintained monitor continuation hooks installed only by the owned compiler. */
public final class Monitors {
    private Monitors() { }

    public static void beforeWait() throws InterruptedException {
        if (Thread.interrupted()) throw new InterruptedException();
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
}
