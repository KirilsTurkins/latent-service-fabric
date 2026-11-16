package dev.latent.guest.runtime.concurrent;
public final class ScheduledCompareFakeClock {
    public static volatile long now;
    public static volatile long step;
    public static synchronized long nanoTime() {
        long result = now;
        now += step;
        return result;
    }
}
