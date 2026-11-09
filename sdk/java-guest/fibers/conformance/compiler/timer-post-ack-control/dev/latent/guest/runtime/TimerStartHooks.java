package dev.latent.guest.runtime;
/** Injected only into a copied Activation source for the host-ledger control. */
public final class TimerStartHooks {
    public static String trigger = "";
    public static Runnable reentryAction, lookupAction, refusalAction;
    private static void run(String where) {
        if (where.equals(trigger) && reentryAction != null) { Runnable action=reentryAction;reentryAction=null;action.run(); }
    }
    public static void allocation() { run("allocation"); }
    public static void clock() { run("clock"); }
    public static void list() { run("list"); }
    public static void refusal() { if (refusalAction != null) { Runnable action=refusalAction;refusalAction=null;action.run(); } }
    public static void lookup() { if (lookupAction != null) { Runnable action=lookupAction;lookupAction=null;action.run(); } }
}
