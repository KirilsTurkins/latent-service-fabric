package dev.latent.guest.runtime;
/** Test-only reentry and failure hooks for the copied source projection. */
public final class PostAckHooks {
    public static RuntimeException failure, fenceFailure;
    public static boolean afterList;
    public static void afterAccept() { if (!afterList && failure != null) throw failure; }
    public static void afterList() { if (afterList && failure != null) throw failure; }
    public static void fence() { if (fenceFailure != null) throw fenceFailure; }
}
