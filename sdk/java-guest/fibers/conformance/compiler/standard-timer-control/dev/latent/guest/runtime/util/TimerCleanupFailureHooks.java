package dev.latent.guest.runtime.util;

import dev.latent.guest.runtime.Activation;

/** Host-only projection of a failure entering the callback-finally monitor. */
public final class TimerCleanupFailureHooks {
    public static final IllegalStateException REPLACEMENT = new IllegalStateException("monitor-reentry-failed");
    public static volatile boolean fencedBeforeCleanup;
    private TimerCleanupFailureHooks() { }
    public static void callbackFinally() { throw REPLACEMENT; }
    public static void beforeWorkerCleanup() { fencedBeforeCleanup = Activation.poisoned(); }
}
