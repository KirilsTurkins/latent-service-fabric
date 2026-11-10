package dev.latent.guest.runtime;

/** Compile-only JDK reference declarations; the reference never runs mode 8. */
public final class Activation {
    public static long monotonicMillis() { throw new AssertionError("guest-only timer probe"); }
    public static Lease timer(long deadline) { throw new AssertionError("guest-only timer probe"); }
    public static final class Lease implements AutoCloseable {
        @Override public void close() { throw new AssertionError("guest-only timer probe"); }
    }
}
