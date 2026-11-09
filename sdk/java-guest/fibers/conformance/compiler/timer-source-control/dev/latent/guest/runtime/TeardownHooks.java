package dev.latent.guest.runtime;

/** Host-only hooks inserted into a copied Activation source for causal controls. */
public final class TeardownHooks {
    public static Runnable action;
    public static Runnable beforeStopAction;
    public static Runnable beforeAdmissionAction;

    public static void afterSample() {
        if (action != null) action.run();
    }

    public static void beforeStopPublication() {
        if (beforeStopAction != null) beforeStopAction.run();
    }

    public static void beforeAdmission() {
        if (beforeAdmissionAction != null) beforeAdmissionAction.run();
    }
}
