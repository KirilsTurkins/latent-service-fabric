package dev.latent.guest.runtime.concurrent;
public final class ScheduledReadyFakeClock {
    public static volatile long now;
    public static volatile boolean failNext;
    public static void armAfterDequeue() { failNext=true; }
    public static long nanoTime() {
        if (failNext) { failNext = false; throw new IllegalStateException("synthetic-clock-failure"); }
        return now;
    }
}
