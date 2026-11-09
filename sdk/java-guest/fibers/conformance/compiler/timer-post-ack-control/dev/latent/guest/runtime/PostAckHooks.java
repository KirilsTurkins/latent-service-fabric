package dev.latent.guest.runtime;
/** Test-only failure hooks for the copied source projection. */
public final class PostAckHooks {
    public static RuntimeException failure;
    public static OutOfMemoryError listFailure;
    public static boolean afterList, beforeAllocation;
    public static Runnable afterListAction;
    public static void beforeAllocation() { if (beforeAllocation && failure != null) throw failure; }
    public static void afterAccept() { if (!beforeAllocation && !afterList && failure != null) throw failure; }
    public static void beforeList() { if (listFailure != null) throw listFailure; }
    public static void afterList() {
        if (afterListAction != null) { Runnable action=afterListAction; afterListAction=null; action.run(); }
        if (afterList && failure != null) throw failure;
    }
}
