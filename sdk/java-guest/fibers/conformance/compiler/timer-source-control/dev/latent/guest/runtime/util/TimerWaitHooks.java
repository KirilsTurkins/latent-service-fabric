package dev.latent.guest.runtime.util;

import dev.latent.guest.runtime.Monitors;

/** Host-only projection of TeaVM's maintained Object.wait continuation hook. */
public final class TimerWaitHooks {
    private TimerWaitHooks() { }
    public static void waitFor(Object monitor, long millis) throws InterruptedException {
        Monitors.ownedWait(monitor, millis, 0);
    }
}
