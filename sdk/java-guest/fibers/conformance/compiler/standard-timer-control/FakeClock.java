package dev.latent.guest.runtime.util;
public final class FakeClock {
    private static int calls;
    public static synchronized long currentTimeMillis() { calls++; return 1_000L; }
    public static synchronized void reset() { calls = 0; }
    public static synchronized int calls() { return calls; }
}
